"""Golden acceptance checks for the Event Identity boundary."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.weekly_report.contracts import (
    EvidenceState,
    EventIdentityFacts,
    ScopeState,
)
from src.weekly_report.event_identity import EventIdentity, EventIdentityRelation
from tests.test_event_identity_contract import _PairAdvisor, _SemanticAdvisor, _record


ROOT = Path(__file__).resolve().parents[1]


class EventDedupGoldenTests(unittest.TestCase):
    def test_event_dedup_golden_index_is_complete(self):
        manifest = json.loads(
            (ROOT / "golden" / "event_dedup_cases.json").read_text(encoding="utf-8")
        )
        cases = manifest["cases"]
        self.assertEqual(len(cases), 15)
        self.assertEqual(
            {case["case_class"] for case in cases},
            {
                "exact_duplicate_source",
                "official_secondary_same_event",
                "tender_vs_award",
                "delivery_testing_service",
                "incident_vs_investigation",
                "repeated_incidents",
                "insufficient_identity",
                "multilingual_same_event",
                "publication_date_difference",
                "transitivity_trap",
                "input_order_permutation",
                "singleton",
                "invalid_semantic_response",
                "unresolved_non_identity_claim",
                "ineligible_upstream_excluded",
            },
        )
        for case in cases:
            self.assertGreaterEqual(len(case["records"]), 1)
            self.assertEqual(
                len({record["candidate_id"] for record in case["records"]}),
                len(case["records"]),
            )
            self.assertEqual(len(case["expected_group_sizes"]), case["expected_group_count"])

    @classmethod
    def _load_event_dedup_cases(cls):
        return json.loads(
            (ROOT / "golden" / "event_dedup_cases.json").read_text(encoding="utf-8")
        )["cases"]

    @staticmethod
    def _advisor_for_case(case):
        if case.get("semantic_relation") == "INVALID":
            return _SemanticAdvisor(invalid=True)
        if case.get("semantic_relation") == EventIdentityRelation.SAME_EVENT.value:
            return _SemanticAdvisor()
        pairs = {
            tuple(pair.split(":")): relation == EventIdentityRelation.SAME_EVENT.value
            for pair, relation in case.get("semantic_pairs", {}).items()
        }
        return _PairAdvisor(pairs) if pairs else None

    @staticmethod
    def _materialize_case(case):
        records = []
        for item in case["records"]:
            facts = (
                EventIdentityFacts.from_mapping(item["facts"])
                if item.get("facts") is not None
                else None
            )
            upstream_state = item.get("upstream_state")
            if upstream_state is None:
                eligible = item.get("eligible", True)
                evidence_state = EvidenceState.READY if eligible else EvidenceState.REJECTED
                in_scope = True
                date_valid = True
            elif upstream_state == "READY":
                evidence_state = EvidenceState.READY
                in_scope = True
                date_valid = True
            elif upstream_state == "EVIDENCE_REJECTED":
                evidence_state = EvidenceState.REJECTED
                in_scope = True
                date_valid = True
            elif upstream_state == "OUT_OF_SCOPE":
                evidence_state = EvidenceState.READY
                in_scope = False
                date_valid = True
            elif upstream_state == "DATE_INVALID":
                evidence_state = EvidenceState.READY
                in_scope = True
                date_valid = False
            else:
                raise ValueError(f"unknown upstream_state: {upstream_state}")
            records.append(
                _record(
                    item["candidate_id"],
                    facts=facts,
                    body=item.get("body", "Synthetic Evidence body for this Event Dedup case."),
                    url=item.get("url"),
                    published_at=item.get("published_at", "2026-09-15T10:00:00Z"),
                    evidence_state=evidence_state,
                    in_scope=in_scope,
                    date_valid=date_valid,
                )
            )
        return records

    def test_ed09_materializes_distinct_candidate_published_at_values(self):
        case = next(item for item in self._load_event_dedup_cases() if item["case_id"] == "ED09")
        records = self._materialize_case(case)
        values = {record.candidate.candidate_id: record.candidate.published_at for record in records}
        self.assertEqual(values, {"N": "2026-09-15", "N1": "2026-09-16"})

    def test_ed15_materializes_real_upstream_states(self):
        case = next(item for item in self._load_event_dedup_cases() if item["case_id"] == "ED15")
        records = self._materialize_case(case)
        by_id = {record.candidate.candidate_id: record for record in records}
        self.assertIs(by_id["READY"].evidence.state, EvidenceState.READY)
        self.assertIs(by_id["REJECTED"].evidence.state, EvidenceState.REJECTED)
        self.assertIs(by_id["OUT_OF_SCOPE"].scope.state, ScopeState.OUT_OF_SCOPE)
        self.assertFalse(by_id["DATE_INVALID"].temporal.date_valid)

    def test_all_ed01_to_ed15_execute_through_event_identity(self):
        for case in self._load_event_dedup_cases():
            with self.subTest(case_id=case["case_id"]):
                owner = EventIdentity(self._advisor_for_case(case))
                result = owner.evaluate(self._materialize_case(case))
                self.assertEqual(len(result.groups), case["expected_group_count"])
                self.assertEqual(
                    sorted(len(group.member_candidate_ids) for group in result.groups),
                    case["expected_group_sizes"],
                )
                all_members = [
                    candidate_id
                    for group in result.groups
                    for candidate_id in group.member_candidate_ids
                ]
                self.assertEqual(len(all_members), len(set(all_members)))

                if case["case_id"] == "ED10":
                    self.assertNotIn(("A", "B", "C"), [group.member_candidate_ids for group in result.groups])
                elif case["case_id"] == "ED13":
                    self.assertTrue(any(item.reason == "SEMANTIC_ADVISOR_INVALID" for item in result.diagnostics))
                elif case["case_id"] == "ED14":
                    self.assertEqual(result.groups[0].unresolved_claims[0].claim_key, "duration")
                elif case["case_id"] == "ED15":
                    self.assertEqual(all_members, ["READY"])

    def test_ed11_golden_case_is_order_invariant(self):
        case = next(item for item in self._load_event_dedup_cases() if item["case_id"] == "ED11")
        records = self._materialize_case(case)
        expected = [
            (group.member_candidate_ids, group.canonical_candidate_id, group.event_id)
            for group in EventIdentity().group(records)
        ]
        import itertools

        for permutation in itertools.permutations(records):
            actual = [
                (group.member_candidate_ids, group.canonical_candidate_id, group.event_id)
                for group in EventIdentity().group(permutation)
            ]
            self.assertEqual(actual, expected)

    def test_existing_g12_g13_g16_expectations_reach_event_identity_owner(self):
        cases = {
            case["case_id"]: json.loads(
                (ROOT / "golden" / case["file"]).read_text(encoding="utf-8")
            )
            for case in json.loads(
                (ROOT / "golden" / "manifest.json").read_text(encoding="utf-8")
            )["cases"]
            if case["case_id"] in {"G12", "G13", "G16"}
        }

        g12 = cases["G12"]["candidates"]
        groups = EventIdentity(_SemanticAdvisor()).group(
            [
                _record(candidate["candidate_id"], body=candidate["source_content"])
                for candidate in g12
            ]
        )
        self.assertEqual(len(groups), cases["G12"]["expected"]["event_count_after_dedup"])

        g13 = cases["G13"]["candidates"]
        groups = EventIdentity().group(
            [
                _record(
                    candidate["candidate_id"],
                    facts=EventIdentityFacts(
                        action="award",
                        lifecycle_step=candidate["event_facts"]["lifecycle"],
                        subject="line-1-signalling",
                        project=candidate["event_facts"]["project"],
                        package=candidate["event_facts"]["project"],
                        location=candidate["event_facts"]["city"],
                        occurrence_context="line-1 signalling award event",
                    ),
                    body=candidate["source_content"],
                )
                for candidate in g13
            ]
        )
        self.assertEqual(len(groups), cases["G13"]["expected"]["event_count_after_dedup"])

        g16 = cases["G16"]["candidates"]
        groups = EventIdentity().group(
            [
                _record(
                    candidate["candidate_id"],
                    facts=EventIdentityFacts(
                        event_key="airport-branch-power-fault",
                        action="incident",
                        lifecycle_step="occurrence",
                        subject="traction-power-fault",
                        asset="airport-branch",
                        location="airport-branch",
                        occurrence_context="airport branch traction power fault occurrence",
                        non_identity_claims={
                            candidate["claim"]["field"]: str(candidate["claim"]["value"])
                        },
                    ),
                    body=candidate["source_content"],
                )
                for candidate in g16
            ]
        )
        self.assertEqual(len(groups), cases["G16"]["expected"]["event_count_after_dedup"])
        self.assertEqual(groups[0].unresolved_claims[0].claim_key, "service_duration_minutes")


if __name__ == "__main__":
    unittest.main()
