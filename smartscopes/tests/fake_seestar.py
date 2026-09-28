"""Minimal in-process Seestar emulator for tests: speaks the line-based
JSON-RPC protocol, checks the auth signature, and plays goto/autofocus/
stacking events."""
from __future__ import annotations

import base64
import json
import socket
import threading
import time


class FakeSeestar:
    def __init__(self, *, public_key=None, firmware_ver_int: int = 2706, frame_interval: float = 0.2):
        self.public_key = public_key          # set -> commands require auth
        self.firmware_ver_int = firmware_ver_int
        self.frame_interval = frame_interval
        self.received: list[dict] = []
        self.verified = False
        self._challenge = "challenge-1234"
        self._server = socket.socket()
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen()
        self.port = self._server.getsockname()[1]
        self._conn: socket.socket | None = None
        self._stacking = threading.Event()
        threading.Thread(target=self._accept, daemon=True).start()

    def close(self) -> None:
        self._stacking.clear()
        self._server.close()
        if self._conn:
            self._conn.close()

    def methods(self) -> list[str]:
        return [m["method"] for m in self.received]

    # --- wire ------------------------------------------------------------
    def _send(self, obj: dict) -> None:
        if self._conn:
            try:
                self._conn.sendall((json.dumps(obj) + "\r\n").encode())
            except OSError:
                pass

    def _accept(self) -> None:
        while True:  # one client at a time, but accept reconnects
            try:
                conn, _ = self._server.accept()
            except OSError:
                return
            self._conn = conn
            self.verified = False
            self._serve(conn)

    def _serve(self, conn: socket.socket) -> None:
        buf = b""
        while True:
            try:
                chunk = conn.recv(65536)
            except OSError:
                return
            if not chunk:
                return
            buf += chunk
            while b"\r\n" in buf:
                line, buf = buf.split(b"\r\n", 1)
                self._handle(json.loads(line))

    def _reply(self, msg: dict, result=0, code: int = 0, error: str | None = None) -> None:
        reply = {"jsonrpc": "2.0", "method": msg["method"], "id": msg["id"], "code": code, "result": result}
        if error:
            reply["error"] = error
        self._send(reply)

    def _event(self, name: str, **fields) -> None:
        self._send({"Event": name, **fields})

    # --- behaviour -------------------------------------------------------
    def _handle(self, msg: dict) -> None:
        self.received.append(msg)
        method = msg["method"]
        if method == "get_verify_str":
            return self._reply(msg, {"str": self._challenge})
        if method == "verify_client":
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.asymmetric import padding
            params = msg["params"]
            try:
                self.public_key.verify(base64.b64decode(params["sign"]), params["data"].encode(),
                                       padding.PKCS1v15(), hashes.SHA1())
                self.verified = params["data"] == self._challenge
            except Exception:
                self.verified = False
            return self._reply(msg, 0, code=0 if self.verified else 103,
                               error=None if self.verified else "verify fail")
        if self.public_key is not None and not self.verified:
            return  # real firmware silently ignores unauthenticated commands

        if method == "get_device_state":
            return self._reply(msg, {
                "device": {"firmware_ver_int": self.firmware_ver_int, "firmware_ver_string": "fake"},
                "pi_status": {"battery_capacity": 87, "temp": 21.5, "charger_status": "Discharging"},
                "storage": {"storage_volume": [{"freeMB": 20480}]},
            })
        if method == "scope_get_equ_coord":
            return self._reply(msg, {"ra": 5.58, "dec": -5.39})
        if method == "iscope_start_view":
            self._reply(msg)
            if "target_ra_dec" in msg["params"]:
                threading.Thread(target=self._play, args=("AutoGoto",), daemon=True).start()
            return
        if method == "start_auto_focuse":
            self._reply(msg)
            threading.Thread(target=self._play, args=("AutoFocus",), daemon=True).start()
            return
        if method == "iscope_start_stack":
            self._reply(msg)
            self._stacking.set()
            threading.Thread(target=self._stack, daemon=True).start()
            return
        if method == "iscope_stop_view":
            if msg["params"].get("stage") == "Stack" and self._stacking.is_set():
                self._stacking.clear()
                self._event("Stack", state="cancel")
            return self._reply(msg)
        self._reply(msg)  # set_setting, set_control_value, pi_set_time, ...

    def _play(self, name: str) -> None:
        self._event(name, state="working")
        time.sleep(0.2)
        self._event(name, state="complete")

    def _stack(self) -> None:
        self._event("Stack", state="start")
        frames = 0
        while self._stacking.is_set():
            time.sleep(self.frame_interval)
            frames += 1
            self._event("Stack", state="frame_complete", stacked_frame=frames, dropped_frame=0)
