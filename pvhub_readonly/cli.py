"""Command-line meter data reader for PVHub 2.0.

Monitoring only. This script must not be extended to perform inverter control,
battery control, settings changes, export-limit changes, or device writes.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .client import PVHubReadOnlyClient, PVHubReadOnlyError, indent_json, parse_yyyy_mm_dd


def main() -> int:
    parser = argparse.ArgumentParser(description="Read PVHub 2.0 meter data safely.")
    parser.add_argument(
        "--date",
        required=True,
        help="Date to request in YYYY-MM-DD format, for example 2026-06-03.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="Network timeout in seconds. Default: 20.",
    )
    parser.add_argument(
        "--payload",
        choices=("analysis", "meter"),
        default="analysis",
        help="Payload shape to send. Use analysis for /dew/w/plant/analysis/raw. Default: analysis.",
    )
    parser.add_argument(
        "--output-json",
        help="Optional path to save the raw JSON response without request-preview text.",
    )
    args = parser.parse_args()

    try:
        requested_date = parse_yyyy_mm_dd(args.date)
        client = PVHubReadOnlyClient.from_env(timeout_seconds=args.timeout)
        if args.payload == "analysis":
            data = client.request_analysis_data(requested_date)
        else:
            data = client.request_meter_data(requested_date)
    except PVHubReadOnlyError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("PVHub JSON response")
    print(indent_json(data))
    if args.output_json:
        Path(args.output_json).write_text(indent_json(data) + "\n", encoding="utf-8")
        print(f"Saved JSON response to {args.output_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
