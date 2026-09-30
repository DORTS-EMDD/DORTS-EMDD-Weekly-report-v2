"""Authoritative V2 E&M Taxonomy owner.

The owner accepts one narrow, proposal-only semantic provider.  The provider
never owns reachability or the final taxonomy decision; this module validates
the proposal against the sealed EventGroup/evidence boundary and constructs
the existing typed :class:`TaxonomyResult`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from .contracts import (
    CategoryResult,
    CategoryState,
    EMSystemId,
    EvidenceState,
    EventGroup,
    EventIdentityRecord,
    ScopeState,
    TaxonomyConflictEvidenceProvenance,
    TaxonomyInsufficientEvidenceProvenance,
    TaxonomyResolutionReason,
    TaxonomyResult,
    TaxonomyState,
    TaxonomySupportSpan,
    canonical_em_system_ids,
)


@dataclass(frozen=True, slots=True)
class TaxonomySemanticMember:
    """One authoritative EventGroup member exposed to the provider."""

    candidate_id: str
    substantive_content: str

    def __post_init__(self) -> None:
        if not isinstance(self.candidate_id, str) or not self.candidate_id.strip():
            raise ValueError("taxonomy provider member requires candidate_id")
        if not isinstance(self.substantive_content, str) or not self.substantive_content.strip():
            raise ValueError("taxonomy provider member requires substantive_content")

    def as_mapping(self) -> dict[str, str]:
        return {
            "candidate_id": self.candidate_id,
            "substantive_content": self.substantive_content,
        }


@dataclass(frozen=True, slots=True)
class TaxonomySemanticRequest:
    """Immutable, bounded proposal-provider input.

    Category values, discovery metadata, expected outcomes and any other
    upstream fields are deliberately absent.
    """

    event_id: str
    members: tuple[TaxonomySemanticMember, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.event_id, str) or not self.event_id.strip():
            raise ValueError("taxonomy provider request requires event_id")
        members = tuple(self.members)
        if not members:
            raise ValueError("taxonomy provider request requires members")
        if any(not isinstance(member, TaxonomySemanticMember) for member in members):
            raise TypeError("taxonomy provider request members must be typed values")
        ids = tuple(member.candidate_id for member in members)
        if len(ids) != len(set(ids)):
            raise ValueError("taxonomy provider request requires unique candidate IDs")
        if ids != tuple(sorted(ids)):
            raise ValueError("taxonomy provider request members must be lexical candidate order")
        object.__setattr__(self, "members", members)

    @property
    def member_candidate_ids(self) -> tuple[str, ...]:
        return tuple(member.candidate_id for member in self.members)

    def as_payload(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "members": [member.as_mapping() for member in self.members],
        }


@dataclass(frozen=True, slots=True)
class TaxonomySemanticCitation:
    """Untrusted exact quote citation returned by a semantic provider."""

    system_id: EMSystemId | str
    candidate_id: str
    exact_quote: str


@dataclass(frozen=True, slots=True)
class TaxonomySemanticProposal:
    """The complete untrusted proposal accepted by the owner seam."""

    event_id: str
    taxonomy_state: TaxonomyState | str
    systems: tuple[EMSystemId | str, ...] = ()
    taxonomy_resolution_reason: TaxonomyResolutionReason | str | None = None
    support_citations: tuple[TaxonomySemanticCitation, ...] = ()
    conflict_citations: tuple[TaxonomySemanticCitation, ...] = ()
    insufficient_provenance: TaxonomyInsufficientEvidenceProvenance | Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "systems", tuple(self.systems))
        object.__setattr__(self, "support_citations", tuple(self.support_citations))
        object.__setattr__(self, "conflict_citations", tuple(self.conflict_citations))


class TaxonomySemanticProposalProvider(Protocol):
    """Narrow proposal-only semantic provider interface."""

    def __call__(self, request: TaxonomySemanticRequest) -> object:
        """Return one untrusted semantic proposal for the bounded request."""


class TaxonomyStageFailure(RuntimeError):
    """Typed technical failure; no :class:`TaxonomyResult` exists on failure."""

    def __init__(self, reason: str, *, event_id: str = "") -> None:
        if not isinstance(reason, str) or not reason.strip():
            reason = "taxonomy stage failed"
        self.reason = reason
        self.event_id = event_id
        super().__init__(reason)


EXACT_TEXT_UNIQUE_RESOLUTION = "EXACT_TEXT_UNIQUE_RESOLUTION"


_PROPOSAL_FIELDS = frozenset(
    {
        "event_id",
        "taxonomy_state",
        "systems",
        "taxonomy_resolution_reason",
        "support_citations",
        "conflict_citations",
        "insufficient_provenance",
    }
)
_CITATION_FIELDS = frozenset({"system_id", "candidate_id", "exact_quote"})
_INSUFFICIENT_FIELDS = frozenset({"member_candidate_ids", "diagnostic"})


def _technical(reason: str, event_id: str = "") -> TaxonomyStageFailure:
    return TaxonomyStageFailure(reason, event_id=event_id)


def _citation(value: object) -> TaxonomySemanticCitation:
    if isinstance(value, TaxonomySemanticCitation):
        return value
    if not isinstance(value, Mapping) or frozenset(value) != _CITATION_FIELDS:
        raise _technical("taxonomy citation fields do not match the proposal contract")
    return TaxonomySemanticCitation(
        system_id=value["system_id"],
        candidate_id=value["candidate_id"],
        exact_quote=value["exact_quote"],
    )


def _citations(value: object, field_name: str) -> tuple[TaxonomySemanticCitation, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise _technical(f"{field_name} must be an array")
    return tuple(_citation(item) for item in value)


def _insufficient_provenance(value: object) -> TaxonomyInsufficientEvidenceProvenance | None:
    if value is None:
        return None
    if isinstance(value, TaxonomyInsufficientEvidenceProvenance):
        return value
    if not isinstance(value, Mapping) or frozenset(value) != _INSUFFICIENT_FIELDS:
        raise _technical("insufficient provenance fields do not match the proposal contract")
    member_ids = value["member_candidate_ids"]
    diagnostic = value["diagnostic"]
    if not isinstance(member_ids, Sequence) or isinstance(member_ids, (str, bytes, bytearray)):
        raise _technical("insufficient provenance member_candidate_ids must be an array")
    try:
        return TaxonomyInsufficientEvidenceProvenance(tuple(member_ids), diagnostic)
    except (TypeError, ValueError):
        raise _technical("invalid insufficient taxonomy provenance") from None


def _proposal(value: object, *, event_id: str) -> TaxonomySemanticProposal:
    if isinstance(value, TaxonomySemanticProposal):
        try:
            # Re-read even typed proposals through the same strict boundary so
            # fake providers cannot smuggle mutable or mapping citations past
            # owner validation.
            proposal = TaxonomySemanticProposal(
                event_id=value.event_id,
                taxonomy_state=value.taxonomy_state,
                systems=tuple(value.systems),
                taxonomy_resolution_reason=value.taxonomy_resolution_reason,
                support_citations=tuple(_citation(item) for item in value.support_citations),
                conflict_citations=tuple(_citation(item) for item in value.conflict_citations),
                insufficient_provenance=_insufficient_provenance(value.insufficient_provenance),
            )
        except (TaxonomyStageFailure, TypeError, ValueError):
            raise _technical("malformed taxonomy proposal", event_id) from None
    else:
        if not isinstance(value, Mapping):
            raise _technical("taxonomy proposal fields do not match the proposal contract", event_id)
        try:
            proposal_fields = frozenset(value)
            fields_match = proposal_fields == _PROPOSAL_FIELDS
        except (TaxonomyStageFailure, TypeError, ValueError):
            raise _technical("malformed taxonomy proposal", event_id) from None
        if not fields_match:
            raise _technical("taxonomy proposal fields do not match the proposal contract", event_id)
        try:
            proposal = TaxonomySemanticProposal(
                event_id=value["event_id"],
                taxonomy_state=value["taxonomy_state"],
                systems=tuple(value["systems"]),
                taxonomy_resolution_reason=value["taxonomy_resolution_reason"],
                support_citations=_citations(value["support_citations"], "support_citations"),
                conflict_citations=_citations(value["conflict_citations"], "conflict_citations"),
                insufficient_provenance=_insufficient_provenance(value["insufficient_provenance"]),
            )
        except (TaxonomyStageFailure, TypeError, ValueError):
            raise _technical("malformed taxonomy proposal", event_id) from None

    if proposal.event_id != event_id:
        raise _technical("taxonomy proposal event_id does not match EventGroup", event_id)
    return proposal


def _parse_state(value: object, event_id: str) -> TaxonomyState:
    try:
        state = TaxonomyState(value)
    except (TypeError, ValueError) as exc:
        raise _technical("taxonomy proposal has an invalid state", event_id) from exc
    if state is TaxonomyState.NOT_EVALUATED:
        raise _technical("provider may not propose NOT_EVALUATED", event_id)
    return state


def _parse_reason(value: object, event_id: str) -> TaxonomyResolutionReason:
    try:
        return TaxonomyResolutionReason(value)
    except (TypeError, ValueError) as exc:
        raise _technical("taxonomy proposal has an invalid unresolved reason", event_id) from exc


def _parse_systems(value: object, event_id: str) -> tuple[EMSystemId, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise _technical("taxonomy proposal systems must be an array", event_id)
    output: list[EMSystemId] = []
    for raw_system in value:
        try:
            system = EMSystemId(raw_system)
        except (TypeError, ValueError) as exc:
            raise _technical("taxonomy proposal contains an invalid system ID", event_id) from exc
        if system in output:
            raise _technical("taxonomy proposal systems contain duplicates", event_id)
        output.append(system)
    canonical = tuple(system for system in canonical_em_system_ids() if system in output)
    return canonical


def _unique_quote_span(
    citation: TaxonomySemanticCitation,
    bodies: Mapping[str, str],
    event_id: str,
) -> TaxonomySupportSpan:
    if not isinstance(citation.candidate_id, str) or not citation.candidate_id.strip():
        raise _technical("taxonomy citation requires candidate_id", event_id)
    if citation.candidate_id not in bodies:
        raise _technical("taxonomy citation references a non-member candidate", event_id)
    if not isinstance(citation.exact_quote, str) or not citation.exact_quote:
        raise _technical("taxonomy citation requires a non-empty exact_quote", event_id)
    if not isinstance(citation.system_id, (str, EMSystemId)):
        raise _technical("taxonomy citation has an invalid system ID", event_id)
    try:
        system = EMSystemId(citation.system_id)
    except (TypeError, ValueError) as exc:
        raise _technical("taxonomy citation has an invalid system ID", event_id) from exc

    body = bodies[citation.candidate_id]
    start = body.find(citation.exact_quote)
    if start < 0:
        raise _technical("taxonomy citation exact_quote was not found", event_id)
    second = body.find(citation.exact_quote, start + 1)
    if second >= 0:
        raise _technical("taxonomy citation exact_quote is ambiguous", event_id)
    end = start + len(citation.exact_quote)
    if start < 0 or end <= start or end > len(body) or body[start:end] != citation.exact_quote:
        raise _technical("taxonomy citation span does not exactly map to source content", event_id)
    return TaxonomySupportSpan(system, citation.candidate_id, start, end)


def _canonical_span_order(span: TaxonomySupportSpan) -> tuple[int, str, int, int]:
    return (canonical_em_system_ids().index(span.system_id), span.candidate_id, span.start, span.end)


class Taxonomy:
    """Sole authoritative owner for one EventGroup's E&M Taxonomy result."""

    CONTRACT_VERSION = "em-taxonomy-v1"

    def __init__(
        self,
        proposal_provider: TaxonomySemanticProposalProvider | None = None,
        *,
        provider: TaxonomySemanticProposalProvider | None = None,
    ) -> None:
        if proposal_provider is not None and provider is not None:
            raise TypeError("provide only one taxonomy semantic provider")
        self._proposal_provider = proposal_provider if proposal_provider is not None else provider

    def evaluate(
        self,
        event_group: EventGroup,
        records: Sequence[EventIdentityRecord],
        category_result: CategoryResult,
    ) -> TaxonomyResult:
        """Evaluate one post-dedup EventGroup without fallback or retry."""

        try:
            self._validate_category_boundary(event_group, category_result)
            if category_result.category_state is not CategoryState.CATEGORY_ASSIGNED:
                return TaxonomyResult.not_evaluated(event_id=event_group.event_id)

            ordered_records = self._validate_upstream(event_group, records)
            if self._proposal_provider is None:
                raise _technical("taxonomy semantic proposal provider is unavailable", event_group.event_id)

            request = TaxonomySemanticRequest(
                event_id=event_group.event_id,
                members=tuple(
                    TaxonomySemanticMember(
                        record.candidate.candidate_id,
                        record.evidence.substantive_content,
                    )
                    for record in ordered_records
                ),
            )
            try:
                raw_proposal = self._proposal_provider(request)
            except Exception as exc:
                failure = _technical(
                    f"taxonomy semantic provider failed: {type(exc).__name__}",
                    event_group.event_id,
                )
            else:
                try:
                    proposal = _proposal(raw_proposal, event_id=event_group.event_id)
                except TaxonomyStageFailure:
                    raise
                except Exception:
                    raise _technical("malformed taxonomy proposal", event_group.event_id) from None
                return self._accept_proposal(proposal, event_group, ordered_records)
            # Raise after leaving the provider exception handler so the raw
            # provider exception is not retained as implicit __context__.
            raise failure
        except TaxonomyStageFailure as exc:
            if not isinstance(event_group, EventGroup):
                raise
            failure = _technical(exc.reason, event_group.event_id)
        raise failure from None

    classify = evaluate
    run = evaluate

    @staticmethod
    def _validate_category_boundary(event_group: EventGroup, category_result: CategoryResult) -> None:
        if not isinstance(event_group, EventGroup):
            raise _technical("taxonomy requires an EventGroup")
        if not isinstance(category_result, CategoryResult):
            raise _technical("taxonomy requires a typed CategoryResult", event_group.event_id)
        if category_result.event_id != event_group.event_id:
            raise _technical("CategoryResult event_id does not match EventGroup", event_group.event_id)

    @staticmethod
    def _validate_upstream(
        event_group: EventGroup,
        records: Sequence[EventIdentityRecord],
    ) -> tuple[EventIdentityRecord, ...]:
        if not isinstance(records, Sequence) or isinstance(records, (str, bytes, bytearray)):
            raise _technical("taxonomy records must be a sequence", event_group.event_id)
        by_id: dict[str, EventIdentityRecord] = {}
        for record in records:
            if not isinstance(record, EventIdentityRecord):
                raise _technical("taxonomy records must contain EventIdentityRecord values", event_group.event_id)
            candidate_id = record.candidate.candidate_id
            if candidate_id in by_id:
                raise _technical("taxonomy records contain duplicate candidate IDs", event_group.event_id)
            by_id[candidate_id] = record
        expected = set(event_group.member_candidate_ids)
        if set(by_id) != expected:
            raise _technical("taxonomy records must match EventGroup members exactly", event_group.event_id)
        for candidate_id in event_group.member_candidate_ids:
            record = by_id[candidate_id]
            if record.evidence.state is not EvidenceState.READY:
                raise _technical("taxonomy requires EVIDENCE_READY members", event_group.event_id)
            if record.scope.state is not ScopeState.IN_SCOPE:
                raise _technical("taxonomy requires IN_SCOPE members", event_group.event_id)
            if not record.temporal.date_valid:
                raise _technical("taxonomy requires DATE_VALID members", event_group.event_id)
        return tuple(by_id[candidate_id] for candidate_id in sorted(by_id))

    def _accept_proposal(
        self,
        proposal: TaxonomySemanticProposal,
        event_group: EventGroup,
        records: tuple[EventIdentityRecord, ...],
    ) -> TaxonomyResult:
        state = _parse_state(proposal.taxonomy_state, event_group.event_id)
        systems = _parse_systems(proposal.systems, event_group.event_id)
        bodies = {record.candidate.candidate_id: record.evidence.substantive_content for record in records}
        support = tuple(
            _unique_quote_span(citation, bodies, event_group.event_id)
            for citation in proposal.support_citations
        )
        conflict = tuple(
            _unique_quote_span(citation, bodies, event_group.event_id)
            for citation in proposal.conflict_citations
        )
        support = tuple(sorted(support, key=_canonical_span_order))
        conflict = tuple(sorted(conflict, key=_canonical_span_order))

        if state is TaxonomyState.TAXONOMY_EVALUATED:
            if proposal.taxonomy_resolution_reason is not None:
                raise _technical("evaluated taxonomy proposal cannot carry a reason", event_group.event_id)
            if proposal.insufficient_provenance is not None or conflict:
                raise _technical("evaluated taxonomy proposal carries unresolved provenance", event_group.event_id)
            assigned = set(systems)
            support_systems = {span.system_id for span in support}
            if not support_systems.issubset(assigned):
                raise _technical("taxonomy support refers to an unassigned system", event_group.event_id)
            if assigned and support_systems != assigned:
                raise _technical("every assigned taxonomy system requires support", event_group.event_id)
            if not assigned and support:
                raise _technical("evaluated empty taxonomy cannot carry support", event_group.event_id)
            return TaxonomyResult(
                taxonomy_state=state,
                event_id=event_group.event_id,
                systems=systems,
                support_spans=support,
            )

        if systems or support:
            raise _technical("unresolved taxonomy proposal requires empty systems and support", event_group.event_id)
        if proposal.taxonomy_resolution_reason is None:
            raise _technical("unresolved taxonomy proposal requires a reason", event_group.event_id)
        reason = _parse_reason(proposal.taxonomy_resolution_reason, event_group.event_id)
        if reason is TaxonomyResolutionReason.INSUFFICIENT_SYSTEM_EVIDENCE:
            if conflict or proposal.insufficient_provenance is None:
                raise _technical("insufficient taxonomy proposal requires insufficient provenance only", event_group.event_id)
            provenance = proposal.insufficient_provenance
            if not isinstance(provenance, TaxonomyInsufficientEvidenceProvenance):
                raise _technical("invalid insufficient taxonomy provenance", event_group.event_id)
            if tuple(provenance.member_candidate_ids) != event_group.member_candidate_ids:
                raise _technical("insufficient provenance must identify exactly all EventGroup members", event_group.event_id)
            return TaxonomyResult(
                taxonomy_state=state,
                event_id=event_group.event_id,
                taxonomy_resolution_reason=reason,
                provenance=provenance,
            )

        if proposal.insufficient_provenance is not None or len({span.system_id for span in conflict}) < 2:
            raise _technical("conflicting taxonomy proposal requires two competing system hypotheses", event_group.event_id)
        return TaxonomyResult(
            taxonomy_state=state,
            event_id=event_group.event_id,
            taxonomy_resolution_reason=reason,
            provenance=TaxonomyConflictEvidenceProvenance(conflict),
        )


EMTaxonomy = Taxonomy
TaxonomyOwner = Taxonomy


__all__ = [
    "EXACT_TEXT_UNIQUE_RESOLUTION",
    "EMTaxonomy",
    "Taxonomy",
    "TaxonomyOwner",
    "TaxonomySemanticCitation",
    "TaxonomySemanticMember",
    "TaxonomySemanticProposal",
    "TaxonomySemanticProposalProvider",
    "TaxonomySemanticRequest",
    "TaxonomyStageFailure",
]
