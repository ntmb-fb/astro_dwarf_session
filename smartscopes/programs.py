"""Create/list program files for a non-Dwarf device, in the upstream
program format (built from the Dwarf program editor's own template, so
new upstream fields are picked up automatically)."""
from __future__ import annotations

import json
import os
from datetime import datetime

from smartscopes import store


def new_program(
    *,
    target: str,
    ra,
    dec,
    start: datetime,
    exposure_s: float,
    gain: int | None,
    count: int,
    end_time: str = "",
    auto_focus: bool = True,
    lp_filter: bool = False,
    max_retries: int = 3,
) -> dict:
    from components.program_editor import _blank_program  # upstream template

    program = _blank_program()
    cmd = program["command"]
    cmd["id_command"].update(
        description=target,
        date=start.strftime("%Y-%m-%d"),
        time=start.strftime("%H:%M:%S"),
        max_retries=max_retries,
    )
    cmd["goto_manual"].update(do_action=True, target=target, ra_coord=ra, dec_coord=dec, wait_after=0)
    cmd["auto_focus"].update(do_action=auto_focus, wait_before=0, wait_after=0)
    cmd["setup_camera"].update(
        do_action=True,
        exposure=str(exposure_s),
        gain="" if gain is None else str(gain),
        count=str(count),
        end_time=end_time,
        wait_after=0,
        lp_filter=lp_filter,  # Seestar-specific key; ignored by the Dwarf runner
    )
    cmd["setup_wide_camera"]["do_action"] = False
    return program


def save_to_todo(uid: str, program: dict) -> str:
    from components.program_editor import _filename_for  # upstream naming

    dirs = store.session_dirs(uid, create=True)
    path = os.path.join(dirs["TODO_DIR"], _filename_for(program))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(program, f, indent=4)
    return path


def list_programs(uid: str, folder: str) -> list[tuple[str, dict]]:
    """(path, program) for every .json in TODO_DIR/DONE_DIR/ERROR_DIR...,
    newest schedule first for Done/Error, soonest first for ToDo."""
    directory = store.session_dirs(uid)[folder]
    if not os.path.isdir(directory):
        return []
    items = []
    for name in os.listdir(directory):
        if not name.endswith(".json"):
            continue
        path = os.path.join(directory, name)
        try:
            with open(path, encoding="utf-8") as f:
                items.append((path, json.load(f)))
        except (OSError, ValueError):
            continue

    def key(item):
        idc = item[1].get("command", {}).get("id_command", {})
        return f"{idc.get('date', '')} {idc.get('time', '')}"

    items.sort(key=key, reverse=folder != "TODO_DIR")
    return items
