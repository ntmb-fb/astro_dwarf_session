"""Support for non-Dwarf smart telescopes (ZWO Seestar, ...), kept in its
own package so the fork stays easy to merge with upstream.

The upstream code touches this package in exactly two places, both marked
"smartscopes hook":
  * astro_dwarf_ui.py  -> smartscopes.install()
  * pages/dashboard.py -> smartscopes.render_dashboard_section()

See SMARTSCOPE.md for the architecture and how to add a new telescope.
"""
from __future__ import annotations

_SCHEDULER_INTERVAL_S = 15.0


def install() -> None:
    """Call once at startup: registers drivers, pages and the scheduler."""
    from nicegui import app

    import smartscopes.drivers  # noqa: F401  (registers every driver)
    from smartscopes.manager import get_scope_manager, scheduler_tick
    from smartscopes.ui.pages import build_pages

    get_scope_manager()
    build_pages()
    app.timer(_SCHEDULER_INTERVAL_S, scheduler_tick)

    def _shutdown() -> None:
        for device in get_scope_manager().all():
            device.request_stop()
            device.driver.disconnect()

    app.on_shutdown(_shutdown)


def render_dashboard_section() -> None:
    from smartscopes.ui.dashboard import render_dashboard_section as render

    render()
