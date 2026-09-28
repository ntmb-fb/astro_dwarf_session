"""'Tonight from TonightPlan' dialog: ranked targets for this telescope's
Site and field of view; the first two are ticked, the user adjusts, and
the ticked ones become back-to-back programs in the queue."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from nicegui import run, ui

from smartscopes import store, tonightplan as tp
from smartscopes.base import Capability as C
from smartscopes.manager import ScopeDevice
from smartscopes.programs import new_program, save_to_todo

_IMPACT_COLOR = {"Showstopper": "amber-8", "Rewarding": "positive", "Decent": "grey-7", "Subtle": "grey-6"}
_FIT_TEXT = {"yes": "fits", "depends": "fits (orientation)", "tight": "tight fit", "no": "needs mosaic"}
_AUTO_TICK = 2


def _local_tz_name() -> str:
    try:
        import tzlocal
        return tzlocal.get_localzone_name()
    except Exception:
        return "UTC"


def open_tonightplan_dialog(device: ScopeDevice, on_added) -> None:
    from site_registry import get_site_entry, list_site_entries  # upstream module

    driver = device.driver
    model = driver.model
    sites = [s for s in list_site_entries() if s.latitude is not None and s.longitude is not None]
    site_names = [s.name for s in sites]
    default_site = device.entry.options.get("site")
    if default_site not in site_names:
        default_site = site_names[0] if site_names else None

    with ui.dialog() as dialog, ui.card().classes("w-full max-w-3xl"):
        with ui.row().classes("items-center justify-between w-full"):
            ui.label("Tonight from TonightPlan").classes("text-lg")
            ui.link("tonightplan.cosmiccaptures.com", tp.SITE_URL, new_tab=True).classes("text-xs")
        if not sites:
            ui.label("Add a Site with a location first (dashboard → 📍), then choose it in this "
                     "telescope's settings.").classes("text-negative")
            ui.button("Close", on_click=dialog.close).props("flat")
            dialog.open()
            return

        with ui.row().classes("items-end gap-3 w-full"):
            site_sel = ui.select(site_names, value=default_site, label="Location (Site)").classes("w-48")
            sky_sel = ui.select(list(tp.SKY_QUALITIES), label="Your sky",
                                value=device.entry.options.get("tonightplan_sky", "Suburban")).classes("w-32")
            refresh_btn = ui.button(icon="refresh").props("flat round").tooltip("Fetch again from TonightPlan")
        summary = ui.label().classes("text-sm text-grey-7")
        body = ui.column().classes("w-full gap-1")
        with ui.row().classes("items-end gap-3 w-full"):
            exp = (ui.select(list(model.exposures_s), value=model.exposures_s[0], label="Exposure (s)")
                   if model.exposures_s else ui.number("Exposure (s)", value=10)).classes("w-28")
            gain = ui.number("Gain", value=model.default_gain, format="%d").classes("w-20")
            af = ui.checkbox("Autofocus after each goto", value=driver.supports(C.AUTOFOCUS))
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancel", on_click=dialog.close).props("flat")
            add_btn = ui.button("Add to queue")
        ui.label("Ratings and notes © Tim Ciasto / Cosmic Captures. Moon-greyed and "
                 "smart-scope 'Challenging' targets are left out.").classes("text-xs text-grey-6")

    state: dict = {"candidates": [], "checks": {}, "tz": None}

    async def load(force: bool = False) -> None:
        site = get_site_entry(site_sel.value)
        tz_name = site.timezone or _local_tz_name()
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
                lambda: tp.rank_tonight(catalogue, lat=site.latitude, lon=site.longitude, tz_name=tz_name,
                                        sky=sky_sel.value, scope_fov=model.fov_arcmin))
        except tp.TonightPlanError as exc:
            body.clear()
            with body:
                ui.label(str(exc)).classes("text-negative")
            return
        state["candidates"] = candidates
        tz = state["tz"]
        dark = "darkness" if not night.twilight_tier else ("nautical twilight only", "civil twilight only")[night.twilight_tier - 1]
        summary.set_text(f"{site.name}: {dark} {night.evening.astimezone(tz):%H:%M}–"
                         f"{night.morning.astimezone(tz):%H:%M} · Moon {night.moon_illum}% "
                         f"(up to {night.moon_peak_alt}°) · {len(candidates)} targets")
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
                                _FIT_TEXT[c.fit], f"smart scope: {t.get('smart_scope', '?')}",
                                f"suggested {t.get('imaging_time', '?')}"]
                        if c.moon_status == "ok":
                            bits.append("some Moon")
                        ui.label(" · ".join(bits)).classes("text-xs text-grey-7")

    async def add() -> None:
        chosen = [c for c in state["candidates"] if state["checks"].get(c.id) and state["checks"][c.id].value]
        if not chosen:
            ui.notify("Tick at least one target", type="warning")
            return
        slots = tp.schedule(chosen)
        dropped = {c.id for c in chosen} - {c.id for c, _, _ in slots}
        for c, start, end in slots:
            t = c.target
            fr = (t.get("filter_rec") or "").lower()
            local_start = start.astimezone().replace(tzinfo=None)   # scheduler runs on this PC's clock
            local_end = end.astimezone().replace(tzinfo=None)
            program = new_program(
                target=c.label, ra=t["ra_h"], dec=t["dec_d"], start=local_start,
                exposure_s=float(exp.value), gain=int(gain.value), count=0,
                end_time=local_end.strftime("%H:%M"), auto_focus=af.value,
                lp_filter=driver.supports(C.LP_FILTER) and ("dual" in fr or "narrowband" in fr),
            )
            program["command"]["id_command"]["description"] = f"{c.label} ({t['visual_impact']}, TonightPlan)"
            save_to_todo(device.uid, program)
        entry = device.entry
        entry.options["tonightplan_sky"] = sky_sel.value
        store.save_entry(entry)
        msg = f"Queued {len(slots)} program(s)"
        if dropped:
            msg += f"; no room left for {', '.join(sorted(dropped))}"
        ui.notify(msg, type="positive" if not dropped else "warning", multi_line=True)
        if not device.armed:
            ui.notify("Arm the scheduler to run them automatically", type="info")
        dialog.close()
        on_added()

    site_sel.on_value_change(lambda _: load())
    sky_sel.on_value_change(lambda _: load())
    refresh_btn.on_click(lambda: load(force=True))
    add_btn.on_click(add)
    dialog.open()
    ui.timer(0.1, load, once=True)
