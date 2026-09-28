import json
import os
import time
from datetime import datetime, timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

import smartscopes.drivers  # noqa: F401  registers drivers
from smartscopes import store
from smartscopes.base import ScopeEntry
from smartscopes.coords import parse_dec_deg, parse_ra_hours
from smartscopes.drivers.seestar.client import _NO_PARAMS, SeestarClient, SeestarTimeout, inject_verify
from smartscopes.drivers.seestar.driver import SeestarDriver
from smartscopes.runner import RunState, run_program_file
from smartscopes.tests.fake_seestar import FakeSeestar


# --- pure helpers -------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("05:35:17.3", 5 + 35 / 60 + 17.3 / 3600),
    ("5h35m17.3s", 5 + 35 / 60 + 17.3 / 3600),
    (5.5, 5.5),
    ("5.5", 5.5),
])
def test_parse_ra(value, expected):
    assert parse_ra_hours(value) == pytest.approx(expected)


@pytest.mark.parametrize("value,expected", [
    ("-05:23:28", -(5 + 23 / 60 + 28 / 3600)),   # sign applies to the whole value
    ("-0:30:00", -0.5),
    ("+41:16:09", 41 + 16 / 60 + 9 / 3600),
    ("-5d23m28s", -(5 + 23 / 60 + 28 / 3600)),
    (0.0, 0.0),
])
def test_parse_dec(value, expected):
    assert parse_dec_deg(value) == pytest.approx(expected)


def test_parse_rejects_out_of_range():
    with pytest.raises(ValueError):
        parse_ra_hours("25:00:00")
    with pytest.raises(ValueError):
        parse_dec_deg("-91")


@pytest.mark.parametrize("fw,params,expected", [
    (0, _NO_PARAMS, ["verify"]),
    (2706, ["gain", 80], ["gain", 80, "verify"]),
    (2706, {"stage": "Stack"}, {"stage": "Stack"}),          # dicts untouched from 2706
    (2600, {"stage": "Stack"}, {"stage": "Stack", "verify": True}),
    (2500, ["gain", 80], ["gain", 80]),                     # old firmware: never
    (2706, "x", ["x", "verify"]),
])
def test_inject_verify(fw, params, expected):
    assert inject_verify("anything", params, fw) == expected


def test_inject_verify_skips_auth_methods():
    assert inject_verify("get_verify_str", _NO_PARAMS, 0) is _NO_PARAMS


# --- client / driver against the fake device -----------------------------------------

@pytest.fixture
def rsa_key(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = tmp_path / "seestar.pem"
    pem.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                      serialization.NoEncryption()))
    return key, str(pem)


def _driver(fake: FakeSeestar, **options) -> SeestarDriver:
    return SeestarDriver(ScopeEntry(uid="seestar-test", name="Test", protocol="seestar",
                                    model_id="s50", host="127.0.0.1", port=fake.port, options=options))


def test_auth_handshake(rsa_key):
    key, pem = rsa_key
    fake = FakeSeestar(public_key=key.public_key())
    try:
        client = SeestarClient("127.0.0.1", fake.port, pem_path=pem)
        client.connect()
        assert fake.verified and client.authenticated
        assert client.firmware_ver_int == 2706
        assert fake.methods()[:2] == ["get_verify_str", "verify_client"]
        client.close()
    finally:
        fake.close()


def test_unauthenticated_times_out_with_hint(rsa_key):
    key, _ = rsa_key
    fake = FakeSeestar(public_key=key.public_key())
    try:
        client = SeestarClient("127.0.0.1", fake.port, first_reply_timeout=2)
        with pytest.raises(SeestarTimeout, match="auth key"):
            client.connect()
    finally:
        client.close()
        fake.close()


def test_status_goto_focus():
    fake = FakeSeestar()
    driver = _driver(fake)
    try:
        driver.connect()
        status = driver.get_status()
        assert status.connected and status.battery_pct == 87 and status.storage_free_mb == 20480
        driver.goto(5.58, -5.39, "M42")
        driver.auto_focus()
        goto = next(m for m in fake.received if m["method"] == "iscope_start_view")
        assert goto["params"]["target_ra_dec"] == [5.58, -5.39]
    finally:
        driver.disconnect()
        fake.close()


# --- full program run -----------------------------------------------------------

def test_program_file_runs_to_done(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_BASE_DIR", str(tmp_path))
    fake = FakeSeestar(frame_interval=0.1)
    driver = _driver(fake)
    dirs = store.session_dirs("seestar-test", create=True)
    program = {"command": {
        "id_command": {"description": "M42", "date": "2026-01-01", "time": "00:00:00", "max_retries": 1},
        "goto_manual": {"do_action": True, "target": "M42", "ra_coord": "05:35:17", "dec_coord": "-05:23:28"},
        "auto_focus": {"do_action": True},
        "calibration": {"do_action": True},
        "setup_camera": {"do_action": True, "exposure": "10", "gain": "80", "count": "3", "lp_filter": True},
    }}
    src = os.path.join(dirs["TODO_DIR"], "m42.json")
    with open(src, "w") as f:
        json.dump(program, f)

    state = RunState(program_name="m42")
    try:
        run_program_file(driver, src, dirs, state)
    finally:
        driver.disconnect()
        fake.close()

    assert state.success, state.message
    done = json.load(open(os.path.join(dirs["DONE_DIR"], "m42.json")))
    assert done["command"]["id_command"]["result"] is True
    assert not os.listdir(dirs["TODO_DIR"]) and not os.listdir(dirs["CURRENT_DIR"])
    methods = fake.methods()
    assert methods.index("iscope_start_view") < methods.index("start_auto_focuse") < methods.index("iscope_start_stack")
    assert {"stack_lenhance": True} in [m["params"] for m in fake.received if m["method"] == "set_setting"]
    assert any("Calibration: not supported" in text for _, text in state.steps)
    assert state.frames >= 3
    assert done["command"]["id_command"]["shots_stacked"] >= 3


def test_program_stop_moves_to_error(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_BASE_DIR", str(tmp_path))
    fake = FakeSeestar(frame_interval=0.1)
    driver = _driver(fake)
    dirs = store.session_dirs("seestar-test", create=True)
    program = {"command": {
        "id_command": {"description": "x"},
        "setup_camera": {"do_action": True, "exposure": "10", "count": "1000"},
    }}
    src = os.path.join(dirs["TODO_DIR"], "x.json")
    json.dump(program, open(src, "w"))
    state = RunState(program_name="x")

    import threading
    threading.Timer(1.0, state.stop_event.set).start()
    try:
        run_program_file(driver, src, dirs, state)
    finally:
        driver.disconnect()
        fake.close()
    assert state.success is False and "Stopped" in state.message
    assert os.path.exists(os.path.join(dirs["ERROR_DIR"], "x.json"))


def test_describe_shows_plan_settings_and_end_time():
    # Needs the upstream app stack (program template); the app imports
    # dwarf_python_api first, which avoids a circular import inside it.
    pytest.importorskip("dwarf_python_api.lib.dwarf_session")
    from smartscopes.programs import describe, new_program

    program = new_program(target="M2", ra=21.558, dec=-0.82, start=datetime(2026, 9, 28, 22, 57, 51),
                          exposure_s=10, gain=80, count=0, end_time="01:12", lp_filter=True)
    program["command"]["id_command"]["tonightplan"] = {
        "visual_impact": "Showstopper", "peak_alt": 35.3, "peak_time": "22:17", "fit": "fits",
        "smart_scope": "Excellent", "imaging_time": "<= 1h", "moon_status": "good"}
    info = describe(program)
    assert info["when"] == "2026-09-28 22:57–01:12"          # end rolls past midnight
    assert info["plan"] == "Showstopper · peak 35° at 22:17 · fits · smart scope: Excellent · suggested <= 1h"
    assert info["settings"] == "10s until stop time · gain 80 · LP filter · autofocus · RA 21.558h Dec -0.82°"
