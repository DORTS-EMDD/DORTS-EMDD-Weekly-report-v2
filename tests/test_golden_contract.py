"""Contract-level validation for the deterministic Golden Corpus."""

from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "golden"
CASES = GOLDEN / "cases"


class GoldenContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads((GOLDEN / "manifest.json").read_text(encoding="utf-8"))
        cls.entries = cls.manifest["cases"]
        cls.fixtures = {
            entry["case_id"]: json.loads(
                (GOLDEN / entry["file"]).read_text(encoding="utf-8")
            )
            for entry in cls.entries
        }

    def test_manifest_is_sequential_and_complete(self):
        self.assertEqual(self.manifest["case_count"], 48)
        self.assertEqual(len(self.entries), 48)
        self.assertEqual(
            [entry["case_id"] for entry in self.entries],
            [f"G{i:02d}" for i in range(1, 49)],
        )
        for entry in self.entries:
            self.assertTrue((GOLDEN / entry["file"]).is_file())
            self.assertEqual(self.fixtures[entry["case_id"]]["case_id"], entry["case_id"])

    def test_all_fixtures_are_deterministic_and_self_contained(self):
        self.assertFalse(self.manifest["live_search"])
        for fixture in self.fixtures.values():
            self.assertEqual(fixture["origin_type"], "SYNTHETIC_CONTRACT_CASE")
            for candidate in fixture["candidates"]:
                self.assertTrue(candidate["url"].startswith("https://fixtures.invalid/"))
                self.assertIn("source_content", candidate)

    def test_formal_temporal_candidates_have_source_date_provenance(self):
        for fixture in self.fixtures.values():
            expected = fixture["expected"]
            if expected["scope"] != "IN_SCOPE" or not isinstance(expected["date_valid"], bool):
                continue
            if expected.get("temporal_diagnostic") in {"DATE_MISSING", "DATE_PROVENANCE_INVALID"}:
                continue
            for candidate in fixture["candidates"]:
                facts = candidate.get("source_date_facts")
                self.assertIsInstance(facts, list, fixture["case_id"])
                self.assertGreater(len(facts), 0, fixture["case_id"])
                for fact in facts:
                    self.assertTrue(fact["raw_date_value"])
                    self.assertTrue(fact["date_kind"])
                    self.assertTrue(fact["principal_document_association"])
                    self.assertTrue(fact["source_node_or_field_provenance"])
                    self.assertIn("explicit_timezone_or_offset", fact)

    def test_scope_boundary_cases_have_locked_outcomes(self):
        expected_scope = {
            "G22": "IN_SCOPE",
            "G23": "OUT_OF_SCOPE",
            "G24": "IN_SCOPE",
            "G25": "IN_SCOPE",
            "G26": "IN_SCOPE",
            "G27": "OUT_OF_SCOPE",
            "G28": "OUT_OF_SCOPE",
            "G29": "OUT_OF_SCOPE",
            "G30": "IN_SCOPE",
            "G31": "OUT_OF_SCOPE",
            "G32": "IN_SCOPE",
            "G33": "OUT_OF_SCOPE",
            "G34": "OUT_OF_SCOPE",
            "G35": "IN_SCOPE",
        }
        for case_id, scope in expected_scope.items():
            expected = self.fixtures[case_id]["expected"]
            self.assertEqual(expected["scope"], scope, case_id)
            if scope == "OUT_OF_SCOPE":
                self.assertEqual(expected["date_valid"], "NOT_EVALUATED", case_id)
                self.assertIn(
                    expected["scope_diagnostic"],
                    {"NON_URBAN_RAIL", "EXCLUDED_TRANSPORT_MODE", "SCOPE_NOT_ESTABLISHED"},
                )

    def test_temporal_boundary_cases_have_locked_diagnostics(self):
        diagnostics = {
            "G36": "NONE",
            "G37": "NONE",
            "G38": "OUT_OF_RANGE",
            "G39": "OUT_OF_RANGE",
            "G40": "OUT_OF_RANGE",
            "G41": "NONE",
            "G42": "NONE",
            "G43": "DATE_MISSING",
            "G44": "DATE_PROVENANCE_INVALID",
            "G45": "OUT_OF_RANGE",
            "G46": "OUT_OF_RANGE",
            "G47": "DATE_CONFLICT",
            "G48": "OUT_OF_RANGE",
        }
        for case_id, diagnostic in diagnostics.items():
            expected = self.fixtures[case_id]["expected"]
            self.assertEqual(expected["temporal_diagnostic"], diagnostic, case_id)
            self.assertIsInstance(expected["date_valid"], bool, case_id)
            if diagnostic == "NONE":
                self.assertTrue(expected["date_valid"], case_id)
            else:
                self.assertFalse(expected["date_valid"], case_id)

        self.assertEqual(self.fixtures["G43"]["candidates"][0].get("published_at"), None)
        self.assertEqual(self.fixtures["G43"]["candidates"][0].get("source_date_facts"), [])
        self.assertEqual(self.fixtures["G44"]["candidates"][0]["published_at"], "2026-09-15T12:00:00Z")
        self.assertEqual(self.fixtures["G44"]["candidates"][0].get("source_date_facts"), [])
        self.assertEqual(self.fixtures["G47"]["candidates"][0]["source_date_facts"].__len__(), 2)

    def test_upstream_rejections_stop_downstream_fields(self):
        for fixture in self.fixtures.values():
            expected = fixture["expected"]
            if expected["scope"] == "OUT_OF_SCOPE" or expected["date_valid"] is False:
                self.assertEqual(expected["event_identity_expectation"], "NOT_EVALUATED", fixture["case_id"])
                self.assertEqual(expected["event_count_after_dedup"], "NOT_EVALUATED", fixture["case_id"])
                self.assertEqual(expected["primary_category"], "NOT_EVALUATED", fixture["case_id"])
                self.assertEqual(expected["subtype"], "NOT_EVALUATED", fixture["case_id"])
                self.assertEqual(expected["e&m_taxonomy"], "NOT_EVALUATED", fixture["case_id"])
                self.assertEqual(expected["reportability"], "NOT_EVALUATED", fixture["case_id"])

    def test_evidence_rejections_do_not_reach_scope_or_temporal(self):
        for fixture in self.fixtures.values():
            expected = fixture["expected"]
            if expected["evidence_state"] == "EVIDENCE_REJECTED":
                self.assertEqual(expected["scope"], "NOT_EVALUATED", fixture["case_id"])
                self.assertEqual(expected["date_valid"], "NOT_EVALUATED", fixture["case_id"])


if __name__ == "__main__":
    unittest.main()
