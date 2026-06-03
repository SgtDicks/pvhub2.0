"""Emit compact JSON for Home Assistant command_line sensors.

Monitoring only. This script performs the same guarded read-only PVHub request
as the CLI, then prints one JSON object suitable for Home Assistant.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from typing import Any

from .client import PVHubReadOnlyClient, PVHubReadOnlyError, parse_yyyy_mm_dd
from .summarize_response import find_series


SERIES_MAP = {
    "SoC": "battery_soc_percent",
    "pvPower": "pv_power_kw",
    "batChargePower": "battery_charge_power_kw",
    "batDischargePower": "battery_discharge_power_kw",
    "feedinPower": "grid_export_power_kw",
    "gridConsumptionPower": "grid_import_power_kw",
    "loadsPower": "load_power_kw",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Emit PVHub data as Home Assistant JSON.")
    parser.add_argument(
        "--date",
        help="Date to request in YYYY-MM-DD format. Default: today's local date.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="Network timeout in seconds. Default: 20.",
    )
    args = parser.parse_args()

    requested_date = parse_yyyy_mm_dd(args.date) if args.date else date.today()

    try:
        client = PVHubReadOnlyClient.from_env(
            timeout_seconds=args.timeout,
            preview_requests=False,
        )
        data = client.request_analysis_data(requested_date)
        output = build_homeassistant_payload(data)
    except PVHubReadOnlyError as exc:
        output = {
            "status": "error",
            "error": str(exc),
        }

    print(json.dumps(output, separators=(",", ":"), sort_keys=True))
    return 0


def build_homeassistant_payload(data: Any) -> dict[str, Any]:
    output: dict[str, Any] = {"status": "ok"}
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
        output[f"{key}_display"] = latest.get("valueShow")
        output[f"{key}_time"] = latest.get("index")
        latest_timestamp = latest.get("index") or latest_timestamp

    if latest_timestamp:
        output["updated_at"] = latest_timestamp

    return output


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


if __name__ == "__main__":
    raise SystemExit(main())
