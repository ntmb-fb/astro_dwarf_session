"""Tonight's targets from TonightPlan (tonightplan.cosmiccaptures.com).

TonightPlan has no API: its whole catalogue (positions, sizes and the
author's own ratings) is embedded in the page as `const TARGETS = [...]`,
and the plan is computed in the browser. This module fetches that
catalogue live (never stored in the repo, cached for a day) and re-runs
the site's own planning rules in Python with the same astronomy library
it uses (Astronomy Engine), so the list matches what the site shows for
the same location, sky quality and scope:

  * night = astronomical darkness (Sun < -18 deg), with the site's
    twilight fallbacks for short summer nights at high latitude;
  * a target is workable when it spends >= 50 min above 20 deg;
  * "tonight" season filter: peak month within +-1 of this month;
  * sky-quality filter (City/Suburban/Rural/Dark);
  * Moon status per target (good / ok / not ideal) - "not ideal" is what
    the site greys out, and is filtered out here;
  * score = usable minutes x altitude x Moon distance x impact, sunk by
    Moon status; field-of-view fit for the chosen scope.

Our additions on top: smart-scope "Challenging" targets are dropped, and
the list is ordered Showstopper, then Rewarding, then the rest.

Ratings and notes are Tim Ciasto's work (c) Cosmic Captures - fetched for
personal use exactly like a browser does, credited and linked back.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import astronomy as A

log = logging.getLogger("smartscopes.tonightplan")

SITE_URL = "https://tonightplan.cosmiccaptures.com/"
_CACHE_PATH = os.path.abspath(os.path.join("Devices_Sessions", "tonightplan_cache.json"))
_CACHE_MAX_AGE_S = 24 * 3600

# Constants mirrored from the site's own source.
MIN_ALT = 20
MIN_WORKABLE_MIN = 50
FOV_TIGHT = 0.8
_STEP_MIN = 10
_IMPACT_MULT = {"Showstopper": 1.4, "Rewarding": 1.15, "Decent": 1.0, "Subtle": 0.7, "Challenging": 0.5}
_MOON_SINK = {"not ideal": 0.35, "ok": 0.7}
_IMPACT_ORDER = {"Showstopper": 0, "Rewarding": 1}
SKY_QUALITIES = ("City", "Suburban", "Rural", "Dark")


class TonightPlanError(RuntimeError):
    pass


# --- catalogue --------------------------------------------------------------------

def _extract_targets(html: str) -> list[dict]:
    marker = re.search(r"const\s+TARGETS\s*=\s*", html)
    if not marker:
        raise TonightPlanError("TonightPlan page layout changed (catalogue not found)")
    try:
        targets, _ = json.JSONDecoder().raw_decode(html, marker.end())
    except ValueError as exc:
        raise TonightPlanError(f"TonightPlan catalogue could not be read: {exc}") from exc
    required = {"id", "ra_h", "dec_d", "visual_impact", "smart_scope"}
    if not targets or not required <= set(targets[0]):
        raise TonightPlanError("TonightPlan catalogue format changed")
    return targets


def fetch_catalogue(*, force: bool = False) -> list[dict]:
    """Downloads the catalogue at most once a day."""
    if not force and os.path.exists(_CACHE_PATH):
        if time.time() - os.path.getmtime(_CACHE_PATH) < _CACHE_MAX_AGE_S:
            with open(_CACHE_PATH, encoding="utf-8") as f:
                return json.load(f)
    request = urllib.request.Request(SITE_URL, headers={
        "User-Agent": "astro_dwarf_session-smartscope (personal telescope planner)"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            html = response.read().decode("utf-8")
    except OSError as exc:
        raise TonightPlanError(f"Could not reach TonightPlan: {exc}") from exc
    targets = _extract_targets(html)
    os.makedirs(os.path.dirname(_CACHE_PATH), exist_ok=True)
    with open(_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(targets, f)
    return targets


# --- night & Moon -------------------------------------------------------------------

@dataclass
class Night:
    evening: datetime            # UTC
    morning: datetime            # UTC
    twilight_tier: int = 0       # 0 = real darkness, 1 = nautical, 2 = civil only
    moon_illum: int = 0          # % at calculation time (as the site does)
    moon_peak_alt: int = 0
    moon_score: float = 0.0
    moon_free_ratio: float = 0.0


def _local_anchor(now: datetime, tz: ZoneInfo, hour: int, day_offset: int) -> A.Time:
    local = now.astimezone(tz)
    anchor = datetime(local.year, local.month, local.day, hour, tzinfo=tz) + timedelta(days=day_offset)
    return A.Time.Make(*anchor.astimezone(timezone.utc).timetuple()[:6])


def _search_sun(obs: A.Observer, direction: int, start: A.Time, alt: float) -> A.Time | None:
    try:
        return A.SearchAltitude(A.Body.Sun, obs, A.Direction.Rise if direction > 0 else A.Direction.Set,
                                start, 1, alt)
    except Exception:
        return None


def _darkness(obs: A.Observer, now: datetime, tz: ZoneInfo, day_offset: int):
    noon = _local_anchor(now, tz, 12, day_offset)
    eve = _search_sun(obs, -1, noon, -18)
    mor = _search_sun(obs, +1, eve or noon, -18)
    return eve, mor


def _night_window(obs: A.Observer, now: datetime, tz: ZoneInfo) -> tuple[A.Time, A.Time, int]:
    # After midnight we still belong to the night that began yesterday evening.
    _, prev_morning = _darkness(obs, now, tz, -1)
    offset = -1 if prev_morning and A.Time.Make(*now.astimezone(timezone.utc).timetuple()[:6]).ut < prev_morning.ut else 0
    eve, mor = _darkness(obs, now, tz, offset)
    if eve and mor:
        return eve, mor, 0
    # No astronomical darkness: the site's twilight tiers.
    noon = _local_anchor(now, tz, 12, 0)
    midnight = _local_anchor(now, tz, 0, 1)
    naut = (_search_sun(obs, -1, noon, -12), _search_sun(obs, +1, midnight, -12))
    if all(naut):
        return naut[0], naut[1], 1
    civil = (_search_sun(obs, -1, noon, -6), _search_sun(obs, +1, midnight, -6))
    if all(civil):
        return civil[0], civil[1], 2
    raise TonightPlanError("No usable darkness tonight at this location (midnight sun)")


def _moon_window(obs: A.Observer, eve: A.Time, mor: A.Time) -> tuple[int, float]:
    step = 5 / 1440
    peak, rise, set_, prev = -90.0, None, None, None
    ut = eve.ut
    while ut <= mor.ut:
        t = A.Time(ut)
        eq = A.Equator(A.Body.Moon, t, obs, True, True)
        alt = A.Horizon(t, obs, eq.ra, eq.dec, A.Refraction.Normal).altitude
        peak = max(peak, alt)
        above = alt > 0
        if prev is not None:
            if not prev and above and rise is None:
                rise = ut
            if prev and not above and set_ is None:
                set_ = ut
        prev = above
        ut += step
    eq0 = A.Equator(A.Body.Moon, eve, obs, True, True)
    up_at_start = A.Horizon(eve, obs, eq0.ra, eq0.dec, A.Refraction.Normal).altitude > 0
    dark_hrs = (mor.ut - eve.ut) * 24
    if not up_at_start and rise:
        free = (rise - eve.ut) * 24
    elif up_at_start and set_:
        free = (mor.ut - set_) * 24
    elif not up_at_start and not rise:
        free = dark_hrs
    else:
        free = 0.0
    return max(0, round(peak)), round(free, 1) / (dark_hrs or 1)


def compute_night(lat: float, lon: float, tz_name: str, now: datetime | None = None) -> tuple[Night, A.Observer]:
    obs = A.Observer(lat, lon, 0)
    tz = ZoneInfo(tz_name)
    now = now or datetime.now(timezone.utc)
    eve, mor, tier = _night_window(obs, now, tz)
    t_now = A.Time.Make(*now.astimezone(timezone.utc).timetuple()[:6])
    illum = round(A.Illumination(A.Body.Moon, t_now).phase_fraction * 100)
    peak, free_ratio = _moon_window(obs, eve, mor)
    night = Night(
        evening=eve.Utc().replace(tzinfo=timezone.utc), morning=mor.Utc().replace(tzinfo=timezone.utc),
        twilight_tier=tier, moon_illum=illum, moon_peak_alt=peak,
        moon_score=(illum / 100) * peak, moon_free_ratio=free_ratio,
    )
    night._eve, night._mor = eve, mor  # type: ignore[attr-defined]
    return night, obs


_STATUS = ("good", "ok", "not ideal")


def _severity_cap(n: Night) -> str:
    if n.moon_score < 12:
        return "good"
    if n.moon_score >= 45 or (n.moon_illum >= 90 and n.moon_score >= 20):
        return "not ideal"
    if n.moon_score >= 25:
        return "ok"
    return "good"


def _worse(a: str, b: str) -> str:
    return _STATUS[max(_STATUS.index(a), _STATUS.index(b))]


def moon_status(t: dict, moon_dist: float | None, n: Night) -> str:
    morph, kind = (t.get("morphology") or "").lower(), (t.get("object_type") or "").lower()
    cap = _severity_cap(n)
    if any(w in morph or w in kind for w in ("cluster", "asterism", "star cloud")):
        if t.get("sky_conditions") == "City":
            return "good"
        return "good" if cap == "good" else "ok"
    fr = (t.get("filter_rec") or "").lower()
    narrowband = "narrowband" in fr or "dual" in fr
    lp = t.get("lp_friendly") or ""
    if not narrowband or lp == "Dark Skies Recommended":
        good, ok = 8, 25
    elif lp == "Some Moon / Moderate LP":
        good, ok = 18, 42
    else:
        good, ok = 30, 60
    status = "good" if n.moon_score < good else "ok" if n.moon_score < ok else "not ideal"
    if n.moon_free_ratio > 0.55 and status == "ok":
        status = "good"
    elif n.moon_free_ratio > 0.55 and status == "not ideal":
        status = "ok"
    status = _worse(status, cap)
    if n.moon_score >= 15 and moon_dist is not None:
        steps = 2 if moon_dist < 30 else 1 if moon_dist < 60 else 0
        status = _STATUS[min(2, _STATUS.index(status) + steps)]
    return status


def fov_fit(scope_w: float, scope_h: float, t: dict) -> str:
    """The site's verdict for a fixed-sensor smart scope: yes / depends / tight / no."""
    tw = (t.get("moon_width") or 0) * 30
    th = (t.get("moon_height") or t.get("moon_width") or 0) * 30
    if not tw or not th:
        return "yes"
    a = min(scope_w / tw, scope_h / th)
    b = min(scope_h / tw, scope_w / th)
    best, worst = max(a, b), min(a, b)
    if worst >= 1:
        return "yes"
    if best >= 1:
        return "depends"
    return "tight" if best >= FOV_TIGHT else "no"


# --- ranking ----------------------------------------------------------------------------

@dataclass
class Candidate:
    target: dict
    window_start: datetime        # UTC, first 10-min step >= 20 deg
    window_end: datetime
    peak_time: datetime
    peak_alt: float
    usable_min: int
    moon_dist: int | None
    moon_status: str
    score: float
    fit: str
    extra: dict = field(default_factory=dict)

    @property
    def id(self) -> str:
        return self.target["id"]

    @property
    def label(self) -> str:
        t = self.target
        return f"{t['id']} - {t['common_name']}" if t.get("common_name") else t["id"]


def _analyze(t: dict, n: Night, obs: A.Observer) -> dict:
    A.DefineStar(A.Body.Star1, t["ra_h"], t["dec_d"], 1000)
    eve, mor = n._eve, n._mor  # type: ignore[attr-defined]
    step = _STEP_MIN / 1440
    peak_alt, peak_ut, ws, we, mins = -90.0, None, None, None, 0
    ut = eve.ut
    while ut <= mor.ut:
        tt = A.Time(ut)
        eq = A.Equator(A.Body.Star1, tt, obs, True, True)
        alt = A.Horizon(tt, obs, eq.ra, eq.dec, A.Refraction.Normal).altitude
        if alt > peak_alt:
            peak_alt, peak_ut = alt, ut
        if alt >= MIN_ALT:
            mins += _STEP_MIN
            ws = ws or ut
            we = ut
        ut += step
    moon_dist = None
    if peak_ut is not None:
        tp = A.Time(peak_ut)
        star = A.Equator(A.Body.Star1, tp, obs, True, True)
        moon = A.Equator(A.Body.Moon, tp, obs, True, True)
        moon_dist = A.AngleBetween(star.vec, moon.vec)
    moon_factor = min(1, moon_dist / 45) if moon_dist else 0.5
    alt_factor = peak_alt / 90 if peak_alt > 0 else 0
    return dict(peak_alt=round(peak_alt, 1), peak_ut=peak_ut, ws=ws, we=we, mins=mins,
                moon_dist=round(moon_dist) if moon_dist else None,
                score=round(mins * moon_factor * alt_factor * _IMPACT_MULT.get(t["visual_impact"], 1.0)))


def _in_season(t: dict, month: int) -> bool:
    try:
        peak = int(t.get("peak_month") or 0)
    except ValueError:
        return False
    if not peak:
        return False
    diff = abs(peak - month)
    return min(diff, 12 - diff) <= 1


def _twilight_ok(t: dict, tier: int) -> bool:
    good = t["visual_impact"] in ("Showstopper", "Rewarding")
    if tier == 1:
        return good and t.get("brightness_cat") in ("Very Bright", "Bright")
    if tier == 2:
        morph = t.get("morphology") or ""
        return good and t.get("brightness_cat") == "Very Bright" and ("Cluster" in morph or "Nebula" in morph)
    return True


def _utc(ut: float) -> datetime:
    return A.Time(ut).Utc().replace(tzinfo=timezone.utc)


def rank_tonight(
    targets: list[dict],
    *,
    lat: float,
    lon: float,
    tz_name: str,
    sky: str = "Suburban",
    scope_fov: tuple[float, float] | None = None,
    now: datetime | None = None,
) -> tuple[Night, list[Candidate]]:
    night, obs = compute_night(lat, lon, tz_name, now)
    local_month = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(tz_name)).month
    sky_max = SKY_QUALITIES.index(sky)

    out: list[Candidate] = []
    for t in targets:
        if t.get("smart_scope") == "Challenging":
            continue
        if t.get("sky_conditions") in SKY_QUALITIES and SKY_QUALITIES.index(t["sky_conditions"]) > sky_max:
            continue
        if not _in_season(t, local_month) or not _twilight_ok(t, night.twilight_tier):
            continue
        a = _analyze(t, night, obs)
        if a["mins"] < MIN_WORKABLE_MIN:
            continue
        status = moon_status(t, a["moon_dist"], night)
        if status == "not ideal":  # greyed out on the site
            continue
        out.append(Candidate(
            target=t,
            window_start=_utc(a["ws"]),
            window_end=min(_utc(a["we"]) + timedelta(minutes=_STEP_MIN), night.morning),
            peak_time=_utc(a["peak_ut"]), peak_alt=a["peak_alt"], usable_min=a["mins"],
            moon_dist=a["moon_dist"], moon_status=status,
            score=a["score"] * _MOON_SINK.get(status, 1),
            fit=fov_fit(*scope_fov, t) if scope_fov else "yes",
        ))

    out.sort(key=lambda c: (_IMPACT_ORDER.get(c.target["visual_impact"], 2),
                            c.fit == "no",  # needs a mosaic: after the ones that fit
                            -c.score))
    return night, out


# --- scheduling ------------------------------------------------------------------------------

_MIN_SLOT = timedelta(minutes=30)


def schedule(selected: list[Candidate]) -> list[tuple[Candidate, datetime, datetime]]:
    """Back-to-back slots in transit order: each target gets its own
    window, split from the next one halfway between their transits.
    Targets left with less than 30 minutes are dropped."""
    ordered = sorted(selected, key=lambda c: c.peak_time)
    slots: list[tuple[Candidate, datetime, datetime]] = []
    cursor: datetime | None = None
    for i, c in enumerate(ordered):
        start = max(c.window_start, cursor) if cursor else c.window_start
        end = c.window_end
        if i + 1 < len(ordered):
            nxt = ordered[i + 1]
            split = c.peak_time + (nxt.peak_time - c.peak_time) / 2
            end = min(end, max(split, nxt.window_start))
        if end - start >= _MIN_SLOT:
            slots.append((c, start, end))
            cursor = end
    return slots
