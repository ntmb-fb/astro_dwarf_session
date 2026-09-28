"""Dashboard section listing non-Dwarf telescopes. Rendered by the single
hook line in pages/dashboard.py, right under the Dwarf cards.

The card deliberately mirrors upstream's Dwarf card (components/
device_card.py): same header (icon, name, address, scheduler clock,
connection dot), same picture size and battery/temperature/storage row,
and the same coloured status banner with upstream's own translated
texts, so both kinds of telescope read the same at a glance."""
from __future__ import annotations

from nicegui import ui

from components.i18n import t
from components.status_banner import status_banner
from smartscopes.manager import ScopeDevice, get_scope_manager

try:  # upstream's card styling, so both card types stay identical
    from components.device_card import (
        _INFO_ICON_CLASSES,
        _INFO_TEXT_CLASSES,
        _LARGE_VISUAL_CLASSES,
        _LOW_BATTERY_PCT,
        _LOW_DISK_GB,
        _apply_warning_style,
    )
except ImportError:  # upstream renamed something: degrade gracefully
    _LARGE_VISUAL_CLASSES = "rounded w-32 h-32 md:w-40 md:h-40"
    _INFO_TEXT_CLASSES = "text-xs md:text-sm"
    _INFO_ICON_CLASSES = "text-sm md:text-base"
    _LOW_BATTERY_PCT, _LOW_DISK_GB = 15, 15

    def _apply_warning_style(icon, label, is_low):
        pass


class ScopeCardView:
    def __init__(self, device: ScopeDevice):
        self.device = device
        self._banner_kind: str | None = None
        self._banner_title: ui.label | None = None
        self._banner_detail: ui.label | None = None
        self._was_connected = False
        model = device.driver.model

        with ui.card().classes("w-full cursor-pointer").on(
            "click", lambda: ui.navigate.to(f"/scopes/{device.uid}")
        ):
            with ui.row().classes("items-center justify-between w-full"):
                with ui.row().classes("items-center gap-2 min-w-0"):
                    ui.icon("satellite_alt").classes("text-2xl text-grey-6 shrink-0")
                    with ui.column().classes("gap-0 min-w-0"):
                        ui.label(device.entry.name).classes("font-medium truncate")
                        ui.label(device.entry.host).classes("text-xs text-grey-6 truncate")
                with ui.row().classes("items-center gap-1"):
                    self._scheduler_icon = ui.icon("schedule")
                    self._status_dot = ui.icon("circle")

            with ui.row().classes(
                "flex-wrap justify-center sm:justify-start items-center text-center sm:text-left gap-3 w-full"
            ):
                if model.image:
                    ui.image(f"/smartscope-images/{model.image}").classes(_LARGE_VISUAL_CLASSES).props(
                        "fit=contain"
                    )
                with ui.column().classes("gap-2"):
                    ui.label(model.display_name).classes("text-sm font-medium text-grey-7 truncate")
                    with ui.row().classes("items-center gap-3 flex-wrap") as self._info_row:
                        with ui.row().classes("items-center gap-1"):
                            self._battery_icon = ui.icon("battery_full").classes(
                                f"text-grey-6 {_INFO_ICON_CLASSES}")
                            self._battery_label = ui.label("").classes(f"text-grey-7 {_INFO_TEXT_CLASSES}")
                        with ui.row().classes("items-center gap-1"):
                            ui.icon("thermostat").classes(f"text-grey-6 {_INFO_ICON_CLASSES}")
                            self._temperature_label = ui.label("").classes(f"text-grey-7 {_INFO_TEXT_CLASSES}")
                        with ui.row().classes("items-center gap-1"):
                            self._disk_icon = ui.icon("sd_card").classes(f"text-grey-6 {_INFO_ICON_CLASSES}")
                            self._disk_label = ui.label("").classes(f"text-grey-7 {_INFO_TEXT_CLASSES}")

            # Only this slot is rebuilt, and only when the banner kind changes.
            self._banner_slot = ui.column().classes("w-full gap-0")

        self.update()

    def update(self) -> None:
        device = self.device
        status = device.driver.get_status()
        connected = status.connected
        running = device.is_running and device.run is not None

        if status.error:
            kind = "error"
        elif running:
            kind = "program_running"
        elif connected and status.capturing:
            kind = "capturing"
        elif not connected:
            kind = "connection_lost" if self._was_connected else "disconnected"
        else:
            kind = "connected"
        if connected:
            self._was_connected = True

        self._status_dot.classes(replace=f"text-xs text-{'positive' if connected else 'negative'}")
        self._scheduler_icon.classes(replace="text-sm text-primary" if device.armed else "text-sm text-grey-4")
        self._scheduler_icon.props(
            f"title='{t('scheduler_on_tooltip') if device.armed else t('scheduler_off_tooltip')}'")

        self._info_row.set_visibility(connected)
        if connected:
            battery = status.battery_pct
            self._battery_icon.name = "battery_charging_full" if status.charging else "battery_full"
            self._battery_label.set_text(f"{battery}%" if battery is not None else "")
            _apply_warning_style(self._battery_icon, self._battery_label,
                                 battery is not None and battery < _LOW_BATTERY_PCT)
            self._temperature_label.set_text(
                f"{status.temperature_c:.0f}°C" if status.temperature_c is not None else "")
            free_gb = status.storage_free_mb / 1024 if status.storage_free_mb is not None else None
            total_gb = status.storage_total_mb / 1024 if status.storage_total_mb is not None else None
            if free_gb is not None and total_gb is not None:
                self._disk_label.set_text(
                    t("dashboard_disk_space", available=f"{free_gb:.0f}", total=f"{total_gb:.0f}"))
            else:
                self._disk_label.set_text(f"{free_gb:.0f} GB" if free_gb is not None else "")
            _apply_warning_style(self._disk_icon, self._disk_label,
                                 free_gb is not None and free_gb < _LOW_DISK_GB)

        if kind != self._banner_kind:
            self._banner_kind = kind
            self._banner_title = self._banner_detail = None
            self._banner_slot.clear()
            with self._banner_slot:
                if kind == "error":
                    status_banner(t("error_with_detail", error=status.error), kind="danger")
                elif kind in ("capturing", "program_running"):
                    icon = "schedule" if kind == "program_running" else "play_arrow"
                    with ui.row().classes("items-center gap-2 rounded-lg px-3 py-2 w-full bg-blue-50 text-blue-800"):
                        ui.icon(icon).classes("text-lg")
                        with ui.column().classes("gap-0"):
                            self._banner_title = ui.label("").classes("text-sm font-medium")
                            self._banner_detail = ui.label("").classes("text-xs opacity-80")
                elif kind == "connection_lost":
                    status_banner(t("connection_lost"), kind="danger")
                elif kind == "disconnected":
                    status_banner(t("disconnected"), kind="warning")
                else:
                    status_banner(t("connected"), kind="success")

        # Same kind as last tick: update the live text in place.
        if kind == "program_running" and self._banner_title is not None:
            run = device.run
            self._banner_title.set_text(run.program_name or t("program_untitled"))
            detail = run.current_step
            if run.frames_target:
                detail = t("capture_progress_with_total", current=run.frames, total=run.frames_target,
                           stacked=run.frames)
            self._banner_detail.set_text(detail)
        elif kind == "capturing" and self._banner_title is not None:
            stacked = status.frames_stacked or 0
            self._banner_title.set_text(t("capture_progress_no_total",
                                          current=stacked + (status.frames_dropped or 0), stacked=stacked))
            self._banner_detail.set_text("")


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
        cards = [ScopeCardView(device) for device in devices]

    def refresh() -> None:
        for card in cards:
            card.update()

    ui.timer(2.0, refresh)
