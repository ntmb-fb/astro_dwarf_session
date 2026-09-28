"""Dashboard section listing non-Dwarf telescopes. Rendered by the single
hook line in pages/dashboard.py, right under the Dwarf cards."""
from __future__ import annotations

from nicegui import ui

from smartscopes.manager import ScopeDevice, get_scope_manager


def _card(device: ScopeDevice) -> None:
    with ui.card().classes("w-full cursor-pointer").on(
        "click", lambda: ui.navigate.to(f"/scopes/{device.uid}")
    ):
        with ui.row().classes("items-center justify-between w-full"):
            with ui.column().classes("gap-0"):
                ui.label(device.entry.name).classes("text-lg")
                ui.label(device.driver.model.display_name).classes("text-xs text-grey-6")
            dot = ui.icon("circle").classes("text-sm")
        detail = ui.label().classes("text-sm")

    def refresh() -> None:
        status = device.driver.get_status()
        dot.classes(replace="text-sm " + ("text-positive" if status.connected else "text-grey-5"))
        parts = [status.state]
        if status.battery_pct is not None:
            parts.append(f"🔋 {status.battery_pct}%")
        if device.is_running and device.run:
            run = device.run
            frames = f" {run.frames}/{run.frames_target}" if run.frames_target else ""
            parts.append(f"▶ {run.program_name}{frames}")
        elif status.capturing and status.frames_stacked is not None:
            parts.append(f"{status.frames_stacked} frames")
        detail.set_text(" · ".join(parts))

    refresh()
    ui.timer(2.0, refresh)


def render_dashboard_section() -> None:
    devices = get_scope_manager().all()
    with ui.row().classes("items-center justify-between w-full mt-2"):
        ui.label("Other smart telescopes").classes("text-xl")
        with ui.row().classes("items-center gap-1"):
            ui.button(icon="lock", on_click=lambda: ui.navigate.to("/scopes/https")).props(
                "flat round"
            ).tooltip("HTTPS for phones (install as app)")
            ui.button(icon="add", on_click=lambda: ui.navigate.to("/scopes/add")).props(
                "flat round"
            ).tooltip("Add a Seestar or other telescope")
    if not devices:
        ui.label("None yet - tap + to add a Seestar.").classes("text-grey-6 text-sm")
        return
    with ui.grid(columns=2 if len(devices) >= 2 else 1).classes("w-full gap-3"):
        for device in devices:
            _card(device)
