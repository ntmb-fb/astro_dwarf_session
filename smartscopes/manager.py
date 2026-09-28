"""Process-wide registry of live non-Dwarf devices (the counterpart of
dwarf_python_api's DwarfManager), plus the background program scheduler.
"""
from __future__ import annotations

import logging
import os
import threading

from smartscopes import store
from smartscopes.base import ScopeDriver, ScopeEntry
from smartscopes.registry import get_driver_class
from smartscopes.runner import RunState, run_program_file

log = logging.getLogger("smartscopes")


class ScopeDevice:
    def __init__(self, entry: ScopeEntry):
        self.entry = entry
        self.driver: ScopeDriver = get_driver_class(entry.protocol)(entry)
        self.run: RunState | None = None
        self.armed = False  # scheduler auto-start, OFF by default like the Dwarf side
        self.op_lock = threading.Lock()  # one blocking operation at a time

    @property
    def uid(self) -> str:
        return self.entry.uid

    @property
    def is_running(self) -> bool:
        return self.run is not None and not self.run.finished

    def site(self) -> tuple[float, float] | None:
        name = self.entry.options.get("site")
        if not name:
            return None
        from site_registry import get_site_entry  # upstream module

        site = get_site_entry(name)
        if site and site.latitude is not None and site.longitude is not None:
            return site.latitude, site.longitude
        return None

    def start_program(self, filepath: str) -> RunState:
        """Starts a program file in a background thread."""
        if self.is_running:
            raise RuntimeError("A program is already running on this telescope")
        if not self.op_lock.acquire(blocking=False):
            raise RuntimeError("Another operation is in progress on this telescope")
        state = RunState(program_name=os.path.splitext(os.path.basename(filepath))[0])
        self.run = state

        def worker() -> None:
            try:
                run_program_file(self.driver, filepath, store.session_dirs(self.uid, create=True),
                                 state, site=self.site())
            finally:
                self.op_lock.release()

        threading.Thread(target=worker, name=f"program-{self.uid}", daemon=True).start()
        return state

    def request_stop(self) -> None:
        if self.run is not None:
            self.run.stop_event.set()


class ScopeManager:
    def __init__(self) -> None:
        self._devices: dict[str, ScopeDevice] = {}

    def load(self) -> None:
        for entry in store.load_entries():
            try:
                self._devices[entry.uid] = ScopeDevice(entry)
            except KeyError as exc:  # driver removed/renamed
                log.error("Skipping telescope %s: %s", entry.name, exc)

    def all(self) -> list[ScopeDevice]:
        return list(self._devices.values())

    def get(self, uid: str) -> ScopeDevice | None:
        return self._devices.get(uid)

    def add(self, entry: ScopeEntry) -> ScopeDevice:
        store.save_entry(entry)
        store.session_dirs(entry.uid, create=True)
        device = ScopeDevice(entry)
        self._devices[entry.uid] = device
        return device

    def update(self, entry: ScopeEntry) -> ScopeDevice:
        """Replaces the device (e.g. new IP/key); drops its live connection."""
        old = self._devices.get(entry.uid)
        if old is not None:
            if old.is_running:
                raise RuntimeError("Stop the running program before editing this telescope")
            old.driver.disconnect()
        store.save_entry(entry)
        device = ScopeDevice(entry)
        self._devices[entry.uid] = device
        return device

    def remove(self, uid: str) -> None:
        device = self._devices.pop(uid, None)
        if device is not None:
            device.request_stop()
            device.driver.disconnect()
        store.delete_entry(uid)


_manager: ScopeManager | None = None


def get_scope_manager() -> ScopeManager:
    global _manager
    if _manager is None:
        _manager = ScopeManager()
        _manager.load()
    return _manager


def scheduler_tick() -> None:
    """Starts the earliest due ToDo program on every armed, idle device.
    Reuses the Dwarf scheduler's own due-file logic so the ToDo file
    format (id_command date/time) stays identical."""
    from components.scheduler_loop import _next_due_file  # upstream helper

    for device in get_scope_manager().all():
        if not device.armed or device.is_running:
            continue
        filepath = _next_due_file(store.session_dirs(device.uid)["TODO_DIR"])
        if filepath is None:
            continue
        try:
            device.start_program(filepath)
        except RuntimeError as exc:
            log.info("Scheduler: %s not started yet (%s)", device.entry.name, exc)
