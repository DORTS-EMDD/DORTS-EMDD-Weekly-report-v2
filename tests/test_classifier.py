"""Owner-level contract tests for the V2 Category Classifier."""

from __future__ import annotations

import unittest

from src.weekly_report.classifier import (
    CategoryActionProposal,
    CategoryCitation,
    CategoryProposalViolation,
    CategorySemanticRequest,
    CategorySemanticResponse,
    Classifier,
)
from src.weekly_report.contracts import (
    CanonicalCandidate,
    CategoryId,
    CategoryResolutionReason,
    CategoryState,
    EvidenceResult,
    EvidenceState,
    EventGroup,
    EventIdentityFacts,
    EventIdentityRecord,
    RejectReason,
    ScopeDiagnostic,
    ScopeResult,
    ScopeState,
    TemporalDiagnostic,
    TemporalResult,
)


def _record(
    candidate_id: str,
    body: str,
    *,
    evidence_state: EvidenceState = EvidenceState.READY,
    scope_state: ScopeState = ScopeState.IN_SCOPE,
    date_valid: bool = True,
    identity_facts: EventIdentityFacts | None = None,
) -> EventIdentityRecord:
    candidate = CanonicalCandidate(
        candidate_id=candidate_id,
        title="PRIVATE_TITLE_TOKEN",
        url="https://private.invalid/PRIVATE_URL_TOKEN",
        publisher="PRIVATE_PUBLISHER_TOKEN",
        published_at="PRIVATE_DATE_TOKEN",
        discovery_intent="PRIVATE_QUERY_TOKEN",
        search_snippet="PRIVATE_SNIPPET_TOKEN",
    )
    evidence = EvidenceResult(
        candidate_id=candidate_id,
        state=evidence_state,
        canonical_source_url="https://private.invalid/PRIVATE_CANONICAL_URL_TOKEN",
        source_type="private-source-type",
        substantive_content=body if evidence_state is EvidenceState.READY else "",
        provenance={"domain": "PRIVATE_DOMAIN_TOKEN"},
        reject_reason=(
            RejectReason.CONTENT_UNAVAILABLE
            if evidence_state is EvidenceState.REJECTED
            else None
        ),
        identity_facts=identity_facts,
    )
    scope = ScopeResult(
        candidate_id=candidate_id,
        state=scope_state,
        diagnostic=(
            ScopeDiagnostic.NON_URBAN_RAIL
            if scope_state is ScopeState.OUT_OF_SCOPE
            else ScopeDiagnostic.NONE
        ),
    )
    temporal = TemporalResult(
        candidate_id=candidate_id,
        date_valid=date_valid,
        diagnostic=(
            TemporalDiagnostic.NONE
            if date_valid
            else TemporalDiagnostic.OUT_OF_RANGE
        ),
    )
    return EventIdentityRecord(candidate, evidence, scope, temporal)


def _group(records: tuple[EventIdentityRecord, ...], event_id: str = "event-1") -> EventGroup:
    member_ids = tuple(sorted(record.candidate.candidate_id for record in records))
    return EventGroup(
        event_id=event_id,
        member_candidate_ids=member_ids,
        canonical_candidate_id=member_ids[0],
        identity_basis=(),
        unresolved_claims=(),
    )


def _action(
    action_id: str,
    action_kind: str,
    *,
    subject_kind: str = "TECHNOLOGY_METHOD_MATERIAL",
    lifecycle_relation: str = "TECHNOLOGY_ITSELF",
    adoption_status: str = "COMPLETED",
    source_ref: str = "M1",
) -> dict[str, object]:
    return {
        "action_id": action_id,
        "action_kind": action_kind,
        "subject_kind": subject_kind,
        "lifecycle_relation": lifecycle_relation,
        "adoption_status": adoption_status,
        "citations": [{"source_ref": source_ref, "sentence_ids": ["S1"]}],
    }


def _proposal(
    actions: list[dict[str, object]],
    *,
    principal_action_id: str | None,
    subtype: str | None = "pilot",
    examined_citations: list[dict[str, object]] | None = None,
    relationships: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "actions": actions,
        "principal_action_id": principal_action_id,
        "subtype": subtype,
        "examined_citations": examined_citations or [{"source_ref": "M1", "sentence_ids": ["S1"]}],
        "relationships": relationships or [],
    }


def _common_decision(*action_ids: str) -> dict[str, object]:
    return {
        "relationship_type": "COMMON_DECISION_MEMBERSHIP",
        "member_action_ids": list(action_ids),
        "principal_action_id": None,
        "dependent_action_id": None,
        "dependence_kind": None,
        "citations": [{"source_ref": "M1", "sentence_ids": ["S1"]}],
    }


def _same_occurrence_dependence(
    principal_action_id: str,
    dependent_action_id: str,
    dependence_kind: str = "CONSEQUENCE",
) -> dict[str, object]:
    return {
        "relationship_type": "SAME_OCCURRENCE_DEPENDENCE",
        "member_action_ids": [],
        "principal_action_id": principal_action_id,
        "dependent_action_id": dependent_action_id,
        "dependence_kind": dependence_kind,
        "citations": [{"source_ref": "M1", "sentence_ids": ["S1"]}],
    }


class _Helper:
    def __init__(self, response=None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.requests: list[CategorySemanticRequest] = []

    def __call__(self, request: CategorySemanticRequest):
        self.requests.append(request)
        if self.error:
            raise self.error
        return self.response(request) if callable(self.response) else self.response


class ClassifierTests(unittest.TestCase):
    def test_classifier_owns_technology_mapping_and_provenance(self):
        record = _record("C1", "The operator completed deployment of a radio system.")
        result = Classifier(_Helper(_proposal([_action("A1", "DEPLOYMENT")], principal_action_id="A1"))).classify(
            _group((record,)), (record,)
        )
        self.assertEqual(result.category_state, CategoryState.CATEGORY_ASSIGNED)
        self.assertEqual(result.primary_category_id, CategoryId.TECHNICAL_DEVELOPMENT)
        self.assertEqual(result.provenance["decision_basis"], "classifier_authoritative_domain_mechanism")
        self.assertEqual(result.provenance["helper_proposal_role"], "advisory_action_lifecycle_relationships")
        self.assertEqual(result.provenance["principal_action_id"], "A1")

    def test_technology_deployment_remains_principal_over_later_acceptance(self):
        record = _record("C1", "Deployment was completed. Acceptance testing followed.")
        proposal = _proposal(
            [
                _action("A1", "DEPLOYMENT"),
                _action("A2", "APPLIED_TECHNICAL_TEST", lifecycle_relation="PROJECT_DELIVERY"),
            ],
            principal_action_id="A1",
        )
        result = Classifier(_Helper(proposal)).classify(_group((record,)), (record,))
        self.assertEqual(result.primary_category_id, CategoryId.TECHNICAL_DEVELOPMENT)

    def test_preopening_project_step_is_unresolved(self):
        record = _record("C1", "Pre-opening signalling tests were completed.")
        proposal = _proposal(
            [_action("A1", "PROJECT_STEP", lifecycle_relation="PRE_OPENING")],
            principal_action_id="A1",
            subtype=None,
        )
        result = Classifier(_Helper(proposal)).classify(_group((record,)), (record,))
        self.assertEqual(result.category_state, CategoryState.CATEGORY_UNRESOLVED)
        self.assertEqual(result.category_resolution_reason, CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION)

    def test_operating_service_change_is_not_reclassified_as_technology(self):
        record = _record("C1", "The operator implemented a new timetable.")
        proposal = _proposal(
            [_action(
                "A1",
                "TIMETABLE_CHANGE",
                subject_kind="PASSENGER_SERVICE",
                lifecycle_relation="OPERATING_SERVICE",
                adoption_status="IMPLEMENTED",
            )],
            principal_action_id="A1",
        )
        result = Classifier(_Helper(proposal)).classify(_group((record,)), (record,))
        self.assertEqual(result.primary_category_id, CategoryId.OPERATIONAL_CHANGE)

    def test_future_procurement_is_not_completed_procurement(self):
        record = _record("C1", "The operator plans to tender a new system.")
        proposal = _proposal(
            [_action(
                "A1",
                "PROCUREMENT_TENDER",
                subject_kind="PROCUREMENT_ACTION",
                lifecycle_relation="PROCUREMENT_LIFECYCLE",
                adoption_status="PLANNED",
            )],
            principal_action_id="A1",
        )
        result = Classifier(_Helper(proposal)).classify(_group((record,)), (record,))
        self.assertEqual(result.category_state, CategoryState.CATEGORY_UNRESOLVED)
        self.assertEqual(result.category_resolution_reason, CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION)

    def test_recommendation_without_adoption_has_domain_reason(self):
        record = _record("C1", "The report recommends adopting a new fare policy.")
        proposal = _proposal(
            [_action(
                "A1",
                "RECOMMENDATION",
                subject_kind="RECOMMENDATION",
                lifecycle_relation="NONE",
                adoption_status="RECOMMENDED",
            )],
            principal_action_id="A1",
            subtype=None,
        )
        result = Classifier(_Helper(proposal)).classify(_group((record,)), (record,))
        self.assertEqual(result.category_resolution_reason, CategoryResolutionReason.RECOMMENDATION_WITHOUT_ADOPTED_ACTION)

    def test_multiple_equal_actions_require_no_unique_principal(self):
        record = _record("C1", "Deployment and a timetable change were both reported.")
        proposal = _proposal(
            [
                _action("A1", "DEPLOYMENT"),
                _action(
                    "A2",
                    "TIMETABLE_CHANGE",
                    subject_kind="PASSENGER_SERVICE",
                    lifecycle_relation="OPERATING_SERVICE",
                    adoption_status="IMPLEMENTED",
                ),
            ],
            principal_action_id=None,
        )
        result = Classifier(_Helper(proposal)).classify(_group((record,)), (record,))
        self.assertEqual(result.category_resolution_reason, CategoryResolutionReason.NO_UNIQUE_PRINCIPAL_ACTION)

    def test_same_category_does_not_prove_coherence(self):
        record = _record("C1", "Two independent fare changes were adopted.")
        proposal = _proposal(
            [
                _action(
                    "A1",
                    "FARE_CHANGE",
                    subject_kind="PASSENGER_SERVICE",
                    lifecycle_relation="OPERATING_SERVICE",
                    adoption_status="ADOPTED",
                ),
                _action(
                    "A2",
                    "FARE_CHANGE",
                    subject_kind="PASSENGER_SERVICE",
                    lifecycle_relation="OPERATING_SERVICE",
                    adoption_status="ADOPTED",
                ),
            ],
            principal_action_id=None,
        )
        result = Classifier(_Helper(proposal)).classify(_group((record,)), (record,))
        self.assertEqual(result.category_state, CategoryState.CATEGORY_UNRESOLVED)
        self.assertEqual(result.category_resolution_reason, CategoryResolutionReason.NO_UNIQUE_PRINCIPAL_ACTION)

    def test_common_decision_membership_allows_same_category_components(self):
        record = _record("C1", "One authority approval changed fares and operating hours.")
        proposal = _proposal(
            [
                _action(
                    "A1",
                    "FARE_CHANGE",
                    subject_kind="PASSENGER_SERVICE",
                    lifecycle_relation="OPERATING_SERVICE",
                    adoption_status="ADOPTED",
                ),
                _action(
                    "A2",
                    "TIMETABLE_CHANGE",
                    subject_kind="PASSENGER_SERVICE",
                    lifecycle_relation="OPERATING_SERVICE",
                    adoption_status="ADOPTED",
                ),
            ],
            principal_action_id=None,
            relationships=[_common_decision("A1", "A2")],
        )
        result = Classifier(_Helper(proposal)).classify(_group((record,)), (record,))
        self.assertEqual(result.category_state, CategoryState.CATEGORY_ASSIGNED)
        self.assertEqual(result.primary_category_id, CategoryId.OPERATIONAL_CHANGE)

    def test_incident_consequence_requires_explicit_same_occurrence_relationship(self):
        record = _record("C1", "A fault suspended service, and a separate timetable change was implemented.")
        actions = [
            _action(
                "A1",
                "INCIDENT",
                subject_kind="INCIDENT_SUBJECT",
                lifecycle_relation="INCIDENT_OCCURRENCE",
                adoption_status="COMPLETED",
            ),
            _action(
                "A2",
                "SERVICE_CHANGE",
                subject_kind="PASSENGER_SERVICE",
                lifecycle_relation="OPERATING_SERVICE",
                adoption_status="IMPLEMENTED",
            ),
        ]
        without_relation = Classifier(_Helper(_proposal(actions, principal_action_id=None))).classify(
            _group((record,)), (record,)
        )
        self.assertEqual(without_relation.category_state, CategoryState.CATEGORY_UNRESOLVED)
        self.assertEqual(
            without_relation.category_resolution_reason,
            CategoryResolutionReason.NO_UNIQUE_PRINCIPAL_ACTION,
        )
        with_relation = Classifier(
            _Helper(
                _proposal(
                    actions,
                    principal_action_id=None,
                    relationships=[_same_occurrence_dependence("A1", "A2")],
                )
            )
        ).classify(_group((record,)), (record,))
        self.assertEqual(with_relation.category_state, CategoryState.CATEGORY_ASSIGNED)
        self.assertEqual(with_relation.primary_category_id, CategoryId.INCIDENT)

    def test_locked_original_failures_and_adjacent_controls(self):
        cases = {
            "G08": (
                [
                    _action(
                        "A1",
                        "FARE_CHANGE",
                        subject_kind="PASSENGER_SERVICE",
                        lifecycle_relation="OPERATING_SERVICE",
                        adoption_status="ADOPTED",
                    ),
                    _action(
                        "A2",
                        "TIMETABLE_CHANGE",
                        subject_kind="PASSENGER_SERVICE",
                        lifecycle_relation="OPERATING_SERVICE",
                        adoption_status="ADOPTED",
                    ),
                ],
                None,
                [_common_decision("A1", "A2")],
                CategoryId.OPERATIONAL_CHANGE,
            ),
            "G11": (
                [
                    _action(
                        "A1",
                        "PROCUREMENT_TENDER",
                        subject_kind="PROCUREMENT_ACTION",
                        lifecycle_relation="PROCUREMENT_LIFECYCLE",
                    ),
                    _action("A2", "PILOT", adoption_status="PLANNED"),
                ],
                None,
                [],
                CategoryId.PROCUREMENT,
            ),
            "G12": (
                [
                    _action(
                        "A1",
                        "INCIDENT",
                        subject_kind="INCIDENT_SUBJECT",
                        lifecycle_relation="INCIDENT_OCCURRENCE",
                    ),
                    _action(
                        "A2",
                        "SERVICE_CHANGE",
                        subject_kind="PASSENGER_SERVICE",
                        lifecycle_relation="OPERATING_SERVICE",
                        adoption_status="IMPLEMENTED",
                    ),
                ],
                None,
                [_same_occurrence_dependence("A1", "A2", "RECOVERY")],
                CategoryId.INCIDENT,
            ),
            "G19": (
                [
                    _action(
                        "A1",
                        "PROCUREMENT_AWARD",
                        subject_kind="PROCUREMENT_ACTION",
                        lifecycle_relation="PROCUREMENT_LIFECYCLE",
                    ),
                    _action("A2", "PILOT", adoption_status="PLANNED"),
                ],
                "A2",
                [],
                CategoryId.PROCUREMENT,
            ),
            "G55": (
                [
                    _action(
                        "A1",
                        "OPERATING_PRACTICE_CHANGE",
                        subject_kind="OTHER",
                        lifecycle_relation="OPERATING_SERVICE",
                        adoption_status="IMPLEMENTED",
                    ),
                ],
                "A1",
                [],
                CategoryId.OPERATIONAL_CHANGE,
            ),
            "G80": (
                [
                    _action(
                        "A1",
                        "OPERATING_PRACTICE_CHANGE",
                        subject_kind="OTHER",
                        lifecycle_relation="OPERATING_SERVICE",
                        adoption_status="IMPLEMENTED",
                    ),
                ],
                "A1",
                [],
                CategoryId.OPERATIONAL_CHANGE,
            ),
            "G03": ([_action("A1", "DEPLOYMENT")], "A1", [], CategoryId.TECHNICAL_DEVELOPMENT),
            "G64": ([_action("A1", "DEPLOYMENT")], "A1", [], CategoryId.TECHNICAL_DEVELOPMENT),
            "G78": ([_action("A1", "DEPLOYMENT")], "A1", [], CategoryId.TECHNICAL_DEVELOPMENT),
            "G84": ([_action("A1", "DEPLOYMENT")], "A1", [], CategoryId.TECHNICAL_DEVELOPMENT),
            "G101": ([_action("A1", "DEPLOYMENT")], "A1", [], CategoryId.TECHNICAL_DEVELOPMENT),
            "G66": (
                [
                    _action(
                        "A1",
                        "TIMETABLE_CHANGE",
                        subject_kind="PASSENGER_SERVICE",
                        lifecycle_relation="OPERATING_SERVICE",
                        adoption_status="IMPLEMENTED",
                    ),
                ],
                "A1",
                [],
                CategoryId.OPERATIONAL_CHANGE,
            ),
        }
        for case_id, (actions, principal, relationships, expected_category) in cases.items():
            with self.subTest(case_id=case_id):
                record = _record("C1", f"Offline contract fixture {case_id}.")
                result = Classifier(
                    _Helper(
                        _proposal(
                            actions,
                            principal_action_id=principal,
                            relationships=relationships,
                        )
                    )
                ).classify(_group((record,), event_id=case_id), (record,))
                self.assertEqual(result.category_state, CategoryState.CATEGORY_ASSIGNED)
                self.assertEqual(result.primary_category_id, expected_category)

        for case_id in ("G100", "G93"):
            with self.subTest(case_id=case_id):
                record = _record("C1", f"Offline project-step control {case_id}.")
                result = Classifier(
                    _Helper(
                        _proposal(
                            [_action("A1", "PROJECT_STEP", subject_kind="PROJECT", lifecycle_relation="PRE_OPENING")],
                            principal_action_id="A1",
                            subtype=None,
                        )
                    )
                ).classify(_group((record,), event_id=case_id), (record,))
                self.assertEqual(result.category_state, CategoryState.CATEGORY_UNRESOLVED)
                self.assertEqual(result.category_resolution_reason, CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION)

    def test_relationship_citations_are_required_and_invalid_relationship_fails_closed(self):
        record = _record("C1", "Two actions share no valid relationship citation.")
        invalid = _common_decision("A1", "A2")
        invalid["citations"] = [{"source_ref": "M1", "sentence_ids": ["S9"]}]
        with self.assertRaises(CategoryProposalViolation):
            Classifier(
                _Helper(
                    _proposal(
                        [_action("A1", "DEPLOYMENT"), _action("A2", "DEPLOYMENT")],
                        principal_action_id=None,
                        relationships=[invalid],
                    )
                )
            ).classify(_group((record,)), (record,))

    def test_legacy_final_category_response_is_rejected(self):
        record = _record("C1", "The operator completed a deployment.")
        legacy = {
            "category_state": CategoryState.CATEGORY_ASSIGNED.value,
            "primary_category_id": CategoryId.TECHNICAL_DEVELOPMENT.value,
            "subtype": None,
            "category_resolution_reason": None,
            "citations": [{"source_ref": "M1", "sentence_ids": ["S1"]}],
        }
        with self.assertRaises(CategoryProposalViolation):
            Classifier(_Helper(legacy)).classify(_group((record,)), (record,))

    def test_invalid_action_citation_fails_closed(self):
        record = _record("C1", "The operator completed a deployment.")
        proposal = _proposal(
            [{**_action("A1", "DEPLOYMENT"), "citations": [{"source_ref": "M1", "sentence_ids": ["S9"]}]}],
            principal_action_id="A1",
        )
        with self.assertRaises(CategoryProposalViolation):
            Classifier(_Helper(proposal)).classify(_group((record,)), (record,))

    def test_principal_action_must_name_an_observation(self):
        record = _record("C1", "The operator completed a deployment.")
        with self.assertRaises(CategoryProposalViolation):
            Classifier(_Helper(_proposal([_action("A1", "DEPLOYMENT")], principal_action_id="A9"))).classify(
                _group((record,)), (record,)
            )

    def test_typed_advisory_response_is_supported(self):
        record = _record("C1", "The operator completed a deployment.")
        typed = CategorySemanticResponse(
            actions=(
                CategoryActionProposal(
                    "A1",
                    "DEPLOYMENT",
                    "TECHNOLOGY_METHOD_MATERIAL",
                    "TECHNOLOGY_ITSELF",
                    "COMPLETED",
                    (CategoryCitation("M1", ("S1",)),),
                ),
            ),
            principal_action_id="A1",
            subtype=None,
            examined_citations=(CategoryCitation("M1", ("S1",)),),
        )
        result = Classifier(_Helper(typed)).classify(_group((record,)), (record,))
        self.assertEqual(result.primary_category_id, CategoryId.TECHNICAL_DEVELOPMENT)

    def test_upstream_boundary_prevents_helper_invocation(self):
        cases = (
            _record("C1", "", evidence_state=EvidenceState.REJECTED),
            _record("C1", "An urban-rail event.", scope_state=ScopeState.OUT_OF_SCOPE),
            _record("C1", "An urban-rail event.", date_valid=False),
        )
        helper = _Helper(_proposal([_action("A1", "DEPLOYMENT")], principal_action_id="A1"))
        for record in cases:
            with self.subTest(state=record.evidence.state):
                with self.assertRaises(ValueError):
                    Classifier(helper).classify(_group((record,)), (record,))
        self.assertEqual(helper.requests, [])

    def test_records_must_match_event_group_exactly(self):
        first = _record("C1", "A metro pilot began.")
        second = _record("C2", "A metro pilot began.")
        helper = _Helper(_proposal([_action("A1", "PILOT")], principal_action_id="A1"))
        with self.assertRaises(ValueError):
            Classifier(helper).classify(_group((first, second)), (first,))
        with self.assertRaises(ValueError):
            Classifier(helper).classify(_group((first,)), (first, first))
        self.assertEqual(helper.requests, [])

    def test_missing_helper_is_explicit_technical_gap(self):
        record = _record("C1", "A metro pilot began.")
        result = Classifier().classify(_group((record,)), (record,))
        self.assertEqual(result.category_resolution_reason, CategoryResolutionReason.SEMANTIC_HELPER_UNAVAILABLE)


if __name__ == "__main__":
    unittest.main()
