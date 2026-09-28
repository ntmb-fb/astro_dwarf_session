"""Pages for non-Dwarf telescopes:
  /scopes/add          add a telescope (any registered driver/model)
  /scopes/{uid}/edit   edit or remove it
  /scopes/{uid}        live control, program queue, scheduler, run log
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

from nicegui import run, ui

from components.pwa import add_pwa_head_tags
from components.theme import apply_theme, theme_toggle_button
from smartscopes import store
from smartscopes.base import Capability as C, CaptureSettings, DriverError, ScopeEntry
from smartscopes.coords import parse_dec_deg, parse_ra_hours
from smartscopes.manager import ScopeDevice, get_scope_manager
from smartscopes.programs import list_programs, new_program, save_to_todo
from smartscopes.registry import all_models, get_driver_class


def _header(title: str, back: str = "/") -> None:
    add_pwa_head_tags()
    apply_theme()
    with ui.row().classes("items-center w-full"):
        ui.button(icon="arrow_back", on_click=lambda: ui.navigate.to(back)).props("flat round")
        ui.label(title).classes("text-xl grow")
        theme_toggle_button()


def _site_names() -> list[str]:
    from site_registry import list_site_entries  # upstream module

    return [s.name for s in list_site_entries()]


# --- add / edit -----------------------------------------------------------------

def _entry_form(existing: ScopeEntry | None) -> None:
    models = {f"{drv.protocol}:{m.model_id}": f"{m.display_name}" for drv, m in all_models()}
    key0 = f"{existing.protocol}:{existing.model_id}" if existing else next(iter(models))

    model_select = ui.select(models, value=key0, label="Model").classes("w-full")
    if existing:
        model_select.disable()
    name = ui.input("Name", value=existing.name if existing else "").classes("w-full")
    host = ui.input("IP address or hostname", value=existing.host if existing else "",
                    placeholder="e.g. 192.168.1.50 or seestar.local").classes("w-full")
    port = ui.number("Port (empty = default)", value=existing.port if existing else None,
                     format="%d").classes("w-full")
    sites = _site_names()
    site = ui.select([""] + sites, label="Site (time zone & location pushed to the scope)",
                     value=(existing.options.get("site", "") if existing else "")).classes("w-full")

    options_box = ui.column().classes("w-full")
    option_inputs: dict[str, object] = {}

    def render_options() -> None:
        options_box.clear()
        option_inputs.clear()
        protocol = model_select.value.split(":")[0]
        values = existing.options if existing else {}
        with options_box:
            for opt in get_driver_class(protocol).option_fields:
                current = values.get(opt.key, opt.default)
                if opt.kind == "bool":
                    widget = ui.checkbox(opt.label, value=bool(current))
                else:
                    widget = ui.input(opt.label, value=str(current or "")).classes("w-full")
                if opt.help:
                    ui.label(opt.help).classes("text-xs text-grey-6 -mt-2")
                option_inputs[opt.key] = widget

    model_select.on_value_change(lambda _: render_options())
    render_options()

    def save() -> None:
        if not name.value.strip() or not host.value.strip():
            ui.notify("Name and address are required", type="warning")
            return
        protocol, model_id = model_select.value.split(":")
        options = {k: w.value for k, w in option_inputs.items()}
        if site.value:
            options["site"] = site.value
        if options.get("pem_path") and not os.path.isfile(os.path.expanduser(options["pem_path"])):
            ui.notify("Key file not found", type="warning")
            return
        entry = ScopeEntry(
            uid=existing.uid if existing else store.make_uid(protocol, name.value.strip()),
            name=name.value.strip(),
            protocol=protocol,
            model_id=model_id,
            host=host.value.strip(),
            port=int(port.value) if port.value else None,
            options=options,
        )
        manager = get_scope_manager()
        try:
            device = manager.update(entry) if existing else manager.add(entry)
        except RuntimeError as exc:
            ui.notify(str(exc), type="negative")
            return
        ui.navigate.to(f"/scopes/{device.uid}")

    with ui.row().classes("w-full justify-end gap-2"):
        if existing:
            def remove() -> None:
                get_scope_manager().remove(existing.uid)
                ui.navigate.to("/")
            ui.button("Remove", on_click=remove).props("flat color=negative")
        ui.button("Save", on_click=save)


# --- control page -----------------------------------------------------------------

async def _op(device: ScopeDevice, label: str, fn) -> None:
    """Runs a blocking driver call off the event loop, one at a time."""
    if device.is_running:
        ui.notify("A program is running - stop it first", type="warning")
        return
    if not device.op_lock.acquire(blocking=False):
        ui.notify("Another operation is in progress", type="warning")
        return
    ui.notify(f"{label}…")
    try:
        await run.io_bound(fn)
        ui.notify(f"{label}: done", type="positive")
    except (DriverError, ValueError) as exc:
        ui.notify(f"{label}: {exc}", type="negative", multi_line=True)
    finally:
        device.op_lock.release()


def _status_panel(device: ScopeDevice) -> None:
    driver = device.driver
    with ui.card().classes("w-full"):
        with ui.row().classes("items-center justify-between w-full"):
            state = ui.label().classes("text-lg")
            conn_btn = ui.button()
        info = ui.label().classes("text-sm text-grey-7")

    async def toggle_connection() -> None:
        if driver.is_connected():
            driver.disconnect()
        else:
            await _op(device, "Connect", driver.connect)
        refresh()

    conn_btn.on_click(toggle_connection)
    ticks = {"n": 0}

    async def poll() -> None:
        # Full state (battery, storage) every ~10s; events keep the rest live.
        ticks["n"] += 1
        if driver.is_connected() and ticks["n"] % 5 == 0 and hasattr(driver, "refresh_state"):
            try:
                await run.io_bound(driver.refresh_state)
            except Exception:
                pass
        refresh()

    def refresh() -> None:
        s = driver.get_status()
        state.set_text(s.state + (f" ({s.error})" if s.error else ""))
        conn_btn.set_text("Disconnect" if s.connected else "Connect")
        bits = []
        if s.battery_pct is not None:
            bits.append(f"Battery {s.battery_pct}%{' ⚡' if s.charging else ''}")
        if s.temperature_c is not None:
            bits.append(f"{s.temperature_c:.0f}°C")
        if s.storage_free_mb is not None:
            bits.append(f"{s.storage_free_mb / 1024:.1f} GB free")
        if s.ra_hours is not None:
            bits.append(f"RA {s.ra_hours:.3f}h Dec {s.dec_deg:+.2f}°")
        if s.frames_stacked is not None:
            bits.append(f"{s.frames_stacked} stacked / {s.frames_dropped or 0} dropped")
        if s.firmware:
            bits.append(f"fw {s.firmware}")
        info.set_text(" · ".join(bits) or device.entry.host)

    refresh()
    ui.timer(2.0, poll)


def _manual_panel(device: ScopeDevice) -> None:
    d = device.driver
    model = d.model
    with ui.expansion("Manual control", icon="gamepad").classes("w-full"):
        with ui.row().classes("gap-2"):
            if d.supports(C.AUTOFOCUS):
                ui.button("Autofocus", on_click=lambda: _op(device, "Autofocus", d.auto_focus))
            if d.supports(C.PARK):
                ui.button("Park", on_click=lambda: _op(device, "Park", d.park))
            ui.button("Stop all", on_click=lambda: run.io_bound(d.abort)).props("color=negative")

        if d.supports(C.GOTO):
            with ui.row().classes("items-end gap-2 w-full"):
                target = ui.input("Target").classes("w-32")
                ra = ui.input("RA (h or hh:mm:ss)").classes("w-36")
                dec = ui.input("Dec (° or dd:mm:ss)").classes("w-36")
                lp = ui.checkbox("LP filter") if d.supports(C.LP_FILTER) else None

                def goto() -> None:
                    ra_h, dec_d = parse_ra_hours(ra.value), parse_dec_deg(dec.value)
                    d.goto(ra_h, dec_d, target.value or "Target", lp_filter=lp.value if lp else None)

                ui.button("Goto", on_click=lambda: _op(device, "Goto", goto))

        if d.supports(C.CAPTURE):
            with ui.row().classes("items-end gap-2 w-full"):
                exp = (ui.select(list(model.exposures_s), value=model.exposures_s[0], label="Exposure (s)")
                       if model.exposures_s else ui.number("Exposure (s)", value=10))
                gain = ui.number("Gain", value=model.default_gain, format="%d").classes("w-20")

                def start() -> None:
                    d.start_capture(CaptureSettings(exposure_s=float(exp.value), gain=int(gain.value)))

                ui.button("Start stacking", on_click=lambda: _op(device, "Start stacking", start))
                ui.button("Stop stacking", on_click=lambda: _op(device, "Stop stacking", d.stop_capture))


def _program_panel(device: ScopeDevice) -> None:
    d = device.driver
    model = d.model
    uid = device.uid

    with ui.card().classes("w-full"):
        with ui.row().classes("items-center justify-between w-full"):
            ui.label("Programs").classes("text-lg")
            armed = ui.switch("Scheduler armed", value=device.armed)
            armed.on_value_change(lambda e: setattr(device, "armed", e.value))
        ui.label("When armed, programs in the queue start automatically at their time. "
                 "Programs use the same file format as the Dwarf side.").classes("text-xs text-grey-6")

        def open_tonightplan() -> None:
            from smartscopes.ui.tonightplan_dialog import open_tonightplan_dialog
            open_tonightplan_dialog(device, queue.refresh)

        ui.button("Tonight from TonightPlan", icon="auto_awesome", on_click=open_tonightplan).props("flat")

        with ui.expansion("New program", icon="add").classes("w-full"):
            start = datetime.now() + timedelta(minutes=5)
            with ui.row().classes("gap-2 w-full"):
                target = ui.input("Target").classes("w-32")
                ra = ui.input("RA (h or hh:mm:ss)").classes("w-36")
                dec = ui.input("Dec (° or dd:mm:ss)").classes("w-36")
            with ui.row().classes("gap-2 w-full"):
                date = ui.input("Date", value=start.strftime("%Y-%m-%d")).classes("w-32")
                time_ = ui.input("Start", value=start.strftime("%H:%M:%S")).classes("w-24")
                end = ui.input("Stop at (optional)", placeholder="HH:MM").classes("w-32")
            with ui.row().classes("gap-2 w-full items-end"):
                exp = (ui.select(list(model.exposures_s), value=model.exposures_s[0], label="Exposure (s)")
                       if model.exposures_s else ui.number("Exposure (s)", value=10))
                gain = ui.number("Gain", value=model.default_gain, format="%d").classes("w-20")
                count = ui.number("Frames (0 = until stop time)", value=90, format="%d").classes("w-48")
            with ui.row().classes("gap-4"):
                af = ui.checkbox("Autofocus after goto", value=d.supports(C.AUTOFOCUS))
                lp = ui.checkbox("LP filter", value=False) if d.supports(C.LP_FILTER) else None

            def add_program(run_now: bool) -> None:
                try:
                    ra_h, dec_d = parse_ra_hours(ra.value), parse_dec_deg(dec.value)
                    when = datetime.now() if run_now else datetime.strptime(
                        f"{date.value.strip()} {time_.value.strip()}", "%Y-%m-%d %H:%M:%S")
                except ValueError as exc:
                    ui.notify(str(exc), type="warning")
                    return
                if not int(count.value or 0) and not end.value.strip():
                    ui.notify("Set a frame count or a stop time", type="warning")
                    return
                program = new_program(
                    target=target.value.strip() or "Target", ra=ra_h, dec=dec_d, start=when,
                    exposure_s=float(exp.value), gain=int(gain.value), count=int(count.value or 0),
                    end_time=end.value.strip(), auto_focus=af.value, lp_filter=bool(lp and lp.value),
                )
                path = save_to_todo(uid, program)
                if run_now:
                    try:
                        device.start_program(path)
                    except RuntimeError as exc:
                        ui.notify(f"Queued, not started: {exc}", type="warning")
                queue.refresh()

            with ui.row().classes("gap-2 justify-end w-full"):
                ui.button("Add to queue", on_click=lambda: add_program(False)).props("flat")
                ui.button("Run now", on_click=lambda: add_program(True))

        @ui.refreshable
        def queue() -> None:
            for label, folder in (("Queue", "TODO_DIR"), ("Done", "DONE_DIR"), ("Failed", "ERROR_DIR")):
                items = list_programs(uid, folder)[:10]
                if not items:
                    continue
                ui.label(label).classes("text-sm text-grey-7 mt-2")
                for path, program in items:
                    idc = program.get("command", {}).get("id_command", {})
                    with ui.row().classes("items-center w-full gap-2"):
                        ui.label(f"{idc.get('date', '')} {idc.get('time', '')[:5]}").classes("text-xs w-28")
                        ui.label(idc.get("description") or os.path.basename(path)).classes("grow")
                        if folder != "TODO_DIR" and idc.get("message"):
                            ui.label(idc["message"]).classes("text-xs text-grey-6")
                        if folder == "TODO_DIR":
                            def run_now(p=path) -> None:
                                try:
                                    device.start_program(p)
                                except RuntimeError as exc:
                                    ui.notify(str(exc), type="warning")
                                queue.refresh()

                            def delete(p=path) -> None:
                                os.remove(p)
                                queue.refresh()

                            ui.button(icon="play_arrow", on_click=run_now).props("flat round dense")
                            ui.button(icon="delete", on_click=delete).props("flat round dense")

        queue()


def _run_panel(device: ScopeDevice) -> None:
    with ui.card().classes("w-full"):
        with ui.row().classes("items-center justify-between w-full"):
            title = ui.label("No program running").classes("text-lg")
            stop = ui.button("Stop program", on_click=device.request_stop).props("color=negative")
        progress = ui.linear_progress(value=0, show_value=False)
        log_view = ui.log(max_lines=200).classes("w-full h-48")
    shown = {"run": None, "n": 0}

    def refresh() -> None:
        r = device.run
        stop.set_visibility(device.is_running)
        log_view.set_visibility(r is not None)
        if r is None:
            progress.set_visibility(False)
            return
        if shown["run"] is not r:
            shown["run"], shown["n"] = r, 0
            log_view.clear()
        for ts, text in r.steps[shown["n"]:]:
            log_view.push(f"{ts:%H:%M:%S}  {text}")
        shown["n"] = len(r.steps)
        state = "running" if not r.finished else ("done" if r.success else "failed")
        title.set_text(f"{r.program_name} - {state}")
        progress.set_visibility(bool(r.frames_target))
        if r.frames_target:
            progress.set_value(min(1.0, r.frames / r.frames_target))

    refresh()
    ui.timer(1.0, refresh)


def build_pages() -> None:
    @ui.page("/scopes/add", title="Add telescope")
    def add_page() -> None:
        _header("Add telescope")
        with ui.column().classes("w-full max-w-xl mx-auto gap-3 p-4"):
            _entry_form(None)

    @ui.page("/scopes/{uid}/edit", title="Edit telescope")
    def edit_page(uid: str) -> None:
        device = get_scope_manager().get(uid)
        _header("Edit telescope", back=f"/scopes/{uid}")
        with ui.column().classes("w-full max-w-xl mx-auto gap-3 p-4"):
            if device is None:
                ui.label("Unknown telescope")
                return
            _entry_form(device.entry)

    @ui.page("/scopes/{uid}", title="Telescope")
    def device_page(uid: str) -> None:
        device = get_scope_manager().get(uid)
        if device is None:
            _header("Unknown telescope")
            return
        _header(f"{device.entry.name} · {device.driver.model.display_name}")
        with ui.column().classes("w-full max-w-3xl mx-auto gap-3 p-4"):
            with ui.row().classes("w-full justify-end -mt-2"):
                ui.button("Settings", icon="settings",
                          on_click=lambda: ui.navigate.to(f"/scopes/{uid}/edit")).props("flat dense")
            _status_panel(device)
            _run_panel(device)
            _program_panel(device)
            _manual_panel(device)
