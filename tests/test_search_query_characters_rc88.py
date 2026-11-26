"""RC-88 (user decision 2026-11-26): Google News reads the first 200 characters
of a query; planned queries have at most 155 characters (200 - 35 for the
leading date operators - 10 margin). Packing only regroups terms into
requests: every mode term is still searched together with every intent term."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
import re

from src.weekly_report.contracts import SearchWindow
from src.weekly_report.region_registry import RegionRegistry
from src.weekly_report.search_planner import (
    _DATE_OPERATOR_CHARACTERS,
    _GOOGLE_QUERY_CHARACTERS,
    _MAX_QUERY_CHARACTERS,
    SearchPlanner,
)

REGISTRY = RegionRegistry.from_file()
PLAN = SearchPlanner(REGISTRY).plan("selected", window=SearchWindow(date(2026, 11, 16), date(2026, 11, 22)))
_TWO_GROUPS = re.compile(r"^\(([^()]*)\) \(([^()]*)\)$")


def test_the_bound():
    assert (_GOOGLE_QUERY_CHARACTERS, _DATE_OPERATOR_CHARACTERS, _MAX_QUERY_CHARACTERS) == (200, 35, 155)
    assert all(len(item.query) <= 155 for item in PLAN.items)
    assert len(PLAN.items) == 728


def _bare(term: str) -> str:
    return term.removeprefix("intitle:").strip('"')


def test_every_mode_term_meets_every_intent_term():
    pairs = defaultdict(set)
    modes = defaultdict(set)
    intents = defaultdict(set)
    for item in PLAN.items:
        match = _TWO_GROUPS.match(item.query)
        if item.query_family_id != "urban_rail_or_groups" or not match:
            continue
        key = (item.market_id, item.language_profile, item.intent.value)
        first = [_bare(t) for t in match.group(1).split(" OR ")]
        second = [_bare(t) for t in match.group(2).split(" OR ")]
        modes[key].update(first)
        intents[key].update(second)
        pairs[key].update((m, i) for m in first for i in second)
    assert pairs
    for key in pairs:
        assert pairs[key] == {(m, i) for m in modes[key] for i in intents[key]}, key


def test_the_configured_vocabulary_is_all_searched():
    for market, language, intent in (("finland", "fi", "major_incident"), ("taiwan", "zh", "technology"),
                                      ("united_kingdom", "en", "operations"), ("poland", "pl", "procurement")):
        profile = REGISTRY.profile(language)
        family = next(f for f in REGISTRY.query_families if f.family_id == "urban_rail_or_groups")
        groups = ("urban_rail_terms", *family.vocabulary_groups[intent])
        vocabulary = {group: profile.intent_vocabulary[intent].get(group, ()) for group in groups}
        searched = " ".join(
            item.query for item in PLAN.items
            if (item.market_id, item.language_profile, item.intent.value) == (market, language, intent)
            and item.query_family_id == "urban_rail_or_groups"
        )
        for group, terms in vocabulary.items():
            for term in terms:
                assert term in searched, (market, intent, group, term)


def test_the_trade_press_queries_fit_with_the_same_sites():
    trade = [item.query for item in PLAN.items if item.query_family_id == "rail_trade_press"]
    assert len(trade) == 2 and all(len(query) <= 155 for query in trade)
