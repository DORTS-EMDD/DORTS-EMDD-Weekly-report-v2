"""Thin command-line entrypoint for the V2 production runner."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from weekly_report.contracts import RegionMode  # noqa: E402
from weekly_report.production_runner import ProductionRunner  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one Weekly-report V2 production report")
    parser.add_argument("--period-start", type=date.fromisoformat)
    parser.add_argument("--period-end", type=date.fromisoformat)
    parser.add_argument(
        "--region-mode",
        choices=tuple(mode.value for mode in RegionMode),
        default=RegionMode.SELECTED.value,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        runner = ProductionRunner.from_environment()
        result = runner.run(
            region_mode=args.region_mode,
            period_start=args.period_start,
            period_end=args.period_end,
        )
    except Exception as exc:
        print(f"status=CONFIGURATION_FAILURE failure_class={type(exc).__name__} diagnostic=production configuration unavailable")
        return 1
    print(result.summary())
    return 0 if result.successful else 1


if __name__ == "__main__":
    raise SystemExit(main())
