# Smartscope Session

Automated imaging sessions for smart telescopes: **DWARF II / 3 / Mini** and **ZWO Seestar S50 / S30**, from one local web app on your PC, tablet or phone.

This is a fork of [stevejcl/astro_dwarf_session](https://github.com/stevejcl/astro_dwarf_session). Everything that app does for Dwarfs works here unchanged; see the **[upstream README](../README.md)** for those features (pairing, live control, programs, native schedules, session explorer, Milky Way mosaic planner, watch mode). This fork adds:

- **ZWO Seestar support** (S50, S30): connect, goto, autofocus, stacking, park, a program queue and a background scheduler, side by side with your Dwarfs on the same dashboard.
- **Tonight from [TonightPlan](https://tonightplan.cosmiccaptures.com/)** for Seestars *and* Dwarfs: tonight's best targets for your location and scope, ranked Showstopper → Rewarding, turned into a night of back-to-back programs in one click.
- **HTTPS for phones**, so Android can install the app full-screen from its home screen.
- A **driver interface** for adding other telescope brands later.

The app shows itself as **Smartscope Session** (window, browser tabs, phone install name, dashboard). The fork stays close to upstream and pulls in its updates regularly (see [Keeping up with upstream](#keeping-up-with-upstream)).

---

## Install

Requires Python 3.10+ on Windows, macOS or Linux.

```sh
git clone https://github.com/ntmb-fb/smartscope-session.git smartscope-session
cd smartscope-session
python -m venv venv
# Windows: venv\Scripts\activate      macOS/Linux: source venv/bin/activate
python -m pip install -r requirements.txt -r requirements-smartscopes.txt
python -m pip install -r requirements-local.txt --target .
```

The last line installs the Dwarf control library (`dwarf_python_api`) into the project folder, as upstream requires. [`uv`](https://docs.astral.sh/uv/) works just as well (`uv venv`, `uv pip install ...`).

> **Known issue in `dwarf_python_api` 3.1.1 on Python 3.14:** one of its files is saved in the wrong encoding, and Python 3.14 refuses to load it (`SyntaxError: Non-UTF-8 code ... websockets_testV2.py`). Python 3.10–3.13 are fine. On 3.14, convert it once after installing:
> `iconv -f latin1 -t utf-8 dwarf_python_api/lib/websockets_testV2.py -o tmp && mv tmp dwarf_python_api/lib/websockets_testV2.py`

Run it:

```sh
python astro_dwarf_ui.py              # desktop window
python astro_dwarf_ui.py --no_native  # server only; open http://<pc-ip>:<port> from any device
```

## Run it on a NAS or home server (Docker)

Running the app on an always-on box means scheduled sessions don't depend on your PC being awake, and every phone or tablet on your network can reach it. The [`docker/`](../docker) folder has everything needed.

**Requirements:**

- **NAS:** Docker, e.g. a **Synology** with **Container Manager** (DSM 7.2+). That means an Intel/AMD (x86-64) or 64-bit ARM model; check Synology's Container Manager compatibility list for yours.
- **Telescopes:** on the **same Wi-Fi network as the NAS** (station mode). A NAS can't join a telescope's own hotspot.

**Synology with the ready-made image (easiest):**

GitHub builds a ready-made image for Intel/AMD and ARM NASes on every update: `ghcr.io/ntmb-fb/smartscope-session:latest`.

1. **Add the registry, once:** Container Manager → **Registry** → **Settings** → **Add**, URL `https://ghcr.io`. No login needed.
2. **Download:** select that registry, search `ntmb-fb/smartscope-session`, and download tag `latest`.
3. **Create the container:** Container Manager → **Image** → select it → **Run**:
   - **Network:** `host`
   - **Environment:** `TZ` = your time zone (e.g. `Europe/Copenhagen`). Optionally `PORT` (default **8765**) if that port is taken.
   - **Volume:** a NAS folder, e.g. `/docker/smartscope-session/data`, mounted to `/data`
   - **Auto-restart:** on
4. **Open** `http://<nas-ip>:8765`.

**Updating:** when Container Manager shows an update for the image, download it, then stop the container and choose **Action → Reset** (or re-create it with the same settings). Your data folder is kept.

**Synology, building from source instead:**

1. Download this repo as a ZIP (green **Code** button → *Download ZIP*) and unpack it with File Station into e.g. `/docker/smartscope-session`. Or use `git clone` over SSH, which makes updates easier.
2. Open `docker/docker-compose.yml` and set `TZ` to your time zone (e.g. `Europe/Copenhagen`). Programs start by local clock time, so this matters.
3. Container Manager → **Project** → **Create**. Name it `smartscope-session`, set the path to the repo's **`docker`** folder, and choose *Use existing docker-compose.yml*. Then build and start.
4. Open `http://<nas-ip>:8765`.

**Anywhere else with Docker:**

```sh
docker compose -f docker/docker-compose.yml up -d --build
```

**Good to know:**

- **Data:** all app data (telescopes, Sites, program queues, logs, HTTPS certificates) lives in `docker/data/`. Back it up, and keep it when updating.
- **Updating:** replace the code (or `git pull`), then in Container Manager open the project → **Action** → **Build**. Your data folder is untouched.
- **Host networking:** the container uses the NAS's own network (`network_mode: host`), so the app knows its real LAN address for the Watch QR code and HTTPS. It also reaches your telescopes directly.
- **Ports:** web UI on **8765**. Change with `PORT` if something else uses it; HTTPS for phones is on 8443 (`SMARTSCOPE_HTTPS_PORT`). If the NAS firewall is on, allow them.
- **Pairing a Dwarf:** Bluetooth pairing isn't available in a container. Use the **Wi-Fi icon** (manual setup) with the IP and UID shown in the DwarfLab app.
- **Seestar key:** put your `.pem` file in `docker/data/` and enter `/data/<file>.pem` as its path in the telescope's settings.
- **Desktop window:** the container runs as a server only; there's no desktop window. Use a browser, or install the app on your phone (HTTPS for phones).

## Quick start

1. **Add a Site** (📍 on the dashboard): a name, your location and time zone. Sites feed the telescopes' clocks and TonightPlan.
2. **Add your telescopes:**
   - **Dwarf:** use **+** or the Wi-Fi icon at the top of the dashboard, as described in the [upstream README](../README.md).
   - **Seestar:** under **Other smart telescopes**, tap **+**, pick the model and enter its IP address: its address on your Wi-Fi in station mode, or `10.0.0.1` on its own hotspot. Choose your Site.
3. **Plan tonight:** open the telescope, tap **Tonight from TonightPlan** (Seestar page) or the **✨** icon (Dwarf Programs page), keep or change the two pre-ticked targets, and tap **Add to queue**.
4. **Arm the scheduler** on that telescope. Queued programs then start by themselves at their times, even with no browser open.

## Seestar

### Authentication key (firmware 7.18 and newer)

Recent Seestar firmware only accepts commands from apps that sign in with a private key that ships inside ZWO's own Seestar app. This project does not include that key; you extract it once yourself, for example with [seestar-tool](https://github.com/bguthro/seestar-tool) ("Extract PEM Key"). [seestar_alp](https://github.com/smart-underworld/seestar_alp) documents the same process.

Save it as a `.pem` file and enter its path in the telescope's **Settings** in the app. Older firmware works without it. If the key is missing or wrong, **Connect** fails with *"no reply ... (auth key required by this firmware?)"*.

### What you can do

- **Status:** battery, temperature, free storage, position, stacking progress (frames stacked and dropped).
- **Manual control:** goto by RA/Dec, autofocus, start/stop stacking, LP filter, park, stop all.
- **Programs:** target, coordinates, start time, exposure (10/20/30 s), gain, frame count and/or stop time, autofocus, LP filter. Choose *Run now* or *Add to queue*. The queue shows each program's time window, settings, TonightPlan info and, once finished, its result.
- **Scheduler:** off by default; when armed, due programs start automatically, one after another.

Program files use the same format as the Dwarf side. They move through `Devices_Sessions/<telescope-id>/Astro_Sessions/{ToDo,Current,Done,Error}`. Compared with the Dwarf runner, autofocus runs *after* the goto, and steps a Seestar can't do (calibration, wide camera) are logged and skipped instead of failing the run.

**Not yet supported:** the Seestar's own mosaic mode (it exists in ZWO's app, but its command isn't documented and needs testing on a real scope), and solar-system gotos.

## Tonight from TonightPlan

Builds tonight's target list from [TonightPlan](https://tonightplan.cosmiccaptures.com/) by Tim Ciasto / Cosmic Captures, using the same rules as the site itself for your location, sky and scope.

- **Location:** the telescope's Site, or a Dwarf's own configured location; you can pick another in the dialog.
- **Scope:** your model's field of view, as listed by TonightPlan (Seestar S50 44′ × 77′, S30 84′ × 148′, Dwarf 3 176′ × 99′, Dwarf II 191′ × 108′, Dwarf Mini 128′ × 72′). It decides *fits / tight fit / needs mosaic*.
- **Your sky:** City, Suburban, Rural or Dark, remembered per telescope. Targets that need darker skies are hidden, as on the site.
- **Left out:** targets the site greys out because of the Moon, targets rated *Challenging* for smart telescopes, and anything out of season or with less than 50 minutes above 20°.
- **Order:** Showstopper, then Rewarding, then the rest; within each group, the site's own score, with mosaic-only targets last. The first two are ticked.
- **Scheduling:** ticked targets become back-to-back programs in the order they cross the sky. Each target's slot ends halfway to the next one's transit, and nothing starts in the past. A target left with under 30 minutes is skipped, with a message.
- **Filter:** where the site recommends a dual-band or narrowband filter, a Seestar turns on its LP filter and a Dwarf 3 / Mini uses Duo-Band; otherwise a Dwarf uses its Astro filter.
- **Dwarf extras:** only the night's first program calibrates (and autofocuses, if ticked). Targets bigger than the frame use the Dwarf's built-in mosaic (up to 1.8 × 1.8). Programs land in the Dwarf's normal Scripts queue and run with upstream's own Dwarf runner.

TonightPlan has no official data feed. The app reads the catalog from the site's page at most once a day, caches it locally in `Devices_Sessions/` (never committed), and recalculates the plan with the same astronomy library the site uses. Checked against the site's own code: identical results for all 221 targets across five nights and locations. If the site changes its page layout, the dialog says *"catalogue not found"* instead of guessing. The site's per-location skyline (trees, buildings) isn't available, because it only lives in your browser.

## HTTPS for phones

Android Chrome only installs web apps full-screen over HTTPS. On the dashboard, tap the **🔒** icon next to *Other smart telescopes*, then **Enable HTTPS**. The page shows two QR codes:

1. **Download the certificate** to your phone and install it once:
   - **Android:** *Settings → Security & privacy → More security settings → Encryption & credentials → Install a certificate → CA certificate*.
   - **iPhone / iPad:** install the profile, then enable it under *Settings → General → About → Certificate Trust Settings*.
2. **Open `https://<pc-ip>:8443/`** in Chrome, then tap *⋮ → Install app*.

The app creates its own small certificate authority for your network. The certificate is renewed automatically when your PC's IP changes, so each phone is set up only once. That authority is restricted to private network addresses and `.local` names, so it can't be misused for real websites. Plain HTTP and the desktop window keep working as before.

- **Files:** stored in `~/.smartscope_session/https/`. Change with `SMARTSCOPE_CERT_DIR`, and the port with `SMARTSCOPE_HTTPS_PORT`.
- **Firewall:** allow TCP 8443 if your PC runs one.

---

## Keeping up with upstream

| Branch | Content |
|---|---|
| `NiceGui_V3_multi` | Exact mirror of upstream. Never commit here. |
| `smartscope` | Upstream plus this fork's additions. The default branch; work here. |

```sh
tools/sync-upstream.sh           # fetch and merge upstream into smartscope, run the tests
tools/sync-upstream.sh --deps    # ...also update dwarf_python_api
tools/sync-upstream.sh --push    # ...and push both branches to GitHub
```

`git rerere` is enabled, so a merge conflict you resolve once is resolved the same way next time. The optional [sync workflow](workflows/sync-upstream.yml) does the same merge daily on GitHub, opening a PR when it's clean and the tests pass, or an issue when it conflicts. It runs only if Actions is enabled for the fork.

**Why merges stay easy:** all fork code lives in new files:

- `smartscopes/`
- `requirements-smartscopes.txt`
- `tools/sync-upstream.sh`
- `docker/` and `.dockerignore`
- this README, in `.github/`, which GitHub shows instead of upstream's root `README.md`, left untouched

Upstream files are changed in only four places, each marked `smartscopes hook`:

| File | Hook | Adds |
|---|---|---|
| `astro_dwarf_ui.py` | `smartscopes.install()` | pages, scheduler, HTTPS, app name |
| `pages/dashboard.py` | `smartscopes.render_dashboard_section()` | the *Other smart telescopes* cards |
| `pages/dashboard.py` | `smartscopes.brand_html()` | the *Smartscope Session* wordmark |
| `pages/programs.py` | `smartscopes.dwarf_tonightplan_button()` | the ✨ button on Dwarf Programs pages |

The app name itself is applied at startup by `smartscopes/branding.py`, which renames upstream's titles, window title and install name where they're used, so the ~14 "Astro Dwarf Session" strings in upstream code stay untouched.

Keep it that way: new behavior belongs in `smartscopes/`. Generic fixes to upstream code are better sent to stevejcl as pull requests.

## Architecture

```
smartscopes/
├── base.py          ScopeDriver interface, Capability, ModelInfo, ScopeEntry, ScopeStatus
├── registry.py      protocol name -> driver class (@register_driver)
├── drivers/
│   ├── __init__.py  imports every driver package (add new ones here)
│   └── seestar/     client.py (JSON-RPC over TCP 4700, auth, events) + driver.py
├── runner.py        runs an upstream-format program on any driver; file lifecycle
├── manager.py       live devices, background program threads, scheduler tick
├── store.py         Devices_Sessions/smartscopes.json + per-device session folders
├── programs.py      build/list/describe program files (reuses upstream's template)
├── coords.py        RA/Dec parsing (decimal or sexagesimal)
├── tonightplan.py   TonightPlan catalogue fetch + port of its planning rules
├── plan_targets.py  per-scope adapters for the TonightPlan dialog (drivers, Dwarfs)
├── https.py         private CA + auto-renewed server certificate + TLS relay (port 8443)
├── branding.py      "Smartscope Session" name applied at startup
├── ui/              dashboard section, /scopes/... pages, TonightPlan dialog, HTTPS setup
└── tests/           fake Seestar TCP server + protocol, runner and planner tests
```

Dwarfs still go entirely through upstream's code (`dwarf_python_api`, `DwarfManager`, `dwarf_session.py`). Run the tests with `python -m pytest smartscopes/tests`.

## Adding another telescope

1. Create `smartscopes/drivers/<name>/driver.py` with a `ScopeDriver` subclass:
   - `protocol`, `protocol_display_name`, `default_port`
   - `models`: one `ModelInfo` per model, with its `Capability` set and field of view
   - `option_fields` for extra settings such as an API key; the add/edit form renders them automatically
   - `connect`, `disconnect`, `is_connected`, `get_status`, plus whatever the device supports: `goto`, `auto_focus`, `start_capture`, `capture_progress`, `stop_capture`, ...
2. Decorate it with `@register_driver` and import the package in `smartscopes/drivers/__init__.py`.
3. Add a fake-device test next to `smartscopes/tests/test_seestar.py`.

The dashboard, pages, program runner, scheduler and TonightPlan dialog pick it up with no other changes.

**DWARF Draco and future DwarfLab models:** if they use the same protocol as the Dwarf 3, support belongs upstream (in `dwarf_python_api` and the model list) and arrives here with the next sync.

## Known upstream issues

To report to stevejcl:

- **`dwarf_python_api/lib/dwarf_utils.py`, `parse_dec_to_float`:** the minus sign applies only to the degrees, so `-05:23:28` becomes −4.61° instead of −5.39°. It affects declinations entered as text; decimal values from the program editor are fine.
- **`dwarf_python_api/lib/websockets_testV2.py`:** saved as Latin-1, so Python 3.14 refuses to import it (workaround under [Install](#install); the Docker image uses Python 3.12 and isn't affected).

## Credits

- **[astro_dwarf_session](https://github.com/stevejcl/astro_dwarf_session)** and **[dwarf_python_api](https://github.com/stevejcl/dwarf_python_api)** by stevejcl: the app this fork builds on (MIT).
- **[seestar_alp](https://github.com/smart-underworld/seestar_alp):** the community's documentation of the Seestar protocol; the Seestar client here is an independent implementation.
- **[TonightPlan](https://tonightplan.cosmiccaptures.com/)** by Tim Ciasto / Cosmic Captures: target ratings and notes, fetched live for personal use.
- **[Astronomy Engine](https://github.com/cosinekitty/astronomy)** by Don Cross (MIT): sun, Moon and target positions.

MIT License, as upstream (see [LICENSE](../LICENSE)).
