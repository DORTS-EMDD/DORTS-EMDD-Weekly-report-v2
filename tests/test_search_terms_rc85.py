"""RC-85 (section A.66): "metro train" mode phrases (English) and T-bane compounds (Norwegian).

The CAF order for 24 more Oslo metro trains (2026-11-17) was never a candidate:
its English title ("Oslo increases CAF metro train order") contains none of the
English mode phrases, and Norwegian writes the compound "T-banetog".
"""

from __future__ import annotations

from datetime import date

from src.weekly_report.contracts import SearchWindow
from src.weekly_report.region_registry import RegionRegistry
from src.weekly_report.search_planner import SearchPlanner

PLAN = SearchPlanner(RegionRegistry.from_file()).plan("selected", window=SearchWindow(date(2026, 11, 16), date(2026, 11, 22)))


def _queries(profile, intent):
    return [item.query for item in PLAN.items if item.language_profile == profile and item.intent.value == intent]


def test_english_metro_train_phrases():
    # RC-88: a mode group may be split across requests to fit 155 characters,
    # so each phrase is searched in some request of every English edition.
    # RC-90: operations is not planned; major_incident uses the compact family.
    for intent, phrases in (("procurement", ('"metro train"',)), ("major_incident", ('"metro train"', '"metro trains"'))):
        markets = {item.market_id for item in PLAN.items if item.language_profile == "en" and item.intent.value == intent
                   and item.query_family_id.startswith("urban_rail_or_groups")}
        assert len(markets) == 8, intent
        for market in markets:
            queries = [item.query for item in PLAN.items if item.market_id == market and item.language_profile == "en"
                       and item.intent.value == intent and item.query_family_id.startswith("urban_rail_or_groups")]
            assert all(any(phrase in query for query in queries) for phrase in phrases), (market, intent)
    # Technology is unchanged.
    assert not any("metro train" in query for query in _queries("en", "technology"))


def test_norwegian_compounds():
    for intent in ("major_incident", "procurement"):
        assert all("intitle:T-banetog" in query and "intitle:T-banevogner" in query for query in _queries("no", intent))


def test_every_query_fits_and_the_plan_size():
    # RC-90: the 155-character bound applies to the character-packed families;
    # the compact major-incident family is packed to 30 words.
    assert all(len(item.query) <= 155 for item in PLAN.items if item.query_family_id != "urban_rail_or_groups_compact")
    assert len(PLAN.items) == 599  # RC-90 (RC-88: 728; RC-85: 239)
