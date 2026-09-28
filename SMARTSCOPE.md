# Smartscope fork

This fork of [stevejcl/astro_dwarf_session](https://github.com/stevejcl/astro_dwarf_session)
adds non-Dwarf smart telescopes, starting with the **ZWO Seestar S50** (and S30),
while staying easy to merge with upstream.

## Branches and staying up to date

| Branch | Content |
|---|---|
| `NiceGui_V3_multi` | Pure mirror of upstream. Never commit here. |
| `smartscope` | Upstream + this fork's additions. Work here. |

To pull in upstream changes:

```sh
tools/sync-upstream.sh           # fetch + merge upstream into smartscope, run tests
tools/sync-upstream.sh --deps    # ...also update dwarf_python_api
tools/sync-upstream.sh --push    # ...and push both branches to your fork
```

`git rerere` is turned on, so a conflict you have resolved once gets resolved
the same way automatically after that. The optional workflow
`.github/workflows/sync-upstream.yml` does the same merge once a day on GitHub.
It opens a PR when the merge is clean and the tests pass, or an issue when there
is a conflict. It only runs if Actions is enabled for the fork.

### Why merges stay easy

All fork code lives in **new files**:

- `smartscopes/`
- `requirements-smartscopes.txt`
- `tools/sync-upstream.sh`
- `SMARTSCOPE.md`

Upstream files are touched in only **two places**, each marked `smartscopes hook`:

- `astro_dwarf_ui.py`: `smartscopes.install()` registers the pages and the scheduler.
- `pages/dashboard.py`: `smartscopes.render_dashboard_section()` adds the telescope cards.

Keep it that way. When a change seems to need an edit inside an upstream file,
prefer calling into upstream from `smartscopes/`. If a generic improvement
belongs in upstream, send it as a PR to stevejcl instead.

## Setup

Follow the upstream README, then:

```sh
pip install -r requirements-smartscopes.txt
```

### Seestar authentication

Seestar firmware **7.18 and newer** only accepts commands from a client that
signs a challenge with ZWO's private key. That key ships inside the official
Seestar app and has to be extracted from it. This fork does not include it.
Community tools can extract it from the APK, for example
[seestar-tool](https://github.com/bguthro/seestar-tool) ("Extract PEM Key"). The
[seestar_alp](https://github.com/smart-underworld/seestar_alp) project documents
the same process.

Save the key as a `.pem` file and enter its path in the telescope's settings in
the app. Older firmware works without it.

Symptom of a missing or wrong key: *Connect* fails with "no reply ... (auth key
required by this firmware?)".

## Using a Seestar

1. On the dashboard, under **Other smart telescopes**, tap **+**. Pick *Seestar
   S50*, then enter its IP address (station mode on your Wi-Fi, or `10.0.0.1` on
   its own hotspot) and optionally a Site, which pushes location and time zone
   to the scope.
2. On the telescope's page:
   - **Connect** shows battery, temperature, storage, position and stacking progress.
   - **New program**: target + RA/Dec, start time, exposure (10/20/30 s), gain,
     frame count and/or stop time, autofocus, LP filter. Use *Run now* or *Add to queue*.
   - **Scheduler armed**: queued programs start automatically at their time.
     It is off by default, as on the Dwarf side.
   - **Manual control**: goto, autofocus, start/stop stacking, park.

Program files use the upstream format and live in
`Devices_Sessions/<telescope-id>/Astro_Sessions/{ToDo,Current,Done,Error}`.
Two differences from the Dwarf runner:

- Autofocus runs *after* the goto.
- Steps the device doesn't support (calibration, wide camera, infinite focus)
  are logged and skipped instead of failing the run.

## HTTPS for phones (installable app on Android)

Android Chrome only installs the app as a real full-screen app when it is
served over HTTPS. On the dashboard, tap the **lock** icon next to *Other
smart telescopes*, then tap **Enable HTTPS**. The page then shows two QR codes:

1. **Download the certificate** onto the phone and install it once:
   - Android: *Settings → Security & privacy → More security settings →
     Encryption & credentials → Install a certificate → CA certificate*.
   - iOS: install the profile, then enable it under *Settings → General →
     About → Certificate Trust Settings*.
2. **Open `https://<pc-ip>:8443/`** in Chrome, then use *⋮ → Install app*.

How it works:

- A private certificate authority (CA) signs a certificate for this PC's LAN
  IPs and `<hostname>.local`.
- The app reissues that certificate automatically when the IP changes, so a
  phone only needs setting up once.
- The CA is name-constrained to private IPs, `localhost` and `.local`. A leaked
  CA key therefore cannot be used against real websites.
- A small in-process TLS relay on port 8443 forwards to the normal HTTP port.
  Plain HTTP and the desktop window are unchanged.
- Certificates are stored in `~/.astro_dwarf_session/https/`. Set
  `SMARTSCOPE_CERT_DIR` to use another folder, or `SMARTSCOPE_HTTPS_PORT` to
  use another port.
- If the PC runs a firewall, allow TCP 8443.

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
├── programs.py      build/list program files (reuses upstream's program template)
├── coords.py        RA/Dec parsing (decimal or sexagesimal)
├── https.py         private CA + auto-renewed server cert + TLS relay (port 8443)
├── ui/              dashboard section + /scopes/... pages (incl. /scopes/https setup)
└── tests/           fake Seestar TCP server + protocol/runner tests
```

Dwarf devices are unchanged and still go through upstream's own code
(`dwarf_python_api`, `DwarfManager`, `dwarf_session.py`).

## Adding another telescope

1. Create `smartscopes/drivers/<name>/driver.py` with a `ScopeDriver` subclass:
   - `protocol`, `protocol_display_name`, `default_port`
   - `models`: one `ModelInfo` per model, each with its set of `Capability` values
   - `option_fields` for any extra settings, for example an API key. The
     add/edit form renders these automatically.
   - `connect`, `disconnect`, `is_connected`, `get_status`, plus the operations
     the device supports: `goto`, `auto_focus`, `start_capture`,
     `capture_progress`, `stop_capture`, and so on.
2. Decorate the class with `@register_driver` and import the package in
   `smartscopes/drivers/__init__.py`.
3. Add a fake-device test next to `smartscopes/tests/test_seestar.py`.

The UI, program runner, scheduler and dashboard pick it up with no other changes.

**DWARF Draco / future DwarfLab models:** if they use the same protocol as the
Dwarf 3, support belongs in upstream (`dwarf_python_api` plus the model list) and
arrives with the next sync. Write a driver here only if upstream doesn't add it.

## Known upstream issues (to report to stevejcl)

- `dwarf_python_api/lib/dwarf_utils.py`, `parse_dec_to_float`: the sign applies
  only to the degrees (`sign * degrees + minutes/60 ...`), so `-05:23:28` gives
  -4.61° instead of -5.39°. This matters for string Dec values; decimal values
  from the program editor are not affected.
- `dwarf_python_api/lib/websockets_testV2.py` is saved as Latin-1, which Python 3
  refuses to import (`SyntaxError: Non-UTF-8 code`). Workaround:
  `iconv -f latin1 -t utf-8`.
