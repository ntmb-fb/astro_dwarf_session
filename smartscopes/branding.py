"""The fork's app name, applied at startup without editing upstream files.

Upstream hard-codes "Astro Dwarf Session" in ~14 places across 11 files
(page titles, native window title, PWA manifest, iOS home-screen title).
Instead of patching each one - and conflicting whenever upstream edits
those lines - apply() rewrites the name where it is *used*:

  * every browser-tab title goes through nicegui's Client.resolve_title();
  * the native window title comes from the one ui.run() call;
  * the install name comes from components.pwa's manifest dict and the
    iOS apple-mobile-web-app-title meta tag.

The dashboard wordmark is literal HTML in pages/dashboard.py and uses
brand_html() through a marked hook line there.
"""
from __future__ import annotations

APP_NAME = "Smartscope Session"
SHORT_NAME = "Smartscope"
_UPSTREAM_NAME = "Astro Dwarf Session"
_UPSTREAM_SHORT = "Astro Dwarf"
_applied = False


def rebrand(text: str | None) -> str | None:
    if not text:
        return text
    return text.replace(_UPSTREAM_NAME, APP_NAME).replace(_UPSTREAM_SHORT, SHORT_NAME)


def brand_html() -> str:
    """Dashboard wordmark, styled like upstream's (accent-coloured middle)."""
    # The wordmark sits right-aligned on the same row as upstream's centred QR
    # button, so it must stay about as wide as "Dwarfium Lite": "Session" is
    # smaller, and hidden on phone-width screens (Quasar's gt-xs).
    return ('Smart<span style="color:#00c896">scope</span>'
            '<span class="gt-xs" style="font-size:0.6em;font-weight:500;margin-left:0.3em">Session</span>')


def apply() -> None:
    global _applied
    if _applied:
        return
    _applied = True

    from nicegui import ui
    from nicegui.client import Client

    original_resolve = Client.resolve_title

    def resolve_title(self) -> str:
        return rebrand(original_resolve(self))

    Client.resolve_title = resolve_title

    original_run = ui.run

    def run(*args, **kwargs):
        if "title" in kwargs:
            kwargs["title"] = rebrand(kwargs["title"])
        return original_run(*args, **kwargs)

    ui.run = run

    from components import pwa  # upstream module; the route serves this dict per request

    pwa._MANIFEST["name"] = APP_NAME
    pwa._MANIFEST["short_name"] = SHORT_NAME
    # iOS reads the home-screen name from this meta tag, added per page by upstream.
    ui.add_head_html(
        "<script>document.addEventListener('DOMContentLoaded', () => {"
        "document.querySelectorAll('meta[name=\"apple-mobile-web-app-title\"]')"
        f".forEach(m => m.content = {SHORT_NAME!r});}});</script>",
        shared=True,
    )
