"""Focused tests for deterministic offline SearchPlanner planning."""

from __future__ import annotations

import copy
import json
import unittest
from dataclasses import FrozenInstanceError

from src.weekly_report.contracts import DiscoveryIntent, RegionMode
from src.weekly_report.region_registry import RegionRegistry
from src.weekly_report.search_planner import SearchPlanner


class SearchPlannerTests(unittest.TestCase):
    def setUp(self) -> None:
        with open("src/weekly_report/search_configuration.json", encoding="utf-8") as handle:
            self.source = json.load(handle)
        self.registry = RegionRegistry.from_mapping(self.source)
        self.planner = SearchPlanner(self.registry)

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
        self.assertEqual(south_korea_profiles, {"ko", "en"})
        expected_count = sum(
            len(self.registry.profile(profile_id).intent_vocabulary["technology"]["technology_terms"])
            for market in self.registry.selected_markets
            for profile_id in self.registry.profiles_for_market(market)
        )
        self.assertEqual(len(plan.items), expected_count)

    def test_concrete_requests_from_one_family_have_distinct_stable_ids(self) -> None:
        source = copy.deepcopy(self.source)
        source["query_families"][0]["templates"].append("{market} {anchor} {intent_term} update")
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
