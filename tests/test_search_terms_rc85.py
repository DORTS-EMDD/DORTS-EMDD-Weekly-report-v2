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
    assert all('"metro train"' in query for query in _queries("en", "procurement"))
    for intent in ("major_incident", "operations"):
        assert all('"metro train"' in query and '"metro trains"' in query for query in _queries("en", intent))
    # Technology is unchanged: one more phrase would split every technology request.
    assert not any("metro train" in query for query in _queries("en", "technology"))


def test_norwegian_compounds():
    for intent in ("major_incident", "operations", "procurement"):
        assert all("intitle:T-banetog" in query and "intitle:T-banevogner" in query for query in _queries("no", intent))


def test_every_query_fits_and_the_plan_size():
    assert all(len(item.query.replace("(", " ").replace(")", " ").split()) <= 32 for item in PLAN.items)
    assert len(PLAN.items) == 239
