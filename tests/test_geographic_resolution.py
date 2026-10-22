"""RC-4: deterministic, versioned country/region resolution owned by EvidenceService."""

from __future__ import annotations

import unittest

from src.weekly_report.contracts import (
    CanonicalCandidate,
    FetchedSource,
    RegionResolution,
    RegionResolutionBasis,
)
from src.weekly_report.evidence_service import EvidenceService
from src.weekly_report.geographic_reference import (
    GeographicMatchKind,
    GeographicReference,
    default_geographic_reference,
)


def _resolve(country=None, system=None, location=None, unresolved=()):
    owner = EvidenceService(fetcher=lambda _url: None)
    return owner._resolve_region(
        {"country": country, "transit_system_name": system, "location": location},
        tuple(unresolved),
    )


def _evaluate(observations, body):
    def judge(request):
        return {
            "relation": "SAME_EVENT",
            "support_evidence": [{"segment_id": s.segment_id, "exact_quote": s.text} for s in request.principal_body_segments],
            "conflict_evidence": [],
            "explanation": "grounded",
        }

    service = EvidenceService(
        lambda _url: FetchedSource("https://source.test/a", f"<html><body><article><p>{body}</p></article></body></html>"),
        semantic_judge=judge,
        metadata_extractor=lambda _request: {
            "observations": [
                {"field_name": field, "value": value, "segment_id": "body-0001"} for field, value in observations
            ]
        },
    )
    return service.evaluate(
        CanonicalCandidate("C1", "Vietnam headline", "https://source.test/a", publisher="Japan Publisher")
    )


class GeographicReferenceTests(unittest.TestCase):
    def test_reference_is_versioned_and_matches_whole_values_only(self):
        reference = default_geographic_reference()
        self.assertEqual(reference.version, "geo-reference-v2")
        self.assertEqual(reference.lookup("vietnam").kind, GeographicMatchKind.REGION)
        self.assertEqual(reference.lookup("Hanoi Metro").kind, GeographicMatchKind.SYSTEM)
        self.assertEqual(reference.lookup("Hanoi").kind, GeographicMatchKind.CITY)
        self.assertIsNone(reference.lookup("Hanoi Metro Line 3"))
        self.assertIsNone(reference.lookup("Hano"))

    def test_same_name_in_two_regions_is_ambiguous_and_never_resolves(self):
        reference = GeographicReference(
            {
                "reference_version": "test-v1",
                "regions": [
                    {"region_id": "AA", "display_name": "甲", "names": ["Aland"]},
                    {"region_id": "BB", "display_name": "乙", "names": ["Bland"]},
                ],
                "places": [
                    {"region_id": "AA", "cities": ["Springfield"], "systems": []},
                    {"region_id": "BB", "cities": ["Springfield"], "systems": []},
                ],
            }
        )
        self.assertEqual(reference.lookup("Springfield").kind, GeographicMatchKind.AMBIGUOUS)
        self.assertEqual(default_geographic_reference().lookup("Valencia").kind, GeographicMatchKind.AMBIGUOUS)


class RegionResolutionTests(unittest.TestCase):
    def test_source_stated_country(self):
        resolution = _resolve(country="Vietnam", location="Hanoi")
        self.assertEqual(
            (resolution.basis, resolution.region_id, resolution.display_name, resolution.source_field, resolution.source_value),
            (RegionResolutionBasis.SOURCE_STATED, "VN", "越南", "country", "Vietnam"),
        )

    def test_reference_mapped_from_source_system_name(self):
        resolution = _resolve(system="Hanoi Metro")
        self.assertEqual(
            (resolution.basis, resolution.region_id, resolution.source_field, resolution.reference_version),
            (RegionResolutionBasis.REFERENCE_MAPPED, "VN", "transit_system_name", "geo-reference-v2"),
        )

    def test_conflicting_regions_are_unresolved_without_choosing(self):
        resolution = _resolve(country="Japan", location="Hanoi")
        self.assertEqual((resolution.basis, resolution.diagnostic), (RegionResolutionBasis.UNRESOLVED, "CONFLICTING_REGIONS"))
        self.assertIsNone(resolution.region_id)

    def test_ambiguous_place_is_unresolved(self):
        resolution = _resolve(location="Valencia")
        self.assertEqual((resolution.basis, resolution.diagnostic), (RegionResolutionBasis.UNRESOLVED, "AMBIGUOUS_NAME"))

    def test_unrecognized_value_is_unresolved_not_guessed(self):
        resolution = _resolve(location="Seventh Avenue-53rd Street subway station")
        self.assertEqual((resolution.basis, resolution.diagnostic), (RegionResolutionBasis.UNRESOLVED, "UNRECOGNIZED_VALUE"))

    def test_nothing_in_source_is_not_stated(self):
        self.assertEqual(_resolve().basis, RegionResolutionBasis.NOT_STATED)
        self.assertEqual(_resolve(unresolved=("country",)).diagnostic, "INVALID_FIELD")

    def test_unestablished_resolution_cannot_store_a_region(self):
        with self.assertRaises(ValueError):
            RegionResolution(RegionResolutionBasis.NOT_STATED, region_id="VN")
        with self.assertRaises(ValueError):
            RegionResolution(RegionResolutionBasis.SOURCE_STATED, region_id="VN", display_name="越南")


class EvidenceServiceRegionTests(unittest.TestCase):
    def test_discovery_title_and_publisher_never_supply_country(self):
        result = _evaluate((("location", "Seventh Avenue"),), "The work closed Seventh Avenue overnight.")
        self.assertIsNone(result.identity_facts.region_resolution.region_id)
        self.assertEqual(result.identity_facts.region_resolution.basis, RegionResolutionBasis.UNRESOLVED)

    def test_city_or_mode_word_is_never_stored_as_a_system_name(self):
        for value in ("Hanoi", "subway", "地鐵"):
            with self.subTest(value=value):
                result = _evaluate((("transit_system_name", value),), f"Work on the {value} began.")
                self.assertIsNone(result.identity_facts.transit_system_name)
                self.assertIn("transit_system_name", result.identity_facts.unresolved_metadata_fields)

    def test_mapped_country_keeps_source_value_and_spans(self):
        body = "Hanoi Metro signed contracts in Hanoi."
        result = _evaluate((("transit_system_name", "Hanoi Metro"), ("location", "Hanoi")), body)
        facts = result.identity_facts
        self.assertEqual(facts.region_resolution.basis, RegionResolutionBasis.REFERENCE_MAPPED)
        self.assertEqual(facts.region_resolution.display_name, "越南")
        location_spans = [(s.start, s.end) for s in facts.metadata_support if s.field_name == "location"]
        # "Hanoi" occurs twice in the body (once inside "Hanoi Metro"); every
        # exact occurrence is retained as support (RC-3).
        self.assertEqual(location_spans, [(0, 5), (32, 37)])



class NonSpecificSystemNameTests(unittest.TestCase):
    """A list of places or mode words is never a transit-system name."""

    def test_lists_of_places_or_mode_words_are_not_system_names(self):
        from src.weekly_report.geographic_reference import default_geographic_reference

        reference = default_geographic_reference()
        for value in ("Hong Kong and Shenzhen", "Hong Kong, metro", "香港與深圳", "metro"):
            self.assertTrue(reference.is_non_specific_system_name(value), value)
        for value in ("Hanoi Metro", "Chennai Metro", "Hong Kong Tramways", "MetroLink", "København metro"):
            self.assertFalse(reference.is_non_specific_system_name(value), value)


if __name__ == "__main__":
    unittest.main()


class CompoundSourceNameTests(unittest.TestCase):
    """RC-19: compound source names resolve through the curated names they contain."""

    def setUp(self):
        self.reference = GeographicReference.from_file()

    def test_real_compound_names_resolve_to_the_one_region_they_contain(self):
        cases = {
            "名古屋市交通局": "JP",
            "桃園捷運綠線": "TW",
            "Línea 2 del Metro de Lima y Callao": "PE",
            "광주 도시철도 2호선": "KR",
            "Gwangju Metro Line 2": "KR",
            "Metro di Xiamen": "CN",
            "Bern–Ostermundigen tram line": "CH",
        }
        for value, region in cases.items():
            with self.subTest(value=value):
                self.assertIsNone(self.reference.lookup(value))
                self.assertEqual(self.reference.lookup_contained(value).region_id, region)

    def test_ambiguous_names_never_count_and_latin_names_need_word_boundaries(self):
        self.assertIsNone(self.reference.lookup_contained("Metro de Santiago"))
        self.assertIsNone(self.reference.lookup_contained("Bernard Street depot"))
        self.assertIsNone(self.reference.lookup_contained("Limassol light rail"))

    def test_names_of_two_regions_make_the_value_ambiguous(self):
        match = self.reference.lookup_contained("Tokyo and Seoul subway exchange")
        self.assertIs(match.kind, GeographicMatchKind.AMBIGUOUS)

    def test_resolution_uses_contained_names_only_without_a_whole_match(self):
        resolution = _resolve(system="名古屋市交通局")
        self.assertIs(resolution.basis, RegionResolutionBasis.REFERENCE_MAPPED)
        self.assertEqual(resolution.region_id, "JP")
        self.assertEqual(resolution.source_value, "名古屋市交通局")
        self.assertIs(_resolve(country="Swiss").basis, RegionResolutionBasis.SOURCE_STATED)
