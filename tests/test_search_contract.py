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
    SearchObservation,
    SearchPlanItem,
    SearchProvider,
    SearchPlanningLimits,
    SearchTechnicalFailureClass,
    SearchTerminalStatus,
)


class SearchContractTests(TestCase):
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
        item = SearchPlanItem("item", "market", RegionMode.SELECTED, DiscoveryIntent.OPERATIONS, "en", "family", "default", "query", "en")
        planned = SearchObservation("item", "market", DiscoveryIntent.OPERATIONS, "en", "family", "default", True, False, None, 0)
        attempted = SearchObservation("item", "market", DiscoveryIntent.OPERATIONS, "en", "family", "default", True, True, SearchTerminalStatus.SUCCESS_ZERO_RESULTS, 0)
        self.assertFalse(planned.attempted)
        self.assertTrue(attempted.attempted)
        self.assertEqual(item.request, item.query)
        self.assertEqual(item.locale, "en")
        with self.assertRaises(FrozenInstanceError):
            item.query = "other"
        with self.assertRaises(ValueError):
            SearchObservation("item", "market", DiscoveryIntent.OPERATIONS, "en", "family", "default", False, True, SearchTerminalStatus.SUCCESS_ZERO_RESULTS, 0)

    def test_query_family_requires_all_canonical_intents_and_is_immutable(self) -> None:
        family = QueryFamilyConfig(
            "family",
            ("{market} {intent_term}",),
            {intent.value: ("urban_rail_terms",) for intent in DiscoveryIntent},
        )
        self.assertEqual(family.vocabulary_groups["technology"], ("urban_rail_terms",))
        with self.assertRaises(TypeError):
            family.vocabulary_groups["technology"] = ("changed",)
        with self.assertRaises(ValueError):
            QueryFamilyConfig("bad", ("x",), {"technology": ("technology",)})

    def test_planning_limits_are_typed_and_positive(self) -> None:
        limits = SearchPlanningLimits(64, 100_000)
        self.assertEqual(limits.max_concrete_requests_per_family, 64)
        with self.assertRaises(ValueError):
            SearchPlanningLimits(0, 10)

    def test_discovery_result_is_mechanical_metadata(self) -> None:
        result = DiscoveryResult("title", "https://example.test/item", snippet="metadata")
        self.assertEqual(result.snippet, "metadata")
