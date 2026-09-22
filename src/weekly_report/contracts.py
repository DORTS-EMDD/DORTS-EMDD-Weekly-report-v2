"""Small immutable contracts for the V2 Evidence boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any, Mapping


class EvidenceState(StrEnum):
    """The only terminal states owned by EvidenceService."""

    READY = "EVIDENCE_READY"
    REJECTED = "EVIDENCE_REJECTED"


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
        if self.state is EvidenceState.READY and self.reject_reason is not None:
            raise ValueError("EVIDENCE_READY cannot carry a reject reason")
        if self.state is EvidenceState.REJECTED and self.reject_reason is None:
            raise ValueError("EVIDENCE_REJECTED requires a reject reason")
        if self.state is EvidenceState.READY and not self.substantive_content.strip():
            raise ValueError("EVIDENCE_READY requires substantive_content")
        if self.state is EvidenceState.REJECTED and self.substantive_content:
            raise ValueError("Rejected evidence cannot expose authoritative content")
