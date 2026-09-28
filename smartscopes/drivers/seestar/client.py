"""Low-level JSON-RPC client for ZWO Seestar telescopes (S50/S30).

Wire format (TCP port 4700): one JSON object per line, "\\r\\n"
terminated, in both directions.

  -> {"id": 12, "method": "get_device_state", "params": ["verify"]}
  <- {"jsonrpc": "2.0", "method": "get_device_state", "id": 12, "code": 0, "result": {...}}
  <- {"Event": "Stack", "state": "frame_complete", "stacked_frame": 7, ...}

Replies carry the request "id"; unsolicited "Event" messages carry the
device's live state (goto/autofocus/stacking progress, battery...).

Two firmware quirks handled here:
  * Authentication (firmware 7.18+): the device only obeys a client that
    signed its challenge - get_verify_str -> SHA1withRSA signature ->
    verify_client. The private key ships inside ZWO's own app and must
    be extracted by the user; we never bundle it. Without a key, older
    firmware works as-is; newer firmware silently ignores commands.
  * "verify" parameter: firmware newer than 2582 expects a "verify"
    marker in every command's params (appended to list params, or a
    "verify": true key in dict params below 2706).

Protocol knowledge from the community project seestar_alp
(github.com/smart-underworld/seestar_alp); this is an independent
implementation.
"""
from __future__ import annotations

import base64
import itertools
import json
import logging
import socket
import threading
import time
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("smartscopes.seestar")

DEFAULT_PORT = 4700
_AUTH_METHODS = frozenset({"get_verify_str", "verify_client", "pi_is_verified"})
_HEARTBEAT_S = 3.0


class SeestarError(RuntimeError):
    def __init__(self, method: str, reply: dict | None, message: str | None = None):
        self.method = method
        self.reply = reply
        detail = message or (reply.get("error") if reply else None) or reply
        super().__init__(f"{method}: {detail}")


class SeestarTimeout(SeestarError):
    pass


def inject_verify(method: str, params: Any, firmware_ver_int: int) -> Any:
    """Returns params with the firmware's "verify" marker added, or
    params unchanged when this firmware/method doesn't want it. The
    sentinel _NO_PARAMS means the command had no params at all."""
    if method in _AUTH_METHODS or not (firmware_ver_int == 0 or firmware_ver_int > 2582):
        return params
    if params is _NO_PARAMS:
        return ["verify"]
    if isinstance(params, dict):
        if firmware_ver_int >= 2706 or "verify" in params:
            return params
        return {**params, "verify": True}
    if isinstance(params, list):
        return params if params and params[-1] == "verify" else [*params, "verify"]
    return [params, "verify"]


_NO_PARAMS = object()


def sign_challenge(challenge: str, pem: bytes) -> str:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    key = serialization.load_pem_private_key(pem, password=None)
    signature = key.sign(challenge.encode("utf-8"), padding.PKCS1v15(), hashes.SHA1())
    return base64.b64encode(signature).decode("ascii")


class _Pending:
    __slots__ = ("done", "reply")

    def __init__(self) -> None:
        self.done = threading.Event()
        self.reply: dict | None = None


class SeestarClient:
    """One TCP connection. Thread-safe: call() may be used from any thread."""

    def __init__(
        self,
        host: str,
        port: int = DEFAULT_PORT,
        *,
        pem_path: str | None = None,
        verify_injection: bool = True,
        connect_timeout: float = 8.0,
        first_reply_timeout: float = 15.0,
    ):
        self.host = host
        self.port = port
        self.pem_path = pem_path
        self.verify_injection = verify_injection
        self.connect_timeout = connect_timeout
        self.first_reply_timeout = first_reply_timeout

        self.firmware_ver_int = 0
        self.authenticated = False
        self.events: dict[str, dict] = {}  # latest message per Event name
        self.equ_coord: tuple[float, float] | None = None

        self._sock: socket.socket | None = None
        self._send_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._pending: dict[int, _Pending] = {}
        self._ids = itertools.count(10000)
        self._listeners: list[Callable[[dict], None]] = []
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    # --- lifecycle ------------------------------------------------------
    @property
    def connected(self) -> bool:
        return self._sock is not None and not self._stop.is_set()

    def connect(self) -> None:
        self.close()
        sock = socket.create_connection((self.host, self.port), timeout=self.connect_timeout)
        sock.settimeout(1.0)  # reader loop wakes up regularly to notice close()
        # A fresh stop event per connection, so a dying reader thread of a
        # previous connection can never close this new one.
        self._stop = threading.Event()
        self._sock = sock
        reader = threading.Thread(target=self._read_loop, args=(sock, self._stop),
                                  name=f"seestar-rx-{self.host}", daemon=True)
        reader.start()
        self._threads = [reader]

        if self.pem_path:
            self.authenticate()

        state = self.call("get_device_state", timeout=self.first_reply_timeout)
        self.firmware_ver_int = int(state.get("device", {}).get("firmware_ver_int") or 0)

        beat = threading.Thread(target=self._heartbeat_loop, args=(self._stop,), name=f"seestar-hb-{self.host}", daemon=True)
        beat.start()
        self._threads.append(beat)

    def close(self) -> None:
        self._stop.set()
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()
        with self._state_lock:
            for pending in self._pending.values():
                pending.done.set()
            self._pending.clear()
        self.authenticated = False

    def add_listener(self, callback: Callable[[dict], None]) -> None:
        self._listeners.append(callback)

    # --- auth ------------------------------------------------------------
    def authenticate(self) -> None:
        pem = Path(self.pem_path).expanduser().read_bytes()
        challenge = self.call("get_verify_str", timeout=12).get("str")
        if not challenge:
            raise SeestarError("get_verify_str", None, "device returned no challenge (busy?)")
        self.call("verify_client", {"sign": sign_challenge(challenge, pem), "data": challenge}, timeout=12)
        self.authenticated = True
        log.info("Seestar %s: authenticated", self.host)

    # --- RPC ---------------------------------------------------------------
    def _message(self, msg_id: int, method: str, params: Any) -> dict:
        message: dict[str, Any] = {"id": msg_id, "method": method}
        if self.verify_injection:
            params = inject_verify(method, params, self.firmware_ver_int)
        if params is not _NO_PARAMS:
            message["params"] = params
        return message

    def send(self, method: str, params: Any = _NO_PARAMS) -> int:
        """Fire-and-forget; returns the request id."""
        msg_id = next(self._ids)
        self._write(self._message(msg_id, method, params))
        return msg_id

    def call(self, method: str, params: Any = _NO_PARAMS, *, timeout: float = 10.0) -> Any:
        """Sends a command and waits for its reply; returns reply["result"]
        (or {} if absent). Raises SeestarError on an error reply."""
        pending = _Pending()
        msg_id = next(self._ids)
        with self._state_lock:
            self._pending[msg_id] = pending
        try:
            self._write(self._message(msg_id, method, params))
            if not pending.done.wait(timeout) or pending.reply is None:
                raise SeestarTimeout(method, None, f"no reply within {timeout:.0f}s"
                                     + ("" if self.authenticated else " (auth key required by this firmware?)"))
        finally:
            with self._state_lock:
                self._pending.pop(msg_id, None)

        reply = pending.reply
        if "error" in reply or reply.get("code", 0) not in (0, None):
            raise SeestarError(method, reply)
        result = reply.get("result")
        return {} if result is None else result

    def _write(self, message: dict) -> None:
        sock = self._sock
        if sock is None:
            raise SeestarError(message["method"], None, "not connected")
        data = (json.dumps(message) + "\r\n").encode("utf-8")
        try:
            with self._send_lock:
                sock.sendall(data)
        except OSError as exc:
            self._on_connection_lost(self._stop, exc)
            raise SeestarError(message["method"], None, f"send failed: {exc}") from exc

    # --- background threads ---------------------------------------------
    def _read_loop(self, sock: socket.socket, stop: threading.Event) -> None:
        buffer = b""
        while not stop.is_set():
            try:
                chunk = sock.recv(65536)
            except socket.timeout:
                continue
            except OSError as exc:
                self._on_connection_lost(stop, exc)
                return
            if not chunk:
                self._on_connection_lost(stop, ConnectionResetError("closed by device"))
                return
            buffer += chunk
            while b"\r\n" in buffer:
                line, buffer = buffer.split(b"\r\n", 1)
                if line.strip():
                    self._dispatch(line)

    def _dispatch(self, line: bytes) -> None:
        try:
            message = json.loads(line)
        except ValueError:
            log.debug("Seestar %s: unparseable line %r", self.host, line[:200])
            return
        if "Event" in message:
            with self._state_lock:
                self.events[message["Event"]] = message
            for callback in self._listeners:
                try:
                    callback(message)
                except Exception:
                    log.exception("Seestar event listener failed")
            return
        if message.get("method") == "scope_get_equ_coord" and isinstance(message.get("result"), dict):
            result = message["result"]
            if "ra" in result and "dec" in result:
                self.equ_coord = (float(result["ra"]), float(result["dec"]))
        with self._state_lock:
            pending = self._pending.get(message.get("id"))
        if pending is not None:
            pending.reply = message
            pending.done.set()

    def _heartbeat_loop(self, stop: threading.Event) -> None:
        # The device drops idle connections; a cheap query keeps it open
        # and doubles as a position update.
        while not stop.wait(_HEARTBEAT_S):
            try:
                self.send("scope_get_equ_coord")
            except SeestarError:
                return

    def _on_connection_lost(self, stop: threading.Event, exc: BaseException) -> None:
        if stop is self._stop and not stop.is_set():
            log.warning("Seestar %s: connection lost (%s)", self.host, exc)
            self.close()

    # --- event helpers -----------------------------------------------------
    def event_state(self, name: str) -> str | None:
        with self._state_lock:
            return (self.events.get(name) or {}).get("state")

    def clear_event(self, name: str) -> None:
        with self._state_lock:
            self.events.pop(name, None)

    def wait_event_state(
        self,
        name: str,
        *,
        timeout: float,
        terminal: frozenset[str] = frozenset({"complete", "fail", "cancel"}),
        interrupted: Callable[[], bool] = lambda: False,
    ) -> dict:
        """Blocks until Event `name` reaches a terminal state; returns
        that event message. Call clear_event(name) *before* issuing the
        command so a stale "complete" from an earlier run doesn't count."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if interrupted():
                raise SeestarError(name, None, "interrupted")
            if not self.connected:
                raise SeestarError(name, None, "connection lost")
            with self._state_lock:
                event = self.events.get(name)
            if event and event.get("state") in terminal:
                return event
            time.sleep(0.5)
        raise SeestarTimeout(name, None, f"did not finish within {timeout:.0f}s")
