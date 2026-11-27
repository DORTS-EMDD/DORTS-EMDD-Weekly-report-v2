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


def _distribution(values: Mapping[str, int]) -> str:
    return ",".join(f"{key}={values[key]}" for key in sorted(values)) or "none"


def _minutes(milliseconds: int) -> str:
    return f"{milliseconds / 60000:.1f}"


def build_run_digest(
    result: Any,
    *,
    stage_elapsed_ms: Mapping[str, int],
    total_elapsed_ms: int,
    run_mode: str = FORMAL_MODE,
    maiagent_attempts: Mapping[str, Mapping[str, int]] | None = None,
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
    # MaiAgent HTTP attempts by stage (OK and each failure class; a retried
    # transient failure is one failed attempt plus the retry).
    attempts = {stage: dict(counts) for stage, counts in (maiagent_attempts or {}).items()}
    total_attempts = sum(sum(counts.values()) for counts in attempts.values())
    by_class: dict[str, int] = {}
    for counts in attempts.values():
        for outcome, count in counts.items():
            if outcome != "OK":
                by_class[outcome] = by_class.get(outcome, 0) + count
    lines.append(
        f"maiagent: attempts={total_attempts} ok={total_attempts - sum(by_class.values())} "
        f"failed={_distribution(by_class)} by_stage="
        + (",".join(f"{stage}={sum(counts.values())}" for stage, counts in attempts.items()) or "none")
    )
    # Errors per stage: disclosed technical gaps, plus Search failures and
    # Validation FAILs.
    errors = {
        key.removeprefix("technical_gaps_"): value
        for key, value in stage_counts.items()
        if key.startswith("technical_gaps_")
    }
    if getattr(result, "search_failure_count", None):
        errors["search_failures"] = result.search_failure_count
    if stage_counts.get("validation_failed"):
        errors["validation_failed"] = stage_counts["validation_failed"]
    lines.append(f"stage_errors: {_distribution(errors)}")
    # Site blocking: publisher pages answering 403 or 429, and Google News link
    # resolutions still rate-limited after their retry.
    statuses = dict(getattr(result, "evidence_http_status_distribution", None) or {})
    signatures = dict(getattr(result, "technical_gap_signature_distribution", None) or {})
    link_429 = sum(count for signature, count in signatures.items()
                   if "LINK_RESOLUTION" in signature and signature.endswith("HTTP_429"))
    lines.append(
        f"site_blocking: evidence_http_403={statuses.get('403', 0)} evidence_http_429={statuses.get('429', 0)} "
        f"link_resolution_429_gaps={link_429}"
    )
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
