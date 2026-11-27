"""RC-76 (section A.57, user decision 2026-11-19): 27 designated regions.

Principle: technologically advanced countries. Mainland China is not designated;
Hong Kong stays designated. Added: Finland, Belgium, Czechia, Israel, Ireland,
Poland and New Zealand.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from src.weekly_report.geographic_reference import default_geographic_reference
from src.weekly_report.production_runner import HEALTH_PROBE_ORDINALS
from src.weekly_report.region_registry import CONFIGURATION_PATH, RegionRegistry
from src.weekly_report.report_service import ReportService
from src.weekly_report.search_planner import SearchPlanner
from tests.test_golden_contract import GOLDEN, _materialize_ordering_case

REGISTRY = RegionRegistry.from_file()
NEW_REGIONS = {"FI", "BE", "CZ", "IL", "IE", "PL", "NZ"}


def _event(event_id: str, value: str, region_id: str, basis: str = "REFERENCE_MAPPED") -> dict:
    return {
        "event_id": event_id,
        "reportability_state": "REPORTABLE",
        "canonical_member_candidate_id": f"candidate-{event_id}",
        "members": [
            {
                "candidate_id": f"candidate-{event_id}",
                "canonical": True,
                "country": {"basis": basis, "value": value, "region_id": region_id, "display_name": value},
                "temporal": {"date_valid": True, "controlling_calendar_date": "2026-11-12"},
            }
        ],
    }


def _project(events: list[dict]):
    fixture = json.loads((GOLDEN / "cases/region_non_designated_event.json").read_text(encoding="utf-8"))
    fixture = copy.deepcopy(fixture)
    fixture["input"]["events"] = events
    service = ReportService(formal_region_ids=REGISTRY.formal_region_ids)
    return service.project_formal_metadata_population(_materialize_ordering_case(fixture))


def test_the_designated_set_is_the_27_market_regions():
    assert len(REGISTRY.formal_region_ids) == 27 == REGISTRY.selected_market_count
    assert NEW_REGIONS <= REGISTRY.formal_region_ids


def test_mainland_china_stays_non_designated_and_hong_kong_stays_designated():
    reference = default_geographic_reference()
    for name in ("Shanghai", "上海", "北京", "Shenzhen Metro", "China", "中国大陆"):
        assert reference.lookup(name).region_id == "CN", name
    for name in ("Hong Kong", "香港", "홍콩"):
        assert reference.lookup(name).region_id == "HK", name
    assert "CN" not in REGISTRY.formal_region_ids
    assert "HK" in REGISTRY.formal_region_ids
    projection = _project([_event("shanghai", "上海", "CN"), _event("hong-kong", "香港", "HK")])
    assert [item.event_id for item in projection.metadata] == ["hong-kong"]
    assert {item.event_id: item.reason.value for item in projection.exclusions} == {"shanghai": "NON_DESIGNATED_REGION"}


@pytest.mark.parametrize(
    "name, region",
    [
        ("Helsinki", "FI"), ("Helsingfors", "FI"), ("Tampere", "FI"), ("헬싱키", "FI"),
        ("Bruxelles", "BE"), ("Brussel", "BE"), ("Antwerpen", "BE"), ("Liège", "BE"),
        ("Praha", "CZ"), ("Prague", "CZ"), ("Brno", "CZ"), ("プラハ", "CZ"),
        ("Tel Aviv", "IL"), ("תל אביב", "IL"), ("Jerusalem", "IL"), ("ירושלים", "IL"),
        ("Dublin", "IE"), ("Luas", "IE"),
        ("Warszawa", "PL"), ("Warsaw", "PL"), ("Kraków", "PL"), ("바르샤바", "PL"),
        ("Auckland", "NZ"), ("Wellington", "NZ"),
    ],
)
def test_the_new_regions_cities_resolve_to_their_region(name, region):
    match = default_geographic_reference().lookup(name)
    assert match is not None and match.region_id == region, name


def test_an_event_in_a_new_region_is_now_eligible():
    projection = _project([_event("helsinki", "Helsinki", "FI"), _event("warsaw", "Warszawa", "PL")])
    assert [item.event_id for item in projection.metadata] == ["helsinki", "warsaw"]
    assert not projection.exclusions


def test_finland_is_searched_and_denmark_stays_the_only_coverage_gap():
    # RC-78 (2026-11-20): FI:fi answered with a redirect to hl=fi-FI on the same
    # edition; DK:da redirected to the Norwegian edition (no Danish edition).
    plan = SearchPlanner(REGISTRY).plan("selected")
    assert tuple(gap.market_id for gap in plan.coverage.gaps) == ("denmark",)
    finnish = [item for item in plan.items if item.market_id == "finland"]
    assert finnish and {item.language_profile for item in finnish} == {"fi"}
    assert {(item.provider_encoding.hl, item.provider_encoding.gl, item.provider_encoding.ceid) for item in finnish} == {
        ("fi-FI", "FI", "FI:fi")
    }
    assert not any(item.market_id == "denmark" for item in plan.items)


def test_health_probes_are_spread_over_the_new_plan():
    size = len(SearchPlanner(REGISTRY).plan("selected").items)
    assert size == 599  # RC-90 (search-discovery-v15 as amended); RC-88 728; RC-85 239; RC-78 231, RC-77 221, RC-76 210
    assert HEALTH_PROBE_ORDINALS == (1, 10, size // 2, size // 2 + 5, size - 7, size)


def test_israel_searches_hebrew_and_english_and_belgium_dutch_and_french():
    plan = SearchPlanner(REGISTRY).plan("selected")
    editions = {(item.market_id, item.language_profile) for item in plan.items}
    assert {("israel", "he"), ("israel", "en"), ("belgium", "nl"), ("belgium", "fr"),
            ("czechia", "cs"), ("poland", "pl"), ("ireland", "en"), ("new_zealand", "en")} <= editions
    assert ("belgium", "en") not in editions and ("czechia", "en") not in editions
