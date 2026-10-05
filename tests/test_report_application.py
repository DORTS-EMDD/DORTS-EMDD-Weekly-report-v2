from __future__ import annotations

from dataclasses import replace
from unittest import TestCase

from src.weekly_report.candidate_normalizer import CandidateNormalizationError, CandidateNormalizer
from src.weekly_report.contracts import (
    CandidateNormalizationFailure,
    DiscoveryIntent,
    DiscoveryResult,
    EvidenceResult,
    EvidenceState,
    EventGroup,
    EventIdentityRun,
    GoogleNewsRssEncoding,
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
    TemporalResult,
    TemporalDiagnostic,
    candidate_id_for_url,
)
from src.weekly_report.region_registry import RegionRegistry
from src.weekly_report.report_application import ReportApplication
from src.weekly_report.evidence_service import EvidenceService
from src.weekly_report.search_executor import SearchExecutor
from src.weekly_report.search_planner import SearchPlanner
from src.weekly_report.scope_classifier import ScopeClassifier
from src.weekly_report.temporal_rule import TemporalRule
from src.weekly_report.event_identity import EventIdentity


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
    def __init__(self, *, invalid=None, error=None, date_valid=True):
        self.calls = []
        self.invalid = invalid
        self.error = error
        self.date_valid = date_valid

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
        )

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
