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
        self.assertEqual(ids, ["G92", "G93", "G94", "G95", "G96", "G97", "G98", "G99", "G100", "G101"])
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

    def test_near_boundary_technology_deployment_stays_technical_development(self):
        # RC-66: the boundary must not turn a real technology deployment into a
        # false negative (G49, G64, G84 and the operating-line deployment G101).
        assigned = [entry for entry in MANIFEST["cases"] if entry["category_family"] != "CATEGORY_UNRESOLVED"]
        self.assertEqual([entry["case_id"] for entry in assigned], ["G101"])
        for entry in assigned:
            fixture = json.loads((GOLDEN / entry["file"]).read_text(encoding="utf-8"))
            expected = fixture["expected"]
            with self.subTest(case_id=entry["case_id"]):
                self.assertEqual(expected["primary_category_id"], entry["category_family"])
                records = tuple(_materialize_record(candidate) for candidate in fixture["candidates"])
                groups = _materialize_groups(fixture, records)
                result = Classifier(_GoldenSemanticOracle(expected)).classify(groups[0], records)
                self.assertIs(result.category_state, CategoryState.CATEGORY_ASSIGNED)
                self.assertEqual(result.primary_category_id.value, "TECHNICAL_DEVELOPMENT")
                self.assertEqual(result.subtype, expected["subtype"])

    def test_prompt_carries_the_section_l_boundaries(self):
        self.assertEqual(CATEGORY_SEMANTIC_PROMPT_VERSION, "category-principal-action-relationship-v9")
        guidance = "\n".join(classifier_module._CATEGORY_GUIDANCE)
        self.assertIn("return only advisory action/lifecycle observations", guidance)
        self.assertIn("Do not return a Category ID, Category state, unresolved reason", guidance)
        self.assertIn("one principal current or lifecycle action only when the Evidence supports a unique principal action", guidance)
        self.assertIn("subject_kind is TECHNOLOGY_METHOD_MATERIAL and lifecycle_relation is TECHNOLOGY_ITSELF", guidance)
        self.assertIn("PROJECT_DELIVERY or PRE_OPENING", guidance)
        self.assertIn("A procurement action must have taken place", guidance)
        self.assertIn("An unadopted recommendation is RECOMMENDATION", guidance)
        self.assertIn("leave principal_action_id null", guidance)
        self.assertIn("COMMON_DECISION_MEMBERSHIP and SAME_OCCURRENCE_DEPENDENCE", guidance)
        self.assertIn("relationship citations must support the relationship itself", guidance)
        self.assertIn("When the Evidence supports multiple returned observations as constituent or dependent aspects of one occurrence or decision, preserve that supported relationship", guidance)
        self.assertIn("One complete observation for one occurrence is valid; do not split one occurrence merely because the Evidence contains several verbs or aspects", guidance)
        self.assertIn("Do not infer it from citation or sentence overlap", guidance)
        self.assertIn("Do not infer from titles, snippets, discovery intent, publisher, URL", guidance)
        self.assertIn("Subtype is optional descriptive metadata only", guidance)
        self.assertNotIn("TECHNOLOGY > OPERATIONAL_CHANGE", guidance)
        self.assertNotIn("future tense does not make it an unadopted recommendation", guidance)
        self.assertNotIn("passenger-facing service", guidance)



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
