"""Contract-level validation for the deterministic Golden Corpus."""

from __future__ import annotations

import json
import unittest
from datetime import date
from pathlib import Path

from src.weekly_report.contracts import (
    CanonicalCandidate,
    CategoryId,
    CategoryResult,
    CategoryState,
    EvidenceResult,
    EvidenceState,
    EventDecisionRecord,
    EventGroup,
    EventIdentityFacts,
    EventIdentityRecord,
    EMSystemId,
    ReportabilityEvidenceProvenance,
    ReportabilityReason,
    ReportabilityResult,
    ReportabilityState,
    ReportabilitySupportSpan,
    ScopeResult,
    ScopeState,
    SourceDateKind,
    TaxonomyConflictEvidenceProvenance,
    TaxonomyInsufficientEvidenceProvenance,
    TaxonomyResolutionReason,
    TaxonomyResult,
    TaxonomyState,
    TaxonomySupportSpan,
    TemporalResult,
    canonical_em_system_ids,
)
from src.weekly_report.ordering import Ordering
from src.weekly_report.report_workflow import ReportWorkflowResult


ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "golden"
CASES = GOLDEN / "cases"


def _materialize_ordering_event(event: dict) -> ReportWorkflowResult:
    """Build one typed workflow result from a declarative Ordering fixture."""

    event_id = event["event_id"]
    category_id = CategoryId(event.get("category_id", CategoryId.PROCUREMENT.value))
    member_records = []
    member_candidate_ids = []
    for member in event["members"]:
        candidate_id = member["candidate_id"]
        member_candidate_ids.append(candidate_id)
        controlling_date = date.fromisoformat(
            member["temporal"]["controlling_calendar_date"]
        )
        identity_facts = EventIdentityFacts(
            location=member.get("identity_facts", {}).get("location", "")
        )
        candidate = CanonicalCandidate(
            candidate_id=candidate_id,
            title=f"Golden {candidate_id}",
            url=f"https://fixtures.invalid/ordering/{candidate_id}",
            publisher="Synthetic Ordering Golden",
        )
        member_records.append(
            EventIdentityRecord(
                candidate=candidate,
                evidence=EvidenceResult(
                    candidate_id=candidate_id,
                    state=EvidenceState.READY,
                    canonical_source_url=candidate.url,
                    source_type="synthetic_ordering_golden",
                    substantive_content="Synthetic authoritative Ordering fixture content.",
                    identity_facts=identity_facts,
                ),
                scope=ScopeResult(candidate_id, ScopeState.IN_SCOPE),
                temporal=TemporalResult(
                    candidate_id=candidate_id,
                    date_valid=member["temporal"]["date_valid"],
                    controlling_calendar_date=controlling_date,
                    controlling_date_kind=SourceDateKind.ORIGINAL_PUBLICATION,
                ),
            )
        )

    event_group = EventGroup(
        event_id=event_id,
        member_candidate_ids=tuple(member_candidate_ids),
        canonical_candidate_id=event["canonical_member_candidate_id"],
        identity_basis=(),
    )
    category_result = CategoryResult(
        CategoryState.CATEGORY_ASSIGNED,
        event_id=event_id,
        primary_category_id=category_id,
        primary_category=category_id.display_label,
        classification_reason=f"PRINCIPAL_ACTION_{category_id.value}",
    )
    taxonomy_systems = tuple(
        EMSystemId(system_id) for system_id in event.get("taxonomy_systems", ())
    )
    taxonomy_result = TaxonomyResult(
        TaxonomyState.TAXONOMY_EVALUATED,
        event_id=event_id,
        systems=taxonomy_systems,
        support_spans=tuple(
            TaxonomySupportSpan(
                system_id,
                event["canonical_member_candidate_id"],
                0,
                1,
            )
            for system_id in taxonomy_systems
        ),
    )
    decision = EventDecisionRecord(
        event_group,
        tuple(member_records),
        category_result,
        taxonomy_result,
    )
    reportability_state = ReportabilityState(event["reportability_state"])
    reportability_result = ReportabilityResult(
        event_id,
        reportability_state,
        (
            None
            if reportability_state is ReportabilityState.REPORTABLE
            else ReportabilityReason.LOW_REPORTABILITY_VALUE
        ),
        ReportabilityEvidenceProvenance(
            tuple(member_candidate_ids),
            (
                (ReportabilitySupportSpan(member_candidate_ids[0], 0, 1),)
                if reportability_state is ReportabilityState.REPORTABLE
                else ()
            ),
            "Synthetic Ordering Golden fixture.",
        ),
    )
    return ReportWorkflowResult(decision, reportability_result)


def _materialize_ordering_case(fixture: dict) -> tuple[ReportWorkflowResult, ...]:
    """Materialize fixture input in declared order without ranking or filtering."""

    return tuple(_materialize_ordering_event(event) for event in fixture["input"]["events"])


class GoldenContractTests(unittest.TestCase):
    TAXONOMY_EXTENSION_IDS = frozenset({f"G{i:02d}" for i in range(86, 92)})
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
        cls.taxonomy_manifest = json.loads(
            (GOLDEN / "taxonomy_manifest.json").read_text(encoding="utf-8")
        )
        cls.taxonomy_fixtures = {
            entry["case_id"]: json.loads(
                (GOLDEN / entry["file"]).read_text(encoding="utf-8")
            )
            for entry in cls.taxonomy_manifest["cases"]
        }
        cls.ordering_manifest = json.loads(
            (GOLDEN / "ordering_manifest.json").read_text(encoding="utf-8")
        )
        cls.ordering_entries = cls.ordering_manifest["cases"]
        cls.ordering_fixtures = {
            entry["case_id"]: json.loads(
                (GOLDEN / entry["file"]).read_text(encoding="utf-8")
            )
            for entry in cls.ordering_entries
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

    def test_taxonomy_manifest_is_explicitly_isolated(self):
        category_ids = [entry["case_id"] for entry in self.entries]
        taxonomy_ids = [entry["case_id"] for entry in self.taxonomy_manifest["cases"]]

        self.assertEqual(len(category_ids), len(set(category_ids)))
        self.assertEqual(len(taxonomy_ids), len(set(taxonomy_ids)))
        self.assertTrue(self.taxonomy_manifest["category_acceptance_population_excluded"])
        self.assertEqual(self.taxonomy_manifest["case_count"], len(taxonomy_ids))
        self.assertEqual(set(taxonomy_ids), self.TAXONOMY_EXTENSION_IDS)
        self.assertTrue(set(category_ids).isdisjoint(taxonomy_ids))

        for entry in self.taxonomy_manifest["cases"]:
            fixture_path = GOLDEN / entry["file"]
            self.assertTrue(fixture_path.is_file(), entry["case_id"])
            fixture = self.taxonomy_fixtures[entry["case_id"]]
            self.assertEqual(fixture["case_id"], entry["case_id"])

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
                if expected["subtype"] is not None:
                    self.assertIsInstance(expected["subtype"], str, fixture["case_id"])
                    self.assertRegex(
                        expected["subtype"],
                        r"^[a-z][a-z0-9_]{0,63}$",
                        fixture["case_id"],
                    )
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
        self.assertEqual(mixed["expected"]["category_state"], "CATEGORY_UNRESOLVED")
        self.assertEqual(
            mixed["expected"]["category_resolution_reason"],
            "NO_UNIQUE_PRINCIPAL_ACTION",
        )
        low_value = self.fixtures["G85"]["expected"]
        self.assertEqual(low_value["category_state"], "CATEGORY_ASSIGNED")
        self.assertEqual(low_value["primary_category_id"], "PROCUREMENT")
        self.assertEqual(low_value["subtype"], "award")
        self.assertEqual(low_value["classification_reason"], "PRINCIPAL_ACTION_PROCUREMENT")
        self.assertEqual(low_value["reportability"], "NOT_REPORTABLE")

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

    def test_taxonomy_projection_representation_is_consistent(self):
        all_taxonomy_fixtures = {**self.fixtures, **self.taxonomy_fixtures}
        for case_id, fixture in all_taxonomy_fixtures.items():
            expected = fixture["expected"]
            raw_systems = expected["e&m_taxonomy"]
            explicit_state = expected.get("taxonomy_state")
            reason = expected.get("taxonomy_resolution_reason")

            if raw_systems == "NOT_EVALUATED":
                if explicit_state is not None:
                    self.assertEqual(explicit_state, TaxonomyState.NOT_EVALUATED.value, case_id)
                self.assertIsNone(reason, case_id)
                self.assertNotIn("taxonomy_support_spans", expected, case_id)
                self.assertNotIn("taxonomy_provenance", expected, case_id)
                continue

            self.assertIsInstance(raw_systems, list, case_id)
            self.assertNotEqual(explicit_state, TaxonomyState.NOT_EVALUATED.value, case_id)
            state = TaxonomyState(explicit_state or TaxonomyState.TAXONOMY_EVALUATED.value)

            if state is TaxonomyState.TAXONOMY_EVALUATED:
                self.assertIsNone(reason, case_id)
                self.assertNotIn("taxonomy_provenance", expected, case_id)
                if not raw_systems:
                    self.assertNotIn("taxonomy_support_spans", expected, case_id)
            else:
                self.assertEqual(state, TaxonomyState.TAXONOMY_UNRESOLVED, case_id)
                self.assertEqual(raw_systems, [], case_id)
                self.assertIn(reason, {item.value for item in TaxonomyResolutionReason}, case_id)
                self.assertIsInstance(expected.get("taxonomy_provenance"), dict, case_id)

    def test_designated_taxonomy_provenance_is_required(self):
        display_to_id = {
            system_id.display_label: system_id.value for system_id in canonical_em_system_ids()
        }

        for case_id in ("G52", "G86", "G88"):
            expected = ({**self.fixtures, **self.taxonomy_fixtures})[case_id]["expected"]
            self.assertEqual(expected.get("taxonomy_state"), TaxonomyState.TAXONOMY_EVALUATED.value)
            assigned = {display_to_id[label] for label in expected["e&m_taxonomy"]}
            spans = expected.get("taxonomy_support_spans")
            self.assertIsInstance(spans, list, case_id)
            self.assertTrue(spans, case_id)
            span_systems = {span["system_id"] for span in spans}
            self.assertEqual(span_systems, assigned, case_id)
            candidate_ids = {
                candidate["candidate_id"]
                for candidate in ({**self.fixtures, **self.taxonomy_fixtures})[case_id]["candidates"]
            }
            for span in spans:
                self.assertIn(span["candidate_id"], candidate_ids, case_id)

        all_fixtures = {**self.fixtures, **self.taxonomy_fixtures}
        for case_id in ("G19", "G62"):
            expected = all_fixtures[case_id]["expected"]
            self.assertEqual(expected.get("taxonomy_state"), TaxonomyState.TAXONOMY_UNRESOLVED.value)
            self.assertEqual(
                expected.get("taxonomy_resolution_reason"),
                TaxonomyResolutionReason.INSUFFICIENT_SYSTEM_EVIDENCE.value,
                case_id,
            )
            provenance = expected.get("taxonomy_provenance")
            self.assertIsInstance(provenance, dict, case_id)
            self.assertTrue(provenance.get("member_candidate_ids"), case_id)
            self.assertTrue(provenance.get("diagnostic"), case_id)

        conflict = all_fixtures["G87"]["expected"]
        self.assertEqual(
            conflict.get("taxonomy_state"), TaxonomyState.TAXONOMY_UNRESOLVED.value
        )
        self.assertEqual(
            conflict.get("taxonomy_resolution_reason"),
            TaxonomyResolutionReason.CONFLICTING_SYSTEM_EVIDENCE.value,
        )
        conflict_spans = conflict.get("taxonomy_provenance", {}).get("conflict_spans")
        self.assertIsInstance(conflict_spans, list)
        self.assertEqual(
            {span["system_id"] for span in conflict_spans},
            {EMSystemId.SIGNALLING.value, EMSystemId.POWER_SUPPLY.value},
        )
        candidate_ids = {candidate["candidate_id"] for candidate in all_fixtures["G87"]["candidates"]}
        self.assertTrue(all(span["candidate_id"] in candidate_ids for span in conflict_spans))

    def test_taxonomy_values_follow_typed_contract_and_provenance_shape(self):
        display_to_id = {
            system_id.display_label: system_id for system_id in canonical_em_system_ids()
        }
        canonical_order = list(canonical_em_system_ids())

        all_taxonomy_fixtures = {**self.fixtures, **self.taxonomy_fixtures}
        for case_id, fixture in all_taxonomy_fixtures.items():
            expected = fixture["expected"]
            candidates_by_id = {
                candidate["candidate_id"]: candidate for candidate in fixture["candidates"]
            }

            def assert_span_is_member_and_bounded(span: TaxonomySupportSpan) -> None:
                self.assertIn(span.candidate_id, candidates_by_id, case_id)
                source_content = candidates_by_id[span.candidate_id]["source_content"]
                self.assertLessEqual(span.end, len(source_content), case_id)
                self.assertTrue(source_content[span.start : span.end], case_id)

            raw_systems = expected["e&m_taxonomy"]
            explicit_state = expected.get("taxonomy_state")
            if explicit_state is None:
                state = (
                    TaxonomyState.NOT_EVALUATED
                    if raw_systems == "NOT_EVALUATED"
                    else TaxonomyState.TAXONOMY_EVALUATED
                )
            else:
                state = TaxonomyState(explicit_state)

            if state is TaxonomyState.NOT_EVALUATED:
                self.assertEqual(raw_systems, "NOT_EVALUATED", case_id)
                self.assertNotIn("taxonomy_support_spans", expected, case_id)
                self.assertNotIn("taxonomy_provenance", expected, case_id)
                continue

            self.assertIsInstance(raw_systems, list, case_id)
            system_ids = [display_to_id[label] for label in raw_systems]
            self.assertEqual(len(system_ids), len(set(system_ids)), case_id)
            self.assertEqual(
                system_ids,
                [system_id for system_id in canonical_order if system_id in system_ids],
                case_id,
            )

            reason_value = expected.get("taxonomy_resolution_reason")
            if state is TaxonomyState.TAXONOMY_EVALUATED:
                self.assertIsNone(reason_value, case_id)
                if not system_ids:
                    self.assertNotIn("taxonomy_support_spans", expected, case_id)
            else:
                reason = TaxonomyResolutionReason(reason_value)
                self.assertEqual(system_ids, [], case_id)
                provenance = expected.get("taxonomy_provenance")
                self.assertIsInstance(provenance, dict, case_id)
                if reason is TaxonomyResolutionReason.INSUFFICIENT_SYSTEM_EVIDENCE:
                    typed = TaxonomyInsufficientEvidenceProvenance(
                        tuple(provenance["member_candidate_ids"]),
                        provenance["diagnostic"],
                    )
                    self.assertTrue(typed.member_candidate_ids, case_id)
                    member_ids = {
                        candidate["candidate_id"] for candidate in fixture["candidates"]
                    }
                    self.assertTrue(
                        set(typed.member_candidate_ids).issubset(member_ids), case_id
                    )
                else:
                    typed_spans = tuple(
                        TaxonomySupportSpan(
                            EMSystemId(span["system_id"]),
                            span["candidate_id"],
                            span["start"],
                            span["end"],
                        )
                        for span in provenance["conflict_spans"]
                    )
                    for typed_span in typed_spans:
                        assert_span_is_member_and_bounded(typed_span)
                    self.assertIsInstance(
                        TaxonomyConflictEvidenceProvenance(typed_spans),
                        TaxonomyConflictEvidenceProvenance,
                    )

            for span in expected.get("taxonomy_support_spans", ()):
                typed_span = TaxonomySupportSpan(
                    EMSystemId(span["system_id"]),
                    span["candidate_id"],
                    span["start"],
                    span["end"],
                )
                self.assertIn(typed_span.system_id, system_ids, case_id)
                assert_span_is_member_and_bounded(typed_span)

    def test_taxonomy_coverage_and_contextual_boundaries_are_locked(self):
        display_to_id = {
            system_id.display_label: system_id for system_id in canonical_em_system_ids()
        }
        counts = {system_id: 0 for system_id in canonical_em_system_ids()}
        state_counts = {state: 0 for state in TaxonomyState}
        multi_label_groups = 0
        total_groups = reached_groups = not_evaluated_groups = 0

        all_taxonomy_fixtures = {**self.fixtures, **self.taxonomy_fixtures}
        for fixture in all_taxonomy_fixtures.values():
            expected = fixture["expected"]
            group_count = expected["event_count_after_dedup"]
            if not isinstance(group_count, int):
                continue
            total_groups += group_count
            raw_systems = expected["e&m_taxonomy"]
            state = TaxonomyState(
                expected.get(
                    "taxonomy_state",
                    "NOT_EVALUATED" if raw_systems == "NOT_EVALUATED" else "TAXONOMY_EVALUATED",
                )
            )
            state_counts[state] += group_count
            if state is TaxonomyState.NOT_EVALUATED:
                not_evaluated_groups += group_count
                continue
            reached_groups += group_count
            if state is TaxonomyState.TAXONOMY_EVALUATED:
                system_ids = [display_to_id[label] for label in raw_systems]
                for system_id in system_ids:
                    counts[system_id] += group_count
                if len(system_ids) > 1:
                    multi_label_groups += group_count

        self.assertEqual(total_groups, 59)
        self.assertEqual(reached_groups, 53)
        self.assertEqual(not_evaluated_groups, 6)
        self.assertEqual(state_counts[TaxonomyState.TAXONOMY_EVALUATED], 50)
        self.assertEqual(state_counts[TaxonomyState.TAXONOMY_UNRESOLVED], 3)
        self.assertEqual(counts[EMSystemId.ROLLING_STOCK], 6)
        self.assertEqual(counts[EMSystemId.SIGNALLING], 11)
        self.assertEqual(counts[EMSystemId.POWER_SUPPLY], 9)
        self.assertEqual(counts[EMSystemId.COMMUNICATIONS], 4)
        self.assertEqual(counts[EMSystemId.AUTOMATIC_FARE_COLLECTION], 2)
        self.assertEqual(counts[EMSystemId.DEPOT_MAINTENANCE_EQUIPMENT], 1)
        self.assertEqual(counts[EMSystemId.PLATFORM_SCREEN_DOORS], 3)
        self.assertEqual(multi_label_groups, 1)

        self.assertEqual(
            self.taxonomy_fixtures["G88"]["expected"]["e&m_taxonomy"], ["供電"]
        )
        self.assertEqual(self.taxonomy_fixtures["G89"]["expected"]["e&m_taxonomy"], [])
        self.assertEqual(self.taxonomy_fixtures["G90"]["expected"]["e&m_taxonomy"], [])
        self.assertEqual(self.taxonomy_fixtures["G91"]["expected"]["e&m_taxonomy"], [])

    def test_reportability_projection_follows_reachability_and_locked_cases(self):
        all_fixtures = {**self.fixtures, **self.taxonomy_fixtures}
        for case_id, fixture in all_fixtures.items():
            expected = fixture["expected"]
            category_reached = expected["category_state"] == "CATEGORY_ASSIGNED"
            raw_systems = expected["e&m_taxonomy"]
            taxonomy_state = expected.get("taxonomy_state")
            taxonomy_reached = raw_systems != "NOT_EVALUATED" and taxonomy_state in {
                None,
                "TAXONOMY_EVALUATED",
            }
            reportability = expected["reportability"]

            if not (category_reached and taxonomy_reached):
                self.assertEqual(reportability, "NOT_EVALUATED", case_id)
                # Preserve upstream rejection metadata, but never project a
                # Reportability rejection before Reportability is reached.
                self.assertNotEqual(expected["reject_stage"], "REPORTABILITY", case_id)
                self.assertNotEqual(expected["reject_reason"], "LOW_REPORTABILITY_VALUE", case_id)
            else:
                self.assertIn(reportability, {"REPORTABLE", "NOT_REPORTABLE"}, case_id)
                if reportability == "REPORTABLE":
                    self.assertNotEqual(expected["reject_stage"], "REPORTABILITY", case_id)
                    self.assertNotEqual(expected["reject_reason"], "LOW_REPORTABILITY_VALUE", case_id)
                else:
                    self.assertEqual(expected["reject_stage"], "REPORTABILITY", case_id)
                    self.assertEqual(expected["reject_reason"], "LOW_REPORTABILITY_VALUE", case_id)

        self.assertEqual(self.fixtures["G07"]["expected"]["reportability"], "NOT_REPORTABLE")
        self.assertEqual(self.fixtures["G07"]["expected"]["reject_stage"], "REPORTABILITY")
        self.assertEqual(self.fixtures["G07"]["expected"]["reject_reason"], "LOW_REPORTABILITY_VALUE")

        office_move = self.taxonomy_fixtures["G90"]["expected"]
        self.assertEqual(office_move["e&m_taxonomy"], [])
        self.assertEqual(office_move["reportability"], "NOT_REPORTABLE")
        self.assertEqual(office_move["reject_stage"], "REPORTABILITY")
        self.assertEqual(office_move["reject_reason"], "LOW_REPORTABILITY_VALUE")

        self.assertEqual(self.fixtures["G17"]["expected"]["e&m_taxonomy"], [])
        self.assertEqual(self.fixtures["G17"]["expected"]["reportability"], "REPORTABLE")
        self.assertEqual(self.fixtures["G85"]["expected"]["reportability"], "NOT_REPORTABLE")

    def test_ordering_manifest_is_explicit_and_stage_scoped(self):
        manifest = self.ordering_manifest
        self.assertEqual(manifest["stage"], "ORDERING")
        self.assertFalse(manifest["live_search"])
        self.assertEqual(manifest["input_boundary"], "completed REPORTABLE population")
        self.assertEqual(manifest["mixed_reportability"], "NOT_APPLICABLE_AT_GOLDEN_BOUNDARY")
        self.assertFalse(manifest["failure_cases_supported"])
        self.assertEqual(manifest["case_count"], 9)
        self.assertEqual(len(self.ordering_entries), 9)
        self.assertEqual(
            [entry["case_id"] for entry in self.ordering_entries],
            [f"O{i:02d}" for i in range(1, 10)],
        )
        for entry in self.ordering_entries:
            fixture = self.ordering_fixtures[entry["case_id"]]
            self.assertEqual(fixture["case_id"], entry["case_id"])
            self.assertEqual(fixture["origin_type"], "SYNTHETIC_CONTRACT_CASE")
            self.assertTrue((GOLDEN / entry["file"]).is_file())

    def test_ordering_expected_orders_are_declarative_and_cardinality_preserving(self):
        expected_orders = {
            "O01": [],
            "O02": ["event-only"],
            "O03": ["event-newest", "event-middle", "event-old"],
            "O04": ["event-alpha", "event-zulu"],
            "O05": ["event-competitor", "event-canonical-authority"],
            "O06": [
                "event-12", "event-11", "event-10", "event-09", "event-08", "event-07",
                "event-06", "event-05", "event-04", "event-03", "event-02", "event-01",
            ],
            "O07": ["event-technical", "event-incident"],
            "O08": ["event-power", "event-signalling"],
            "O09": ["event-alpha", "event-zulu"],
        }
        for case_id, fixture in self.ordering_fixtures.items():
            events = fixture["input"]["events"]
            expected = fixture["expected"]
            input_ids = [event["event_id"] for event in events]
            self.assertEqual(expected["ordered_event_ids"], expected_orders[case_id], case_id)
            self.assertEqual(len(input_ids), len(set(input_ids)), case_id)
            self.assertEqual(set(expected["ordered_event_ids"]), set(input_ids), case_id)
            self.assertEqual(expected["input_count"], len(input_ids), case_id)
            self.assertEqual(expected["output_count"], len(expected["ordered_event_ids"]), case_id)
            self.assertTrue(expected["cardinality_preserved"], case_id)
            self.assertEqual(expected["input_count"], expected["output_count"], case_id)
            for event in events:
                self.assertEqual(event["reportability_state"], "REPORTABLE", case_id)

    def test_ordering_golden_locks_canonical_and_forbidden_dimensions(self):
        canonical = self.ordering_fixtures["O05"]["input"]["events"][0]
        self.assertEqual(canonical["canonical_member_candidate_id"], "candidate-canonical")
        members = {member["candidate_id"]: member for member in canonical["members"]}
        self.assertEqual(members["candidate-canonical"]["temporal"]["controlling_calendar_date"], "2026-09-10")
        self.assertEqual(members["candidate-secondary"]["temporal"]["controlling_calendar_date"], "2026-09-18")

        category_events = self.ordering_fixtures["O07"]["input"]["events"]
        self.assertEqual({event["category_id"] for event in category_events}, {"INCIDENT", "TECHNICAL_DEVELOPMENT"})
        taxonomy_events = self.ordering_fixtures["O08"]["input"]["events"]
        self.assertEqual({event["taxonomy_systems"][0] for event in taxonomy_events}, {"POWER_SUPPLY", "SIGNALLING"})
        geography_events = self.ordering_fixtures["O09"]["input"]["events"]
        events_by_id = {event["event_id"]: event for event in geography_events}
        self.assertEqual(
            events_by_id["event-zulu"]["members"][0]["identity_facts"]["location"],
            "Amsterdam",
        )
        self.assertEqual(
            events_by_id["event-alpha"]["members"][0]["identity_facts"]["location"],
            "Zurich",
        )
        locations = {
            event["members"][0]["identity_facts"]["location"] for event in geography_events
        }
        self.assertEqual(locations, {"Amsterdam", "Zurich"})
        self.assertEqual(
            [event["members"][0]["temporal"]["controlling_calendar_date"] for event in geography_events],
            ["2026-09-18", "2026-09-18"],
        )
        self.assertEqual(self.ordering_fixtures["O09"]["expected"]["ordered_event_ids"], ["event-alpha", "event-zulu"])

    def test_ordering_golden_executes_production_against_declared_expected_orders(self):
        for entry in self.ordering_entries:
            case_id = entry["case_id"]
            fixture = self.ordering_fixtures[case_id]
            with self.subTest(case_id=case_id):
                typed_events = _materialize_ordering_case(fixture)
                actual = Ordering().order(typed_events)
                actual_ids = tuple(item.event_group.event_id for item in actual)
                expected_ids = tuple(fixture["expected"]["ordered_event_ids"])

                self.assertEqual(actual_ids, expected_ids)
                self.assertEqual(len(actual), fixture["expected"]["output_count"])
                self.assertEqual(len(actual), len(typed_events))
                if case_id == "O06":
                    self.assertEqual(len(typed_events), 12)
                if case_id == "O07":
                    self.assertEqual(
                        {item.category_result.primary_category_id for item in typed_events},
                        {CategoryId.INCIDENT, CategoryId.TECHNICAL_DEVELOPMENT},
                    )
                if case_id == "O08":
                    self.assertEqual(
                        {item.taxonomy_result.systems[0] for item in typed_events},
                        {EMSystemId.POWER_SUPPLY, EMSystemId.SIGNALLING},
                    )
                if case_id == "O09":
                    self.assertEqual(
                        {
                            member.evidence.identity_facts.location
                            for item in typed_events
                            for member in item.member_records
                        },
                        {"Amsterdam", "Zurich"},
                    )

    def test_ordering_large_population_is_explicit_anti_zero_and_anti_top_n_lock(self):
        fixture = self.ordering_fixtures["O06"]
        self.assertEqual(len(fixture["input"]["events"]), 12)
        self.assertEqual(len(fixture["expected"]["ordered_event_ids"]), 12)
        self.assertEqual(fixture["expected"]["input_count"], 12)
        self.assertEqual(fixture["expected"]["output_count"], 12)
        self.assertEqual(
            fixture["expected"]["ordered_event_ids"],
            [
                "event-12", "event-11", "event-10", "event-09", "event-08", "event-07",
                "event-06", "event-05", "event-04", "event-03", "event-02", "event-01",
            ],
        )


if __name__ == "__main__":
    unittest.main()
