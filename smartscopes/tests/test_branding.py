import pytest

from smartscopes import branding


def test_rebrand_titles():
    assert branding.rebrand("Astro Dwarf Session - Logs") == "Smartscope Session - Logs"
    assert branding.rebrand("Astro Dwarf Session — Watch") == "Smartscope Session — Watch"
    assert branding.rebrand("Astro Dwarf") == "Smartscope"
    assert branding.rebrand(None) is None


def test_apply_patches_titles_manifest_and_run(monkeypatch):
    pytest.importorskip("dwarf_python_api.lib.dwarf_session")  # needs the upstream app stack
    from nicegui import ui
    from nicegui.client import Client

    from components import pwa

    calls = {}
    monkeypatch.setattr(ui, "run", lambda *a, **kw: calls.update(kw))
    monkeypatch.setattr(Client, "resolve_title", lambda self: "Astro Dwarf Session - Sites")
    monkeypatch.setattr(branding, "_applied", False)
    monkeypatch.setitem(pwa._MANIFEST, "name", pwa._MANIFEST["name"])
    monkeypatch.setitem(pwa._MANIFEST, "short_name", pwa._MANIFEST["short_name"])
    monkeypatch.setattr(ui, "add_head_html", lambda *a, **kw: None)

    branding.apply()

    assert Client.resolve_title(object()) == "Smartscope Session - Sites"
    ui.run(title="Astro Dwarf Session", port=1)
    assert calls["title"] == "Smartscope Session"
    assert pwa._MANIFEST["name"] == "Smartscope Session" and pwa._MANIFEST["short_name"] == "Smartscope"
