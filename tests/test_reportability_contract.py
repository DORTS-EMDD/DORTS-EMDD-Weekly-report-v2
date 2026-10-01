"""Focused tests for the typed Reportability contract boundary."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from unittest import TestCase

from src.weekly_report.contracts import (
    ReportabilityEvidenceProvenance,
    ReportabilityReason,
    ReportabilityResult,
    ReportabilitySemanticCitation,
    ReportabilitySemanticMember,
    ReportabilitySemanticProposal,
    ReportabilitySemanticProposalProvider,
    ReportabilitySemanticRequest,
    ReportabilityStageFailure,
    ReportabilityState,
    ReportabilitySupportSpan,
)


def _span(candidate_id: str = "C1", start: int = 0, end: int = 4) -> ReportabilitySupportSpan:
    return ReportabilitySupportSpan(candidate_id=candidate_id, start=start, end=end)


def _provenance(
    *,
    candidate_ids: tuple[str, ...] = ("C1",),
    spans: tuple[ReportabilitySupportSpan, ...] = (),
    rationale: str = "The evidence establishes the reportability outcome.",
) -> ReportabilityEvidenceProvenance:
    return ReportabilityEvidenceProvenance(
        examined_candidate_ids=candidate_ids,
        support_spans=spans,
        rationale=rationale,
    )


class ReportabilityContractTests(TestCase):
    def test_state_and_reason_vocabularies_are_exact(self):
        self.assertEqual(
            {state.name: state.value for state in ReportabilityState},
            {"REPORTABLE": "REPORTABLE", "NOT_REPORTABLE": "NOT_REPORTABLE"},
        )
        self.assertEqual(
            {reason.name: reason.value for reason in ReportabilityReason},
            {"LOW_REPORTABILITY_VALUE": "LOW_REPORTABILITY_VALUE"},
        )

    def test_support_span_accepts_valid_bounds_and_is_immutable(self):
        span = _span()
        self.assertEqual((span.candidate_id, span.start, span.end), ("C1", 0, 4))
        with self.assertRaises(FrozenInstanceError):
            span.end = 5  # type: ignore[misc]

    def test_support_span_rejects_invalid_identity_and_bounds(self):
        with self.assertRaises(ValueError):
            _span(candidate_id="")
        with self.assertRaises(ValueError):
            _span(start=-1)
        with self.assertRaises(ValueError):
            _span(start=4, end=4)
        with self.assertRaises(ValueError):
            _span(start=5, end=4)
        with self.assertRaises(TypeError):
            _span(start=True)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            _span(end=False)  # type: ignore[arg-type]

    def test_evidence_provenance_validates_membership_and_freezes_collections(self):
        candidate_ids = ["C1", "C2"]
        spans = [_span("C1")]
        provenance = ReportabilityEvidenceProvenance(
            examined_candidate_ids=candidate_ids,
            support_spans=spans,
            rationale="Evidence supports the positive path.",
        )
        candidate_ids.append("C3")
        spans.clear()
        self.assertEqual(provenance.examined_candidate_ids, ("C1", "C2"))
        self.assertEqual(provenance.support_spans, (_span("C1"),))
        with self.assertRaises(FrozenInstanceError):
            provenance.rationale = "changed"  # type: ignore[misc]

    def test_evidence_provenance_rejects_empty_duplicate_and_unexamined_values(self):
        with self.assertRaises(ValueError):
            _provenance(candidate_ids=())
        with self.assertRaises(ValueError):
            _provenance(candidate_ids=("C1", "C1"))
        with self.assertRaises(ValueError):
            _provenance(candidate_ids=("",))
        with self.assertRaises(ValueError):
            _provenance(rationale=" ")
        with self.assertRaises(ValueError):
            _provenance(spans=(_span("C2"),))

    def test_reportable_result_requires_none_reason_and_support(self):
        result = ReportabilityResult(
            event_id="E1",
            reportability_state=ReportabilityState.REPORTABLE,
            reportability_reason=None,
            provenance=_provenance(spans=(_span(),)),
        )
        self.assertEqual(result.reportability_state, ReportabilityState.REPORTABLE)
        self.assertIsNone(result.reportability_reason)
        with self.assertRaises(ValueError):
            ReportabilityResult(
                event_id="E1",
                reportability_state=ReportabilityState.REPORTABLE,
                reportability_reason=ReportabilityReason.LOW_REPORTABILITY_VALUE,
                provenance=_provenance(spans=(_span(),)),
            )
        with self.assertRaises(ValueError):
            ReportabilityResult(
                event_id="E1",
                reportability_state=ReportabilityState.REPORTABLE,
                reportability_reason=None,
                provenance=_provenance(),
            )

    def test_not_reportable_result_requires_reason_and_no_support(self):
        result = ReportabilityResult(
            event_id="E1",
            reportability_state=ReportabilityState.NOT_REPORTABLE,
            reportability_reason=ReportabilityReason.LOW_REPORTABILITY_VALUE,
            provenance=_provenance(),
        )
        self.assertEqual(result.reportability_reason, ReportabilityReason.LOW_REPORTABILITY_VALUE)
        with self.assertRaises(ValueError):
            ReportabilityResult(
                event_id="E1",
                reportability_state=ReportabilityState.NOT_REPORTABLE,
                reportability_reason=None,
                provenance=_provenance(),
            )
        with self.assertRaises(ValueError):
            ReportabilityResult(
                event_id="E1",
                reportability_state=ReportabilityState.NOT_REPORTABLE,
                reportability_reason=ReportabilityReason.LOW_REPORTABILITY_VALUE,
                provenance=_provenance(spans=(_span(),)),
            )

    def test_result_requires_event_and_typed_provenance(self):
        with self.assertRaises(ValueError):
            ReportabilityResult(
                event_id="",
                reportability_state=ReportabilityState.REPORTABLE,
                reportability_reason=None,
                provenance=_provenance(spans=(_span(),)),
            )
        with self.assertRaises(TypeError):
            ReportabilityResult(
                event_id="E1",
                reportability_state=ReportabilityState.REPORTABLE,
                reportability_reason=None,
                provenance="not provenance",  # type: ignore[arg-type]
            )

    def test_semantic_member_requires_candidate_and_preserves_content(self):
        member = ReportabilitySemanticMember("C1", "  exact content  ")
        self.assertEqual(member.substantive_content, "  exact content  ")
        with self.assertRaises(ValueError):
            ReportabilitySemanticMember("", "content")
        with self.assertRaises(TypeError):
            ReportabilitySemanticMember("C1", None)  # type: ignore[arg-type]

    def test_semantic_request_requires_unique_canonical_member_order(self):
        members = [
            ReportabilitySemanticMember("C1", "one"),
            ReportabilitySemanticMember("C2", "two"),
        ]
        request = ReportabilitySemanticRequest("E1", members)
        self.assertEqual(request.member_candidate_ids, ("C1", "C2"))
        self.assertEqual(request.as_payload()["members"][0]["candidate_id"], "C1")
        members.append(ReportabilitySemanticMember("C3", "three"))
        self.assertEqual(len(request.members), 2)
        with self.assertRaises(ValueError):
            ReportabilitySemanticRequest("E1", (members[1], members[0]))
        with self.assertRaises(ValueError):
            ReportabilitySemanticRequest("E1", (members[0], members[0]))
        with self.assertRaises(ValueError):
            ReportabilitySemanticRequest("", tuple(members[:1]))
        with self.assertRaises(ValueError):
            ReportabilitySemanticRequest("E1", ())

    def test_semantic_citation_validates_without_normalizing_quote(self):
        citation = ReportabilitySemanticCitation("C1", "  exact quote  ")
        self.assertEqual(citation.exact_quote, "  exact quote  ")
        with self.assertRaises(ValueError):
            ReportabilitySemanticCitation("", "quote")
        with self.assertRaises(ValueError):
            ReportabilitySemanticCitation("C1", " ")

    def test_proposal_reportable_requires_citation_and_has_no_reason_field(self):
        citation = ReportabilitySemanticCitation("C1", "positive evidence")
        proposal = ReportabilitySemanticProposal(
            event_id="E1",
            proposed_state=ReportabilityState.REPORTABLE,
            examined_candidate_ids=("C1",),
            support_citations=(citation,),
            rationale="The evidence supports an accepted value path.",
        )
        self.assertEqual(proposal.support_citations, (citation,))
        names = {field.name for field in fields(ReportabilitySemanticProposal)}
        self.assertNotIn("proposed_reason", names)
        self.assertNotIn("confidence", names)
        self.assertNotIn("score", names)
        with self.assertRaises(ValueError):
            ReportabilitySemanticProposal(
                event_id="E1",
                proposed_state=ReportabilityState.REPORTABLE,
                examined_candidate_ids=("C1",),
                support_citations=(),
                rationale="The evidence supports an accepted value path.",
            )

    def test_proposal_not_reportable_forbids_citations(self):
        proposal = ReportabilitySemanticProposal(
            event_id="E1",
            proposed_state=ReportabilityState.NOT_REPORTABLE,
            examined_candidate_ids=("C1",),
            support_citations=(),
            rationale="The evidence does not establish an accepted value path.",
        )
        self.assertEqual(proposal.support_citations, ())
        with self.assertRaises(ValueError):
            ReportabilitySemanticProposal(
                event_id="E1",
                proposed_state=ReportabilityState.NOT_REPORTABLE,
                examined_candidate_ids=("C1",),
                support_citations=(ReportabilitySemanticCitation("C1", "quote"),),
                rationale="The evidence does not establish an accepted value path.",
            )
        with self.assertRaises(ValueError):
            ReportabilitySemanticProposal(
                event_id="E1",
                proposed_state="NOT_EVALUATED",  # type: ignore[arg-type]
                examined_candidate_ids=("C1",),
                support_citations=(),
                rationale="The stage was not reached.",
            )

    def test_provider_protocol_shape_is_importable_and_usable(self):
        class Provider:
            def __call__(self, request: ReportabilitySemanticRequest):
                return ReportabilitySemanticProposal(
                    event_id=request.event_id,
                    proposed_state=ReportabilityState.NOT_REPORTABLE,
                    examined_candidate_ids=request.member_candidate_ids,
                    support_citations=(),
                    rationale="The supplied evidence is insufficient for an accepted path.",
                )

        provider: ReportabilitySemanticProposalProvider = Provider()
        request = ReportabilitySemanticRequest(
            "E1", (ReportabilitySemanticMember("C1", "content"),)
        )
        self.assertIsInstance(provider(request), ReportabilitySemanticProposal)

    def test_stage_failure_is_technical_and_distinct_from_domain_result(self):
        failure = ReportabilityStageFailure("provider unavailable", event_id="E1")
        self.assertIsInstance(failure, RuntimeError)
        self.assertEqual(failure.reason, "provider unavailable")
        self.assertEqual(failure.event_id, "E1")
        self.assertNotIsInstance(failure, ReportabilityResult)
        safe_default = ReportabilityStageFailure("", event_id="E1")
        self.assertEqual(str(safe_default), "reportability stage failed")


if __name__ == "__main__":
    import unittest

    unittest.main()
