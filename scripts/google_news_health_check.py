"""Run the six-probe Google News RSS operational health check (RC-72 rule)."""

from __future__ import annotations

from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from weekly_report.google_news_rss_provider import GoogleNewsRssProvider  # noqa: E402
from weekly_report.production_runner import (  # noqa: E402
    HEALTH_MIN_SUCCESS_COUNT,
    GoogleNewsHealthCheck,
)
from weekly_report.region_registry import RegionRegistry  # noqa: E402


def _print_attempt(number: int, result) -> None:
    print(f"attempt={number}")
    print(f"plan_item_count={result.plan_item_count}")
    print("probe_ordinals=" + ",".join(str(item) for item in result.probe_ordinals))
    for probe in result.probes:
        failure = probe.technical_failure_class or ""
        print(
            f"ordinal={probe.ordinal} market={probe.market_id} profile={probe.language_profile} "
            f"intent={probe.intent} status={probe.status} failure_class={failure}"
        )
    print(
        f"aggregate_status={result.status} success_count={result.success_count} "
        f"failure_count={result.failure_count}",
        flush=True,
    )


def main() -> int:
    check = GoogleNewsHealthCheck(RegionRegistry.from_file(), GoogleNewsRssProvider())

    def wait(seconds: float) -> None:
        print(
            f"health_gate=RETRY rule=at_least_{HEALTH_MIN_SUCCESS_COUNT}_success_and_only_RATE_LIMIT_failures "
            f"wait_seconds={int(seconds)}",
            flush=True,
        )
        time.sleep(seconds)

    gate = check.run_gated(sleep=wait, observe=_print_attempt)
    print(f"health_gate_status={'PASS' if gate.passed else 'FAIL'} attempts={len(gate.attempts)}")
    return 0 if gate.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
