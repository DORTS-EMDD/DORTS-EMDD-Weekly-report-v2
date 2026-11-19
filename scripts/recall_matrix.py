"""Turn the recall_periods dispatch input into a GitHub Actions matrix.

Orchestration only: it validates the text format ``START:END,START:END`` and
emits the job matrix. It decides nothing about a reporting period; each pair is
passed unchanged to the shared production CLI.
"""

from __future__ import annotations

from datetime import date
import json
import os
import sys

MAX_PERIODS = 8


def parse_periods(text: str) -> list[dict[str, str]]:
    items = [part.strip() for part in text.split(",") if part.strip()]
    if not items:
        raise ValueError("recall_periods is empty")
    if len(items) > MAX_PERIODS:
        raise ValueError(f"recall_periods has {len(items)} periods; at most {MAX_PERIODS}")
    periods: list[dict[str, str]] = []
    for item in items:
        start_text, separator, end_text = item.partition(":")
        if not separator:
            raise ValueError(f"period {item!r} is not START:END")
        start, end = date.fromisoformat(start_text.strip()), date.fromisoformat(end_text.strip())
        if end < start:
            raise ValueError(f"period {item!r} ends before it starts")
        entry = {"start": start.isoformat(), "end": end.isoformat()}
        if entry in periods:
            raise ValueError(f"period {item!r} is listed twice")
        periods.append(entry)
    return periods


def main() -> int:
    try:
        periods = parse_periods(os.environ.get("RECALL_PERIODS", ""))
    except ValueError as exc:
        print(f"::error title=recall_periods::{exc}")
        return 1
    matrix = json.dumps({"include": periods}, separators=(",", ":"))
    print(f"matrix={matrix}")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"matrix={matrix}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
