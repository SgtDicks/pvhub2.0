"""Read-only PVHub 2.0 API client.

This module is intended for monitoring only. Do not use it for inverter
control, battery control, configuration changes, export-limit changes, or any
device/account write operation.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests
from dotenv import load_dotenv
from requests import Response


DEFAULT_METER_VARIABLES = (
    "meterPower",
    "meterPowerR",
    "meterPowerS",
    "meterPowerT",
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

SENSITIVE_QUERY_WORDS = (
    "access_token",
    "auth",
    "bearer",
    "cookie",
    "csrf",
    "jwt",
    "password",
    "refresh",
    "secret",
    "session",
    "sid",
    "token",
)


class PVHubReadOnlyError(RuntimeError):
    """Base error for PVHub read-only client failures."""


class SafetyError(PVHubReadOnlyError):
    """Raised when a request violates read-only safety rules."""


class MissingEnvironmentError(PVHubReadOnlyError):
    """Raised when a required environment variable is missing."""


class AuthenticationError(PVHubReadOnlyError):
    """Raised when PVHub rejects authentication or authorization."""


class EndpointNotFoundError(PVHubReadOnlyError):
    """Raised when the configured endpoint is not found."""


class InvalidJSONError(PVHubReadOnlyError):
    """Raised when the response is not valid JSON."""


class NetworkTimeoutError(PVHubReadOnlyError):
    """Raised when the network request times out."""


@dataclass(frozen=True)
class PVHubConfig:
    """Configuration loaded from environment variables."""

    api_url: str
    rail_id: str | None = None
    plant_id: str | None = None
    bearer_token: str | None = None
    cookie: str | None = None
    token: str | None = None
    signature: str | None = None
    timestamp: str | None = None
    lang: str = "English"
    timezone: str | None = None


def load_config() -> PVHubConfig:
    """Load required PVHub settings from .env/environment variables."""

    load_dotenv()
    missing = [name for name in ("PVHUB_API_URL",) if not os.getenv(name)]
    if missing:
        joined = ", ".join(missing)
        raise MissingEnvironmentError(f"Missing required environment variable(s): {joined}")

    rail_id = clean_env_value(os.getenv("PVHUB_RAIL_ID"))
    plant_id = clean_env_value(os.getenv("PVHUB_PLANT_ID"))
    if not any((rail_id, plant_id)):
        raise MissingEnvironmentError("Set PVHUB_PLANT_ID for Analysis requests or PVHUB_RAIL_ID for rail meter requests.")

    bearer_token = clean_env_value(os.getenv("PVHUB_BEARER_TOKEN"))
    cookie = clean_env_value(os.getenv("PVHUB_COOKIE"))
    token = clean_env_value(os.getenv("PVHUB_TOKEN"))
    if not any((bearer_token, cookie, token)):
        raise MissingEnvironmentError(
            "Missing authentication value. Set PVHUB_COOKIE for cookie-based auth, "
            "PVHUB_TOKEN for PVHub's custom token header, or PVHUB_BEARER_TOKEN if your "
            "request actually uses bearer auth."
        )

    return PVHubConfig(
        api_url=os.environ["PVHUB_API_URL"],
        rail_id=rail_id,
        plant_id=plant_id,
        bearer_token=bearer_token,
        cookie=cookie,
        token=token,
        signature=clean_env_value(os.getenv("PVHUB_SIGNATURE")),
        timestamp=clean_env_value(os.getenv("PVHUB_TIMESTAMP")),
        lang=clean_env_value(os.getenv("PVHUB_LANG")) or "English",
        timezone=clean_env_value(os.getenv("PVHUB_TIMEZONE")),
    )


def clean_env_value(value: str | None) -> str | None:
    """Treat blank/example placeholder values as unset."""

    if value is None:
        return None
    stripped = value.strip()
    if not stripped or stripped.startswith("paste-"):
        return None
    return stripped


def parse_yyyy_mm_dd(value: str) -> date:
    """Parse a command-line date in YYYY-MM-DD format."""

    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise PVHubReadOnlyError("Date must use YYYY-MM-DD format, for example 2026-06-03") from exc


def build_meter_payload(rail_id: str, requested_date: date) -> dict[str, Any]:
    """Build the captured PVHub meter-data query payload."""

    return {
        "railID": rail_id,
        "variables": list(DEFAULT_METER_VARIABLES),
        "date": {
            "year": f"{requested_date.year:04d}",
            "month": f"{requested_date.month:02d}",
            "day": f"{requested_date.day:02d}",
        },
        "exportFlag": False,
    }


def build_analysis_payload(plant_id: str, requested_date: date) -> dict[str, Any]:
    """Build the PVHub 2.0 Analysis page read-only query payload."""

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
    """Block unsafe methods and endpoint paths that look like writes/control."""

    normalized_method = method.upper()
    if normalized_method not in APPROVED_METHODS:
        raise SafetyError(
            f"Blocked HTTP method {normalized_method}. Only GET and read-only POST are allowed."
        )

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SafetyError("Blocked request because the URL is not a valid HTTP(S) URL.")

    path = parsed.path.lower()
    blocked_words = [word for word in BLOCKED_PATH_WORDS if word in path]
    if blocked_words:
        joined = ", ".join(blocked_words)
        raise SafetyError(
            "Blocked endpoint because its path looks unsafe for monitoring only "
            f"(matched: {joined})."
        )


class PVHubReadOnlyClient:
    """Minimal guarded client for PVHub monitoring reads."""

    def __init__(
        self,
        config: PVHubConfig,
        timeout_seconds: float = 20.0,
        preview_requests: bool = True,
    ) -> None:
        self.config = config
        self.timeout_seconds = timeout_seconds
        self.preview_requests = preview_requests

    @classmethod
    def from_env(
        cls,
        timeout_seconds: float = 20.0,
        preview_requests: bool = True,
    ) -> "PVHubReadOnlyClient":
        return cls(
            load_config(),
            timeout_seconds=timeout_seconds,
            preview_requests=preview_requests,
        )

    def request_meter_data(self, requested_date: date) -> Any:
        """Request meter data for a date using the captured read-only POST payload."""

        if not self.config.rail_id:
            raise MissingEnvironmentError("PVHUB_RAIL_ID is required for rail meter payloads.")
        payload = build_meter_payload(self.config.rail_id, requested_date)
        return self.safe_request_json("POST", self.config.api_url, json_body=payload)

    def request_analysis_data(self, requested_date: date) -> Any:
        """Request PVHub Analysis page data for a date using plantId."""

        if not self.config.plant_id:
            raise MissingEnvironmentError("PVHUB_PLANT_ID is required for Analysis payloads.")
        payload = build_analysis_payload(self.config.plant_id, requested_date)
        return self.safe_request_json("POST", self.config.api_url, json_body=payload)

    def safe_request_json(
        self,
        method: str,
        url: str,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        """Send a guarded read-only request and parse the JSON response."""

        assert_read_only_request(method, url)
        normalized_method = method.upper()

        if self.preview_requests:
            print_request_summary(normalized_method, url, json_body)

        headers: dict[str, str] = {
            "Accept": "application/json",
            "category": "2",
            "contentType": "application/json",
            "lang": self.config.lang,
            "platform": "web",
        }
        if self.config.timezone:
            headers["timezone"] = self.config.timezone
        if self.config.bearer_token:
            headers["Authorization"] = f"Bearer {self.config.bearer_token}"
        if self.config.cookie:
            headers["Cookie"] = self.config.cookie
        if self.config.token:
            headers["token"] = self.config.token
        if self.config.signature:
            headers["signature"] = self.config.signature
        if self.config.timestamp:
            headers["timestamp"] = self.config.timestamp
        if normalized_method == "POST":
            headers["Content-Type"] = "application/json"

        try:
            response = requests.request(
                normalized_method,
                url,
                headers=headers,
                json=json_body if normalized_method == "POST" else None,
                timeout=self.timeout_seconds,
            )
        except requests.Timeout as exc:
            raise NetworkTimeoutError(
                f"Network timeout after {self.timeout_seconds:g} seconds."
            ) from exc
        except requests.RequestException as exc:
            raise PVHubReadOnlyError(f"Network request failed: {exc}") from exc

        self._raise_for_known_http_errors(response)

        try:
            return response.json()
        except ValueError as exc:
            preview = response.text[:200].replace("\n", " ")
            raise InvalidJSONError(
                f"Response was not valid JSON. Status={response.status_code}. Preview={preview!r}"
            ) from exc

    @staticmethod
    def _raise_for_known_http_errors(response: Response) -> None:
        if response.status_code in {401, 403}:
            raise AuthenticationError(
                f"Authentication/authorization failed with HTTP {response.status_code}. "
                "Your cookie/token may be expired or the endpoint may not allow this account."
            )
        if response.status_code == 404:
            raise EndpointNotFoundError(
                "PVHub returned HTTP 404. Check that PVHUB_API_URL is the exact Request URL "
                "copied from Chrome DevTools."
            )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise PVHubReadOnlyError(
                f"PVHub returned HTTP {response.status_code}: {response.reason}"
            ) from exc


def print_request_summary(
    method: str,
    url: str,
    json_body: dict[str, Any] | None = None,
) -> None:
    """Print request details without secrets."""

    print("Read-only request preview")
    print(f"  Method: {method}")
    print(f"  URL: {redact_url(url)}")
    print("  Secrets: <redacted>")
    if json_body is not None:
        print("  JSON body:")
        print(indent_json(json_body))


def indent_json(data: Any) -> str:
    return json.dumps(data, indent=2, sort_keys=True)


def redact_url(url: str) -> str:
    """Redact sensitive-looking query parameters before logging a URL."""

    parsed = urlparse(url)
    if not parsed.query:
        return url

    redacted_params = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        lower_key = key.lower()
        if any(word in lower_key for word in SENSITIVE_QUERY_WORDS):
            redacted_params.append((key, "<redacted>"))
        else:
            redacted_params.append((key, value))

    return urlunparse(parsed._replace(query=urlencode(redacted_params, safe="<>")))
