"""Manually supplied PVHub endpoint tester with read-only guards.

This helper does not discover endpoints, bypass security controls, or test
write/control paths. It only checks URLs you provide yourself.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .client import (
    PVHubReadOnlyClient,
    PVHubReadOnlyError,
    SafetyError,
    build_meter_payload,
    build_analysis_payload,
    indent_json,
    parse_yyyy_mm_dd,
)


def load_endpoint_urls(path: Path) -> list[str]:
    urls: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        urls.append(line)
    return urls


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Test manually provided read-only-looking PVHub endpoints."
    )
    parser.add_argument(
        "--endpoints-file",
        required=True,
        help="Text file containing one manually provided endpoint URL per line.",
    )
    parser.add_argument(
        "--method",
        choices=("GET", "POST"),
        default="POST",
        help="HTTP method to test. POST uses the meter query payload. Default: POST.",
    )
    parser.add_argument(
        "--date",
        default="2026-06-03",
        help="Date used for POST meter payloads in YYYY-MM-DD format. Default: 2026-06-03.",
    )
    parser.add_argument(
        "--payload",
        choices=("analysis", "meter"),
        default="analysis",
        help="POST payload shape. Use analysis for /dew/w/plant/analysis/raw. Default: analysis.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="Network timeout in seconds. Default: 20.",
    )
    args = parser.parse_args()

    try:
        endpoints = load_endpoint_urls(Path(args.endpoints_file))
        requested_date = parse_yyyy_mm_dd(args.date)
        client = PVHubReadOnlyClient.from_env(timeout_seconds=args.timeout)
    except (OSError, PVHubReadOnlyError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if not endpoints:
        print("Error: endpoint file did not contain any URLs.", file=sys.stderr)
        return 1

    payload = None
    if args.method == "POST":
        if args.payload == "analysis":
            if not client.config.plant_id:
                print("Error: PVHUB_PLANT_ID is required for analysis payloads.", file=sys.stderr)
                return 1
            payload = build_analysis_payload(client.config.plant_id, requested_date)
        else:
            if not client.config.rail_id:
                print("Error: PVHUB_RAIL_ID is required for meter payloads.", file=sys.stderr)
                return 1
            payload = build_meter_payload(client.config.rail_id, requested_date)

    failures = 0
    for url in endpoints:
        print("=" * 72)
        print(f"Testing endpoint: {url}")
        try:
            data = client.safe_request_json(args.method, url, json_body=payload)
        except SafetyError as exc:
            failures += 1
            print(f"Warning: skipped unsafe-looking endpoint: {exc}", file=sys.stderr)
            continue
        except PVHubReadOnlyError as exc:
            failures += 1
            print(f"Error: {exc}", file=sys.stderr)
            continue

        print("Response JSON")
        print(indent_json(data))

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
