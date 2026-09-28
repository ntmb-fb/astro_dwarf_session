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

    items.sort(key=key, reverse=folder not in ("TODO_DIR", "CURRENT_DIR"))
    return items


def describe(program: dict) -> dict:
    """Display fields for a program row: time range, capture settings,
    TonightPlan info (if it came from there) and the run outcome."""
    from components.scheduler_loop import _extract_end_time  # upstream end-time rule

    cmd = program.get("command", {})
    idc = cmd.get("id_command", {})
    date, time_ = idc.get("date", ""), idc.get("time", "")
    try:
        start = datetime.strptime(f"{date} {time_}", "%Y-%m-%d %H:%M:%S")
    except ValueError:
        start = None
    end = _extract_end_time(cmd, start) if start else None
    when = f"{date} {time_[:5]}" + (f"–{end[11:16]}" if end else "")

    cam = cmd.get("setup_camera") or {}
    settings = []
    if cam.get("do_action"):
        count = int(cam.get("count") or 0)
        try:
            exposure = f"{float(cam.get('exposure')):g}s"
        except (TypeError, ValueError):
            exposure = f"{cam.get('exposure')}s"
        settings.append(exposure + (f" × {count}" if count else " until stop time"))
        if str(cam.get("gain", "")).strip():
            settings.append(f"gain {cam['gain']}")
        if cam.get("lp_filter"):
            settings.append("LP filter")
    if (cmd.get("auto_focus") or {}).get("do_action"):
        settings.append("autofocus")
    goto = cmd.get("goto_manual") or {}
    if goto.get("do_action") and goto.get("ra_coord") not in ("", None):
        try:
            settings.append(f"RA {float(goto['ra_coord']):.3f}h Dec {float(goto['dec_coord']):+.2f}°")
        except (TypeError, ValueError):
            settings.append(f"RA {goto['ra_coord']} Dec {goto['dec_coord']}")

    plan = idc.get("tonightplan") or {}
    plan_bits = []
    if plan:
        plan_bits = [plan.get("visual_impact", ""),
                     f"peak {plan['peak_alt']:.0f}° at {plan['peak_time']}" if plan.get("peak_alt") is not None else "",
                     plan.get("fit", ""), f"smart scope: {plan['smart_scope']}" if plan.get("smart_scope") else "",
                     f"suggested {plan['imaging_time']}" if plan.get("imaging_time") else "",
                     "some Moon" if plan.get("moon_status") == "ok" else ""]

    outcome = idc.get("message") or ""
    if idc.get("shots_stacked") is not None:
        outcome = f"{outcome} · {idc['shots_stacked']} frames stacked".strip(" ·")

    return {
        "when": when,
        "title": idc.get("description") or "",
        "settings": " · ".join(settings),
        "plan": " · ".join(b for b in plan_bits if b),
        "plan_url": plan.get("url"),
        "outcome": outcome,
    }
