"""P2 full production acceptance (test-only; not production code).

Runs the unchanged production composition (ProductionRunner.from_environment)
from live Google News Search to the formal report for one report period.
Every external call goes through a RunJournal (scripts/run_journal.py): RSS,
Google News link resolution, publisher fetches and MaiAgent responses are
stored under their request identity, so a run killed by its environment can
be started again and replays everything already obtained. Only unseen
requests are live, and the journal ledger enforces the HTTP, MaiAgent and
wall-clock budgets cumulatively across attempts. Delivery is disabled (no
recipient, LIVE_EMAIL_SEND=0). The RunTrace is appended line by line.
"""

from __future__ import annotations

import argparse
import base64
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
    HarnessAbort,
    _caller_task,
    fake_maiagent,
    load_environ,
    slot_outcomes,
    to_jsonable,
)
from run_journal import BudgetExhausted, RunJournal, request_key  # noqa: E402
from weekly_report import evidence_service as evidence_module  # noqa: E402
from weekly_report import google_news_links as links_module  # noqa: E402
from weekly_report import google_news_rss_provider as rss_module  # noqa: E402
from weekly_report.contracts import FetchedSource  # noqa: E402
from weekly_report.debug_service import ExecutionTrace, execution_trace  # noqa: E402
from weekly_report.google_news_rss_provider import RssTransportResponse  # noqa: E402
from weekly_report.maiagent_transport import (  # noqa: E402
    MaiAgentHttpResponse,
    MaiAgentResponseError,
    UrllibMaiAgentJsonTransport,
    parse_maiagent_response,
)
from weekly_report.production_runner import ProductionRunner  # noqa: E402


def _b64(data: bytes | str) -> str:
    return base64.b64encode(data.encode("utf-8") if isinstance(data, str) else data).decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))


def _fetch_failure(record: dict[str, Any]) -> BaseException:
    request_host = record.get("request_hostname") or ""
    failing_host = record.get("failing_endpoint_hostname") or ""
    return evidence_module._EvidenceFetchError(
        record.get("status_code"),
        request_url=f"https://{request_host}/" if request_host else "",
        failing_url=f"https://{failing_host}/" if failing_host else "",
        redirect_hop_count=record.get("redirect_hop_count"),
    )


def _parseable_maiagent(response: MaiAgentHttpResponse) -> bool:
    if response.status_code != 200:
        return False
    try:
        parse_maiagent_response(response.body)
    except MaiAgentResponseError:
        return False
    return True


def _transient_status(status: int | None) -> bool:
    return status is None or status == 429 or status >= 500


def _definitive_fetch_failure(exc: BaseException) -> bool:
    """A 4xx answer or a refused destination is final; timeouts, connection
    failures, 429 and 5xx are retried on resume."""

    if isinstance(exc, evidence_module._EvidenceFetchError):
        return not _transient_status(exc.status_code)
    return isinstance(exc, evidence_module._UnsafeDestinationError)


def seed_maiagent(journal: RunJournal, directories: list[Path]) -> dict[str, int]:
    """Import parseable responses recorded by earlier runs of the same code path."""

    seeded = skipped = 0
    for directory in directories:
        for request_path in sorted(directory.glob("*_request.json")):
            response_path = request_path.with_name(request_path.name.replace("_request.json", "_response.json"))
            if not response_path.exists():
                continue
            body, response = request_path.read_bytes(), response_path.read_bytes()
            try:
                parse_maiagent_response(response)
            except MaiAgentResponseError:
                skipped += 1
                continue
            record = {"response": {"status_code": 200, "body_b64": _b64(response)}, "seeded_from": str(request_path.name)}
            seeded += journal.seed("maiagent", request_key("maiagent", body), record)
    return {"seeded": seeded, "unparseable_skipped": skipped}


class JournalMaiAgentTransport:
    def __init__(self, inner, journal: RunJournal) -> None:
        self._inner, self._journal = inner, journal
        self.calls: list[dict[str, Any]] = []

    def __call__(self, endpoint, *, headers, body, timeout_seconds):
        task = _caller_task()
        record: dict[str, Any] = {"task": task, "request_bytes": len(body), "source": "replay"}

        def live():
            record["source"] = "live"
            return self._inner(endpoint, headers=headers, body=body, timeout_seconds=timeout_seconds)

        try:
            response = self._journal.call(
                "maiagent",
                "maiagent",
                request_key("maiagent", body),
                live,
                encode=lambda r: {"status_code": r.status_code, "body_b64": _b64(r.body or b"")},
                decode=lambda d: MaiAgentHttpResponse(int(d["status_code"]), _unb64(d["body_b64"])),
                # Only a complete, parseable 200 response is final; anything
                # else is retried live (RC-6), never replayed.
                keep_response=_parseable_maiagent,
                keep_failure=lambda exc: False,
            )
        except Exception as exc:
            record["outcome"] = f"TRANSPORT_ERROR:{type(exc).__name__}"
            self.calls.append(record)
            raise
        record["outcome"] = f"HTTP_{response.status_code}"
        self.calls.append(record)
        return response


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--journal", required=True, help="RunJournal directory; reuse it to resume")
    parser.add_argument("--http-budget", type=int, default=1500)
    parser.add_argument("--maiagent-budget", type=int, default=700)
    parser.add_argument("--seconds", type=int, default=100 * 60)
    parser.add_argument("--seed-maiagent", type=Path, action="append", default=[],
                        help="directory of NNN_task_request/response.json pairs from an earlier run")
    parser.add_argument("--prior-spend", default="",
                        help="live usage of an earlier attempt without a journal, e.g. maiagent=250,http=1120")
    parser.add_argument("--prior-spend-note", default="")
    parser.add_argument("--dry-run", action="store_true", help="fake RSS/links/fetch/MaiAgent; no network")
    parser.add_argument("--prepare-only", action="store_true", help="book prior spend and seed, then exit")
    parser.add_argument("--offline", action="store_true",
                        help="replay the journal only; an unrecorded (transient) request fails as a timeout")
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    journal = RunJournal(
        Path(args.journal),
        limits={"http": args.http_budget, "maiagent": args.maiagent_budget},
        seconds_limit=args.seconds,
    )
    journal.factories["_EvidenceFetchError"] = _fetch_failure
    journal.factories["_UnsafeDestinationError"] = lambda record: evidence_module._UnsafeDestinationError(record["message"])
    if args.prior_spend:
        spend = {key: int(value) for key, value in (item.split("=") for item in args.prior_spend.split(","))}
        journal.record_prior_spend(spend, args.prior_spend_note)
    seeding = seed_maiagent(journal, args.seed_maiagent) if args.seed_maiagent else {}
    if args.prepare_only:
        journal.ledger["attempts"].pop()
        journal.flush()
        print(json.dumps({"seeding": seeding, "live": journal.ledger["live"]}))
        return 0

    real_rss = rss_module._default_transport
    real_link = links_module._default_transport
    real_fetch = evidence_module._default_fetcher
    if args.dry_run:
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

    if args.offline:
        def _unrecorded(*_args, **_kwargs):
            raise TimeoutError("offline replay: request was not recorded (transient in the live run)")

        real_rss = real_link = real_fetch = _unrecorded  # noqa: F811

    def rss_transport(url: str, timeout: float):
        return journal.call(
            "rss", "http", request_key("rss", url), lambda: real_rss(url, timeout),
            encode=lambda r: {"body_b64": _b64(r.body), "status_code": r.status_code,
                              "final_url": r.final_url, "headers": dict(r.headers or {})},
            decode=lambda d: RssTransportResponse(_unb64(d["body_b64"]), d["status_code"], d["final_url"], d["headers"]),
            keep_response=lambda r: r.status_code == 200,
            keep_failure=lambda exc: False,
        )

    def link_transport(method, url, headers, body, timeout):
        return journal.call(
            "link", "http", request_key("link", method, url, body or b""),
            lambda: real_link(method, url, headers, body, timeout),
            encode=lambda r: {"status": r[0], "text": r[1]},
            decode=lambda d: (int(d["status"]), d["text"]),
            keep_response=lambda r: not _transient_status(r[0]),
            keep_failure=lambda exc: False,
        )

    def fetcher(url: str, timeout_seconds: float):
        return journal.call(
            "fetch", "http", request_key("fetch", url), lambda: real_fetch(url, timeout_seconds),
            encode=lambda r: {"url": r.url, "content": r.content, "status_code": r.status_code,
                              "content_type": r.content_type, "redirect_chain": list(r.redirect_chain)},
            decode=lambda d: FetchedSource(d["url"], d["content"], d["status_code"], d["content_type"], tuple(d["redirect_chain"])),
            keep_failure=_definitive_fetch_failure,
        )

    # The production composition builds GoogleNewsLinkResolver() and
    # EvidenceService() with these module-level defaults.
    links_module._default_transport = link_transport  # type: ignore[assignment]
    evidence_module._default_fetcher = fetcher  # type: ignore[assignment]
    inner_maiagent = fake_maiagent if args.dry_run else UrllibMaiAgentJsonTransport()
    if args.offline:
        inner_maiagent = _unrecorded
    maiagent = JournalMaiAgentTransport(inner_maiagent, journal)

    trace_path = out / "trace.jsonl"
    if trace_path.exists() and trace_path.stat().st_size:
        # Keep the trace of an interrupted attempt as evidence.
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        trace_path.rename(out / f"trace.interrupted-{stamp}.jsonl")
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
            try:
                captured["result"] = application.run(*a, **k)
            except Exception:
                # The runner reports only the exception class; keep the
                # traceback so an application failure is explainable.
                import traceback

                (out / "application_exception.txt").write_text(traceback.format_exc(), encoding="utf-8")
                raise
            return captured["result"]

    runner._application = Capture()  # harness-only proxy; production code unchanged

    remaining = max(1, int(args.seconds - journal.elapsed_seconds()))
    watchdog = threading.Timer(remaining + 60, _thread.interrupt_main)
    watchdog.daemon = True
    watchdog.start()
    started = dt.datetime.now(dt.timezone.utc)
    run_result, abort = None, None
    try:
        with execution_trace(trace):
            run_result = runner.run(region_mode="selected", period_start=args.start, period_end=args.end)
    except (HarnessAbort, BudgetExhausted) as exc:
        abort = str(exc)
    except KeyboardInterrupt:
        abort = "WATCHDOG_WALL_CLOCK"
    finally:
        watchdog.cancel()
        journal.flush()

    result = captured.get("result")
    identity = {}
    if result is not None and result.normalization_result is not None:
        identity = {item.candidate.candidate_id: item.candidate.candidate_id for item in result.normalization_result.normalized_candidates}
    summary: dict[str, Any] = {
        "attempt_started_utc": started.isoformat(),
        "git_head": os.popen(f'git -C "{REPO}" rev-parse HEAD').read().strip(),
        "dry_run": args.dry_run,
        "period": [args.start, args.end],
        "abort": abort,
        "ledger": journal.ledger,
        "budgets": {"http": args.http_budget, "maiagent": args.maiagent_budget, "seconds": args.seconds},
        "maiagent_seeding": seeding,
        "run_status": None if run_result is None else to_jsonable(run_result.status),
        "run_failure": None if run_result is None else {
            "stage": run_result.failure_stage, "class": run_result.failure_class, "diagnostic": run_result.diagnostic,
        },
        "stage_counts": None if run_result is None else to_jsonable(run_result.stage_counts),
        "stage_elapsed_ms": stage_ms,
        "maiagent_calls_by_task": {
            source: dict(Counter(call["task"] for call in maiagent.calls if call["source"] == source))
            for source in ("live", "replay")
        },
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
        (Path(args.journal) / "application_result.json").write_text(
            json.dumps(to_jsonable(result), ensure_ascii=False, indent=1), encoding="utf-8"
        )
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    if run_result is not None and run_result.final_report is not None:
        (out / "final_report.md").write_text(run_result.final_report.content, encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("abort", "run_status", "stage_counts", "maiagent_calls_by_task", "final_report_event_count")}, ensure_ascii=False, indent=1))
    print(json.dumps({"live": journal.ledger["live"], "replayed": journal.ledger["replayed"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
