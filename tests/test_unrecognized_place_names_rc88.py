"""RC-88 (user decision 2026-11-26, observation only): metadata place names the
geographic reference does not recognise are recorded for extending it later.

EvidenceService records them on its own RegionResolution; the selection audit
projects them under the RC-69 public-exposure policy. No decision reads them:
the resolution's basis, region and diagnostic are unchanged."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.weekly_report.contracts import RegionResolution, RegionResolutionBasis
from src.weekly_report.selection_audit import _region
from tests.test_geographic_resolution import _resolve


def test_unrecognised_values_are_recorded_and_the_decision_is_unchanged():
    resolution = _resolve(location="Nowheresville", system="Imaginary Line")
    assert (resolution.basis, resolution.diagnostic) == (RegionResolutionBasis.UNRESOLVED, "UNRECOGNIZED_VALUE")
    assert resolution.unrecognized_values == (("transit_system_name", "Imaginary Line"), ("location", "Nowheresville"))


def test_an_established_region_also_records_the_values_it_did_not_recognise():
    resolution = _resolve(country="Japan", location="Nowheresville")
    assert resolution.established and resolution.region_id
    assert resolution.unrecognized_values == (("location", "Nowheresville"),)


def test_recognised_and_absent_values_are_not_recorded():
    assert _resolve(country="Japan").unrecognized_values == ()
    assert _resolve().unrecognized_values == ()


def test_only_governed_fields_and_text_values():
    with pytest.raises(ValueError):
        RegionResolution(RegionResolutionBasis.NOT_STATED, unrecognized_values=(("publisher", "X"),))
    with pytest.raises(ValueError):
        RegionResolution(RegionResolutionBasis.NOT_STATED, unrecognized_values=(("location", " "),))


def _audit_region(resolution):
    return _region(SimpleNamespace(identity_facts=SimpleNamespace(region_resolution=resolution)))


def test_the_audit_shows_short_place_names_and_withholds_anything_else():
    long_value = "x" * 81
    resolution = RegionResolution(
        RegionResolutionBasis.UNRESOLVED,
        diagnostic="UNRECOGNIZED_VALUE",
        unrecognized_values=(
            ("location", "Nowheresville"),
            ("location", long_value),
            ("transit_system_name", "Line​ 9"),
            ("location", "See https://example.test"),
        ),
    )
    entry = _audit_region(resolution)
    assert entry["diagnostic"] == "UNRECOGNIZED_VALUE"
    shown = entry["unrecognized_values"]
    assert shown[0] == {"field": "location", "value": "Nowheresville"}
    assert shown[1]["value"]["withheld"] == "SIZE_BOUND" and "sha256" in shown[1]["value"]
    assert shown[2]["value"]["withheld"] == "CONTENT_BOUND"
    assert shown[3]["value"]["withheld"] == "CONTENT_BOUND"
    assert long_value not in str(entry)


def test_nothing_is_added_without_unrecognised_values():
    assert "unrecognized_values" not in _audit_region(_resolve(country="Japan"))
