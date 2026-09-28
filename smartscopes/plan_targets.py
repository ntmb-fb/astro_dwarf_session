"""Adapters that let the TonightPlan dialog plan for any telescope.

The dialog only knows this interface; each telescope family says what
its camera can do and how to write its program files. Two families
exist: our own drivers (Seestar, ...) and upstream's Dwarfs, whose
programs go into the Dwarf's normal ToDo folder and are run by
upstream's own, hardware-tested runner.
"""
from __future__ import annotations

import json
import math
import os
import threading
from dataclasses import dataclass
from datetime import datetime

from smartscopes import tonightplan as tp

_PREFS_PATH = os.path.abspath(os.path.join("Devices_Sessions", "smartscopes_prefs.json"))
_prefs_lock = threading.Lock()

# Dwarf fields of view (arcmin, width x height), as listed by TonightPlan's scope picker.
_DWARF_FOV = {"2": (191, 108), "3": (176, 99), "5": (128, 72)}
_DWARF_NAME = {"2": "Dwarf II", "3": "Dwarf 3", "5": "Dwarf Mini"}
_DWARF_MOSAIC_MAX = 1.8          # upstream program editor's framingX/Y range is 1.0-1.8
_MAX_COUNT = 999


def get_pref(uid: str, key: str, default=None):
    try:
        with open(_PREFS_PATH, encoding="utf-8") as f:
            return json.load(f).get(uid, {}).get(key, default)
    except (OSError, ValueError):
        return default


def set_pref(uid: str, key: str, value) -> None:
    with _prefs_lock:
        try:
            with open(_PREFS_PATH, encoding="utf-8") as f:
                prefs = json.load(f)
        except (OSError, ValueError):
            prefs = {}
        prefs.setdefault(uid, {})[key] = value
        os.makedirs(os.path.dirname(_PREFS_PATH), exist_ok=True)
        with open(_PREFS_PATH, "w", encoding="utf-8") as f:
            json.dump(prefs, f, indent=2)


@dataclass
class Location:
    label: str
    lat: float
    lon: float
    tz: str


@dataclass
class PlanOptions:
    exposure: str
    gain: int
    autofocus: bool
    use_filter: bool     # switch to the narrowband/LP filter when TonightPlan recommends one
    mosaic: bool         # use the scope's own mosaic for targets bigger than the frame


def _site_locations() -> list[Location]:
    from site_registry import list_site_entries  # upstream module

    return [Location(s.name, s.latitude, s.longitude, s.timezone or "")
            for s in list_site_entries() if s.latitude is not None and s.longitude is not None]


def _mosaic_framing(c: tp.Candidate, fov: tuple[float, float]) -> tuple[int, int] | None:
    """framingX/Y (x100) covering the target, longest side on the longest
    axis of the frame, with 10% margin. None if it already fits."""
    tw = (c.target.get("moon_width") or 0) * 30
    th = (c.target.get("moon_height") or c.target.get("moon_width") or 0) * 30
    if not tw or not th:
        return None
    big, small = max(tw, th), min(tw, th)
    fw, fh = fov
    if fw >= fh:
        fx, fy = big / fw, small / fh
    else:
        fx, fy = small / fw, big / fh
    fx, fy = (min(_DWARF_MOSAIC_MAX, max(1.0, v * 1.1)) for v in (fx, fy))
    if fx <= 1.0 and fy <= 1.0:
        return None
    return round(fx * 100), round(fy * 100)


class PlanTarget:
    uid: str
    scope_name: str
    fov: tuple[float, float] | None
    exposures: list[str]
    default_exposure: str
    default_gain: int
    autofocus_label = "Autofocus after each goto"
    autofocus_default = True
    filter_label = ""            # empty = no switchable filter
    supports_mosaic = False

    def locations(self) -> list[Location]:
        return _site_locations()

    def default_location(self) -> str | None:
        return None

    def is_armed(self) -> bool:
        raise NotImplementedError

    def save_programs(self, slots, opts: PlanOptions, tz) -> list[str]:
        raise NotImplementedError


def _plan_meta(c: tp.Candidate, tz, fit_text: str) -> dict:
    t = c.target
    return {"visual_impact": t["visual_impact"], "smart_scope": t.get("smart_scope"),
            "imaging_time": t.get("imaging_time"), "fit": fit_text, "peak_alt": c.peak_alt,
            "peak_time": f"{c.peak_time.astimezone(tz):%H:%M}", "moon_status": c.moon_status,
            "url": tp.SITE_URL}


def _wants_filter(c: tp.Candidate) -> bool:
    fr = (c.target.get("filter_rec") or "").lower()
    return "dual" in fr or "narrowband" in fr


def _local_naive(dt: datetime) -> datetime:
    return dt.astimezone().replace(tzinfo=None)  # schedulers compare against this PC's clock


FIT_TEXT = {"yes": "fits", "depends": "fits (orientation)", "tight": "tight fit", "no": "needs mosaic"}


# --- our own drivers (Seestar, ...) --------------------------------------------------------

class DriverPlanTarget(PlanTarget):
    def __init__(self, device):
        from smartscopes.base import Capability as C

        self.device = device
        model = device.driver.model
        self.uid = device.uid
        self.scope_name = model.display_name
        self.fov = model.fov_arcmin
        self.exposures = [f"{e:g}" for e in model.exposures_s] or ["10"]
        self.default_exposure = self.exposures[0]
        self.default_gain = model.default_gain
        self.autofocus_default = device.driver.supports(C.AUTOFOCUS)
        self.filter_label = "LP filter when recommended" if device.driver.supports(C.LP_FILTER) else ""

    def default_location(self) -> str | None:
        return self.device.entry.options.get("site")

    def is_armed(self) -> bool:
        return self.device.armed

    def save_programs(self, slots, opts: PlanOptions, tz) -> list[str]:
        from smartscopes.programs import new_program, save_to_todo

        paths = []
        for c, start, end in slots:
            t = c.target
            program = new_program(
                target=c.label, ra=t["ra_h"], dec=t["dec_d"], start=_local_naive(start),
                exposure_s=float(opts.exposure), gain=opts.gain, count=0,
                end_time=_local_naive(end).strftime("%H:%M"), auto_focus=opts.autofocus,
                lp_filter=bool(self.filter_label) and opts.use_filter and _wants_filter(c),
            )
            idc = program["command"]["id_command"]
            idc["description"] = c.label
            idc["tonightplan"] = _plan_meta(c, tz, FIT_TEXT[c.fit])
            paths.append(save_to_todo(self.uid, program))
        return paths


# --- upstream Dwarfs --------------------------------------------------------------------------

class DwarfPlanTarget(PlanTarget):
    autofocus_label = "Autofocus at the start of the night"
    supports_mosaic = True

    def __init__(self, session):
        from dwarf_python_api.get_config_data import config_to_dwarf_id_str
        from components.camera_settings import _exposure_names, _ir_filter_names

        self.session = session
        self.uid = session.dwarf_uid
        self.dwarf_type = config_to_dwarf_id_str(session.config.dwarf_model_id) or "2"
        self.scope_name = _DWARF_NAME.get(self.dwarf_type, "Dwarf")
        self.fov = _DWARF_FOV.get(self.dwarf_type)
        # Deep-sky subs only (>= 5 s) from the model's own exposure table.
        names = _exposure_names("tele", self.dwarf_type)
        self.exposures = [n for n in names if _seconds(n) >= 5] or names
        self.default_exposure = "15" if "15" in self.exposures else self.exposures[-1]
        self.default_gain = 80
        self._filters = _ir_filter_names(self.dwarf_type)
        self.filter_label = "Duo-Band filter when recommended" if any("Duo" in f for f in self._filters) else ""

    def locations(self) -> list[Location]:
        cfg = self.session.config
        own = []
        if cfg.latitude is not None and cfg.longitude is not None:
            own = [Location(f"{self.scope_name}'s own location" + (f" ({cfg.city_name})" if cfg.city_name else ""),
                            cfg.latitude, cfg.longitude, cfg.timezone or "")]
        return own + _site_locations()

    def default_location(self) -> str | None:
        locs = self.locations()
        return locs[0].label if locs else None

    def is_armed(self) -> bool:
        from components import scheduler_loop

        return scheduler_loop.is_armed(self.uid)

    def _ircut(self, duo: bool) -> str:
        from components.camera_settings import _ir_filter_index_by_name

        if self.dwarf_type == "2":
            return "1"                                    # IR_PASS for astro
        wanted = "Duo-Band Filter" if duo else "Astro Filter"
        return str(_ir_filter_index_by_name(self.dwarf_type, wanted))

    def save_programs(self, slots, opts: PlanOptions, tz) -> list[str]:
        from components.program_editor import _blank_program, _filename_for
        from components.session_dirs import ensure_dirs

        dirs = ensure_dirs(self.session)
        exp_s = _seconds(opts.exposure) or 15
        paths = []
        for i, (c, start, end) in enumerate(slots):
            t = c.target
            program = _blank_program()
            cmd = program["command"]
            start_l, end_l = _local_naive(start), _local_naive(end)
            cmd["id_command"].update(description=c.label, date=start_l.strftime("%Y-%m-%d"),
                                     time=start_l.strftime("%H:%M:%S"))
            cmd["id_command"]["tonightplan"] = _plan_meta(c, tz, FIT_TEXT[c.fit])
            first = i == 0
            # Upstream's runner order is autofocus -> calibration -> goto, so the
            # night's first program aligns the mount once for all that follow.
            cmd["calibration"].update(do_action=first)
            cmd["auto_focus"].update(do_action=first and opts.autofocus)
            # Strings, not floats: upstream skips the goto when a coordinate is falsy (0.0).
            cmd["goto_manual"].update(do_action=True, target=c.label,
                                      ra_coord=str(t["ra_h"]), dec_coord=str(t["dec_d"]))
            count = max(1, min(_MAX_COUNT, int((end - start).total_seconds() // (exp_s + 1))))
            cam = cmd["setup_camera"]
            cam.update(do_action=True, exposure=opts.exposure, gain=str(opts.gain),
                       ircut=self._ircut(bool(self.filter_label) and opts.use_filter and _wants_filter(c)),
                       count=str(count), end_time=end_l.strftime("%H:%M"))
            framing = _mosaic_framing(c, self.fov) if (opts.mosaic and self.fov and c.fit in ("tight", "no")) else None
            if framing:
                panels = math.ceil(framing[0] / 100) * math.ceil(framing[1] / 100)
                cam.update(doMosaic=True, framingX=framing[0], framingY=framing[1],
                           mosaic_count=str(max(1, min(249, count // panels))))
                cmd["id_command"]["tonightplan"]["fit"] = f"mosaic {framing[0] / 100:.2f}×{framing[1] / 100:.2f}"
            cmd["setup_wide_camera"]["do_action"] = False
            path = os.path.join(dirs["TODO_DIR"], _filename_for(program))
            with open(path, "w", encoding="utf-8") as f:
                json.dump(program, f, indent=4)
            paths.append(path)
        return paths


def _seconds(name: str) -> float:
    try:
        if "/" in name:
            num, den = name.split("/")
            return float(num) / float(den)
        return float(name)
    except (ValueError, ZeroDivisionError):
        return 0.0
