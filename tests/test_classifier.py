"""Owner-level contract tests for the V2 Category Classifier."""

from __future__ import annotations

import json
import unittest

from src.weekly_report.classifier import (
    CategoryCitation,
    CategorySemanticRequest,
    CategorySemanticResponse,
    CategorySourceEvidence,
    Classifier,
)
from src.weekly_report.contracts import (
    CanonicalCandidate,
    CategoryId,
    CategoryResolutionReason,
    CategoryResult,
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
    SourceDateKind,
    TemporalDiagnostic,
    TemporalResult,
    UnresolvedClaim,
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
        url="https://private.invalid/PRIVATE_URL_TOKEN?category=procurement",
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
        provenance={"domain": "PRIVATE_DOMAIN_TOKEN", "fetch_rank": 91},
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


def _group(
    records: tuple[EventIdentityRecord, ...],
    *,
    event_id: str = "event-1",
    unresolved_claims: tuple[UnresolvedClaim, ...] = (),
) -> EventGroup:
    member_ids = tuple(sorted(record.candidate.candidate_id for record in records))
    return EventGroup(
        event_id=event_id,
        member_candidate_ids=member_ids,
        canonical_candidate_id=member_ids[0],
        identity_basis=(),
        unresolved_claims=unresolved_claims,
    )


def _span(source, start: int = 0, end: int | None = None) -> dict[str, object]:
    content = source.substantive_content
    return {
        "candidate_id": source.candidate_id,
        "quote": content[start:len(content) if end is None else end],
    }


def _source_for_test(candidate_id: str, body: str) -> CategorySourceEvidence:
    return CategorySourceEvidence(candidate_id, body, {})


def _assigned_response(request: CategorySemanticRequest, category_id, subtype="pilot"):
    return {
        "category_state": CategoryState.CATEGORY_ASSIGNED.value,
        "primary_category_id": str(category_id),
        "subtype": subtype,
        "category_resolution_reason": None,
        "citations": [_span(request.sources[0])],
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
    def test_all_five_canonical_categories_are_constructed_by_the_owner(self):
        record = _record("C1", "The operator began a technical pilot on the metro line.")
        group = _group((record,))
        for category_id in CategoryId:
            helper = _Helper(lambda request, cid=category_id: _assigned_response(request, cid))
            result = Classifier(helper).classify(group, (record,))
            self.assertEqual(result.category_state, CategoryState.CATEGORY_ASSIGNED)
            self.assertEqual(result.primary_category_id, category_id)
            self.assertEqual(result.primary_category, category_id.display_label)
            self.assertEqual(result.classification_reason, f"PRINCIPAL_ACTION_{category_id.value}")
            self.assertEqual(result.subtype, "pilot")
            self.assertIsNone(result.category_resolution_reason)

    def test_assigned_subtype_is_optional_and_pattern_applies_when_present(self):
        record = _record("C1", "The operator formally awarded a contract.")
        group = _group((record,))

        for subtype in (None, "award"):
            with self.subTest(subtype=subtype):
                result = Classifier(
                    _Helper(
                        lambda request, subtype=subtype: _assigned_response(
                            request, CategoryId.PROCUREMENT, subtype
                        )
                    )
                ).classify(group, (record,))
                self.assertEqual(result.category_state, CategoryState.CATEGORY_ASSIGNED)
                self.assertEqual(result.primary_category_id, CategoryId.PROCUREMENT)
                self.assertEqual(result.subtype, subtype)

        accepted_without_subtype = CategoryResult(
            category_state=CategoryState.CATEGORY_ASSIGNED,
            event_id="event-1",
            primary_category_id=CategoryId.PROCUREMENT,
            primary_category=CategoryId.PROCUREMENT.display_label,
            subtype=None,
            classification_reason="PRINCIPAL_ACTION_PROCUREMENT",
        )
        self.assertIsNone(accepted_without_subtype.subtype)

        with self.assertRaises(ValueError):
            CategoryResult(
                category_state=CategoryState.CATEGORY_ASSIGNED,
                event_id="event-1",
                primary_category_id=CategoryId.PROCUREMENT,
                primary_category=CategoryId.PROCUREMENT.display_label,
                subtype="Invalid-Subtype",
                classification_reason="PRINCIPAL_ACTION_PROCUREMENT",
            )

    def test_invalid_non_null_assigned_subtype_fails_closed(self):
        record = _record("C1", "The operator formally awarded a contract.")
        result = Classifier(
            _Helper(
                lambda request: _assigned_response(
                    request, CategoryId.PROCUREMENT, "Invalid-Subtype"
                )
            )
        ).classify(_group((record,)), (record,))
        self.assertEqual(result.category_state, CategoryState.CATEGORY_UNRESOLVED)
        self.assertEqual(
            result.category_resolution_reason,
            CategoryResolutionReason.SEMANTIC_HELPER_INVALID_RESPONSE,
        )

    def test_unresolved_subtype_must_remain_null(self):
        record = _record("C1", "No category-defining action is established.")

        def unresolved_with_subtype(request):
            return {
                "category_state": CategoryState.CATEGORY_UNRESOLVED.value,
                "primary_category_id": None,
                "subtype": "award",
                "category_resolution_reason": (
                    CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION.value
                ),
                "citations": [_span(request.sources[0])],
            }

        result = Classifier(_Helper(unresolved_with_subtype)).classify(
            _group((record,)), (record,)
        )
        self.assertEqual(result.category_state, CategoryState.CATEGORY_UNRESOLVED)
        self.assertEqual(
            result.category_resolution_reason,
            CategoryResolutionReason.SEMANTIC_HELPER_INVALID_RESPONSE,
        )

    def test_not_evaluated_is_an_uninvoked_stage_state(self):
        result = CategoryResult.not_evaluated()
        self.assertEqual(result.category_state, CategoryState.NOT_EVALUATED)
        self.assertIsNone(result.primary_category_id)
        self.assertIsNone(result.primary_category)
        self.assertIsNone(result.subtype)
        self.assertIsNone(result.classification_reason)
        self.assertIsNone(result.category_resolution_reason)

    def test_request_contains_only_source_bodies_and_evidenced_action_facts(self):
        facts = EventIdentityFacts(
            event_key="PRIVATE_EVENT_KEY_TOKEN",
            action="award",
            lifecycle_step="supplier selection",
            subject="radio equipment",
            occurrence_date="PRIVATE_OCCURRENCE_DATE_TOKEN",
            non_identity_claims={"contract_amount": "USD 2M"},
            evidence_references=("PRIVATE_EVIDENCE_REFERENCE_TOKEN",),
        )
        record = _record(
            "C1",
            "The operator formally awarded the radio equipment contract.",
            identity_facts=facts,
        )
        helper = _Helper(lambda request: _assigned_response(request, CategoryId.PROCUREMENT, "award"))
        result = Classifier(helper).classify(_group((record,)), (record,))
        payload = json.dumps(helper.requests[0].as_payload(), ensure_ascii=False)
        for forbidden in (
            "PRIVATE_TITLE_TOKEN",
            "PRIVATE_URL_TOKEN",
            "PRIVATE_CANONICAL_URL_TOKEN",
            "PRIVATE_PUBLISHER_TOKEN",
            "PRIVATE_DATE_TOKEN",
            "PRIVATE_QUERY_TOKEN",
            "PRIVATE_SNIPPET_TOKEN",
            "PRIVATE_DOMAIN_TOKEN",
            "PRIVATE_EVENT_KEY_TOKEN",
            "PRIVATE_OCCURRENCE_DATE_TOKEN",
            "PRIVATE_EVIDENCE_REFERENCE_TOKEN",
            "fetch_rank",
        ):
            self.assertNotIn(forbidden, payload)
        self.assertIn("supplier selection", payload)
        self.assertIn("contract_amount", payload)
        self.assertEqual(result.primary_category_id, CategoryId.PROCUREMENT)

    def test_sources_are_preserved_separately_and_input_order_does_not_matter(self):
        first = _record("C1", "English source: a technical pilot began.")
        second = _record("C2", "中文來源：技術試驗已開始。")
        group = _group((first, second))
        seen_payloads = []
        for order in ((first, second), (second, first)):
            helper = _Helper(lambda request: seen_payloads.append(request.as_payload()) or _assigned_response(request, CategoryId.TECHNICAL_DEVELOPMENT))
            Classifier(helper).classify(group, order)
        self.assertEqual(seen_payloads[0], seen_payloads[1])
        sources = seen_payloads[0]["sources"]
        self.assertEqual(len(sources), 2)
        self.assertNotEqual(sources[0]["substantive_content"], sources[1]["substantive_content"])

    def test_irrelevant_event_identity_claim_conflict_does_not_block_category(self):
        first = _record("C1", "An unexpected traction-power failure stopped service.")
        second = _record("C2", "The same traction-power failure stopped service.")
        group = _group(
            (first, second),
            unresolved_claims=(
                UnresolvedClaim("service_duration_minutes", (("C1", "42"), ("C2", "47"))),
            ),
        )
        helper = _Helper(lambda request: _assigned_response(request, CategoryId.INCIDENT, "technical_accident"))
        result = Classifier(helper).classify(group, (first, second))
        self.assertEqual(result.primary_category_id, CategoryId.INCIDENT)
        self.assertIn("service_duration_minutes", helper.requests[0].as_payload()["unresolved_event_claims"][0]["claim_key"])
        guidance = " ".join(helper.requests[0].as_payload()["guidance"])
        self.assertIn("Differences only in duration, count, magnitude", guidance)
        self.assertIn("When CATEGORY_ASSIGNED, category_resolution_reason must be null.", guidance)

    def test_minor_safety_incident_without_service_impact_can_be_assigned_incident(self):
        record = _record(
            "C1",
            "A passenger fell and received a minor injury in an urban-rail station. "
            "No train, system, evacuation, service, or project impact occurred.",
        )
        helper = _Helper(
            lambda request: _assigned_response(request, CategoryId.INCIDENT, None)
        )

        result = Classifier(helper).classify(_group((record,)), (record,))

        self.assertEqual(result.category_state, CategoryState.CATEGORY_ASSIGNED)
        self.assertEqual(result.primary_category_id, CategoryId.INCIDENT)
        self.assertIsNone(result.category_resolution_reason)
        guidance = " ".join(helper.requests[0].as_payload()["guidance"])
        self.assertIn("An actual passenger, staff, or public safety incident", guidance)
        self.assertIn("Severity and report value do not determine Category", guidance)

    def test_category_unresolved_has_no_assigned_fields_or_reportability(self):
        first = _record("C1", "The source reports a technical trial began.")
        second = _record("C2", "The source says a supplier award occurred and no trial began.")

        def response(request):
            return {
                "category_state": CategoryState.CATEGORY_UNRESOLVED.value,
                "primary_category_id": None,
                "subtype": None,
                "category_resolution_reason": CategoryResolutionReason.CONFLICTING_CATEGORY_DEFINING_CLAIMS.value,
                "citations": [_span(request.sources[0]), _span(request.sources[1])],
            }

        result = Classifier(_Helper(response)).classify(
            _group((first, second)), (first, second)
        )
        self.assertEqual(result.category_state, CategoryState.CATEGORY_UNRESOLVED)
        self.assertEqual(
            result.category_resolution_reason,
            CategoryResolutionReason.CONFLICTING_CATEGORY_DEFINING_CLAIMS,
        )
        self.assertIsNone(result.primary_category_id)
        self.assertIsNone(result.primary_category)
        self.assertIsNone(result.subtype)
        self.assertEqual(result.classification_reason, "CATEGORY_UNRESOLVED")
        self.assertFalse(hasattr(result, "reportability"))

    def test_assigned_response_with_resolution_reason_remains_invalid(self):
        record = _record("C1", "An unexpected urban-rail power failure stopped service.")

        def assigned_with_reason(request):
            proposal = _assigned_response(request, CategoryId.INCIDENT, None)
            proposal["category_resolution_reason"] = (
                CategoryResolutionReason.CONFLICTING_CATEGORY_DEFINING_CLAIMS.value
            )
            return proposal

        result = Classifier(_Helper(assigned_with_reason)).classify(
            _group((record,)), (record,)
        )

        self.assertEqual(result.category_state, CategoryState.CATEGORY_UNRESOLVED)
        self.assertEqual(
            result.category_resolution_reason,
            CategoryResolutionReason.SEMANTIC_HELPER_INVALID_RESPONSE,
        )

    def test_no_unique_principal_action_accepts_one_quote_for_whole_proposal(self):
        record = _record("C1", "The release starts a signalling pilot and passenger service.")
        group = _group((record,))

        def response(request):
            source = request.sources[0]
            return {
                "category_state": CategoryState.CATEGORY_UNRESOLVED.value,
                "primary_category_id": None,
                "subtype": None,
                "category_resolution_reason": CategoryResolutionReason.NO_UNIQUE_PRINCIPAL_ACTION.value,
                "citations": [_span(source)],
            }

        result = Classifier(_Helper(response)).classify(group, (record,))
        self.assertEqual(result.category_state, CategoryState.CATEGORY_UNRESOLVED)
        self.assertEqual(
            result.category_resolution_reason,
            CategoryResolutionReason.NO_UNIQUE_PRINCIPAL_ACTION,
        )

    def test_invalid_or_failed_helper_never_forces_a_category(self):
        record = _record("C1", "The operator awarded a contract for a new system.")
        group = _group((record,))
        cases = (
            (None, CategoryResolutionReason.SEMANTIC_HELPER_UNAVAILABLE),
            (_Helper(error=RuntimeError("provider unavailable")), CategoryResolutionReason.SEMANTIC_HELPER_FAILURE),
            (_Helper({"category_state": "CATEGORY_ASSIGNED"}), CategoryResolutionReason.SEMANTIC_HELPER_INVALID_RESPONSE),
            (_Helper(lambda request: _assigned_response(request, "UNKNOWN_CATEGORY")), CategoryResolutionReason.SEMANTIC_HELPER_INVALID_RESPONSE),
        )
        for helper, reason in cases:
            with self.subTest(reason=reason):
                classifier = Classifier(helper)
                result = classifier.classify(group, (record,))
                self.assertEqual(result.category_state, CategoryState.CATEGORY_UNRESOLVED)
                self.assertEqual(result.category_resolution_reason, reason)
                self.assertIsNone(result.primary_category_id)

    def test_invalid_citations_and_contradictory_responses_fail_closed(self):
        record = _record("C1", "A metro pilot began testing signalling equipment.")
        group = _group((record,))

        def legacy_offsets(request):
            response = _assigned_response(request, CategoryId.TECHNICAL_DEVELOPMENT)
            response.pop("citations")
            response["support_spans"] = [{"candidate_id": "C1", "start": 0, "end": 9999}]
            return response

        def extra_legacy_conflict_field(request):
            response = _assigned_response(request, CategoryId.TECHNICAL_DEVELOPMENT)
            response["conflict_spans"] = [_span(request.sources[0])]
            return response

        for callback in (legacy_offsets, extra_legacy_conflict_field):
            result = Classifier(_Helper(callback)).classify(group, (record,))
            self.assertEqual(result.category_state, CategoryState.CATEGORY_UNRESOLVED)
            self.assertEqual(
                result.category_resolution_reason,
                CategoryResolutionReason.SEMANTIC_HELPER_INVALID_RESPONSE,
            )

    def test_assigned_and_unresolved_empty_citations_fail_closed(self):
        record = _record("C1", "A metro pilot began testing signalling equipment.")
        group = _group((record,))

        def response(request, state):
            proposal = _assigned_response(request, CategoryId.TECHNICAL_DEVELOPMENT)
            if state is CategoryState.CATEGORY_UNRESOLVED:
                proposal.update(
                    {
                        "category_state": state.value,
                        "primary_category_id": None,
                        "subtype": None,
                        "category_resolution_reason": CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION.value,
                    }
                )
            proposal["citations"] = []
            return proposal

        for state in (CategoryState.CATEGORY_ASSIGNED, CategoryState.CATEGORY_UNRESOLVED):
            with self.subTest(state=state):
                result = Classifier(
                    _Helper(lambda request, state=state: response(request, state))
                ).classify(group, (record,))
                self.assertEqual(result.category_state, CategoryState.CATEGORY_UNRESOLVED)
                self.assertEqual(
                    result.category_resolution_reason,
                    CategoryResolutionReason.SEMANTIC_HELPER_INVALID_RESPONSE,
                )

    def test_exact_quote_resolution_produces_canonical_ascii_and_unicode_spans(self):
        cases = (
            ("C1", "Prefix: the pilot began. Suffix.", "the pilot began."),
            ("C1", "前文🙂營運正式啟用。後文", "🙂營運正式啟用。"),
        )
        for candidate_id, body, quote in cases:
            with self.subTest(quote=quote):
                record = _record(candidate_id, body)
                response = _assigned_response(
                    CategorySemanticRequest(
                        sources=(
                            # The owner constructs the real request in classify;
                            # this temporary value only helps form the proposal below.
                            _source_for_test(candidate_id, body),
                        )
                    ),
                    CategoryId.OPERATIONAL_CHANGE,
                )
                response["citations"] = [{"candidate_id": candidate_id, "quote": quote}]
                result = Classifier(_Helper(response)).classify(_group((record,)), (record,))
                start = body.index(quote)
                self.assertEqual(
                    result.provenance["validated_support_spans"],
                    [{"candidate_id": candidate_id, "start": start, "end": start + len(quote)}],
                )
                self.assertNotIn("validated_conflict_spans", result.provenance)

    def test_quote_resolution_fails_closed_without_repair(self):
        cases = (
            ("zero occurrences", "The exact phrase is absent.", "not present"),
            ("multiple occurrences", "repeat here; repeat here", "repeat here"),
            ("overlapping occurrences", "aaa", "aa"),
            ("empty quote", "some source text", ""),
            ("trim recovery forbidden", "phrase", " phrase "),
            ("whitespace normalization forbidden", "line one" + chr(10) + "line two", "line one line two"),
            ("unicode normalization forbidden", "café", "cafe" + chr(0x301)),
            ("case folding forbidden", "Pilot", "pilot"),
            ("fuzzy matching forbidden", "pilot begins", "pilot begen"),
        )
        for label, body, quote in cases:
            with self.subTest(case=label):
                record = _record("C1", body)
                proposal = _assigned_response(
                    CategorySemanticRequest(sources=(_source_for_test("C1", body),)),
                    CategoryId.PROCUREMENT,
                )
                proposal["citations"] = [{"candidate_id": "C1", "quote": quote}]
                result = Classifier(_Helper(proposal)).classify(_group((record,)), (record,))
                self.assertEqual(
                    result.category_resolution_reason,
                    CategoryResolutionReason.SEMANTIC_HELPER_INVALID_RESPONSE,
                )
                self.assertNotIn("validated_support_spans", result.provenance)

    def test_every_citation_must_resolve_and_candidate_membership_is_exact(self):
        record = _record("C1", "The pilot began on the corridor.")
        other = _record("C2", "The pilot began on the corridor.")
        group = _group((record,))
        cases = (
            [{"candidate_id": "missing", "quote": "The pilot began"}],
            [
                {"candidate_id": "C1", "quote": "The pilot began"},
                {"candidate_id": "C1", "quote": "not present"},
            ],
        )
        for citations in cases:
            with self.subTest(citations=citations):
                proposal = _assigned_response(
                    CategorySemanticRequest(sources=(_source_for_test("C1", record.evidence.substantive_content),)),
                    CategoryId.TECHNICAL_DEVELOPMENT,
                )
                proposal["citations"] = citations
                result = Classifier(_Helper(proposal)).classify(group, (record,))
                self.assertEqual(
                    result.category_resolution_reason,
                    CategoryResolutionReason.SEMANTIC_HELPER_INVALID_RESPONSE,
                )
                self.assertNotIn("validated_support_spans", result.provenance)
        # The same text in a different candidate does not make C1's citation ambiguous.
        multi_group = _group((record, other))
        proposal = {
            "category_state": CategoryState.CATEGORY_ASSIGNED.value,
            "primary_category_id": CategoryId.TECHNICAL_DEVELOPMENT.value,
            "subtype": None,
            "category_resolution_reason": None,
            "citations": [{"candidate_id": "C1", "quote": "The pilot began"}],
        }
        accepted = Classifier(_Helper(proposal)).classify(multi_group, (record, other))
        self.assertEqual(accepted.category_state, CategoryState.CATEGORY_ASSIGNED)

    def test_v4_rejects_legacy_v3_shape_and_accepts_one_quote_for_each_unresolved_reason(self):
        record = _record("C1", "The source provides this substantive evidence.")
        group = _group((record,))
        legacy = {
            "category_state": CategoryState.CATEGORY_ASSIGNED.value,
            "primary_category_id": CategoryId.INCIDENT.value,
            "subtype": None,
            "category_resolution_reason": None,
            "support_spans": [{"candidate_id": "C1", "start": 0, "end": 4}],
            "conflict_spans": [],
        }
        rejected = Classifier(_Helper(legacy)).classify(group, (record,))
        self.assertEqual(
            rejected.category_resolution_reason,
            CategoryResolutionReason.SEMANTIC_HELPER_INVALID_RESPONSE,
        )

        for reason in (
            CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION,
            CategoryResolutionReason.RECOMMENDATION_WITHOUT_ADOPTED_ACTION,
            CategoryResolutionReason.CONFLICTING_CATEGORY_DEFINING_CLAIMS,
            CategoryResolutionReason.NO_UNIQUE_PRINCIPAL_ACTION,
            CategoryResolutionReason.INSUFFICIENT_CATEGORY_EVIDENCE,
        ):
            proposal = {
                "category_state": CategoryState.CATEGORY_UNRESOLVED.value,
                "primary_category_id": None,
                "subtype": None,
                "category_resolution_reason": reason.value,
                "citations": [{"candidate_id": "C1", "quote": record.evidence.substantive_content}],
            }
            result = Classifier(_Helper(proposal)).classify(group, (record,))
            self.assertEqual(result.category_state, CategoryState.CATEGORY_UNRESOLVED)
            self.assertEqual(result.category_resolution_reason, reason)
            self.assertEqual(len(result.provenance["validated_support_spans"]), 1)

    def test_typed_v4_response_uses_citation_items(self):
        record = _record("C1", "The operator awarded a contract.")
        typed = CategorySemanticResponse(
            category_state=CategoryState.CATEGORY_ASSIGNED,
            primary_category_id=CategoryId.PROCUREMENT,
            subtype=None,
            category_resolution_reason=None,
            citations=(CategoryCitation("C1", "awarded a contract"),),
        )
        result = Classifier(_Helper(typed)).classify(_group((record,)), (record,))
        self.assertEqual(result.category_state, CategoryState.CATEGORY_ASSIGNED)

    def test_upstream_boundary_is_required_before_helper_invocation(self):
        cases = (
            _record("C1", "", evidence_state=EvidenceState.REJECTED),
            _record("C1", "An urban-rail event.", scope_state=ScopeState.OUT_OF_SCOPE),
            _record("C1", "An urban-rail event.", date_valid=False),
        )
        for record in cases:
            helper = _Helper(lambda request: _assigned_response(request, CategoryId.INCIDENT))
            with self.subTest(candidate=record.candidate.candidate_id, state=record.evidence.state):
                with self.assertRaises(ValueError):
                    Classifier(helper).classify(_group((record,)), (record,))
                self.assertEqual(helper.requests, [])

    def test_record_set_must_match_exactly_the_authoritative_event_group(self):
        first = _record("C1", "A metro pilot began.")
        second = _record("C2", "A metro pilot began.")
        helper = _Helper(lambda request: _assigned_response(request, CategoryId.TECHNICAL_DEVELOPMENT))
        with self.assertRaises(ValueError):
            Classifier(helper).classify(_group((first, second)), (first,))
        with self.assertRaises(ValueError):
            Classifier(helper).classify(_group((first,)), (first, first))
        self.assertEqual(helper.requests, [])


if __name__ == "__main__":
    unittest.main()
