"""Focused tests for the Search provider profile capability contract."""

from __future__ import annotations

import copy
import json
import unittest

from src.weekly_report.contracts import (
    GoogleNewsRssEncoding,
    ProviderProfileBinding,
    ProviderProfileEligibility,
    SearchProviderId,
)
from src.weekly_report.region_registry import RegionRegistry
from src.weekly_report.search_planner import SearchPlanner


SUPPORTED_ENCODINGS = {
    ("australia", "en"): ("en-AU", "AU", "AU:en"),
    ("austria", "de"): ("de", "AT", "AT:de"),
    ("canada", "en"): ("en-CA", "CA", "CA:en"),
    ("canada", "fr"): ("fr-CA", "CA", "CA:fr"),
    ("france", "fr"): ("fr", "FR", "FR:fr"),
    ("germany", "de"): ("de", "DE", "DE:de"),
    ("hong_kong", "zh"): ("zh-HK", "HK", "HK:zh-Hant"),
    ("italy", "it"): ("it", "IT", "IT:it"),
    ("japan", "ja"): ("ja", "JP", "JP:ja"),
    ("netherlands", "nl"): ("nl", "NL", "NL:nl"),
    ("norway", "no"): ("no", "NO", "NO:no"),
    ("portugal", "pt"): ("pt-PT", "PT", "PT:pt-150"),
    ("singapore", "en"): ("en-SG", "SG", "SG:en"),
    ("south_korea", "ko"): ("ko", "KR", "KR:ko"),
    ("spain", "es"): ("es", "ES", "ES:es"),
    ("sweden", "sv"): ("sv", "SE", "SE:sv"),
    ("switzerland", "de"): ("de", "CH", "CH:de"),
    ("switzerland", "fr"): ("fr", "CH", "CH:fr"),
    ("united_kingdom", "en"): ("en-GB", "GB", "GB:en"),
    ("united_states", "en"): ("en-US", "US", "US:en"),
}

UNSUPPORTED_KEYS = {
    ("austria", "en"),
    ("denmark", "da"),
    ("denmark", "en"),
    ("france", "en"),
    ("germany", "en"),
    ("hong_kong", "en"),
    ("italy", "en"),
    ("japan", "en"),
    ("netherlands", "en"),
    ("norway", "en"),
    ("portugal", "en"),
    ("south_korea", "en"),
    ("spain", "en"),
    ("sweden", "en"),
    ("switzerland", "en"),
    ("switzerland", "it"),
}


class ProviderCapabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        with open("src/weekly_report/search_configuration.json", encoding="utf-8") as handle:
            self.source = json.load(handle)

    def test_typed_encoding_preserves_exact_values_without_normalization(self) -> None:
        encoding = GoogleNewsRssEncoding(" en-US ", "US", "US:en")
        self.assertEqual(encoding.hl, " en-US ")
        for values in (("", "US", "US:en"), ("en-US", " ", "US:en"), ("en-US", "US", "")):
            with self.assertRaises(ValueError):
                GoogleNewsRssEncoding(*values)

    def test_binding_requires_encoding_only_for_supported(self) -> None:
        encoding = GoogleNewsRssEncoding("en-US", "US", "US:en")
        supported = ProviderProfileBinding(
            "united_states", "en", SearchProviderId.GOOGLE_NEWS_RSS,
            ProviderProfileEligibility.SUPPORTED, encoding,
        )
        unsupported = ProviderProfileBinding(
            "united_states", "en", SearchProviderId.GOOGLE_NEWS_RSS,
            ProviderProfileEligibility.UNSUPPORTED,
        )
        self.assertIs(supported.eligibility, ProviderProfileEligibility.SUPPORTED)
        self.assertIsNone(unsupported.encoding)
        with self.assertRaises(ValueError):
            ProviderProfileBinding(
                "united_states", "en", SearchProviderId.GOOGLE_NEWS_RSS,
                ProviderProfileEligibility.SUPPORTED,
            )
        with self.assertRaises(ValueError):
            ProviderProfileBinding(
                "united_states", "en", SearchProviderId.GOOGLE_NEWS_RSS,
                ProviderProfileEligibility.UNSUPPORTED, encoding,
            )

    def test_materialized_population_is_exactly_36_with_20_supported(self) -> None:
        registry = RegionRegistry.from_mapping(self.source)
        self.assertEqual(registry.configuration_version, "search-discovery-v3")
        self.assertEqual(len(registry.provider_profile_bindings), 36)
        self.assertEqual(
            sum(binding.eligibility is ProviderProfileEligibility.SUPPORTED for binding in registry.provider_profile_bindings),
            20,
        )
        self.assertEqual(
            sum(binding.eligibility is ProviderProfileEligibility.UNSUPPORTED for binding in registry.provider_profile_bindings),
            16,
        )
        self.assertTrue(
            all(
                binding.encoding is None
                for binding in registry.provider_profile_bindings
                if binding.eligibility is ProviderProfileEligibility.UNSUPPORTED
            )
        )
        self.assertEqual(
            registry.provider_profile_binding("portugal", "pt", "google_news_rss").encoding,
            GoogleNewsRssEncoding("pt-PT", "PT", "PT:pt-150"),
        )
        self.assertIsNone(registry.provider_profile_binding("denmark", "da", "google_news_rss").encoding)

    def test_complete_supported_matrix_matches_verified_values(self) -> None:
        registry = RegionRegistry.from_mapping(self.source)
        actual = {
            (binding.market_id, binding.language_profile_id): (
                binding.encoding.hl,
                binding.encoding.gl,
                binding.encoding.ceid,
            )
            for binding in registry.provider_profile_bindings
            if binding.eligibility is ProviderProfileEligibility.SUPPORTED
        }
        self.assertEqual(actual, SUPPORTED_ENCODINGS)

    def test_complete_unsupported_matrix_matches_verified_keys(self) -> None:
        registry = RegionRegistry.from_mapping(self.source)
        actual = {
            (binding.market_id, binding.language_profile_id)
            for binding in registry.provider_profile_bindings
            if binding.eligibility is ProviderProfileEligibility.UNSUPPORTED
        }
        self.assertEqual(actual, UNSUPPORTED_KEYS)
        self.assertTrue(
            all(
                binding.encoding is None
                for binding in registry.provider_profile_bindings
                if binding.eligibility is ProviderProfileEligibility.UNSUPPORTED
            )
        )

    def test_nested_binding_and_encoding_fields_are_exact(self) -> None:
        extra_binding = copy.deepcopy(self.source)
        extra_binding["provider_profile_bindings"][0]["fallback_provider"] = "other"
        with self.assertRaises(ValueError):
            RegionRegistry.from_mapping(extra_binding)

        extra_encoding = copy.deepcopy(self.source)
        extra_encoding["provider_profile_bindings"][0]["encoding"]["extra"] = "x"
        with self.assertRaises(ValueError):
            RegionRegistry.from_mapping(extra_encoding)

    def test_missing_binding_and_encoding_fields_fail_closed(self) -> None:
        missing_binding = copy.deepcopy(self.source)
        del missing_binding["provider_profile_bindings"][0]["eligibility"]
        with self.assertRaises(ValueError):
            RegionRegistry.from_mapping(missing_binding)

        for field_name in ("hl", "gl", "ceid"):
            missing_encoding = copy.deepcopy(self.source)
            del missing_encoding["provider_profile_bindings"][0]["encoding"][field_name]
            with self.assertRaises(ValueError):
                RegionRegistry.from_mapping(missing_encoding)

    def test_missing_or_extra_population_fails_closed(self) -> None:
        missing = copy.deepcopy(self.source)
        missing["provider_profile_bindings"].pop()
        with self.assertRaises(ValueError):
            RegionRegistry.from_mapping(missing)

        extra = copy.deepcopy(self.source)
        extra["provider_profile_bindings"].append(copy.deepcopy(extra["provider_profile_bindings"][0]))
        with self.assertRaises(ValueError):
            RegionRegistry.from_mapping(extra)

    def test_profile_membership_and_unknown_provider_fail_closed(self) -> None:
        wrong_profile = copy.deepcopy(self.source)
        wrong_profile["provider_profile_bindings"][0]["language_profile_id"] = "fr"
        with self.assertRaises(ValueError):
            RegionRegistry.from_mapping(wrong_profile)

        unknown_provider = copy.deepcopy(self.source)
        unknown_provider["provider_profile_bindings"][0]["provider_id"] = "other"
        with self.assertRaises(ValueError):
            RegionRegistry.from_mapping(unknown_provider)

    def test_planner_excludes_unsupported_profiles_and_copies_exact_encoding(self) -> None:
        fixture = copy.deepcopy(self.source)
        fixture["selected_markets"] = [
            market for market in fixture["selected_markets"] if market["market_id"] != "denmark"
        ]
        fixture["global_targets"] = [target for target in fixture["global_targets"] if target != "denmark"]
        fixture["provider_profile_bindings"] = [
            binding for binding in fixture["provider_profile_bindings"] if binding["market_id"] != "denmark"
        ]
        registry = RegionRegistry.from_mapping(fixture)
        plan = SearchPlanner(registry).plan("selected")
        self.assertNotIn("en", {item.language_profile for item in plan.items if item.market_id == "south_korea"})
        item = next(item for item in plan.items if item.market_id == "south_korea" and item.language_profile == "ko")
        self.assertEqual(item.provider_encoding, GoogleNewsRssEncoding("ko", "KR", "KR:ko"))
        mapped = plan.as_mapping()
        mapped_item = next(entry for entry in mapped["items"] if entry["plan_item_id"] == item.plan_item_id)
        self.assertEqual(mapped_item["provider_encoding"], {"hl": "ko", "gl": "KR", "ceid": "KR:ko"})

    def test_configured_market_without_supported_binding_fails_whole_plan(self) -> None:
        registry = RegionRegistry.from_mapping(self.source)
        with self.assertRaises(ValueError):
            SearchPlanner(registry).plan("selected")


if __name__ == "__main__":
    unittest.main()
