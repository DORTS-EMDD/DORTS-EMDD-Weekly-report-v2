"""P1 Search-to-Evidence measurement (test-only; not production code).

Runs the production Search planner, Google News RSS provider and candidate
normalizer for one report window, then resolves and fetches a deterministic
sample of candidates through the production EvidenceService with no semantic
judge (MaiAgent is never called). Every HTTP request (RSS, link resolution,
publisher fetch) is counted against one hard budget. The summary is written
after every step so a hard termination keeps completed measurements.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
import json
import sys
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from weekly_report import evidence_service as evidence_module  # noqa: E402
from weekly_report import google_news_links as links_module  # noqa: E402
from weekly_report import google_news_rss_provider as rss_module  # noqa: E402
from weekly_report.candidate_normalizer import CandidateNormalizer  # noqa: E402
from weekly_report.contracts import SearchProviderId, SearchWindow  # noqa: E402
from weekly_report.evidence_service import EvidenceService  # noqa: E402
from weekly_report.google_news_links import GoogleNewsLinkResolver  # noqa: E402
from weekly_report.google_news_rss_provider import GoogleNewsRssProvider  # noqa: E402
from weekly_report.region_registry import RegionRegistry  # noqa: E402
from weekly_report.report_application import ReportApplication  # noqa: E402
from weekly_report.search_executor import SearchExecutor  # noqa: E402
from weekly_report.search_planner import SearchPlanner  # noqa: E402


class BudgetExceeded(BaseException):
    """Deliberately not an Exception so production handlers cannot swallow it."""


class Budget:
    def __init__(self, http_limit: int, seconds: int) -> None:
        self.http_limit, self.seconds = http_limit, seconds
        self.used: Counter[str] = Counter()
        self.started = time.monotonic()

    @property
    def http_used(self) -> int:
        return sum(self.used.values())

    def take(self, kind: str) -> None:
        if time.monotonic() - self.started > self.seconds:
            raise BudgetExceeded("WALL_CLOCK")
        if self.http_used >= self.http_limit:
            raise BudgetExceeded("HTTP_BUDGET")
        self.used[kind] += 1


def _pub_date(value: str) -> date | None:
    try:
        return parsedate_to_datetime(value).astimezone(timezone.utc).date()
    except (TypeError, ValueError, IndexError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--http-budget", type=int, default=520)
    parser.add_argument("--seconds", type=int, default=1200)
    parser.add_argument("--reserve", type=int, default=6, help="HTTP requests kept unused at the end")
    parser.add_argument("--pacing", type=float, default=0.4)
    args = parser.parse_args()

    window = SearchWindow(date.fromisoformat(args.start), date.fromisoformat(args.end))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    budget = Budget(args.http_budget, args.seconds)
    summary: dict[str, Any] = {"window": window.as_mapping(), "budget": {"http_limit": args.http_budget, "seconds": args.seconds, "maiagent_calls": 0}}

    def save(stage: str) -> None:
        summary["stage_completed"] = stage
        summary["http_used"] = dict(budget.used)
        summary["http_used_total"] = budget.http_used
        summary["elapsed_seconds"] = round(time.monotonic() - budget.started, 1)
        (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")

    # --- Search (production planner, provider, executor) -----------------
    provider_counts = Counter()

    def rss_transport(url: str, timeout: float):
        budget.take("rss")
        response = rss_module._default_transport(url, timeout)
        # Observation only: count what the provider returned before its
        # publication-window filter.
        try:
            parsed = rss_module._parse_rss(response.body if isinstance(response.body, bytes) else str(response.body).encode())
            provider_counts["provider_items"] += len(parsed)
            provider_counts["provider_items_in_window"] += sum(
                1 for result in parsed if rss_module.published_within(result.published_at, window)
            )
        except Exception:
            provider_counts["unparsed_responses"] += 1
        return response

    registry = RegionRegistry.from_file()
    plan = SearchPlanner(registry).plan("selected", window=window)
    executor = SearchExecutor(
        {SearchProviderId.GOOGLE_NEWS_RSS: GoogleNewsRssProvider(rss_transport)}, pacing_seconds=args.pacing
    )
    abort = None
    try:
        execution = executor.execute(plan)
    except BudgetExceeded as stop:
        abort = f"SEARCH:{stop}"
        summary["abort"] = abort
        save("search_aborted")
        print(json.dumps(summary, ensure_ascii=False, indent=1))
        return 1
    statuses = Counter(attempt.status.value for attempt in execution.attempt_results)
    failures = Counter(
        str(getattr(attempt.technical_failure_class, "value", attempt.technical_failure_class))
        for attempt in execution.attempt_results
        if attempt.technical_failure_class is not None
    )
    acquisitions = ReportApplication._project_acquisitions(execution)
    raw_dates = [_pub_date(record.raw_result.published_at) for record in acquisitions]
    summary["search"] = {
        "configuration_version": plan.configuration_version,
        "plan_items": len(plan.items),
        "attempted": len(execution.attempt_results),
        "terminal_status": dict(statuses),
        "technical_failure_class": dict(failures),
        "raw_results": len(acquisitions),
        "raw_results_by_intent": dict(Counter(record.plan_item.intent.value for record in acquisitions)),
        "raw_pubdate_in_window": sum(1 for value in raw_dates if value and window.start <= value <= window.end),
        "raw_pubdate_outside_window": sum(1 for value in raw_dates if value and not window.start <= value <= window.end),
        "raw_pubdate_missing": sum(1 for value in raw_dates if value is None),
        "results_per_successful_request": round(len(acquisitions) / max(1, statuses.get("SUCCESS_WITH_RESULTS", 0)), 1),
        "provider_items_before_window_filter": provider_counts["provider_items"],
        "provider_items_kept_by_window_filter": provider_counts["provider_items_in_window"],
        "raw_results_by_family": dict(Counter(record.plan_item.query_family_id for record in acquisitions)),
        "requests_hitting_100_cap": sum(1 for attempt in execution.attempt_results if len(attempt.results) >= 100),
    }
    save("search")

    # --- Normalization -----------------------------------------------------
    normalized = CandidateNormalizer().normalize(acquisitions)
    candidates = [item.candidate for item in normalized.normalized_candidates]
    candidate_dates = [_pub_date(candidate.published_at) for candidate in candidates]
    titles = Counter(" ".join(candidate.title.casefold().split()) for candidate in candidates)
    summary["normalization"] = {
        "candidates": len(candidates),
        "candidates_by_intent": dict(Counter(candidate.discovery_intent for candidate in candidates)),
        "candidate_pubdate_in_window": sum(1 for value in candidate_dates if value and window.start <= value <= window.end),
        "candidate_pubdate_outside_window": sum(1 for value in candidate_dates if value and not window.start <= value <= window.end),
        "google_news_links": sum(1 for candidate in candidates if links_module.is_google_news_article_url(candidate.url)),
        "with_publisher_origin": sum(1 for candidate in candidates if candidate.publisher_url),
        "duplicate_title_candidates": sum(count - 1 for count in titles.values() if count > 1),
        "top_publishers": Counter(candidate.publisher for candidate in candidates).most_common(15),
    }
    families_by_candidate = {
        item.candidate.candidate_id: sorted({origin.record.plan_item.query_family_id for origin in item.acquisition_origins})
        for item in normalized.normalized_candidates
    }
    summary["candidates"] = [
        {
            "candidate_id": candidate.candidate_id,
            "intent": candidate.discovery_intent,
            "families": families_by_candidate.get(candidate.candidate_id, []),
            "publisher": candidate.publisher,
            "title": candidate.title[:160],
            "published_at": candidate.published_at,
        }
        for candidate in candidates
    ]
    save("normalization")

    # --- Evidence sample (resolution + fetch, no semantic judge) -------------
    def link_transport(method, url, headers, body, timeout):
        budget.take("link_resolution")
        return links_module._default_transport(method, url, headers, body, timeout)

    real_fetch = evidence_module._default_fetcher

    def fetcher(url: str):
        budget.take("publisher_fetch")
        return real_fetch(url, 10.0)

    service = EvidenceService(fetcher, link_resolver=GoogleNewsLinkResolver(link_transport))
    by_intent: dict[str, list] = {}
    for candidate in sorted(candidates, key=lambda item: item.candidate_id):
        by_intent.setdefault(candidate.discovery_intent, []).append(candidate)
    order = []
    while any(by_intent.values()):
        for intent in sorted(by_intent):
            if by_intent[intent]:
                order.append(by_intent[intent].pop(0))
    samples: list[dict[str, Any]] = []
    summary["evidence_sample"] = samples
    for candidate in order:
        if budget.http_used + 3 > args.http_budget - args.reserve:
            break
        try:
            result = service.evaluate(candidate)
        except BudgetExceeded as stop:
            abort = f"EVIDENCE:{stop}"
            break
        provenance = dict(result.provenance)
        samples.append({
            "candidate_id": candidate.candidate_id,
            "intent": candidate.discovery_intent,
            "publisher": candidate.publisher,
            "title": candidate.title[:160],
            "pubdate_in_window": (lambda value: None if value is None else window.start <= value <= window.end)(_pub_date(candidate.published_at)),
            "link_resolution": provenance.get("link_resolution"),
            "link_resolution_detail": provenance.get("link_resolution_detail"),
            "publisher_origin_check": provenance.get("publisher_origin_check"),
            "resolved_url": provenance.get("link_resolved_url"),
            "state": result.state.value,
            "gate": provenance.get("evidence_rejection_gate"),
            "reached_semantic_judge": provenance.get("response_validation_result") == "not_configured" or provenance.get("evidence_rejection_gate") == "SEMANTIC_MATCH",
        })
        save("evidence_sample")

    resolved = [sample for sample in samples if sample["resolved_url"]]
    summary["evidence_summary"] = {
        "sampled": len(samples),
        "link_resolution": dict(Counter(str(sample["link_resolution"]) for sample in samples)),
        "resolution_success_rate": round(len(resolved) / max(1, len(samples)), 3),
        "publisher_origin_check": dict(Counter(str(sample["publisher_origin_check"]) for sample in samples)),
        "gates": dict(Counter(str(sample["gate"]) for sample in samples)),
        "reached_semantic_judge": sum(1 for sample in samples if sample["reached_semantic_judge"]),
        "distinct_resolved_urls": len({sample["resolved_url"] for sample in resolved}),
        "resolved_hosts": Counter(
            (sample["resolved_url"] or "").split("/")[2] for sample in resolved
        ).most_common(20),
    }
    summary["abort"] = abort
    save("complete" if abort is None else "evidence_aborted")
    print(json.dumps({key: summary[key] for key in ("window", "http_used", "http_used_total", "elapsed_seconds", "search", "evidence_summary", "abort") if key in summary}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
