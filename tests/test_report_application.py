from __future__ import annotations

from datetime import date
from dataclasses import replace
from unittest import TestCase

from src.weekly_report.candidate_normalizer import CandidateNormalizationError, CandidateNormalizer
from src.weekly_report.classifier import Classifier
from src.weekly_report.contracts import (
    CandidateNormalizationFailure,
    CategoryId,
    CategoryResult,
    CategoryState,
    DiscoveryIntent,
    DiscoveryResult,
    EvidenceResult,
    EvidenceState,
    EventIdentityFacts,
    EventGroup,
    EventIdentityRun,
    GoogleNewsRssEncoding,
    IdentityMetadataSupport,
    RejectReason,
    RegionMode,
    SearchAttemptResult,
    SearchPlan,
    SearchPlanItem,
    SearchProviderId,
    SearchTechnicalFailureClass,
    SearchTerminalStatus,
    ScopeResult,
    ScopeState,
    TaxonomyResult,
    TaxonomyState,
    ReportabilityEvidenceProvenance,
    ReportabilityReason,
    ReportabilityResult,
    ReportabilityState,
    ReportabilitySupportSpan,
    TemporalResult,
    TemporalDiagnostic,
    SourceDateKind,
    candidate_id_for_url,
)
from src.weekly_report.region_registry import RegionRegistry
from src.weekly_report.report_application import ReportApplication
from src.weekly_report.report_application import build_report_application
from src.weekly_report.evidence_service import EvidenceService
from src.weekly_report.search_executor import SearchExecutor
from src.weekly_report.search_planner import SearchPlanner
from src.weekly_report.scope_classifier import ScopeClassifier
from src.weekly_report.temporal_rule import TemporalRule
from src.weekly_report.event_identity import EventIdentity
from src.weekly_report.report_workflow import ReportWorkflow, ReportWorkflowResult
from src.weekly_report.ordering import Ordering
from src.weekly_report.report_service import (
    FormalMetadataFailure,
    FormalMetadataFailureReason,
    FormalReportMetadata,
    ReportService,
)
from src.weekly_report.taxonomy import Taxonomy


def _registry() -> RegionRegistry:
    return RegionRegistry.from_file()


def _fixture_plan() -> SearchPlan:
    items = tuple(
        SearchPlanItem(
            f"item-{index}", "fixture", RegionMode.SELECTED, DiscoveryIntent.OPERATIONS,
            "en", "family", SearchProviderId.GOOGLE_NEWS_RSS, f"query-{index}",
            GoogleNewsRssEncoding("en-US", "US", "US:en"), "en-US",
        )
        for index in range(2)
    )
    return SearchPlan("search-discovery-v3", RegionMode.SELECTED, items, "fixture-plan")


class FixturePlanner(SearchPlanner):
    def __init__(self, registry, plan):
        super().__init__(registry)
        self._plan = plan

    def plan(self, mode, intents=None):
        return self._plan


class FakeProvider:
    def __init__(self, *, failure_item: str | None = None, infrastructure: bool = False):
        self.failure_item = failure_item
        self.infrastructure = infrastructure
        self.calls: list[str] = []

    def execute(self, item):
        self.calls.append(item.plan_item_id)
        if self.infrastructure:
            raise RuntimeError("provider failure")
        if item.plan_item_id == self.failure_item:
            return SearchAttemptResult(item.plan_item_id, SearchTerminalStatus.TECHNICAL_FAILURE, technical_failure_class=SearchTechnicalFailureClass.TIMEOUT)
        if item.plan_item_id == "item-1":
            return SearchAttemptResult(item.plan_item_id, SearchTerminalStatus.SUCCESS_ZERO_RESULTS)
        return SearchAttemptResult(item.plan_item_id, SearchTerminalStatus.SUCCESS_WITH_RESULTS, (DiscoveryResult("title", "https://example.test/item"),))


class MultiResultProvider(FakeProvider):
    def execute(self, item):
        self.calls.append(item.plan_item_id)
        if item.plan_item_id == "item-1":
            return SearchAttemptResult(item.plan_item_id, SearchTerminalStatus.SUCCESS_ZERO_RESULTS)
        return SearchAttemptResult(
            item.plan_item_id,
            SearchTerminalStatus.SUCCESS_WITH_RESULTS,
            (
                DiscoveryResult("first", "https://example.test/first"),
                DiscoveryResult("second", "https://example.test/second"),
            ),
        )


class TripleResultProvider(MultiResultProvider):
    def execute(self, item):
        self.calls.append(item.plan_item_id)
        if item.plan_item_id == "item-1":
            return SearchAttemptResult(item.plan_item_id, SearchTerminalStatus.SUCCESS_ZERO_RESULTS)
        return SearchAttemptResult(
            item.plan_item_id,
            SearchTerminalStatus.SUCCESS_WITH_RESULTS,
            (
                DiscoveryResult("first", "https://example.test/first"),
                DiscoveryResult("second", "https://example.test/second"),
                DiscoveryResult("third", "https://example.test/third"),
            ),
        )


class ZeroResultProvider(FakeProvider):
    def execute(self, item):
        self.calls.append(item.plan_item_id)
        return SearchAttemptResult(item.plan_item_id, SearchTerminalStatus.SUCCESS_ZERO_RESULTS)


class FormalResultProvider(FakeProvider):
    def execute(self, item):
        self.calls.append(item.plan_item_id)
        if item.plan_item_id == "item-1":
            return SearchAttemptResult(item.plan_item_id, SearchTerminalStatus.SUCCESS_ZERO_RESULTS)
        return SearchAttemptResult(
            item.plan_item_id,
            SearchTerminalStatus.SUCCESS_WITH_RESULTS,
            (DiscoveryResult("formal event", "https://candidate.example/formal"),),
        )


class TwoFormalResultProvider(FormalResultProvider):
    def execute(self, item):
        self.calls.append(item.plan_item_id)
        if item.plan_item_id == "item-1":
            return SearchAttemptResult(item.plan_item_id, SearchTerminalStatus.SUCCESS_ZERO_RESULTS)
        return SearchAttemptResult(
            item.plan_item_id,
            SearchTerminalStatus.SUCCESS_WITH_RESULTS,
            (
                DiscoveryResult("formal event one", "https://candidate.example/formal-one"),
                DiscoveryResult("formal event two", "https://candidate.example/formal-two"),
            ),
        )


class RecordingEvidenceService(EvidenceService):
    def __init__(self, *, rejected_ids=(), error=None, invalid_result=None):
        self.calls = []
        self.rejected_ids = set(rejected_ids)
        self.error = error
        self.invalid_result = invalid_result

    def evaluate(self, candidate):
        self.calls.append(candidate)
        if self.error is not None:
            raise self.error
        if self.invalid_result is not None:
            return self.invalid_result
        if candidate.candidate_id in self.rejected_ids:
            return EvidenceResult(
                candidate.candidate_id,
                EvidenceState.REJECTED,
                reject_reason=RejectReason.CONTENT_UNAVAILABLE,
            )
        return EvidenceResult(
            candidate.candidate_id,
            EvidenceState.READY,
            substantive_content="authoritative fixture body",
        )


class FormalEvidenceService(RecordingEvidenceService):
    def evaluate(self, candidate):
        self.calls.append(candidate)
        body = "Taiwan Metro Taipei"
        facts = EventIdentityFacts(
            country="Taiwan",
            transit_system_name="Metro",
            location="Taipei",
            metadata_support=(
                IdentityMetadataSupport("country", 0, 6),
                IdentityMetadataSupport("transit_system_name", 7, 12),
                IdentityMetadataSupport("location", 13, 19),
            ),
        )
        return EvidenceResult(
            candidate.candidate_id,
            EvidenceState.READY,
            canonical_source_url="https://WWW.News.Example.COM:8443/formal",
            substantive_content=body,
            identity_facts=facts,
        )


class FailOnSecondEvidenceService(RecordingEvidenceService):
    def __init__(self, error: RuntimeError):
        super().__init__()
        self.error = error

    def evaluate(self, candidate):
        self.calls.append(candidate)
        if len(self.calls) == 2:
            raise self.error
        return EvidenceResult(
            candidate.candidate_id,
            EvidenceState.READY,
            substantive_content="authoritative fixture body",
        )


class FixtureReportApplication(ReportApplication):
    """Keep legacy Search/Evidence fixtures concise with an explicit period."""

    def run(self, mode, intents=None, *, period_start="2026-09-12", period_end="2026-09-18"):
        return super().run(
            mode,
            intents,
            period_start=period_start,
            period_end=period_end,
        )


class RecordingScopeClassifier(ScopeClassifier):
    def __init__(self, *, out_of_scope=(), error=None, invalid=None):
        self.calls = []
        self.out_of_scope = set(out_of_scope)
        self.error = error
        self.invalid = invalid

    def classify(self, evidence, *, candidate_title=""):
        self.calls.append((evidence, candidate_title))
        if self.error is not None:
            raise self.error
        if self.invalid is not None:
            return self.invalid
        state = (
            ScopeState.OUT_OF_SCOPE
            if evidence.candidate_id in self.out_of_scope
            else ScopeState.IN_SCOPE
        )
        return ScopeResult(evidence.candidate_id, state)


class RecordingTemporalRule(TemporalRule):
    def __init__(self, *, invalid=None, error=None, date_valid=True, default_date=None, dates=None):
        self.calls = []
        self.invalid = invalid
        self.error = error
        self.date_valid = date_valid
        self.default_date = default_date
        self.dates = dict(dates or {})

    def evaluate(self, candidate_id, source_date_facts, period_start, period_end, **kwargs):
        self.calls.append((candidate_id, tuple(source_date_facts), period_start, period_end, kwargs))
        if self.error is not None:
            raise self.error
        if self.invalid is not None:
            return self.invalid
        return TemporalResult(
            candidate_id,
            self.date_valid,
            diagnostic=(
                TemporalDiagnostic.NONE
                if self.date_valid
                else TemporalDiagnostic.DATE_MISSING
            ),
            controlling_calendar_date=(
                self.dates.get(candidate_id, self.default_date)
                if self.date_valid
                else None
            ),
            controlling_date_kind=(
                SourceDateKind.ORIGINAL_PUBLICATION if self.date_valid else None
            ),
        )


class RecordingEventIdentity(EventIdentity):
    def __init__(self, *, error=None, invalid=None, merge=False):
        self.calls = []
        self.error = error
        self.invalid = invalid
        self.merge = merge

    def evaluate(self, records):
        records = tuple(records)
        self.calls.append(records)
        if self.error is not None:
            raise self.error
        if self.invalid is not None:
            return self.invalid
        if self.merge and records:
            ids = tuple(sorted(record.candidate.candidate_id for record in records))
            return EventIdentityRun((EventGroup("evt-fixture", ids, ids[0], ()),))
        groups = tuple(
            EventGroup(f"evt-{record.candidate.candidate_id}", (record.candidate.candidate_id,), record.candidate.candidate_id, ())
            for record in records
        )
        return EventIdentityRun(groups)


def _assigned_category(event_group: EventGroup) -> CategoryResult:
    return CategoryResult(
        CategoryState.CATEGORY_ASSIGNED,
        event_id=event_group.event_id,
        primary_category_id=CategoryId.PROCUREMENT,
        primary_category=CategoryId.PROCUREMENT.display_label,
        classification_reason="PRINCIPAL_ACTION_PROCUREMENT",
    )


class RecordingClassifier(Classifier):
    def __init__(self, *, result_factory=None, error_after=None):
        self.calls = []
        self.results = []
        self.result_factory = result_factory
        self.error_after = error_after

    def classify(self, event_group, records):
        records = tuple(records)
        self.calls.append((event_group, records))
        if self.error_after is not None and len(self.calls) > self.error_after:
            raise RuntimeError("unexpected classifier failure")
        if self.result_factory is not None:
            result = self.result_factory(event_group, records, len(self.calls))
        else:
            result = _assigned_category(event_group)
        self.results.append(result)
        return result


class RecordingDownstreamTaxonomy:
    def __init__(self, *, fail_on_event_id=None, fail_on_call=None):
        self.calls = []
        self.fail_on_event_id = fail_on_event_id
        self.fail_on_call = fail_on_call

    def evaluate(self, event_group, records, category_result):
        records = tuple(records)
        self.calls.append((event_group, records, category_result))
        if (
            event_group.event_id == self.fail_on_event_id
            or len(self.calls) == self.fail_on_call
        ):
            raise RuntimeError("downstream taxonomy failure")
        if category_result.category_state is CategoryState.CATEGORY_UNRESOLVED:
            return TaxonomyResult.not_evaluated(event_id=event_group.event_id)
        return TaxonomyResult(
            taxonomy_state=TaxonomyState.TAXONOMY_EVALUATED,
            event_id=event_group.event_id,
        )


class RecordingDownstreamReportability:
    def __init__(self, *, fail_on_call=None, reportable=False, reportable_on_calls=()):
        self.calls = []
        self.successful_event_ids = []
        self.fail_on_call = fail_on_call
        self.reportable = reportable
        self.reportable_on_calls = set(reportable_on_calls)

    def evaluate(self, decision):
        self.calls.append(decision)
        if len(self.calls) == self.fail_on_call:
            raise RuntimeError("downstream reportability failure")
        self.successful_event_ids.append(decision.event_group.event_id)
        if self.reportable or len(self.calls) in self.reportable_on_calls:
            return ReportabilityResult(
                event_id=decision.event_group.event_id,
                reportability_state=ReportabilityState.REPORTABLE,
                reportability_reason=None,
                provenance=ReportabilityEvidenceProvenance(
                    examined_candidate_ids=decision.event_group.member_candidate_ids,
                    support_spans=(
                        ReportabilitySupportSpan(
                            decision.event_group.member_candidate_ids[0], 0, 1
                        ),
                    ),
                    rationale="fixture downstream result",
                ),
            )
        return ReportabilityResult(
            event_id=decision.event_group.event_id,
            reportability_state=ReportabilityState.NOT_REPORTABLE,
            reportability_reason=ReportabilityReason.LOW_REPORTABILITY_VALUE,
            provenance=ReportabilityEvidenceProvenance(
                examined_candidate_ids=decision.event_group.member_candidate_ids,
                support_spans=(),
                rationale="fixture downstream result",
            ),
        )


class RecordingDownstreamWorkflow(ReportWorkflow):
    def __init__(
        self,
        *,
        fail_on_event_id=None,
        fail_on_call=None,
        fail_reportability_on_call=None,
        reportable=False,
        reportable_on_calls=(),
    ):
        self.taxonomy_owner = RecordingDownstreamTaxonomy(
            fail_on_event_id=fail_on_event_id,
            fail_on_call=fail_on_call,
        )
        self.reportability_owner = RecordingDownstreamReportability(
            fail_on_call=fail_reportability_on_call,
            reportable=reportable,
            reportable_on_calls=reportable_on_calls,
        )
        self.calls = []
        super().__init__(self.taxonomy_owner, reportability=self.reportability_owner)

    def run(self, event_groups, member_records, category_results):
        self.calls.append((tuple(event_groups), member_records, tuple(category_results)))
        return super().run(event_groups, member_records, category_results)


class BrokenOrdering(Ordering):
    def __init__(self, output_factory):
        self.calls = []
        self.output_factory = output_factory

    def order(self, events):
        events = tuple(events)
        self.calls.append(events)
        return self.output_factory(events)


class MalformedDownstreamWorkflow(RecordingDownstreamWorkflow):
    def __init__(self, mode):
        super().__init__(reportable=True)
        self.mode = mode

    def run(self, event_groups, member_records, category_results):
        results = super().run(event_groups, member_records, category_results)
        if self.mode == "raw":
            return (results[0].decision,)
        if self.mode == "mixed":
            return (results[0], results[1].decision)
        raise AssertionError(f"unknown malformed mode: {self.mode}")


class RecordingOrdering(Ordering):
    def __init__(self, *, error=None, reverse=False, trace=None):
        self.calls = []
        self.returned_results = []
        self.error = error
        self.reverse = reverse
        self.trace = trace

    def order(self, events):
        events = tuple(events)
        self.calls.append(events)
        if self.trace is not None:
            self.trace.append("ordering")
        if self.error is not None:
            raise self.error
        if self.reverse:
            ordered_results = tuple(reversed(events))
        else:
            ordered_results = super().order(events)
        self.returned_results.append(ordered_results)
        return ordered_results


class RecordingReportService(ReportService):
    def __init__(self, *, failure=None, trace=None):
        self.calls = []
        self.failure = failure
        self.trace = trace

    def project_formal_metadata(self, ordered_results):
        self.calls.append(ordered_results)
        if self.trace is not None:
            self.trace.append("report_service")
        if self.failure is not None:
            raise self.failure
        return super().project_formal_metadata(ordered_results)


class ReportApplicationTests(TestCase):
    def _app(
        self,
        provider: FakeProvider,
        *,
        dispatch=True,
        normalizer=None,
        evidence_service=None,
        scope_classifier=None,
        temporal_rule=None,
        event_identity=None,
        classifier=None,
        report_workflow=None,
        ordering=None,
        report_service=None,
    ) -> ReportApplication:
        plan = _fixture_plan()
        registry = _registry()
        mapping = {SearchProviderId.GOOGLE_NEWS_RSS: provider} if dispatch else {}
        return FixtureReportApplication(
            registry,
            FixturePlanner(registry, plan),
            SearchExecutor(mapping),
            normalizer,
            evidence_service or RecordingEvidenceService(),
            scope_classifier=scope_classifier,
            temporal_rule=temporal_rule,
            event_identity=event_identity,
            classifier=classifier,
            report_workflow=report_workflow,
            ordering=ordering,
            report_service=report_service,
        )

    def _reportable_run(self, ordering, *, provider=None, workflow=None, classifier=None):
        return self._app(
            provider or MultiResultProvider(),
            scope_classifier=RecordingScopeClassifier(),
            temporal_rule=RecordingTemporalRule(default_date=date(2026, 9, 18)),
            event_identity=RecordingEventIdentity(),
            classifier=classifier or RecordingClassifier(),
            report_workflow=workflow or RecordingDownstreamWorkflow(reportable=True),
            ordering=ordering,
        ).run("selected")

    def _formal_application_run(self, *, provider=None, trace=None, ordering=None):
        report_service = RecordingReportService(trace=trace)
        if ordering is None:
            ordering = RecordingOrdering(trace=trace)
        result = self._app(
            provider or FormalResultProvider(),
            evidence_service=FormalEvidenceService(),
            scope_classifier=RecordingScopeClassifier(),
            temporal_rule=RecordingTemporalRule(default_date=date(2026, 9, 18)),
            event_identity=RecordingEventIdentity(),
            classifier=RecordingClassifier(),
            report_workflow=RecordingDownstreamWorkflow(reportable=True),
            ordering=ordering,
            report_service=report_service,
        ).run("selected")
        return result, report_service

    def test_fixture_preserves_complete_production_registry(self) -> None:
        registry = self._app(FakeProvider()).registry
        production = RegionRegistry.from_file()
        self.assertEqual(registry.selected_markets, production.selected_markets)
        self.assertEqual(registry.global_targets, production.global_targets)
        self.assertEqual(registry.provider_profile_bindings, production.provider_profile_bindings)

    def test_denmark_remains_configured_with_no_executable_profiles(self) -> None:
        registry = self._app(FakeProvider()).registry
        self.assertIn("denmark", {market.market_id for market in registry.selected_markets})
        self.assertIn("denmark", registry.global_targets)
        bindings = tuple(binding for binding in registry.provider_profile_bindings if binding.market_id == "denmark")
        self.assertTrue(bindings)
        self.assertTrue(all(binding.eligibility.value == "UNSUPPORTED" and binding.encoding is None for binding in bindings))
        self.assertEqual(sum(binding.eligibility.value == "SUPPORTED" for binding in bindings), 0)

    def test_only_normalizer_owned_typed_failure_is_consumed(self) -> None:
        failure = CandidateNormalizationFailure("INTERNAL_FAILURE")

        class FailingNormalizer(CandidateNormalizer):
            def normalize(self, acquisitions):
                raise CandidateNormalizationError(failure)

        result = self._app(FakeProvider(), normalizer=FailingNormalizer()).run("selected")
        self.assertIs(result.normalization_failure, failure)
        self.assertFalse(result.downstream_ready)
        self.assertIsNone(result.normalization_result)
        self.assertTrue(all(item.normalized_result_count is None for item in result.normalized_observations))

    def test_unexpected_normalizer_exception_is_not_reclassified(self) -> None:
        error = RuntimeError("unexpected normalizer failure")

        class BrokenNormalizer(CandidateNormalizer):
            def normalize(self, acquisitions):
                raise error

        with self.assertRaises(RuntimeError) as context:
            self._app(FakeProvider(), normalizer=BrokenNormalizer()).run("selected")
        self.assertIs(context.exception, error)

    def test_observation_projection_uses_stable_acquisition_identity(self) -> None:
        class CopyingNormalizer(CandidateNormalizer):
            def normalize(self, acquisitions):
                copies = tuple(replace(record, raw_result=replace(record.raw_result)) for record in acquisitions)
                for original, copied in zip(acquisitions, copies, strict=True):
                    self_test.assertIsNot(original, copied)
                    self_test.assertEqual(original.acquisition_id, copied.acquisition_id)
                return super().normalize(copies)

        self_test = self
        result = self._app(FakeProvider(), normalizer=CopyingNormalizer()).run("selected")
        self.assertTrue(result.downstream_ready)
        self.assertEqual(tuple(item.normalized_result_count for item in result.normalized_observations), (1, 0))
        self.assertTrue(all(item.normalized_result_count is None for item in result.execution.observations))

    def test_planner_executor_normalizer_path_and_projection(self) -> None:
        provider = FakeProvider()
        result = self._app(provider).run("selected")
        self.assertTrue(result.downstream_ready)
        self.assertEqual(len(result.normalized_candidates), 1)
        self.assertEqual(tuple(item.normalized_result_count for item in result.normalized_observations), (1, 0))
        self.assertEqual(result.execution.observations[0].normalized_result_count, None)
        self.assertEqual(provider.calls, ["item-0", "item-1"])

    def test_technical_failure_blocks_downstream(self) -> None:
        result = self._app(FakeProvider(failure_item="item-1")).run("selected")
        self.assertFalse(result.downstream_ready)
        self.assertIsNone(result.normalization_result)

    def test_infrastructure_failure_and_incomplete_execution_block(self) -> None:
        result = self._app(FakeProvider(infrastructure=True)).run("selected")
        self.assertFalse(result.downstream_ready)
        self.assertFalse(result.execution.execution_complete)
        result = self._app(FakeProvider(), dispatch=False).run("selected")
        self.assertFalse(result.downstream_ready)
        self.assertFalse(result.execution.execution_complete)

    def test_all_zero_search_is_valid_and_produces_zero_candidates(self) -> None:
        class ZeroProvider(FakeProvider):
            def execute(self, item):
                self.calls.append(item.plan_item_id)
                return SearchAttemptResult(item.plan_item_id, SearchTerminalStatus.SUCCESS_ZERO_RESULTS)

        result = self._app(ZeroProvider()).run("selected")
        self.assertTrue(result.downstream_ready)
        self.assertEqual(result.normalized_candidates, ())
        self.assertEqual(tuple(item.normalized_result_count for item in result.normalized_observations), (0, 0))

    def test_invalid_acquisition_blocks_without_repair(self) -> None:
        class BadProvider(FakeProvider):
            def execute(self, item):
                self.calls.append(item.plan_item_id)
                return SearchAttemptResult(item.plan_item_id, SearchTerminalStatus.SUCCESS_WITH_RESULTS, (DiscoveryResult("bad", "relative"),))

        result = self._app(BadProvider()).run("selected")
        self.assertFalse(result.downstream_ready)
        self.assertEqual(result.normalization_failure.failure_class.value, "INVALID_URL")
        self.assertEqual(result.execution.attempt_results[0].results[0].url, "relative")

    def test_ready_evidence_is_called_once_with_original_candidate_and_admitted(self) -> None:
        service = RecordingEvidenceService()
        result = self._app(FakeProvider(), evidence_service=service).run("selected")

        self.assertTrue(result.evidence_stage_completed)
        self.assertEqual(len(service.calls), 1)
        self.assertIs(service.calls[0], result.normalized_candidates[0].candidate)
        self.assertIs(result.evidence_results[0].state, EvidenceState.READY)
        self.assertEqual(result.evidence_admitted_candidates, result.normalized_candidates)

    def test_rejected_evidence_is_preserved_and_not_admitted(self) -> None:
        candidate_id = candidate_id_for_url("https://example.test/item")
        service = RecordingEvidenceService(rejected_ids={candidate_id})
        result = self._app(FakeProvider(), evidence_service=service).run("selected")

        self.assertTrue(result.downstream_ready)
        self.assertEqual(len(service.calls), 1)
        self.assertEqual(result.evidence_results[0].reject_reason, RejectReason.CONTENT_UNAVAILABLE)
        self.assertEqual(result.evidence_admitted_candidates, ())

    def test_mixed_evidence_keeps_results_and_admits_only_ready_candidates(self) -> None:
        rejected_id = candidate_id_for_url("https://example.test/second")
        service = RecordingEvidenceService(rejected_ids={rejected_id})
        result = self._app(
            MultiResultProvider(), evidence_service=service
        ).run("selected")

        self.assertEqual(len(service.calls), 2)
        self.assertEqual(
            tuple(item.candidate_id for item in result.evidence_results),
            tuple(item.candidate.candidate_id for item in result.normalized_candidates),
        )
        self.assertEqual(
            tuple(item.state for item in result.evidence_results),
            (EvidenceState.READY, EvidenceState.REJECTED),
        )
        self.assertEqual(
            tuple(item.candidate.candidate_id for item in result.evidence_admitted_candidates),
            (result.normalized_candidates[0].candidate.candidate_id,),
        )

    def test_evidence_keeps_normalized_candidate_provenance_unchanged(self) -> None:
        service = RecordingEvidenceService()
        result = self._app(MultiResultProvider(), evidence_service=service).run("selected")

        self.assertIs(result.normalized_candidates[0].candidate, service.calls[0])
        origins = result.normalized_candidates[0].acquisition_origins
        self.assertEqual(len(origins), 1)
        self.assertEqual(
            tuple(origin.record.raw_result.url for origin in origins),
            ("https://example.test/first",),
        )
        self.assertEqual(origins[0].record.plan_item.plan_item_id, "item-0")

    def test_search_failure_does_not_call_evidence(self) -> None:
        service = RecordingEvidenceService()
        result = self._app(FakeProvider(failure_item="item-1"), evidence_service=service).run("selected")

        self.assertFalse(result.evidence_stage_completed)
        self.assertEqual(service.calls, [])

    def test_normalization_failure_does_not_call_evidence(self) -> None:
        service = RecordingEvidenceService()
        failure = CandidateNormalizationFailure("INTERNAL_FAILURE")

        class FailingNormalizer(CandidateNormalizer):
            def normalize(self, acquisitions):
                raise CandidateNormalizationError(failure)

        result = self._app(
            FakeProvider(), normalizer=FailingNormalizer(), evidence_service=service
        ).run("selected")
        self.assertEqual(service.calls, [])
        self.assertFalse(result.evidence_stage_completed)

    def test_invalid_evidence_result_type_aborts_without_fabrication(self) -> None:
        service = RecordingEvidenceService(invalid_result={})
        with self.assertRaises(TypeError):
            self._app(FakeProvider(), evidence_service=service).run("selected")

    def test_evidence_candidate_id_mismatch_aborts(self) -> None:
        service = RecordingEvidenceService(
            invalid_result=EvidenceResult(
                "wrong", EvidenceState.READY, substantive_content="body"
            )
        )
        with self.assertRaises(ValueError):
            self._app(FakeProvider(), evidence_service=service).run("selected")

    def test_unexpected_evidence_exception_propagates_without_partial_result(self) -> None:
        error = RuntimeError("unexpected evidence failure")
        service = RecordingEvidenceService(error=error)
        with self.assertRaises(RuntimeError) as context:
            self._app(FakeProvider(), evidence_service=service).run("selected")
        self.assertIs(context.exception, error)

    def test_partial_ready_then_unexpected_evidence_exception_exposes_no_result(self) -> None:
        error = RuntimeError("unexpected second evidence failure")
        service = FailOnSecondEvidenceService(error)
        completed = None

        with self.assertRaises(RuntimeError) as context:
            completed = self._app(MultiResultProvider(), evidence_service=service).run("selected")

        self.assertIs(context.exception, error)
        self.assertIsNone(completed)
        self.assertEqual(len(service.calls), 2)

    def test_evidence_results_require_successful_search_execution(self) -> None:
        valid = self._app(MultiResultProvider()).run("selected")
        incomplete = self._app(MultiResultProvider(), dispatch=False).run("selected").execution
        technical_failure = self._app(FakeProvider(failure_item="item-1")).run("selected").execution

        for execution in (incomplete, technical_failure):
            with self.assertRaises(ValueError):
                replace(valid, execution=execution)

        self.assertTrue(valid.downstream_ready)
        self.assertTrue(valid.evidence_stage_completed)

    def test_downstream_ready_is_search_side_only(self) -> None:
        rejected_id = candidate_id_for_url("https://example.test/first")
        rejected = self._app(
            MultiResultProvider(),
            evidence_service=RecordingEvidenceService(rejected_ids={rejected_id}),
        ).run("selected")

        class ZeroProvider(FakeProvider):
            def execute(self, item):
                self.calls.append(item.plan_item_id)
                return SearchAttemptResult(item.plan_item_id, SearchTerminalStatus.SUCCESS_ZERO_RESULTS)

        zero = self._app(ZeroProvider()).run("selected")

        self.assertTrue(rejected.downstream_ready)
        self.assertTrue(rejected.evidence_stage_completed)
        self.assertEqual(rejected.evidence_admitted_candidates, (rejected.normalized_candidates[1],))
        self.assertTrue(zero.downstream_ready)
        self.assertTrue(zero.evidence_stage_completed)
        self.assertEqual(zero.evidence_results, ())

    def test_zero_candidates_complete_with_zero_evidence_calls(self) -> None:
        class ZeroProvider(FakeProvider):
            def execute(self, item):
                self.calls.append(item.plan_item_id)
                return SearchAttemptResult(item.plan_item_id, SearchTerminalStatus.SUCCESS_ZERO_RESULTS)

        service = RecordingEvidenceService()
        result = self._app(ZeroProvider(), evidence_service=service).run("selected")
        self.assertTrue(result.evidence_stage_completed)
        self.assertEqual(result.evidence_results, ())
        self.assertEqual(service.calls, [])

    def test_ready_evidence_flows_through_scope_temporal_and_event_identity(self) -> None:
        scope = RecordingScopeClassifier()
        temporal = RecordingTemporalRule()
        identity = RecordingEventIdentity()
        result = self._app(
            FakeProvider(),
            scope_classifier=scope,
            temporal_rule=temporal,
            event_identity=identity,
        ).run("selected", period_start="2026-09-12", period_end="2026-09-18")

        self.assertEqual(len(scope.calls), 1)
        self.assertEqual(len(temporal.calls), 1)
        self.assertEqual(len(identity.calls), 1)
        self.assertEqual(len(identity.calls[0]), 1)
        self.assertEqual(len(result.event_identity_run.groups), 1)
        self.assertIs(result.event_identity_records[0].evidence, result.evidence_results[0])
        self.assertIs(result.event_identity_records[0].scope, result.scope_results[0])
        self.assertIs(result.event_identity_records[0].temporal, result.temporal_results[0])

    def test_rejected_evidence_never_reaches_scope(self) -> None:
        scope = RecordingScopeClassifier()
        result = self._app(
            FakeProvider(),
            evidence_service=RecordingEvidenceService(
                rejected_ids={candidate_id_for_url("https://example.test/item")}
            ),
            scope_classifier=scope,
            temporal_rule=RecordingTemporalRule(),
            event_identity=RecordingEventIdentity(),
        ).run("selected")

        self.assertEqual(scope.calls, [])
        self.assertEqual(result.scope_results, ())
        self.assertEqual(result.temporal_results, ())
        self.assertEqual(result.event_identity_records, ())

    def test_out_of_scope_stops_before_temporal_and_event_identity(self) -> None:
        scope = RecordingScopeClassifier(
            out_of_scope={candidate_id_for_url("https://example.test/item")}
        )
        temporal = RecordingTemporalRule()
        identity = RecordingEventIdentity()
        result = self._app(
            FakeProvider(),
            scope_classifier=scope,
            temporal_rule=temporal,
            event_identity=identity,
        ).run("selected")

        self.assertEqual(result.scope_results[0].state, ScopeState.OUT_OF_SCOPE)
        self.assertEqual(temporal.calls, [])
        self.assertEqual(identity.calls, [()])
        self.assertEqual(result.event_identity_run.groups, ())

    def test_invalid_temporal_result_stops_before_event_identity(self) -> None:
        temporal = RecordingTemporalRule(invalid={})
        identity = RecordingEventIdentity()
        with self.assertRaises(TypeError):
            self._app(
                FakeProvider(),
                scope_classifier=RecordingScopeClassifier(),
                temporal_rule=temporal,
                event_identity=identity,
            ).run("selected")
        self.assertEqual(identity.calls, [])

    def test_event_identity_receives_complete_population_once(self) -> None:
        scope = RecordingScopeClassifier()
        temporal = RecordingTemporalRule()
        identity = RecordingEventIdentity()
        result = self._app(
            MultiResultProvider(),
            scope_classifier=scope,
            temporal_rule=temporal,
            event_identity=identity,
        ).run("selected")

        self.assertEqual(len(scope.calls), 2)
        self.assertEqual(len(temporal.calls), 2)
        self.assertEqual(len(identity.calls), 1)
        self.assertEqual(
            {record.candidate.candidate_id for record in identity.calls[0]},
            {candidate.candidate.candidate_id for candidate in result.normalized_candidates},
        )

    def test_duplicate_event_keeps_all_member_records_and_provenance(self) -> None:
        identity = RecordingEventIdentity(merge=True)
        result = self._app(
            MultiResultProvider(),
            scope_classifier=RecordingScopeClassifier(),
            temporal_rule=RecordingTemporalRule(),
            event_identity=identity,
        ).run("selected")

        self.assertEqual(len(result.event_identity_run.groups), 1)
        group = result.event_identity_run.groups[0]
        self.assertEqual(len(group.member_candidate_ids), 2)
        self.assertEqual(len(result.event_identity_records), 2)
        self.assertEqual(len(identity.calls), 1)
        self.assertEqual(len(result.normalized_candidates[0].acquisition_origins), 1)
        self.assertEqual(len(result.normalized_candidates[1].acquisition_origins), 1)

    def test_category_classifies_one_group_once_and_preserves_result(self) -> None:
        classifier = RecordingClassifier()
        result = self._app(
            FakeProvider(),
            classifier=classifier,
            scope_classifier=RecordingScopeClassifier(),
            temporal_rule=RecordingTemporalRule(),
            event_identity=RecordingEventIdentity(),
        ).run("selected")

        group = result.event_identity_run.groups[0]
        self.assertEqual(len(classifier.calls), 1)
        self.assertIs(classifier.calls[0][0], group)
        self.assertEqual(classifier.calls[0][1], (result.event_identity_records[0],))
        self.assertIs(result.category_results[0], classifier.results[0])
        self.assertEqual(result.category_results[0].event_id, group.event_id)

    def test_category_receives_all_group_members_in_authoritative_order(self) -> None:
        classifier = RecordingClassifier()
        result = self._app(
            MultiResultProvider(),
            classifier=classifier,
            scope_classifier=RecordingScopeClassifier(),
            temporal_rule=RecordingTemporalRule(),
            event_identity=RecordingEventIdentity(merge=True),
        ).run("selected")

        group = result.event_identity_run.groups[0]
        records = classifier.calls[0][1]
        self.assertEqual(len(classifier.calls), 1)
        self.assertEqual(
            tuple(record.candidate.candidate_id for record in records),
            group.member_candidate_ids,
        )
        expected_records = tuple(
            next(
                record
                for record in result.event_identity_records
                if record.candidate.candidate_id == candidate_id
            )
            for candidate_id in group.member_candidate_ids
        )
        self.assertEqual(records, expected_records)
        self.assertTrue(all(actual is expected for actual, expected in zip(records, expected_records)))

    def test_category_calls_once_per_group_and_preserves_group_order(self) -> None:
        classifier = RecordingClassifier()
        result = self._app(
            MultiResultProvider(),
            classifier=classifier,
            scope_classifier=RecordingScopeClassifier(),
            temporal_rule=RecordingTemporalRule(),
            event_identity=RecordingEventIdentity(),
        ).run("selected")

        self.assertEqual(len(classifier.calls), 2)
        self.assertEqual(
            tuple(call[0].event_id for call in classifier.calls),
            tuple(group.event_id for group in result.event_identity_run.groups),
        )
        self.assertEqual(
            tuple(category.event_id for category in result.category_results),
            tuple(group.event_id for group in result.event_identity_run.groups),
        )

    def test_downstream_bridge_adopts_authoritative_category_and_member_references(self) -> None:
        classifier = RecordingClassifier()
        event_identity = RecordingEventIdentity(merge=True)
        workflow = RecordingDownstreamWorkflow()
        result = self._app(
            MultiResultProvider(),
            classifier=classifier,
            scope_classifier=RecordingScopeClassifier(),
            temporal_rule=RecordingTemporalRule(),
            event_identity=event_identity,
            report_workflow=workflow,
        ).run("selected")

        self.assertEqual(len(event_identity.calls), 1)
        self.assertEqual(len(workflow.calls), 1)
        groups, member_records, category_results = workflow.calls[0]
        self.assertEqual(groups, result.event_identity_run.groups)
        self.assertTrue(all(
            actual is expected
            for actual, expected in zip(groups, result.event_identity_run.groups, strict=True)
        ))
        self.assertEqual(category_results, result.category_results)
        self.assertTrue(all(actual is expected for actual, expected in zip(
            category_results, classifier.results, strict=True
        )))
        for group in groups:
            self.assertEqual(len(group.member_candidate_ids), 2)
            expected = tuple(
                next(
                    record
                    for record in result.event_identity_records
                    if record.candidate.candidate_id == candidate_id
                )
                for candidate_id in group.member_candidate_ids
            )
            self.assertTrue(all(actual is expected for actual, expected in zip(
                member_records[group.event_id], expected, strict=True
            )))
            self.assertEqual(
                tuple(record.candidate.candidate_id for record in member_records[group.event_id]),
                group.member_candidate_ids,
            )
        self.assertEqual(len(result.downstream_results), len(groups))
        self.assertTrue(all(
            item.decision.event_group is group
            for item, group in zip(result.downstream_results, groups, strict=True)
        ))
        self.assertTrue(all(
            item.category_result is category
            for item, category in zip(result.downstream_results, category_results, strict=True)
        ))
        self.assertIs(
            replace(result, downstream_results=result.downstream_results).downstream_results[0],
            result.downstream_results[0],
        )
        self.assertEqual(len(classifier.calls), len(groups))
        self.assertEqual(len(workflow.taxonomy_owner.calls), len(groups))
        self.assertEqual(len(workflow.reportability_owner.calls), len(groups))

    def test_real_taxonomy_suppresses_provider_for_unresolved_category_through_bridge(self) -> None:
        class CountingProvider:
            def __init__(self):
                self.calls = []

            def __call__(self, request):
                self.calls.append(request)
                raise AssertionError("unresolved Category must suppress Taxonomy provider")

        def unresolved_factory(group, records, call_number):
            return CategoryResult(
                CategoryState.CATEGORY_UNRESOLVED,
                event_id=group.event_id,
                classification_reason=CategoryState.CATEGORY_UNRESOLVED.value,
                category_resolution_reason="NO_CATEGORY_DEFINING_ACTION",
                provenance={"decision_basis": "fixture"},
            )

        provider = CountingProvider()
        reportability = RecordingDownstreamReportability()
        workflow = ReportWorkflow(
            Taxonomy(proposal_provider=provider),
            reportability=reportability,
        )
        result = self._app(
            FakeProvider(),
            classifier=RecordingClassifier(result_factory=unresolved_factory),
            scope_classifier=RecordingScopeClassifier(),
            temporal_rule=RecordingTemporalRule(),
            event_identity=RecordingEventIdentity(),
            report_workflow=workflow,
        ).run("selected")

        self.assertEqual(provider.calls, [])
        self.assertEqual(reportability.calls, [])
        self.assertEqual(len(result.downstream_results), 1)
        self.assertEqual(
            result.downstream_results[0].taxonomy_result.taxonomy_state,
            TaxonomyState.NOT_EVALUATED,
        )

    def test_report_application_aggregate_rejects_raw_and_mixed_downstream_results(self) -> None:
        result = self._app(
            MultiResultProvider(),
            scope_classifier=RecordingScopeClassifier(),
            temporal_rule=RecordingTemporalRule(),
            event_identity=RecordingEventIdentity(),
            report_workflow=RecordingDownstreamWorkflow(),
        ).run("selected")
        raw_decision = result.downstream_results[0].decision

        with self.assertRaises(TypeError):
            replace(result, downstream_results=(raw_decision,))
        with self.assertRaises(TypeError):
            replace(
                result,
                downstream_results=(result.downstream_results[0], raw_decision),
            )

    def test_report_application_aggregate_accepts_complete_report_workflow_results(self) -> None:
        result = self._app(
            MultiResultProvider(),
            scope_classifier=RecordingScopeClassifier(),
            temporal_rule=RecordingTemporalRule(),
            event_identity=RecordingEventIdentity(),
            report_workflow=RecordingDownstreamWorkflow(),
        ).run("selected")

        accepted = replace(result, downstream_results=tuple(result.downstream_results))
        self.assertEqual(len(accepted.downstream_results), len(accepted.event_identity_run.groups))
        self.assertTrue(all(
            actual is expected
            for actual, expected in zip(
                accepted.downstream_results, result.downstream_results, strict=True
            )
        ))

    def test_formal_factory_injects_and_runs_the_complete_report_workflow(self) -> None:
        registry = _registry()
        provider = MultiResultProvider()
        event_identity = RecordingEventIdentity()
        classifier = RecordingClassifier()
        workflow = RecordingDownstreamWorkflow()
        ordering = RecordingOrdering()
        application = build_report_application(
            registry,
            SearchExecutor({SearchProviderId.GOOGLE_NEWS_RSS: provider}),
            planner=FixturePlanner(registry, _fixture_plan()),
            evidence_service=RecordingEvidenceService(),
            scope_classifier=RecordingScopeClassifier(),
            temporal_rule=RecordingTemporalRule(),
            event_identity=event_identity,
            classifier=classifier,
            report_workflow=workflow,
            ordering=ordering,
            report_service=ReportService(),
        )

        self.assertIs(application.report_workflow, workflow)
        self.assertIs(application.ordering, ordering)
        result = application.run(
            "selected",
            period_start="2026-09-12",
            period_end="2026-09-18",
        )

        self.assertEqual(len(workflow.calls), 1)
        self.assertEqual(len(result.downstream_results), len(result.event_identity_run.groups))
        self.assertTrue(all(
            isinstance(item, ReportWorkflowResult) for item in result.downstream_results
        ))
        self.assertEqual(ordering.calls, [()])
        self.assertEqual(result.ordered_results, ())
        self.assertEqual(result.formal_metadata, ())
        self.assertEqual(len(event_identity.calls), 1)
        self.assertEqual(len(classifier.calls), len(result.event_identity_run.groups))

    def test_formal_factory_rejects_missing_or_taxonomy_only_workflow(self) -> None:
        registry = _registry()
        executor = SearchExecutor({})
        with self.assertRaises(TypeError):
            build_report_application(
                registry,
                executor,
                evidence_service=RecordingEvidenceService(),
            )
        with self.assertRaises(ValueError):
            build_report_application(
                registry,
                executor,
                evidence_service=RecordingEvidenceService(),
                report_workflow=ReportWorkflow(RecordingDownstreamTaxonomy()),
                ordering=RecordingOrdering(),
                report_service=ReportService(),
            )

    def test_formal_factory_rejects_only_missing_ordering(self) -> None:
        with self.assertRaises(TypeError):
            build_report_application(
                _registry(),
                SearchExecutor({}),
                evidence_service=RecordingEvidenceService(),
                report_workflow=RecordingDownstreamWorkflow(),
                report_service=ReportService(),
            )

    def test_formal_factory_requires_report_service(self) -> None:
        kwargs = dict(
            evidence_service=RecordingEvidenceService(),
            report_workflow=RecordingDownstreamWorkflow(),
            ordering=RecordingOrdering(),
        )
        with self.assertRaises(TypeError):
            build_report_application(_registry(), SearchExecutor({}), **kwargs)
        with self.assertRaises(TypeError):
            build_report_application(
                _registry(),
                SearchExecutor({}),
                report_service=object(),
                **kwargs,
            )

    def test_generic_application_without_ordering_preserves_none_surface(self) -> None:
        result = self._app(FakeProvider()).run("selected")
        self.assertIsNone(result.ordered_results)
        self.assertIsNone(result.formal_metadata)

    def test_ordering_projects_all_reportable_results_once_and_preserves_references(self) -> None:
        ordering = RecordingOrdering(reverse=True)
        workflow = RecordingDownstreamWorkflow(reportable=True)
        result = self._app(
            MultiResultProvider(),
            scope_classifier=RecordingScopeClassifier(),
            temporal_rule=RecordingTemporalRule(default_date=date(2026, 9, 18)),
            event_identity=RecordingEventIdentity(),
            classifier=RecordingClassifier(),
            report_workflow=workflow,
            ordering=ordering,
        ).run("selected")

        self.assertEqual(len(ordering.calls), 1)
        self.assertEqual(ordering.calls[0], result.downstream_results)
        self.assertEqual(
            tuple(result.ordered_results),
            tuple(reversed(result.downstream_results)),
        )
        self.assertTrue(all(
            any(ordered is source for source in result.downstream_results)
            for ordered in result.ordered_results
        ))

    def test_completed_ordering_without_report_service_leaves_formal_metadata_none(self) -> None:
        result = self._reportable_run(RecordingOrdering())
        self.assertIsNotNone(result.ordered_results)
        self.assertIsNone(result.formal_metadata)

    def test_zero_reportable_population_invokes_ordering_once_with_empty_tuple(self) -> None:
        ordering = RecordingOrdering()
        result = self._app(
            ZeroResultProvider(),
            report_workflow=RecordingDownstreamWorkflow(),
            ordering=ordering,
        ).run("selected")
        self.assertEqual(ordering.calls, [()])
        self.assertEqual(result.ordered_results, ())

    def test_partial_downstream_failure_never_reaches_ordering(self) -> None:
        ordering = RecordingOrdering()
        with self.assertRaises(RuntimeError):
            self._app(
                MultiResultProvider(),
                scope_classifier=RecordingScopeClassifier(),
                temporal_rule=RecordingTemporalRule(default_date=date(2026, 9, 18)),
                event_identity=RecordingEventIdentity(),
                report_workflow=RecordingDownstreamWorkflow(fail_on_call=2),
                ordering=ordering,
            ).run("selected")
        self.assertEqual(ordering.calls, [])

    def test_ordering_failure_propagates_without_fallback(self) -> None:
        ordering_error = RuntimeError("ordering failure")
        with self.assertRaisesRegex(RuntimeError, "ordering failure"):
            self._app(
                FakeProvider(),
                report_workflow=RecordingDownstreamWorkflow(),
                ordering=RecordingOrdering(error=ordering_error),
            ).run("selected")

    def test_configured_report_service_runs_after_ordering(self) -> None:
        report_service = RecordingReportService()
        result = self._app(
            ZeroResultProvider(),
            report_workflow=RecordingDownstreamWorkflow(),
            ordering=RecordingOrdering(),
            report_service=report_service,
        ).run("selected")
        self.assertEqual(len(report_service.calls), 1)
        self.assertEqual(report_service.calls[0], result.ordered_results)
        self.assertEqual(result.formal_metadata, ())

    def test_nonzero_formal_projection_preserves_values_and_runs_after_ordering_once(self) -> None:
        trace = []
        ordering = RecordingOrdering(trace=trace)
        result, report_service = self._formal_application_run(trace=trace, ordering=ordering)

        self.assertIsNotNone(result.ordered_results)
        self.assertGreater(len(result.ordered_results), 0)
        self.assertEqual(len(result.formal_metadata), len(result.ordered_results))
        self.assertEqual(
            tuple(item.event_id for item in result.formal_metadata),
            tuple(item.event_group.event_id for item in result.ordered_results),
        )
        metadata = result.formal_metadata[0]
        self.assertEqual(metadata.country, "Taiwan")
        self.assertEqual(metadata.transit_system_name, "Metro")
        self.assertEqual(metadata.display_date, "2026-09-18")
        self.assertEqual(metadata.source_display, "www.news.example.com")
        self.assertEqual(trace, ["ordering", "report_service"])
        self.assertEqual(len(ordering.calls), 1)
        self.assertEqual(len(ordering.returned_results), 1)
        self.assertEqual(len(report_service.calls), 1)
        self.assertIs(report_service.calls[0], ordering.returned_results[0])
        self.assertIs(result.ordered_results, ordering.returned_results[0])

    def test_formal_metadata_requires_completed_ordering(self) -> None:
        result, _ = self._formal_application_run()
        with self.assertRaises(ValueError):
            replace(result, ordered_results=None, formal_metadata=result.formal_metadata)

    def test_formal_metadata_rejects_cardinality_mismatch(self) -> None:
        result, _ = self._formal_application_run()
        with self.assertRaises(ValueError):
            replace(result, formal_metadata=())

    def test_formal_metadata_rejects_event_order_mismatch(self) -> None:
        result, _ = self._formal_application_run(provider=TwoFormalResultProvider())
        first, second = result.formal_metadata
        with self.assertRaises(ValueError):
            replace(result, formal_metadata=(second, first))

    def test_formal_metadata_rejects_duplicate_event_ids(self) -> None:
        result, _ = self._formal_application_run(provider=TwoFormalResultProvider())
        first, second = result.formal_metadata
        duplicate_second = replace(second, event_id=first.event_id)
        with self.assertRaisesRegex(ValueError, "preserve ordered event IDs"):
            replace(result, formal_metadata=(first, duplicate_second))

    def test_formal_metadata_failure_propagates_without_downgrade(self) -> None:
        with self.assertRaises(FormalMetadataFailure) as context:
            self._app(
                MultiResultProvider(),
                scope_classifier=RecordingScopeClassifier(),
                temporal_rule=RecordingTemporalRule(default_date=date(2026, 9, 18)),
                event_identity=RecordingEventIdentity(),
                classifier=RecordingClassifier(),
                report_workflow=RecordingDownstreamWorkflow(reportable=True),
                ordering=RecordingOrdering(),
                report_service=ReportService(),
            ).run("selected")
        self.assertEqual(context.exception.reason, FormalMetadataFailureReason.MISSING_COUNTRY)

    def test_ordering_output_validation_rejects_all_malformed_shapes(self) -> None:
        baseline = self._reportable_run(RecordingOrdering())
        first, second = baseline.downstream_results
        group = replace(first.event_group, event_id="foreign-event")
        foreign = ReportWorkflowResult(
            replace(
                first.decision,
                event_group=group,
                category_result=replace(first.category_result, event_id="foreign-event"),
                taxonomy_result=replace(first.taxonomy_result, event_id="foreign-event"),
            ),
            replace(first.reportability_result, event_id="foreign-event"),
        )
        cases = (
            ("non-tuple", lambda events: None, TypeError),
            ("wrong-item", lambda events: (object(),), TypeError),
            ("too-few", lambda events: events[:-1], ValueError),
            ("duplicate", lambda events: (events[0], events[0]), ValueError),
            ("foreign", lambda events: (events[0], foreign), ValueError),
            ("reconstructed", lambda events: (events[0], replace(events[1])), ValueError),
        )
        for label, factory, expected_error in cases:
            with self.subTest(label=label):
                ordering = BrokenOrdering(factory)
                with self.assertRaises(expected_error):
                    self._reportable_run(ordering)
                self.assertEqual(len(ordering.calls), 1)

    def test_mixed_reportability_projection_passes_only_eligible_references(self) -> None:
        def classify(group, records, call_number):
            if call_number == 3:
                return CategoryResult(
                    CategoryState.CATEGORY_UNRESOLVED,
                    event_id=group.event_id,
                    classification_reason=CategoryState.CATEGORY_UNRESOLVED.value,
                    category_resolution_reason="NO_CATEGORY_DEFINING_ACTION",
                    provenance={"decision_basis": "fixture"},
                )
            return _assigned_category(group)

        ordering = RecordingOrdering()
        result = self._reportable_run(
            ordering,
            provider=TripleResultProvider(),
            workflow=RecordingDownstreamWorkflow(reportable_on_calls={1}),
            classifier=RecordingClassifier(result_factory=classify),
        )

        self.assertEqual(len(ordering.calls), 1)
        self.assertEqual(len(ordering.calls[0]), 1)
        self.assertIs(ordering.calls[0][0], result.downstream_results[0])
        self.assertIs(result.downstream_results[1].reportability_state, ReportabilityState.NOT_REPORTABLE)
        self.assertEqual(result.downstream_results[2].reportability_state, "NOT_EVALUATED")
        self.assertEqual(result.ordered_results, (result.downstream_results[0],))

    def test_late_reportability_failure_blocks_configured_ordering(self) -> None:
        ordering = RecordingOrdering()
        with self.assertRaises(RuntimeError):
            self._reportable_run(
                ordering,
                workflow=RecordingDownstreamWorkflow(fail_reportability_on_call=2),
            )
        self.assertEqual(ordering.calls, [])

    def test_raw_and_mixed_workflow_outputs_fail_before_configured_ordering(self) -> None:
        for mode in ("raw", "mixed"):
            with self.subTest(mode=mode):
                ordering = RecordingOrdering()
                with self.assertRaises(TypeError):
                    self._app(
                        MultiResultProvider(),
                        scope_classifier=RecordingScopeClassifier(),
                        temporal_rule=RecordingTemporalRule(default_date=date(2026, 9, 18)),
                        event_identity=RecordingEventIdentity(),
                        classifier=RecordingClassifier(),
                        report_workflow=MalformedDownstreamWorkflow(mode),
                        ordering=ordering,
                    ).run("selected")
                self.assertEqual(ordering.calls, [])

    def test_ordered_results_aggregate_rejects_invalid_populations(self) -> None:
        result = self._reportable_run(RecordingOrdering())
        first, second = result.downstream_results

        with self.assertRaises(ValueError):
            replace(result, downstream_results=None, ordered_results=())
        with self.assertRaises(ValueError):
            replace(result, ordered_results=())
        with self.assertRaises(ValueError):
            replace(result, ordered_results=(first, first))
        with self.assertRaises(ValueError):
            replace(result, ordered_results=(first, replace(second)))

    def test_downstream_bridge_passes_category_unresolved_unchanged(self) -> None:
        unresolved_results = []

        def unresolved_factory(group, records, call_number):
            unresolved = CategoryResult(
                CategoryState.CATEGORY_UNRESOLVED,
                event_id=group.event_id,
                classification_reason=CategoryState.CATEGORY_UNRESOLVED.value,
                category_resolution_reason="NO_CATEGORY_DEFINING_ACTION",
                provenance={"decision_basis": "fixture"},
            )
            unresolved_results.append(unresolved)
            return unresolved

        classifier = RecordingClassifier(
            result_factory=unresolved_factory
        )
        workflow = RecordingDownstreamWorkflow()
        result = self._app(
            FakeProvider(),
            classifier=classifier,
            scope_classifier=RecordingScopeClassifier(),
            temporal_rule=RecordingTemporalRule(),
            event_identity=RecordingEventIdentity(),
            report_workflow=workflow,
        ).run("selected")

        unresolved = unresolved_results[0]
        self.assertIs(result.category_results[0], unresolved)
        self.assertIs(workflow.calls[0][2][0], unresolved)
        self.assertIs(result.downstream_results[0].decision.category_result, unresolved)
        self.assertEqual(
            result.downstream_results[0].taxonomy_result.taxonomy_state,
            TaxonomyState.NOT_EVALUATED,
        )
        self.assertEqual(workflow.taxonomy_owner.calls[0][2], unresolved)
        self.assertEqual(workflow.reportability_owner.calls, [])

    def test_downstream_bridge_skips_empty_population(self) -> None:
        workflow = RecordingDownstreamWorkflow()
        result = self._app(
            ZeroResultProvider(),
            scope_classifier=RecordingScopeClassifier(),
            temporal_rule=RecordingTemporalRule(),
            event_identity=RecordingEventIdentity(),
            report_workflow=workflow,
        ).run("selected")

        self.assertEqual(result.event_identity_run.groups, ())
        self.assertEqual(result.category_results, ())
        self.assertEqual(result.downstream_results, ())
        self.assertEqual(workflow.calls, [])
        self.assertEqual(workflow.taxonomy_owner.calls, [])
        self.assertEqual(workflow.reportability_owner.calls, [])

    def test_first_full_downstream_success_then_second_failure_exposes_no_partial_result(self) -> None:
        workflow = RecordingDownstreamWorkflow(fail_reportability_on_call=2)
        with self.assertRaises(RuntimeError):
            self._app(
                MultiResultProvider(),
                scope_classifier=RecordingScopeClassifier(),
                temporal_rule=RecordingTemporalRule(),
                event_identity=RecordingEventIdentity(),
                classifier=RecordingClassifier(),
                report_workflow=workflow,
            ).run("selected")

        self.assertEqual(len(workflow.taxonomy_owner.calls), 2)
        self.assertEqual(len(workflow.reportability_owner.calls), 2)
        self.assertEqual(len(workflow.reportability_owner.successful_event_ids), 1)
        self.assertEqual(
            workflow.reportability_owner.successful_event_ids,
            [workflow.taxonomy_owner.calls[0][0].event_id],
        )

    def test_category_unresolved_is_preserved_and_other_groups_continue(self) -> None:
        unresolved_provenance = {
            "decision_basis": "constrained_semantic_helper",
            "source_candidate_ids": ("candidate-https-example.test-first",),
        }

        def result_factory(group, records, call_number):
            if call_number == 1:
                return CategoryResult(
                    CategoryState.CATEGORY_UNRESOLVED,
                    event_id=group.event_id,
                    classification_reason=CategoryState.CATEGORY_UNRESOLVED.value,
                    category_resolution_reason="NO_CATEGORY_DEFINING_ACTION",
                    provenance=unresolved_provenance,
                )
            return _assigned_category(group)

        classifier = RecordingClassifier(result_factory=result_factory)
        result = self._app(
            MultiResultProvider(),
            classifier=classifier,
            scope_classifier=RecordingScopeClassifier(),
            temporal_rule=RecordingTemporalRule(),
            event_identity=RecordingEventIdentity(),
        ).run("selected")

        self.assertEqual(len(classifier.calls), 2)
        self.assertIs(result.category_results[0], classifier.results[0])
        self.assertIs(result.category_results[0].category_state, CategoryState.CATEGORY_UNRESOLVED)
        self.assertEqual(
            result.category_results[0].category_resolution_reason.value,
            "NO_CATEGORY_DEFINING_ACTION",
        )
        self.assertEqual(result.category_results[0].provenance, unresolved_provenance)
        self.assertIs(result.category_results[1].category_state, CategoryState.CATEGORY_ASSIGNED)

    def test_invoked_not_evaluated_category_fails_closed(self) -> None:
        classifier = RecordingClassifier(
            result_factory=lambda group, records, call_number: CategoryResult.not_evaluated(
                event_id=group.event_id
            )
        )
        with self.assertRaises(ValueError):
            self._app(
                FakeProvider(),
                classifier=classifier,
                scope_classifier=RecordingScopeClassifier(),
                temporal_rule=RecordingTemporalRule(),
                event_identity=RecordingEventIdentity(),
            ).run("selected")

    def test_invalid_category_result_type_fails_closed(self) -> None:
        classifier = RecordingClassifier(
            result_factory=lambda group, records, call_number: object()
        )
        with self.assertRaises(TypeError):
            self._app(
                FakeProvider(),
                classifier=classifier,
                scope_classifier=RecordingScopeClassifier(),
                temporal_rule=RecordingTemporalRule(),
                event_identity=RecordingEventIdentity(),
            ).run("selected")

    def test_category_event_id_mismatch_fails_closed(self) -> None:
        def mismatched_result(group, records, call_number):
            foreign_id = "foreign-event"
            foreign_group = EventGroup(
                foreign_id,
                group.member_candidate_ids,
                group.canonical_candidate_id,
                (),
            )
            return _assigned_category(foreign_group)

        classifier = RecordingClassifier(result_factory=mismatched_result)
        with self.assertRaises(ValueError):
            self._app(
                FakeProvider(),
                classifier=classifier,
                scope_classifier=RecordingScopeClassifier(),
                temporal_rule=RecordingTemporalRule(),
                event_identity=RecordingEventIdentity(),
            ).run("selected")

    def test_partial_category_success_is_not_exposed_on_exception(self) -> None:
        classifier = RecordingClassifier(error_after=1)
        with self.assertRaises(RuntimeError):
            self._app(
                MultiResultProvider(),
                classifier=classifier,
                scope_classifier=RecordingScopeClassifier(),
                temporal_rule=RecordingTemporalRule(),
                event_identity=RecordingEventIdentity(),
            ).run("selected")
        self.assertEqual(len(classifier.calls), 2)
        self.assertEqual(classifier.results[0].category_state, CategoryState.CATEGORY_ASSIGNED)

    def test_zero_event_groups_complete_category_with_zero_calls(self) -> None:
        class ZeroProvider(FakeProvider):
            def execute(self, item):
                self.calls.append(item.plan_item_id)
                return SearchAttemptResult(item.plan_item_id, SearchTerminalStatus.SUCCESS_ZERO_RESULTS)

        classifier = RecordingClassifier()
        result = self._app(
            ZeroProvider(),
            classifier=classifier,
            scope_classifier=RecordingScopeClassifier(),
            temporal_rule=RecordingTemporalRule(),
            event_identity=RecordingEventIdentity(),
        ).run("selected")

        self.assertEqual(result.event_identity_run.groups, ())
        self.assertEqual(classifier.calls, [])
        self.assertEqual(result.category_results, ())

    def test_category_member_projection_rejects_missing_and_foreign_group_members(self) -> None:
        result = self._app(
            MultiResultProvider(),
            classifier=RecordingClassifier(),
            scope_classifier=RecordingScopeClassifier(),
            temporal_rule=RecordingTemporalRule(),
            event_identity=RecordingEventIdentity(merge=True),
        ).run("selected")
        group = result.event_identity_run.groups[0]
        with self.assertRaises(ValueError):
            replace(
                result,
                event_identity_run=EventIdentityRun(
                    (EventGroup("missing", (group.member_candidate_ids[0],), group.canonical_candidate_id, ()),)
                ),
            )
        with self.assertRaises(ValueError):
            replace(
                result,
                event_identity_run=EventIdentityRun(
                    (EventGroup("foreign", ("foreign",), "foreign", ()),)
                ),
            )

    def test_category_admission_rejects_malformed_groups_before_classifier(self) -> None:
        class MalformedContainerIdentity(RecordingEventIdentity):
            def evaluate(self, records):
                valid_run = super().evaluate(records)
                return EventIdentityRun(list(valid_run.groups))

        semantic_helper_calls = []

        class CountingClassifier(Classifier):
            def __init__(self):
                super().__init__(
                    semantic_helper=lambda request: semantic_helper_calls.append(request)
                )
                self.calls = []

            def classify(self, event_group, records):
                self.calls.append((event_group, tuple(records)))
                return super().classify(event_group, records)

        classifier = CountingClassifier()
        with self.assertRaises(TypeError):
            self._app(
                MultiResultProvider(),
                classifier=classifier,
                scope_classifier=RecordingScopeClassifier(),
                temporal_rule=RecordingTemporalRule(),
                event_identity=MalformedContainerIdentity(),
            ).run("selected")
        self.assertEqual(classifier.calls, [])
        self.assertEqual(semantic_helper_calls, [])

    def test_category_admission_rejects_malformed_group_element_before_classifier(self) -> None:
        class MalformedElementIdentity(RecordingEventIdentity):
            def evaluate(self, records):
                super().evaluate(records)
                return EventIdentityRun((object(),))

        semantic_helper_calls = []

        class CountingClassifier(Classifier):
            def __init__(self):
                super().__init__(
                    semantic_helper=lambda request: semantic_helper_calls.append(request)
                )
                self.calls = []

            def classify(self, event_group, records):
                self.calls.append((event_group, tuple(records)))
                return super().classify(event_group, records)

        classifier = CountingClassifier()
        with self.assertRaises(TypeError):
            self._app(
                MultiResultProvider(),
                classifier=classifier,
                scope_classifier=RecordingScopeClassifier(),
                temporal_rule=RecordingTemporalRule(),
                event_identity=MalformedElementIdentity(),
            ).run("selected")
        self.assertEqual(classifier.calls, [])
        self.assertEqual(semantic_helper_calls, [])

    def test_category_result_aggregate_rejects_duplicate_extra_foreign_and_wrong_order(self) -> None:
        result = self._app(
            MultiResultProvider(),
            classifier=RecordingClassifier(),
            scope_classifier=RecordingScopeClassifier(),
            temporal_rule=RecordingTemporalRule(),
            event_identity=RecordingEventIdentity(),
        ).run("selected")
        first, second = result.category_results

        with self.assertRaises(ValueError):
            replace(result, category_results=(first, first))
        with self.assertRaises(ValueError):
            replace(result, category_results=(first, second, first))
        with self.assertRaises(ValueError):
            replace(result, category_results=(replace(first, event_id="foreign"), second))
        with self.assertRaises(ValueError):
            replace(result, category_results=(second, first))

    def test_category_result_aggregate_invariants_are_mechanical(self) -> None:
        result = self._app(
            FakeProvider(),
            classifier=RecordingClassifier(),
            scope_classifier=RecordingScopeClassifier(),
            temporal_rule=RecordingTemporalRule(),
            event_identity=RecordingEventIdentity(),
        ).run("selected")
        category_result = result.category_results[0]

        with self.assertRaises(ValueError):
            replace(result, category_results=())
        with self.assertRaises(ValueError):
            replace(
                result,
                category_results=(
                    _assigned_category(
                        EventGroup(
                            "foreign",
                            (result.event_identity_records[0].candidate.candidate_id,),
                            result.event_identity_records[0].candidate.candidate_id,
                            (),
                        )
                    ),
                ),
            )
        with self.assertRaises(ValueError):
            replace(
                result,
                category_results=(CategoryResult.not_evaluated(event_id=category_result.event_id),),
            )
        with self.assertRaises(ValueError):
            replace(
                result,
                temporal_results=None,
                event_identity_records=None,
                event_identity_run=None,
                category_results=(category_result,),
            )

    def test_search_intent_does_not_change_category_result(self) -> None:
        first = self._app(
            FakeProvider(),
            classifier=RecordingClassifier(),
            scope_classifier=RecordingScopeClassifier(),
            temporal_rule=RecordingTemporalRule(),
            event_identity=RecordingEventIdentity(),
        ).run("selected", intents=(DiscoveryIntent.OPERATIONS,))
        second = self._app(
            FakeProvider(),
            classifier=RecordingClassifier(),
            scope_classifier=RecordingScopeClassifier(),
            temporal_rule=RecordingTemporalRule(),
            event_identity=RecordingEventIdentity(),
        ).run("selected", intents=(DiscoveryIntent.PROCUREMENT,))
        self.assertEqual(first.category_results, second.category_results)

    def test_category_stage_does_not_invoke_taxonomy_or_construct_decision_record(self) -> None:
        result = self._app(
            FakeProvider(),
            classifier=RecordingClassifier(),
            scope_classifier=RecordingScopeClassifier(),
            temporal_rule=RecordingTemporalRule(),
            event_identity=RecordingEventIdentity(),
        ).run("selected")
        self.assertIsNotNone(result.category_results)
        self.assertFalse(hasattr(result, "decision"))

    def test_scope_invalid_result_is_an_application_contract_failure(self) -> None:
        with self.assertRaises(TypeError):
            self._app(
                FakeProvider(),
                scope_classifier=RecordingScopeClassifier(invalid={}),
                temporal_rule=RecordingTemporalRule(),
                event_identity=RecordingEventIdentity(),
            ).run("selected")

    def test_event_identity_invalid_result_is_an_application_contract_failure(self) -> None:
        with self.assertRaises(TypeError):
            self._app(
                FakeProvider(),
                scope_classifier=RecordingScopeClassifier(),
                temporal_rule=RecordingTemporalRule(),
                event_identity=RecordingEventIdentity(invalid={}),
            ).run("selected")

    def test_scope_exception_does_not_expose_partial_result(self) -> None:
        error = RuntimeError("scope failure")

        class FailOnSecondScope(RecordingScopeClassifier):
            def __init__(self):
                super().__init__()
                self.successful_results = []

            def classify(self, evidence, *, candidate_title=""):
                if len(self.calls) == 0:
                    result = super().classify(evidence, candidate_title=candidate_title)
                    self.successful_results.append(result)
                    return result
                self.calls.append((evidence, candidate_title))
                raise error

        scope = FailOnSecondScope()
        with self.assertRaises(RuntimeError):
            self._app(
                MultiResultProvider(),
                scope_classifier=scope,
                temporal_rule=RecordingTemporalRule(),
                event_identity=RecordingEventIdentity(),
            ).run("selected")
        self.assertEqual(len(scope.calls), 2)
        self.assertEqual(len(scope.successful_results), 1)
        self.assertIsInstance(scope.successful_results[0], ScopeResult)

    def test_temporal_exception_does_not_expose_partial_result(self) -> None:
        error = RuntimeError("temporal failure")

        class FailOnSecondTemporal(RecordingTemporalRule):
            def __init__(self):
                super().__init__()
                self.successful_results = []

            def evaluate(self, candidate_id, source_date_facts, period_start, period_end, **kwargs):
                if len(self.calls) == 0:
                    result = super().evaluate(
                        candidate_id, source_date_facts, period_start, period_end, **kwargs
                    )
                    self.successful_results.append(result)
                    return result
                self.calls.append((candidate_id, tuple(source_date_facts), period_start, period_end, kwargs))
                raise error

        temporal = FailOnSecondTemporal()
        identity = RecordingEventIdentity()
        with self.assertRaises(RuntimeError):
            self._app(
                MultiResultProvider(),
                scope_classifier=RecordingScopeClassifier(),
                temporal_rule=temporal,
                event_identity=identity,
            ).run("selected")
        self.assertEqual(len(temporal.calls), 2)
        self.assertEqual(len(temporal.successful_results), 1)
        self.assertIsInstance(temporal.successful_results[0], TemporalResult)
        self.assertEqual(identity.calls, [])

    def test_event_identity_exception_does_not_expose_partial_result(self) -> None:
        error = RuntimeError("identity failure")
        with self.assertRaises(RuntimeError):
            self._app(
                FakeProvider(),
                scope_classifier=RecordingScopeClassifier(),
                temporal_rule=RecordingTemporalRule(),
                event_identity=RecordingEventIdentity(error=error),
            ).run("selected")

    def test_zero_date_valid_population_is_completed_and_calls_identity_once(self) -> None:
        identity = RecordingEventIdentity()
        result = self._app(
            FakeProvider(),
            scope_classifier=RecordingScopeClassifier(),
            temporal_rule=RecordingTemporalRule(date_valid=False),
            event_identity=identity,
        ).run("selected")

        self.assertEqual(len(identity.calls), 1)
        self.assertEqual(identity.calls[0], ())
        self.assertEqual(result.event_identity_records, ())
        self.assertIsNotNone(result.event_identity_run)

    def test_invalid_report_period_propagates_from_temporal_owner(self) -> None:
        identity = RecordingEventIdentity()
        with self.assertRaises(ValueError):
            self._app(
                FakeProvider(),
                scope_classifier=RecordingScopeClassifier(),
                temporal_rule=TemporalRule(),
                event_identity=identity,
            ).run("selected", period_start="2026-09-19", period_end="2026-09-12")
        self.assertEqual(identity.calls, [])

    def test_invalid_report_period_aborts_independently_of_population(self) -> None:
        class ZeroProvider(FakeProvider):
            def execute(self, item):
                self.calls.append(item.plan_item_id)
                return SearchAttemptResult(item.plan_item_id, SearchTerminalStatus.SUCCESS_ZERO_RESULTS)

        candidate_id = candidate_id_for_url("https://example.test/item")
        invalid_periods = (
            ("not-a-date", "2026-09-18"),
            ("2026-09-19", "2026-09-12"),
        )
        for period_start, period_end in invalid_periods:
            for population in ("in_scope", "out_of_scope", "zero_ready", "zero_normalized"):
                scope = RecordingScopeClassifier(
                    out_of_scope={candidate_id} if population == "out_of_scope" else ()
                )
                evidence = RecordingEvidenceService(
                    rejected_ids={candidate_id} if population == "zero_ready" else ()
                )
                temporal = RecordingTemporalRule()
                identity = RecordingEventIdentity()
                provider = ZeroProvider() if population == "zero_normalized" else FakeProvider()
                with self.assertRaises(ValueError):
                    self._app(
                        provider,
                        evidence_service=evidence,
                        scope_classifier=scope,
                        temporal_rule=temporal,
                        event_identity=identity,
                    ).run(
                        "selected",
                        period_start=period_start,
                        period_end=period_end,
                    )
                self.assertEqual(scope.calls, [], (period_start, period_end, population))
                self.assertEqual(temporal.calls, [], (period_start, period_end, population))
                self.assertEqual(identity.calls, [], (period_start, period_end, population))

    def test_non_boolean_temporal_result_aborts_before_event_identity(self) -> None:
        for value in ("false", 1):
            identity = RecordingEventIdentity()
            with self.assertRaises(TypeError):
                self._app(
                    FakeProvider(),
                    scope_classifier=RecordingScopeClassifier(),
                    temporal_rule=RecordingTemporalRule(date_valid=value),
                    event_identity=identity,
                ).run("selected")
            self.assertEqual(identity.calls, [], value)

    def test_scope_candidate_id_mismatch_aborts_before_temporal(self) -> None:
        temporal = RecordingTemporalRule()
        identity = RecordingEventIdentity()
        with self.assertRaises(ValueError):
            self._app(
                FakeProvider(),
                scope_classifier=RecordingScopeClassifier(
                    invalid=ScopeResult("foreign", ScopeState.IN_SCOPE)
                ),
                temporal_rule=temporal,
                event_identity=identity,
            ).run("selected")
        self.assertEqual(temporal.calls, [])
        self.assertEqual(identity.calls, [])

    def test_temporal_candidate_id_mismatch_aborts_before_event_identity(self) -> None:
        identity = RecordingEventIdentity()
        with self.assertRaises(ValueError):
            self._app(
                FakeProvider(),
                scope_classifier=RecordingScopeClassifier(),
                temporal_rule=RecordingTemporalRule(
                    invalid=TemporalResult("foreign", True)
                ),
                event_identity=identity,
            ).run("selected")
        self.assertEqual(identity.calls, [])

    def test_missing_event_member_is_rejected(self) -> None:
        class MissingMemberIdentity(RecordingEventIdentity):
            def evaluate(self, records):
                records = tuple(records)
                self.calls.append(records)
                first = records[0].candidate.candidate_id
                return EventIdentityRun((EventGroup("evt-one", (first,), first, ()),))

        with self.assertRaises(ValueError):
            self._app(
                MultiResultProvider(),
                scope_classifier=RecordingScopeClassifier(),
                temporal_rule=RecordingTemporalRule(),
                event_identity=MissingMemberIdentity(),
            ).run("selected")

    def test_unknown_event_member_is_rejected(self) -> None:
        class UnknownMemberIdentity(RecordingEventIdentity):
            def evaluate(self, records):
                records = tuple(records)
                self.calls.append(records)
                first = records[0].candidate.candidate_id
                members = tuple(sorted((first, "foreign")))
                return EventIdentityRun((EventGroup("evt-unknown", members, first, ()),))

        with self.assertRaises(ValueError):
            self._app(
                MultiResultProvider(),
                scope_classifier=RecordingScopeClassifier(),
                temporal_rule=RecordingTemporalRule(),
                event_identity=UnknownMemberIdentity(),
            ).run("selected")

    def test_overlapping_event_groups_are_rejected_mechanically(self) -> None:
        class OverlappingIdentity(RecordingEventIdentity):
            def evaluate(self, records):
                records = tuple(records)
                self.calls.append(records)
                first = records[0].candidate.candidate_id
                second = records[-1].candidate.candidate_id
                return EventIdentityRun(
                    (
                        EventGroup("evt-a", (first,), first, ()),
                        EventGroup("evt-b", (first, second), first, ()),
                    )
                )

        with self.assertRaises(ValueError):
            self._app(
                MultiResultProvider(),
                scope_classifier=RecordingScopeClassifier(),
                temporal_rule=RecordingTemporalRule(),
                event_identity=OverlappingIdentity(),
            ).run("selected")

    def test_downstream_ready_remains_search_side_only_after_new_stages(self) -> None:
        result = self._app(
            FakeProvider(),
            scope_classifier=RecordingScopeClassifier(),
            temporal_rule=RecordingTemporalRule(),
            event_identity=RecordingEventIdentity(),
        ).run("selected")
        self.assertTrue(result.downstream_ready)
