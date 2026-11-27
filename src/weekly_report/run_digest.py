"""RC-90 (section A.71): the concise run digest, observation only.

One short block printed at the very end of a run's log and job summary, so a
reader (or Claude Code) needs nothing else from the log: the section counts,
the technology titles, how long each stage took and how often Google News
rate-limited Search. It is projected from the finished result and the same
RunTrace; it recomputes no decision and cannot change the run's outcome.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .contracts import CategoryId
from .report_service import FORMAL_REPORT_SECTIONS

DIGEST_BEGIN = "===== RUN DIGEST ====="
DIGEST_END = "===== END RUN DIGEST ====="
TECHNOLOGY_SECTION = dict(FORMAL_REPORT_SECTIONS)[CategoryId.TECHNICAL_DEVELOPMENT]
# The formal run and the recall-only technology test mode (RC-90 item 3).
FORMAL_MODE = "FORMAL"
TECHNOLOGY_TEST_MODE = "TECHNOLOGY_TEST"
_COUNT_KEYS = (
    ("search_plan", "search_requests"),
    ("evidence_results", "evidence_results"),
    ("scope_results", "scope_results"),
    ("event_identity_records", "event_identity_records"),
    ("technical_gaps", "technical_gaps"),
)


def _minutes(milliseconds: int) -> str:
    return f"{milliseconds / 60000:.1f}"


def build_run_digest(
    result: Any,
    *,
    stage_elapsed_ms: Mapping[str, int],
    total_elapsed_ms: int,
    run_mode: str = FORMAL_MODE,
) -> str:
    """Return the digest text (plain lines between the two markers)."""

    lines = [DIGEST_BEGIN]
    period = f"{result.period_start.isoformat()}..{result.period_end.isoformat()}"
    lines.append(f"status={result.status.value} period={period} mode={run_mode}")
    report = getattr(result, "final_report", None)
    sections = {} if report is None else {section.category: section for section in report.sections}
    counts = [f"{title}={len(sections[title].events) if title in sections else 0}" for _id, title in FORMAL_REPORT_SECTIONS]
    total = 0 if report is None else len(report.events)
    lines.append(f"report_items={total if report is not None else 'NO_REPORT'} | " + " ".join(counts))
    technology = sections.get(TECHNOLOGY_SECTION)
    lines.append(f"{TECHNOLOGY_SECTION} titles:")
    if technology is None or not technology.events:
        lines.append("  (none)")
    else:
        lines.extend(f"  {index}. {event.headline}" for index, event in enumerate(technology.events, start=1))
    stages = " ".join(f"{stage}={_minutes(value)}" for stage, value in stage_elapsed_ms.items())
    lines.append(f"stage_minutes: {stages or 'none'} total={_minutes(total_elapsed_ms)}")
    classes = dict(getattr(result, "search_failure_class_distribution", None) or {})
    retries = getattr(result, "search_rate_limit_retries", None)
    lines.append(
        f"search_429: retried={0 if retries is None else retries} "
        f"failed_after_retry={classes.get('RATE_LIMIT', 0)}"
    )
    stage_counts = dict(getattr(result, "stage_counts", {}) or {})
    lines.append(
        "counts: " + " ".join(f"{label}={stage_counts[key]}" for key, label in _COUNT_KEYS if key in stage_counts)
    )
    lines.append(DIGEST_END)
    return "\n".join(lines) + "\n"


__all__ = [
    "DIGEST_BEGIN",
    "DIGEST_END",
    "FORMAL_MODE",
    "TECHNOLOGY_TEST_MODE",
    "build_run_digest",
]
