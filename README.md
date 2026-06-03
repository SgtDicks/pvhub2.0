# PVHub 2.0 Home Assistant Integration

Small Python helper project for safely exploring and reading your own 1KOMMA5 / PVHub 2.0 solar data.

[![Open your Home Assistant instance and add this repository to HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=SgtDicks&repository=pvhub2.0&category=integration)

This project is intentionally monitoring-only. It does not include inverter control, battery control, export-limit changes, configuration updates, device management, or automation actions.

## Safety Rules

The code blocks:

- `PUT`
- `PATCH`
- `DELETE`
- any HTTP method other than approved read-only methods
- endpoints whose path appears to involve control, settings, configuration, writes, commands, charging, discharging, export limits, or remote actions

Allowed methods are:

- `GET`
- `POST`, only for query/report style reads such as historical meter data

The scripts print a dry-run style summary before each request, but never print bearer tokens, cookies, refresh tokens, passwords, session IDs, or other secrets.

## Files

```text
.
├── .env.example
├── README.md
├── requirements.txt
├── pvhub_readonly/
│   ├── __init__.py
│   ├── cli.py
│   ├── client.py
│   ├── endpoint_tester.py
│   └── homeassistant_sensor.py
├── custom_components/
│   └── pvhub/
│       ├── __init__.py
│       ├── api.py
│       ├── config_flow.py
│       ├── const.py
│       ├── coordinator.py
│       ├── manifest.json
│       ├── sensor.py
│       ├── strings.json
│       └── brand/
│           └── icon.txt
├── homeassistant/
│   ├── command_line.yaml
│   ├── power_flow_apexcharts.yaml
│   └── template_sensors.yaml
├── hacs.json
└── endpoints.example.txt
```

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

On Windows, if `python` is not on PATH, use the Python launcher instead:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
```

## Capture the PVHub Request from Chrome DevTools

1. Open your PVHub 2.0 portal:
   `https://www.pv-hub.com/v2/plants/analysis?...`
2. Open Chrome DevTools with `F12`.
3. Select the `Network` tab.
4. Refresh the page or change the date/graph so the portal loads meter data.
5. Filter for `Fetch/XHR`.
6. Click the request that contains the JSON payload. On the PVHub Analysis page it may contain:
   - `plantId`
   - `dimension`
   - `date`
   - `downloadFlag`

   Older meter/history requests may instead contain:
   - `railID`
   - `variables`
   - `date`
   - `exportFlag`
7. Copy the real API `Request URL`.
8. Paste that URL into `PVHUB_API_URL` in your `.env` file.

Do not paste secrets into source code, README files, screenshots, issues, or shared logs.

## Redact Sensitive Headers

When copying request details from DevTools, treat these as sensitive and do not share them:

- `Authorization`
- bearer tokens
- cookies
- refresh tokens
- passwords
- session IDs
- CSRF tokens
- account IDs you do not want public

This project needs the API URL, plant ID or rail ID, and whatever auth headers your own PVHub request uses. PVHub 2.0 often uses cookie-based auth plus custom `Token`, `Signature`, and `Timestamp` headers rather than `Authorization: Bearer`.

## Configure `.env`

Copy the example file:

```powershell
Copy-Item .env.example .env
```

Then edit `.env`:

```dotenv
PVHUB_API_URL=https://paste-the-real-request-url-from-chrome-devtools-here
PVHUB_COOKIE=paste-your-cookie-header-here
PVHUB_TOKEN=paste-your-token-header-here
PVHUB_SIGNATURE=paste-your-signature-header-here
PVHUB_TIMESTAMP=paste-your-timestamp-header-here
PVHUB_LANG=English
PVHUB_TIMEZONE=Australia/Brisbane
PVHUB_BEARER_TOKEN=
PVHUB_PLANT_ID=5343e453-a5dc-4bfc-ade7-5fc8b0638be2
PVHUB_RAIL_ID=619ee290-5d6d-41bf-8dde-d8fc3cd09685
```

Cookies and tokens expire. If you receive `401` or `403`, capture fresh auth headers from your own logged-in PVHub browser session.

For the PVHub Analysis page request, there may be no `railID`. That is normal. The request uses `plantId`, which is the `GROUPID` in the page URL.

## Import from DevTools cURL

Instead of manually copying values into `.env`, you can use Chrome DevTools:

1. In `Network`, right-click the PVHub API request.
2. Choose `Copy` -> `Copy as cURL`.
3. Save it locally in this project folder as `pvhub-request.curl.txt`.
4. Run:

```powershell
py -m pvhub_readonly.import_curl --curl-file pvhub-request.curl.txt
```

The helper writes `PVHUB_API_URL`, any detected `PVHUB_PLANT_ID` or `PVHUB_RAIL_ID`, and detected auth headers such as `PVHUB_COOKIE`, `PVHUB_TOKEN`, `PVHUB_SIGNATURE`, `PVHUB_TIMESTAMP`, or `PVHUB_BEARER_TOKEN` to `.env`. It does not print secrets. Delete `pvhub-request.curl.txt` after import because it contains secrets.

## Request Data

Run with a specific date:

```powershell
python -m pvhub_readonly.cli --date 2026-06-03
```

Or with the Windows launcher:

```powershell
py -m pvhub_readonly.cli --date 2026-06-03
```

To save a clean JSON file as well as printing the response:

```powershell
py -m pvhub_readonly.cli --date 2026-06-03 --output-json response.json
```

This defaults to the PVHub Analysis payload:

```json
{
  "plantId": "your-plant-id",
  "dimension": "DAY",
  "date": {
    "year": "2026",
    "month": "06",
    "day": "03"
  },
  "downloadFlag": false
}
```

To use the older `railID` meter payload shape, run:

```powershell
py -m pvhub_readonly.cli --date 2026-06-03 --payload meter
```

The optional meter mode sends a read-only `POST` body shaped like:

```json
{
  "railID": "your-rail-id",
  "variables": [
    "meterPower",
    "meterPowerR",
    "meterPowerS",
    "meterPowerT"
  ],
  "date": {
    "year": "2026",
    "month": "06",
    "day": "03"
  },
  "exportFlag": false
}
```

## Test Manually Provided Endpoints

The endpoint tester only tests URLs you manually provide in a text file. It still applies the same method and path safety guards.

Edit `endpoints.example.txt`, or create your own file:

```text
https://example.pv-hub-api.invalid/path/to/read-only-endpoint
https://example.pv-hub-api.invalid/path/to/another-report-endpoint
```

Run:

```powershell
python -m pvhub_readonly.endpoint_tester --endpoints-file endpoints.example.txt --date 2026-06-03
```

By default, it uses `POST` with the meter payload because the captured PVHub history request appears to use a query/report body. You can test `GET` endpoints too:

```powershell
python -m pvhub_readonly.endpoint_tester --endpoints-file endpoints.example.txt --method GET
```

## Important Limits

This project does not:

- bypass login, MFA, Cloudflare, CAPTCHA, rate limits, or authorization checks
- discover hidden endpoints automatically
- perform control or configuration requests
- write to the inverter, battery, meter, PVHub account, or any device

Use it only for your own PVHub account and your own solar data.

## Summarize a Saved Response

If you save the full JSON output to a file, you can summarize the returned time series locally:

```powershell
py -m pvhub_readonly.summarize_response response.json
```

The summarizer does not call PVHub. It reports variables, point counts, time ranges, and min/max/latest values.

## Home Assistant / Hass.io

This project can be polled by Home Assistant OS using the `command_line` integration. The script prints one compact JSON object, for example:

```json
{
  "status": "ok",
  "pv_power_kw": 1.23,
  "battery_charge_power_kw": 0.4,
  "battery_discharge_power_kw": 0,
  "grid_export_power_kw": 0,
  "grid_import_power_kw": 0.2,
  "load_power_kw": 1.1,
  "updated_at": "2026-06-03 20:56:42 AEST"
}
```

On your Home Assistant system:

1. Copy this project folder to `/config/pvhub_readonly`.
2. Copy your working `.env` file into `/config/pvhub_readonly/.env`.
3. Install the Python dependencies in the environment where Home Assistant can run the command, or use an add-on/container path that has Python and `requests`.
4. Add this to `/config/configuration.yaml`:

```yaml
command_line: !include command_line.yaml
template: !include template_sensors.yaml
```

5. Copy:
   - `homeassistant/command_line.yaml` to `/config/command_line.yaml`
   - `homeassistant/template_sensors.yaml` to `/config/template_sensors.yaml`

6. Check configuration and restart Home Assistant.

You can test the command from a Home Assistant terminal add-on:

```sh
cd /config/pvhub_readonly
python3 -m pvhub_readonly.homeassistant_sensor
```

The `command_line` sensor is intentionally one polling sensor with JSON attributes. The template sensors then expose solar, battery, grid, and load values as normal power sensors. This avoids calling PVHub repeatedly for each entity.

Important: if PVHub rejects stale `Signature` or `Timestamp` headers, the HA sensor will report `status: error`. In that case, a future step is adding automatic signature generation from PVHub's public `signature.js` and `signature.wasm`, but this project remains read-only either way.

## HACS Custom Integration

This repository also contains a proper Home Assistant custom integration:

```text
custom_components/pvhub
```

It creates these entities:

- Battery SoC
- Solar power
- Battery charge power
- Battery discharge power
- Grid export power
- Grid import power
- Load power

The entities are grouped into Home Assistant devices:

- `PVHub Battery`
- `PVHub Solar Inverter`
- `PVHub Grid Meter`
- `Site Power Usage`

The integration is still strictly read-only. It only calls the PVHub Analysis endpoint with a monitoring/report payload and keeps the same endpoint/method safety checks.

The integration ships a local brand icon hint using `mdi:solar-panel`, and the entities also use solar, battery, grid, and home power icons. Home Assistant local custom integration brand assets are supported through a `brand/` directory in newer Home Assistant versions; entity icons work independently of that.

### Manual Install

1. Copy `custom_components/pvhub` to:

```text
/config/custom_components/pvhub
```

2. Restart Home Assistant.
3. Go to `Settings` -> `Devices & services` -> `Add integration`.
4. Search for `PVHub 2.0`.
5. Home Assistant will open a setup form asking for:
   - `PVHUB_API_URL`
   - `PVHUB_PLANT_ID / GROUPID`
   - Authentication method
   - PVHub username/password, or copied request headers
   - `PVHUB_COOKIE`
   - `PVHUB_TOKEN`
   - `PVHUB_SIGNATURE`
   - `PVHUB_TIMESTAMP`
   - `PVHUB_LANG`
   - `PVHUB_TIMEZONE`

The config flow performs one read-only validation request before creating the entry.

### Authentication Modes

The integration supports two setup modes:

- Copied PVHub request headers: the most reliable current method. Copy `Cookie`, `Token`, `Signature`, and `Timestamp` from your own `/dew/w/plant/analysis/raw` request.
- PVHub username and password: experimental. The PVHub web app posts to `/basic/v0/user/login` with an MD5-hashed password. This integration follows that first-party flow only when PVHub accepts it. It does not bypass MFA, CAPTCHA, Cloudflare, region checks, or other security controls.

If PVHub rejects the stored auth details, Home Assistant will create a Repair issue titled `PVHub credentials expired` with instructions to update the integration.

### Devices

The integration creates logical Home Assistant devices from the data returned by the Analysis endpoint:

- `PVHub Battery`
- `PVHub Solar Inverter`
- `PVHub Grid Meter`
- `Site Power Usage`

If a future PVHub endpoint exposes physical device serial numbers and models, the integration can be extended to create exact inverter, battery, and meter devices.

### HACS Custom Repository

Once this folder is pushed to a GitHub repository:

Click the button below to open your Home Assistant instance and add this repository to HACS:

[![Open your Home Assistant instance and add this repository to HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=SgtDicks&repository=pvhub2.0&category=integration)

Or add it manually:

1. Open HACS.
2. Open `Integrations`.
3. Choose `Custom repositories`.
4. Add `https://github.com/SgtDicks/pvhub2.0`.
5. Select category `Integration`.
6. Install `PVHub 2.0`.
7. Restart Home Assistant.
8. Add it from `Settings` -> `Devices & services`.

HACS stores custom integrations under `custom_components/`; this project includes `hacs.json` and `custom_components/pvhub/manifest.json` for that layout.

## Releases

Current version: `v0.1.0`.

Use the GitHub release/tag `v0.1.0` for the first stable HACS install.

## Dashboard Card

For a graph like the PVHub portal's combined power/SOC chart, install `apexcharts-card` from HACS, then add a manual card with this YAML:

```yaml
type: custom:apexcharts-card
graph_span: 24h
header:
  show: true
  title: PVHub Power and Battery
  show_states: true
span:
  start: day
now:
  show: true
apex_config:
  chart:
    height: 360
  stroke:
    width: 2
  legend:
    show: true
    position: right
  grid:
    borderColor: "#d7dbe0"
yaxis:
  - id: power
    min: ~-6
    max: ~6
    decimals: 1
    apex_config:
      title:
        text: Power (kW)
  - id: soc
    opposite: true
    min: 0
    max: 100
    decimals: 0
    apex_config:
      title:
        text: SOC
series:
  - entity: sensor.pvhub_battery_soc
    name: SoC
    yaxis_id: soc
    color: "#38c978"
  - entity: sensor.pvhub_solar_power
    attribute: raw
    name: Solar
    yaxis_id: power
    color: "#0097a7"
  - entity: sensor.pvhub_battery_discharge_power
    attribute: raw
    name: Battery Discharge
    yaxis_id: power
    color: "#5aa2ff"
  - entity: sensor.pvhub_grid_import_power
    attribute: raw
    name: Grid Import
    yaxis_id: power
    color: "#b586f4"
  - entity: sensor.pvhub_grid_export_power
    attribute: raw
    name: Grid Export
    yaxis_id: power
    color: "#7d197b"
  - entity: sensor.pvhub_battery_charge_power
    attribute: raw
    name: Battery Charge
    yaxis_id: power
    color: "#ef2a8a"
  - entity: sensor.pvhub_load_power
    attribute: raw
    name: Total Load
    yaxis_id: power
    color: "#ff7c0a"
```

The same card is also saved in `homeassistant/power_flow_apexcharts.yaml`.

## Suggestions

- Keep the polling interval around 5 minutes unless you know PVHub tolerates faster refreshes.
- Add sensors to Home Assistant's Energy dashboard only after you add energy-in-kWh entities; the current entities are power-in-kW snapshots.
- Keep raw signed values as attributes for graphing, and friendly positive values as entity states for normal dashboard tiles.
- Automating PVHub signature generation would make the integration more reliable than copied `PVHUB_SIGNATURE` and `PVHUB_TIMESTAMP` values.
- Capturing a device inventory endpoint would let the integration create exact physical devices with serial numbers instead of logical devices.
