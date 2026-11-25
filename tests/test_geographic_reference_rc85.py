"""RC-85 (section A.66): Polish and Czech case forms resolve (geo-reference-v8).

Polish and Czech sources write places in their case forms ("w Krakowie",
"v Praze", "do Německa"). The metadata helper copies the exact source surface
value, so the reference lists these forms as names of their own. There is no
suffix inference: a form that is not listed still does not resolve.
"""

from __future__ import annotations

import pytest

from src.weekly_report.geographic_reference import GeographicMatchKind, GeographicReference

REFERENCE = GeographicReference.from_file()


def _resolve(value):
    match = REFERENCE.lookup(value) or REFERENCE.lookup_contained(value)
    return None if match is None else (match.kind, match.region_id)


@pytest.mark.parametrize(
    "value, region",
    [
        # Run 45103217994 / 44919705575 values left REGION_NOT_ESTABLISHED.
        ("Krakowie", "PL"), ("Warszawie", "PL"), ("Toruniu", "PL"), ("Gorzowie Wielkopolskim", "PL"),
        ("Konstantynów Łódzki", "PL"), ("Łodzi", "PL"), ("Bydgoszczy", "PL"), ("warszawskie metro", "PL"),
        ("Praze", "CZ"), ("pražských Nuslích", "CZ"), ("Brně", "CZ"), ("Olomouci", "CZ"),
        ("Londynie", "GB"), ("Paryżu", "FR"), ("Vídni", "AT"),
    ],
)
def test_case_forms_of_designated_cities_resolve(value, region):
    kind, region_id = _resolve(value)
    assert kind is GeographicMatchKind.CITY
    assert region_id == region


@pytest.mark.parametrize("value, region", [("Německa", "DE"), ("Niemczech", "DE"), ("Polsce", "PL"), ("Česku", "CZ")])
def test_case_forms_of_country_names_resolve(value, region):
    assert _resolve(value) == (GeographicMatchKind.REGION, region)


def test_there_is_no_suffix_inference():
    # An unlisted form of a listed city stays unresolved.
    assert _resolve("Krakowowi") is None
    assert REFERENCE.version == "geo-reference-v8"
