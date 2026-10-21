"""P2 full production acceptance (test-only; not production code).

Runs the unchanged production composition (ProductionRunner.from_environment)
from live Google News Search to the formal report for one report period.
Every network call is counted against hard budgets: RSS, Google News link
resolution and publisher fetches against one HTTP budget, MaiAgent calls
against another. Delivery is disabled (no recipient, LIVE_EMAIL_SEND=0). The
RunTrace is appended line by line so completed stages survive termination.
"""

from __future__ import annotations

import argparse
from collections import Counter
import datetime as dt
import json
import os
import sys
import threading
import _thread
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from phase_a_acceptance import (  # noqa: E402
    Budget,
    CountingMaiAgentTransport,
    HarnessAbort,
    fake_maiagent,
    load_environ,
    slot_outcomes,
    to_jsonable,
)
from weekly_report import evidence_service as evidence_module  # noqa: E402
from weekly_report import google_news_links as links_module  # noqa: E402
from weekly_report import google_news_rss_provider as rss_module  # noqa: E402
from weekly_report.debug_service import ExecutionTrace, execution_trace  # noqa: E402
from weekly_report.maiagent_transport import UrllibMaiAgentJsonTransport  # noqa: E402
from weekly_report.production_runner import ProductionRunner  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--scratch", required=True)
    parser.add_argument("--http-budget", type=int, default=1500)
    parser.add_argument("--maiagent-budget", type=int, default=700)
    parser.add_argument("--seconds", type=int, default=100 * 60)
    parser.add_argument("--dry-run", action="store_true", help="fake RSS/links/fetch/MaiAgent; no network")
    args = parser.parse_args()

    out, scratch = Path(args.out), Path(args.scratch)
    for path in (out, scratch / "maiagent"):
        path.mkdir(parents=True, exist_ok=True)
    budget = Budget(args.http_budget, args.maiagent_budget, args.seconds)
    http_by_kind: Counter[str] = Counter()

    def take_http(kind: str) -> None:
        budget.check_clock()
        if budget.http_used >= budget.http_limit:
            budget.stop(f"HTTP_BUDGET_EXCEEDED ({budget.http_limit})")
        budget.http_used += 1
        http_by_kind[kind] += 1

    real_rss = rss_module._default_transport
    real_link = links_module._default_transport
    real_fetch = evidence_module._default_fetcher
    if args.dry_run:
        from weekly_report.contracts import FetchedSource
        from weekly_report.google_news_rss_provider import RssTransportResponse

        published = dt.datetime.fromisoformat(args.start).strftime("%a, %d %b %Y 08:00:00 GMT")

        def real_rss(url, timeout):  # noqa: F811 - offline plumbing only
            item = (
                f"<item><title>Metro line {abs(hash(url)) % 997} opens</title>"
                f"<link>https://news.google.com/rss/articles/DRY{abs(hash(url)) % 997}</link>"
                f"<pubDate>{published}</pubDate><source url=\"https://pub.example\">Pub</source></item>"
            )
            return RssTransportResponse(f"<rss><channel>{item}</channel></rss>".encode())

        def real_link(method, url, headers, body, timeout):  # noqa: F811
            if method == "GET":
                return 200, '<div data-n-a-sg="S" data-n-a-ts="1">'
            inner = json.dumps(["garturlres", "https://pub.example/a", 1])
            return 200, ")]}'\n\n" + json.dumps([["wrb.fr", "Fbv4je", inner]])

        def real_fetch(url, timeout_seconds):  # noqa: F811
            html = "<html><body><article><h1>Metro line opens</h1><p>The metro operator opened a new line.</p></article></body></html>"
            return FetchedSource(url=url, content=html, status_code=200, content_type="text/html", redirect_chain=(url,))

    def rss_transport(url: str, timeout: float):
        take_http("rss")
        return real_rss(url, timeout)

    def link_transport(method, url, headers, body, timeout):
        take_http("link_resolution")
        return real_link(method, url, headers, body, timeout)

    def fetcher(url: str, timeout_seconds: float):
        take_http("publisher_fetch")
        return real_fetch(url, timeout_seconds)

    # The production composition builds GoogleNewsLinkResolver() and
    # EvidenceService() with these module-level defaults.
    links_module._default_transport = link_transport  # type: ignore[assignment]
    evidence_module._default_fetcher = fetcher  # type: ignore[assignment]
    maiagent = CountingMaiAgentTransport(
        fake_maiagent if args.dry_run else UrllibMaiAgentJsonTransport(), budget, scratch / "maiagent"
    )

    trace_path = out / "trace.jsonl"
    trace_path.write_text("", encoding="utf-8")
    stage_ms: dict[str, Any] = {}

    def sink(line: str) -> None:
        with trace_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        record = json.loads(line)
        if record.get("event") in {"STAGE_COMPLETED", "STAGE_FAILED"}:
            stage_ms[record["stage"]] = record.get("elapsed_ms")

    trace = ExecutionTrace(sink=sink, environ={})
    runner = ProductionRunner.from_environment(
        environ=load_environ(args.dry_run), transport=maiagent, rss_transport=rss_transport
    )
    application = runner.application
    captured: dict[str, Any] = {}

    class Capture:
        def run(self, *a, **k):
            captured["result"] = application.run(*a, **k)
            return captured["result"]

    runner._application = Capture()  # harness-only proxy; production code unchanged

    watchdog = threading.Timer(args.seconds + 60, _thread.interrupt_main)
    watchdog.daemon = True
    watchdog.start()
    started = dt.datetime.now(dt.timezone.utc)
    run_result, abort = None, None
    try:
        with execution_trace(trace):
            run_result = runner.run(region_mode="selected", period_start=args.start, period_end=args.end)
    except HarnessAbort as exc:
        abort = str(exc)
    except KeyboardInterrupt:
        abort = "WATCHDOG_WALL_CLOCK"
    finally:
        watchdog.cancel()

    result = captured.get("result")
    identity = {}
    if result is not None and result.normalization_result is not None:
        identity = {item.candidate.candidate_id: item.candidate.candidate_id for item in result.normalization_result.normalized_candidates}
    summary: dict[str, Any] = {
        "run_started_utc": started.isoformat(),
        "git_head": os.popen(f'git -C "{REPO}" rev-parse HEAD').read().strip(),
        "dry_run": args.dry_run,
        "period": [args.start, args.end],
        "abort": abort,
        "wall_clock_seconds": round(budget.elapsed(), 1),
        "budgets": {
            "http": [budget.http_used, budget.http_limit],
            "http_by_kind": dict(http_by_kind),
            "maiagent_calls": [budget.maiagent_used, budget.maiagent_limit],
            "seconds": budget.seconds,
        },
        "run_status": None if run_result is None else to_jsonable(run_result.status),
        "run_failure": None if run_result is None else {
            "stage": run_result.failure_stage, "class": run_result.failure_class, "diagnostic": run_result.diagnostic,
        },
        "stage_counts": None if run_result is None else to_jsonable(run_result.stage_counts),
        "stage_elapsed_ms": stage_ms,
        "maiagent_calls_by_task": dict(Counter(call["task"] for call in maiagent.calls)),
        "maiagent_outcomes": dict(Counter(call["outcome"] for call in maiagent.calls)),
        "final_report_event_count": None
        if run_result is None or run_result.final_report is None else run_result.final_report.event_count,
    }
    if result is not None:
        evidence = result.evidence_results or ()
        summary["evidence_gates"] = dict(Counter(
            str(dict(item.provenance).get("evidence_rejection_gate", "READY")) for item in evidence
        ))
        summary["candidate_outcomes"] = slot_outcomes(result, identity)
        summary["technical_gaps"] = [to_jsonable(gap) for gap in result.technical_gaps]
        summary["technical_gap_classes"] = dict(Counter(f"{gap.stage}:{gap.failure_class}" for gap in result.technical_gaps))
        summary["metadata_exclusions"] = [to_jsonable(item) for item in result.metadata_exclusions]
        if result.final_report is not None:
            summary["disclosure"] = to_jsonable(result.final_report.disclosure)
        (scratch / "application_result.json").write_text(
            json.dumps(to_jsonable(result), ensure_ascii=False, indent=1), encoding="utf-8"
        )
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    if run_result is not None and run_result.final_report is not None:
        (out / "final_report.md").write_text(run_result.final_report.content, encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("abort", "wall_clock_seconds", "budgets", "run_status", "stage_counts", "maiagent_calls_by_task", "final_report_event_count")}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
