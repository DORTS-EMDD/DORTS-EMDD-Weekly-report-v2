from __future__ import annotations

from unittest import TestCase

from src.weekly_report.contracts import (
    DiscoveryIntent,
    DiscoveryResult,
    GoogleNewsRssEncoding,
    RegionMode,
    SearchAttemptResult,
    SearchInfrastructureStage,
    SearchPlan,
    SearchPlanItem,
    SearchProviderId,
    SearchTechnicalFailureClass,
    SearchTerminalStatus,
)
from src.weekly_report.search_executor import SearchExecutor


def _plan() -> SearchPlan:
    items = tuple(
        SearchPlanItem(
            f"item-{index}", "market", RegionMode.SELECTED, DiscoveryIntent.OPERATIONS,
            "en", "family", SearchProviderId.GOOGLE_NEWS_RSS, f"query-{index}",
            GoogleNewsRssEncoding("en-US", "US", "US:en"), "en-US",
        )
        for index in range(3)
    )
    return SearchPlan("search-discovery-v3", RegionMode.SELECTED, items, "plan-1")


class FakeProvider:
    def __init__(self, outcome=None, *, raise_error: bool = False):
        self.calls: list[str] = []
        self.outcome = outcome
        self.raise_error = raise_error

    def execute(self, request):
        self.calls.append(request.plan_item_id)
        if self.raise_error:
            raise RuntimeError("transport secret")
        if callable(self.outcome):
            return self.outcome(request)
        if self.outcome is not None:
            return self.outcome
        return SearchAttemptResult(request.plan_item_id, SearchTerminalStatus.SUCCESS_ZERO_RESULTS)


class SearchExecutorTests(TestCase):
    def test_exact_plan_order_and_one_call_per_item(self) -> None:
        provider = FakeProvider(lambda item: SearchAttemptResult(item.plan_item_id, SearchTerminalStatus.SUCCESS_WITH_RESULTS, (DiscoveryResult(item.plan_item_id, f"https://example/{item.plan_item_id}"),)))
        result = SearchExecutor({SearchProviderId.GOOGLE_NEWS_RSS: provider}).execute(_plan())
        self.assertEqual(provider.calls, ["item-0", "item-1", "item-2"])
        self.assertEqual(tuple(item.plan_item_id for item in result.attempt_results), tuple(provider.calls))
        self.assertTrue(result.execution_complete)
        self.assertTrue(all(observation.normalized_result_count is None for observation in result.observations))

    def test_zero_results_is_complete_success(self) -> None:
        result = SearchExecutor({SearchProviderId.GOOGLE_NEWS_RSS: FakeProvider()}).execute(_plan())
        self.assertTrue(result.execution_complete)
        self.assertFalse(result.has_technical_failures)
        self.assertTrue(all(item.status is SearchTerminalStatus.SUCCESS_ZERO_RESULTS for item in result.attempt_results))

    def test_item_technical_failure_continues_remaining_items(self) -> None:
        def outcome(item):
            if item.plan_item_id == "item-1":
                return SearchAttemptResult(item.plan_item_id, SearchTerminalStatus.TECHNICAL_FAILURE, technical_failure_class=SearchTechnicalFailureClass.TIMEOUT)
            return SearchAttemptResult(item.plan_item_id, SearchTerminalStatus.SUCCESS_ZERO_RESULTS)

        provider = FakeProvider(outcome)
        result = SearchExecutor({SearchProviderId.GOOGLE_NEWS_RSS: provider}).execute(_plan())
        self.assertEqual(provider.calls, ["item-0", "item-1", "item-2"])
        self.assertTrue(result.execution_complete)
        self.assertTrue(result.has_technical_failures)

    def test_missing_dispatch_aborts_with_unattempted_items(self) -> None:
        result = SearchExecutor({}).execute(_plan())
        self.assertFalse(result.execution_complete)
        self.assertEqual(result.infrastructure_failure.stage, SearchInfrastructureStage.DISPATCH)
        self.assertEqual(tuple(item.plan_item_id for item in result.unattempted_items), ("item-0", "item-1", "item-2"))
        self.assertEqual(len(result.observations), 3)

    def test_provider_exception_aborts_without_raw_exception(self) -> None:
        provider = FakeProvider(raise_error=True)
        result = SearchExecutor({SearchProviderId.GOOGLE_NEWS_RSS: provider}).execute(_plan())
        self.assertFalse(result.execution_complete)
        self.assertEqual(result.infrastructure_failure.stage, SearchInfrastructureStage.EXECUTION)
        self.assertEqual(tuple(item.plan_item_id for item in result.unattempted_items), ("item-1", "item-2"))
        self.assertEqual(tuple(item.plan_item_id for item in result.attempt_results), ("item-0",))
        self.assertEqual(result.attempt_results[0].status, SearchTerminalStatus.TECHNICAL_FAILURE)
        self.assertEqual(result.attempt_results[0].technical_failure_class, SearchTechnicalFailureClass.UNKNOWN)
        self.assertTrue(result.observations[0].attempted)
        self.assertNotIn("secret", repr(result))
        self.assertEqual(provider.calls, ["item-0"])

    def test_provider_exception_after_completed_item_preserves_provenance(self) -> None:
        def outcome(item):
            if item.plan_item_id == "item-1":
                raise RuntimeError("transport secret")
            return SearchAttemptResult(item.plan_item_id, SearchTerminalStatus.SUCCESS_ZERO_RESULTS)

        provider = FakeProvider(outcome)
        result = SearchExecutor({SearchProviderId.GOOGLE_NEWS_RSS: provider}).execute(_plan())
        self.assertEqual(provider.calls, ["item-0", "item-1"])
        self.assertEqual(tuple(item.plan_item_id for item in result.attempt_results), ("item-0", "item-1"))
        self.assertEqual(result.attempt_results[0].status, SearchTerminalStatus.SUCCESS_ZERO_RESULTS)
        self.assertEqual(result.attempt_results[1].status, SearchTerminalStatus.TECHNICAL_FAILURE)
        self.assertTrue(result.observations[0].attempted)
        self.assertTrue(result.observations[1].attempted)
        self.assertEqual(tuple(item.plan_item_id for item in result.unattempted_items), ("item-2",))

    def test_malformed_provider_result_becomes_one_item_failure(self) -> None:
        provider = FakeProvider(lambda item: object())
        result = SearchExecutor({SearchProviderId.GOOGLE_NEWS_RSS: provider}).execute(_plan())
        self.assertTrue(result.execution_complete)
        self.assertTrue(result.has_technical_failures)
        self.assertEqual(len(result.attempt_results), 3)
        self.assertTrue(all(item.technical_failure_class is SearchTechnicalFailureClass.UNKNOWN for item in result.attempt_results))

    def test_dispatch_is_immutable_and_unknown_key_fails_closed(self) -> None:
        provider = FakeProvider()
        dispatch = {"unknown": provider}
        executor = SearchExecutor(dispatch)
        dispatch.clear()
        result = executor.execute(_plan())
        self.assertFalse(result.execution_complete)
        self.assertEqual(provider.calls, [])
