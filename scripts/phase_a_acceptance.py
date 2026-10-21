"""Phase A bounded live acceptance harness (test-only; not production code).

Runs the unchanged production composition (ProductionRunner.from_environment)
over a frozen manifest of publisher URLs:

* Search: a replay RSS transport serves the frozen manifest as RSS for one
  plan item per discovery intent and empty RSS for every other item. No
  Search request reaches the network.
* Evidence: the real default fetcher, wrapped only to count/record requests.
* MaiAgent: the real transport, wrapped only to count/time calls.
* Delivery: disabled by an explicit environ (LIVE_EMAIL_SEND=0, no recipient).

Budgets are enforced by raising HarnessAbort (a BaseException, so production
``except Exception`` blocks cannot swallow it). Use --dry-run for a fully
offline plumbing check with fake fetcher/MaiAgent and blocked sockets.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import enum
import hashlib
import inspect
import json
import os
import socket
import sys
import threading
import _thread
import time
from collections import Counter
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from weekly_report import evidence_service as evidence_module  # noqa: E402
from weekly_report import google_news_rss_provider as rss_module  # noqa: E402
from weekly_report.contracts import FetchedSource, RegionMode  # noqa: E402
from weekly_report.debug_service import ExecutionTrace, execution_trace  # noqa: E402
from weekly_report.maiagent_transport import (  # noqa: E402
    MaiAgentHttpResponse,
    SHARED_MAIAGENT_CONFIG_KEYS,
    UrllibMaiAgentJsonTransport,
)
from weekly_report.production_runner import ProductionRunner  # noqa: E402
from weekly_report.region_registry import RegionRegistry  # noqa: E402
from weekly_report.search_planner import SearchPlanner  # noqa: E402


class HarnessAbort(BaseException):
    """Budget or safety stop; deliberately not an Exception subclass."""


TASK_MODULES = {
    "maiagent_semantic_judge_provider": "evidence_semantic_judge",
    "maiagent_evidence_metadata_provider": "evidence_metadata_extraction",
    "maiagent_scope_provider": "scope_semantic_proposal",
    "maiagent_event_identity_provider": "event_identity_semantic_proposal",
    "category_semantic_provider": "category_semantic_proposal",
    "maiagent_taxonomy_provider": "taxonomy_semantic_proposal",
    "maiagent_reportability_provider": "reportability_semantic_proposal",
    "maiagent_validation_provider": "validation_semantic_check",
    "writer": "writer",
}


class Budget:
    def __init__(self, http: int, maiagent: int, seconds: int) -> None:
        self.http_limit, self.maiagent_limit, self.seconds = http, maiagent, seconds
        self.http_used = 0
        self.maiagent_used = 0
        self.consecutive_timeouts = 0
        self.started = time.monotonic()
        self.abort_reason: str | None = None

    def elapsed(self) -> float:
        return time.monotonic() - self.started

    def check_clock(self) -> None:
        if self.elapsed() > self.seconds:
            self.stop(f"WALL_CLOCK_BUDGET_EXCEEDED ({self.seconds}s)")

    def stop(self, reason: str) -> None:
        self.abort_reason = self.abort_reason or reason
        raise HarnessAbort(reason)


def _caller_task() -> str:
    for frame in inspect.stack()[2:40]:
        name = Path(frame.filename).stem
        if name in TASK_MODULES:
            return TASK_MODULES[name]
    return "unknown"


class CountingMaiAgentTransport:
    def __init__(self, inner, budget: Budget, body_dir: Path) -> None:
        self._inner, self._budget, self._body_dir = inner, budget, body_dir
        self.calls: list[dict[str, Any]] = []

    def __call__(self, endpoint, *, headers, body, timeout_seconds):
        self._budget.check_clock()
        if self._budget.maiagent_used >= self._budget.maiagent_limit:
            self._budget.stop(f"MAIAGENT_CALL_BUDGET_EXCEEDED ({self._budget.maiagent_limit})")
        self._budget.maiagent_used += 1
        index = self._budget.maiagent_used
        task = _caller_task()
        record: dict[str, Any] = {"index": index, "task": task, "request_bytes": len(body)}
        started = time.monotonic()
        try:
            response = self._inner(endpoint, headers=headers, body=body, timeout_seconds=timeout_seconds)
        except TimeoutError:
            record.update(outcome="TIMEOUT", latency_s=round(time.monotonic() - started, 3))
            self.calls.append(record)
            self._budget.consecutive_timeouts += 1
            if self._budget.consecutive_timeouts >= 3:
                self._budget.stop("THREE_CONSECUTIVE_MAIAGENT_TIMEOUTS")
            raise
        except Exception as exc:
            record.update(outcome=f"TRANSPORT_ERROR:{type(exc).__name__}", latency_s=round(time.monotonic() - started, 3))
            self.calls.append(record)
            raise
        self._budget.consecutive_timeouts = 0
        record.update(
            outcome=f"HTTP_{response.status_code}",
            latency_s=round(time.monotonic() - started, 3),
            response_bytes=len(response.body or b""),
        )
        self.calls.append(record)
        # Bodies contain article text: kept only in the local scratch directory.
        (self._body_dir / f"{index:03d}_{task}_request.json").write_bytes(body)
        (self._body_dir / f"{index:03d}_{task}_response.json").write_bytes(response.body or b"")
        return response


class RecordingFetcher:
    def __init__(self, inner, budget: Budget, raw_dir: Path, slot_by_url: dict[str, str]) -> None:
        self._inner, self._budget, self._raw_dir = inner, budget, raw_dir
        self._slot_by_url = slot_by_url
        self.requests: list[dict[str, Any]] = []

    def __call__(self, url: str, timeout_seconds: float) -> FetchedSource:
        self._budget.check_clock()
        if self._budget.http_used + 1 > self._budget.http_limit:
            self._budget.stop(f"EVIDENCE_HTTP_BUDGET_EXCEEDED ({self._budget.http_limit})")
        slot = self._slot_by_url.get(url, "?")
        started = time.monotonic()
        record: dict[str, Any] = {"slot": slot, "url": url}
        try:
            fetched = self._inner(url, timeout_seconds)
        except BaseException as exc:
            hops = getattr(exc, "redirect_hop_count", None)
            used = 1 + (hops if isinstance(hops, int) else 0)
            self._budget.http_used += used
            record.update(
                outcome=f"ERROR:{type(exc).__name__}",
                status_code=getattr(exc, "status_code", None),
                failing_host=getattr(exc, "failing_endpoint_hostname", None),
                http_requests=used,
                latency_s=round(time.monotonic() - started, 3),
            )
            self.requests.append(record)
            if self._budget.http_used > self._budget.http_limit:
                self._budget.stop(f"EVIDENCE_HTTP_BUDGET_EXCEEDED ({self._budget.http_limit})")
            raise
        chain = tuple(fetched.redirect_chain or ())
        distinct = []
        for item in chain:
            if not distinct or distinct[-1] != item:
                distinct.append(item)
        used = max(1, len(distinct))
        self._budget.http_used += used
        content = fetched.content or ""
        digest = hashlib.sha256(content.encode("utf-8", "replace")).hexdigest()
        (self._raw_dir / f"{slot}.html").write_text(content, encoding="utf-8")
        record.update(
            outcome=f"HTTP_{fetched.status_code}",
            final_url=fetched.url,
            content_type=fetched.content_type,
            content_chars=len(content),
            sha256=digest,
            redirect_chain=list(chain),
            http_requests=used,
            latency_s=round(time.monotonic() - started, 3),
        )
        self.requests.append(record)
        if self._budget.http_used > self._budget.http_limit:
            self._budget.stop(f"EVIDENCE_HTTP_BUDGET_EXCEEDED ({self._budget.http_limit})")
        return fetched


def _rfc822(day: str) -> str:
    value = dt.datetime.fromisoformat(day).replace(hour=12, tzinfo=dt.timezone.utc)
    return value.strftime("%a, %d %b %Y %H:%M:%S GMT")


def build_replay_transport(manifest: dict[str, Any]):
    plan = SearchPlanner(RegionRegistry.from_file()).plan(RegionMode.SELECTED)
    items_by_intent: dict[str, list[dict[str, Any]]] = {}
    for item in manifest["items"]:
        items_by_intent.setdefault(item["discovery_intent"], []).append(item)
    target_query: dict[str, list[dict[str, Any]]] = {}
    for intent, items in items_by_intent.items():
        first = next(p for p in plan.items if p.intent.value == intent)
        target_query[rss_module.GoogleNewsRssProvider.request_url(first)] = items
    served: list[str] = []

    def transport(url: str, timeout_seconds: float) -> rss_module.RssTransportResponse:
        if not url.startswith(rss_module.GOOGLE_NEWS_RSS_ENDPOINT):
            raise HarnessAbort("REPLAY_TRANSPORT_UNEXPECTED_URL")
        rows = target_query.get(url, [])
        entries = "".join(
            "<item>"
            f"<title>{escape(row['title'])}</title>"
            f"<link>{escape(row['url'])}</link>"
            f"<source>{escape(row['publisher'])}</source>"
            f"<pubDate>{_rfc822(row['observed_date'])}</pubDate>"
            "</item>"
            for row in rows
        )
        served.extend(row["slot"] for row in rows)
        body = f'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>replay</title>{entries}</channel></rss>'
        return rss_module.RssTransportResponse(body=body.encode("utf-8"), status_code=200, final_url=url)

    return transport, served, len(plan.items)


def to_jsonable(value: Any, depth: int = 0) -> Any:
    if depth > 12:
        return repr(value)[:200]
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_jsonable(getattr(value, f.name), depth + 1) for f in dataclasses.fields(value)}
    if isinstance(value, dict) or hasattr(value, "items") and callable(value.items):
        return {str(k): to_jsonable(v, depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_jsonable(v, depth + 1) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)[:500]


def load_environ(dry_run: bool) -> dict[str, str]:
    values: dict[str, str] = {}
    if not dry_run:
        from dotenv import dotenv_values

        env = dotenv_values(REPO / ".env")
        for key in (*SHARED_MAIAGENT_CONFIG_KEYS, "MAIAGENT_CHATBOT_ID"):
            if env.get(key):
                values[key] = str(env[key])
    else:
        values.update(
            MAIAGENT_API_BASE="https://maiagent.invalid",
            MAIAGENT_API_KEY="dry-run",
            MAIAGENT_STRUCTURED_HELPER_CHATBOT_ID="dry-run-helper",
            MAIAGENT_CHATBOT_ID="dry-run-writer",
        )
    # Explicit delivery keys stop .env lookup: no recipient, no live email.
    values.update(LIVE_EMAIL_SEND="0", DEFAULT_RECIPIENTS="", GMAIL_USER="", GMAIL_APP_PASS="")
    return values


def fake_fetcher(url: str, timeout_seconds: float) -> FetchedSource:
    html = (
        "<html><head><title>Dry run</title>"
        '<meta property="article:published_time" content="2026-10-14T08:00:00Z"></head>'
        "<body><article><h1>Dry run article</h1>"
        "<p>The metro operator awarded a contract for new signalling equipment on Line 1.</p>"
        "<p>The contract covers design, supply and commissioning over four years.</p>"
        "</article></body></html>"
    )
    return FetchedSource(url=url, content=html, status_code=200, content_type="text/html", redirect_chain=(url,))


def fake_maiagent(endpoint, *, headers, body, timeout_seconds) -> MaiAgentHttpResponse:
    return MaiAgentHttpResponse(503, b"")


class ReplayFetcher:
    """Serve archived HTML from a previous live run (no network)."""

    def __init__(self, run_summary: dict[str, Any], raw_dir: Path, slot_by_url: dict[str, str]) -> None:
        self._requests = {r["slot"]: r for r in run_summary["evidence_requests"]}
        self._raw_dir, self._slot_by_url = raw_dir, slot_by_url

    def __call__(self, url: str, timeout_seconds: float) -> FetchedSource:
        record = self._requests[self._slot_by_url[url]]
        if not record["outcome"].startswith("HTTP_"):
            if record.get("status_code"):
                raise evidence_module._EvidenceFetchError(record["status_code"], request_url=url, failing_url=url)
            raise OSError("replayed transport failure")
        content = (self._raw_dir / f"{record['slot']}.html").read_text(encoding="utf-8")
        return FetchedSource(
            url=record["final_url"], content=content, status_code=200,
            content_type=record["content_type"], redirect_chain=tuple(record["redirect_chain"]),
        )


class ReplayMaiAgent:
    """Serve recorded MaiAgent responses in the recorded call order (no network)."""

    def __init__(self, run_summary: dict[str, Any], body_dir: Path) -> None:
        self._calls = run_summary["maiagent_calls"]
        self._body_dir = body_dir
        self._next = 0

    def __call__(self, endpoint, *, headers, body, timeout_seconds) -> MaiAgentHttpResponse:
        call = self._calls[self._next]
        self._next += 1
        if call["outcome"] == "TIMEOUT":
            raise TimeoutError
        status = int(call["outcome"].removeprefix("HTTP_"))
        path = self._body_dir / f"{call['index']:03d}_{call['task']}_response.json"
        return MaiAgentHttpResponse(status, path.read_bytes())


STAGE_RECORDS: list[dict[str, Any]] = []


def record_owner_outputs() -> None:
    """Wrap owner entry points to keep their typed outputs (observation only)."""

    from weekly_report.scope_classifier import ScopeClassifier
    from weekly_report.temporal_rule import TemporalRule

    for cls, name, stage in ((EvidenceServiceCls, "evaluate", "Evidence"), (ScopeClassifier, "classify", "Scope"), (TemporalRule, "evaluate", "Temporal")):
        original = getattr(cls, name)

        def wrapper(self, *a, __original=original, __stage=stage, **k):
            if __stage == "Scope" and "observation_hook" not in k:
                k["observation_hook"] = lambda obs: STAGE_RECORDS.append(
                    {"stage": "ScopeObservation", "output": to_jsonable(obs)}
                )
            output = __original(self, *a, **k)
            STAGE_RECORDS.append({"stage": __stage, "output": to_jsonable(output)})
            return output

        setattr(cls, name, wrapper)


EvidenceServiceCls = evidence_module.EvidenceService


def block_network() -> None:
    def refuse(*args, **kwargs):
        raise HarnessAbort("DRY_RUN_NETWORK_ATTEMPT")

    socket.create_connection = refuse  # type: ignore[assignment]
    socket.socket.connect = refuse  # type: ignore[assignment]
    socket.getaddrinfo = refuse  # type: ignore[assignment]


def slot_outcomes(result: Any, slot_by_candidate: dict[str, str]) -> dict[str, dict[str, Any]]:
    """Observation-only per-sample projection of the owners' typed results."""

    outcomes: dict[str, dict[str, Any]] = {}

    def entry(candidate_id: str) -> dict[str, Any]:
        return outcomes.setdefault(slot_by_candidate.get(candidate_id, candidate_id), {})

    for evidence in result.evidence_results or ():
        item = entry(evidence.candidate_id)
        provenance = evidence.provenance
        facts = evidence.identity_facts
        resolution = facts.region_resolution if facts is not None else None
        item.update(
            evidence=evidence.state.value,
            gate=provenance.get("evidence_rejection_gate"),
            judge=provenance.get("response_validation_result"),
            metadata=provenance.get("metadata_extraction_status"),
            region=None if resolution is None else [resolution.basis.value, resolution.display_name, resolution.diagnostic],
            system_name=None if facts is None else facts.transit_system_name,
        )
    for scope in result.scope_results or ():
        entry(scope.candidate_id).update(scope=scope.state.value, scope_detail=dict(scope.provenance).get("proposal") or dict(scope.provenance).get("helper_error") or scope.diagnostic.value)
    for temporal in result.temporal_results or ():
        entry(temporal.candidate_id).update(date_valid=temporal.date_valid, date=None if temporal.controlling_calendar_date is None else temporal.controlling_calendar_date.isoformat())
    event_slots: dict[str, list[str]] = {}
    if result.event_identity_run is not None:
        for group in result.event_identity_run.groups:
            event_slots[group.event_id] = [slot_by_candidate.get(c, c) for c in group.member_candidate_ids]
            for candidate_id in group.member_candidate_ids:
                entry(candidate_id)["event_id"] = group.event_id
    for category in result.category_results or ():
        for slot in event_slots.get(category.event_id, ()):
            outcomes[slot].update(category=category.category_state.value, primary_category=category.primary_category)
    for downstream in result.downstream_results or ():
        for slot in event_slots.get(downstream.event_group.event_id, ()):
            outcomes[slot].update(
                taxonomy=[system.display_label for system in downstream.taxonomy_result.systems],
                taxonomy_state=downstream.taxonomy_result.taxonomy_state.value,
                reportability=str(getattr(downstream.reportability_state, "value", downstream.reportability_state)),
            )
    for metadata in result.formal_metadata or ():
        for slot in event_slots.get(metadata.event_id, ()):
            outcomes[slot].update(country=[metadata.country, metadata.country_basis.value], transit_system=[metadata.transit_system_name, metadata.transit_system_basis.value])
    if result.validation_result is not None:
        for item in result.validation_result.passed:
            for slot in event_slots.get(item.event_id, ()):
                outcomes[slot].update(validation="PASS")
        for item in result.validation_result.failed:
            for slot in event_slots.get(item.event_id, ()):
                outcomes[slot].update(validation="FAIL", validation_reasons=list(item.reasons))
    for gap in result.technical_gaps:
        for slot in event_slots.get(gap.subject_id, [slot_by_candidate.get(gap.subject_id, gap.subject_id)]):
            outcomes.setdefault(slot, {}).update(technical_gap=[gap.stage, gap.kind.value, gap.failure_class, gap.attempts])
    return dict(sorted(outcomes.items()))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default=str(REPO / "acceptance/phase_a/manifest.json"))
    parser.add_argument("--out", required=True)
    parser.add_argument("--scratch", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--replay-from", help="summary.json of a live run; replays its HTML and MaiAgent responses offline")
    parser.add_argument("--replay-scratch", help="scratch dir of the replayed live run")
    parser.add_argument(
        "--live-maiagent",
        action="store_true",
        help="with --replay-from: replay only the archived HTML (no Evidence HTTP) and call MaiAgent live",
    )
    parser.add_argument("--http-budget", type=int, default=80)
    parser.add_argument("--maiagent-budget", type=int, default=160)
    parser.add_argument("--seconds", type=int, default=45 * 60)
    args = parser.parse_args()

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    out, scratch = Path(args.out), Path(args.scratch)
    for path in (out, scratch / "raw", scratch / "maiagent"):
        path.mkdir(parents=True, exist_ok=True)

    budget = Budget(args.http_budget, args.maiagent_budget, args.seconds)
    slot_by_url = {item["url"]: item["slot"] for item in manifest["items"]}

    replay_summary = None
    if args.replay_from:
        replay_summary = json.loads(Path(args.replay_from).read_text(encoding="utf-8"))
        if not args.live_maiagent:
            args.dry_run = True
            record_owner_outputs()
    if args.dry_run:
        block_network()
    # Search must never reach the network in this harness.
    def forbidden_rss(*a, **k):
        raise HarnessAbort("LIVE_SEARCH_ATTEMPT")

    rss_module._default_transport = forbidden_rss  # type: ignore[assignment]
    if replay_summary is not None:
        source = Path(args.replay_scratch)
        real_fetch = ReplayFetcher(replay_summary, source / "raw", slot_by_url)
        inner_maiagent = (
            UrllibMaiAgentJsonTransport() if args.live_maiagent else ReplayMaiAgent(replay_summary, source / "maiagent")
        )
    else:
        real_fetch = fake_fetcher if args.dry_run else evidence_module._default_fetcher
        inner_maiagent = fake_maiagent if args.dry_run else UrllibMaiAgentJsonTransport()
    fetcher = RecordingFetcher(real_fetch, budget, scratch / "raw", slot_by_url)
    evidence_module._default_fetcher = fetcher  # type: ignore[assignment]
    maiagent = CountingMaiAgentTransport(inner_maiagent, budget, scratch / "maiagent")
    replay, served, plan_items = build_replay_transport(manifest)

    trace_records: list[dict[str, Any]] = []
    trace = ExecutionTrace(sink=lambda line: trace_records.append(json.loads(line)), environ={})
    runner = ProductionRunner.from_environment(
        environ=load_environ(args.dry_run), transport=maiagent, rss_transport=replay
    )
    application = runner.application
    captured: dict[str, Any] = {}

    class Capture:
        def run(self, *a, **k):
            captured["result"] = application.run(*a, **k)
            return captured["result"]

    runner._application = Capture()  # harness-only proxy; production code unchanged

    watchdog = threading.Timer(args.seconds + 30, _thread.interrupt_main)
    watchdog.daemon = True
    watchdog.start()
    run_result = None
    abort = None
    started_wall = dt.datetime.now(dt.timezone.utc)
    try:
        with execution_trace(trace):
            run_result = runner.run(
                region_mode="selected",
                period_start=manifest["period_start"],
                period_end=manifest["period_end"],
            )
    except HarnessAbort as exc:
        abort = str(exc)
    except KeyboardInterrupt:
        abort = "WATCHDOG_WALL_CLOCK"
    finally:
        watchdog.cancel()
    elapsed = round(budget.elapsed(), 1)

    result = captured.get("result")
    # candidate-id-v1 recomputed from the frozen URL (mapping only; no decision).
    slot_by_candidate = {
        "cand_" + hashlib.sha256(
            json.dumps({"version": "candidate-id-v1", "url": url}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(): slot
        for url, slot in slot_by_url.items()
    }

    stage_ms: dict[str, int] = {}
    for record in trace_records:
        if record.get("event") in {"STAGE_COMPLETED", "STAGE_FAILED"}:
            stage_ms[record["stage"]] = record.get("elapsed_ms")

    summary = {
        "run_started_utc": started_wall.isoformat(),
        "git_head": os.popen(f'git -C "{REPO}" rev-parse HEAD').read().strip(),
        "dry_run": args.dry_run,
        "period": [manifest["period_start"], manifest["period_end"]],
        "abort": abort,
        "wall_clock_seconds": elapsed,
        "budgets": {
            "evidence_http": [budget.http_used, budget.http_limit],
            "maiagent_calls": [budget.maiagent_used, budget.maiagent_limit],
            "seconds": budget.seconds,
        },
        "search": {"plan_items_replayed_offline": plan_items, "manifest_rows_served": served},
        "run_status": None if run_result is None else to_jsonable(run_result.status),
        "run_failure": None if run_result is None else {
            "stage": run_result.failure_stage,
            "class": run_result.failure_class,
            "diagnostic": run_result.diagnostic,
        },
        "replayed_owner_outputs": STAGE_RECORDS,
        "stage_counts": None if run_result is None else to_jsonable(run_result.stage_counts),
        "stage_elapsed_ms": stage_ms,
        "maiagent_calls_by_task": dict(Counter(call["task"] for call in maiagent.calls)),
        "maiagent_outcomes": dict(Counter(call["outcome"] for call in maiagent.calls)),
        "maiagent_calls": maiagent.calls,
        "evidence_requests": fetcher.requests,
        "slot_by_candidate": slot_by_candidate,
        "final_report_event_count": None
        if run_result is None or run_result.final_report is None
        else run_result.final_report.event_count,
    }
    if result is not None:
        summary["slot_outcomes"] = slot_outcomes(result, slot_by_candidate)
        summary["technical_gaps"] = [to_jsonable(gap) for gap in result.technical_gaps]
        summary["metadata_exclusions"] = [to_jsonable(item) for item in result.metadata_exclusions]
        if result.final_report is not None:
            summary["disclosure"] = to_jsonable(result.final_report.disclosure)
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "trace.jsonl").write_text("\n".join(json.dumps(r) for r in trace_records), encoding="utf-8")
    if run_result is not None and run_result.final_report is not None:
        (out / "final_report.md").write_text(run_result.final_report.content, encoding="utf-8")
    if result is not None:
        # Full result (includes source text) stays in the local scratch area.
        (scratch / "application_result.json").write_text(
            json.dumps(to_jsonable(result), ensure_ascii=False, indent=1), encoding="utf-8"
        )
    print(json.dumps({k: summary[k] for k in ("abort", "wall_clock_seconds", "budgets", "run_status", "stage_counts", "maiagent_calls_by_task", "final_report_event_count")}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
