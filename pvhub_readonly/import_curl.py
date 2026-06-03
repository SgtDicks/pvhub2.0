"""Import PVHub request details from a locally saved DevTools cURL command.

This helper is for your own logged-in PVHub browser session only. It does not
bypass authentication or security controls. It reads a cURL command you copied
from Chrome DevTools and writes the URL/token/rail ID to .env without printing
secrets.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from .client import assert_read_only_request


AUTH_HEADER_RE = re.compile(
    r"""Authorization\s*:\s*Bearer\s+([^'"\s]+)""",
    re.IGNORECASE,
)
COOKIE_HEADER_RE = re.compile(
    r"""Cookie\s*:\s*([^'"\r\n]+)""",
    re.IGNORECASE,
)
TOKEN_HEADER_RE = re.compile(
    r"""(?:^|\s)token\s*:\s*([^'"\r\n]+)""",
    re.IGNORECASE,
)
HEADER_PATTERNS = {
    "PVHUB_SIGNATURE": re.compile(r"""(?:^|\s)signature\s*:\s*([^'"\r\n]+)""", re.IGNORECASE),
    "PVHUB_TIMESTAMP": re.compile(r"""(?:^|\s)timestamp\s*:\s*([^'"\r\n]+)""", re.IGNORECASE),
    "PVHUB_LANG": re.compile(r"""(?:^|\s)lang\s*:\s*([^'"\r\n]+)""", re.IGNORECASE),
    "PVHUB_TIMEZONE": re.compile(r"""(?:^|\s)timezone\s*:\s*([^'"\r\n]+)""", re.IGNORECASE),
}
URL_RE = re.compile(r"""curl(?:\.exe)?\s+(?:--location\s+)?["']([^"']+)["']""", re.IGNORECASE)
DATA_RE = re.compile(
    r"""(?:--data-raw|--data|--data-binary|-d)\s+(["'])(.*?)\1""",
    re.IGNORECASE | re.DOTALL,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import PVHub API URL/token/rail ID from a locally saved cURL command."
    )
    parser.add_argument(
        "--curl-file",
        required=True,
        help="Path to a text file containing Chrome DevTools 'Copy as cURL' output.",
    )
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Destination .env file. Default: .env",
    )
    args = parser.parse_args()

    curl_path = Path(args.curl_file)
    env_path = Path(args.env_file)

    try:
        curl_text = curl_path.read_text(encoding="utf-8")
        values = extract_values(curl_text)
        assert_read_only_request("POST", values["PVHUB_API_URL"])
        write_env(env_path, values)
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Updated {env_path} with PVHub API URL, bearer token, and rail ID.")
    print("Bearer token was not printed. Delete the temporary cURL file when you are done.")
    return 0


def extract_values(curl_text: str) -> dict[str, str]:
    url_match = URL_RE.search(curl_text)
    auth_match = AUTH_HEADER_RE.search(curl_text)
    cookie_match = COOKIE_HEADER_RE.search(curl_text)
    token_match = TOKEN_HEADER_RE.search(curl_text)
    data_match = DATA_RE.search(curl_text)

    if not url_match:
        raise ValueError("Could not find the cURL Request URL.")
    if not any((auth_match, cookie_match, token_match)):
        raise ValueError("Could not find Authorization, Cookie, or token header auth details.")
    if not data_match:
        raise ValueError("Could not find a JSON --data payload containing railID.")

    payload = parse_json_payload(data_match.group(2))
    values = {
        "PVHUB_API_URL": url_match.group(1),
    }
    rail_id = payload.get("railID") or os.getenv("PVHUB_RAIL_ID")
    plant_id = payload.get("plantId") or os.getenv("PVHUB_PLANT_ID")
    if isinstance(rail_id, str) and rail_id:
        values["PVHUB_RAIL_ID"] = rail_id
    if isinstance(plant_id, str) and plant_id:
        values["PVHUB_PLANT_ID"] = plant_id
    if "PVHUB_RAIL_ID" not in values and "PVHUB_PLANT_ID" not in values:
        raise ValueError("Could not find railID or plantId in the cURL JSON payload.")
    if auth_match:
        values["PVHUB_BEARER_TOKEN"] = auth_match.group(1).strip()
    if cookie_match:
        values["PVHUB_COOKIE"] = cookie_match.group(1).strip()
    if token_match:
        values["PVHUB_TOKEN"] = token_match.group(1).strip()
    for env_name, pattern in HEADER_PATTERNS.items():
        match = pattern.search(curl_text)
        if match:
            values[env_name] = match.group(1).strip()
    return values


def parse_json_payload(raw_payload: str) -> dict[str, Any]:
    cleaned = raw_payload.strip()
    cleaned = cleaned.replace('\\"', '"')

    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError("Could not parse the cURL --data payload as JSON.") from exc

    if not isinstance(payload, dict):
        raise ValueError("The cURL --data payload was not a JSON object.")
    return payload


def write_env(path: Path, values: dict[str, str]) -> None:
    existing: dict[str, str] = {}
    order: list[str] = []

    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            existing[key] = value
            order.append(key)

    existing.update(values)
    for key in values:
        if key not in order:
            order.append(key)

    lines = [f"{key}={existing[key]}" for key in order if key in existing]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
