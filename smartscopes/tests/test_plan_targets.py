"""TonightPlan -> Dwarf program files (upstream format, upstream folders)."""
import json
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

pytest.importorskip("dwarf_python_api.lib.dwarf_session")  # needs the upstream app stack

from smartscopes import tonightplan as tp  # noqa: E402
from smartscopes.plan_targets import DwarfPlanTarget, PlanOptions, _mosaic_framing  # noqa: E402

BASE = datetime(2026, 10, 10, 19, 0, tzinfo=timezone.utc)


def dwarf_session(model_id: str):
    """model_id is the config value (offset by -1): "2" = Dwarf 3, "4" = Mini, "1" = Dwarf II."""
    cfg = SimpleNamespace(dwarf_model_id=model_id, config_py_path="config_mydwarf.py",
                          latitude=55.68, longitude=12.57, city_name="Copenhagen",
                          timezone="Europe/Copenhagen")
    return SimpleNamespace(dwarf_uid="dwarf-uid-1", config=cfg)


def cand(id_, start_h, end_h, filter_rec="None", w=1.0, h=1.0, fit="yes", dec=41.3):
    t = {"id": id_, "common_name": "", "ra_h": 0.712, "dec_d": dec, "visual_impact": "Showstopper",
         "smart_scope": "Excellent", "filter_rec": filter_rec, "moon_width": w, "moon_height": h}
    return tp.Candidate(target=t, window_start=BASE + timedelta(hours=start_h),
                        window_end=BASE + timedelta(hours=end_h),
                        peak_time=BASE + timedelta(hours=(start_h + end_h) / 2), peak_alt=70.0,
                        usable_min=240, moon_dist=90, moon_status="good", score=1, fit=fit)


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _load(paths):
    return [json.load(open(p))["command"] for p in paths]


def test_dwarf3_programs(workdir):
    target = DwarfPlanTarget(dwarf_session("2"))
    assert target.scope_name == "Dwarf 3" and target.fov == (176, 99)
    assert "15" in target.exposures and all(float(e) >= 5 for e in target.exposures if "/" not in e)

    a = cand("NGC7000", 0, 2, filter_rec="Dual / Narrowband", w=4, h=3.2, fit="no")
    b = cand("M31", 2, 5, dec=0.0)
    slots = tp.schedule([a, b])
    paths = target.save_programs(slots, PlanOptions("15", 80, True, True, True), ZoneInfo("Europe/Copenhagen"))

    assert all(os.path.dirname(p).endswith(os.path.join("Devices_Sessions", "mydwarf", "Astro_Sessions", "ToDo"))
               for p in paths)
    first, second = _load(paths)
    assert first["calibration"]["do_action"] and first["auto_focus"]["do_action"]
    assert not second["calibration"]["do_action"] and not second["auto_focus"]["do_action"]
    assert first["setup_camera"]["ircut"] == "2"          # Duo-Band for a dual/narrowband target
    assert second["setup_camera"]["ircut"] == "1"         # Astro filter otherwise
    assert first["setup_camera"]["doMosaic"] and first["setup_camera"]["framingX"] <= 180
    assert "doMosaic" not in second["setup_camera"] or not second["setup_camera"]["doMosaic"]
    assert second["goto_manual"]["dec_coord"] == "0.0"   # truthy string, upstream won't skip the goto
    assert int(second["setup_camera"]["count"]) == int(3 * 3600 // 16)
    assert first["id_command"]["tonightplan"]["fit"].startswith("mosaic")


def test_mini_uses_its_own_filter_indices(workdir):
    target = DwarfPlanTarget(dwarf_session("4"))
    assert target.scope_name == "Dwarf Mini" and target.fov == (128, 72)
    paths = target.save_programs(tp.schedule([cand("NGC7000", 0, 2, filter_rec="Dual")]),
                                 PlanOptions("15", 80, False, True, False), ZoneInfo("UTC"))
    from components.camera_settings import _ir_filter_index_by_name
    assert _load(paths)[0]["setup_camera"]["ircut"] == str(_ir_filter_index_by_name("5", "Duo-Band Filter"))


def test_dwarf_own_location_offered_first(workdir):
    locs = DwarfPlanTarget(dwarf_session("2")).locations()
    assert locs[0].lat == 55.68 and locs[0].tz == "Europe/Copenhagen"


def test_mosaic_framing_puts_long_side_on_long_axis():
    fx, fy = _mosaic_framing(cand("x", 0, 1, w=2, h=7), (176, 99))
    assert fx > fy
    assert _mosaic_framing(cand("small", 0, 1, w=1, h=1), (176, 99)) is None
