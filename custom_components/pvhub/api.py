"""Read-only PVHub 2.0 API helpers for Home Assistant."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
from typing import Any
from urllib.parse import urlparse

import requests

from .const import (
    CONF_API_URL,
    CONF_AUTH_MODE,
    CONF_COOKIE,
    CONF_LANG,
    CONF_PLANT_ID,
    CONF_SIGNATURE,
    CONF_TIMESTAMP,
    CONF_TIMEZONE,
    CONF_TOKEN,
    CONF_USERNAME,
    DEFAULT_LANG,
    DEFAULT_TIMEOUT,
    AUTH_MODE_HEADERS,
    AUTH_MODE_PASSWORD,
)

APPROVED_METHODS = {"GET", "POST"}
BLOCKED_PATH_WORDS = (
    "control",
    "setting",
    "settings",
    "config",
    "update",
    "delete",
    "write",
    "command",
    "dispatch",
    "charge",
    "discharge",
    "export-limit",
    "remote",
)

SERIES_MAP = {
    "SoC": "battery_soc_percent",
    "pvPower": "pv_power_kw",
    "batChargePower": "battery_charge_power_kw",
    "batDischargePower": "battery_discharge_power_kw",
    "feedinPower": "grid_export_power_kw",
    "gridConsumptionPower": "grid_import_power_kw",
    "loadsPower": "load_power_kw",
}


class PVHubError(RuntimeError):
    """Base PVHub API error."""


class PVHubAuthError(PVHubError):
    """PVHub rejected authentication."""


class PVHubSafetyError(PVHubError):
    """Request was blocked by read-only safety rules."""


@dataclass(frozen=True)
class PVHubAuth:
    """PVHub copied browser-auth headers."""

    cookie: str | None
    token: str | None
    signature: str | None
    timestamp: str | None
    lang: str
    timezone: str | None
    username: str | None = None
    password: str | None = None
    auth_mode: str = AUTH_MODE_HEADERS


class PVHubClient:
    """Minimal guarded PVHub Analysis client.

    Monitoring only. This client intentionally exposes no control/config/write
    methods and only uses POST for the Analysis report query body.
    """

    def __init__(
        self,
        api_url: str,
        plant_id: str,
        auth: PVHubAuth,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self.api_url = api_url
        self.plant_id = plant_id
        self.auth = auth
        self.timeout = timeout

    @classmethod
    def from_config(cls, data: dict[str, Any]) -> "PVHubClient":
        return cls(
            api_url=data[CONF_API_URL],
            plant_id=data[CONF_PLANT_ID],
            auth=PVHubAuth(
                cookie=clean_value(data.get(CONF_COOKIE)),
                token=clean_value(data.get(CONF_TOKEN)),
                signature=clean_value(data.get(CONF_SIGNATURE)),
                timestamp=clean_value(data.get(CONF_TIMESTAMP)),
                lang=clean_value(data.get(CONF_LANG)) or DEFAULT_LANG,
                timezone=clean_value(data.get(CONF_TIMEZONE)),
                username=clean_value(data.get(CONF_USERNAME)),
                password=clean_value(data.get(CONF_PASSWORD)),
                auth_mode=clean_value(data.get(CONF_AUTH_MODE)) or AUTH_MODE_HEADERS,
            ),
        )

    def get_analysis(self, requested_date: date | None = None) -> dict[str, Any]:
        """Fetch today's PVHub Analysis data."""

        if self.auth.auth_mode == AUTH_MODE_PASSWORD and not self.auth.token:
            self.login()
        payload = build_analysis_payload(self.plant_id, requested_date or date.today())
        return self._request_json("POST", self.api_url, payload)

    def login(self) -> None:
        """Log in using PVHub's first-party login endpoint when accepted.

        PVHub currently signs browser requests using signature.js/signature.wasm.
        This method intentionally does not bypass MFA, CAPTCHA, Cloudflare, or
        other security controls. If PVHub rejects unsigned login requests, users
        must continue using copied headers until automatic signing is supported.
        """

        if not self.auth.username or not self.auth.password:
            raise PVHubAuthError("PVHub username/password are required")
        parsed = urlparse(self.api_url)
        login_url = f"{parsed.scheme}://{parsed.netloc}/basic/v0/user/login"
        payload = {
            "user": self.auth.username,
            "password": hashlib.md5(self.auth.password.encode("utf-8")).hexdigest(),
            "type": 1,
            "verification": 1,
        }
        response = self._request_json("POST", login_url, payload)
        result = response.get("result")
        if not isinstance(result, dict) or not result.get("token"):
            raise PVHubAuthError("PVHub login response did not include a token")
        object.__setattr__(self.auth, "token", str(result["token"]))

    def _request_json(self, method: str, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        assert_read_only_request(method, url)
        headers = self._headers()
        try:
            response = requests.request(
                method,
                url,
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )
        except requests.Timeout as exc:
            raise PVHubError("Network timeout while reading PVHub data") from exc
        except requests.RequestException as exc:
            raise PVHubError(f"Network error while reading PVHub data: {exc}") from exc

        if response.status_code in {401, 403}:
            raise PVHubAuthError("PVHub rejected the copied cookie/token headers")
        if response.status_code == 404:
            raise PVHubError("PVHub endpoint was not found")

        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise PVHubError(f"PVHub returned HTTP {response.status_code}") from exc

        try:
            parsed = response.json()
        except ValueError as exc:
            raise PVHubError("PVHub response was not valid JSON") from exc

        if isinstance(parsed, dict) and parsed.get("errno") not in (None, 0):
            msg = parsed.get("msg") or "PVHub returned an application error"
            raise PVHubError(str(msg))
        if not isinstance(parsed, dict):
            raise PVHubError("PVHub response was not a JSON object")
        return parsed

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "category": "2",
            "contentType": "application/json",
            "lang": self.auth.lang,
            "platform": "web",
        }
        if self.auth.cookie:
            headers["Cookie"] = self.auth.cookie
        if self.auth.token:
            headers["token"] = self.auth.token
        if self.auth.signature:
            headers["signature"] = self.auth.signature
        if self.auth.timestamp:
            headers["timestamp"] = self.auth.timestamp
        if self.auth.timezone:
            headers["timezone"] = self.auth.timezone
        return headers


def build_analysis_payload(plant_id: str, requested_date: date) -> dict[str, Any]:
    """Build the PVHub Analysis page read-only query payload."""

    return {
        "plantId": plant_id,
        "dimension": "DAY",
        "date": {
            "year": f"{requested_date.year:04d}",
            "month": f"{requested_date.month:02d}",
            "day": f"{requested_date.day:02d}",
        },
        "downloadFlag": False,
    }


def assert_read_only_request(method: str, url: str) -> None:
    """Block unsafe methods and endpoint paths."""

    normalized_method = method.upper()
    if normalized_method not in APPROVED_METHODS:
        raise PVHubSafetyError("Only GET and read-only POST are allowed")

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise PVHubSafetyError("PVHub URL must be HTTP(S)")

    path = parsed.path.lower()
    blocked_words = [word for word in BLOCKED_PATH_WORDS if word in path]
    if blocked_words:
        raise PVHubSafetyError(
            f"Endpoint path looks unsafe for monitoring only: {', '.join(blocked_words)}"
        )


def extract_sensor_data(data: dict[str, Any]) -> dict[str, Any]:
    """Extract latest HA sensor values from PVHub's time-series response."""

    output: dict[str, Any] = {}
    latest_timestamp = None
    for item in find_series(data):
        variable = item.get("variable")
        key = SERIES_MAP.get(variable)
        if not key:
            continue
        latest = latest_point(item.get("points") or item.get("data") or [])
        if not latest:
            continue
        output[key] = to_float(latest.get("valueShow"))
        output[f"{key}_raw"] = to_float(latest.get("value"))
        output[f"{key}_time"] = latest.get("index")
        output[f"{key}_display"] = latest.get("valueShow")
        latest_timestamp = latest.get("index") or latest_timestamp

    if latest_timestamp:
        output["updated_at"] = latest_timestamp
    return output


def extract_device_inventory(data: dict[str, Any], plant_id: str) -> list[dict[str, str]]:
    """Return logical PVHub devices exposed by the Analysis response."""

    seen_variables = {item.get("variable") for item in find_series(data)}
    devices: list[dict[str, str]] = []
    if {"SoC", "batChargePower", "batDischargePower"} & seen_variables:
        devices.append({"id": f"{plant_id}_battery", "name": "PVHub Battery", "model": "PVHub Battery"})
    if "pvPower" in seen_variables:
        devices.append({"id": f"{plant_id}_solar", "name": "PVHub Solar Inverter", "model": "PVHub Solar / Inverter"})
    if {"feedinPower", "gridConsumptionPower"} & seen_variables:
        devices.append({"id": f"{plant_id}_grid", "name": "PVHub Grid Meter", "model": "PVHub Meter"})
    if "loadsPower" in seen_variables:
        devices.append({"id": f"{plant_id}_load", "name": "Site Power Usage", "model": "PVHub Site Power Usage"})
    return devices


def find_series(data: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            if isinstance(value.get("variable"), str) and (
                isinstance(value.get("points"), list) or isinstance(value.get("data"), list)
            ):
                found.append(value)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(data)
    return found


def latest_point(points: Any) -> dict[str, Any] | None:
    if not isinstance(points, list):
        return None
    for point in reversed(points):
        if isinstance(point, dict) and point.get("value") is not None:
            return point
    return None


def to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def clean_value(value: Any) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    if not stripped:
        return None
    return stripped
    CONF_PASSWORD,
