"""Deterministic offline Search planning over the RegionRegistry seam."""

from __future__ import annotations

import hashlib
import json
from typing import Iterable

from .contracts import (
    DiscoveryIntent,
    ProviderProfileEligibility,
    QueryFamilyConfig,
    RegionMode,
    SearchCoverageGap,
    SearchCoverageGapReason,
    SearchCoverageProjection,
    SearchPlan,
    SearchPlanItem,
)
from .region_registry import RegionRegistry


def _stable_digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class SearchPlanner:
    """The only owner of deterministic discovery plan construction."""

    def __init__(self, registry: RegionRegistry) -> None:
        if not isinstance(registry, RegionRegistry):
            raise TypeError("SearchPlanner requires a RegionRegistry")
        self._registry = registry

    def plan(
        self,
        mode: RegionMode | str,
        intents: Iterable[DiscoveryIntent | str] | None = None,
    ) -> SearchPlan:
        mode = RegionMode(mode)
        selected_intents = self._canonical_intents(intents)
        items: list[SearchPlanItem] = []
        configured_markets = self._registry.markets_for(mode)
        configured_market_ids = tuple(market.market_id for market in configured_markets)
        intent_item_counts = {intent: 0 for intent in selected_intents}
        coverage_gaps: list[SearchCoverageGap] = []
        for market in configured_markets:
            profiles = self._registry.profiles_for_market(market)
            market_has_supported_binding = False
            market_binding_count = 0
            for intent in selected_intents:
                for profile_id in profiles:
                    for family in self._registry.query_families:
                        market_binding_count += 1
                        binding = self._registry.provider_profile_binding(
                            market.market_id, profile_id, family.provider_target
                        )
                        if binding.eligibility is ProviderProfileEligibility.UNSUPPORTED:
                            continue
                        market_has_supported_binding = True
                        encoding = binding.encoding
                        if encoding is None:
                            raise ValueError("supported provider profile binding has no encoding")
                        concrete = self._concrete_queries(market, profile_id, intent, family)
                        for query in concrete:
                            payload = {
                                "configuration_version": self._registry.configuration_version,
                                "region_mode": mode.value,
                                "market_id": market.market_id,
                                "intent": intent.value,
                                "language_profile": profile_id,
                                "query_family_id": family.family_id,
                                "provider_target": family.provider_target,
                                "query": query,
                                "locale": self._registry.profile(profile_id).locale,
                                "provider_encoding": {
                                    "hl": encoding.hl,
                                    "gl": encoding.gl,
                                    "ceid": encoding.ceid,
                                },
                            }
                            items.append(
                                SearchPlanItem(
                                    plan_item_id=f"search_{_stable_digest(payload)}",
                                    market_id=market.market_id,
                                    region_mode=mode,
                                    intent=intent,
                                    language_profile=profile_id,
                                    query_family_id=family.family_id,
                                    provider_target=family.provider_target,
                                    query=query,
                                    locale=self._registry.profile(profile_id).locale,
                                    provider_encoding=encoding,
                                )
                            )
                            intent_item_counts[intent] += 1
                            if len(items) > self._registry.planning_limits.max_plan_items:
                                raise ValueError("Search plan exceeds bounded item limit")
            if market_binding_count == 0:
                raise ValueError("Search plan market has no required provider bindings")
            if not market_has_supported_binding:
                coverage_gaps.append(
                    SearchCoverageGap(
                        market.market_id,
                        SearchCoverageGapReason.KNOWN_UNSUPPORTED_PROVIDER_CAPABILITY,
                    )
                )
        if any(count == 0 for count in intent_item_counts.values()):
            raise ValueError("Search plan has an enabled intent with no executable provider coverage")
        if not items:
            raise ValueError("Search plan has no executable provider coverage")

        # The loops consume ordered tuples from the registry. Sorting here is
        # an explicit final canonical order and cannot depend on hash iteration.
        items.sort(key=lambda item: (item.market_id, item.intent.value, item.language_profile,
                                     item.query_family_id, item.provider_target, item.query,
                                     item.provider_encoding.hl, item.provider_encoding.gl,
                                     item.provider_encoding.ceid))
        plan_payload = {
            "configuration_version": self._registry.configuration_version,
            "region_mode": mode.value,
            "coverage": SearchCoverageProjection(
                SearchCoverageProjection.VERSION,
                configured_market_ids,
                tuple(coverage_gaps),
            ).as_mapping(),
            "items": [
                {
                    "plan_item_id": item.plan_item_id,
                    "market_id": item.market_id,
                    "intent": item.intent.value,
                    "language_profile": item.language_profile,
                    "query_family_id": item.query_family_id,
                    "provider_target": item.provider_target,
                    "query": item.query,
                    "locale": item.locale,
                    "provider_encoding": {
                        "hl": item.provider_encoding.hl,
                        "gl": item.provider_encoding.gl,
                        "ceid": item.provider_encoding.ceid,
                    },
                }
                for item in items
            ],
        }
        coverage = SearchCoverageProjection(
            SearchCoverageProjection.VERSION,
            configured_market_ids,
            tuple(coverage_gaps),
        )
        return SearchPlan(
            configuration_version=self._registry.configuration_version,
            region_mode=mode,
            items=tuple(items),
            plan_id=f"plan_{_stable_digest(plan_payload)}",
            coverage=coverage,
        )

    @staticmethod
    def _canonical_intents(intents: Iterable[DiscoveryIntent | str] | None) -> tuple[DiscoveryIntent, ...]:
        if intents is None:
            return tuple(DiscoveryIntent)
        values = tuple(DiscoveryIntent(intent) for intent in intents)
        if not values:
            raise ValueError("SearchPlanner requires at least one discovery intent")
        if len(values) != len(set(values)):
            raise ValueError("SearchPlanner intents must be unique")
        return tuple(intent for intent in DiscoveryIntent if intent in values)

    def _concrete_queries(self, market, profile_id: str, intent: DiscoveryIntent, family: QueryFamilyConfig) -> tuple[str, ...]:
        profile = self._registry.profile(profile_id)
        intent_terms: list[str] = []
        for group_name in family.vocabulary_groups[intent.value]:
            intent_terms.extend(profile.intent_vocabulary[intent.value][group_name])
        if not intent_terms:
            raise ValueError("query family resolved no governed vocabulary terms")
        intent_terms = tuple(intent_terms)
        anchors = family.anchor_terms or ("",)
        combinations = len(family.templates) * len(anchors) * len(intent_terms)
        if combinations > self._registry.planning_limits.max_concrete_requests_per_family:
            raise ValueError("query family exceeds bounded concrete request limit")
        queries: list[str] = []
        for template in family.templates:
            for anchor in anchors:
                for intent_term in intent_terms:
                    try:
                        query = template.format(
                            market=market.display_name,
                            market_id=market.market_id,
                            profile=profile_id,
                            intent=intent.value,
                            intent_label=intent.display_label,
                            anchor=anchor,
                            intent_term=intent_term,
                        )
                    except (KeyError, IndexError, ValueError) as exc:
                        raise ValueError("query family template has unsupported placeholders") from exc
                    if not isinstance(query, str) or not query.strip():
                        raise ValueError("query family generated an empty query")
                    queries.append(query.strip())
        if len(queries) != len(set(queries)):
            raise ValueError("query family generated duplicate concrete queries")
        return tuple(queries)
