from __future__ import annotations

from dataclasses import replace
from unittest import TestCase

from src.weekly_report.candidate_normalizer import CandidateNormalizationError, CandidateNormalizer
from src.weekly_report.contracts import (
    CandidateNormalizationFailure,
    DiscoveryIntent,
    DiscoveryResult,
    GoogleNewsRssEncoding,
    RegionMode,
    SearchAttemptResult,
    SearchPlan,
    SearchPlanItem,
    SearchProviderId,
    SearchTechnicalFailureClass,
    SearchTerminalStatus,
)
from src.weekly_report.region_registry import RegionRegistry
from src.weekly_report.report_application import ReportApplication
from src.weekly_report.search_executor import SearchExecutor
from src.weekly_report.search_planner import SearchPlanner


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


class ReportApplicationTests(TestCase):
    def _app(self, provider: FakeProvider, *, dispatch=True, normalizer=None) -> ReportApplication:
        plan = _fixture_plan()
        registry = _registry()
        mapping = {SearchProviderId.GOOGLE_NEWS_RSS: provider} if dispatch else {}
        return ReportApplication(registry, FixturePlanner(registry, plan), SearchExecutor(mapping), normalizer)

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
