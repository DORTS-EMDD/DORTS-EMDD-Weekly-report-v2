"""The single typed owner of configured Search discovery targets."""

from __future__ import annotations

import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from .contracts import (
    DiscoveryIntent,
    LanguageProfileConfig,
    MarketConfig,
    QueryFamilyConfig,
    RegionMode,
    SearchPlanningLimits,
)


CONFIGURATION_PATH = Path(__file__).with_name("search_configuration.json")


def _tuple_strings(value: Any, field_name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{field_name} must be a list of strings")
    try:
        values = tuple(value)
    except TypeError as exc:
        raise ValueError(f"{field_name} must be a list of strings") from exc
    if any(not isinstance(item, str) or not item.strip() for item in values):
        raise ValueError(f"{field_name} must contain non-empty strings")
    return values


def _is_taiwan_identifier(value: str) -> bool:
    normalized = value.strip().casefold().replace("-", "_")
    return normalized in {"taiwan", "tw"} or normalized.startswith("taiwan_")


class RegionRegistry:
    """Immutable materialized selected/global target and profile registry."""

    __slots__ = (
        "configuration_version",
        "selected_markets",
        "global_targets",
        "global_markets",
        "profiles",
        "query_families",
        "planning_limits",
        "_market_by_id",
        "_profile_by_id",
        "_sealed",
    )

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("RegionRegistry is immutable")
        object.__setattr__(self, name, value)

    def __init__(
        self,
        *,
        configuration_version: str,
        selected_markets: tuple[MarketConfig, ...],
        global_targets: tuple[str, ...],
        global_markets: tuple[MarketConfig, ...],
        profiles: tuple[LanguageProfileConfig, ...],
        query_families: tuple[QueryFamilyConfig, ...],
        planning_limits: SearchPlanningLimits,
    ) -> None:
        if not isinstance(configuration_version, str) or not configuration_version.strip():
            raise ValueError("configuration requires configuration_version")
        self.configuration_version = configuration_version
        self.selected_markets = tuple(selected_markets)
        self.global_targets = tuple(global_targets)
        self.global_markets = tuple(global_markets)
        self.profiles = tuple(profiles)
        self.query_families = tuple(query_families)
        if not isinstance(planning_limits, SearchPlanningLimits):
            raise TypeError("planning_limits must be SearchPlanningLimits")
        self.planning_limits = planning_limits
        self._validate()

        self._market_by_id = MappingProxyType(
            {market.market_id: market for market in (*self.selected_markets, *self.global_markets)}
        )
        self._profile_by_id = MappingProxyType({profile.profile_id: profile for profile in self.profiles})
        object.__setattr__(self, "_sealed", True)

    @classmethod
    def from_file(cls, path: str | Path = CONFIGURATION_PATH) -> "RegionRegistry":
        source = Path(path)
        with source.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        if not isinstance(value, Mapping):
            raise ValueError("Search configuration must be a JSON object")
        return cls.from_mapping(value)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "RegionRegistry":
        if not isinstance(value, Mapping):
            raise TypeError("Search configuration must be a mapping")
        selected = tuple(cls._market_from_mapping(item) for item in value.get("selected_markets", ()))
        global_markets = tuple(cls._market_from_mapping(item) for item in value.get("global_markets", ()))
        profiles = tuple(
            LanguageProfileConfig(
                profile_id=item.get("profile_id", ""),
                display_name=item.get("display_name", ""),
                locale=item.get("locale", ""),
                intent_vocabulary=item.get("intent_vocabulary", {}),
                enabled=item.get("enabled", True),
            )
            for item in value.get("profiles", ())
        )
        families = tuple(
            QueryFamilyConfig(
                family_id=item.get("family_id", ""),
                templates=_tuple_strings(item.get("templates", ()), "query family templates"),
                anchor_terms=_tuple_strings(item.get("anchor_terms", ()), "query family anchor terms"),
                vocabulary_groups=item.get("vocabulary_groups", {}),
                provider_target=item.get("provider_target", ""),
            )
            for item in value.get("query_families", ())
        )
        intents = value.get("discovery_intents", ())
        expected_intents = tuple(
            {"id": intent.value, "display_label": intent.display_label} for intent in DiscoveryIntent
        )
        if tuple(intents) != expected_intents:
            raise ValueError("discovery_intents must match the canonical typed mapping")
        modes = tuple(value.get("region_modes", ()))
        if modes != tuple(mode.value for mode in RegionMode):
            raise ValueError("region_modes must declare selected and global")
        return cls(
            configuration_version=value.get("configuration_version", ""),
            selected_markets=selected,
            global_targets=_tuple_strings(value.get("global_targets", ()), "global_targets"),
            global_markets=global_markets,
            profiles=profiles,
            query_families=families,
            planning_limits=cls._planning_limits_from_mapping(value.get("planning_limits", {})),
        )

    @staticmethod
    def _planning_limits_from_mapping(value: Any) -> SearchPlanningLimits:
        if not isinstance(value, Mapping):
            raise ValueError("planning_limits must be an object")
        return SearchPlanningLimits(
            max_concrete_requests_per_family=value.get("max_concrete_requests_per_family", 0),
            max_plan_items=value.get("max_plan_items", 0),
        )

    @staticmethod
    def _market_from_mapping(value: Any) -> MarketConfig:
        if not isinstance(value, Mapping):
            raise ValueError("market configuration must be an object")
        return MarketConfig(
            market_id=value.get("market_id", ""),
            display_name=value.get("display_name", ""),
            primary_profiles=_tuple_strings(value.get("primary_profiles", ()), "primary_profiles"),
            secondary_profiles=_tuple_strings(value.get("secondary_profiles", ()), "secondary_profiles"),
            english_supplement_profiles=_tuple_strings(
                value.get("english_supplement_profiles", ()), "english_supplement_profiles"
            ),
            locale_hints=_tuple_strings(value.get("locale_hints", ()), "locale_hints"),
            terminology_refs=_tuple_strings(value.get("terminology_refs", ()), "terminology_refs"),
            enabled=value.get("enabled", True),
        )

    def _validate(self) -> None:
        all_markets = (*self.selected_markets, *self.global_markets)
        market_ids = tuple(market.market_id for market in all_markets)
        if len(market_ids) != len(set(market_ids)):
            raise ValueError("market IDs must be unique across registry configuration")
        if any(_is_taiwan_identifier(market.market_id) or _is_taiwan_identifier(market.display_name) for market in all_markets):
            raise ValueError("Taiwan is forbidden in Search target configuration")
        if any(not isinstance(market.enabled, bool) for market in all_markets):
            raise TypeError("market enabled must be bool")

        profile_ids = tuple(profile.profile_id for profile in self.profiles)
        if len(profile_ids) != len(set(profile_ids)):
            raise ValueError("profile IDs must be unique")
        if any(not isinstance(profile.enabled, bool) for profile in self.profiles):
            raise TypeError("profile enabled must be bool")
        if any(not profile.enabled for profile in self.profiles):
            raise ValueError("configured profiles must not be disabled")
        if any(not market.enabled for market in all_markets):
            raise ValueError("configured markets must not be disabled")
        known_profiles = set(profile_ids)
        for market in all_markets:
            referenced = (
                *market.primary_profiles,
                *market.secondary_profiles,
                *market.english_supplement_profiles,
            )
            if not referenced or any(profile_id not in known_profiles for profile_id in referenced):
                raise ValueError("market profile references must resolve")
        if len(self.global_targets) != len(set(self.global_targets)):
            raise ValueError("global target IDs must be unique")
        if any(_is_taiwan_identifier(target) for target in self.global_targets):
            raise ValueError("Taiwan is forbidden in global target configuration")
        known_market_ids = set(market_ids)
        if any(target not in known_market_ids for target in self.global_targets):
            raise ValueError("global targets must resolve to governed market configuration")
        if not self.query_families:
            raise ValueError("at least one bounded query family is required")
        family_ids = tuple(family.family_id for family in self.query_families)
        if len(family_ids) != len(set(family_ids)):
            raise ValueError("query family IDs must be unique")
        for family in self.query_families:
            for intent in DiscoveryIntent:
                if any(
                    group not in profile.intent_vocabulary[intent.value]
                    for profile in self.profiles
                    for group in family.vocabulary_groups[intent.value]
                ):
                    raise ValueError("query family references an unknown vocabulary group")

    @property
    def selected_profile_ids(self) -> tuple[str, ...]:
        return tuple(profile.profile_id for profile in self.profiles)

    @property
    def selected_market_count(self) -> int:
        return len(self.selected_markets)

    @property
    def global_target_count(self) -> int:
        return len(self.global_targets)

    def markets_for(self, mode: RegionMode | str) -> tuple[MarketConfig, ...]:
        mode = RegionMode(mode)
        if mode is RegionMode.SELECTED:
            return self.selected_markets
        return tuple(self._market_by_id[target] for target in self.global_targets)

    def market(self, market_id: str) -> MarketConfig:
        return self._market_by_id[market_id]

    def profile(self, profile_id: str) -> LanguageProfileConfig:
        return self._profile_by_id[profile_id]

    def profiles_for_market(self, market: MarketConfig) -> tuple[str, ...]:
        profiles = (*market.primary_profiles, *market.secondary_profiles, *market.english_supplement_profiles)
        return profiles

    def as_mapping(self) -> dict[str, Any]:
        def market_mapping(market: MarketConfig) -> dict[str, Any]:
            return {
                "market_id": market.market_id,
                "display_name": market.display_name,
                "primary_profiles": list(market.primary_profiles),
                "secondary_profiles": list(market.secondary_profiles),
                "english_supplement_profiles": list(market.english_supplement_profiles),
                "locale_hints": list(market.locale_hints),
                "terminology_refs": list(market.terminology_refs),
                "enabled": market.enabled,
            }

        return {
            "configuration_version": self.configuration_version,
            "region_modes": [mode.value for mode in RegionMode],
            "selected_markets": [market_mapping(market) for market in self.selected_markets],
            "global_targets": list(self.global_targets),
            "global_markets": [market_mapping(market) for market in self.global_markets],
            "profiles": [
                {
                    "profile_id": profile.profile_id,
                    "display_name": profile.display_name,
                    "locale": profile.locale,
                    "intent_vocabulary": {
                        intent: {group: list(terms) for group, terms in groups.items()}
                        for intent, groups in profile.intent_vocabulary.items()
                    },
                    "enabled": profile.enabled,
                }
                for profile in self.profiles
            ],
            "discovery_intents": [
                {"id": intent.value, "display_label": intent.display_label} for intent in DiscoveryIntent
            ],
            "query_families": [
                {
                    "family_id": family.family_id,
                    "templates": list(family.templates),
                    "anchor_terms": list(family.anchor_terms),
                    "vocabulary_groups": {key: list(value) for key, value in family.vocabulary_groups.items()},
                    "provider_target": family.provider_target,
                }
                for family in self.query_families
            ],
            "planning_limits": {
                "max_concrete_requests_per_family": self.planning_limits.max_concrete_requests_per_family,
                "max_plan_items": self.planning_limits.max_plan_items,
            },
        }
