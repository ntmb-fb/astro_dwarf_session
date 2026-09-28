"""Persistence of non-Dwarf devices and their per-device session folders.

Devices live in Devices_Sessions/smartscopes.json (Devices_Sessions/ is
already git-ignored upstream). Program files use the exact same
ToDo/Current/Done/Error/Results layout as the Dwarf side
(components/session_dirs.py), under Devices_Sessions/<uid>/Astro_Sessions.
"""
from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import asdict

from smartscopes.base import ScopeEntry

_BASE_DIR = os.path.abspath("Devices_Sessions")
_STORE_PATH = os.path.join(_BASE_DIR, "smartscopes.json")
_lock = threading.Lock()


def _read() -> list[ScopeEntry]:
    if not os.path.exists(_STORE_PATH):
        return []
    with open(_STORE_PATH, encoding="utf-8") as f:
        return [ScopeEntry(**raw) for raw in json.load(f)]


def _write(entries: list[ScopeEntry]) -> None:
    os.makedirs(_BASE_DIR, exist_ok=True)
    tmp = _STORE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump([asdict(e) for e in entries], f, indent=2)
    os.replace(tmp, _STORE_PATH)


def load_entries() -> list[ScopeEntry]:
    with _lock:
        return _read()


def make_uid(protocol: str, name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "scope"
    existing = {e.uid for e in load_entries()}
    uid, n = f"{protocol}-{slug}", 2
    while uid in existing:
        uid, n = f"{protocol}-{slug}-{n}", n + 1
    return uid


def save_entry(entry: ScopeEntry) -> None:
    """Insert or replace (by uid)."""
    with _lock:
        entries = [e for e in _read() if e.uid != entry.uid]
        entries.append(entry)
        _write(entries)


def delete_entry(uid: str) -> None:
    with _lock:
        _write([e for e in _read() if e.uid != uid])


def session_dirs(uid: str, *, create: bool = False) -> dict[str, str]:
    sessions_dir = os.path.join(_BASE_DIR, uid, "Astro_Sessions")
    dirs = {
        "SESSIONS_DIR": sessions_dir,
        "TODO_DIR": os.path.join(sessions_dir, "ToDo"),
        "CURRENT_DIR": os.path.join(sessions_dir, "Current"),
        "DONE_DIR": os.path.join(sessions_dir, "Done"),
        "ERROR_DIR": os.path.join(sessions_dir, "Error"),
        "RESULTS_DIR": os.path.join(sessions_dir, "Results"),
    }
    if create:
        for path in dirs.values():
            os.makedirs(path, exist_ok=True)
    return dirs
