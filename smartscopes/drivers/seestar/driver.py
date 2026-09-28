"""ZWO Seestar driver (S50, S30) on top of SeestarClient."""
from __future__ import annotations

import logging
from datetime import datetime

from smartscopes.base import (
    Capability as C,
    CaptureProgress,
    CaptureSettings,
    DriverError,
    ModelInfo,
    OptionField,
    ScopeDriver,
    ScopeStatus,
)
from smartscopes.drivers.seestar.client import DEFAULT_PORT, SeestarClient, SeestarError
from smartscopes.registry import register_driver

log = logging.getLogger("smartscopes.seestar")

_COMMON = frozenset({C.GOTO, C.AUTOFOCUS, C.CAPTURE, C.LP_FILTER, C.PARK, C.TIME_LOCATION})

# Seconds a goto (slew + plate-solve + re-centre) / an autofocus may take.
_GOTO_TIMEOUT_S = 300
_AUTOFOCUS_TIMEOUT_S = 240


@register_driver
class SeestarDriver(ScopeDriver):
    protocol = "seestar"
    protocol_display_name = "ZWO Seestar"
    default_port = DEFAULT_PORT
    models = {
        # Fields of view as listed by TonightPlan's scope picker.
        "s50": ModelInfo("s50", "Seestar S50", _COMMON, exposures_s=(10, 20, 30), default_gain=80,
                         fov_arcmin=(44, 77), image="seestar-s50.svg"),
        "s50pro": ModelInfo("s50pro", "Seestar S50 Pro", _COMMON, exposures_s=(10, 20, 30), default_gain=80,
                            fov_arcmin=(83, 147), image="seestar-s50pro.svg"),
        "s30": ModelInfo("s30", "Seestar S30", _COMMON, exposures_s=(10, 20, 30), default_gain=80,
                         fov_arcmin=(84, 148), image="seestar-s30.svg"),
        "s30pro": ModelInfo("s30pro", "Seestar S30 Pro", _COMMON, exposures_s=(10, 20, 30), default_gain=80,
                            fov_arcmin=(134, 239), image="seestar-s30pro.svg"),
    }

    option_fields = (
        OptionField(
            "pem_path", "Auth key file (.pem)",
            help="Needed for Seestar firmware 7.18+. Extract it from the Seestar app "
                 "(see the README). Leave empty for older firmware.",
        ),
        OptionField(
            "verify_injection", "Send 'verify' marker", kind="bool", default=True,
            help="Required by recent firmware; disable only if commands are rejected.",
        ),
    )

    def __init__(self, entry):
        super().__init__(entry)
        self.client = SeestarClient(
            entry.host,
            entry.port or DEFAULT_PORT,
            pem_path=entry.options.get("pem_path") or None,
            verify_injection=entry.options.get("verify_injection", True),
        )
        self._last_state: dict = {}

    # --- connection ------------------------------------------------------
    def connect(self) -> None:
        try:
            self.client.connect()
            self._last_state = self.client.call("get_device_state", timeout=15)
        except (OSError, SeestarError) as exc:
            self.client.close()
            raise DriverError(f"Cannot connect to {self.entry.host}: {exc}") from exc

    def disconnect(self) -> None:
        self.client.close()

    def is_connected(self) -> bool:
        return self.client.connected

    def refresh_state(self) -> None:
        """Full device-state query (a few KB); called by the UI poller."""
        self._last_state = self.client.call("get_device_state", timeout=10)

    def get_status(self) -> ScopeStatus:
        connected = self.client.connected
        state = self._last_state if connected else {}
        pi = state.get("pi_status", {})
        # PiStatus events are more recent than the last full state query.
        pi = {**pi, **{k: v for k, v in (self.client.events.get("PiStatus") or {}).items() if k != "Event"}}
        volumes = (state.get("storage") or {}).get("storage_volume") or [{}]
        device = state.get("device", {})
        stack = self.client.events.get("Stack") or {}
        coord = self.client.equ_coord

        return ScopeStatus(
            connected=connected,
            state=self._activity() if connected else "Disconnected",
            battery_pct=pi.get("battery_capacity"),
            charging=(pi["charger_status"] == "Charging") if "charger_status" in pi else None,
            temperature_c=pi.get("temp"),
            storage_free_mb=volumes[0].get("freeMB"),
            storage_total_mb=volumes[0].get("totalMB"),
            firmware=str(device["firmware_ver_string"]) if "firmware_ver_string" in device else None,
            ra_hours=coord[0] if coord else None,
            dec_deg=coord[1] if coord else None,
            capturing=self._is_stacking(),
            frames_stacked=stack.get("stacked_frame"),
            frames_dropped=stack.get("dropped_frame"),
        )

    def _activity(self) -> str:
        for event, label in (("AutoGoto", "Goto"), ("AutoFocus", "Autofocus"),
                             ("EqModePA", "Polar alignment"), ("ScopeHome", "Parking")):
            if self.client.event_state(event) == "working":
                return label
        return "Stacking" if self._is_stacking() else "Idle"

    def _is_stacking(self) -> bool:
        return self.client.event_state("Stack") in ("working", "frame_complete", "start")

    # --- operations ------------------------------------------------------
    def set_time_and_location(self, lat, lon) -> None:
        now = datetime.now().astimezone()
        tz_name = _local_tz_name()
        self.client.call("pi_set_time", {
            "year": now.year, "mon": now.month, "day": now.day,
            "hour": now.hour, "min": now.minute, "sec": now.second,
            "time_zone": tz_name,
        })
        if lat is not None and lon is not None:
            self.client.call("set_user_location", {"lat": lat, "lon": lon, "force": True})

    def goto(self, ra_hours, dec_deg, target_name, *, lp_filter=None) -> None:
        self.client.clear_event("AutoGoto")
        try:
            self.client.call("iscope_start_view", {
                "mode": "star",
                "target_ra_dec": [ra_hours, dec_deg],
                "target_name": target_name,
                "lp_filter": bool(lp_filter),
            })
            event = self.client.wait_event_state("AutoGoto", timeout=_GOTO_TIMEOUT_S)
        except SeestarError as exc:
            raise DriverError(f"Goto failed: {exc}") from exc
        if event.get("state") != "complete":
            raise DriverError(f"Goto {event.get('state')}: {event.get('error') or event}")

    def auto_focus(self) -> None:
        self.client.clear_event("AutoFocus")
        try:
            self.client.call("start_auto_focuse")  # sic - firmware spelling
            event = self.client.wait_event_state("AutoFocus", timeout=_AUTOFOCUS_TIMEOUT_S)
        except SeestarError as exc:
            raise DriverError(f"Autofocus failed: {exc}") from exc
        if event.get("state") != "complete":
            raise DriverError(f"Autofocus {event.get('state')}: {event.get('error') or event}")

    def park(self) -> None:
        self.client.clear_event("ScopeHome")
        try:
            self.client.call("scope_park")
            self.client.wait_event_state("ScopeHome", timeout=120)
        except SeestarError as exc:
            raise DriverError(f"Park failed: {exc}") from exc

    # --- capture ---------------------------------------------------------
    def start_capture(self, settings: CaptureSettings) -> None:
        if settings.wide:
            raise DriverError("The Seestar has no wide-angle camera")
        try:
            self.client.call("set_setting", {"exp_ms": {"stack_l": int(settings.exposure_s * 1000)}})
            if settings.gain is not None:
                self.client.call("set_control_value", ["gain", int(settings.gain)])
            if settings.lp_filter is not None:
                self.client.call("set_setting", {"stack_lenhance": bool(settings.lp_filter)})
            self.client.clear_event("Stack")
            self.client.call("iscope_start_stack", {"restart": True})
        except SeestarError as exc:
            raise DriverError(f"Could not start stacking: {exc}") from exc

    def capture_progress(self) -> CaptureProgress:
        stack = self.client.events.get("Stack") or {}
        return CaptureProgress(
            running=self._is_stacking(),
            stacked=int(stack.get("stacked_frame") or 0),
            dropped=int(stack.get("dropped_frame") or 0),
        )

    def stop_capture(self) -> None:
        try:
            self.client.call("iscope_stop_view", {"stage": "Stack"})
        except SeestarError as exc:
            raise DriverError(f"Could not stop stacking: {exc}") from exc

    def abort(self) -> None:
        for stage in ("AutoGoto", "Stack"):
            try:
                self.client.call("iscope_stop_view", {"stage": stage}, timeout=5)
            except SeestarError:
                pass


def _local_tz_name() -> str:
    try:
        import tzlocal
        return tzlocal.get_localzone_name()
    except Exception:
        return "UTC"
