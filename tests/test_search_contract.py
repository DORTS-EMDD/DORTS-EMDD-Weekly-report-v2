"""Focused offline tests for Search typed contracts and ownership boundaries."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from unittest import TestCase

from src.weekly_report.contracts import (
    CategoryId,
    DiscoveryIntent,
    DiscoveryResult,
    QueryFamilyConfig,
    RegionMode,
    SearchAttemptResult,
    SearchExecutionResult,
    SearchInfrastructureFailure,
    SearchInfrastructureFailureClass,
    SearchObservation,
    SearchPlanItem,
    SearchPlan,
    SearchProviderId,
    SearchProvider,
    SearchPlanningLimits,
    SearchTechnicalFailureClass,
    SearchTerminalStatus,
)


class SearchContractTests(TestCase):
    def _plan(self) -> SearchPlan:
        items = tuple(
            SearchPlanItem(
                item_id,
                "market",
                RegionMode.SELECTED,
                DiscoveryIntent.OPERATIONS,
                "en",
                "family",
                SearchProviderId.GOOGLE_NEWS_RSS,
                item_id,
                "en-US",
            )
            for item_id in ("item-1", "item-2")
        )
        return SearchPlan("search-discovery-v2", RegionMode.SELECTED, items, "plan-1")

    @staticmethod
    def _attempt_observation(item, result, *, raw_result_count=None, normalized_result_count=None):
        if raw_result_count is None:
            raw_result_count = (
                len(result.results)
                if result.status is SearchTerminalStatus.SUCCESS_WITH_RESULTS
                else 0
            )
        return SearchObservation(
            item.plan_item_id,
            item.market_id,
            item.intent,
            item.language_profile,
            item.query_family_id,
            item.provider_target,
            True,
            True,
            result.status,
            raw_result_count,
            result.technical_failure_class,
            normalized_result_count,
        )

    @staticmethod
    def _unattempted_observation(item):
        return SearchObservation(
            item.plan_item_id,
            item.market_id,
            item.intent,
            item.language_profile,
            item.query_family_id,
            item.provider_target,
            True,
            False,
            None,
            0,
            None,
            None,
        )

    def test_discovery_intent_is_canonical_and_not_category(self) -> None:
        self.assertEqual(
            tuple(intent.value for intent in DiscoveryIntent),
            ("technology", "major_incident", "operations", "procurement"),
        )
        self.assertEqual(DiscoveryIntent.MAJOR_INCIDENT.display_label, "major incident")
        self.assertEqual(DiscoveryIntent.PROCUREMENT.display_label, "procurement")
        self.assertNotEqual(DiscoveryIntent.PROCUREMENT.value, CategoryId.PROCUREMENT.value)
        with self.assertRaises(ValueError):
            DiscoveryIntent("major incident")
        with self.assertRaises(ValueError):
            DiscoveryIntent(" PROCUREMENT ")

    def test_legal_statuses_and_zero_results_are_distinct(self) -> None:
        self.assertEqual(
            {status.value for status in SearchTerminalStatus},
            {"SUCCESS_WITH_RESULTS", "SUCCESS_ZERO_RESULTS", "TECHNICAL_FAILURE"},
        )
        empty = SearchAttemptResult("item", SearchTerminalStatus.SUCCESS_ZERO_RESULTS)
        failure = SearchAttemptResult("item", SearchTerminalStatus.TECHNICAL_FAILURE, technical_failure_class=SearchTechnicalFailureClass.TIMEOUT)
        self.assertEqual(empty.results, ())
        self.assertEqual(failure.results, ())
        self.assertNotEqual(empty.status, failure.status)
        with self.assertRaises(ValueError):
            SearchAttemptResult("item", SearchTerminalStatus.SUCCESS_WITH_RESULTS)
        with self.assertRaises(ValueError):
            SearchAttemptResult("item", SearchTerminalStatus.TECHNICAL_FAILURE, technical_failure_class="secret")

    def test_structural_protocol_and_observation_boundary(self) -> None:
        class Provider:
            def execute(self, request):
                return SearchAttemptResult(request.plan_item_id, SearchTerminalStatus.SUCCESS_ZERO_RESULTS)

        self.assertIsInstance(Provider(), SearchProvider)
        item = SearchPlanItem("item", "market", RegionMode.SELECTED, DiscoveryIntent.OPERATIONS, "en", "family", SearchProviderId.GOOGLE_NEWS_RSS, "query", "en")
        planned = SearchObservation("item", "market", DiscoveryIntent.OPERATIONS, "en", "family", SearchProviderId.GOOGLE_NEWS_RSS, True, False, None, 0)
        attempted = SearchObservation("item", "market", DiscoveryIntent.OPERATIONS, "en", "family", SearchProviderId.GOOGLE_NEWS_RSS, True, True, SearchTerminalStatus.SUCCESS_ZERO_RESULTS, 0)
        self.assertFalse(planned.attempted)
        self.assertTrue(attempted.attempted)
        self.assertEqual(item.request, item.query)
        self.assertEqual(item.locale, "en")
        with self.assertRaises(FrozenInstanceError):
            item.query = "other"
        with self.assertRaises(ValueError):
            SearchObservation("item", "market", DiscoveryIntent.OPERATIONS, "en", "family", SearchProviderId.GOOGLE_NEWS_RSS, False, True, SearchTerminalStatus.SUCCESS_ZERO_RESULTS, 0)

    def test_query_family_requires_all_canonical_intents_and_is_immutable(self) -> None:
        family = QueryFamilyConfig(
            "family",
            ("{market} {intent_term}",),
            {intent.value: ("urban_rail_terms",) for intent in DiscoveryIntent},
            SearchProviderId.GOOGLE_NEWS_RSS,
        )
        self.assertEqual(family.vocabulary_groups["technology"], ("urban_rail_terms",))
        with self.assertRaises(TypeError):
            family.vocabulary_groups["technology"] = ("changed",)
        with self.assertRaises(ValueError):
            QueryFamilyConfig("bad", ("x",), {"technology": ("technology",)}, SearchProviderId.GOOGLE_NEWS_RSS)

    def test_query_family_provider_target_is_explicit_and_canonical(self) -> None:
        groups = {intent.value: ("term",) for intent in DiscoveryIntent}
        with self.assertRaises(TypeError):
            QueryFamilyConfig("missing", ("{intent_term}",), groups)
        with self.assertRaises(ValueError):
            QueryFamilyConfig("default", ("{intent_term}",), groups, "default")
        with self.assertRaises(ValueError):
            QueryFamilyConfig("unknown", ("{intent_term}",), groups, "unknown")

    def test_planning_limits_are_typed_and_positive(self) -> None:
        limits = SearchPlanningLimits(64, 100_000)
        self.assertEqual(limits.max_concrete_requests_per_family, 64)
        with self.assertRaises(ValueError):
            SearchPlanningLimits(0, 10)

    def test_discovery_result_is_mechanical_metadata(self) -> None:
        result = DiscoveryResult("title", "https://example.test/item", snippet="metadata")
        self.assertEqual(result.snippet, "metadata")

    def test_provider_target_is_canonical_and_default_is_rejected(self) -> None:
        self.assertEqual(SearchProviderId("google_news_rss"), SearchProviderId.GOOGLE_NEWS_RSS)
        with self.assertRaises(ValueError):
            SearchPlanItem("item", "market", RegionMode.SELECTED, DiscoveryIntent.OPERATIONS, "en", "family", "default", "query", "en")
        with self.assertRaises(ValueError):
            SearchPlanItem("item", "market", RegionMode.SELECTED, DiscoveryIntent.OPERATIONS, "en", "family", "unknown", "query", "en")

    def test_execution_result_derives_complete_success_and_preserves_plan_order(self) -> None:
        plan = self._plan()
        first = SearchAttemptResult("item-1", SearchTerminalStatus.SUCCESS_WITH_RESULTS, (DiscoveryResult("title", "https://example.test"),))
        second = SearchAttemptResult("item-2", SearchTerminalStatus.SUCCESS_ZERO_RESULTS)
        result = SearchExecutionResult(
            plan,
            attempt_results=(second, first),
            observations=(self._attempt_observation(plan.items[1], second), self._attempt_observation(plan.items[0], first)),
        )
        self.assertEqual(tuple(item.plan_item_id for item in result.attempt_results), ("item-1", "item-2"))
        self.assertEqual(tuple(item.plan_item_id for item in result.observations), ("item-1", "item-2"))
        self.assertTrue(result.execution_complete)
        self.assertFalse(result.has_technical_failures)
        self.assertEqual(result.plan_id, "plan-1")

    def test_execution_result_allows_complete_execution_with_item_failure(self) -> None:
        plan = self._plan()
        first = SearchAttemptResult("item-1", SearchTerminalStatus.SUCCESS_ZERO_RESULTS)
        second = SearchAttemptResult("item-2", SearchTerminalStatus.TECHNICAL_FAILURE, technical_failure_class=SearchTechnicalFailureClass.TIMEOUT)
        result = SearchExecutionResult(
            plan,
            attempt_results=(first, second),
            observations=(self._attempt_observation(plan.items[0], first), self._attempt_observation(plan.items[1], second)),
        )
        self.assertTrue(result.execution_complete)
        self.assertTrue(result.has_technical_failures)

    def test_execution_result_rejects_missing_duplicate_foreign_and_overlap_items(self) -> None:
        plan = self._plan()
        success = SearchAttemptResult("item-1", SearchTerminalStatus.SUCCESS_ZERO_RESULTS)
        first_observation = self._attempt_observation(plan.items[0], success)
        with self.assertRaises(ValueError):
            SearchExecutionResult(plan, attempt_results=(success,), observations=(first_observation,))
        with self.assertRaises(ValueError):
            SearchExecutionResult(plan, attempt_results=(success, success), unattempted_items=(plan.items[1],), observations=(first_observation, self._unattempted_observation(plan.items[1])))
        foreign = SearchAttemptResult("foreign", SearchTerminalStatus.SUCCESS_ZERO_RESULTS)
        with self.assertRaises(ValueError):
            SearchExecutionResult(plan, attempt_results=(success, foreign), observations=(first_observation, self._unattempted_observation(plan.items[1])))
        with self.assertRaises(ValueError):
            SearchExecutionResult(plan, attempt_results=(success,), unattempted_items=(plan.items[0], plan.items[1]), observations=(first_observation, self._unattempted_observation(plan.items[1])))

    def test_execution_result_distinguishes_infrastructure_failure_and_unattempted_items(self) -> None:
        plan = self._plan()
        first = SearchAttemptResult("item-1", SearchTerminalStatus.SUCCESS_ZERO_RESULTS)
        result = SearchExecutionResult(
            plan,
            attempt_results=(first,),
            unattempted_items=(plan.items[1],),
            infrastructure_failure=SearchInfrastructureFailure(
                SearchInfrastructureFailureClass.EXECUTION_ABORTED, "dispatch"
            ),
            observations=(self._attempt_observation(plan.items[0], first), self._unattempted_observation(plan.items[1])),
        )
        self.assertFalse(result.execution_complete)
        self.assertFalse(result.has_technical_failures)
        with self.assertRaises(FrozenInstanceError):
            result.unattempted_items = ()

    def test_execution_result_requires_observations_for_every_plan_item(self) -> None:
        plan = self._plan()
        first = SearchAttemptResult("item-1", SearchTerminalStatus.SUCCESS_ZERO_RESULTS)
        second = SearchAttemptResult("item-2", SearchTerminalStatus.SUCCESS_ZERO_RESULTS)
        with self.assertRaises(ValueError):
            SearchExecutionResult(plan, attempt_results=(first, second))
        with self.assertRaises(ValueError):
            SearchExecutionResult(plan, attempt_results=(first, second), observations=(self._attempt_observation(plan.items[0], first), self._attempt_observation(plan.items[0], first)))

    def test_execution_result_rejects_observation_identity_and_result_mismatches(self) -> None:
        plan = self._plan()
        first = SearchAttemptResult("item-1", SearchTerminalStatus.SUCCESS_WITH_RESULTS, (DiscoveryResult("title", "https://example.test"),))
        second = SearchAttemptResult("item-2", SearchTerminalStatus.SUCCESS_ZERO_RESULTS)
        valid_first = self._attempt_observation(plan.items[0], first)
        valid_second = self._attempt_observation(plan.items[1], second)
        for field, value in (("market_id", "other"), ("intent", DiscoveryIntent.TECHNOLOGY), ("language_profile", "zh"), ("query_family_id", "other"), ("provider", "default")):
            kwargs = dict(
                plan_item_id=valid_first.plan_item_id,
                market_id=valid_first.market_id,
                intent=valid_first.intent,
                language_profile=valid_first.language_profile,
                query_family_id=valid_first.query_family_id,
                provider=valid_first.provider,
                planned=True,
                attempted=True,
                terminal_status=valid_first.terminal_status,
                raw_result_count=valid_first.raw_result_count,
                technical_failure_class=None,
                normalized_result_count=None,
            )
            kwargs[field] = value
            with self.assertRaises(ValueError):
                SearchExecutionResult(plan, attempt_results=(first, second), observations=(SearchObservation(**kwargs), valid_second))
        wrong_status = SearchObservation(valid_first.plan_item_id, valid_first.market_id, valid_first.intent, valid_first.language_profile, valid_first.query_family_id, valid_first.provider, True, True, SearchTerminalStatus.SUCCESS_ZERO_RESULTS, 0)
        with self.assertRaises(ValueError):
            SearchExecutionResult(plan, attempt_results=(first, second), observations=(wrong_status, valid_second))
        wrong_count = self._attempt_observation(plan.items[0], first, raw_result_count=0)
        with self.assertRaises(ValueError):
            SearchExecutionResult(plan, attempt_results=(first, second), observations=(wrong_count, valid_second))

    def test_execution_result_rejects_normalization_and_failure_parity_violations(self) -> None:
        plan = self._plan()
        first = SearchAttemptResult("item-1", SearchTerminalStatus.SUCCESS_ZERO_RESULTS)
        second = SearchAttemptResult("item-2", SearchTerminalStatus.TECHNICAL_FAILURE, technical_failure_class=SearchTechnicalFailureClass.TIMEOUT)
        normalized = self._attempt_observation(plan.items[0], first, normalized_result_count=0)
        valid_failure = self._attempt_observation(plan.items[1], second)
        with self.assertRaises(ValueError):
            SearchExecutionResult(plan, attempt_results=(first, second), observations=(normalized, valid_failure))
        wrong_failure = SearchObservation(valid_failure.plan_item_id, valid_failure.market_id, valid_failure.intent, valid_failure.language_profile, valid_failure.query_family_id, valid_failure.provider, True, True, valid_failure.terminal_status, 99, SearchTechnicalFailureClass.NETWORK)
        with self.assertRaises(ValueError):
            SearchExecutionResult(plan, attempt_results=(first, second), observations=(self._attempt_observation(plan.items[0], first), wrong_failure))

    def test_unattempted_observation_cannot_claim_results_or_normalization(self) -> None:
        item = self._plan().items[0]
        with self.assertRaises(ValueError):
            SearchObservation(item.plan_item_id, item.market_id, item.intent, item.language_profile, item.query_family_id, item.provider_target, True, False, None, 1)
        with self.assertRaises(ValueError):
            SearchObservation(item.plan_item_id, item.market_id, item.intent, item.language_profile, item.query_family_id, item.provider_target, True, False, None, 0, normalized_result_count=0)
        with self.assertRaises(ValueError):
            SearchObservation(item.plan_item_id, item.market_id, item.intent, item.language_profile, item.query_family_id, item.provider_target, True, False, None, 0, SearchTechnicalFailureClass.TIMEOUT)

    def test_observation_normalization_count_distinguishes_not_run_and_zero(self) -> None:
        not_run = SearchObservation("item", "market", DiscoveryIntent.OPERATIONS, "en", "family", SearchProviderId.GOOGLE_NEWS_RSS, True, False, None, 0)
        normalized_zero = SearchObservation("item", "market", DiscoveryIntent.OPERATIONS, "en", "family", SearchProviderId.GOOGLE_NEWS_RSS, True, True, SearchTerminalStatus.SUCCESS_ZERO_RESULTS, 0, normalized_result_count=0)
        self.assertIsNone(not_run.normalized_result_count)
        self.assertEqual(normalized_zero.normalized_result_count, 0)
        with self.assertRaises(ValueError):
            SearchObservation("item", "market", DiscoveryIntent.OPERATIONS, "en", "family", SearchProviderId.GOOGLE_NEWS_RSS, True, True, SearchTerminalStatus.SUCCESS_ZERO_RESULTS, 0, normalized_result_count=-1)
        with self.assertRaises(ValueError):
            SearchObservation("item", "market", DiscoveryIntent.OPERATIONS, "en", "family", "default", True, False, None, 0)
