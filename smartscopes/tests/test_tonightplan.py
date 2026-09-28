"""TonightPlan import. Uses a tiny hand-made catalogue (the real one is the
site author's work and is never stored in this repo). The port was
checked separately against the site's own JavaScript: identical usable
minutes, score, Moon status and fit for all 221 targets on 5 nights."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from smartscopes import tonightplan as tp

NEW_MOON = datetime(2026, 10, 10, 21, 0, tzinfo=timezone.utc)
FULL_MOON = datetime(2026, 9, 28, 20, 30, tzinfo=timezone.utc)
CPH = dict(lat=55.68, lon=12.57, tz_name="Europe/Copenhagen")


def target(id_, ra, dec, impact="Rewarding", scope="Excellent", **extra):
    base = {"id": id_, "common_name": "", "ra_h": ra, "dec_d": dec, "visual_impact": impact,
            "smart_scope": scope, "peak_month": "10", "sky_conditions": "Suburban",
            "object_type": "Galaxy", "morphology": "Spiral Galaxy", "filter_rec": "None",
            "lp_friendly": "Dark Skies Recommended", "brightness_cat": "Bright",
            "moon_width": 1, "moon_height": 1}
    return {**base, **extra}


CATALOGUE = [
    target("M31", 0.712, 41.27, "Showstopper", moon_width=6, moon_height=2),      # too big for an S50
    target("M33", 1.564, 30.66, "Rewarding"),
    target("NGC7331", 22.62, 34.42, "Showstopper"),
    target("NGC891", 2.376, 42.35, "Rewarding", scope="Challenging"),
    target("M74", 1.611, 15.78, "Decent"),
    target("M45", 3.79, 24.12, "Showstopper", object_type="Cluster", morphology="Open Cluster",
           sky_conditions="City"),
    target("CityOnly", 1.0, 40.0, "Rewarding", sky_conditions="Dark"),
]


def test_extract_targets_from_page():
    html = "<script>let x=1;\nconst TARGETS = " + json.dumps(CATALOGUE) + ";\nfunction f(){}</script>"
    assert [t["id"] for t in tp._extract_targets(html)] == [t["id"] for t in CATALOGUE]


def test_extract_detects_layout_change():
    with pytest.raises(tp.TonightPlanError):
        tp._extract_targets("<html>no catalogue here</html>")


def test_new_moon_ranking_and_filters():
    night, ranked = tp.rank_tonight(CATALOGUE, **CPH, sky="Suburban", scope_fov=(44, 77), now=NEW_MOON)
    ids = [c.id for c in ranked]
    assert night.moon_illum < 5
    assert "NGC891" not in ids                      # smart-scope Challenging dropped
    assert "CityOnly" not in ids                    # needs darker sky than "Suburban"
    impacts = [c.target["visual_impact"] for c in ranked]
    assert impacts == sorted(impacts, key=lambda i: {"Showstopper": 0, "Rewarding": 1}.get(i, 2))
    showstoppers = [c for c in ranked if c.target["visual_impact"] == "Showstopper"]
    assert showstoppers[-1].id == "M31" and showstoppers[-1].fit == "no"   # mosaic-only goes last


def test_full_moon_drops_greyed_targets_but_keeps_clusters():
    night, ranked = tp.rank_tonight(CATALOGUE, **CPH, now=FULL_MOON)
    assert night.moon_illum >= 90
    assert [c.id for c in ranked] == ["M45"]        # broadband galaxies are "not ideal" -> gone
    assert ranked[0].moon_status == "good"


def test_moon_status_rules():
    night = tp.Night(evening=NEW_MOON, morning=NEW_MOON, moon_illum=95, moon_score=50)
    assert tp.moon_status(target("x", 0, 0), 90, night) == "not ideal"
    assert tp.moon_status(target("x", 0, 0, morphology="Open Cluster"), 10, night) == "ok"
    dark = tp.Night(evening=NEW_MOON, morning=NEW_MOON, moon_illum=0, moon_score=0)
    assert tp.moon_status(target("x", 0, 0), 5, dark) == "good"


def test_fov_fit_matches_site_rules():
    s50 = (44, 77)
    assert tp.fov_fit(*s50, target("a", 0, 0, moon_width=1, moon_height=1)) == "yes"      # 30'x30'
    assert tp.fov_fit(*s50, target("b", 0, 0, moon_width=2, moon_height=1)) == "depends"  # 60'x30'
    assert tp.fov_fit(*s50, target("c", 0, 0, moon_width=3, moon_height=1)) == "tight"    # 90' in 77' = 85%
    assert tp.fov_fit(*s50, target("d", 0, 0, moon_width=4, moon_height=1)) == "no"


def _cand(id_, start_h, end_h, peak_h):
    base = datetime(2026, 10, 10, 18, tzinfo=timezone.utc)
    return tp.Candidate(target={"id": id_}, window_start=base + timedelta(hours=start_h),
                        window_end=base + timedelta(hours=end_h), peak_time=base + timedelta(hours=peak_h),
                        peak_alt=60, usable_min=300, moon_dist=90, moon_status="good", score=1, fit="yes")


def test_schedule_back_to_back_in_transit_order():
    a, b = _cand("late", 2, 10, 6), _cand("early", 0, 6, 2)
    slots = tp.schedule([a, b])
    assert [c.id for c, _, _ in slots] == ["early", "late"]
    (_, s1, e1), (_, s2, e2) = slots
    assert e1 == s2 and s1 == b.window_start and e2 == a.window_end
    assert e1 - s1 >= timedelta(minutes=30)


def test_schedule_drops_target_without_room():
    a = _cand("a", 0, 8, 4)
    squeezed = _cand("b", 0, 4.2, 4.1)      # same transit, leaves < 30 min
    ids = [c.id for c, _, _ in tp.schedule([a, squeezed])]
    assert len(ids) == 1
