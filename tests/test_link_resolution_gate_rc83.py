"""RC-83 (contract section A.64): run-level Google News link-resolution gate.

When at least 20 links and at least 30% of the run's Google News links are left
as transient link-resolution TechnicalGaps, the application waits once (45
minutes) and retries only those links. Still over the gate after the retry, the
run stops after Evidence as a TECHNICAL_FAILURE: no report, nothing delivered.
"""

from __future__ import annotations

from datetime import date
import threading
from unittest import TestCase

from src.weekly_report.contracts import (
    DiscoveryResult,
    EvidenceAcquisitionTechnicalFailure,
    EvidenceResult,
    EvidenceState,
    SearchAttemptResult,
    SearchProviderId,
    SearchTerminalStatus,
    SemanticProviderTechnicalFailure,
)
from src.weekly_report.evidence_service import EvidenceService
from src.weekly_report.production_runner import ProductionRunner, ProductionRunStatus
from src.weekly_report.report_application import (
    LINK_RESOLUTION_GATE_MIN_FAILED,
    LINK_RESOLUTION_GATE_MIN_RATIO,
    LINK_RESOLUTION_RETRY_WAIT_SECONDS,
    LinkResolutionAcceptance,
    LinkResolutionGateResult,
    link_resolution_gate_exceeded,
)
from src.weekly_report.search_executor import SearchExecutor
from tests.test_report_application import (
    FixturePlanner,
    FixtureReportApplication,
    FormalEvidenceService,
    RecordingClassifier,
    RecordingDownstreamWorkflow,
    RecordingEventIdentity,
    RecordingOrdering,
    RecordingReportService,
    RecordingScopeClassifier,
    RecordingTemporalRule,
    _fixture_plan,
    _registry,
)


def _google_news(index: int) -> str:
    return f"https://news.google.com/rss/articles/CBMiRC{index:04d}fixture?oc=5"


class LinkProvider:
    """item-0 returns ``links`` Google News links and ``publisher`` publisher URLs."""

    def __init__(self, links: int, publisher: int = 0) -> None:
        self.links = links
        self.publisher = publisher

    def execute(self, item):
        if item.plan_item_id != "item-0":
            return SearchAttemptResult(item.plan_item_id, SearchTerminalStatus.SUCCESS_ZERO_RESULTS)
        results = tuple(DiscoveryResult(f"news {index}", _google_news(index)) for index in range(self.links))
        results += tuple(
            DiscoveryResult(f"publisher {index}", f"https://publisher.example/{index}") for index in range(self.publisher)
        )
        return SearchAttemptResult(item.plan_item_id, SearchTerminalStatus.SUCCESS_WITH_RESULTS, results)


class LinkEvidenceService(FormalEvidenceService):
    """The first ``fail_first`` link candidates fail; ``fail_retry`` of them fail again."""

    def __init__(self, *, fail_first: int, fail_retry: int, semantic_gaps: int = 0) -> None:
        self.fail_first = fail_first
        self.fail_retry = fail_retry
        self.semantic_gaps = semantic_gaps
        self.calls: list[str] = []
        # RC-90: Evidence runs with parallel workers; the bookkeeping is shared.
        self._lock = threading.Lock()

    def evaluate(self, candidate):
        with self._lock:
            self.calls.append(candidate.candidate_id)
            seen = self.calls.count(candidate.candidate_id)
        if candidate.title.startswith("news "):
            index = int(candidate.title.split()[1])
            if seen == 1 and index < self.fail_first:
                raise EvidenceAcquisitionTechnicalFailure("LINK_RESOLUTION_BATCHEXECUTE_HTTP_429", attempts=2)
            if seen == 2 and index < self.fail_retry:
                raise EvidenceAcquisitionTechnicalFailure("LINK_RESOLUTION_BATCHEXECUTE_HTTP_429", attempts=2)
            if self.fail_first <= index < self.fail_first + self.semantic_gaps:
                raise SemanticProviderTechnicalFailure("TIMEOUT", attempts=2, transient=True)
        return FormalEvidenceService.evaluate(_Untracked(), candidate)


class _Untracked:
    """FormalEvidenceService's result without recording the call twice."""

    def __init__(self) -> None:
        self.calls: list = []


def _application(provider, evidence, sleeps, *, formal=False):
    registry = _registry()
    kwargs = {}
    if formal:
        kwargs = dict(
            scope_classifier=RecordingScopeClassifier(),
            temporal_rule=RecordingTemporalRule(default_date=date(2026, 9, 18)),
            event_identity=RecordingEventIdentity(),
            classifier=RecordingClassifier(),
            report_workflow=RecordingDownstreamWorkflow(reportable=True),
            ordering=RecordingOrdering(),
            report_service=RecordingReportService(),
        )
    return FixtureReportApplication(
        registry,
        FixturePlanner(registry, _fixture_plan()),
        SearchExecutor({SearchProviderId.GOOGLE_NEWS_RSS: provider}),
        None,
        evidence,
        sleep=sleeps.append,
        **kwargs,
    )


class LinkResolutionGateRuleTests(TestCase):
    def test_constants_are_the_user_decision(self) -> None:
        self.assertEqual(LINK_RESOLUTION_GATE_MIN_FAILED, 20)
        self.assertEqual(LINK_RESOLUTION_GATE_MIN_RATIO, 0.30)
        self.assertEqual(LINK_RESOLUTION_RETRY_WAIT_SECONDS, 2700)

    def test_both_the_count_and_the_ratio_are_required(self) -> None:
        self.assertFalse(link_resolution_gate_exceeded(0, 0))
        self.assertFalse(link_resolution_gate_exceeded(19, 19))  # 100%, but fewer than 20 links failed
        self.assertTrue(link_resolution_gate_exceeded(20, 20))
        self.assertTrue(link_resolution_gate_exceeded(20, 66))  # 30.3%
        self.assertFalse(link_resolution_gate_exceeded(20, 67))  # 29.9%
        self.assertTrue(link_resolution_gate_exceeded(30, 100))  # exactly 30%
        self.assertFalse(link_resolution_gate_exceeded(29, 100))
        self.assertTrue(link_resolution_gate_exceeded(103, 103))  # Run 44652152415, 05-26..05-28
        self.assertFalse(link_resolution_gate_exceeded(24, 102))  # 23.5%, the highest normal run observed

    def test_gate_result_states(self) -> None:
        self.assertIs(LinkResolutionGateResult(100, 10).acceptance, LinkResolutionAcceptance.PASS)
        self.assertIs(LinkResolutionGateResult(100, 40, 5, wait_seconds=2700).acceptance, LinkResolutionAcceptance.PASS_AFTER_RETRY)
        self.assertIs(LinkResolutionGateResult(100, 40, 35, wait_seconds=2700).acceptance, LinkResolutionAcceptance.BLOCK)
        with self.assertRaises(ValueError):
            LinkResolutionGateResult(100, 10, 5)  # a retry only follows an exceeded gate
        with self.assertRaises(ValueError):
            LinkResolutionGateResult(100, 40, 41)  # a retry never adds failures
        self.assertEqual(
            LinkResolutionGateResult(100, 40, 35, wait_seconds=2700).projection(),
            {"STATUS": "BLOCK", "LINKS": 100, "FAILED": 40, "RETRIED": 40, "FAILED_AFTER_RETRY": 35, "WAIT_SECONDS": 2700},
        )

    def test_evidence_service_names_the_link_population(self) -> None:
        service = EvidenceService.__new__(EvidenceService)
        self.assertTrue(service.requires_link_resolution({"url": _google_news(1), "title": "t"}))
        self.assertFalse(service.requires_link_resolution({"url": "https://publisher.example/a", "title": "t"}))


class LinkResolutionGateApplicationTests(TestCase):
    def test_under_the_gate_runs_on_without_waiting(self) -> None:
        sleeps: list[float] = []
        evidence = LinkEvidenceService(fail_first=19, fail_retry=19)
        result = _application(LinkProvider(19), evidence, sleeps).run("selected")
        self.assertEqual(sleeps, [])
        self.assertIs(result.link_resolution_acceptance, LinkResolutionAcceptance.PASS)
        self.assertEqual(result.link_resolution_gate.projection(), {"STATUS": "PASS", "LINKS": 19, "FAILED": 19, "RETRIED": 0})
        self.assertEqual(len([gap for gap in result.technical_gaps if gap.stage == "Evidence"]), 19)
        self.assertIsNotNone(result.scope_results)

    def test_ratio_counts_only_google_news_links(self) -> None:
        # 20 failed of 20 links (100%), although 60 candidates in all: publisher
        # URLs need no link resolution and are not in the population.
        sleeps: list[float] = []
        evidence = LinkEvidenceService(fail_first=20, fail_retry=0)
        result = _application(LinkProvider(20, publisher=40), evidence, sleeps).run("selected")
        self.assertEqual(result.link_resolution_gate.links, 20)
        self.assertEqual(sleeps, [2700])

    def test_other_evidence_gaps_are_not_link_failures(self) -> None:
        sleeps: list[float] = []
        evidence = LinkEvidenceService(fail_first=10, fail_retry=10, semantic_gaps=30)
        result = _application(LinkProvider(60), evidence, sleeps).run("selected")
        self.assertEqual(sleeps, [])
        self.assertEqual(result.link_resolution_gate.failed, 10)
        self.assertEqual(len([gap for gap in result.technical_gaps if gap.stage == "Evidence"]), 40)

    def test_exceeded_gate_waits_once_and_retries_only_failed_links(self) -> None:
        sleeps: list[float] = []
        evidence = LinkEvidenceService(fail_first=40, fail_retry=5)
        result = _application(LinkProvider(100), evidence, sleeps).run("selected")
        self.assertEqual(sleeps, [2700])
        self.assertEqual(len(evidence.calls), 140)  # 100 first pass + the 40 failed links once
        self.assertEqual(len(set(evidence.calls[100:])), 40)
        self.assertIs(result.link_resolution_acceptance, LinkResolutionAcceptance.PASS_AFTER_RETRY)
        self.assertEqual(result.link_resolution_gate.failed_after_retry, 5)
        # The links that resolved on retry continue; the rest stay disclosed gaps.
        self.assertEqual(len(result.evidence_results), 95)
        self.assertEqual(len([gap for gap in result.technical_gaps if gap.stage == "Evidence"]), 5)
        self.assertIsNotNone(result.scope_results)
        # Evidence keeps the candidates' order.
        order = [candidate.candidate.candidate_id for candidate in result.normalized_candidates]
        self.assertEqual([evidence.candidate_id for evidence in result.evidence_results], [i for i in order if i in {e.candidate_id for e in result.evidence_results}])

    def test_still_exceeded_after_retry_stops_after_evidence(self) -> None:
        sleeps: list[float] = []
        evidence = LinkEvidenceService(fail_first=103, fail_retry=103)
        result = _application(LinkProvider(103), evidence, sleeps, formal=True).run("selected")
        self.assertEqual(sleeps, [2700])
        self.assertEqual(len(evidence.calls), 206)  # no third attempt
        self.assertIs(result.link_resolution_acceptance, LinkResolutionAcceptance.BLOCK)
        self.assertIsNone(result.scope_results)
        self.assertIsNone(result.final_report)
        self.assertEqual(len(result.technical_gaps), 103)


class LinkResolutionGateRunnerTests(TestCase):
    def test_blocked_gate_is_a_technical_failure_with_no_artifact(self) -> None:
        evidence = LinkEvidenceService(fail_first=103, fail_retry=103)
        app = _application(LinkProvider(103), evidence, [], formal=True)
        outcome = ProductionRunner(app).run(period_start="2026-09-12", period_end="2026-09-18")
        self.assertIs(outcome.status, ProductionRunStatus.TECHNICAL_FAILURE)
        self.assertFalse(outcome.successful)
        self.assertEqual(outcome.failure_stage, "evidence")
        self.assertEqual(outcome.failure_class, "LINK_RESOLUTION_GATE")
        self.assertIsNone(outcome.final_report)
        self.assertIsNone(outcome.delivery_result)
        summary = outcome.summary()
        self.assertIn("link_resolution_gate=FAILED=103,FAILED_AFTER_RETRY=103,LINKS=103,RETRIED=103,STATUS=BLOCK,WAIT_SECONDS=2700", summary)
        self.assertIn("TRANSIENT_FAILURE_AFTER_RETRY", summary)
        self.assertEqual(outcome.selection_audit["link_resolution_gate"]["STATUS"], "BLOCK")

    def test_passing_gate_lets_the_run_continue_and_is_disclosed(self) -> None:
        evidence = LinkEvidenceService(fail_first=40, fail_retry=5)
        app = _application(LinkProvider(100), evidence, [], formal=True)
        outcome = ProductionRunner(app).run(period_start="2026-09-12", period_end="2026-09-18")
        # This fixture has no Writer, so the run ends at the report stage; the
        # gate did not stop it.
        self.assertNotEqual(outcome.failure_class, "LINK_RESOLUTION_GATE")
        self.assertEqual(outcome.failure_stage, "final_report")
        self.assertEqual(outcome.link_resolution_gate["STATUS"], "PASS_AFTER_RETRY")
        self.assertIn("link_resolution_gate=", outcome.summary())

    def test_main_exits_non_zero_for_a_technical_failure(self) -> None:
        from pathlib import Path

        source = Path("main.py").read_text(encoding="utf-8")
        self.assertIn("return 2 if result.successful else 1", source)
