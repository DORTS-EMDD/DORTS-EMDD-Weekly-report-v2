"""Focused tests for deterministic offline SearchPlanner planning."""

from __future__ import annotations

import copy
import json
import unittest
from dataclasses import FrozenInstanceError

from src.weekly_report.contracts import (
    DiscoveryIntent,
    RegionMode,
    SearchCoverageGapReason,
)
from src.weekly_report.region_registry import RegionRegistry
from src.weekly_report.search_planner import SearchPlanner, _query_words


class SearchPlannerTests(unittest.TestCase):
    def setUp(self) -> None:
        with open("src/weekly_report/search_configuration.json", encoding="utf-8") as handle:
            self.source = json.load(handle)
        self.production_registry = RegionRegistry.from_mapping(self.source)
        self.source = self._supported_fixture(self.source)
        self.registry = RegionRegistry.from_mapping(self.source)
        self.planner = SearchPlanner(self.registry)

    @staticmethod
    def _supported_fixture(source: dict) -> dict:
        fixture = copy.deepcopy(source)
        fixture["selected_markets"] = [
            market for market in fixture["selected_markets"] if market["market_id"] != "denmark"
        ]
        fixture["global_targets"] = [target for target in fixture["global_targets"] if target != "denmark"]
        fixture["provider_profile_bindings"] = [
            binding for binding in fixture["provider_profile_bindings"] if binding["market_id"] != "denmark"
        ]
        return fixture

    def test_identical_input_produces_identical_frozen_plan(self) -> None:
        first = self.planner.plan(RegionMode.SELECTED)
        second = SearchPlanner(RegionRegistry.from_mapping(copy.deepcopy(self.source))).plan("selected")
        self.assertEqual(first, second)
        self.assertEqual(first.plan_id, second.plan_id)
        self.assertEqual(tuple(item.plan_item_id for item in first.items), tuple(item.plan_item_id for item in second.items))
        keys = [(item.market_id, item.intent.value, item.language_profile, item.query_family_id, item.provider_target, item.query) for item in first.items]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual({item.intent for item in first.items}, set(DiscoveryIntent))
        with self.assertRaises(FrozenInstanceError):
            first.items += (first.items[0],)

    def test_selected_and_global_consume_registry_targets_and_exclude_taiwan(self) -> None:
        selected = self.planner.plan("selected")
        global_plan = self.planner.plan("global")
        self.assertEqual({item.market_id for item in selected.items}, {market.market_id for market in self.registry.selected_markets})
        self.assertEqual({item.market_id for item in global_plan.items}, set(self.registry.global_targets))
        self.assertNotIn("taiwan", {item.market_id for item in selected.items})
        self.assertNotIn("taiwan", {item.market_id for item in global_plan.items})

    def test_primary_and_preplanned_english_supplement_are_in_frozen_plan(self) -> None:
        plan = self.planner.plan("selected", intents=(DiscoveryIntent.TECHNOLOGY,))
        south_korea_profiles = {item.language_profile for item in plan.items if item.market_id == "south_korea"}
        self.assertEqual(south_korea_profiles, {"ko"})
        supported = {
            (market.market_id, profile_id)
            for market in self.registry.selected_markets
            for profile_id in self.registry.profiles_for_market(market)
            if self.registry.provider_profile_binding(market.market_id, profile_id, "google_news_rss").eligibility.value == "SUPPORTED"
        }
        # RC-11: every supported edition is planned, in its own vocabulary,
        # within the 32-word query bound, and far below one request per term.
        self.assertEqual({(item.market_id, item.language_profile) for item in plan.items}, supported)
        self.assertTrue(all(_query_words(item.query) <= 32 for item in plan.items))
        per_term = sum(
            len(self.registry.profile(profile_id).intent_vocabulary["technology"][group])
            for _market, profile_id in supported
            for group in ("technology_terms", "new_material_terms", "new_method_terms")
        )
        self.assertLess(len(plan.items), per_term)
        korean = [item.query for item in plan.items if item.language_profile == "ko"]
        self.assertTrue(korean and all("urban rail" not in query and "South Korea" not in query for query in korean))
        self.assertTrue(all(" OR " in item.query for item in plan.items))

    def test_production_selected_planning_exposes_denmark_coverage_gap(self) -> None:
        plan = SearchPlanner(self.production_registry).plan("selected")
        configured = tuple(market.market_id for market in self.production_registry.selected_markets)
        self.assertIn("denmark", configured)
        self.assertEqual(plan.coverage.configured_market_ids, configured)
        self.assertEqual(tuple(gap.market_id for gap in plan.coverage.gaps), ("denmark",))
        self.assertEqual(
            plan.coverage.gaps[0].reason,
            SearchCoverageGapReason.KNOWN_UNSUPPORTED_PROVIDER_CAPABILITY,
        )
        self.assertEqual(sum(item.market_id == "denmark" for item in plan.items), 0)
        self.assertEqual(len({item.market_id for item in plan.items}), 18)

    def test_production_global_planning_exposes_denmark_coverage_gap(self) -> None:
        plan = SearchPlanner(self.production_registry).plan("global")
        self.assertIn("denmark", plan.coverage.configured_market_ids)
        self.assertEqual(tuple(gap.market_id for gap in plan.coverage.gaps), ("denmark",))
        self.assertEqual(sum(item.market_id == "denmark" for item in plan.items), 0)

    def test_coverage_is_in_plan_mapping_and_identity(self) -> None:
        plan = SearchPlanner(self.production_registry).plan("selected")
        mapping = plan.as_mapping()
        self.assertEqual(mapping["coverage"]["version"], "search-plan-coverage-v1")
        self.assertEqual(mapping["coverage"]["gaps"][0]["market_id"], "denmark")
        source = copy.deepcopy(self.source)
        source["selected_markets"][0]["display_name"] += " changed"
        changed = SearchPlanner(RegionRegistry.from_mapping(source)).plan("selected")
        self.assertNotEqual(plan.plan_id, changed.plan_id)

    def test_all_explicitly_unsupported_markets_fail_before_execution(self) -> None:
        source = copy.deepcopy(self.source)
        for binding in source["provider_profile_bindings"]:
            binding["eligibility"] = "UNSUPPORTED"
            binding["encoding"] = None
        with self.assertRaises(ValueError):
            SearchPlanner(RegionRegistry.from_mapping(source)).plan("selected")

    def test_concrete_requests_from_one_family_have_distinct_stable_ids(self) -> None:
        source = copy.deepcopy(self.source)
        # The legacy one-term-per-request family remains supported.
        source["query_families"][0].update(
            templates=["{market} {anchor} {intent_term}", "{market} {anchor} {intent_term} update"],
            anchor_terms=["urban rail"],
            vocabulary_groups={
                "technology": ["technology_terms"],
                "major_incident": ["accident_terms"],
                "operations": ["policy_terms"],
                "procurement": ["tender_terms"],
            },
        )
        registry = RegionRegistry.from_mapping(source)
        plan = SearchPlanner(registry).plan("selected", intents=(DiscoveryIntent.PROCUREMENT,))
        ids = tuple(item.plan_item_id for item in plan.items)
        self.assertEqual(len(ids), len(set(ids)))
        queries = {item.query for item in plan.items if item.market_id == "south_korea" and item.language_profile == "ko"}
        self.assertTrue(any(query.endswith(" update") for query in queries))
        self.assertTrue(any(not query.endswith(" update") for query in queries))
        self.assertEqual(
            len(queries),
            2 * len(self.registry.profile("ko").intent_vocabulary["procurement"]["tender_terms"]),
        )

    def test_search_window_scopes_every_item_and_changes_plan_identity(self) -> None:
        from datetime import date

        from src.weekly_report.contracts import SearchWindow
        from src.weekly_report.google_news_rss_provider import GoogleNewsRssProvider

        window = SearchWindow(date(2026, 10, 12), date(2026, 10, 18))
        unbounded = self.planner.plan("selected", intents=(DiscoveryIntent.TECHNOLOGY,))
        bounded = self.planner.plan("selected", intents=(DiscoveryIntent.TECHNOLOGY,), window=window)
        self.assertTrue(all(item.search_window == window for item in bounded.items))
        self.assertNotEqual(unbounded.plan_id, bounded.plan_id)
        url = GoogleNewsRssProvider.request_url(bounded.items[0])
        self.assertIn("after%3A2026-10-12", url)
        self.assertIn("before%3A2026-10-19", url)
        self.assertNotIn("after%3A", GoogleNewsRssProvider.request_url(unbounded.items[0]))

    def test_mode_terms_are_required_in_titles_and_trade_press_is_restricted(self) -> None:
        plan = SearchPlanner(self.production_registry).plan("selected")
        editions = [item for item in plan.items if item.query_family_id == "urban_rail_or_groups"]
        self.assertTrue(editions and all(item.query.startswith("(intitle:") for item in editions))
        trade = [item for item in plan.items if item.query_family_id == "rail_trade_press"]
        self.assertEqual({(item.market_id, item.intent.value) for item in trade}, {("united_kingdom", "technology")})
        self.assertEqual(len(trade), 2)
        self.assertTrue(all("site:railwaygazette.com" in item.query or "site:railwaypro.com" in item.query for item in trade))
        self.assertTrue(all(_query_words(item.query) <= 32 for item in plan.items))
        self.assertLess(len(plan.items), 207)

    def test_query_generation_is_bounded(self) -> None:
        source = copy.deepcopy(self.source)
        source["query_families"][0]["templates"] = [f"{{market}} {{anchor}} {{intent_term}} {index}" for index in range(65)]
        with self.assertRaises(ValueError):
            SearchPlanner(RegionRegistry.from_mapping(source)).plan("selected")

    def test_planner_consumes_configured_limits(self) -> None:
        source = copy.deepcopy(self.source)
        source["planning_limits"]["max_plan_items"] = 1
        with self.assertRaises(ValueError):
            SearchPlanner(RegionRegistry.from_mapping(source)).plan("selected")

        source = copy.deepcopy(self.source)
        source["planning_limits"]["max_concrete_requests_per_family"] = 1
        source["query_families"][0]["templates"].append("{market} {anchor} {intent_term} update")
        with self.assertRaises(ValueError):
            SearchPlanner(RegionRegistry.from_mapping(source)).plan("selected")

    def test_changing_configured_budget_changes_acceptance_boundary(self) -> None:
        baseline = self.planner.plan("selected", intents=(DiscoveryIntent.TECHNOLOGY,))
        source = copy.deepcopy(self.source)
        source["planning_limits"]["max_plan_items"] = len(baseline.items) - 1
        with self.assertRaises(ValueError):
            SearchPlanner(RegionRegistry.from_mapping(source)).plan("selected", intents=(DiscoveryIntent.TECHNOLOGY,))
