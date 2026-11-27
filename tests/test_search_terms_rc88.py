"""RC-88 (external review item 1): Traditional and Simplified Chinese forms are separate OR terms."""

from __future__ import annotations

import copy
import re
import json
from datetime import date
from pathlib import Path

import pytest

from src.weekly_report.contracts import SearchWindow
from src.weekly_report.region_registry import RegionRegistry
from src.weekly_report.search_planner import SearchPlanner

SOURCE = json.loads((Path(__file__).resolve().parents[1] / "src" / "weekly_report" / "search_configuration.json").read_text(encoding="utf-8"))
PLAN = SearchPlanner(RegionRegistry.from_file()).plan("selected", window=SearchWindow(date(2026, 11, 16), date(2026, 11, 22)))


def test_no_chinese_query_joins_two_forms_with_a_slash():
    zh = [item.query for item in PLAN.items if item.language_profile == "zh"]
    assert zh and not any("/" in query for query in zh)


def test_both_forms_are_separate_or_terms():
    zh = [item.query for item in PLAN.items if item.language_profile == "zh"]
    for traditional, simplified in (("號誌", "信号"), ("脫軌", "脱轨"), ("招標", "招标"), ("人工智慧", "人工智能")):
        # Each form is its own OR term (RC-88); packing may place them in different requests.
        for form in (traditional, simplified):
            assert any(re.search(rf"[( ]{re.escape(form)}[ )]", query) for query in zh), form
        assert not any(f"{traditional}/{simplified}" in query for query in zh)


def test_taiwan_and_hong_kong_request_counts():
    counts = {market: sum(1 for item in PLAN.items if item.market_id == market and item.language_profile == "zh")
              for market in ("taiwan", "hong_kong")}
    # RC-85: 7 each; 11 with the split; 40 with 155-character queries; RC-90: 39
    # (operations 2 not planned, major incident 4 -> 3 in the compact packing).
    assert counts == {"taiwan": 39, "hong_kong": 39}


def test_a_slash_joined_term_is_rejected_by_the_registry():
    source = copy.deepcopy(SOURCE)
    zh = next(profile for profile in source["profiles"] if profile["profile_id"] == "zh")
    zh["intent_vocabulary"]["procurement"]["tender_terms"][0] = "招標/招标"
    with pytest.raises(ValueError, match="must not join alternatives"):
        RegionRegistry.from_mapping(source)
