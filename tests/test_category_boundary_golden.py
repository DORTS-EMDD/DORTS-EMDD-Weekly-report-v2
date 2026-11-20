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

# RC-80 (section A.61): the principal action each boundary case describes. The
# oracle proposes it; the Classifier's fixed table must give the sealed result.
BOUNDARY_ACTIONS = {
    "G92": "PROJECT_STEP",  # groundbreaking
    "G93": "PRE_SERVICE_OR_ACCEPTANCE_TEST",  # pre-opening test runs
    "G94": "STATISTICS_RANKING_OR_AWARD",  # ridership record
    "G95": "PROJECT_STEP",  # demolition and relocation plan
    "G96": "NON_TRANSPORT_SERVICE",  # station clinic booth
    "G97": "PROJECT_STEP",  # project progress publicity
    "G98": "STATEMENT_OR_COMMENTARY",  # criticism of an earlier selection
    "G99": "EVENT_OR_EXHIBITION",  # technical exchange meeting
    "G100": "PRE_SERVICE_OR_ACCEPTANCE_TEST",  # pre-opening signalling tests
    "G101": "TECHNOLOGY_TRIAL_OR_DEPLOYMENT",  # 5G on operating lines
    "G102": "DRILL_OR_TRAINING",  # emergency drill
    "G103": "PROJECT_STEP",  # funding request
    "G104": "PROJECT_STEP",  # opening delay
    "G105": "PRE_SERVICE_OR_ACCEPTANCE_TEST",  # new trams' clearance and EMC tests
    "G106": "PRE_SERVICE_OR_ACCEPTANCE_TEST",  # new-line tests with a service effect
    "G107": "TECHNOLOGY_TRIAL_OR_DEPLOYMENT",  # track monitoring on service trains
    "G108": "TECHNOLOGY_TRIAL_OR_DEPLOYMENT",  # on-board 5G Wi-Fi
    "G109": "SERVICE_CHANGE",  # works closure notice
}


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
                result = Classifier(_GoldenSemanticOracle(expected, BOUNDARY_ACTIONS[entry["case_id"]])).classify(groups[0], records)
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
                result = Classifier(_GoldenSemanticOracle(expected, BOUNDARY_ACTIONS[entry["case_id"]])).classify(groups[0], records)
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
        # RC-80 (section A.61): the helper chooses a principal action from a
        # closed list; the section L boundaries of RC-63..RC-68 are carried by
        # the action definitions, and Python maps the action to the Category.
        from src.weekly_report.contracts import CategoryPrincipalAction

        self.assertEqual(CATEGORY_SEMANTIC_PROMPT_VERSION, "category-principal-action-v9")
        guidance = "\n".join(classifier_module._CATEGORY_GUIDANCE)
        for action in CategoryPrincipalAction:
            self.assertIn(f"{action.value}:", guidance)
        self.assertIn("never name a Category", guidance)
        self.assertIn("whose subject is a technology, method or material itself", guidance)
        for step in ("groundbreaking", "test runs before opening", "commissioning, type, acceptance or homologation tests",
                     "funding or budget requests and decisions", "cost increases", "construction stages and progress",
                     "changes to or forecasts of an expected opening date", "ridership counts or records"):
            self.assertIn(step, guidance)
        self.assertIn("A planned, expected or future tender, selection or award is PROJECT_STEP", guidance)
        self.assertIn("not the passenger transport service, such as a shop, clinic", guidance)
        self.assertIn("also when that facility uses a technology", guidance)
        self.assertIn("a drill, exercise, rehearsal or training session", guidance)
        self.assertIn("statements, criticisms, demands, questions", guidance)
        self.assertIn("a meeting, exchange, conference, exhibition", guidance)
        self.assertIn("even when the tested system is signalling, train control, communication or power equipment", guidance)
        self.assertIn("also on a network that is already running", guidance)
        self.assertIn("also when it changes how maintenance, inspection or monitoring is done", guidance)
        self.assertIn("such as Wi-Fi or mobile network coverage", guidance)
        self.assertIn("a new line, extension, station or train fleet actually begins carrying passengers", guidance)
        self.assertIn("Choose the action the evidence reports as its news, not a consequence of it", guidance)
        self.assertIn("the action is still PROJECT_STEP", guidance)
        self.assertIn("A service change is the principal action only when the evidence reports the service change itself as its news", guidance)
        self.assertIn("starts with a letter a-z", guidance)

    def test_every_action_maps_to_exactly_one_outcome(self):
        from src.weekly_report.contracts import CategoryId, CategoryPrincipalAction, CategoryResolutionReason

        table = classifier_module.PRINCIPAL_ACTION_CATEGORY
        self.assertEqual(set(table), set(CategoryPrincipalAction))
        to_category = {action.value: target.value for action, target in table.items() if isinstance(target, CategoryId)}
        self.assertEqual(
            to_category,
            {
                "TECHNOLOGY_TRIAL_OR_DEPLOYMENT": "TECHNICAL_DEVELOPMENT",
                "SERVICE_OPENING": "OPERATIONAL_CHANGE",
                "SERVICE_CHANGE": "OPERATIONAL_CHANGE",
                "OPERATIONAL_DISPUTE": "OPERATIONAL_CHANGE",
                "OPERATIONAL_GOVERNANCE": "OPERATIONAL_CHANGE",
                "INCIDENT_OR_FAILURE": "INCIDENT",
                "FORMAL_PROCUREMENT_ACTION": "PROCUREMENT",
                "NORMATIVE_ACTION": "NORMATIVE_CHANGE",
            },
        )
        self.assertEqual(
            table[CategoryPrincipalAction.RECOMMENDATION_WITHOUT_ADOPTION],
            CategoryResolutionReason.RECOMMENDATION_WITHOUT_ADOPTED_ACTION,
        )
        no_category = {action.value for action, target in table.items() if target is CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION}
        self.assertEqual(
            no_category,
            {"PRE_SERVICE_OR_ACCEPTANCE_TEST", "PROJECT_STEP", "DRILL_OR_TRAINING", "NON_TRANSPORT_SERVICE",
             "STATISTICS_RANKING_OR_AWARD", "STATEMENT_OR_COMMENTARY", "EVENT_OR_EXHIBITION", "OTHER"},
        )


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
