#!/usr/bin/env python3
"""Headless-browser helper that logs into pv-hub.com and captures fresh
auth headers (Cookie / Token / Signature / Timestamp) for the PVHub Home
Assistant integration.

This is intentionally a SEPARATE, standalone script -- not something the
Home Assistant custom_component imports or bundles -- because Playwright
needs a real Chromium binary + OS-level dependencies that most Home
Assistant installs (HAOS, Supervised) cannot provide. Run this next to
Home Assistant (a small sidecar container, a cron job on the same host or
another machine on your network, etc.).

Two ways to get the captured headers into Home Assistant -- pick whichever
fits your setup, or use both:

  - PUSH (--ha-url + --ha-token): after each capture, drive Home
    Assistant's own built-in config-entries **reconfigure flow** over its
    HTTP API (`POST /api/config/config_entries/flow`, then
    `POST /api/config/config_entries/flow/{flow_id}`) -- the same
    mechanism the "Configure" button in the UI uses, requiring an admin
    long-lived access token. The PVHub integration validates the new
    headers against pv-hub.com before committing them, then reloads
    itself. No shared filesystem needed -- works even if this script runs
    on a different machine. Tradeoff: an HA long-lived access token is
    account-wide, so it's a more sensitive secret to have sitting in this
    script's environment.
  - FILE (--output): write the headers to a local JSON file that the
    PVHub integration re-reads on every poll (auth_mode: file). Requires
    the file to be on a path both this script and Home Assistant can
    read (e.g. a mounted volume), which is more setup if they're on
    different machines. Tradeoff: no HA credential needed at all here --
    only filesystem access, which is easy to scope tightly (e.g. a
    read-only bind mount) if that matters more to you than convenience.

What it does, every cycle:
  1. Launches headless Chromium via Playwright.
  2. Logs in to pv-hub.com with your username/password.
  3. Opens your plant's Analysis page so the portal's own JS fires the
     Analysis API request (the same one the integration replays).
  4. Captures that request's Cookie / Token / Signature / Timestamp
     headers.
  5. Writes them to --output (if given) and/or pushes them to Home
     Assistant (if --ha-url/--ha-token given).
  6. If --loop-interval is set, sleeps and repeats (fresh login each time,
     since cookies/signed headers expire).

What it deliberately does NOT do:
  - It never clicks, submits, or calls anything related to control,
    settings, charge/discharge, export-limit, or configuration -- only
    login + navigating to the read-only Analysis page.
  - It never logs your password, cookie, token, signature, or HA access
    token to stdout/stderr -- only redacted previews.

Install (run this on the sidecar machine/container, NOT inside HA):
    pip install -r requirements.txt
    playwright install --with-deps chromium

Create a Home Assistant long-lived access token: your HA profile page
(bottom-left avatar) -> Security tab -> Long-Lived Access Tokens -> Create
Token.

Usage (push mode -- see --output above for the file-mode equivalent):
    python capture_headers.py \\
        --login-url "https://www.pv-hub.com/login" \\
        --plant-url "https://www.pv-hub.com/v2/plants/analysis?GROUPID=YOUR_PLANT_ID" \\
        --username "you@example.com" \\
        --password "..." \\
        --ha-url "http://homeassistant.local:8123" \\
        --ha-token "$HA_TOKEN" \\
        --plant-id "YOUR_PLANT_ID" \\
        --loop-interval 1500

Username/password/HA token can also be supplied via the PVHUB_USERNAME /
PVHUB_PASSWORD / HA_TOKEN environment variables instead of flags, so they
don't end up in shell history or process listings.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger("pvhub_auth_helper")

REQUIRED_HEADERS = ("cookie", "token", "signature", "timestamp")


def _env_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in ("0", "false", "no", "")


def _redact(value: str, keep: int = 4) -> str:
    if not value:
        return "<empty>"
    if len(value) <= keep * 2:
        return "*" * len(value)
    return f"{value[:keep]}...{value[-keep:]} ({len(value)} chars)"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--login-url", default=os.environ.get("PVHUB_LOGIN_URL"), help="pv-hub.com login page URL (env: PVHUB_LOGIN_URL)")
    parser.add_argument("--plant-url", default=os.environ.get("PVHUB_PLANT_URL"), help="Your plant's Analysis page URL, contains GROUPID (env: PVHUB_PLANT_URL)")
    parser.add_argument("--api-url-match", default=os.environ.get("PVHUB_API_URL_MATCH", "analysis"), help="Substring to match the Analysis API request URL (env: PVHUB_API_URL_MATCH, default: 'analysis')")
    parser.add_argument("--username", default=os.environ.get("PVHUB_USERNAME"))
    parser.add_argument("--password", default=os.environ.get("PVHUB_PASSWORD"))
    parser.add_argument("--username-selector", default=os.environ.get("PVHUB_USERNAME_SELECTOR", "input[type=email], input[name*=user i], input[name*=email i]"))
    parser.add_argument("--password-selector", default=os.environ.get("PVHUB_PASSWORD_SELECTOR", "input[type=password]"))
    parser.add_argument("--submit-selector", default=os.environ.get("PVHUB_SUBMIT_SELECTOR", "button[type=submit], button:has-text('Log'), button:has-text('Sign')"))
    parser.add_argument("--dismiss-selector", default=os.environ.get("PVHUB_DISMISS_SELECTOR"), help="Optional selector for a cookie/consent overlay button to click before logging in (env: PVHUB_DISMISS_SELECTOR)")
    parser.add_argument("--headless", type=_env_bool, default=_env_bool(os.environ.get("PVHUB_HEADLESS", "1")), help="Set to 0/false to launch a visible browser window for debugging (env: PVHUB_HEADLESS). Only useful when not running inside Docker.")
    parser.add_argument("--debug-dir", default=os.environ.get("PVHUB_DEBUG_DIR", "/app/debug" if os.path.isdir("/app") else "./debug"), help="Where to save screenshots/HTML on failure (env: PVHUB_DEBUG_DIR)")
    parser.add_argument("--output", default=os.environ.get("PVHUB_OUTPUT"), help="Path to write the captured headers JSON, file mode (env: PVHUB_OUTPUT)")
    parser.add_argument("--ha-url", default=os.environ.get("PVHUB_HA_URL"), help="Base URL of your Home Assistant instance, e.g. http://homeassistant.local:8123, push mode (env: PVHUB_HA_URL)")
    parser.add_argument("--ha-token", default=os.environ.get("HA_TOKEN") or os.environ.get("PVHUB_HA_TOKEN"), help="Home Assistant long-lived access token, push mode (env: HA_TOKEN)")
    parser.add_argument("--plant-id", default=os.environ.get("PVHUB_PLANT_ID"), help="Plant ID to target when pushing, if you have more than one PVHub config entry (env: PVHUB_PLANT_ID)")
    parser.add_argument("--entry-id", default=os.environ.get("PVHUB_ENTRY_ID"), help="PVHub config entry_id to target when pushing, alternative to --plant-id (env: PVHUB_ENTRY_ID)")
    parser.add_argument("--loop-interval", type=int, default=int(os.environ.get("PVHUB_LOOP_INTERVAL", "0")), help="Seconds between capture cycles. 0 = run once and exit (env: PVHUB_LOOP_INTERVAL)")
    parser.add_argument("--nav-timeout", type=int, default=int(os.environ.get("PVHUB_NAV_TIMEOUT", "30000")), help="Navigation timeout in ms (env: PVHUB_NAV_TIMEOUT)")
    parser.add_argument("--capture-timeout", type=int, default=int(os.environ.get("PVHUB_CAPTURE_TIMEOUT", "25000")), help="How long to wait for the Analysis request in ms (env: PVHUB_CAPTURE_TIMEOUT)")
    parser.add_argument("-v", "--verbose", action="store_true", default=bool(os.environ.get("PVHUB_VERBOSE")))
    args = parser.parse_args()

    if not args.login_url or not args.plant_url:
        parser.error(
            "--login-url/PVHUB_LOGIN_URL and --plant-url/PVHUB_PLANT_URL are "
            "both required."
        )


    if not args.output and not (args.ha_url and args.ha_token):
        parser.error(
            "Specify --output (file mode) and/or --ha-url together with "
            "--ha-token / HA_TOKEN env var (push mode) -- at least one "
            "destination is required."
        )
    return args


async def _dump_debug(page, debug_dir: Path, label: str) -> tuple[str, str]:
    """Best-effort save of a screenshot + full HTML so the failure can be
    inspected without needing to reproduce it interactively. Never raises --
    a dump failure shouldn't mask the real error."""
    debug_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    png_path = debug_dir / f"{stamp}_{label}.png"
    html_path = debug_dir / f"{stamp}_{label}.html"
    try:
        await page.screenshot(path=str(png_path), full_page=True)
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Could not save debug screenshot: %s", err)
        png_path = None
    try:
        html = await page.content()
        html_path.write_text(html, encoding="utf-8")
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Could not save debug HTML: %s", err)
        html_path = None
    return (str(png_path) if png_path else "", str(html_path) if html_path else "")


async def _dump_cookie_snapshot(context, debug_dir: Path, checkpoint: str) -> str:
    """Write every cookie's FULL value (not just name/domain/path) at this
    point in the flow, so a cookie that appears then gets cleared -- or
    never appears at all -- is visible across the whole session, not just
    at the final capture moment.

    Contains full cookie values in plain text -- never logged to stdout,
    only written to a local file. Treat it like a credential.
    """
    debug_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = debug_dir / f"{stamp}_cookies_{checkpoint}.json"
    try:
        cookies = await context.cookies()
        path.write_text(json.dumps(cookies, indent=2), encoding="utf-8")
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Could not save cookie snapshot at %s: %s", checkpoint, err)
        return ""
    _LOGGER.info(
        "Cookie snapshot at '%s': %d cookie(s) -- full values saved to %s",
        checkpoint, len(cookies) if isinstance(cookies, list) else 0, path,
    )
    return str(path)


def _dump_network_trace(trace: list[dict], debug_dir: Path, label: str) -> str:
    """Write the full request/response header trace to a JSON file.

    Contains complete Cookie/Token/Signature/Timestamp values in plain
    text -- this is deliberately NEVER logged to stdout/stderr, only
    written to a local file, since it's meant for your own inspection.
    Treat this file like a credential: don't paste its raw contents
    somewhere public without redacting the Cookie/Token/Signature values
    first.
    """
    debug_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = debug_dir / f"{stamp}_{label}.json"
    try:
        path.write_text(json.dumps(trace, indent=2), encoding="utf-8")
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Could not save network trace: %s", err)
        return ""
    return str(path)


async def _capture_once(args: argparse.Namespace) -> dict[str, Any]:
    # Imported lazily so `--help` works even if playwright isn't installed yet.
    from playwright.async_api import async_playwright

    captured: dict[str, str] = {}
    capture_event = asyncio.Event()
    debug_dir = Path(args.debug_dir)
    # Full request/response headers for every document/xhr/fetch exchange
    # during the session -- written to disk regardless of outcome so a
    # missing cookie or unexpected auth flow can be inspected directly
    # instead of guessed at again.
    network_trace: list[dict] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=args.headless)
        context = await browser.new_context()
        page = await context.new_page()
        page.set_default_navigation_timeout(args.nav_timeout)

        def on_request_trace(request):
            if request.resource_type not in ("document", "xhr", "fetch"):
                return
            network_trace.append(
                {
                    "type": "request",
                    "resource_type": request.resource_type,
                    "method": request.method,
                    "url": request.url,
                    "headers": dict(request.headers),
                }
            )

        async def _record_response_trace(response) -> None:
            try:
                if response.request.resource_type not in ("document", "xhr", "fetch"):
                    return
                # headers_array preserves duplicate header names (multiple
                # Set-Cookie lines collapse into one string with .headers).
                headers_array = await response.headers_array()
                network_trace.append(
                    {
                        "type": "response",
                        "url": response.url,
                        "status": response.status,
                        "headers": headers_array,
                    }
                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Could not record a response in the trace: %s", err)

        page.on("request", on_request_trace)
        page.on("response", lambda r: asyncio.create_task(_record_response_trace(r)))

        def on_request(request):
            if capture_event.is_set():
                return
            if args.api_url_match.lower() in request.url.lower():
                headers = request.headers
                found = {h: headers.get(h) for h in REQUIRED_HEADERS if headers.get(h)}
                if found:
                    captured.update(found)
                    _LOGGER.debug("Matched analysis request: %s", request.url)
                    capture_event.set()

        page.on("request", on_request)

        login_api_responses: list[str] = []

        async def _record_login_response(response) -> None:
            try:
                url_lower = response.url.lower()
                if not any(kw in url_lower for kw in ("login", "signin", "sign-in", "auth")):
                    return
                status = response.status
                body_preview = ""
                try:
                    body = await response.json()
                    for key in ("message", "msg", "errMsg", "error", "detail"):
                        if isinstance(body, dict) and body.get(key):
                            body_preview = str(body[key])
                            break
                    if not body_preview:
                        body_preview = str(body)[:200]
                except Exception:  # noqa: BLE001 - not JSON, fall back to text
                    try:
                        body_preview = (await response.text())[:200]
                    except Exception:  # noqa: BLE001
                        body_preview = "<could not read body>"
                login_api_responses.append(f"HTTP {status} from {response.url}: {body_preview}")
            except Exception as err:  # noqa: BLE001 - never let logging break the run
                _LOGGER.debug("Could not inspect a response: %s", err)

        def on_response(response):
            asyncio.create_task(_record_login_response(response))

        page.on("response", on_response)

        try:
            _LOGGER.info("Navigating to login page...")
            await page.goto(args.login_url)
            await page.wait_for_load_state("networkidle", timeout=args.nav_timeout)
            await _dump_cookie_snapshot(context, debug_dir, "01_on_login_page")

            if args.dismiss_selector:
                try:
                    await page.click(args.dismiss_selector, timeout=5000)
                    _LOGGER.info("Dismissed a cookie/consent overlay via --dismiss-selector.")
                except Exception:  # noqa: BLE001
                    _LOGGER.debug("--dismiss-selector did not match anything (may not be needed).")

            if args.username and args.password:
                _LOGGER.info("Filling login form...")
                try:
                    await page.fill(args.username_selector, args.username)
                except Exception as err:
                    png, html = await _dump_debug(page, debug_dir, "username_selector_failed")
                    raise RuntimeError(
                        f"Could not find the username field with selector "
                        f"'{args.username_selector}'. Saved a screenshot/HTML "
                        f"of the actual login page to {png} / {html} -- "
                        f"inspect those (or set PVHUB_HEADLESS=0 to watch it "
                        f"live) and correct --username-selector / "
                        f"PVHUB_USERNAME_SELECTOR. Common culprits: a cookie-"
                        f"consent overlay blocking the form (try "
                        f"--dismiss-selector), or a login page that renders "
                        f"the form after a longer delay than --nav-timeout."
                    ) from err

                try:
                    await page.fill(args.password_selector, args.password)
                except Exception as err:
                    png, html = await _dump_debug(page, debug_dir, "password_selector_failed")
                    raise RuntimeError(
                        f"Could not find the password field with selector "
                        f"'{args.password_selector}'. Saved a screenshot/HTML "
                        f"to {png} / {html} -- correct --password-selector / "
                        f"PVHUB_PASSWORD_SELECTOR."
                    ) from err

                try:
                    await page.click(args.submit_selector)
                except Exception as err:
                    png, html = await _dump_debug(page, debug_dir, "submit_selector_failed")
                    raise RuntimeError(
                        f"Could not find the submit button with selector "
                        f"'{args.submit_selector}'. Saved a screenshot/HTML "
                        f"to {png} / {html} -- correct --submit-selector / "
                        f"PVHUB_SUBMIT_SELECTOR."
                    ) from err

                await page.wait_for_load_state("networkidle", timeout=args.nav_timeout)
                await _dump_cookie_snapshot(context, debug_dir, "02_after_submit")
                # Give any toast/error notification (often transient in
                # Element-UI apps) a moment to appear before we check.
                await asyncio.sleep(1.5)

                # A login failure often leaves you back on the login page or
                # shows an error banner rather than throwing an exception --
                # dump proactively so a bad password/selector mismatch is
                # visible even when nothing "errored".
                if args.username_selector and await page.locator(args.username_selector).count() > 0:
                    toast_texts: list[str] = []
                    for toast_selector in (".el-message__content", "[role=alert]", ".el-notification__content"):
                        try:
                            toast_texts.extend(await page.locator(toast_selector).all_text_contents())
                        except Exception:  # noqa: BLE001
                            pass
                    toast_texts = [t.strip() for t in toast_texts if t and t.strip()]

                    png, html = await _dump_debug(page, debug_dir, "still_on_login_after_submit")
                    diagnosis_parts = []
                    if toast_texts:
                        diagnosis_parts.append(f"On-page message(s): {toast_texts}")
                    if login_api_responses:
                        diagnosis_parts.append(f"Login API response(s): {login_api_responses}")
                    if not diagnosis_parts:
                        diagnosis_parts.append(
                            "No error toast or login-API response was captured "
                            "-- if login worked before, double-check for typos/"
                            "stray quotes in PVHUB_USERNAME/PVHUB_PASSWORD in "
                            ".env (docker-compose env_file does NOT strip "
                            "quote characters the way a shell would), or set "
                            "PVHUB_HEADLESS=0 to watch it happen live."
                        )
                    diagnosis = " ".join(diagnosis_parts)
                    _LOGGER.warning(
                        "Still on the login page after submitting -- login "
                        "likely failed. %s Saved %s / %s for inspection.",
                        diagnosis, png, html,
                    )
            else:
                _LOGGER.warning(
                    "No username/password provided -- assuming this browser "
                    "context already has a valid session (not typical for a "
                    "fresh headless run). Set --username/--password or "
                    "PVHUB_USERNAME/PVHUB_PASSWORD."
                )

            await _dump_cookie_snapshot(context, debug_dir, "03_before_plant_nav")
            _LOGGER.info("Opening plant Analysis page to trigger the API request...")
            await page.goto(args.plant_url)
            await _dump_cookie_snapshot(context, debug_dir, "04_after_plant_nav")

            try:
                await asyncio.wait_for(capture_event.wait(), timeout=args.capture_timeout / 1000)
            except asyncio.TimeoutError as err:
                png, html = await _dump_debug(page, debug_dir, "analysis_request_not_seen")
                raise RuntimeError(
                    f"Timed out waiting for the Analysis API request. Saved "
                    f"{png} / {html} -- check whether you actually landed on "
                    f"the plant page (login may have silently failed) and "
                    f"that --api-url-match / PVHUB_API_URL_MATCH matches the "
                    f"real request URL."
                ) from err

            # capture_event fires when the request is SENT, not when its
            # response arrives -- if the server issues a fresh session
            # cookie via Set-Cookie on that response, reading the cookie
            # jar immediately can race ahead of it. Give it a moment.
            await asyncio.sleep(1.0)

            # The Cookie header on the intercepted request is exactly what
            # the browser chose to attach to THAT request, which is
            # filtered by each cookie's Path (and possibly a different
            # subdomain for API calls) -- always rebuild it from the full
            # jar instead of trusting the single request. Sending a few
            # extra harmless cookies to pv-hub.com costs nothing.
            all_cookies = await context.cookies()
            await _dump_cookie_snapshot(context, debug_dir, "05_final_capture")
            _LOGGER.info(
                "Cookie jar contains: %s",
                [(c.get("name"), c.get("domain"), c.get("path")) for c in all_cookies],
            )
            if all_cookies:
                captured["cookie"] = "; ".join(f"{c['name']}={c['value']}" for c in all_cookies)
        finally:
            trace_path = _dump_network_trace(network_trace, debug_dir, "network_trace")
            if trace_path:
                _LOGGER.info(
                    "Full request/response header trace (%d entries) saved "
                    "to %s -- contains complete Cookie/Token/Signature "
                    "values in plain text, treat it like a credential.",
                    len(network_trace), trace_path,
                )
            await browser.close()

    missing = [h for h in REQUIRED_HEADERS if not captured.get(h)]
    if missing:
        raise RuntimeError(f"Captured request was missing headers: {missing}. Got: {list(captured.keys())}")

    return captured


async def _resolve_entry_id(
    session, ha_url: str, request_headers: dict[str, str], args: argparse.Namespace
) -> str:
    """Work out which PVHub config entry to reconfigure.

    Home Assistant's config-entries listing endpoint
    (GET /api/config/config_entries/entry) doesn't expose each entry's
    `data` for security reasons, so plant_id (which lives inside `data`)
    can't be matched directly -- but the title this integration sets at
    setup time is `f"PVHub Plant {plant_id}"`, so plant_id can still be
    resolved via the title instead.
    """
    import aiohttp

    if args.entry_id:
        return args.entry_id

    list_url = ha_url.rstrip("/") + "/api/config/config_entries/entry"
    async with session.get(
        list_url,
        params={"domain": "pvhub"},
        headers=request_headers,
        timeout=aiohttp.ClientTimeout(total=20),
    ) as resp:
        if resp.status >= 400:
            text = await resp.text()
            raise RuntimeError(
                f"Could not list PVHub config entries (HTTP {resp.status}): "
                f"{text[:300]}"
            )
        entries = await resp.json()

    if not entries:
        raise RuntimeError(
            "No PVHub config entries found in Home Assistant -- set up the "
            "integration first."
        )

    if args.plant_id:
        expected_title = f"PVHub Plant {args.plant_id}"
        match = next((e for e in entries if e.get("title") == expected_title), None)
        if match is None:
            titles = [e.get("title") for e in entries]
            raise RuntimeError(
                f"No PVHub config entry titled {expected_title!r} (from "
                f"plant_id={args.plant_id!r}). Configured entries: {titles}. "
                f"Double-check plant_id matches what you entered when "
                f"setting up the integration, or use --entry-id instead."
            )
        return match["entry_id"]

    if len(entries) == 1:
        return entries[0]["entry_id"]

    titles = [(e.get("title"), e.get("entry_id")) for e in entries]
    raise RuntimeError(
        f"Multiple PVHub plants are configured -- set --entry-id or "
        f"--plant-id (PVHUB_ENTRY_ID / PVHUB_PLANT_ID) to pick one. "
        f"Configured (title, entry_id) pairs: {titles}"
    )


async def _push_to_home_assistant(args: argparse.Namespace, headers: dict[str, str]) -> None:
    """Push captured headers into Home Assistant by driving its own
    built-in config-entries reconfigure flow over HTTP -- the same
    mechanism the "Configure" button in the UI uses -- rather than a
    custom service. This means the push gets the exact same validation
    (a real request to pv-hub.com) as any other config change before
    Home Assistant commits it.
    """
    import aiohttp

    request_headers = {
        "Authorization": f"Bearer {args.ha_token}",
        "Content-Type": "application/json",
    }
    debug_dir = Path(args.debug_dir)

    def _dump_rejection(stage: str, url: str, status: int, content_type: str, text: str, extra: str = "") -> str:
        debug_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        body_path = debug_dir / f"{stamp}_ha_reconfigure_{stage}_rejected.txt"
        try:
            body_path.write_text(
                f"Stage: {stage}\nURL: {url}\nStatus: {status}\n"
                f"Content-Type: {content_type}\n{extra}\n\n"
                f"--- Response body ---\n{text}",
                encoding="utf-8",
            )
            return str(body_path)
        except Exception:  # noqa: BLE001
            return ""

    async with aiohttp.ClientSession() as session:
        entry_id = await _resolve_entry_id(session, args.ha_url, request_headers, args)

        # Step 1: start a reconfigure flow for this entry. Home Assistant's
        # own config-entries flow view sets context.source=SOURCE_RECONFIGURE
        # automatically whenever `entry_id` is present in the POST body.
        flow_init_url = args.ha_url.rstrip("/") + "/api/config/config_entries/flow"
        async with session.post(
            flow_init_url,
            json={"handler": "pvhub", "entry_id": entry_id},
            headers=request_headers,
            timeout=aiohttp.ClientTimeout(total=20),
        ) as resp:
            content_type = resp.headers.get("Content-Type", "<none>")
            text = await resp.text()
            if resp.status >= 400:
                dump = _dump_rejection("init", flow_init_url, resp.status, content_type, text)
                hint = (
                    " This endpoint requires an ADMIN user's long-lived "
                    "access token -- double-check HA_TOKEN belongs to an "
                    "admin account." if resp.status in (401, 403) else ""
                )
                raise RuntimeError(
                    f"Home Assistant rejected starting the reconfigure flow "
                    f"(HTTP {resp.status}): {text[:300]}"
                    f"{' Full body saved to ' + dump if dump else ''}.{hint}"
                )
            try:
                flow_result = json.loads(text)
            except ValueError as err:
                raise RuntimeError(
                    f"Home Assistant's reconfigure-flow-init response wasn't "
                    f"JSON (Content-Type: {content_type}): {text[:300]}"
                ) from err

        if flow_result.get("type") == "abort":
            raise RuntimeError(
                f"Home Assistant aborted the reconfigure flow immediately: "
                f"reason={flow_result.get('reason')!r}. Full response: {flow_result}"
            )
        flow_id = flow_result.get("flow_id")
        if not flow_id:
            raise RuntimeError(
                f"No flow_id in Home Assistant's response to starting the "
                f"reconfigure flow: {flow_result}"
            )

        # Step 2: submit the new header values. Any field we don't send
        # (api_url, plant_id, auth_mode, ...) keeps its current value --
        # the integration's reconfigure step schema fills in defaults from
        # the entry's existing data for anything omitted here.
        payload: dict[str, str] = {
            "cookie": headers["cookie"],
            "token": headers["token"],
            "signature": headers["signature"],
            "timestamp": headers["timestamp"],
        }
        _LOGGER.debug(
            "Submitting reconfigure flow %s with payload keys=%s "
            "(cookie=%s, token=%s, signature=%s, timestamp=%s)",
            flow_id, sorted(payload.keys()),
            _redact(payload["cookie"]), _redact(payload["token"]),
            _redact(payload["signature"]), _redact(payload["timestamp"]),
        )

        flow_submit_url = args.ha_url.rstrip("/") + f"/api/config/config_entries/flow/{flow_id}"
        async with session.post(
            flow_submit_url,
            json=payload,
            headers=request_headers,
            timeout=aiohttp.ClientTimeout(total=20),
        ) as resp:
            content_type = resp.headers.get("Content-Type", "<none>")
            text = await resp.text()
            if resp.status >= 400:
                dump = _dump_rejection("submit", flow_submit_url, resp.status, content_type, text)
                raise RuntimeError(
                    f"Home Assistant rejected submitting the reconfigure "
                    f"flow (HTTP {resp.status}): {text[:300]}"
                    f"{' Full body saved to ' + dump if dump else ''}."
                )
            try:
                submit_result = json.loads(text)
            except ValueError as err:
                raise RuntimeError(
                    f"Home Assistant's reconfigure-flow-submit response "
                    f"wasn't JSON (Content-Type: {content_type}): {text[:300]}"
                ) from err

    result_type = submit_result.get("type")
    if result_type == "form":
        # Validation failed (e.g. invalid_auth) -- the flow re-shows the
        # form with an errors dict instead of completing.
        raise RuntimeError(
            f"Home Assistant rejected the new headers during validation: "
            f"errors={submit_result.get('errors')}. This means it actually "
            f"tried them against pv-hub.com and they didn't work -- not a "
            f"transport/API problem."
        )
    # Home Assistant's own async_update_reload_and_abort helper aborts
    # with reason "reconfigured" on success (observed directly from a
    # live instance) -- accept the older "reconfigure_successful" name
    # too in case that varies across HA versions.
    _SUCCESS_REASONS = {"reconfigured", "reconfigure_successful"}
    if result_type == "abort" and submit_result.get("reason") not in _SUCCESS_REASONS:
        raise RuntimeError(
            f"Reconfigure flow aborted for an unexpected reason: "
            f"{submit_result.get('reason')!r}. Full response: {submit_result}"
        )

    _LOGGER.info(
        "Reconfigured PVHub entry %s in Home Assistant via the built-in "
        "reconfigure flow.", entry_id,
    )


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=".pvhub_auth_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


async def _run(args: argparse.Namespace) -> None:
    output_path = Path(args.output) if args.output else None

    while True:
        try:
            headers = await _capture_once(args)

            if output_path:
                payload = {
                    "cookie": headers["cookie"],
                    "token": headers["token"],
                    "signature": headers["signature"],
                    "timestamp": headers["timestamp"],
                    "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                }
                _atomic_write_json(output_path, payload)
                _LOGGER.info("Wrote fresh headers to %s", output_path)

            if args.ha_url and args.ha_token:
                await _push_to_home_assistant(args, headers)

            _LOGGER.info(
                "Cycle complete (token=%s, signature=%s)",
                _redact(headers["token"]),
                _redact(headers["signature"]),
            )
        except Exception as err:  # noqa: BLE001 - top-level cycle guard
            _LOGGER.error("Cycle failed: %s", err)
            if args.loop_interval <= 0:
                sys.exit(1)

        if args.loop_interval <= 0:
            return
        _LOGGER.info("Sleeping %ss until next capture...", args.loop_interval)
        await asyncio.sleep(args.loop_interval)


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
