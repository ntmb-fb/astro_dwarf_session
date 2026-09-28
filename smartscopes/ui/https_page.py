"""/scopes/https - enable HTTPS and walk a phone through trusting it."""
from __future__ import annotations

from typing import Callable

from nicegui import run, ui

from smartscopes import https


def _qr(url: str) -> None:
    import qrcode
    import qrcode.image.svg

    svg = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage).to_string(encoding="unicode")
    ui.html(svg).classes("w-44 h-44 bg-white p-2 rounded")
    ui.label(url).classes("text-xs text-grey-7 break-all")


def build_https_page(target: Callable[[], tuple[str, int]]) -> None:
    @ui.page("/scopes/https", title="Smartscope Session - HTTPS for phones")
    def https_page() -> None:
        from smartscopes.ui.pages import _header

        _header("HTTPS for phones")
        with ui.column().classes("w-full max-w-2xl mx-auto gap-3 p-4"):
            ui.markdown(
                "Android only installs this app as a real full-screen app over **HTTPS**. "
                "This creates a private certificate for your network. You trust it **once** "
                "on each phone; after that it keeps working even if this computer's IP changes."
            )
            content = ui.column().classes("w-full gap-3")

            async def enable() -> None:
                await run.io_bound(lambda: https.ensure_certificates(create_ca=True))
                host, port = target()
                await https.start_relay(port, host)
                render.refresh()

            @ui.refreshable
            def render() -> None:
                if not https.is_enabled():
                    ui.button("Enable HTTPS", icon="lock", on_click=enable)
                    return
                if not https.is_running():
                    ui.label(f"HTTPS is set up but not listening on port {https.HTTPS_PORT} "
                             "(port busy? see the log).").classes("text-negative")
                host, port = target()
                ip = (https.local_ips() or ["localhost"])[0]

                with ui.card().classes("w-full"):
                    ui.label("1. On the phone, download and install the certificate").classes("text-lg")
                    _qr(f"http://{ip}:{port}/smartscope/ca.crt")
                    ui.markdown(
                        "- **Android:** Settings → Security & privacy → More security settings → "
                        "Encryption & credentials → Install a certificate → **CA certificate** → "
                        "pick the downloaded file. (Menu names vary a little by brand.)\n"
                        "- **iPhone/iPad:** open the link in Safari → Settings → *Profile Downloaded* → "
                        "Install; then Settings → General → About → Certificate Trust Settings → "
                        "enable full trust for it."
                    )
                with ui.card().classes("w-full"):
                    ui.label("2. Open the app over HTTPS, then install it").classes("text-lg")
                    _qr(https.https_urls()[0])
                    ui.markdown(
                        "In Chrome: menu ⋮ → **Install app** (or *Add to Home screen*). "
                        "It then opens full screen, without an address bar.\n\n"
                        "Other addresses that work: " + ", ".join(f"`{u}`" for u in https.https_urls()[1:])
                    )
                ui.label(f"Certificates are stored in {https.CERT_DIR}. Plain HTTP on port {port} "
                         "keeps working for this computer.").classes("text-xs text-grey-6")

            with content:
                render()
