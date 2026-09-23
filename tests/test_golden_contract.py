"""Contract-level validation for the deterministic Golden Corpus."""

from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "golden"
CASES = GOLDEN / "cases"


class GoldenContractTests(unittest.TestCase):
    CATEGORY_LABELS = {
        "TECHNICAL_DEVELOPMENT": "技術新知",
        "INCIDENT": "事故事件",
        "OPERATIONAL_CHANGE": "營運動態",
        "PROCUREMENT": "採購事件",
        "NORMATIVE_CHANGE": "規範變動",
    }

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
        case_count = self.manifest["case_count"]
        self.assertEqual(case_count, 85)
        self.assertEqual(len(self.entries), case_count)
        self.assertEqual(
            [entry["case_id"] for entry in self.entries],
            [f"G{i:02d}" for i in range(1, case_count + 1)],
        )
        for entry in self.entries:
            self.assertTrue((GOLDEN / entry["file"]).is_file())
            self.assertEqual(self.fixtures[entry["case_id"]]["case_id"], entry["case_id"])

    def test_category_states_are_explicit_and_terminal_rules_hold(self):
        assigned = unresolved = not_evaluated = 0
        for fixture in self.fixtures.values():
            expected = fixture["expected"]
            state = expected["category_state"]
            manifest_family = next(
                entry["category_family"]
                for entry in self.entries
                if entry["case_id"] == fixture["case_id"]
            )
            self.assertEqual(
                manifest_family,
                expected["primary_category_id"] if state == "CATEGORY_ASSIGNED" else state,
                fixture["case_id"],
            )
            self.assertIn(
                state,
                {"NOT_EVALUATED", "CATEGORY_ASSIGNED", "CATEGORY_UNRESOLVED"},
                fixture["case_id"],
            )
            if state == "CATEGORY_ASSIGNED":
                assigned += 1
                category_id = expected["primary_category_id"]
                self.assertIn(category_id, self.CATEGORY_LABELS, fixture["case_id"])
                self.assertEqual(expected["primary_category"], self.CATEGORY_LABELS[category_id])
                self.assertTrue(expected["subtype"], fixture["case_id"])
                self.assertTrue(expected["classification_reason"], fixture["case_id"])
                self.assertEqual(expected["category_resolution_reason"], "NONE", fixture["case_id"])
            elif state == "CATEGORY_UNRESOLVED":
                unresolved += 1
                self.assertIsNone(expected["primary_category_id"], fixture["case_id"])
                self.assertIsNone(expected["primary_category"], fixture["case_id"])
                self.assertIsNone(expected["subtype"], fixture["case_id"])
                self.assertEqual(expected["e&m_taxonomy"], "NOT_EVALUATED", fixture["case_id"])
                self.assertEqual(expected["reportability"], "NOT_EVALUATED", fixture["case_id"])
                self.assertTrue(expected["category_resolution_reason"], fixture["case_id"])
                self.assertEqual(expected["reject_stage"], "NONE", fixture["case_id"])
                self.assertEqual(expected["reject_reason"], "NONE", fixture["case_id"])
            else:
                not_evaluated += 1
                for field in (
                    "primary_category_id",
                    "primary_category",
                    "subtype",
                    "e&m_taxonomy",
                    "reportability",
                    "classification_reason",
                    "category_resolution_reason",
                ):
                    self.assertEqual(expected[field], "NOT_EVALUATED", fixture["case_id"])

        self.assertEqual((assigned, unresolved, not_evaluated), (46, 6, 33))
        self.assertEqual(self.manifest["category_case_count"], assigned + unresolved)

    def test_locked_category_families_and_independent_decisions(self):
        expected_categories = {
            **{f"G{i:02d}": "TECHNICAL_DEVELOPMENT" for i in (3, 4, 5, 17, 49, 50, 64, 78, 79, 84)},
            **{f"G{i:02d}": "INCIDENT" for i in (6, 7, 12, 16, 52, 53)},
            **{f"G{i:02d}": "OPERATIONAL_CHANGE" for i in (8, 9, 54, 55, 65, 66, 67, 80)},
            **{f"G{i:02d}": "PROCUREMENT" for i in (10, 11, 13, 19, 20, 21, 56, 57, 58, 59, 60, 61, 62, 63, 77, 85)},
            **{f"G{i:02d}": "NORMATIVE_CHANGE" for i in (69, 70, 71, 72, 73, 74)},
        }
        for case_id, category_id in expected_categories.items():
            expected = self.fixtures[case_id]["expected"]
            self.assertEqual(expected["category_state"], "CATEGORY_ASSIGNED", case_id)
            self.assertEqual(expected["primary_category_id"], category_id, case_id)

        for case_id in ("G51", "G68", "G75", "G76", "G81", "G82"):
            self.assertEqual(
                self.fixtures[case_id]["expected"]["category_state"],
                "CATEGORY_UNRESOLVED",
                case_id,
            )

        self.assertEqual(self.fixtures["G07"]["expected"]["primary_category_id"], "INCIDENT")
        self.assertEqual(self.fixtures["G07"]["expected"]["reportability"], "NOT_REPORTABLE")
        self.assertEqual(self.fixtures["G85"]["expected"]["primary_category_id"], "PROCUREMENT")
        self.assertEqual(self.fixtures["G85"]["expected"]["reportability"], "NOT_REPORTABLE")
        self.assertEqual(self.fixtures["G49"]["category_period_invariance"]["weekly"]["expected_category_id"], "TECHNICAL_DEVELOPMENT")
        self.assertEqual(self.fixtures["G49"]["category_period_invariance"]["annual"]["expected_category_id"], "TECHNICAL_DEVELOPMENT")
        self.assertEqual(self.fixtures["G60"]["expected"]["primary_category_id"], "PROCUREMENT")
        self.assertEqual(self.fixtures["G64"]["expected"]["primary_category_id"], "TECHNICAL_DEVELOPMENT")
        mixed = self.fixtures["G82"]
        self.assertEqual(mixed["expected"]["event_identity_expectation"], "SAME_EVENT")
        self.assertEqual(mixed["expected"]["event_count_after_dedup"], 1)
        self.assertEqual(len(mixed["candidates"]), 2)

    def test_search_context_is_non_authoritative_and_evidence_rejection_stops_category(self):
        for case_id in ("G49", "G53", "G60", "G62", "G63", "G64", "G69", "G79"):
            context = self.fixtures[case_id]["category_fixture_context"]
            self.assertEqual(context["authority"], "NON_AUTHORITATIVE_DISCOVERY_CONTEXT", case_id)
        expected = self.fixtures["G83"]["expected"]
        self.assertEqual(expected["evidence_state"], "EVIDENCE_REJECTED")
        self.assertEqual(expected["reject_reason"], "SOURCE_PAGE_MISMATCH")
        self.assertEqual(expected["category_state"], "NOT_EVALUATED")

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
