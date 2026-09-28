"""'Tonight from TonightPlan' dialog: ranked targets for a telescope's
location and field of view; the first two are ticked, the user adjusts,
and the ticked ones become back-to-back programs in its queue. Works for
any telescope through a PlanTarget adapter (smartscopes/plan_targets.py)."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

from nicegui import run, ui

from smartscopes import tonightplan as tp
from smartscopes.plan_targets import FIT_TEXT, PlanOptions, PlanTarget, get_pref, set_pref

_IMPACT_COLOR = {"Showstopper": "amber-8", "Rewarding": "positive", "Decent": "grey-7", "Subtle": "grey-6"}
_AUTO_TICK = 2


def _local_tz_name() -> str:
    try:
        import tzlocal
        return tzlocal.get_localzone_name()
    except Exception:
        return "UTC"


def open_tonightplan_dialog(target: PlanTarget, on_added: Callable[[], None]) -> None:
    locations = {loc.label: loc for loc in target.locations()}

    with ui.dialog() as dialog, ui.card().classes("w-full max-w-3xl"):
        with ui.row().classes("items-center justify-between w-full"):
            ui.label(f"Tonight from TonightPlan · {target.scope_name}").classes("text-lg")
            ui.link("tonightplan.cosmiccaptures.com", tp.SITE_URL, new_tab=True).classes("text-xs")
        if not locations:
            ui.label("No location known: add a Site with a location first (dashboard → 📍).").classes("text-negative")
            ui.button("Close", on_click=dialog.close).props("flat")
            dialog.open()
            return

        default_loc = get_pref(target.uid, "tonightplan_location") or target.default_location()
        if default_loc not in locations:
            default_loc = next(iter(locations))
        with ui.row().classes("items-end gap-3 w-full"):
            loc_sel = ui.select(list(locations), value=default_loc, label="Location").classes("min-w-48")
            sky_sel = ui.select(list(tp.SKY_QUALITIES), label="Your sky",
                                value=get_pref(target.uid, "tonightplan_sky", "Suburban")).classes("w-32")
            refresh_btn = ui.button(icon="refresh").props("flat round").tooltip("Fetch again from TonightPlan")
        summary = ui.label().classes("text-sm text-grey-7")
        body = ui.column().classes("w-full gap-1")
        with ui.row().classes("items-end gap-3 w-full"):
            exp = ui.select(target.exposures, value=target.default_exposure, label="Exposure (s)").classes("w-28")
            gain = ui.number("Gain", value=target.default_gain, format="%d").classes("w-20")
            af = ui.checkbox(target.autofocus_label, value=target.autofocus_default)
        with ui.row().classes("gap-4"):
            use_filter = ui.checkbox(target.filter_label, value=True) if target.filter_label else None
            mosaic = (ui.checkbox("Mosaic for targets bigger than the frame", value=True)
                      if target.supports_mosaic else None)
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancel", on_click=dialog.close).props("flat")
            add_btn = ui.button("Add to queue")
        ui.label("Ratings and notes © Tim Ciasto / Cosmic Captures. Moon-greyed and "
                 "smart-scope 'Challenging' targets are left out.").classes("text-xs text-grey-6")

    state: dict = {"candidates": [], "checks": {}, "tz": None}

    async def load(force: bool = False) -> None:
        loc = locations[loc_sel.value]
        tz_name = loc.tz or _local_tz_name()
        try:
            ZoneInfo(tz_name)
        except Exception:
            tz_name = _local_tz_name()
        state["tz"] = ZoneInfo(tz_name)
        body.clear()
        with body:
            ui.spinner()
        try:
            catalogue = await run.io_bound(tp.fetch_catalogue, force=force)
            night, candidates = await run.io_bound(
                lambda: tp.rank_tonight(catalogue, lat=loc.lat, lon=loc.lon, tz_name=tz_name,
                                        sky=sky_sel.value, scope_fov=target.fov))
        except tp.TonightPlanError as exc:
            body.clear()
            with body:
                ui.label(str(exc)).classes("text-negative")
            return
        state["candidates"] = candidates
        tz = state["tz"]
        dark = "darkness" if not night.twilight_tier else ("nautical twilight only", "civil twilight only")[night.twilight_tier - 1]
        summary.set_text(f"{dark} {night.evening.astimezone(tz):%H:%M}–{night.morning.astimezone(tz):%H:%M} · "
                         f"Moon {night.moon_illum}% (up to {night.moon_peak_alt}°) · {len(candidates)} targets")
        render()

    def render() -> None:
        body.clear()
        tz = state["tz"]
        state["checks"] = {}
        with body:
            if not state["candidates"]:
                ui.label("Nothing suitable tonight (bright Moon?). Try another night.").classes("text-grey-7")
                return
            for i, c in enumerate(state["candidates"]):
                t = c.target
                with ui.row().classes("items-center w-full gap-2 no-wrap"):
                    state["checks"][c.id] = ui.checkbox(value=i < _AUTO_TICK)
                    ui.badge(t["visual_impact"], color=_IMPACT_COLOR.get(t["visual_impact"], "grey")).classes("w-24")
                    with ui.column().classes("gap-0 grow"):
                        ui.label(c.label).classes("text-sm")
                        bits = [f"{c.window_start.astimezone(tz):%H:%M}–{c.window_end.astimezone(tz):%H:%M}",
                                f"peak {c.peak_alt:.0f}° at {c.peak_time.astimezone(tz):%H:%M}",
                                FIT_TEXT[c.fit], f"smart scope: {t.get('smart_scope', '?')}",
                                f"suggested {t.get('imaging_time', '?')}"]
                        if c.moon_status == "ok":
                            bits.append("some Moon")
                        ui.label(" · ".join(bits)).classes("text-xs text-grey-7")

    async def add() -> None:
        chosen = [c for c in state["candidates"] if state["checks"].get(c.id) and state["checks"][c.id].value]
        if not chosen:
            ui.notify("Tick at least one target", type="warning")
            return
        slots = tp.schedule(chosen, not_before=datetime.now().astimezone() + timedelta(minutes=2))
        dropped = {c.id for c in chosen} - {c.id for c, _, _ in slots}
        opts = PlanOptions(exposure=str(exp.value), gain=int(gain.value or target.default_gain),
                           autofocus=af.value, use_filter=bool(use_filter and use_filter.value),
                           mosaic=bool(mosaic and mosaic.value))
        try:
            target.save_programs(slots, opts, state["tz"])
        except Exception as exc:
            ui.notify(f"Could not save programs: {exc}", type="negative", multi_line=True)
            return
        set_pref(target.uid, "tonightplan_sky", sky_sel.value)
        set_pref(target.uid, "tonightplan_location", loc_sel.value)
        msg = f"Queued {len(slots)} program(s)"
        if dropped:
            msg += f"; no room left for {', '.join(sorted(dropped))}"
        ui.notify(msg, type="positive" if not dropped else "warning", multi_line=True)
        if not target.is_armed():
            ui.notify("Arm the scheduler to run them automatically", type="info")
        dialog.close()
        on_added()

    loc_sel.on_value_change(lambda _: load())
    sky_sel.on_value_change(lambda _: load())
    refresh_btn.on_click(lambda: load(force=True))
    add_btn.on_click(add)
    dialog.open()
    ui.timer(0.1, load, once=True)
