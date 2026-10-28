"""RC-28: formal region eligibility (designated regions only, established from Evidence)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from unittest import TestCase

from src.weekly_report.geographic_reference import default_geographic_reference
from src.weekly_report.region_registry import CONFIGURATION_PATH, RegionRegistry
from src.weekly_report.report_service import (
    FormalMetadataFailureReason,
    ReportDisclosure,
    ReportService,
)
from tests.test_golden_contract import GOLDEN, _materialize_ordering_case

REGISTRY_SOURCE = json.loads(Path(CONFIGURATION_PATH).read_text(encoding="utf-8"))
REGISTRY = RegionRegistry.from_mapping(REGISTRY_SOURCE)
MANIFEST = json.loads((GOLDEN / "region_eligibility_manifest.json").read_text(encoding="utf-8"))


class RegionEligibilityGoldenTests(TestCase):
    def test_manifest_is_sequential_and_complete(self) -> None:
        self.assertEqual(MANIFEST["stage"], "FORMAL_METADATA_REGION_ELIGIBILITY")
        self.assertFalse(MANIFEST["live_search"])
        self.assertEqual([entry["case_id"] for entry in MANIFEST["cases"]], [f"R{i:02d}" for i in range(1, 8)])
        self.assertEqual(MANIFEST["case_count"], len(MANIFEST["cases"]))

    def test_golden_executes_production_projection_with_the_production_region_set(self) -> None:
        service = ReportService(formal_region_ids=REGISTRY.formal_region_ids)
        for entry in MANIFEST["cases"]:
            fixture = json.loads((GOLDEN / entry["file"]).read_text(encoding="utf-8"))
            with self.subTest(case_id=entry["case_id"]):
                projection = service.project_formal_metadata_population(_materialize_ordering_case(fixture))
                self.assertEqual([item.event_id for item in projection.metadata], fixture["expected"]["included"])
                self.assertEqual(
                    {item.event_id: item.reason.value for item in projection.exclusions},
                    fixture["expected"]["excluded"],
                )

    def test_included_events_display_the_established_region(self) -> None:
        fixture = json.loads((GOLDEN / "cases/region_domestic_event.json").read_text(encoding="utf-8"))
        projection = ReportService(formal_region_ids=REGISTRY.formal_region_ids).project_formal_metadata_population(
            _materialize_ordering_case(fixture)
        )
        self.assertEqual(projection.metadata[0].country, "臺灣")

    def test_without_a_region_set_the_projection_is_unchanged(self) -> None:
        # Isolated projection fixtures only; production always supplies the set.
        fixture = json.loads((GOLDEN / "cases/region_non_designated_event.json").read_text(encoding="utf-8"))
        projection = ReportService().project_formal_metadata_population(_materialize_ordering_case(fixture))
        self.assertEqual(len(projection.metadata), 2)


class FormalRegionSetTests(TestCase):
    def test_formal_regions_are_the_approved_selected_markets(self) -> None:
        self.assertEqual(
            REGISTRY.formal_region_ids,
            frozenset({"TW", "KR", "HK", "GB", "DE", "CA", "NL", "IT", "AT", "NO",
                       "PT", "JP", "SG", "AU", "FR", "US", "ES", "CH", "SE", "DK"}),
        )
        self.assertEqual(len(REGISTRY.formal_region_ids), REGISTRY.selected_market_count)

    def test_every_market_region_exists_in_the_geographic_reference(self) -> None:
        reference = json.loads(
            (Path(CONFIGURATION_PATH).parent / "geographic_reference.json").read_text(encoding="utf-8")
        )
        reference_ids = {region["region_id"] for region in reference["regions"]}
        self.assertLessEqual(REGISTRY.formal_region_ids, reference_ids)
        self.assertEqual(default_geographic_reference().version, reference["reference_version"])

    def test_missing_or_duplicate_market_region_fails_closed(self) -> None:
        missing = copy.deepcopy(REGISTRY_SOURCE)
        del missing["selected_markets"][0]["region_id"]
        duplicate = copy.deepcopy(REGISTRY_SOURCE)
        duplicate["selected_markets"][1]["region_id"] = duplicate["selected_markets"][0]["region_id"]
        malformed = copy.deepcopy(REGISTRY_SOURCE)
        malformed["selected_markets"][0]["region_id"] = "Taiwan"
        for broken in (missing, duplicate, malformed):
            with self.assertRaises((ValueError, TypeError)):
                RegionRegistry.from_mapping(broken)

    def test_registry_round_trip_keeps_region_ids(self) -> None:
        self.assertEqual(RegionRegistry.from_mapping(REGISTRY.as_mapping()).formal_region_ids, REGISTRY.formal_region_ids)


class EntryPointAndDisclosureTests(TestCase):
    def test_production_composition_uses_the_registry_region_set(self) -> None:
        # One composition serves the CLI, GitHub Actions and Streamlit.
        source = (Path(CONFIGURATION_PATH).parents[0] / "production_runner.py").read_text(encoding="utf-8")
        self.assertIn("report_service=ReportService(formal_region_ids=registry.formal_region_ids)", source)
        self.assertNotIn("report_service=ReportService()", source)

    def test_unconfirmed_regions_are_disclosed_and_out_of_region_events_are_not(self) -> None:
        notes = ReportService._render_disclosure(ReportDisclosure(region_not_established_count=3))
        self.assertEqual(notes, ["本期有 3 則事件因來源未能確認所在國家／地區，未列入本報告。"])
        self.assertEqual(ReportService._render_disclosure(ReportDisclosure()), [])
        self.assertIn(FormalMetadataFailureReason.NON_DESIGNATED_REGION.value, "NON_DESIGNATED_REGION")
