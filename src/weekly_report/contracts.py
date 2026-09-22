"""Small immutable contracts for the V2 Evidence boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping


class EvidenceState(StrEnum):
    """The only terminal states owned by EvidenceService."""

    READY = "EVIDENCE_READY"
    REJECTED = "EVIDENCE_REJECTED"


@dataclass(frozen=True, slots=True)
class EventIdentityFacts:
    """Evidence-backed facts that may participate in event identity."""

    # Compatibility/debug corroboration only; Event Identity never treats
    # this field as proof of SAME_EVENT.
    event_key: str = ""
    action: str = ""
    lifecycle_step: str = ""
    subject: str = ""
    asset: str = ""
    project: str = ""
    package: str = ""
    location: str = ""
    occurrence_context: str = ""
    occurrence_date: str = ""
    non_identity_claims: Mapping[str, str] = field(default_factory=dict)
    evidence_references: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        claims = {
            str(key): str(value)
            for key, value in dict(self.non_identity_claims).items()
            if str(value).strip()
        }
        object.__setattr__(self, "non_identity_claims", MappingProxyType(claims))
        object.__setattr__(
            self,
            "evidence_references",
            tuple(str(value) for value in self.evidence_references if str(value)),
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "EventIdentityFacts":
        claims = value.get("non_identity_claims", {})
        references = value.get("evidence_references", ())
        return cls(
            event_key=str(value.get("event_key", "") or ""),
            action=str(value.get("action", "") or ""),
            lifecycle_step=str(value.get("lifecycle_step", "") or ""),
            subject=str(value.get("subject", "") or ""),
            asset=str(value.get("asset", "") or ""),
            project=str(value.get("project", "") or ""),
            package=str(value.get("package", "") or ""),
            location=str(value.get("location", "") or ""),
            occurrence_context=str(value.get("occurrence_context", "") or ""),
            occurrence_date=str(value.get("occurrence_date", "") or ""),
            non_identity_claims=claims if isinstance(claims, Mapping) else {},
            evidence_references=tuple(references or ()),
        )


class EventIdentityRelation(StrEnum):
    """Advisory pair relation; UNCERTAIN never becomes a group state."""

    SAME_EVENT = "SAME_EVENT"
    DISTINCT_EVENT = "DISTINCT_EVENT"
    UNCERTAIN = "UNCERTAIN"


@dataclass(frozen=True, slots=True)
class EventIdentitySupportSpan:
    candidate_id: str
    role: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class EventIdentitySemanticRequest:
    left_candidate_id: str
    right_candidate_id: str
    left_headline: str
    right_headline: str
    left_body: str
    right_body: str
    left_source_url: str
    right_source_url: str
    left_source_type: str
    right_source_type: str
    left_identity_facts: EventIdentityFacts | None = None
    right_identity_facts: EventIdentityFacts | None = None


@dataclass(frozen=True, slots=True)
class EventIdentitySemanticDecision:
    relation: EventIdentityRelation
    support_spans: tuple[EventIdentitySupportSpan, ...] = ()
    contradictions: tuple[str, ...] = ()
    missing_support: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EventIdentityRecord:
    """One candidate after Evidence, Scope, and Temporal have run."""

    candidate: "CanonicalCandidate"
    evidence: "EvidenceResult"
    scope: "ScopeResult"
    temporal: "TemporalResult"

    def __post_init__(self) -> None:
        candidate_id = self.candidate.candidate_id
        if not candidate_id:
            raise ValueError("EventIdentityRecord requires candidate_id")
        for value in (self.evidence, self.scope, self.temporal):
            if value.candidate_id != candidate_id:
                raise ValueError("all upstream results must use the candidate_id")

    @property
    def identity_facts(self) -> EventIdentityFacts | None:
        return self.evidence.identity_facts


@dataclass(frozen=True, slots=True)
class EventIdentityBasis:
    candidate_id: str
    supported_fields: tuple[str, ...]
    evidence_references: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class UnresolvedClaim:
    claim_key: str
    candidate_values: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class EventGroup:
    """Immutable post-decision group; source bodies are never merged here."""

    event_id: str
    member_candidate_ids: tuple[str, ...]
    canonical_candidate_id: str
    identity_basis: tuple[EventIdentityBasis, ...]
    unresolved_claims: tuple[UnresolvedClaim, ...] = ()

    def __post_init__(self) -> None:
        if not self.event_id:
            raise ValueError("EventGroup requires event_id")
        if tuple(sorted(set(self.member_candidate_ids))) != self.member_candidate_ids:
            raise ValueError("member_candidate_ids must be unique and sorted")
        if not self.member_candidate_ids:
            raise ValueError("EventGroup requires at least one member")
        if self.canonical_candidate_id not in self.member_candidate_ids:
            raise ValueError("canonical_candidate_id must belong to the group")


@dataclass(frozen=True, slots=True)
class EventIdentityDiagnostic:
    candidate_ids: tuple[str, ...]
    reason: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class EventIdentityRun:
    groups: tuple[EventGroup, ...]
    diagnostics: tuple[EventIdentityDiagnostic, ...] = ()


class RejectReason(StrEnum):
    """Reject vocabulary locked by the Architecture Contract."""

    URL_UNRESOLVED = "URL_UNRESOLVED"
    CONTENT_UNAVAILABLE = "CONTENT_UNAVAILABLE"
    SOURCE_PAGE_MISMATCH = "SOURCE_PAGE_MISMATCH"
    TITLE_ONLY = "TITLE_ONLY"
    INSUFFICIENT_SUBSTANCE = "INSUFFICIENT_SUBSTANCE"
    UNTRUSTWORTHY_SOURCE = "UNTRUSTWORTHY_SOURCE"


class ScopeState(StrEnum):
    """The only authoritative terminal outcomes owned by ScopeClassifier."""

    IN_SCOPE = "IN_SCOPE"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


class ScopeDiagnostic(StrEnum):
    """Non-authoritative explanations for a Scope decision."""

    NONE = "NONE"
    EXCLUDED_TRANSPORT_MODE = "EXCLUDED_TRANSPORT_MODE"
    NON_URBAN_RAIL = "NON_URBAN_RAIL"
    SCOPE_NOT_ESTABLISHED = "SCOPE_NOT_ESTABLISHED"


class SourceDateKind(StrEnum):
    """Factual date concepts observed on an established source document."""

    ORIGINAL_PUBLICATION = "ORIGINAL_PUBLICATION"
    NOTICE_ISSUED = "NOTICE_ISSUED"
    NOTICE_PUBLISHED = "NOTICE_PUBLISHED"
    MODIFIED = "MODIFIED"
    EVENT_DATE = "EVENT_DATE"
    DEADLINE = "DEADLINE"
    OTHER = "OTHER"


@dataclass(frozen=True, slots=True)
class SourceDateFact:
    """Immutable source-associated date observation.

    This object records facts only. It does not identify the controlling date
    or decide report-period eligibility.
    """

    raw_date_value: str
    date_kind: SourceDateKind | str
    principal_document_association: str
    source_node_or_field_provenance: str
    explicit_timezone_or_offset: str | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SourceDateFact":
        """Create a fact from the fixed Golden/source boundary shape."""

        return cls(
            raw_date_value=str(value.get("raw_date_value", "") or ""),
            date_kind=value.get("date_kind", ""),
            principal_document_association=str(
                value.get("principal_document_association", "") or ""
            ),
            source_node_or_field_provenance=str(
                value.get("source_node_or_field_provenance", "") or ""
            ),
            explicit_timezone_or_offset=value.get("explicit_timezone_or_offset"),
        )


@dataclass(frozen=True, slots=True)
class ScopeResult:
    """Immutable authoritative result returned by ScopeClassifier."""

    candidate_id: str
    state: ScopeState
    diagnostic: ScopeDiagnostic = ScopeDiagnostic.NONE
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.state not in {ScopeState.IN_SCOPE, ScopeState.OUT_OF_SCOPE}:
            raise ValueError("ScopeResult requires an authoritative ScopeState")
        if self.state is ScopeState.IN_SCOPE and self.diagnostic is not ScopeDiagnostic.NONE:
            raise ValueError("IN_SCOPE cannot carry an exclusion diagnostic")


class TemporalDiagnostic(StrEnum):
    """Non-authoritative explanations for a Temporal decision."""

    NONE = "NONE"
    OUT_OF_RANGE = "OUT_OF_RANGE"
    DATE_MISSING = "DATE_MISSING"
    DATE_UNPARSEABLE = "DATE_UNPARSEABLE"
    DATE_CONFLICT = "DATE_CONFLICT"
    DATE_PROVENANCE_INVALID = "DATE_PROVENANCE_INVALID"


@dataclass(frozen=True, slots=True)
class TemporalResult:
    """Immutable authoritative result returned by TemporalRule."""

    candidate_id: str
    date_valid: bool
    diagnostic: TemporalDiagnostic = TemporalDiagnostic.NONE
    controlling_calendar_date: date | None = None
    controlling_date_kind: SourceDateKind | None = None
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.date_valid and self.diagnostic is not TemporalDiagnostic.NONE:
            raise ValueError("DATE_VALID cannot carry a failure diagnostic")
        if not self.date_valid and self.diagnostic is TemporalDiagnostic.NONE:
            raise ValueError("Invalid date requires a Temporal diagnostic")


@dataclass(frozen=True, slots=True)
class CanonicalCandidate:
    """The minimum candidate input required before Evidence acquisition."""

    candidate_id: str
    title: str
    url: str
    publisher: str = ""
    published_at: str = ""
    discovery_intent: str = ""
    search_snippet: str = ""
    source_type: str = "web_source"

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CanonicalCandidate":
        """Create a candidate without retaining unrelated upstream fields."""

        return cls(
            candidate_id=str(value.get("candidate_id", "")),
            title=str(value.get("title", "")),
            url=str(value.get("url", "")),
            publisher=str(value.get("publisher", "")),
            published_at=str(value.get("published_at", "")),
            discovery_intent=str(value.get("discovery_intent", "")),
            search_snippet=str(value.get("search_snippet", "")),
            source_type=str(value.get("source_type", "web_source")),
        )


@dataclass(frozen=True, slots=True)
class FetchedSource:
    """Transport output consumed by EvidenceService.

    Transport reports what it obtained. It does not decide whether the
    content is authoritative evidence.
    """

    url: str
    content: str
    status_code: int = 200
    content_type: str = "text/html"
    redirect_chain: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EvidenceResult:
    """Authoritative EvidenceService output."""

    candidate_id: str
    state: EvidenceState
    canonical_source_url: str = ""
    source_type: str = ""
    substantive_content: str = ""
    provenance: Mapping[str, Any] = field(default_factory=dict)
    reject_reason: RejectReason | None = None
    source_date_facts: tuple[SourceDateFact, ...] = ()
    identity_facts: EventIdentityFacts | None = None

    def __post_init__(self) -> None:
        facts: list[SourceDateFact] = []
        for fact in self.source_date_facts:
            if isinstance(fact, SourceDateFact):
                facts.append(fact)
            elif isinstance(fact, Mapping):
                facts.append(SourceDateFact.from_mapping(fact))
            else:
                raise TypeError("source_date_facts must contain SourceDateFact values")
        object.__setattr__(self, "source_date_facts", tuple(facts))
        if isinstance(self.identity_facts, Mapping):
            object.__setattr__(
                self,
                "identity_facts",
                EventIdentityFacts.from_mapping(self.identity_facts),
            )
        elif self.identity_facts is not None and not isinstance(
            self.identity_facts, EventIdentityFacts
        ):
            raise TypeError("identity_facts must contain EventIdentityFacts values")
        if self.state is EvidenceState.READY and self.reject_reason is not None:
            raise ValueError("EVIDENCE_READY cannot carry a reject reason")
        if self.state is EvidenceState.REJECTED and self.reject_reason is None:
            raise ValueError("EVIDENCE_REJECTED requires a reject reason")
        if self.state is EvidenceState.READY and not self.substantive_content.strip():
            raise ValueError("EVIDENCE_READY requires substantive_content")
        if self.state is EvidenceState.REJECTED and self.substantive_content:
            raise ValueError("Rejected evidence cannot expose authoritative content")
