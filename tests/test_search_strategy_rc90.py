"""RC-90 (contract section A.71; user decision 2026-11-27, strategy delegated to Claude).

1. Search plan v15 as amended: technology in the full 155-character packing of
   RC-88, procurement the same, the major-incident lane in the compact 30-word
   packing, operations planned by no query family (599 weekly requests).
2. Evidence and Scope run with three workers (user decision 2026-11-27); results are taken in the
   candidates' original order, so the output equals the serial run. Google News
   link resolution stays serial and paced.
3. The recall-only technology test mode plans technology and the trade press only.
4. The concise run digest is an observer-only projection printed last.
"""

from __future__ import annotations

from datetime import date
import random
import threading
import time
from types import SimpleNamespace

import pytest

from src.weekly_report.contracts import (
    DiscoveryIntent,
    EvidenceAcquisitionTechnicalFailure,
    ScopeResult,
    ScopeState,
    SearchProviderId,
    SearchWindow,
    SemanticProviderTechnicalFailure,
)
from src.weekly_report.google_news_links import LINK_RESOLUTION_MIN_INTERVAL_SECONDS, GoogleNewsLinkResolver
from src.weekly_report.production_runner import HEALTH_PROBE_ORDINALS
from src.weekly_report.region_registry import RegionRegistry
from src.weekly_report.report_application import CANDIDATE_STAGE_WORKERS, _in_candidate_order
from src.weekly_report.search_executor import SearchExecutor
from src.weekly_report.search_planner import _MAX_QUERY_CHARACTERS, _MAX_QUERY_WORDS, SearchPlanner, _query_words
from tests.test_link_resolution_gate_rc83 import LinkProvider
from tests.test_report_application import (
    FixturePlanner,
    FixtureReportApplication,
    FormalEvidenceService,
    RecordingClassifier,
    RecordingDownstreamWorkflow,
    RecordingEventIdentity,
    RecordingEvidenceService,
    RecordingOrdering,
    RecordingReportService,
    RecordingScopeClassifier,
    RecordingTemporalRule,
    _fixture_plan,
)

REGISTRY = RegionRegistry.from_file()
WEEK = SearchWindow(date(2026, 11, 16), date(2026, 11, 22))
PLAN = SearchPlanner(REGISTRY).plan("selected", window=WEEK)


# --- 1. Search plan v15 ----------------------------------------------------------------------


def _counts(plan):
    counts: dict[tuple[str, str], int] = {}
    for item in plan.items:
        key = (item.intent.value, item.query_family_id)
        counts[key] = counts.get(key, 0) + 1
    return counts


def test_the_weekly_plan_per_intent_and_family():
    assert _counts(PLAN) == {
        ("technology", "urban_rail_or_groups"): 462,
        ("technology", "rail_trade_press"): 2,
        ("procurement", "urban_rail_or_groups"): 75,
        ("major_incident", "urban_rail_or_groups_compact"): 60,
    }
    assert len(PLAN.items) == 599
    assert HEALTH_PROBE_ORDINALS == (1, 10, 299, 304, 592, 599)


def test_operations_is_planned_by_no_family_but_keeps_its_vocabulary():
    # User decision 2026-11-27: operations yielded no report item in recall
    # Runs 45641734970 and 45764691167; Operations Category events arrive
    # through the other intents. Search intent is not Category (section 5).
    assert REGISTRY.planned_intents == (
        DiscoveryIntent.TECHNOLOGY, DiscoveryIntent.MAJOR_INCIDENT, DiscoveryIntent.PROCUREMENT,
        DiscoveryIntent.MONITORED_STANDARDS,
    )
    assert not any(DiscoveryIntent.OPERATIONS.value in family.intents for family in REGISTRY.query_families)
    assert all(profile.intent_vocabulary["operations"] for profile in REGISTRY.profiles)
    with pytest.raises(ValueError, match="not planned"):
        SearchPlanner(REGISTRY).plan("selected", intents=(DiscoveryIntent.OPERATIONS,), window=WEEK)


def test_technology_and_procurement_keep_the_full_character_packing():
    full = [item for item in PLAN.items if item.intent.value in {"technology", "procurement"}]
    assert full and all(len(item.query) <= _MAX_QUERY_CHARACTERS == 155 for item in full)
    families = {family.family_id: family for family in REGISTRY.query_families}
    assert families["urban_rail_or_groups"].query_packing == "characters"
    assert families["urban_rail_or_groups"].intents == ("technology", "procurement")


def test_the_major_incident_lane_uses_the_compact_word_packing():
    family = next(f for f in REGISTRY.query_families if f.family_id == "urban_rail_or_groups_compact")
    assert family.query_packing == "words" and family.intents == ("major_incident",)
    incident = [item for item in PLAN.items if item.intent is DiscoveryIntent.MAJOR_INCIDENT]
    assert incident and all(_query_words(item.query) <= _MAX_QUERY_WORDS == 30 for item in incident)
    for item in incident:
        # The mode group is sent whole and first; the date operators still lead the request.
        profile = REGISTRY.profile(item.language_profile)
        modes = profile.intent_vocabulary["major_incident"]["urban_rail_terms"]
        head = item.query.split(") (", 1)[0]
        assert all(mode in head for mode in modes), item.query
    # The same governed vocabulary groups as the character-packed family.
    full = next(f for f in REGISTRY.query_families if f.family_id == "urban_rail_or_groups")
    assert dict(family.vocabulary_groups) == dict(full.vocabulary_groups)


def test_the_compact_packing_is_rejected_for_an_unknown_value():
    source = REGISTRY.as_mapping()
    source["query_families"][1]["query_packing"] = "truncate"
    with pytest.raises(ValueError, match="query_packing"):
        RegionRegistry.from_mapping(source)


def test_the_registry_round_trips_the_packing():
    again = RegionRegistry.from_mapping(REGISTRY.as_mapping())
    assert SearchPlanner(again).plan("selected", window=WEEK) == PLAN


# --- 3. Technology test mode -----------------------------------------------------------------


def test_the_technology_test_mode_plans_technology_and_the_trade_press_only():
    plan = SearchPlanner(REGISTRY).plan("selected", intents=(DiscoveryIntent.TECHNOLOGY,), window=WEEK)
    assert _counts(plan) == {
        ("technology", "urban_rail_or_groups"): 462,
        ("technology", "rail_trade_press"): 2,
    }


def test_main_refuses_the_test_mode_with_live_email(monkeypatch, capsys):
    import main

    monkeypatch.setenv("LIVE_EMAIL_SEND", "1")
    called = []
    monkeypatch.setattr(main, "ProductionRunner", SimpleNamespace(from_environment=lambda: called.append(1)))
    assert main.main(["--technology-test-mode"]) == 1
    assert not called
    assert "TechnologyTestModeWithLiveEmail" in capsys.readouterr().out


def test_main_passes_only_the_technology_intent_in_the_test_mode(monkeypatch, tmp_path):
    import main

    monkeypatch.setenv("LIVE_EMAIL_SEND", "0")
    seen = []

    class FakeRunner:
        @classmethod
        def from_environment(cls):
            return cls()

        def run(self, **kwargs):
            seen.append(kwargs)
            return SimpleNamespace(successful=False, complete=False, final_report=None, summary=lambda: "status=X")

    monkeypatch.setattr(main, "ProductionRunner", FakeRunner)
    main.main(["--technology-test-mode", "--output-dir", str(tmp_path)])
    main.main(["--output-dir", str(tmp_path)])
    assert seen[0]["search_intents"] == (DiscoveryIntent.TECHNOLOGY,)
    assert "search_intents" not in seen[1]


# --- 2. Bounded parallel Evidence and Scope ----------------------------------------------------


def test_three_workers_by_default():
    # User decision 2026-11-27: three workers (back to two if MaiAgent rate
    # limiting or site blocking clearly increases).
    assert CANDIDATE_STAGE_WORKERS == 3


@pytest.mark.parametrize("workers", [1, 2, 3])
def test_outcomes_come_back_in_input_order_with_bounded_concurrency(workers):
    active, peak, lock = [0], [0], threading.Lock()
    rng = random.Random(workers)
    delays = [rng.uniform(0, 0.004) for _ in range(40)]

    def work(index):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(delays[index])
        with lock:
            active[0] -= 1
        if index % 9 == 4:
            raise SemanticProviderTechnicalFailure("TIMEOUT", attempts=2, transient=True)
        return index * 10

    with _in_candidate_order(work, list(range(40)), workers) as outcomes:
        values = []
        for index, outcome in outcomes:
            try:
                values.append((index, outcome()))
            except SemanticProviderTechnicalFailure:
                values.append((index, "gap"))
    assert values == [(i, "gap" if i % 9 == 4 else i * 10) for i in range(40)]
    assert peak[0] <= workers


def test_an_unexpected_failure_stops_the_stage_at_the_same_candidate():
    def work(index):
        if index == 5:
            raise RuntimeError("boom")
        return index

    for workers in (1, 2):
        taken = []
        with pytest.raises(RuntimeError, match="boom"):
            with _in_candidate_order(work, list(range(20)), workers) as outcomes:
                for index, outcome in outcomes:
                    taken.append(outcome())
        assert taken == [0, 1, 2, 3, 4]


class _SlowEvidence(RecordingEvidenceService):
    """Deterministic outcomes by candidate title, random delays, concurrency tracked."""

    def __init__(self) -> None:
        super().__init__()
        self.lock, self.active, self.peak = threading.Lock(), 0, 0

    def evaluate(self, candidate):
        index = int(candidate.title.split()[1])
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            time.sleep(random.Random(index).uniform(0, 0.003))
            if index % 13 == 3:
                raise EvidenceAcquisitionTechnicalFailure("LINK_RESOLUTION_BATCHEXECUTE_HTTP_429", attempts=2)
            if index % 7 == 2:
                raise SemanticProviderTechnicalFailure("TIMEOUT", attempts=2, transient=True)
            if index % 5 == 1:
                self.rejected_ids = {candidate.candidate_id}
                return RecordingEvidenceService.evaluate(self, candidate)
            return FormalEvidenceService.evaluate(self, candidate)
        finally:
            with self.lock:
                self.active -= 1


class _SlowScope(RecordingScopeClassifier):
    def __init__(self, out_of_scope_titles) -> None:
        super().__init__()
        self.out_of_scope_titles = out_of_scope_titles
        self.lock, self.active, self.peak = threading.Lock(), 0, 0

    def classify(self, evidence, *, candidate_title="", monitored_check=None):
        index = int(candidate_title.split()[1])
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            time.sleep(random.Random(1000 + index).uniform(0, 0.003))
            if index % 11 == 6:
                raise SemanticProviderTechnicalFailure("SCHEMA", attempts=1, transient=False)
            state = ScopeState.OUT_OF_SCOPE if index % 4 == 0 else ScopeState.IN_SCOPE
            return ScopeResult(evidence.candidate_id, state)
        finally:
            with self.lock:
                self.active -= 1


def _run(workers):
    from src.weekly_report.region_registry import RegionRegistry as Registry

    registry = Registry.from_file()
    evidence, scope = _SlowEvidence(), _SlowScope(set())
    app = FixtureReportApplication(
        registry,
        FixturePlanner(registry, _fixture_plan()),
        SearchExecutor({SearchProviderId.GOOGLE_NEWS_RSS: LinkProvider(48)}),
        None,
        evidence,
        scope_classifier=scope,
        temporal_rule=RecordingTemporalRule(default_date=date(2026, 9, 18)),
        event_identity=RecordingEventIdentity(),
        classifier=RecordingClassifier(),
        report_workflow=RecordingDownstreamWorkflow(reportable=True),
        ordering=RecordingOrdering(),
        report_service=RecordingReportService(),
        sleep=lambda seconds: None,
        candidate_stage_workers=workers,
    )
    return app.run("selected"), evidence, scope


@pytest.mark.parametrize("workers", [2, CANDIDATE_STAGE_WORKERS])
def test_parallel_and_serial_runs_produce_the_same_result(workers):
    serial, serial_evidence, _ = _run(1)
    parallel, parallel_evidence, parallel_scope = _run(workers)
    assert len(serial.evidence_results) > 20 and serial.scope_results and serial.technical_gaps
    for field in (
        "evidence_results", "technical_gaps", "scope_results", "temporal_results", "event_identity_records",
        "category_results", "downstream_results", "ordered_results", "formal_metadata", "final_report",
        "scope_rejected_proposals", "scope_corrections", "link_resolution_gate",
    ):
        assert getattr(parallel, field) == getattr(serial, field), field
    # The gaps keep the candidates' original order and their stages.
    assert [gap.stage for gap in parallel.technical_gaps] == [gap.stage for gap in serial.technical_gaps]
    assert serial_evidence.peak == 1 and parallel_evidence.peak <= workers and parallel_scope.peak <= workers


def test_the_parallel_run_is_deterministic():
    first, _, _ = _run(CANDIDATE_STAGE_WORKERS)
    for _ in range(3):
        again, _, _ = _run(CANDIDATE_STAGE_WORKERS)
        assert again.evidence_results == first.evidence_results
        assert again.technical_gaps == first.technical_gaps
        assert again.scope_results == first.scope_results


def test_the_worker_count_must_be_positive():
    for bad in (0, -1, True, 1.5):
        with pytest.raises(ValueError, match="candidate_stage_workers"):
            FixtureReportApplication(
                REGISTRY, FixturePlanner(REGISTRY, _fixture_plan()),
                SearchExecutor({SearchProviderId.GOOGLE_NEWS_RSS: LinkProvider(1)}), None, FormalEvidenceService(),
                candidate_stage_workers=bad,
            )


# --- 2. Google News link resolution stays serial and paced ------------------------------------

_LINK = "https://news.google.com/rss/articles/CBMiAU_yqLexample?oc=5"
_PAGE = '<div jscontroller="x" data-n-a-sg="SIG" data-n-a-ts="1700000000">'


def _batch(url):
    import json

    return ")]}'\n\n" + json.dumps([["wrb.fr", "Fbv4je", json.dumps(["garturlres", url, 1]), None, None, None, "g"]])


def test_link_resolutions_never_overlap_across_workers():
    lock, active, peak = threading.Lock(), [0], [0]

    def transport(method, url, headers, body, timeout):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.002)
        with lock:
            active[0] -= 1
        return (200, _PAGE) if method == "GET" else (200, _batch("https://publisher.example/a"))

    resolver = GoogleNewsLinkResolver(transport, min_interval_seconds=0)
    with _in_candidate_order(lambda _: resolver.resolve(_LINK), list(range(12)), 3) as outcomes:
        results = [outcome() for _, outcome in outcomes]
    assert all(result.publisher_url == "https://publisher.example/a" for result in results)
    assert peak[0] == 1


def test_link_resolutions_are_paced_by_the_minimum_interval():
    now, waits = [100.0], []

    def sleep(seconds):
        waits.append(round(seconds, 6))
        now[0] += seconds

    def transport(method, url, headers, body, timeout):
        now[0] += 0.25  # each request takes a quarter second
        return (200, _PAGE) if method == "GET" else (200, _batch("https://publisher.example/a"))

    resolver = GoogleNewsLinkResolver(transport, sleep=sleep, clock=lambda: now[0])
    for _ in range(3):
        resolver.resolve(_LINK)
    assert LINK_RESOLUTION_MIN_INTERVAL_SECONDS == 2.0
    # Each resolution takes 0.5 s, so the next one waits the remaining 1.5 s.
    assert waits == [1.5, 1.5]


def test_offline_legacy_ids_are_not_paced():
    import base64

    publisher = "https://www.example.com/a/very/long/article/path/0001"
    raw = b"\x08\x13\x22" + bytes([len(publisher)]) + publisher.encode() + b"\xd2\x01\x00"
    article_id = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    waits = []
    resolver = GoogleNewsLinkResolver(lambda *args: (500, ""), sleep=waits.append)
    for _ in range(3):
        assert resolver.resolve(f"https://news.google.com/rss/articles/{article_id}").method == "LEGACY_ID_DECODE"
    assert waits == []


# --- 4. Concise run digest --------------------------------------------------------------------


def _digest_result():
    from src.weekly_report.production_runner import ProductionRunStatus

    block = lambda title: SimpleNamespace(headline=title)  # noqa: E731
    sections = (
        SimpleNamespace(category="技術新知", events=(block("新號誌試驗"), block("車載軌道檢測"))),
        SimpleNamespace(category="事故及安全事件", events=(block("出軌"),)),
    )
    report = SimpleNamespace(sections=sections, events=tuple(e for s in sections for e in s.events))
    return SimpleNamespace(
        status=ProductionRunStatus.SUCCESS_WITH_TECHNICAL_GAPS,
        period_start=date(2026, 11, 16), period_end=date(2026, 11, 22),
        final_report=report, search_rate_limit_retries=11,
        search_failure_class_distribution={"RATE_LIMIT": 2},
        stage_counts={"search_plan": 599, "evidence_results": 1200, "technical_gaps": 30,
                      "technical_gaps_evidence": 12, "technical_gaps_scope": 18, "validation_failed": 2},
        search_failure_count=3,
        evidence_http_status_distribution={"403": 39, "404": 1, "429": 2},
        technical_gap_signature_distribution={
            "Evidence:SUBJECT:TRANSIENT_FAILURE_AFTER_RETRY:LINK_RESOLUTION_ARTICLE_PAGE_HTTP_429": 10,
            "Scope:SUBJECT:PROPOSAL_CONTRACT_VIOLATION:ENDPOINT_LABEL": 8,
        },
    )


def test_the_digest_lists_sections_titles_stage_times_and_rate_limits():
    from src.weekly_report.run_digest import DIGEST_BEGIN, DIGEST_END, build_run_digest

    text = build_run_digest(
        _digest_result(), stage_elapsed_ms={"Search": 1_380_000, "Evidence": 3_600_000}, total_elapsed_ms=8_400_000,
        maiagent_attempts={"Evidence": {"OK": 900, "HTTP_429": 3, "TIMEOUT": 1}, "Scope": {"OK": 500}},
    )
    lines = text.splitlines()
    assert lines[0] == DIGEST_BEGIN and lines[-1] == DIGEST_END
    assert "status=SUCCESS_WITH_TECHNICAL_GAPS period=2026-11-16..2026-11-22 mode=FORMAL" in lines
    assert ("report_items=3 | 技術新知=2 事故及安全事件=1 營運動態=0 機電標案及採購動態=0 規範及標準動態=0") in lines
    assert "  1. 新號誌試驗" in lines and "  2. 車載軌道檢測" in lines
    assert "stage_minutes: Search=23.0 Evidence=60.0 total=140.0" in lines
    assert "search_429: retried=11 failed_after_retry=2" in lines
    assert "maiagent: attempts=1404 ok=1400 failed=HTTP_429=3,TIMEOUT=1 by_stage=Evidence=904,Scope=500" in lines
    assert "stage_errors: evidence=12,scope=18,search_failures=3,validation_failed=2" in lines
    assert "site_blocking: evidence_http_403=39 evidence_http_429=2 link_resolution_429_gaps=10" in lines
    assert len(lines) <= 16


def test_the_trace_records_stage_durations_for_the_digest():
    from src.weekly_report.debug_service import ExecutionTrace, execution_trace, observe_stage

    clock = [0.0]
    trace = ExecutionTrace(sink=lambda line: None, clock=lambda: clock[0])
    with execution_trace(trace):
        with observe_stage("Search", 1) as observation:
            clock[0] += 90
            observation.observe((), final=True)
        with observe_stage("Evidence", 1) as observation:
            clock[0] += 30
            observation.observe((), final=True)
    assert trace.stage_elapsed_ms() == {"Search": 90_000, "Evidence": 30_000}
    assert trace.elapsed_ms() == 120_000


def test_the_printer_appends_the_v4_score_inside_the_digest(tmp_path):
    import json

    from scripts.print_run_digest import digest_text
    from src.weekly_report.run_digest import DIGEST_END, build_run_digest

    (tmp_path / "run_digest.txt").write_text(
        build_run_digest(_digest_result(), stage_elapsed_ms={}, total_elapsed_ms=0), encoding="utf-8"
    )
    audit = {"period": {"start": "2026-11-16", "end": "2026-11-22"}, "candidates": [], "events": []}
    (tmp_path / "selection_audit.json").write_text(json.dumps(audit), encoding="utf-8")
    text = digest_text(tmp_path, "acceptance/gold/recall_v1.json")
    lines = text.splitlines()
    assert lines[-1] == DIGEST_END
    score = next(line for line in lines if line.startswith("recall_v4: "))
    assert score.startswith("recall_v4: accuracy=") and "/25 " in score
    assert digest_text(tmp_path / "missing").splitlines()[1].startswith("run_digest=UNAVAILABLE")


def test_maiagent_attempts_are_counted_by_stage_and_outcome():
    from src.weekly_report.debug_service import ExecutionTrace, execution_trace, observe_stage
    from src.weekly_report.maiagent_transport import MaiAgentHttpResponse, request_maiagent_proposal

    replies = iter([MaiAgentHttpResponse(429, b""), MaiAgentHttpResponse(200, b'{"content": "{\\"ok\\": 1}"}')])
    trace = ExecutionTrace(sink=lambda line: None)
    with execution_trace(trace):
        with observe_stage("Scope", 1):
            request_maiagent_proposal(lambda *a, **k: next(replies), "https://maiagent.example/x",
                                      headers={}, body=b"{}", timeout_seconds=1)
        # Outside any stage, and never raising when no trace is active.
        with pytest.raises(Exception):
            request_maiagent_proposal(lambda *a, **k: MaiAgentHttpResponse(400, b""), "https://maiagent.example/x",
                                      headers={}, body=b"{}", timeout_seconds=1)
    assert trace.maiagent_attempts() == {"Scope": {"HTTP_429": 1, "OK": 1}, "Other": {"HTTP_400": 1}}
    request_maiagent_proposal(lambda *a, **k: MaiAgentHttpResponse(200, b'{"content": "{\\"ok\\": 1}"}'),
                              "https://maiagent.example/x", headers={}, body=b"{}", timeout_seconds=1)


def test_maiagent_attempts_from_parallel_workers_are_all_counted():
    from src.weekly_report.debug_service import ExecutionTrace, execution_trace, observe_maiagent_attempt, observe_stage

    trace = ExecutionTrace(sink=lambda line: None)
    with execution_trace(trace), observe_stage("Evidence", 300):
        with _in_candidate_order(lambda _: observe_maiagent_attempt("OK"), list(range(300)), 3) as outcomes:
            for _, outcome in outcomes:
                outcome()
    assert trace.maiagent_attempts() == {"Evidence": {"OK": 300}}
