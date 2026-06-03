"""Summarize a saved PVHub JSON response.

This is a local read-only helper. It does not call PVHub or send any data.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize a saved PVHub JSON response.")
    parser.add_argument("json_file", help="Path to a complete JSON response saved from the CLI.")
    args = parser.parse_args()

    try:
        data = load_json(Path(args.json_file))
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    series = find_series(data)
    if not series:
        print("No PVHub time-series arrays found.")
        return 0

    print("PVHub response summary")
    for item in series:
        variable = item.get("variable", "<unknown>")
        unit = item.get("unit", "")
        points = item.get("points") or item.get("data") or []
        numeric_values = [to_float(point.get("value")) for point in points if isinstance(point, dict)]
        numeric_values = [value for value in numeric_values if value is not None]
        first_index = points[0].get("index") if points and isinstance(points[0], dict) else ""
        last_index = points[-1].get("index") if points and isinstance(points[-1], dict) else ""

        print(f"- {variable}: {len(points)} point(s), unit={unit or 'n/a'}")
        if first_index or last_index:
            print(f"  range: {first_index} -> {last_index}")
        if numeric_values:
            print(
                "  values: "
                f"min={min(numeric_values):g}, "
                f"max={max(numeric_values):g}, "
                f"latest={numeric_values[-1]:g}"
            )

    return 0


def load_json(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    text = strip_powershell_prompt(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "Could not parse JSON. Make sure the file contains the full response, "
            "including the opening lines, and not a truncated terminal paste."
        ) from exc


def strip_powershell_prompt(text: str) -> str:
    lines = text.splitlines()
    kept = [line for line in lines if not line.startswith("PS ")]
    return "\n".join(kept).strip()


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


def to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    raise SystemExit(main())
