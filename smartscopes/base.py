"""The driver contract every non-Dwarf smart telescope implements.

A driver is a *blocking* object: every method may take seconds (a goto)
or minutes (an autofocus) and is always called from a worker thread,
never from the NiceGUI event loop directly (UI code goes through
nicegui.run.io_bound). Keeping drivers synchronous keeps them easy to
write and test against a plain TCP/HTTP device, whatever its protocol.

Adding a new telescope family = subclass ScopeDriver, declare its
models/capabilities, and decorate it with @register_driver (see
smartscopes/registry.py and smartscopes/drivers/seestar/ for a full
example). The program runner and the UI only ever talk to this
interface, and skip any program step whose Capability a driver doesn't
declare.
"""
from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar


class DriverError(RuntimeError):
    """Raised by a driver when the device refused or failed an operation."""


class Capability(str, enum.Enum):
    GOTO = "goto"                  # goto RA/Dec
    GOTO_SOLAR = "goto_solar"      # goto a named solar-system body
    AUTOFOCUS = "autofocus"
    CAPTURE = "capture"            # deep-sky stacked capture on the main camera
    WIDE_CAPTURE = "wide_capture"  # second (wide-angle) camera
    CALIBRATION = "calibration"    # Dwarf-style sky calibration
    POLAR_ALIGN = "polar_align"    # EQ-mode polar alignment (Dwarf EQ solving, Seestar 3PPA)
    LP_FILTER = "lp_filter"        # switchable light-pollution filter
    PARK = "park"
    TIME_LOCATION = "time_location"  # push host time + site location to the device


@dataclass(frozen=True)
class ModelInfo:
    """One concrete telescope model served by a driver."""
    model_id: str
    display_name: str
    capabilities: frozenset[Capability]
    # Exposure choices (seconds) the device accepts for stacked capture;
    # empty = free numeric input.
    exposures_s: tuple[float, ...] = ()
    default_gain: int = 80
    # Field of view in arcminutes (width, height) of the main camera, as
    # listed by TonightPlan's scope picker; None = unknown.
    fov_arcmin: tuple[float, float] | None = None
    # Picture shown on the dashboard card: a file in smartscopes/ui/images/.
    image: str | None = None


@dataclass(frozen=True)
class OptionField:
    """A driver-specific setting shown in the add/edit telescope form and
    stored in ScopeEntry.options[key]."""
    key: str
    label: str
    kind: str = "text"          # "text" | "bool"
    default: object = ""
    help: str = ""


@dataclass
class ScopeEntry:
    """Persisted configuration of one paired device (see store.py)."""
    uid: str
    name: str
    protocol: str
    model_id: str
    host: str
    port: int | None = None
    # Driver-specific settings (e.g. Seestar's auth key path).
    options: dict = field(default_factory=dict)


@dataclass
class ScopeStatus:
    connected: bool = False
    state: str = ""                    # short human-readable activity ("Idle", "Stacking", ...)
    battery_pct: int | None = None
    charging: bool | None = None
    temperature_c: float | None = None
    storage_free_mb: int | None = None
    storage_total_mb: int | None = None
    firmware: str | None = None
    ra_hours: float | None = None
    dec_deg: float | None = None
    capturing: bool = False
    frames_stacked: int | None = None
    frames_dropped: int | None = None
    error: str | None = None
    updated_at: datetime = field(default_factory=datetime.now)


@dataclass
class CaptureSettings:
    exposure_s: float
    gain: int | None = None
    count: int = 0                     # 0 = until stopped / end_time
    end_time: datetime | None = None
    lp_filter: bool | None = None      # None = leave device setting untouched
    wide: bool = False


@dataclass
class CaptureProgress:
    running: bool
    stacked: int = 0
    dropped: int = 0


class ScopeDriver(ABC):
    """Base class for one live connection to one device."""

    protocol: ClassVar[str]
    protocol_display_name: ClassVar[str]
    models: ClassVar[dict[str, ModelInfo]]
    default_port: ClassVar[int | None] = None
    option_fields: ClassVar[tuple[OptionField, ...]] = ()

    def __init__(self, entry: ScopeEntry):
        self.entry = entry

    @property
    def model(self) -> ModelInfo:
        return self.models[self.entry.model_id]

    def supports(self, capability: Capability) -> bool:
        return capability in self.model.capabilities

    # --- connection -------------------------------------------------
    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @abstractmethod
    def is_connected(self) -> bool: ...

    @abstractmethod
    def get_status(self) -> ScopeStatus:
        """Cheap: may return cached state, must not block for long."""

    # --- operations (blocking until finished) -------------------------
    def set_time_and_location(self, lat: float | None, lon: float | None) -> None:
        raise DriverError("Not supported by this device")

    def goto(self, ra_hours: float, dec_deg: float, target_name: str, *, lp_filter: bool | None = None) -> None:
        raise DriverError("Not supported by this device")

    def goto_solar(self, target_name: str) -> None:
        raise DriverError("Not supported by this device")

    def auto_focus(self) -> None:
        raise DriverError("Not supported by this device")

    def calibrate(self) -> None:
        raise DriverError("Not supported by this device")

    def polar_align(self) -> None:
        raise DriverError("Not supported by this device")

    def park(self) -> None:
        raise DriverError("Not supported by this device")

    # --- capture (non-blocking start, then polled) --------------------
    def start_capture(self, settings: CaptureSettings) -> None:
        raise DriverError("Not supported by this device")

    def capture_progress(self) -> CaptureProgress:
        raise DriverError("Not supported by this device")

    def stop_capture(self) -> None:
        raise DriverError("Not supported by this device")

    def abort(self) -> None:
        """Best-effort stop of whatever the device is doing (used on
        program cancel). Must not raise."""
        try:
            self.stop_capture()
        except Exception:
            pass
