"""Authoritative V2 Reportability owner.

The owner accepts one narrow, proposal-only semantic provider.  The provider
does not own Reportability decisions; this module validates its complete
proposal against the EventDecisionRecord evidence boundary and constructs the
typed ReportabilityResult.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .contracts import (
    CategoryState,
    EventDecisionRecord,
    EvidenceState,
    EventIdentityRecord,
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
    ScopeState,
    TaxonomyState,
)


_PROPOSAL_FIELDS = frozenset(
    {
        "event_id",
        "proposed_state",
        "examined_candidate_ids",
        "support_citations",
        "rationale",
    }
)
_CITATION_FIELDS = frozenset({"candidate_id", "exact_quote"})


def _technical(reason: str, event_id: str = "") -> ReportabilityStageFailure:
    """Create an owner-controlled technical failure diagnostic."""

    return ReportabilityStageFailure(reason, event_id=event_id)


def _citation(value: object) -> ReportabilitySemanticCitation:
    if isinstance(value, ReportabilitySemanticCitation):
        return ReportabilitySemanticCitation(value.candidate_id, value.exact_quote)
    if not isinstance(value, Mapping) or frozenset(value) != _CITATION_FIELDS:
        raise _technical("reportability citation fields do not match the proposal contract")
    return ReportabilitySemanticCitation(
        candidate_id=value["candidate_id"],
        exact_quote=value["exact_quote"],
    )


def _citations(value: object) -> tuple[ReportabilitySemanticCitation, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise _technical("reportability support_citations must be an array")
    return tuple(_citation(item) for item in value)


def _trusted_str(value: object) -> str:
    """Copy a validated string into an exact built-in string object."""

    if not isinstance(value, str):
        raise TypeError("reportability proposal string field is invalid")
    copied = str.__str__(value)
    if type(copied) is not str:
        raise TypeError("reportability proposal string field is invalid")
    return copied


def _trusted_citation(value: ReportabilitySemanticCitation) -> ReportabilitySemanticCitation:
    return ReportabilitySemanticCitation(
        candidate_id=_trusted_str(value.candidate_id),
        exact_quote=_trusted_str(value.exact_quote),
    )


def _trusted_proposal(
    proposal: ReportabilitySemanticProposal,
) -> ReportabilitySemanticProposal:
    """Detach provider object behavior after typed validation succeeds."""

    return ReportabilitySemanticProposal(
        event_id=_trusted_str(proposal.event_id),
        proposed_state=proposal.proposed_state,
        examined_candidate_ids=tuple(
            _trusted_str(candidate_id) for candidate_id in proposal.examined_candidate_ids
        ),
        support_citations=tuple(
            _trusted_citation(citation) for citation in proposal.support_citations
        ),
        rationale=_trusted_str(proposal.rationale),
    )


def _proposal(value: object, *, event_id: str) -> ReportabilitySemanticProposal:
    """Materialize and validate one untrusted provider proposal."""

    try:
        if isinstance(value, ReportabilitySemanticProposal):
            proposal = ReportabilitySemanticProposal(
                event_id=value.event_id,
                proposed_state=value.proposed_state,
                examined_candidate_ids=value.examined_candidate_ids,
                support_citations=_citations(value.support_citations),
                rationale=value.rationale,
            )
        else:
            if not isinstance(value, Mapping) or frozenset(value) != _PROPOSAL_FIELDS:
                raise _technical("reportability proposal fields do not match the proposal contract")
            proposal = ReportabilitySemanticProposal(
                event_id=value["event_id"],
                proposed_state=value["proposed_state"],
                examined_candidate_ids=value["examined_candidate_ids"],
                support_citations=_citations(value["support_citations"]),
                rationale=value["rationale"],
            )
    except Exception:
        raise _technical("malformed reportability proposal", event_id) from None

    try:
        trusted_proposal = _trusted_proposal(proposal)
    except Exception:
        raise _technical("malformed reportability proposal", event_id) from None
    if trusted_proposal.event_id != event_id:
        raise _technical("reportability proposal event_id mismatch", event_id)
    return trusted_proposal


def _unique_quote_span(
    citation: ReportabilitySemanticCitation,
    bodies: Mapping[str, str],
    event_id: str,
) -> ReportabilitySupportSpan:
    if citation.candidate_id not in bodies:
        raise _technical("reportability citation references a non-member candidate", event_id)
    body = bodies[citation.candidate_id]
    quote = citation.exact_quote
    start = body.find(quote)
    if start < 0:
        raise _technical("reportability citation exact_quote not found", event_id)
    second = body.find(quote, start + 1)
    if second >= 0:
        raise _technical("reportability citation exact_quote ambiguous", event_id)
    end = start + len(quote)
    if end <= start or end > len(body) or body[start:end] != quote:
        raise _technical("reportability citation span does not exactly map to source content", event_id)
    return ReportabilitySupportSpan(citation.candidate_id, start, end)


class Reportability:
    """Sole authoritative owner for one EventDecisionRecord."""

    CONTRACT_VERSION = "reportability-v1"

    def __init__(self, proposal_provider: ReportabilitySemanticProposalProvider) -> None:
        if proposal_provider is None:
            raise TypeError("Reportability requires a semantic proposal provider")
        self._proposal_provider = proposal_provider

    @staticmethod
    def _event_id(record: object) -> str:
        if isinstance(record, EventDecisionRecord):
            event_group = record.event_group
            event_id = getattr(event_group, "event_id", "")
            return event_id if isinstance(event_id, str) else ""
        return ""

    @staticmethod
    def _ordered_records(record: EventDecisionRecord) -> tuple[EventIdentityRecord, ...]:
        event_id = record.event_group.event_id
        if not isinstance(record.member_records, tuple):
            raise _technical("Reportability member records must be immutable", event_id)
        by_candidate: dict[str, EventIdentityRecord] = {}
        for member_record in record.member_records:
            if not isinstance(member_record, EventIdentityRecord):
                raise _technical("Reportability member records are invalid", event_id)
            candidate_id = member_record.candidate.candidate_id
            if candidate_id in by_candidate:
                raise _technical("Reportability member records contain duplicates", event_id)
            if member_record.evidence.candidate_id != candidate_id:
                raise _technical("Reportability evidence identity does not match member", event_id)
            if member_record.evidence.state is not EvidenceState.READY:
                raise _technical("Reportability requires EVIDENCE_READY members", event_id)
            if member_record.scope.state is not ScopeState.IN_SCOPE:
                raise _technical("Reportability requires IN_SCOPE members", event_id)
            if not member_record.temporal.date_valid:
                raise _technical("Reportability requires DATE_VALID members", event_id)
            if not isinstance(member_record.evidence.substantive_content, str):
                raise _technical("Reportability evidence content is invalid", event_id)
            if not member_record.evidence.substantive_content.strip():
                raise _technical("Reportability evidence content is empty", event_id)
            by_candidate[candidate_id] = member_record

        expected_ids = tuple(record.event_group.member_candidate_ids)
        if len(by_candidate) != len(expected_ids) or set(by_candidate) != set(expected_ids):
            raise _technical("Reportability members must match EventGroup exactly", event_id)
        return tuple(by_candidate[candidate_id] for candidate_id in expected_ids)

    @classmethod
    def _request(cls, record: EventDecisionRecord) -> ReportabilitySemanticRequest:
        event_id = record.event_group.event_id
        ordered_records = cls._ordered_records(record)
        return ReportabilitySemanticRequest(
            event_id=event_id,
            members=tuple(
                ReportabilitySemanticMember(
                    candidate_id=member_record.candidate.candidate_id,
                    substantive_content=member_record.evidence.substantive_content,
                )
                for member_record in ordered_records
            ),
        )

    @staticmethod
    def _validate_record(record: object) -> EventDecisionRecord:
        if not isinstance(record, EventDecisionRecord):
            raise _technical("Reportability requires an EventDecisionRecord")
        event_id = record.event_group.event_id
        if record.category_result.event_id != event_id:
            raise _technical("Reportability CategoryResult event_id mismatch", event_id)
        if record.taxonomy_result.event_id != event_id:
            raise _technical("Reportability TaxonomyResult event_id mismatch", event_id)
        if record.category_result.category_state is not CategoryState.CATEGORY_ASSIGNED:
            raise _technical("Reportability prerequisites are not satisfied", event_id)
        if record.taxonomy_result.taxonomy_state is not TaxonomyState.TAXONOMY_EVALUATED:
            raise _technical("Reportability prerequisites are not satisfied", event_id)
        return record

    @classmethod
    def _accept_proposal(
        cls,
        proposal: ReportabilitySemanticProposal,
        request: ReportabilitySemanticRequest,
        records: tuple[EventIdentityRecord, ...],
    ) -> ReportabilityResult:
        event_id = request.event_id
        request_ids = request.member_candidate_ids
        examined_ids = proposal.examined_candidate_ids
        if len(examined_ids) != len(request_ids) or len(examined_ids) != len(set(examined_ids)):
            raise _technical("reportability proposal examined population mismatch", event_id)
        if set(examined_ids) != set(request_ids):
            raise _technical("reportability proposal examined population mismatch", event_id)

        bodies = {
            member_record.candidate.candidate_id: member_record.evidence.substantive_content
            for member_record in records
        }
        if proposal.proposed_state is ReportabilityState.REPORTABLE:
            support_spans = tuple(
                _unique_quote_span(citation, bodies, event_id)
                for citation in proposal.support_citations
            )
            try:
                provenance = ReportabilityEvidenceProvenance(
                    examined_candidate_ids=request_ids,
                    support_spans=support_spans,
                    rationale=proposal.rationale,
                )
                return ReportabilityResult(
                    event_id=event_id,
                    reportability_state=ReportabilityState.REPORTABLE,
                    reportability_reason=None,
                    provenance=provenance,
                )
            except ReportabilityStageFailure:
                raise
            except (TypeError, ValueError):
                raise _technical("invalid reportability result", event_id) from None

        try:
            provenance = ReportabilityEvidenceProvenance(
                examined_candidate_ids=request_ids,
                support_spans=(),
                rationale=proposal.rationale,
            )
            return ReportabilityResult(
                event_id=event_id,
                reportability_state=ReportabilityState.NOT_REPORTABLE,
                reportability_reason=ReportabilityReason.LOW_REPORTABILITY_VALUE,
                provenance=provenance,
            )
        except ReportabilityStageFailure:
            raise
        except (TypeError, ValueError):
            raise _technical("invalid reportability result", event_id) from None

    def _evaluate_once(self, record: EventDecisionRecord, event_id: str) -> ReportabilityResult:
        record = self._validate_record(record)
        request = self._request(record)
        try:
            raw_proposal = self._proposal_provider(request)
        except Exception:
            failure = _technical("reportability semantic provider failed", event_id)
        else:
            try:
                proposal = _proposal(raw_proposal, event_id=event_id)
            except ReportabilityStageFailure:
                raise
            except Exception:
                raise _technical("malformed reportability proposal", event_id) from None
            return self._accept_proposal(proposal, request, tuple(record.member_records))
        # Raise after leaving the provider exception handler so the raw
        # provider exception is not retained as implicit __context__.
        raise failure

    def evaluate(self, record: EventDecisionRecord) -> ReportabilityResult:
        """Evaluate one reachable EventDecisionRecord without fallback or retry."""

        event_id = self._event_id(record)
        try:
            result = self._evaluate_once(record, event_id)
        except ReportabilityStageFailure as exc:
            reason = exc.reason
        except Exception:
            reason = "reportability stage failed"
        else:
            return result

        # Construct and raise outside the exception handler so the public
        # failure has no provider-controlled exception context or traceback.
        raise _technical(reason, event_id)
