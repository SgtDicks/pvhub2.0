"""Constants for the PVHub 2.0 Readonly integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "pvhub"
DEFAULT_API_URL = "https://www.pv-hub.com/dew/w/plant/analysis/raw"
DEFAULT_LANG = "en"
DEFAULT_SCAN_INTERVAL = timedelta(minutes=5)
DEFAULT_TIMEOUT = 20

CONF_API_URL = "api_url"
CONF_PLANT_ID = "plant_id"
CONF_COOKIE = "cookie"
CONF_TOKEN = "token"
CONF_SIGNATURE = "signature"
CONF_TIMESTAMP = "timestamp"
CONF_LANG = "lang"
CONF_TIMEZONE = "timezone"

READ_ONLY_WARNING = (
    "PVHub 2.0 Readonly only performs guarded GET/read-only POST monitoring "
    "requests. It must not be used for inverter, battery, export, or account control."
)
