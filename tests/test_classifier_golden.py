"""Golden-driven Classifier boundary tests using an injected semantic oracle.

The fixture helper returns each sealed expected semantic judgment. It contains
no Category rules; these tests exercise Classifier input gating, response
validation, result construction, and all Category state contracts without a
configured production model provider.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.weekly_report.classifier import CategorySemanticRequest, Classifier
from src.weekly_report.contracts import (
    CanonicalCandidate,
    CategoryId,
    CategoryResult,
    CategoryState,
    EvidenceResult,
    EvidenceState,
    EventGroup,
    EventIdentityFacts,
    EventIdentityRecord,
    IdentityMetadataSupport,
    ScopeResult,
    ScopeState,
    TemporalResult,
    UnresolvedClaim,
)


ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "golden"


class _GoldenSemanticOracle:
    """Supply sealed per-fixture judgments without reimplementing semantics."""

    def __init__(self, expected):
        self.expected = expected

    def __call__(self, request: CategorySemanticRequest):
        expected = self.expected
        sources = request.sources
        citations = [
            {
                "candidate_id": source.candidate_id,
                "quote": source.substantive_content,
            }
            for source in sources
        ]
        category_state = expected["category_state"]
        if category_state == CategoryState.CATEGORY_ASSIGNED.value:
            return {
                "category_state": category_state,
                "primary_category_id": expected["primary_category_id"],
                "subtype": expected["subtype"],
                "category_resolution_reason": None,
                "citations": citations[:1],
            }
        if category_state == CategoryState.CATEGORY_UNRESOLVED.value:
            reason = expected["category_resolution_reason"]
            return {
                "category_state": category_state,
                "primary_category_id": None,
                "subtype": None,
                "category_resolution_reason": reason,
                "citations": citations,
            }
        raise AssertionError("the semantic oracle is not called for NOT_EVALUATED fixtures")


def _materialize_record(candidate: dict) -> EventIdentityRecord:
    candidate_id = candidate["candidate_id"]
    event_facts = candidate.get("event_facts", {})
    claim = candidate.get("claim", {})
    facts = EventIdentityFacts(
        action=str(event_facts.get("action", "")),
        lifecycle_step=str(event_facts.get("lifecycle", "")),
        project=str(event_facts.get("project", "")),
        location=str(event_facts.get("city", "")),
        non_identity_claims=(
            {str(claim["field"]): str(claim["value"])}
            if claim.get("field") is not None
            else {}
        ),
    )
    source_content = candidate["source_content"]
    if facts.location:
        if facts.location not in source_content:
            source_content = f"{source_content} {facts.location}"
        start = source_content.index(facts.location)
        facts = EventIdentityFacts(
            action=facts.action,
            lifecycle_step=facts.lifecycle_step,
            project=facts.project,
            location=facts.location,
            non_identity_claims=facts.non_identity_claims,
            metadata_support=(
                IdentityMetadataSupport("location", start, start + len(facts.location)),
            ),
        )
    canonical = CanonicalCandidate.from_mapping(candidate)
    evidence = EvidenceResult(
        candidate_id=candidate_id,
        state=EvidenceState.READY,
        canonical_source_url=candidate["url"],
        source_type="synthetic_golden_source",
        substantive_content=source_content,
        provenance={"canonical_source": candidate["url"]},
        identity_facts=facts,
    )
    scope = ScopeResult(candidate_id=candidate_id, state=ScopeState.IN_SCOPE)
    temporal = TemporalResult(candidate_id=candidate_id, date_valid=True)
    return EventIdentityRecord(canonical, evidence, scope, temporal)


def _materialize_groups(fixture: dict, records: tuple[EventIdentityRecord, ...]):
    expected = fixture["expected"]
    if expected["event_identity_expectation"] == "DIFFERENT_EVENTS":
        partitions = tuple((record,) for record in records)
    else:
        partitions = (records,)

    groups = []
    for index, partition in enumerate(partitions, start=1):
        member_ids = tuple(sorted(record.candidate.candidate_id for record in partition))
        unresolved_claims = []
        claims_by_key: dict[str, list[tuple[str, str]]] = {}
        for record in partition:
            for key, value in record.evidence.identity_facts.non_identity_claims.items():
                claims_by_key.setdefault(key, []).append(
                    (record.candidate.candidate_id, value)
                )
        for key, values in claims_by_key.items():
            if len({value for _, value in values}) > 1:
                unresolved_claims.append(UnresolvedClaim(key, tuple(sorted(values))))
        groups.append(
            EventGroup(
                event_id=f"{fixture['case_id']}-event-{index}",
                member_candidate_ids=member_ids,
                canonical_candidate_id=member_ids[0],
                identity_basis=(),
                unresolved_claims=tuple(unresolved_claims),
            )
        )
    return tuple(groups)


class CategoryGoldenAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((GOLDEN / "manifest.json").read_text(encoding="utf-8"))
        cls.fixtures = {
            entry["case_id"]: json.loads(
                (GOLDEN / entry["file"]).read_text(encoding="utf-8")
            )
            for entry in cls.manifest["cases"]
        }

    def test_all_cases_retain_their_golden_category_state(self):
        reached = 0
        passed = 0
        classified_groups = 0
        for case_id, fixture in self.fixtures.items():
            expected = fixture["expected"]
            with self.subTest(case_id=case_id):
                if expected["category_state"] == CategoryState.NOT_EVALUATED.value:
                    result = CategoryResult.not_evaluated()
                    self.assertEqual(result.category_state.value, expected["category_state"])
                    self.assertIsNone(result.primary_category_id)
                    self.assertIsNone(result.primary_category)
                    self.assertIsNone(result.subtype)
                    self.assertIsNone(result.classification_reason)
                    self.assertIsNone(result.category_resolution_reason)
                    passed += 1
                    continue

                reached += 1
                records = tuple(
                    _materialize_record(candidate)
                    for candidate in fixture["candidates"]
                )
                groups = _materialize_groups(fixture, records)
                outcomes = [
                    Classifier(_GoldenSemanticOracle(expected)).classify(
                        group,
                        tuple(
                            record
                            for record in records
                            if record.candidate.candidate_id in group.member_candidate_ids
                        ),
                    )
                    for group in groups
                ]
                classified_groups += len(outcomes)
                self.assertGreaterEqual(len(outcomes), 1)
                for result in outcomes:
                    self.assertEqual(result.category_state.value, expected["category_state"])
                    self.assertEqual(
                        result.primary_category_id.value
                        if result.primary_category_id
                        else None,
                        expected["primary_category_id"],
                    )
                    self.assertEqual(result.primary_category, expected["primary_category"])
                    self.assertEqual(result.subtype, expected["subtype"])
                    self.assertEqual(
                        result.classification_reason,
                        expected["classification_reason"],
                    )
                    if result.category_state is CategoryState.CATEGORY_UNRESOLVED:
                        self.assertEqual(
                            result.category_resolution_reason.value,
                            expected["category_resolution_reason"],
                        )
                        self.assertEqual(result.provenance["decision_basis"], "constrained_semantic_helper")
                    else:
                        self.assertIsNone(result.category_resolution_reason)
                passed += 1

        self.assertEqual((reached, passed), (52, 85))
        self.assertEqual(classified_groups, 53)

    def test_golden_boundary_cases_reach_the_classifier_contract(self):
        boundary_cases = (
            "G07",
            "G11",
            "G19",
            "G49",
            "G53",
            "G60",
            "G63",
            "G64",
            "G69",
            "G79",
            "G80",
            "G81",
            "G82",
            "G85",
        )
        for case_id in boundary_cases:
            fixture = self.fixtures[case_id]
            expected = fixture["expected"]
            self.assertIn(
                expected["category_state"],
                {
                    CategoryState.CATEGORY_ASSIGNED.value,
                    CategoryState.CATEGORY_UNRESOLVED.value,
                },
                case_id,
            )
            if expected["category_state"] == CategoryState.CATEGORY_ASSIGNED.value:
                self.assertIn(
                    expected["primary_category_id"],
                    {item.value for item in CategoryId},
                    case_id,
                )
            else:
                self.assertIsNone(expected["primary_category_id"], case_id)

        g49 = self.fixtures["G49"]["category_period_invariance"]
        self.assertEqual(
            g49["weekly"]["expected_category_id"],
            g49["annual"]["expected_category_id"],
        )
        self.assertEqual(
            g49["weekly"]["expected_category_id"],
            self.fixtures["G49"]["expected"]["primary_category_id"],
        )


if __name__ == "__main__":
    unittest.main()
