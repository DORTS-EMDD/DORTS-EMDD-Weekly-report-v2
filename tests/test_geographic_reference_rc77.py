"""RC-77 (section A.58): Frankfurt, Kitchener and Vitoria-Gasteiz resolve (geo-reference-v7).

Root causes (recall test Run 44468386445, REGION_NOT_ESTABLISHED):
* "Frankfurt" was listed in ambiguous_names although every Frankfurt with urban
  rail is in Germany (Frankfurt am Main; Frankfurt (Oder) is German too), and the
  German city adjective "Frankfurter" (as in "Frankfurter Bahnhofsviertel") was
  missing, unlike Berliner or Münchner.
* Kitchener (ION LRT, Region of Waterloo, Ontario) was not in the reference.
* Spain listed only the full "Vitoria-Gasteiz"; a source writing "Vitoria" or
  "Gasteiz" had no match.
The matching rule (whole value, then contained names on word boundaries) is unchanged.
"""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.weekly_report.geographic_reference import GeographicMatchKind, GeographicReference  # noqa: E402

REFERENCE = GeographicReference.from_file()


def _region(value: str) -> str | None:
    match = REFERENCE.lookup(value) or REFERENCE.lookup_contained(value)
    return None if match is None or match.kind is GeographicMatchKind.AMBIGUOUS else match.region_id


@pytest.mark.parametrize(
    "value, region",
    [
        ("Frankfurt", "DE"),
        ("Frankfurt am Main", "DE"),
        ("Frankfurter Bahnhofsviertel", "DE"),
        ("Kitchener", "CA"),
        ("Kitchener, Ontario", "CA"),
        ("Kitchener-Waterloo", "CA"),
        ("Region of Waterloo", "CA"),
        ("ION LRT", "CA"),
        ("Vitoria", "ES"),
        ("Gasteiz", "ES"),
        ("Vitoria-Gasteiz", "ES"),
    ],
)
def test_the_three_cities_resolve(value, region):
    assert _region(value) == region


def test_names_shared_by_regions_stay_ambiguous():
    # Waterloo (London station, Belgium, Ontario) and Victoria are unchanged.
    assert REFERENCE.lookup("Waterloo").kind is GeographicMatchKind.AMBIGUOUS
    assert REFERENCE.lookup("Victoria").kind is GeographicMatchKind.AMBIGUOUS


def test_reference_version():
    assert REFERENCE.version == "geo-reference-v8"
