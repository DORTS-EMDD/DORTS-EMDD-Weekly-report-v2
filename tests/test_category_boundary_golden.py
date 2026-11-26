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
    # RC-84 (section A.65, user decision 2026-11-23).
    "G110": "SERVICE_OPENING_ANNOUNCEMENT",  # Essen: first Sunday of Advent
    "G111": "SERVICE_OPENING_ANNOUNCEMENT",  # expected in 2027, no date
    "G112": "SERVICE_OPENING_ANNOUNCEMENT",  # dated, beyond 30 days
    "G113": "TEMPORARY_EVENT_SERVICE",  # exam-day extra trains (Daegu)
    "G114": "EXTERNAL_HAZARD_PRECAUTION",  # car park fire (Almàssera)
    "G115": "INCIDENT_OR_FAILURE",  # platform smoke (Nagoya)
    "G116": "OPERATIONAL_DISPUTE",  # strike notice (Seoul Metro unions)
    "G117": "OPERATIONAL_GOVERNANCE",  # fare checks and patrols (DART)
    # RC-85 (section A.66, user decision 2026-11-24).
    "G118": "SUPPLIER_SYSTEM_ENGAGEMENT",  # CBTC radio network subcontract (Fortress)
    "G119": "PROJECT_STEP",  # project participation publicity
    # RC-86 (section A.67, user decisions 2026-11-25).
    "G120": "FAILURE_SERVICE_DISRUPTION",  # line curtailed after a fault (Warsaw M1)
    "G121": "ASSET_DISPOSAL",  # damaged cars at auction (Taichung)
    "G122": "SERVICE_CHANGE",  # replacement buses for a closed section (Sheffield)
    "G123": "PROCUREMENT_AUTHORIZATION",  # authorised air-conditioning renewal (Madrid)
    "G124": "PROJECT_STEP",  # tender plan without a formal decision
    "G125": "NETWORK_EQUIPMENT_INSPECTION",  # all-line inspection (Daegu)
    # RC-87 (section A.68, user decision 2026-11-25).
    "G126": "FAILURE_SERVICE_DISRUPTION",  # fault closure with replacement buses (Warsaw M1)
}
# RC-86: the amount and scope a PROCUREMENT_AUTHORIZATION case states (text of its first sentence).
BOUNDARY_AUTHORIZATION_TERMS = {
    "G123": {"amount": "3.4 million euros", "scope": "replace 720 air-conditioning components on the trains of metro line 1"},
}
# RC-84: the date the helper extracts for a SERVICE_OPENING_ANNOUNCEMENT case.
BOUNDARY_OPENING_DATES = {"G110": "2026-11-29", "G111": None, "G112": "2027-03-15"}


def _classify(entry, fixture, expected, records, groups):
    from datetime import date

    context = fixture["run_context"]
    period = (date.fromisoformat(context["period_start"]), date.fromisoformat(context["period_end"]))
    oracle = _GoldenSemanticOracle(
        expected,
        BOUNDARY_ACTIONS[entry["case_id"]],
        BOUNDARY_OPENING_DATES.get(entry["case_id"]),
        BOUNDARY_AUTHORIZATION_TERMS.get(entry["case_id"]),
    )
    return Classifier(oracle).classify(groups[0], records, report_period=period)


class CategoryBoundaryGoldenTests(unittest.TestCase):
    def test_manifest_is_isolated_from_the_locked_population(self):
        locked = json.loads((GOLDEN / "manifest.json").read_text(encoding="utf-8"))
        taxonomy = json.loads((GOLDEN / "taxonomy_manifest.json").read_text(encoding="utf-8"))
        ids = [entry["case_id"] for entry in MANIFEST["cases"]]
        self.assertEqual(ids, ["G92", "G93", "G94", "G95", "G96", "G97", "G98", "G99", "G100", "G101", "G102", "G103", "G104", "G105", "G106", "G107", "G108", "G109",
                               "G110", "G111", "G112", "G113", "G114", "G115", "G116", "G117", "G118", "G119",
                               "G120", "G121", "G122", "G123", "G124", "G125", "G126"])
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
                result = _classify(entry, fixture, expected, records, groups)
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
            [("G101", "TECHNICAL_DEVELOPMENT"), ("G107", "TECHNICAL_DEVELOPMENT"), ("G108", "TECHNICAL_DEVELOPMENT"), ("G109", "OPERATIONAL_CHANGE"),
             ("G110", "OPERATIONAL_CHANGE"), ("G115", "INCIDENT"), ("G116", "OPERATIONAL_CHANGE"), ("G117", "OPERATIONAL_CHANGE"),
             ("G118", "PROCUREMENT"), ("G120", "INCIDENT"), ("G122", "OPERATIONAL_CHANGE"), ("G123", "PROCUREMENT"),
             ("G125", "OPERATIONAL_CHANGE"), ("G126", "INCIDENT")],
        )
        for entry in assigned:
            fixture = json.loads((GOLDEN / entry["file"]).read_text(encoding="utf-8"))
            expected = fixture["expected"]
            with self.subTest(case_id=entry["case_id"]):
                self.assertEqual(expected["primary_category_id"], entry["category_family"])
                records = tuple(_materialize_record(candidate) for candidate in fixture["candidates"])
                groups = _materialize_groups(fixture, records)
                result = _classify(entry, fixture, expected, records, groups)
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

        self.assertEqual(CATEGORY_SEMANTIC_PROMPT_VERSION, "category-principal-action-v15")
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
        # RC-82 (user decision 2026-11-20): announced plans and executive
        # inspections are named under their existing actions (no new action).
        self.assertIn("Selection for a funding, development or demonstration programme", guidance)
        self.assertIn("when that work has not started, are PROJECT_STEP, not TECHNOLOGY_TRIAL_OR_DEPLOYMENT", guidance)
        self.assertIn("safety walk-through by executives, officials or a board", guidance)
        self.assertIn("is EVENT_OR_EXHIBITION, not OPERATIONAL_GOVERNANCE", guidance)
        # RC-84 (user decision 2026-11-23).
        self.assertIn("Python decides what the date means for the report; never judge that", guidance)
        self.assertIn("the first Sunday of Advent", guidance)
        self.assertIn("are TEMPORARY_EVENT_SERVICE, not this action", guidance)
        self.assertIn("whose source is outside the rail facilities", guidance)
        self.assertIn("Smoke or fire on or from a station, platform, tunnel, track, train, power supply or other rail equipment itself is this action", guidance)
        self.assertIn("A strike notice or threatened strike, a work-to-rule or slowdown", guidance)
        self.assertIn("Ticket inspections, fare-evasion checks, security or safety patrols", guidance)
        # RC-85 (user decision 2026-11-24).
        self.assertIn("engaged, contracted or commissioned to provide, supply, integrate or install an electrical and mechanical system", guidance)
        self.assertIn("also as a subcontractor within a larger project", guidance)
        self.assertIn("without naming a system it was engaged to provide, is PROJECT_STEP", guidance)
        # RC-86 (user decisions 2026-11-25).
        self.assertIn("SERVICE_CHANGE: a planned or announced change", guidance)
        self.assertIn("when the section stopped because of a failure or an accident, it is FAILURE_SERVICE_DISRUPTION", guidance)
        self.assertIn("the replacement transport (replacement buses or shuttles) arranged for such a planned or risk closure", guidance)
        self.assertIn("after an external safety risk to it was discovered (for example an old mineshaft found under the track)", guidance)
        # RC-87: a failure disruption wins over its replacement transport.
        self.assertIn("is always FAILURE_SERVICE_DISRUPTION, not this action, also when the evidence reports replacement buses", guidance)
        self.assertIn("This action takes precedence over SERVICE_CHANGE", guidance)
        self.assertIn("a contract for anything else is NON_RAIL_CONTRACT", guidance)
        self.assertIn("It is not FORMAL_PROCUREMENT_ACTION", guidance)
        self.assertIn("A plan, intention or announcement to tender without such a formal decision is PROJECT_STEP", guidance)
        self.assertIn("It is null when the evidence does not state both the amount and the scope", guidance)
        self.assertIn("comprehensive inspection of the equipment or facilities of a whole running line or of the whole network", guidance)

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
                "SUPPLIER_SYSTEM_ENGAGEMENT": "PROCUREMENT",
                "NORMATIVE_ACTION": "NORMATIVE_CHANGE",
                # RC-86 (section A.67).
                "FAILURE_SERVICE_DISRUPTION": "INCIDENT",
                "NETWORK_EQUIPMENT_INSPECTION": "OPERATIONAL_CHANGE",
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
             "STATISTICS_RANKING_OR_AWARD", "STATEMENT_OR_COMMENTARY", "EVENT_OR_EXHIBITION", "OTHER",
             # RC-84: SERVICE_OPENING_ANNOUNCEMENT's outcome outside its date window.
             "SERVICE_OPENING_ANNOUNCEMENT", "TEMPORARY_EVENT_SERVICE", "EXTERNAL_HAZARD_PRECAUTION",
             # RC-86: PROCUREMENT_AUTHORIZATION's outcome without a stated amount and scope.
             "PROCUREMENT_AUTHORIZATION", "NON_RAIL_CONTRACT", "ASSET_DISPOSAL"},
        )


class ScopeEventFocusContractTests(unittest.TestCase):
    def test_the_event_focus_must_contain_the_occurrence_sentence(self):
        # RC-65: Event Identity and Writer read only the focus (section A.14).
        from src.weekly_report import maiagent_scope_provider as scope_provider

        self.assertEqual(scope_provider.PROMPT_VERSION, "scope-event-target-system-v14")
        text = " ".join(scope_provider.SCOPE_SEMANTIC_INSTRUCTIONS)
        self.assertIn("must include the sentence or sentences that state the occurrence itself", text)
        self.assertIn("A lead summary, reactions, quotes or figures alone are not the event focus", text)


if __name__ == "__main__":
    unittest.main()


class OpeningAnnouncementWindowTests(unittest.TestCase):
    """RC-84: the 30-day window is Python date arithmetic over the report period."""

    def test_window_bounds(self):
        from datetime import date

        from src.weekly_report.classifier import OPENING_ANNOUNCEMENT_WINDOW_DAYS, opening_announcement_category
        from src.weekly_report.contracts import CategoryId, CategoryResolutionReason

        period = (date(2026, 11, 16), date(2026, 11, 22))
        self.assertEqual(OPENING_ANNOUNCEMENT_WINDOW_DAYS, 30)
        inside = {date(2026, 11, 16), date(2026, 11, 22), date(2026, 11, 29), date(2026, 12, 22)}
        outside = {date(2026, 11, 15), date(2026, 12, 23), date(2027, 3, 15)}
        for day in inside:
            self.assertIs(opening_announcement_category(day, period), CategoryId.OPERATIONAL_CHANGE)
        for day in outside:
            self.assertIs(opening_announcement_category(day, period), CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION)
        self.assertIs(opening_announcement_category(None, period), CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION)
        self.assertIs(opening_announcement_category(date(2026, 11, 29), None), CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION)

    def test_the_date_is_validated_and_recorded(self):
        from datetime import date

        entry = next(item for item in MANIFEST["cases"] if item["case_id"] == "G110")
        fixture = json.loads((GOLDEN / entry["file"]).read_text(encoding="utf-8"))
        records = tuple(_materialize_record(candidate) for candidate in fixture["candidates"])
        groups = _materialize_groups(fixture, records)
        period = (date(2026, 11, 16), date(2026, 11, 22))

        def run(action, opening_date):
            oracle = _GoldenSemanticOracle(fixture["expected"], action, opening_date)
            return Classifier(oracle).classify(groups[0], records, report_period=period)

        result = run("SERVICE_OPENING_ANNOUNCEMENT", "2026-11-29")
        self.assertEqual(result.provenance["announced_opening_date"], "2026-11-29")
        self.assertEqual(result.provenance["opening_window"], "WITHIN")
        self.assertEqual(result.primary_category_id.value, "OPERATIONAL_CHANGE")
        from src.weekly_report.classifier import CategoryProposalViolation

        for action, value in (("SERVICE_OPENING_ANNOUNCEMENT", "29 November"), ("SERVICE_OPENING_ANNOUNCEMENT", "2026-02-30"),
                              ("SERVICE_CHANGE", "2026-11-29")):
            with self.subTest(action=action, value=value), self.assertRaises(CategoryProposalViolation) as raised:
                run(action, value)
            self.assertEqual(raised.exception.failure_class, "OPENING_DATE")


class ProcurementAuthorizationTermsTests(unittest.TestCase):
    """RC-86 (section A.67): Python verifies the stated amount and scope and decides the Category."""

    def _run(self, action="PROCUREMENT_AUTHORIZATION", terms=None):
        entry = next(item for item in MANIFEST["cases"] if item["case_id"] == "G123")
        fixture = json.loads((GOLDEN / entry["file"]).read_text(encoding="utf-8"))
        records = tuple(_materialize_record(candidate) for candidate in fixture["candidates"])
        groups = _materialize_groups(fixture, records)
        oracle = _GoldenSemanticOracle(fixture["expected"], action, None, terms)
        return Classifier(oracle).classify(groups[0], records)

    def test_stated_terms_make_a_procurement_event(self):
        result = self._run(terms=BOUNDARY_AUTHORIZATION_TERMS["G123"])
        self.assertEqual(result.primary_category_id.value, "PROCUREMENT")
        self.assertEqual(result.provenance["principal_action"], "PROCUREMENT_AUTHORIZATION")
        self.assertEqual(result.provenance["authorization_terms"], "STATED")

    def test_without_terms_there_is_no_category_defining_action(self):
        result = self._run(terms=None)
        self.assertIs(result.category_state, CategoryState.CATEGORY_UNRESOLVED)
        self.assertEqual(result.category_resolution_reason.value, "NO_CATEGORY_DEFINING_ACTION")
        self.assertEqual(result.provenance["authorization_terms"], "NOT_STATED")

    def test_invalid_terms_are_a_disclosed_proposal_violation(self):
        from src.weekly_report.classifier import CategoryProposalViolation

        bad = (
            ("PROCUREMENT_AUTHORIZATION", {"amount": "3.5 million euros", "scope": "replace 720 air-conditioning components"}),
            ("PROCUREMENT_AUTHORIZATION", {"amount": "million euros", "scope": "replace 720 air-conditioning components"}),
            ("PROCUREMENT_AUTHORIZATION", {"amount": "3.4 million euros", "scope": "new signalling"}),
            ("PROCUREMENT_AUTHORIZATION", {"amount": "3.4 million euros"}),
            ("FORMAL_PROCUREMENT_ACTION", BOUNDARY_AUTHORIZATION_TERMS["G123"]),
        )
        for action, terms in bad:
            with self.subTest(action=action, terms=terms):
                with self.assertRaises(CategoryProposalViolation) as raised:
                    self._run(action, terms)
                self.assertEqual(raised.exception.failure_class, "AUTHORIZATION_TERMS")
