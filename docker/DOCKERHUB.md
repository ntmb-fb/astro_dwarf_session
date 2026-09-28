# Smartscope Session

Automated imaging sessions for smart telescopes: **DWARF II / 3 / Mini** and **ZWO Seestar S50 / S50 Pro / S30 / S30 Pro**. It's one web app you run on a NAS or home server and use from any browser, phone or tablet on your network.

- **Mission-control dashboard:** every telescope at a glance, with connection, battery, temperature, storage and live capture progress.
- **Programs and a background scheduler:** goto, autofocus, calibration and capture, queued for the night and started on time, with or without a browser open.
- **Tonight from [TonightPlan](https://tonightplan.cosmiccaptures.com/):** tonight's best targets for your location and scope, ranked Showstopper → Rewarding, with Moon-affected targets left out. Queue a whole night of back-to-back programs in one click.
- **Seestar support:** status, goto, autofocus, stacking, LP filter, park.
- **Full Dwarf support:** pairing, live control, native on-device schedules, session explorer, Milky Way mosaic planner and read-only watch mode, inherited from [astro_dwarf_session](https://github.com/stevejcl/astro_dwarf_session).
- **Installable on your phone:** optional HTTPS so Android and iOS can add it to the home screen as a full-screen app.

Source code and full documentation: **[github.com/ntmb-fb/smartscope-session](https://github.com/ntmb-fb/smartscope-session)**

## Quick start

```sh
docker run -d --name smartscope-session \
  --network host \
  -e TZ=Europe/Copenhagen \
  -v /path/to/smartscope-data:/data \
  --restart unless-stopped \
  <this-image>:latest
```

Then open `http://<server-ip>:8765`.

### Synology (Container Manager)

1. **Registry:** search this image and **Download** tag `latest`.
2. **Image:** select it → **Run**, with these settings:
   - **Network:** `host`
   - **Environment:** `TZ` = your time zone
   - **Volume:** a NAS folder mounted to `/data`
   - **Auto-restart:** on
3. **Open** `http://<nas-ip>:8765`.

**To update:** download the new `latest` image, then **Action → Reset** the container. Your data folder is kept.

## Configuration

| Setting | Default | Notes |
|---|---|---|
| `TZ` | `Europe/Copenhagen` | **Set this to your time zone.** Programs start by local clock time. |
| `PORT` | `8765` | Web UI port. Change it if something else already uses it. |
| `SMARTSCOPE_HTTPS_PORT` | `8443` | HTTPS for phones (optional, enabled from the app). |
| `/data` volume | | Everything the app stores: telescopes, Sites, program queues, logs, HTTPS certificates. Back it up. |

**Why host networking:** the app needs your server's real LAN address, for the Watch-mode QR code and the phone HTTPS certificate. It also talks to the telescopes directly on your network.

## Good to know

- **Telescopes:** must be on the same Wi-Fi network as the server (station mode). A server can't join a telescope's own hotspot.
- **Adding a Dwarf:** Bluetooth pairing isn't available in a container. Use the **Wi-Fi icon** (manual setup) with the IP and UID shown in the DwarfLab app.
- **Seestar firmware 7.18+:** needs an authentication key extracted from ZWO's Seestar app; it isn't included. Put the `.pem` file in your data folder and enter `/data/<file>.pem` in the telescope's settings. The [GitHub README](https://github.com/ntmb-fb/smartscope-session#authentication-key-firmware-718-and-newer) explains how to get it.
- **Platform:** `linux/amd64` (Intel/AMD NAS models such as the Synology DS425+).

## Credits

- **Based on** [astro_dwarf_session](https://github.com/stevejcl/astro_dwarf_session) and [dwarf_python_api](https://github.com/stevejcl/dwarf_python_api) by stevejcl (MIT).
- **Seestar protocol** documented by the [seestar_alp](https://github.com/smart-underworld/seestar_alp) community.
- **Target ratings** by [TonightPlan](https://tonightplan.cosmiccaptures.com/) / Tim Ciasto, fetched live for personal use.

MIT License.
