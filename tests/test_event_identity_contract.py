"""RED/contract regressions for the single V2 Event Identity owner."""

from __future__ import annotations

import itertools
import unittest

from src.weekly_report.contracts import (
    CanonicalCandidate,
    EvidenceResult,
    EvidenceState,
    EventIdentityFacts,
    EventIdentityRecord,
    ScopeResult,
    ScopeState,
    TemporalDiagnostic,
    TemporalResult,
)
from src.weekly_report.event_identity import (
    EventIdentity,
    EventIdentityRelation,
)


class _SemanticAdvisor:
    def __init__(self, relation=EventIdentityRelation.SAME_EVENT, *, invalid=False):
        self.relation = relation
        self.invalid = invalid
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        if self.invalid:
            return {"relation": "SAME_EVENT"}
        spans = tuple(
            {
                "candidate_id": candidate_id,
                "role": role,
                "start": 0,
                "end": len(body),
            }
            for candidate_id, body in (
                (request.left_candidate_id, request.left_body),
                (request.right_candidate_id, request.right_body),
            )
            for role in ("occurrence", "subject", "lifecycle")
        )
        return {
            "relation": self.relation.value,
            "support_spans": spans,
            "contradictions": [] if self.relation is EventIdentityRelation.SAME_EVENT else ["action"],
            "missing_support": [],
        }


def _record(
    candidate_id: str,
    *,
    facts: EventIdentityFacts | None = None,
    body: str = "The source documents the same metro occurrence.",
    url: str | None = None,
    publisher: str = "Fixture Publisher",
    source_type: str = "trade_press",
    first_hand: bool = False,
    published_at: str = "2026-09-15T10:00:00Z",
    evidence_state: EvidenceState = EvidenceState.READY,
    in_scope: bool = True,
    date_valid: bool = True,
) -> EventIdentityRecord:
    candidate = CanonicalCandidate(
        candidate_id=candidate_id,
        title="Metro event report",
        url=url or f"https://fixtures.invalid/{candidate_id}",
        publisher=publisher,
        published_at=published_at,
        source_type=source_type,
    )
    evidence = EvidenceResult(
        candidate_id=candidate_id,
        state=evidence_state,
        canonical_source_url=candidate.url,
        source_type=source_type,
        substantive_content=body if evidence_state is EvidenceState.READY else "",
        provenance={"first_hand_source": first_hand},
        reject_reason=None if evidence_state is EvidenceState.READY else "TITLE_ONLY",
        identity_facts=facts,
    )
    scope = ScopeResult(candidate_id, ScopeState.IN_SCOPE if in_scope else ScopeState.OUT_OF_SCOPE)
    temporal = TemporalResult(
        candidate_id,
        date_valid,
        diagnostic=TemporalDiagnostic.NONE if date_valid else TemporalDiagnostic.DATE_MISSING,
    )
    return EventIdentityRecord(candidate, evidence, scope, temporal)


def _facts(**values) -> EventIdentityFacts:
    return EventIdentityFacts(
        event_key=values.get("event_key", "incident-line-4-2026-09-15"),
        action=values.get("action", "commissioning"),
        lifecycle_step=values.get("lifecycle_step", "service_entry"),
        subject=values.get("subject", "line-4-signalling"),
        asset=values.get("asset", "line-4"),
        project=values.get("project", "metro-modernisation"),
        package=values.get("package", "signalling-package"),
        location=values.get("location", "central-city"),
        occurrence_context=values.get("occurrence_context", "approved commissioning"),
        occurrence_date=values.get("occurrence_date", "2026-09-15"),
        non_identity_claims=values.get("non_identity_claims", {}),
        evidence_references=("body:0-10",),
    )


class EventIdentityContractTests(unittest.TestCase):
    def test_generic_incident_asset_and_location_overlap_cannot_prove_same_event(self):
        facts = lambda: EventIdentityFacts(
            action="incident",
            lifecycle_step="occurrence",
            asset="line-4",
            location="central",
        )
        result = EventIdentity().evaluate([
            _record("A", facts=facts()),
            _record("B", facts=facts()),
        ])
        self.assertEqual([group.member_candidate_ids for group in result.groups], [("A",), ("B",)])
        self.assertTrue(any(item.reason == "INSUFFICIENT_IDENTITY" for item in result.diagnostics))

    def test_action_surface_difference_defers_to_semantic_advisor(self):
        records = [
            _record("EN", facts=_facts(event_key="", action="service_entry")),
            _record("JA", facts=_facts(event_key="", action="entered_service")),
        ]
        advisor = _SemanticAdvisor()
        groups = EventIdentity(advisor).group(records)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(advisor.requests), 1)

    def test_occurrence_date_surface_difference_defers_to_semantic_advisor(self):
        records = [
            _record("ISO", facts=_facts(event_key="", occurrence_date="2026-09-15")),
            _record("TEXT", facts=_facts(event_key="", occurrence_date="15 September 2026")),
        ]
        advisor = _SemanticAdvisor()
        groups = EventIdentity(advisor).group(records)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(advisor.requests), 1)

    def test_event_key_only_cannot_establish_same_event(self):
        records = [
            _record("X", facts=EventIdentityFacts(event_key="same")),
            _record("Y", facts=EventIdentityFacts(event_key="same")),
        ]
        result = EventIdentity().evaluate(records)
        self.assertEqual([group.member_candidate_ids for group in result.groups], [("X",), ("Y",)])
        self.assertTrue(any(item.reason == "INSUFFICIENT_IDENTITY" for item in result.diagnostics))

    def test_multilingual_structured_surface_difference_defers_to_advisor(self):
        records = [
            _record(
                "EN",
                facts=_facts(event_key="", asset="Line 4"),
                body="Line 4 signalling entered service after approval.",
            ),
            _record(
                "JA",
                facts=_facts(event_key="", asset="4号線"),
                body="承認後、4号線の信号システムが営業開始した。",
            ),
        ]
        advisor = _SemanticAdvisor()
        groups = EventIdentity(advisor).group(records)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(advisor.requests), 1)

    def test_structured_case_and_whitespace_variation_is_not_distinct(self):
        records = [
            _record("A", facts=_facts(event_key="", asset="Line 4", location="Central City")),
            _record("B", facts=_facts(event_key="", asset=" line 4 ", location=" central city ")),
        ]
        self.assertEqual(len(EventIdentity().group(records)), 1)

    def test_exact_duplicate_source_forms_one_group_with_two_members(self):
        records = [
            _record("C2", facts=None, body="Exact authoritative source body.", url="https://fixtures.invalid/exact"),
            _record("C1", facts=None, body="Exact authoritative source body.", url="https://fixtures.invalid/exact"),
        ]
        groups = EventIdentity().group(records)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].member_candidate_ids, ("C1", "C2"))

    def test_official_and_secondary_same_event_group_after_membership(self):
        records = [
            _record("SECONDARY", facts=_facts(), publisher="Trade Press"),
            _record("OFFICIAL", facts=_facts(), publisher="Operator", first_hand=True, source_type="official_notice"),
        ]
        groups = EventIdentity().group(records)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].canonical_candidate_id, "OFFICIAL")

    def test_different_procurement_milestones_do_not_merge(self):
        records = [
            _record("TENDER", facts=_facts(action="tender", lifecycle_step="tender_issued")),
            _record("AWARD", facts=_facts(action="award", lifecycle_step="contract_awarded")),
        ]
        self.assertEqual(len(EventIdentity().group(records)), 2)

    def test_delivery_testing_and_service_are_three_groups(self):
        records = [
            _record("DELIVERY", facts=_facts(action="delivery", lifecycle_step="delivered")),
            _record("TESTING", facts=_facts(action="testing", lifecycle_step="testing_begins")),
            _record("SERVICE", facts=_facts(action="service_entry", lifecycle_step="service_entry")),
        ]
        self.assertEqual(len(EventIdentity().group(records)), 3)

    def test_incident_and_investigation_release_are_distinct(self):
        records = [
            _record("INCIDENT", facts=_facts(action="incident", lifecycle_step="occurrence")),
            _record("INVESTIGATION", facts=_facts(action="investigation_release", lifecycle_step="report_released")),
        ]
        self.assertEqual(len(EventIdentity().group(records)), 2)

    def test_repeated_similar_incidents_on_different_dates_are_distinct(self):
        records = [
            _record("I1", facts=_facts(event_key="incident-1", occurrence_date="2026-09-10")),
            _record("I2", facts=_facts(event_key="incident-2", occurrence_date="2026-09-15")),
        ]
        self.assertEqual(len(EventIdentity().group(records)), 2)

    def test_insufficient_identity_does_not_merge_and_preserves_diagnostic(self):
        records = [
            _record("A", facts=EventIdentityFacts(action="incident", subject="line-4")),
            _record("B", facts=EventIdentityFacts(action="incident", subject="line-4")),
        ]
        result = EventIdentity().evaluate(records)
        self.assertEqual(len(result.groups), 2)
        self.assertTrue(any(item.reason == "INSUFFICIENT_IDENTITY" for item in result.diagnostics))

    def test_multilingual_same_event_uses_advisor_without_title_equality(self):
        records = [
            _record("EN", facts=None, body="Line 4 signalling entered service after approval."),
            _record("JA", facts=None, body="承認後、4号線の信号システムが営業開始した。"),
        ]
        advisor = _SemanticAdvisor()
        groups = EventIdentity(advisor).group(records)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(advisor.requests), 1)
        self.assertFalse(hasattr(advisor.requests[0], "search_snippet"))
        self.assertFalse(hasattr(advisor.requests[0], "published_at"))

    def test_publication_date_difference_does_not_split_same_event(self):
        records = [
            _record("N", facts=_facts(), body="The event occurred on September 15."),
            _record("N1", facts=_facts(), body="The event occurred on September 15, reported later."),
        ]
        records[1] = _record("N1", facts=_facts(), body="The event occurred on September 15, reported later.")
        groups = EventIdentity().group(records)
        self.assertEqual(len(groups), 1)

    def test_transitivity_trap_does_not_union_weak_bridge(self):
        advisor = _PairAdvisor({("A", "B"): True, ("B", "C"): True, ("A", "C"): False})
        result = EventIdentity(advisor).evaluate([
            _record("A", facts=None),
            _record("B", facts=None),
            _record("C", facts=None),
        ])
        self.assertEqual(sorted(len(group.member_candidate_ids) for group in result.groups), [1, 2])
        self.assertNotIn(("A", "B", "C"), [group.member_candidate_ids for group in result.groups])

    def test_weak_bridge_permutations_preserve_every_member_and_membership(self):
        urls = {
            "A": "https://fixtures.invalid/a",
            "C": "https://fixtures.invalid/c",
            "B": "https://fixtures.invalid/z",
        }
        advisor_pairs = {("A", "B"): True, ("B", "C"): True, ("A", "C"): False}
        expected = None
        for order in itertools.permutations(("A", "B", "C")):
            advisor = _PairAdvisor(advisor_pairs)
            records = [_record(candidate_id, facts=None, url=urls[candidate_id]) for candidate_id in order]
            result = EventIdentity(advisor).evaluate(records)
            shape = [(group.member_candidate_ids, group.event_id) for group in result.groups]
            self.assertEqual(sorted(sum((list(group.member_candidate_ids) for group in result.groups), [])), ["A", "B", "C"])
            self.assertEqual(sorted(len(group.member_candidate_ids) for group in result.groups), [1, 2])
            if expected is None:
                expected = shape
            self.assertEqual(shape, expected)

    def test_input_permutations_have_same_groups_canonical_and_event_ids(self):
        records = [
            _record("SECONDARY", facts=_facts()),
            _record("OFFICIAL", facts=_facts(), first_hand=True),
            _record("SINGLE", facts=_facts(event_key="single", subject="asset-s")),
        ]
        expected = EventIdentity().group(records)
        expected_shape = [(g.member_candidate_ids, g.canonical_candidate_id, g.event_id) for g in expected]
        for permutation in itertools.permutations(records):
            actual = EventIdentity().group(permutation)
            self.assertEqual(
                [(g.member_candidate_ids, g.canonical_candidate_id, g.event_id) for g in actual],
                expected_shape,
            )

    def test_singleton_is_a_group(self):
        groups = EventIdentity().group([_record("ONLY", facts=_facts(event_key="only"))])
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].member_candidate_ids, ("ONLY",))

    def test_member_ids_follow_candidate_id_order_not_url_order(self):
        records = [
            _record("C1", facts=_facts(event_key="",), url="https://fixtures.invalid/z"),
            _record("C2", facts=_facts(event_key="",), url="https://fixtures.invalid/a"),
        ]
        groups = EventIdentity().group(records)
        self.assertEqual(groups[0].member_candidate_ids, ("C1", "C2"))

    def test_invalid_semantic_response_does_not_merge(self):
        records = [
            _record("A", facts=None, body="A body"),
            _record("B", facts=None, body="B body"),
        ]
        advisor = _SemanticAdvisor(invalid=True)
        result = EventIdentity(advisor).evaluate(records)
        self.assertEqual(len(result.groups), 2)
        self.assertTrue(any(item.reason == "SEMANTIC_ADVISOR_INVALID" for item in result.diagnostics))
        self.assertEqual(len(advisor.requests), 1)

    def test_ungrounded_distinct_semantic_response_is_rejected(self):
        def bare_distinct(_request):
            return {
                "relation": "DISTINCT_EVENT",
                "support_spans": [],
                "contradictions": [],
                "missing_support": [],
            }

        result = EventIdentity(bare_distinct).evaluate([
            _record("A", facts=None, body="A body"),
            _record("B", facts=None, body="B body"),
        ])
        self.assertEqual(len(result.groups), 2)
        self.assertTrue(any(item.reason == "SEMANTIC_ADVISOR_INVALID" for item in result.diagnostics))

    def test_conflicting_non_identity_claim_remains_unresolved(self):
        records = [
            _record("A", facts=_facts(non_identity_claims={"duration": "42 minutes"})),
            _record("B", facts=_facts(non_identity_claims={"duration": "47 minutes"})),
        ]
        groups = EventIdentity().group(records)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].unresolved_claims[0].claim_key, "duration")

    def test_ineligible_upstream_record_is_not_grouped(self):
        result = EventIdentity().evaluate([
            _record("READY", facts=_facts()),
            _record("REJECTED", facts=_facts(), evidence_state=EvidenceState.REJECTED),
            _record("OUT", facts=_facts(), in_scope=False),
            _record("DATE", facts=_facts(), date_valid=False),
        ])
        self.assertEqual([g.member_candidate_ids for g in result.groups], [("READY",)])
        self.assertEqual(sum(item.reason == "UPSTREAM_NOT_ELIGIBLE" for item in result.diagnostics), 3)


class _PairAdvisor(_SemanticAdvisor):
    def __init__(self, pairs):
        super().__init__()
        self.pairs = pairs

    def __call__(self, request):
        key = (request.left_candidate_id, request.right_candidate_id)
        same = self.pairs.get(key, self.pairs.get((key[1], key[0]), False))
        self.relation = EventIdentityRelation.SAME_EVENT if same else EventIdentityRelation.UNCERTAIN
        return super().__call__(request)


if __name__ == "__main__":
    unittest.main()
