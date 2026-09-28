"""Runs an upstream-format program file on any ScopeDriver.

The program JSON is the one the Dwarf program editor / API already
write ({"command": {"id_command": ..., "goto_manual": ..., "setup_camera":
...}}), so programs, the ToDo/Current/Done/Error folders and the external
catalog/API tools stay interchangeable between Dwarf and other scopes.

Step order: time/location -> polar align -> calibration -> goto ->
autofocus -> capture (-> wide capture). Unlike the Dwarf runner,
autofocus runs *after* the goto, on stars of the target field, which is
what the Seestar (and most smart scopes) expect. A step the device
doesn't support is logged and skipped, not treated as a failure.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable

from smartscopes.base import Capability as C, CaptureSettings, DriverError, ScopeDriver
from smartscopes.coords import parse_dec_deg, parse_ra_hours

log = logging.getLogger("smartscopes.runner")


class RunAborted(Exception):
    pass


@dataclass
class RunState:
    program_name: str
    started_at: datetime = field(default_factory=datetime.now)
    steps: list[tuple[datetime, str]] = field(default_factory=list)
    current_step: str = ""
    frames: int = 0
    frames_target: int = 0
    finished: bool = False
    success: bool | None = None
    message: str = ""
    stop_event: threading.Event = field(default_factory=threading.Event)

    def log(self, text: str) -> None:
        self.steps.append((datetime.now(), text))
        self.current_step = text
        log.info("[%s] %s", self.program_name, text)


def _parse_end_time(value: str, now: datetime) -> datetime | None:
    """"HH:MM" or "HH:MM:SS"; a time earlier than now means tomorrow."""
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            t = datetime.strptime(value, fmt).time()
            break
        except ValueError:
            continue
    else:
        raise ValueError(f"Invalid end_time {value!r}")
    end = datetime.combine(now.date(), t)
    return end if end > now else end + timedelta(days=1)


class ProgramRunner:
    def __init__(self, driver: ScopeDriver, state: RunState, *, site: tuple[float, float] | None = None):
        self.driver = driver
        self.state = state
        self.site = site

    # --- helpers -----------------------------------------------------------
    def _check(self) -> None:
        if self.state.stop_event.is_set():
            raise RunAborted("Stopped by user")

    def _sleep(self, seconds) -> None:
        if seconds and float(seconds) > 0:
            self.state.log(f"Waiting {float(seconds):.0f}s")
            if self.state.stop_event.wait(float(seconds)):
                raise RunAborted("Stopped by user")

    def _retry(self, what: str, fn: Callable[[], None], attempts: int) -> None:
        for attempt in range(1, attempts + 1):
            self._check()
            try:
                fn()
                self.state.log(f"{what}: done")
                return
            except DriverError as exc:
                self.state.log(f"{what}: attempt {attempt}/{attempts} failed - {exc}")
                if attempt == attempts:
                    raise
                self._sleep(5)

    def _skip_unless(self, capability: C, what: str) -> bool:
        if self.driver.supports(capability):
            return False
        self.state.log(f"{what}: not supported by {self.driver.model.display_name}, skipped")
        return True

    # --- main ----------------------------------------------------------------
    def run(self, command: dict) -> None:
        """Raises DriverError / RunAborted / ValueError on failure."""
        d = self.driver
        attempts = max(1, int(command.get("id_command", {}).get("max_retries", 3) or 1))

        if not d.is_connected():
            self.state.log("Connecting")
            d.connect()

        if d.supports(C.TIME_LOCATION):
            lat, lon = self.site if self.site else (None, None)
            self._retry("Set time/location", lambda: d.set_time_and_location(lat, lon), attempts)

        def flag(section: str) -> dict | None:
            sect = command.get(section) or {}
            return sect if sect.get("do_action") else None

        if (sect := flag("eq_solving")) and not self._skip_unless(C.POLAR_ALIGN, "Polar alignment"):
            self._sleep(sect.get("wait_before"))
            self._retry("Polar alignment", d.polar_align, attempts)
            self._sleep(sect.get("wait_after"))

        if (sect := flag("calibration")) and not self._skip_unless(C.CALIBRATION, "Calibration"):
            self._sleep(sect.get("wait_before"))
            self._retry("Calibration", d.calibrate, attempts)
            self._sleep(sect.get("wait_after"))

        if flag("infinite_focus"):
            self.state.log("Infinite focus: Dwarf-only step, skipped")

        camera = flag("setup_camera") or {}
        lp_filter = camera.get("lp_filter")

        if sect := flag("goto_solar"):
            if not self._skip_unless(C.GOTO_SOLAR, "Solar-system goto"):
                target = sect.get("target", "")
                self._retry(f"Goto {target}", lambda: d.goto_solar(target), attempts)
                self._sleep(sect.get("wait_after"))
        elif sect := flag("goto_manual"):
            if not self._skip_unless(C.GOTO, "Goto"):
                ra = parse_ra_hours(sect.get("ra_coord"))
                dec = parse_dec_deg(sect.get("dec_coord"))
                target = sect.get("target") or f"RA {ra:.3f}h Dec {dec:+.2f}"
                self._retry(f"Goto {target}", lambda: d.goto(ra, dec, target, lp_filter=lp_filter), attempts)
                self._sleep(sect.get("wait_after"))

        if (sect := flag("auto_focus")) and not self._skip_unless(C.AUTOFOCUS, "Autofocus"):
            self._sleep(sect.get("wait_before"))
            self._retry("Autofocus", d.auto_focus, attempts)
            self._sleep(sect.get("wait_after"))

        if camera and not self._skip_unless(C.CAPTURE, "Capture"):
            self._capture(camera, wide=False)
        if (wide := flag("setup_wide_camera")) and not self._skip_unless(C.WIDE_CAPTURE, "Wide capture"):
            self._capture(wide, wide=True)

    def _capture(self, sect: dict, *, wide: bool) -> None:
        settings = CaptureSettings(
            exposure_s=float(sect.get("exposure") or 10),
            gain=int(sect["gain"]) if str(sect.get("gain", "")).strip() else None,
            count=int(sect.get("count") or 0),
            end_time=_parse_end_time(sect.get("end_time", ""), datetime.now()),
            lp_filter=sect.get("lp_filter"),
            wide=wide,
        )
        label = "Wide capture" if wide else "Capture"
        target = f"{settings.count} x {settings.exposure_s:g}s" if settings.count else "until stopped"
        if settings.end_time:
            target += f", stop at {settings.end_time:%H:%M}"
        self.state.log(f"{label}: {target}")
        self.state.frames, self.state.frames_target = 0, settings.count

        self.driver.start_capture(settings)
        try:
            started = time.monotonic()
            while True:
                if self.state.stop_event.wait(2):
                    raise RunAborted("Stopped by user")
                progress = self.driver.capture_progress()
                self.state.frames = progress.stacked
                if settings.count and progress.stacked >= settings.count:
                    self.state.log(f"{label}: {progress.stacked} frames stacked ({progress.dropped} dropped)")
                    break
                if settings.end_time and datetime.now() >= settings.end_time:
                    self.state.log(f"{label}: end time reached with {progress.stacked} frames")
                    break
                # Give the device a moment to report "stacking" before
                # treating "not running" as the device having stopped.
                if not progress.running and time.monotonic() - started > 60:
                    raise DriverError(f"Device stopped stacking after {progress.stacked} frames")
                if not self.driver.is_connected():
                    raise DriverError("Connection lost during capture")
        finally:
            try:
                self.driver.stop_capture()
            except DriverError as exc:
                self.state.log(f"{label}: stop failed - {exc}")
        self._sleep(sect.get("wait_after"))


# --- file lifecycle (ToDo -> Current -> Done/Error) ---------------------------

def _write_json(path: str, data: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
    os.replace(tmp, path)


def run_program_file(
    driver: ScopeDriver,
    source_path: str,
    dirs: dict[str, str],
    state: RunState,
    *,
    site: tuple[float, float] | None = None,
) -> None:
    """Blocking. Moves the file to Current while running, then to Done or
    Error with id_command.process/result/message filled in (same fields
    the Dwarf scheduler writes)."""
    with open(source_path, encoding="utf-8") as f:
        program = json.load(f)
    filename = os.path.basename(source_path)
    current_path = os.path.join(dirs["CURRENT_DIR"], filename)
    id_command = program["command"].setdefault("id_command", {})
    id_command.update(process="pending", starting_date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    shutil.move(source_path, current_path)
    _write_json(current_path, program)

    try:
        ProgramRunner(driver, state, site=site).run(program["command"])
        state.success, state.message = True, "Session completed successfully"
    except RunAborted as exc:
        state.success, state.message = False, str(exc)
        driver.abort()
    except (DriverError, ValueError, OSError) as exc:
        state.success, state.message = False, str(exc)
        driver.abort()
    except Exception as exc:  # never leave a file stranded in Current
        log.exception("Unexpected error running %s", filename)
        state.success, state.message = False, f"Unexpected error: {exc}"
        driver.abort()
    finally:
        state.finished = True
        state.log(state.message)
        id_command.update(
            process="done",
            result=bool(state.success),
            message=state.message,
            processed_date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        target_dir = dirs["DONE_DIR"] if state.success else dirs["ERROR_DIR"]
        _write_json(current_path, program)
        shutil.move(current_path, os.path.join(target_dir, filename))
