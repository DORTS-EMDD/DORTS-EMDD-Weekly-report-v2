"""RC-63/RC-66 Category boundary Golden (section L): project steps, statistics, plans,
non-transport station services and activities about a technology have no
Category-defining action; a technology deployment on an operating line stays
technical development (near-boundary positive, G101).

The cases run through the same Classifier Golden harness as the locked Category
population, but they are kept in their own manifest so the sealed acceptance
population (v2-category-lock) is unchanged.
"""

from __future__ import annotations

import json
import unittest

from src.weekly_report.classifier import Classifier
from src.weekly_report.contracts import CategoryState
from src.weekly_report.category_semantic_provider import CATEGORY_SEMANTIC_PROMPT_VERSION
from src.weekly_report import classifier as classifier_module
from tests.test_classifier_golden import GOLDEN, _GoldenSemanticOracle, _materialize_groups, _materialize_record

MANIFEST = json.loads((GOLDEN / "category_boundary_manifest.json").read_text(encoding="utf-8"))


class CategoryBoundaryGoldenTests(unittest.TestCase):
    def test_manifest_is_isolated_from_the_locked_population(self):
        locked = json.loads((GOLDEN / "manifest.json").read_text(encoding="utf-8"))
        taxonomy = json.loads((GOLDEN / "taxonomy_manifest.json").read_text(encoding="utf-8"))
        ids = [entry["case_id"] for entry in MANIFEST["cases"]]
        self.assertEqual(ids, ["G92", "G93", "G94", "G95", "G96", "G97", "G98", "G99", "G100", "G101", "G102", "G103", "G104", "G105", "G106", "G107", "G108", "G109"])
        self.assertEqual(MANIFEST["case_count"], len(ids))
        self.assertTrue(MANIFEST["category_acceptance_population_excluded"])
        self.assertTrue(set(ids).isdisjoint(entry["case_id"] for entry in locked["cases"]))
        self.assertTrue(set(ids).isdisjoint(entry["case_id"] for entry in taxonomy["cases"]))

    def test_each_boundary_case_has_no_category_defining_action(self):
        for entry in MANIFEST["cases"]:
            fixture = json.loads((GOLDEN / entry["file"]).read_text(encoding="utf-8"))
            expected = fixture["expected"]
            if entry["category_family"] != "CATEGORY_UNRESOLVED":
                continue
            with self.subTest(case_id=entry["case_id"]):
                self.assertEqual(fixture["case_id"], entry["case_id"])
                self.assertEqual(expected["category_state"], "CATEGORY_UNRESOLVED")
                self.assertEqual(expected["category_resolution_reason"], "NO_CATEGORY_DEFINING_ACTION")
                self.assertEqual(expected["reportability"], "NOT_EVALUATED")
                records = tuple(_materialize_record(candidate) for candidate in fixture["candidates"])
                groups = _materialize_groups(fixture, records)
                self.assertEqual(len(groups), 1)
                result = Classifier(_GoldenSemanticOracle(expected)).classify(groups[0], records)
                self.assertIs(result.category_state, CategoryState.CATEGORY_UNRESOLVED)
                self.assertEqual(result.category_resolution_reason.value, "NO_CATEGORY_DEFINING_ACTION")
                self.assertIsNone(result.primary_category_id)

    def test_near_boundary_positive_cases_keep_their_category(self):
        # RC-66/RC-68: the boundaries must not turn a real technology deployment
        # (G101 operating-line 5G, G107 track monitoring in service, G108
        # on-board 5G Wi-Fi) or a service-change notice (G109) into a false
        # negative.
        assigned = [entry for entry in MANIFEST["cases"] if entry["category_family"] != "CATEGORY_UNRESOLVED"]
        self.assertEqual(
            [(entry["case_id"], entry["category_family"]) for entry in assigned],
            [("G101", "TECHNICAL_DEVELOPMENT"), ("G107", "TECHNICAL_DEVELOPMENT"), ("G108", "TECHNICAL_DEVELOPMENT"), ("G109", "OPERATIONAL_CHANGE")],
        )
        for entry in assigned:
            fixture = json.loads((GOLDEN / entry["file"]).read_text(encoding="utf-8"))
            expected = fixture["expected"]
            with self.subTest(case_id=entry["case_id"]):
                self.assertEqual(expected["primary_category_id"], entry["category_family"])
                records = tuple(_materialize_record(candidate) for candidate in fixture["candidates"])
                groups = _materialize_groups(fixture, records)
                result = Classifier(_GoldenSemanticOracle(expected)).classify(groups[0], records)
                self.assertIs(result.category_state, CategoryState.CATEGORY_ASSIGNED)
                self.assertEqual(result.primary_category_id.value, entry["category_family"])
                self.assertEqual(result.subtype, expected["subtype"])

    def test_technology_deployments_land_in_the_technology_section(self):
        # RC-40/41: the report section is the fixed projection of CategoryId;
        # no other owner places an event in a section.
        from src.weekly_report.contracts import CategoryId
        from src.weekly_report.report_service import FORMAL_REPORT_SECTIONS

        sections = dict(FORMAL_REPORT_SECTIONS)
        for case_id in ("G101", "G107", "G108"):
            entry = next(item for item in MANIFEST["cases"] if item["case_id"] == case_id)
            expected = json.loads((GOLDEN / entry["file"]).read_text(encoding="utf-8"))["expected"]
            with self.subTest(case_id=case_id):
                self.assertEqual(sections[CategoryId(expected["primary_category_id"])], "技術新知")
                self.assertEqual(expected["primary_category"], "技術新知")

    def test_pre_opening_and_delivery_acceptance_tests_share_one_outcome(self):
        # RC-67 D1 / RC-68: pre-opening test runs (G93), pre-opening signalling
        # tests (G100), acceptance tests of newly delivered vehicles on a running
        # network (G105) and pre-opening tests whose works affected a running
        # line (G106) are all project steps under one rule, with no city, line
        # or headline condition.
        outcomes = {}
        for case_id in ("G93", "G100", "G105", "G106"):
            entry = next(item for item in MANIFEST["cases"] if item["case_id"] == case_id)
            expected = json.loads((GOLDEN / entry["file"]).read_text(encoding="utf-8"))["expected"]
            outcomes[case_id] = (expected["category_state"], expected["primary_category_id"], expected["category_resolution_reason"])
        self.assertEqual(set(outcomes.values()), {("CATEGORY_UNRESOLVED", None, "NO_CATEGORY_DEFINING_ACTION")})

    def test_prompt_carries_the_section_l_boundaries(self):
        self.assertEqual(CATEGORY_SEMANTIC_PROMPT_VERSION, "category-principal-action-v8")
        guidance = "\n".join(classifier_module._CATEGORY_GUIDANCE)
        self.assertIn("is of a technology, method or material itself", guidance)
        for step in ("groundbreaking", "pre-opening or trial test runs", "commissioning and acceptance tests"):
            self.assertIn(step, guidance)
        self.assertIn("concerns the passenger transport service itself", guidance)
        self.assertIn("A planned, expected or future tender, selection or award is not a procurement action", guidance)
        self.assertIn("ridership counts or records", guidance)
        self.assertIn("Operational governance actions govern a passenger service that is running", guidance)
        self.assertIn("statements, criticisms, demands or questions about an action", guidance)
        self.assertIn("NO_CATEGORY_DEFINING_ACTION unless the evidence shows another listed principal action", guidance)
        # RC-66: one qualified definition, the closed set of listed actions,
        # on-board non-transport services, and the schema's subtype pattern.
        self.assertIn("substantive development whose subject is a technology, method or material itself", guidance)
        self.assertNotIn("technical deployments, and substantive technical development", guidance)
        self.assertIn("A Category applies only when the principal action is itself one of the actions its definition lists", guidance)
        self.assertIn("is not TECHNICAL_DEVELOPMENT", guidance)
        # RC-67 (user decision 2026-11-16, D1/D2): drills have no Category;
        # funding, cost increases and opening-date changes are project steps.
        self.assertIn("A drill, exercise, rehearsal or training session", guidance)
        self.assertIn("has no Category-defining action under any Category: it is not TECHNICAL_DEVELOPMENT, not INCIDENT and not OPERATIONAL_CHANGE", guidance)
        for step in ("funding or budget requests and decisions", "cost increases", "construction stages and progress", "changes to or forecasts of an expected opening date"):
            self.assertIn(step, guidance)
        self.assertIn("at a station or on board a train that is not transport service", guidance)
        self.assertIn("starts with a letter a-z", guidance)
        self.assertIn("even when the tested system is signalling, train control, communication or power equipment", guidance)
        # RC-68 (Run 43995345298): delivery acceptance tests on a running
        # network, technology deployments that change maintenance or give an
        # on-board amenity, and a consequence is not a principal action.
        self.assertIn("Newly delivered vehicles or equipment go through the same kind of step before they enter passenger service, also on a network that is already running", guidance)
        self.assertIn("A pilot or trial whose subject is a new technology, method or material itself remains technical development", guidance)
        self.assertIn("changes to how the passenger service is operated", guidance)
        self.assertNotIn("operating-practice changes", guidance)
        self.assertIn("Putting a technology, method or material into use is a deployment under TECHNICAL_DEVELOPMENT", guidance)
        self.assertIn("such as Wi-Fi or mobile network coverage", guidance)
        self.assertIn("A passenger service opening of a new line, extension or train fleet remains OPERATIONAL_CHANGE", guidance)
        self.assertIn("Classify the action the evidence reports as its news, not a consequence of it", guidance)
        self.assertIn("the service effect is not a separate principal action", guidance)
        self.assertIn("A service change is the principal action only when the evidence reports the service change itself as its news", guidance)



class ScopeEventFocusContractTests(unittest.TestCase):
    def test_the_event_focus_must_contain_the_occurrence_sentence(self):
        # RC-65: Event Identity and Writer read only the focus (section A.14).
        from src.weekly_report import maiagent_scope_provider as scope_provider

        self.assertEqual(scope_provider.PROMPT_VERSION, "scope-event-target-system-v13")
        text = " ".join(scope_provider.SCOPE_SEMANTIC_INSTRUCTIONS)
        self.assertIn("must include the sentence or sentences that state the occurrence itself", text)
        self.assertIn("A lead summary, reactions, quotes or figures alone are not the event focus", text)


if __name__ == "__main__":
    unittest.main()
