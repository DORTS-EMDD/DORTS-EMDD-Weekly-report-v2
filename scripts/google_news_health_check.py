"""Run the six-probe Google News RSS operational health check."""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from weekly_report.google_news_rss_provider import GoogleNewsRssProvider  # noqa: E402
from weekly_report.production_runner import GoogleNewsHealthCheck  # noqa: E402
from weekly_report.region_registry import RegionRegistry  # noqa: E402


def main() -> int:
    result = GoogleNewsHealthCheck(RegionRegistry.from_file(), GoogleNewsRssProvider()).run()
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
        f"failure_count={result.failure_count}"
    )
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
