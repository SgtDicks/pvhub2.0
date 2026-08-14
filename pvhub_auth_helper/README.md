# pvhub_auth_helper

A standalone headless-browser script that logs into pv-hub.com and keeps
your PVHub Home Assistant integration's `Cookie` / `Token` / `Signature` /
`Timestamp` headers fresh automatically. It supports two delivery modes --
**push** and **file** -- pick whichever fits your setup, or run both.

**This does not run inside Home Assistant.** Playwright needs a real
Chromium binary and OS packages that HAOS/Supervised installs can't
provide. Run it as a small sidecar next to HA instead -- a container, a
cron job on the same box, a Raspberry Pi, whatever's convenient.

## Push vs. file: how to decide

| | Push | File |
|---|---|---|
| How it works | Script drives HA's own **reconfigure flow** over its config-entries HTTP API (same as the "Configure" button) | Script writes headers to a JSON file; integration re-reads it every poll |
| Setup | Needs an HA long-lived access token | Needs a filesystem path both sides can reach |
| Works across machines | Yes -- any network path to HA | Only if you can mount/share the same file (e.g. same host, or a synced/NFS volume) |
| Credential exposure | An HA long-lived token is **account-wide** -- it can call any service your user can, not just this one | No HA credential at all; just filesystem access, which you can scope tightly (e.g. read-only bind mount) |
| Good fit when | Helper runs on a different machine/network than HA, and you're comfortable placing a token there | Helper runs alongside HA (same host or easily shared volume), and you'd rather not hand out an HA token |

Both call the exact same Playwright login/capture logic -- this is purely
about how the result gets to Home Assistant. Fill in both sets of `.env`
variables below if you want both at once.

## Quick start with docker compose (recommended)

Requires **Docker Compose v2** (the `docker compose` plugin, no hyphen) --
see the troubleshooting note at the bottom if you're on the old,
deprecated `docker-compose` v1 and hit an error.

```bash
cd pvhub_auth_helper
cp .env.example .env
# edit .env: fill in login/plant URLs + credentials, and either the
# HA_TOKEN/PVHUB_HA_URL block (push) or PVHUB_OUTPUT (file), or both

docker compose up -d --build
docker compose logs -f
```

Every option -- push, file, both, or neither while you test with
`PVHUB_LOOP_INTERVAL=0` -- is controlled entirely through `.env`; no
need to edit `docker-compose.yml` or pass a `command:` override.

## Manual `docker run` (if you'd rather not use compose)

### Push mode

Create a token: your HA profile page (bottom-left avatar) -> **Security**
tab -> **Long-Lived Access Tokens** -> **Create Token**.

```bash
docker build -t pvhub-auth-helper .

docker run -d --name pvhub-auth-helper \
  -e PVHUB_USERNAME="you@example.com" \
  -e PVHUB_PASSWORD="yourpassword" \
  -e HA_TOKEN="your-long-lived-access-token" \
  -e PVHUB_LOGIN_URL="https://www.pv-hub.com/login" \
  -e PVHUB_PLANT_URL="https://www.pv-hub.com/v2/plants/analysis?GROUPID=YOUR_PLANT_ID" \
  -e PVHUB_HA_URL="http://homeassistant.local:8123" \
  -e PVHUB_PLANT_ID="YOUR_PLANT_ID" \
  -e PVHUB_LOOP_INTERVAL="1500" \
  pvhub-auth-helper
```

The integration's `auth_mode` setting (manual/file) doesn't matter for
push -- it overwrites the stored headers directly regardless.

### File mode

```bash
docker run -d --name pvhub-auth-helper \
  -e PVHUB_USERNAME="you@example.com" \
  -e PVHUB_PASSWORD="yourpassword" \
  -e PVHUB_LOGIN_URL="https://www.pv-hub.com/login" \
  -e PVHUB_PLANT_URL="https://www.pv-hub.com/v2/plants/analysis?GROUPID=YOUR_PLANT_ID" \
  -e PVHUB_OUTPUT="/shared/pvhub_auth.json" \
  -e PVHUB_LOOP_INTERVAL="1500" \
  -v /path/on/host/shared:/shared \
  pvhub-auth-helper
```

Mount `/shared` as (or symlink it into) a folder Home Assistant can read --
e.g. a subfolder of your HA `config/` directory -- then set the
integration's `auth_mode` to `file` and point `auth_file_path` at it.

## Bare Python (no Docker)

```bash
pip install -r requirements.txt
playwright install --with-deps chromium

# Either export the PVHUB_*/HA_TOKEN env vars from .env, or pass flags:
python capture_headers.py \
  --login-url "https://www.pv-hub.com/login" \
  --plant-url "https://www.pv-hub.com/v2/plants/analysis?GROUPID=YOUR_PLANT_ID" \
  --username "you@example.com" \
  --password "yourpassword" \
  --output /config/pvhub_auth.json \
  --loop-interval 1500
```

Run it under cron, systemd, or `screen`/`tmux` for `--loop-interval 0` runs
on a timer instead of the built-in loop.

## Why a headless *browser* instead of just replaying the login request

pv-hub.com signs its API requests client-side using `signature.js` /
`signature.wasm`. Rather than reverse-engineer that signing algorithm,
this script drives a real Chromium instance through an actual login, so
the portal's own JS generates the Token/Signature/Timestamp exactly the
way it would for you in a normal browser. It only ever does the same two
things you'd do by hand: log in, and open the read-only Analysis page.

## Flags/env vars you may need to adjust

pv-hub.com's login page markup isn't publicly documented, so the default
CSS selectors are best-effort guesses. If login fails, inspect the login
page's HTML and override (flag / equivalent env var):

- `--username-selector` / `PVHUB_USERNAME_SELECTOR` (default targets
  `input[type=email]` or `name` containing "user"/"email")
- `--password-selector` / `PVHUB_PASSWORD_SELECTOR` (default:
  `input[type=password]`)
- `--submit-selector` / `PVHUB_SUBMIT_SELECTOR` (default targets a submit
  button or one labelled "Log"/"Sign")
- `--dismiss-selector` / `PVHUB_DISMISS_SELECTOR` -- optional, clicks a
  cookie/consent overlay button before filling the login form, if one is
  in the way (no default; only used if set)
- `--debug-dir` / `PVHUB_DEBUG_DIR` -- where failure screenshots/HTML land
  (default `/app/debug` in Docker, mounted to `./debug` on the host)
- `--headless` / `PVHUB_HEADLESS` -- set to `0` for a visible browser
  window when debugging outside Docker (default: `1`)
- `--api-url-match` / `PVHUB_API_URL_MATCH` -- substring used to recognize
  the Analysis API request among all network traffic (default:
  `"analysis"`)

If pushing and you have more than one PVHub plant configured in Home
Assistant, set `--plant-id`/`PVHUB_PLANT_ID` (or `--entry-id`/
`PVHUB_ENTRY_ID`) so the push targets the right config entry -- otherwise
the service call is rejected as ambiguous.

Run with `-v`/`PVHUB_VERBOSE=1` for verbose logs while you dial these in.
Secrets -- password, cookie, token, signature, HA access token -- are
never printed, only redacted previews and lengths.

## Output format (file mode)

```json
{
  "cookie": "...",
  "token": "...",
  "signature": "...",
  "timestamp": "...",
  "captured_at": "2026-08-03T09:15:02+0000"
}
```

## Things to know before running this unattended

- Whichever mode you pick, your pv-hub.com password sits in this
  container/process's environment. Treat the host it runs on like you'd
  treat anything with your solar portal password.
- Push mode additionally puts an HA long-lived access token in that same
  environment. Those tokens are account-wide -- there's no way to scope
  one to just this service call -- so it's effectively a key to
  everything your HA user can do. If that's a bigger risk than you want
  to take on, file mode sidesteps it entirely at the cost of needing a
  shared filesystem path.
- Automating login isn't the same as browsing normally, and pv-hub.com's
  signed-request scheme is itself a sign they don't especially want
  automated access. A 25-minute default loop is deliberately conservative
  -- don't tighten it much without a reason, and expect this to break
  silently if they change their login flow or add a bot check.
- If a run fails (selector mismatch, MFA prompt, CAPTCHA, etc.) the script
  logs an error and exits non-zero (single-shot) or keeps retrying on the
  next loop interval (loop mode) -- it does not attempt to solve CAPTCHAs
  or bypass MFA.

## Debugging a login-selector failure (e.g. "Timeout 30000ms exceeded ... waiting for locator")

The default selectors are guesses -- pv-hub.com's real login markup isn't
documented. When a fill/click fails, the script now automatically saves a
full-page screenshot and the page's HTML to `--debug-dir`/`PVHUB_DEBUG_DIR`
(default `/app/debug` in the container, mounted to `./debug` on the host by
`docker-compose.yml`) before raising the error, so you don't need to
reproduce the failure interactively:

1. Run once (`PVHUB_LOOP_INTERVAL=0`) and let it fail.
2. Open `./debug/<timestamp>_username_selector_failed.png` -- that's
   exactly what the browser saw. Open the matching `.html` file and search
   it for the actual login form's `id`/`name`/`type` attributes.
3. Set `PVHUB_USERNAME_SELECTOR` (and `PASSWORD`/`SUBMIT` as needed) in
   `.env` to match what you find, e.g. `input#email` or
   `input[name="username"]`.
4. If the screenshot shows a cookie/consent banner covering the form,
   find that button's selector too and set `PVHUB_DISMISS_SELECTOR`.
5. Re-run. If it still fails, the dumped HTML plus the screenshot are
   exactly what's needed to fix the selectors further -- share them
   (with your own account details/cookies redacted) if you want help
   narrowing it down.

For interactive debugging outside Docker, set `PVHUB_HEADLESS=0` (or
`--headless 0`) when running the bare-Python version on a desktop machine
-- this pops up a real, visible Chromium window so you can watch exactly
where it gets stuck. This only works when there's a display available, so
it won't help inside a headless server/container.

## Full network trace (every request/response header, including Set-Cookie)

Every run writes two kinds of files to the debug directory:

- `<timestamp>_cookies_NN_<checkpoint>.json` -- five snapshots of the
  browser's **complete cookie jar, full values included** (not just
  names), at five points through the flow: `01_on_login_page` (before any
  interaction), `02_after_submit` (right after clicking sign-in),
  `03_before_plant_nav` / `04_after_plant_nav` (either side of opening
  the plant page), and `05_final_capture` (when the Analysis request was
  matched). Comparing these across the run shows whether a cookie
  appears and later disappears, or never appears at all, rather than
  only seeing the end state.
- `<timestamp>_network_trace.json` -- every document/xhr/fetch request
  and response's full headers for the whole session, including all
  `Set-Cookie` lines (duplicates preserved).

Useful if you need to check for a specific cookie or header:

```bash
grep -il "some_cookie_name" ./debug/*.json
```

**These files contain your full session in plain text** -- complete
Cookie/Token/Signature values, exactly as sent/received. Treat them like
credentials: don't paste their raw contents somewhere public without
redacting those values first. Never written to the log output, only to
these files.

## Troubleshooting

**`ERROR: for pvhub-auth-helper 'ContainerConfig'` / `KeyError:
'ContainerConfig'`** -- this is a known incompatibility between the old,
deprecated `docker-compose` v1 (the Python-based tool, command has a
hyphen) and image metadata produced by newer Docker builds. It's not
specific to this project's Dockerfile. Fix by either:

1. Using Compose v2 instead: `docker compose up -d --build` (no hyphen --
   it's a Docker CLI plugin, not a separate binary). Most current Docker
   Desktop/Engine installs already have it; check with `docker compose
   version`.
2. Or, if you must stay on v1: remove the stale container and image and
   rebuild clean --
   `docker-compose down; docker rm -f pvhub-auth-helper; docker rmi pvhub-auth-helper; docker-compose up --build`.

**Push rejected, HTTP 400/401/403, or a `type: "form"` result with
`errors`** -- the script dumps the full response body/headers to
`<timestamp>_ha_reconfigure_init_rejected.txt` or
`_submit_rejected.txt` in your debug directory. Also check:

1. **Home Assistant's own logs** (Settings -> System -> Logs) at the
   timestamp of the failed push -- a flow failure logs more detail there
   than what the REST API returns to the caller.
2. **`HTTP 401/403` on the init step** almost always means the token
   isn't an admin account's -- this endpoint requires
   `@require_admin`, unlike the old service-call API.
3. **A `type: "form"` result with an `errors` dict** (not an HTTP error
   at all -- the script raises a `RuntimeError` describing it) means the
   flow completed but pv-hub.com itself rejected the new headers during
   validation. This is the *good* kind of failure: it means the
   integration actually tried them against the real API before
   committing anything, exactly like a human using "Configure" in the
   UI would get the same rejection.
4. **Reproduce it directly** with `curl`, bypassing this script (two
   steps, matching how the script does it):
   ```bash
   # Step 1: start the reconfigure flow (get entry_id from Settings ->
   # Devices & Services -> PVHub -> the integration's URL, or from
   # GET /api/config/config_entries/entry?domain=pvhub)
   curl -i -X POST \
     -H "Authorization: Bearer YOUR_HA_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"handler":"pvhub","entry_id":"YOUR_ENTRY_ID"}' \
     http://homeassistant.local:8123/api/config/config_entries/flow
   # -> note the "flow_id" in the response

   # Step 2: submit the new values
   curl -i -X POST \
     -H "Authorization: Bearer YOUR_HA_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"cookie":"test","token":"test","signature":"test","timestamp":"test"}' \
     http://homeassistant.local:8123/api/config/config_entries/flow/YOUR_FLOW_ID
   ```
5. Or use **Settings -> Devices & Services -> PVHub -> Configure** in the
   HA UI directly -- it drives the exact same reconfigure step and shows
   validation errors inline.
6. If you set `plant_id`, confirm it exactly matches the Plant ID you
   entered when setting up the integration (the script matches it
   against each entry's title, `"PVHub Plant <plant_id>"`). If you only
   have one plant configured, omit `PVHUB_PLANT_ID`/`PVHUB_ENTRY_ID`
   entirely so it's auto-selected instead.

**Login form fails to fill in** -- see the selector overrides above; run
with `-v`/`PVHUB_VERBOSE=1` and inspect pv-hub.com's actual login page
HTML to correct them.
