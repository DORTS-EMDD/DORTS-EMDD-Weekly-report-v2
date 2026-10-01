"""Focused tests for the authoritative Reportability owner."""

from __future__ import annotations

from collections.abc import Mapping
from traceback import format_exception
from unittest import TestCase

from src.weekly_report.contracts import (
    CanonicalCandidate,
    CategoryId,
    CategoryResolutionReason,
    CategoryResult,
    CategoryState,
    EventDecisionRecord,
    EventGroup,
    EventIdentityRecord,
    EvidenceResult,
    EvidenceState,
    EMSystemId,
    ReportabilityReason,
    ReportabilitySemanticCitation,
    ReportabilitySemanticMember,
    ReportabilitySemanticProposal,
    ReportabilitySemanticRequest,
    ReportabilityStageFailure,
    ReportabilityState,
    ScopeResult,
    ScopeState,
    TaxonomyInsufficientEvidenceProvenance,
    TaxonomyResult,
    TaxonomyResolutionReason,
    TaxonomyState,
    TaxonomySupportSpan,
    TemporalDiagnostic,
    TemporalResult,
)
from src.weekly_report.reportability import Reportability


def _member(
    candidate_id: str,
    body: str = "The operator completed a substantive engineering pilot.",
    *,
    evidence_state: EvidenceState = EvidenceState.READY,
    scope_state: ScopeState = ScopeState.IN_SCOPE,
    date_valid: bool = True,
) -> EventIdentityRecord:
    evidence = EvidenceResult(
        candidate_id=candidate_id,
        state=evidence_state,
        canonical_source_url=f"https://example.test/{candidate_id}",
        source_type="authoritative",
        substantive_content=body if evidence_state is EvidenceState.READY else "",
        reject_reason=None if evidence_state is EvidenceState.READY else "CONTENT_UNAVAILABLE",
    )
    return EventIdentityRecord(
        CanonicalCandidate(candidate_id, f"Title {candidate_id}", evidence.canonical_source_url),
        evidence,
        ScopeResult(candidate_id, scope_state),
        TemporalResult(
            candidate_id,
            date_valid,
            diagnostic=TemporalDiagnostic.NONE if date_valid else TemporalDiagnostic.OUT_OF_RANGE,
        ),
    )


def _group(*candidate_ids: str, event_id: str = "E1") -> EventGroup:
    ids = tuple(sorted(candidate_ids))
    return EventGroup(event_id, ids, ids[0], identity_basis=())


def _category(group: EventGroup, state: CategoryState = CategoryState.CATEGORY_ASSIGNED) -> CategoryResult:
    if state is CategoryState.CATEGORY_UNRESOLVED:
        return CategoryResult(
            category_state=state,
            event_id=group.event_id,
            classification_reason=state.value,
            category_resolution_reason=CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION,
        )
    return CategoryResult(
        category_state=state,
        event_id=group.event_id,
        primary_category_id=CategoryId.TECHNICAL_DEVELOPMENT,
        primary_category=CategoryId.TECHNICAL_DEVELOPMENT.display_label,
        classification_reason="PRINCIPAL_ACTION_TECHNICAL_DEVELOPMENT",
    )


def _taxonomy(
    group: EventGroup,
    *,
    state: TaxonomyState = TaxonomyState.TAXONOMY_EVALUATED,
    systems: tuple[EMSystemId, ...] = (),
) -> TaxonomyResult:
    spans = tuple(
        TaxonomySupportSpan(system_id, group.member_candidate_ids[0], 0, 4)
        for system_id in systems
    )
    if state is TaxonomyState.TAXONOMY_UNRESOLVED:
        return TaxonomyResult(
            taxonomy_state=state,
            event_id=group.event_id,
            taxonomy_resolution_reason=TaxonomyResolutionReason.INSUFFICIENT_SYSTEM_EVIDENCE,
            provenance=TaxonomyInsufficientEvidenceProvenance(
                member_candidate_ids=group.member_candidate_ids,
                diagnostic="No supported system is established.",
            ),
        )
    return TaxonomyResult(
        taxonomy_state=state,
        event_id=group.event_id,
        systems=systems,
        support_spans=spans,
    )


def _decision(
    group: EventGroup,
    bodies: dict[str, str],
    *,
    category_state: CategoryState = CategoryState.CATEGORY_ASSIGNED,
    taxonomy_state: TaxonomyState = TaxonomyState.TAXONOMY_EVALUATED,
    systems: tuple[EMSystemId, ...] = (),
) -> EventDecisionRecord:
    records = tuple(_member(candidate_id, bodies[candidate_id]) for candidate_id in group.member_candidate_ids)
    return EventDecisionRecord(
        event_group=group,
        member_records=records,
        category_result=_category(group, category_state),
        taxonomy_result=_taxonomy(group, state=taxonomy_state, systems=systems),
    )


def _proposal(
    group: EventGroup,
    *,
    state: ReportabilityState = ReportabilityState.REPORTABLE,
    examined: tuple[str, ...] | None = None,
    citations: tuple[ReportabilitySemanticCitation, ...] = (),
    rationale: str = "The supplied evidence supports the proposed outcome.",
) -> ReportabilitySemanticProposal:
    return ReportabilitySemanticProposal(
        event_id=group.event_id,
        proposed_state=state,
        examined_candidate_ids=examined or group.member_candidate_ids,
        support_citations=citations,
        rationale=rationale,
    )


class _Provider:
    def __init__(self, response=None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.calls: list[ReportabilitySemanticRequest] = []

    def __call__(self, request: ReportabilitySemanticRequest):
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        return self.response(request) if callable(self.response) else self.response


class ReportabilityOwnerTests(TestCase):
    def test_valid_reportable_single_member_resolves_exact_span(self):
        group = _group("C1")
        body = "The operator completed a substantive engineering pilot."
        provider = _Provider(_proposal(group, citations=(_citation("C1", "engineering pilot"),)))

        result = Reportability(provider).evaluate(_decision(group, {"C1": body}))

        self.assertEqual(result.reportability_state, ReportabilityState.REPORTABLE)
        self.assertIsNone(result.reportability_reason)
        self.assertEqual(result.provenance.support_spans[0].candidate_id, "C1")
        self.assertEqual(result.provenance.support_spans[0].start, body.index("engineering pilot"))
        self.assertEqual(
            body[result.provenance.support_spans[0].start : result.provenance.support_spans[0].end],
            "engineering pilot",
        )

    def test_valid_reportable_multi_member_preserves_complete_canonical_population(self):
        group = _group("C2", "C1")
        bodies = {"C1": "C1 completed a pilot.", "C2": "C2 completed a deployment."}
        provider = _Provider(
            _proposal(
                group,
                citations=(
                    _citation("C1", "completed a pilot"),
                    _citation("C2", "completed a deployment"),
                ),
            )
        )

        result = Reportability(provider).evaluate(_decision(group, bodies))

        self.assertEqual(result.provenance.examined_candidate_ids, ("C1", "C2"))
        self.assertEqual({span.candidate_id for span in result.provenance.support_spans}, {"C1", "C2"})
        self.assertEqual(len(provider.calls), 1)

    def test_valid_not_reportable_derives_locked_reason(self):
        group = _group("C1")
        provider = _Provider(_proposal(group, state=ReportabilityState.NOT_REPORTABLE))

        result = Reportability(provider).evaluate(_decision(group, {"C1": "Administrative workflow only."}))

        self.assertEqual(result.reportability_state, ReportabilityState.NOT_REPORTABLE)
        self.assertEqual(result.reportability_reason, ReportabilityReason.LOW_REPORTABILITY_VALUE)
        self.assertEqual(result.provenance.support_spans, ())

    def test_provider_is_called_once_and_request_contains_only_bounded_evidence(self):
        group = _group("C2", "C1")
        bodies = {"C1": "unchanged C1 content", "C2": "unchanged C2 content"}
        provider = _Provider(_proposal(group, state=ReportabilityState.NOT_REPORTABLE))
        Reportability(provider).evaluate(_decision(group, bodies))

        self.assertEqual(len(provider.calls), 1)
        request = provider.calls[0]
        self.assertEqual(request.event_id, "E1")
        self.assertEqual(request.member_candidate_ids, ("C1", "C2"))
        self.assertEqual(
            request.as_payload(),
            {
                "event_id": "E1",
                "members": [
                    {"candidate_id": "C1", "substantive_content": "unchanged C1 content"},
                    {"candidate_id": "C2", "substantive_content": "unchanged C2 content"},
                ],
            },
        )
        self.assertEqual(set(request.as_payload()), {"event_id", "members"})
        self.assertEqual(set(request.as_payload()["members"][0]), {"candidate_id", "substantive_content"})

    def test_unreachable_category_and_taxonomy_fail_before_provider(self):
        group = _group("C1")
        for category_state, taxonomy_state in (
            (CategoryState.CATEGORY_UNRESOLVED, TaxonomyState.TAXONOMY_EVALUATED),
            (CategoryState.CATEGORY_ASSIGNED, TaxonomyState.TAXONOMY_UNRESOLVED),
        ):
            provider = _Provider(_proposal(group, state=ReportabilityState.NOT_REPORTABLE))
            with self.subTest(category_state=category_state, taxonomy_state=taxonomy_state):
                with self.assertRaises(ReportabilityStageFailure) as raised:
                    Reportability(provider).evaluate(
                        _decision(
                            group,
                            {"C1": "content"},
                            category_state=category_state,
                            taxonomy_state=taxonomy_state,
                        )
                    )
                self.assertEqual(raised.exception.event_id, group.event_id)
                self.assertEqual(provider.calls, [])

    def test_empty_taxonomy_is_allowed_and_nonempty_taxonomy_does_not_approve(self):
        empty_group = _group("C1", event_id="EMPTY")
        empty_provider = _Provider(
            _proposal(empty_group, citations=(_citation("C1", "engineering"),))
        )
        empty_result = Reportability(empty_provider).evaluate(
            _decision(empty_group, {"C1": "engineering work"}, systems=())
        )
        self.assertEqual(empty_result.reportability_state, ReportabilityState.REPORTABLE)

        assigned_group = _group("C1", event_id="ASSIGNED")
        assigned_provider = _Provider(
            _proposal(assigned_group, state=ReportabilityState.NOT_REPORTABLE)
        )
        assigned_result = Reportability(assigned_provider).evaluate(
            _decision(
                assigned_group,
                {"C1": "signal equipment"},
                systems=(EMSystemId.SIGNALLING,),
            )
        )
        self.assertEqual(assigned_result.reportability_state, ReportabilityState.NOT_REPORTABLE)

    def test_proposal_event_id_and_examined_population_are_authoritative_boundaries(self):
        group = _group("C1", "C2")
        decision = _decision(group, {"C1": "one", "C2": "two"})
        cases = (
            _proposal(group, examined=("C1",), state=ReportabilityState.NOT_REPORTABLE),
            _proposal(group, examined=("C1", "C2", "C3"), state=ReportabilityState.NOT_REPORTABLE),
            {
                "event_id": group.event_id,
                "proposed_state": ReportabilityState.NOT_REPORTABLE,
                "examined_candidate_ids": ("C1", "C1"),
                "support_citations": (),
                "rationale": "The evidence does not establish an accepted path.",
            },
        )
        for proposal in cases:
            provider = _Provider(proposal)
            examined = (
                proposal.examined_candidate_ids
                if isinstance(proposal, ReportabilitySemanticProposal)
                else proposal["examined_candidate_ids"]
            )
            with self.subTest(examined=examined):
                with self.assertRaises(ReportabilityStageFailure):
                    Reportability(provider).evaluate(decision)
                self.assertEqual(len(provider.calls), 1)

        mismatched = ReportabilitySemanticProposal(
            event_id="OTHER",
            proposed_state=ReportabilityState.NOT_REPORTABLE,
            examined_candidate_ids=group.member_candidate_ids,
            support_citations=(),
            rationale="The evidence does not establish an accepted path.",
        )
        with self.assertRaises(ReportabilityStageFailure) as raised:
            Reportability(_Provider(mismatched)).evaluate(decision)
        self.assertEqual(raised.exception.event_id, group.event_id)

    def test_unknown_candidate_citation_fails(self):
        group = _group("C1")
        proposal = _proposal(group, citations=(_citation("C2", "content"),))
        with self.assertRaises(ReportabilityStageFailure):
            Reportability(_Provider(proposal)).evaluate(_decision(group, {"C1": "content"}))

    def test_exact_quote_absent_or_repeated_fails(self):
        group = _group("C1")
        for body, quote in (("source content", "missing"), ("repeat repeat", "repeat")):
            provider = _Provider(_proposal(group, citations=(_citation("C1", quote),)))
            with self.subTest(body=body):
                with self.assertRaises(ReportabilityStageFailure):
                    Reportability(provider).evaluate(_decision(group, {"C1": body}))

    def test_exact_quote_resolution_does_not_normalize_or_cross_search(self):
        group = _group("C1", "C2")
        bodies = {"C1": "Exact source text", "C2": "Other source text"}
        provider = _Provider(_proposal(group, citations=(_citation("C1", "Exact source text"),)))
        result = Reportability(provider).evaluate(_decision(group, bodies))
        span = result.provenance.support_spans[0]
        self.assertEqual(bodies[span.candidate_id][span.start : span.end], "Exact source text")

        whitespace_provider = _Provider(
            _proposal(group, citations=(_citation("C1", "Exact  source text"),))
        )
        with self.assertRaises(ReportabilityStageFailure):
            Reportability(whitespace_provider).evaluate(_decision(group, bodies))

    def test_malformed_proposal_and_provider_exception_are_sanitized_without_retry(self):
        group = _group("C1")
        secret = "SECRET_PROVIDER_PAYLOAD_123"
        provider = _Provider(error=RuntimeError(secret))
        with self.assertRaises(ReportabilityStageFailure) as raised:
            Reportability(provider).evaluate(_decision(group, {"C1": "content"}))
        failure = raised.exception
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(failure.event_id, group.event_id)
        self.assertNotIn(secret, str(failure))
        self.assertNotIn(secret, repr(failure.args))
        self.assertIsNone(failure.__cause__)
        self.assertIsNone(failure.__context__)
        self.assertNotIn(secret, "".join(format_exception(failure)))

        malformed = _Provider({"unexpected": "payload"})
        with self.assertRaises(ReportabilityStageFailure) as malformed_raised:
            Reportability(malformed).evaluate(_decision(group, {"C1": "content"}))
        self.assertEqual(len(malformed.calls), 1)
        self.assertEqual(malformed_raised.exception.event_id, group.event_id)

    def test_provider_materialization_failures_are_sanitized_across_untrusted_shapes(self):
        group = _group("C1")
        decision = _decision(group, {"C1": "content"})
        secret = "SECRET_PROVIDER_MATERIALIZATION_123"

        class _KeyIterationFailure(Mapping):
            def __iter__(self):
                raise ValueError(secret)

            def __len__(self):
                return 5

            def __getitem__(self, key):
                raise AssertionError("field access should not be reached")

        class _FieldAccessFailure(dict):
            def __getitem__(self, key):
                raise LookupError(secret)

        class _CitationIterationFailure(Mapping):
            def __iter__(self):
                raise ReportabilityStageFailure(secret, event_id="ATTACKER_EVENT")

            def __len__(self):
                return 2

            def __getitem__(self, key):
                raise AssertionError("citation field access should not be reached")

        class _CitationFieldAccessFailure(dict):
            def __getitem__(self, key):
                raise KeyError(secret)

        class _EqualityFailure(str):
            def __eq__(self, other):
                raise RuntimeError(secret)

        class _TypedAttributeFailure(ReportabilitySemanticProposal):
            armed = False

            def __getattribute__(self, name):
                if name == "rationale" and type(self).armed:
                    raise RuntimeError(secret)
                return super().__getattribute__(name)

        valid_fields = {
            "event_id": group.event_id,
            "proposed_state": ReportabilityState.NOT_REPORTABLE,
            "examined_candidate_ids": ("C1",),
            "support_citations": (),
            "rationale": "The supplied evidence does not establish an accepted path.",
        }
        citation_fields = {
            "event_id": group.event_id,
            "proposed_state": ReportabilityState.REPORTABLE,
            "examined_candidate_ids": ("C1",),
            "support_citations": [_CitationIterationFailure()],
            "rationale": "The supplied evidence supports the proposed outcome.",
        }
        citation_access_fields = {
            **citation_fields,
            "support_citations": [_CitationFieldAccessFailure(candidate_id="C1", exact_quote="content")],
        }
        equality_failure_fields = {**valid_fields, "event_id": _EqualityFailure(group.event_id)}
        typed = _TypedAttributeFailure(**valid_fields)
        _TypedAttributeFailure.armed = True
        responses = (
            _KeyIterationFailure(),
            _FieldAccessFailure(valid_fields),
            citation_fields,
            citation_access_fields,
            equality_failure_fields,
            typed,
        )

        for response in responses:
            provider = _Provider(response)
            with self.subTest(response=type(response).__name__):
                try:
                    result = Reportability(provider).evaluate(decision)
                except ReportabilityStageFailure as failure:
                    self.assertNotIn(secret, str(failure))
                    self.assertNotIn(secret, repr(failure.args))
                    self.assertNotIn(secret, "".join(format_exception(failure)))
                    self.assertIsNone(failure.__cause__)
                    self.assertIsNone(failure.__context__)
                    self.assertEqual(failure.event_id, group.event_id)
                else:
                    self.assertIs(response, equality_failure_fields)
                    self.assertEqual(result.reportability_state, ReportabilityState.NOT_REPORTABLE)
                self.assertEqual(len(provider.calls), 1)

    def test_scalar_examined_candidate_ids_are_rejected_before_population_comparison(self):
        group = _group("1", "C")
        response = {
            "event_id": group.event_id,
            "proposed_state": ReportabilityState.NOT_REPORTABLE,
            "examined_candidate_ids": "C1",
            "support_citations": (),
            "rationale": "The supplied evidence does not establish an accepted path.",
        }
        provider = _Provider(response)

        with self.assertRaises(ReportabilityStageFailure) as raised:
            Reportability(provider).evaluate(_decision(group, {"1": "one", "C": "two"}))

        self.assertEqual(str(raised.exception), "malformed reportability proposal")
        self.assertEqual(raised.exception.event_id, group.event_id)
        self.assertEqual(len(provider.calls), 1)

    def test_scalar_support_citations_are_rejected_at_materialization_boundary(self):
        group = _group("C1")
        response = {
            "event_id": group.event_id,
            "proposed_state": ReportabilityState.NOT_REPORTABLE,
            "examined_candidate_ids": ("C1",),
            "support_citations": "not-an-array",
            "rationale": "The supplied evidence does not establish an accepted path.",
        }
        provider = _Provider(response)

        with self.assertRaises(ReportabilityStageFailure) as raised:
            Reportability(provider).evaluate(_decision(group, {"C1": "content"}))

        self.assertEqual(str(raised.exception), "malformed reportability proposal")
        self.assertEqual(raised.exception.event_id, group.event_id)
        self.assertEqual(len(provider.calls), 1)

    def test_valid_string_subclasses_are_detached_before_authoritative_operations(self):
        group = _group("C1")
        decision = _decision(group, {"C1": "engineering content"})
        secret = "SECRET_PROVIDER_POST_MATERIALIZATION_123"

        class _HashBomb(str):
            def __hash__(self):
                raise RuntimeError(secret)

            def __eq__(self, other):
                raise RuntimeError(secret)

        mapping = {
            "event_id": _HashBomb(group.event_id),
            "proposed_state": ReportabilityState.REPORTABLE,
            "examined_candidate_ids": ("C1",),
            "support_citations": [
                {
                    "candidate_id": _HashBomb("C1"),
                    "exact_quote": _HashBomb("engineering content"),
                }
            ],
            "rationale": _HashBomb("The supplied evidence supports the proposed outcome."),
        }
        mapping_provider = _Provider(mapping)
        mapping_result = Reportability(mapping_provider).evaluate(decision)
        self.assertEqual(mapping_result.reportability_state, ReportabilityState.REPORTABLE)
        self.assertIs(type(mapping_result.event_id), str)
        self.assertIs(type(mapping_result.provenance.rationale), str)
        self.assertIs(type(mapping_result.provenance.support_spans[0].candidate_id), str)

        typed = ReportabilitySemanticProposal(
            event_id=_HashBomb(group.event_id),
            proposed_state=ReportabilityState.REPORTABLE,
            examined_candidate_ids=("C1",),
            support_citations=(
                ReportabilitySemanticCitation(
                    candidate_id=_HashBomb("C1"),
                    exact_quote=_HashBomb("engineering content"),
                ),
            ),
            rationale=_HashBomb("The supplied evidence supports the proposed outcome."),
        )
        typed_provider = _Provider(typed)
        typed_result = Reportability(typed_provider).evaluate(decision)
        self.assertEqual(typed_result.reportability_state, ReportabilityState.REPORTABLE)
        self.assertEqual(len(mapping_provider.calls), 1)
        self.assertEqual(len(typed_provider.calls), 1)

    def test_no_category_or_taxonomy_mutation_and_result_remains_immutable(self):
        group = _group("C1")
        decision = _decision(group, {"C1": "engineering content"})
        category_before = decision.category_result
        taxonomy_before = decision.taxonomy_result
        provider = _Provider(_proposal(group, citations=(_citation("C1", "engineering content"),)))

        result = Reportability(provider).evaluate(decision)

        self.assertIs(decision.category_result, category_before)
        self.assertIs(decision.taxonomy_result, taxonomy_before)
        self.assertEqual(result.provenance.examined_candidate_ids, ("C1",))
        with self.assertRaises(AttributeError):
            result.reportability_state = ReportabilityState.NOT_REPORTABLE  # type: ignore[misc]

    def test_invalid_direct_invocation_is_a_technical_failure(self):
        provider = _Provider(None)
        with self.assertRaises(ReportabilityStageFailure) as raised:
            Reportability(provider).evaluate(object())  # type: ignore[arg-type]
        self.assertEqual(raised.exception.event_id, "")
        self.assertEqual(len(provider.calls), 0)


def _citation(candidate_id: str, exact_quote: str) -> ReportabilitySemanticCitation:
    return ReportabilitySemanticCitation(candidate_id, exact_quote)


if __name__ == "__main__":
    import unittest

    unittest.main()
