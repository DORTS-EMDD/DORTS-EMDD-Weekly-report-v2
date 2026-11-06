"""RC-63 Category boundary Golden (section L): project steps, statistics, plans and
non-transport station services have no Category-defining action.

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
        self.assertEqual(ids, ["G92", "G93", "G94", "G95", "G96", "G97", "G98"])
        self.assertEqual(MANIFEST["case_count"], len(ids))
        self.assertTrue(MANIFEST["category_acceptance_population_excluded"])
        self.assertTrue(set(ids).isdisjoint(entry["case_id"] for entry in locked["cases"]))
        self.assertTrue(set(ids).isdisjoint(entry["case_id"] for entry in taxonomy["cases"]))

    def test_each_boundary_case_has_no_category_defining_action(self):
        for entry in MANIFEST["cases"]:
            fixture = json.loads((GOLDEN / entry["file"]).read_text(encoding="utf-8"))
            expected = fixture["expected"]
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

    def test_prompt_carries_the_section_l_boundaries(self):
        self.assertEqual(CATEGORY_SEMANTIC_PROMPT_VERSION, "category-principal-action-v5")
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
