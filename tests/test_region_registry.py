"""Focused tests for the single materialized RegionRegistry owner."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from src.weekly_report.contracts import DiscoveryIntent, RegionMode
from src.weekly_report.region_registry import CONFIGURATION_PATH, RegionRegistry
from scripts.materialize_search_configuration import validate_configuration


class RegionRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = RegionRegistry.from_file()
        with CONFIGURATION_PATH.open("r", encoding="utf-8") as handle:
            self.source = json.load(handle)

    def test_locked_membership_profiles_and_mappings(self) -> None:
        self.assertEqual(self.registry.selected_market_count, 19)
        self.assertEqual(self.registry.global_target_count, 19)
        self.assertEqual(len(self.registry.selected_profile_ids), 13)
        self.assertNotIn("taiwan", {market.market_id for market in self.registry.selected_markets})
        self.assertNotIn("taiwan", set(self.registry.global_targets))
        self.assertEqual(self.registry.market("hong_kong").primary_profiles, ("zh",))
        self.assertEqual(self.registry.market("switzerland").secondary_profiles, ("fr", "it"))
        self.assertEqual(self.registry.market("south_korea").english_supplement_profiles, ("en",))
        self.assertEqual(self.registry.profiles_for_market(self.registry.market("south_korea")), ("ko", "en"))
        for family in self.registry.query_families:
            self.assertEqual(set(family.vocabulary_groups), {intent.value for intent in DiscoveryIntent})

    def test_registry_is_the_only_target_owner_and_values_are_immutable(self) -> None:
        self.assertEqual(tuple(m.market_id for m in self.registry.markets_for(RegionMode.SELECTED)), tuple(m.market_id for m in self.registry.selected_markets))
        with self.assertRaises(AttributeError):
            self.registry.global_targets = ()
        with self.assertRaises(FrozenInstanceError):
            self.registry.market("hong_kong").market_id = "other"
        with self.assertRaises(FrozenInstanceError):
            self.registry.market("hong_kong").primary_profiles += ("en",)

    def test_future_governed_global_target_requires_capability_population(self) -> None:
        source = copy.deepcopy(self.source)
        source["global_markets"].append(
            {
                "market_id": "future_market",
                "display_name": "Future Market",
                "primary_profiles": ["en"],
                "locale_hints": ["en-FM"],
                "terminology_refs": ["urban_rail_core"],
            }
        )
        source["global_targets"].append("future_market")
        with self.assertRaises(ValueError):
            RegionRegistry.from_mapping(source)

    def test_invalid_configuration_fails_closed(self) -> None:
        duplicate = copy.deepcopy(self.source)
        duplicate["selected_markets"].append(copy.deepcopy(duplicate["selected_markets"][0]))
        with self.assertRaises(ValueError):
            RegionRegistry.from_mapping(duplicate)
        taiwan = copy.deepcopy(self.source)
        taiwan["global_targets"][0] = "taiwan"
        with self.assertRaises(ValueError):
            RegionRegistry.from_mapping(taiwan)
        unresolved_profile = copy.deepcopy(self.source)
        unresolved_profile["selected_markets"][0]["primary_profiles"] = ["xx"]
        with self.assertRaises(ValueError):
            RegionRegistry.from_mapping(unresolved_profile)

        disabled_market = copy.deepcopy(self.source)
        disabled_market["selected_markets"][0]["enabled"] = False
        with self.assertRaises(ValueError):
            RegionRegistry.from_mapping(disabled_market)
        disabled_profile = copy.deepcopy(self.source)
        disabled_profile["profiles"][0]["enabled"] = False
        with self.assertRaises(ValueError):
            RegionRegistry.from_mapping(disabled_profile)
        disabled_required_profile = copy.deepcopy(self.source)
        disabled_required_profile["profiles"][3]["enabled"] = False
        with self.assertRaises(ValueError):
            RegionRegistry.from_mapping(disabled_required_profile)

    def test_materialization_is_lossless_and_deterministic(self) -> None:
        registry = validate_configuration(CONFIGURATION_PATH)
        self.assertEqual(registry.as_mapping(), RegionRegistry.from_mapping(registry.as_mapping()).as_mapping())
        self.assertEqual(
            {family.provider_target.value for family in registry.query_families},
            {"google_news_rss"},
        )

    def test_provider_target_parity_rejects_default_and_unknown_ids(self) -> None:
        for provider_target in ("default", "unknown_provider"):
            source = copy.deepcopy(self.source)
            source["query_families"][0]["provider_target"] = provider_target
            with self.assertRaises(ValueError):
                RegionRegistry.from_mapping(source)

    def test_governance_parity_rejects_runtime_only_or_modified_fields(self) -> None:
        def validate_modified(source: dict) -> None:
            with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False) as handle:
                json.dump(source, handle, ensure_ascii=False)
                path = handle.name
            try:
                with self.assertRaises(ValueError):
                    validate_configuration(path)
            finally:
                Path(path).unlink(missing_ok=True)

        changed_term = copy.deepcopy(self.source)
        changed_term["profiles"][0]["intent_vocabulary"]["technology"]["urban_rail_terms"][0] = "forged"
        validate_modified(changed_term)

        missing_group = copy.deepcopy(self.source)
        del missing_group["profiles"][0]["intent_vocabulary"]["technology"]["new_method_terms"]
        validate_modified(missing_group)

        runtime_profile = copy.deepcopy(self.source)
        extra_profile = copy.deepcopy(runtime_profile["profiles"][0])
        extra_profile["profile_id"] = "xx"
        runtime_profile["profiles"].append(extra_profile)
        validate_modified(runtime_profile)

        removed_market = copy.deepcopy(self.source)
        removed_market["selected_markets"].pop()
        removed_market["global_targets"].pop()
        validate_modified(removed_market)

        changed_hong_kong = copy.deepcopy(self.source)
        hong_kong = next(item for item in changed_hong_kong["selected_markets"] if item["market_id"] == "hong_kong")
        hong_kong["primary_profiles"] = ["fr"]
        hong_kong["english_supplement_profiles"] = ["en"]
        validate_modified(changed_hong_kong)
