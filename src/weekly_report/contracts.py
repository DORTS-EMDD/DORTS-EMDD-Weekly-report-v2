"""Small immutable contracts for the V2 Evidence boundary."""

from __future__ import annotations

import re
import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Literal, Mapping, Protocol, runtime_checkable


class EvidenceState(StrEnum):
    """The only terminal states owned by EvidenceService."""

    READY = "EVIDENCE_READY"
    REJECTED = "EVIDENCE_REJECTED"


class CategoryState(StrEnum):
    """Classifier output state; NOT_EVALUATED means the owner was not invoked."""

    NOT_EVALUATED = "NOT_EVALUATED"
    CATEGORY_ASSIGNED = "CATEGORY_ASSIGNED"
    CATEGORY_UNRESOLVED = "CATEGORY_UNRESOLVED"


class CategoryId(StrEnum):
    """The canonical primary Category IDs locked by Architecture Contract §L."""

    TECHNICAL_DEVELOPMENT = "TECHNICAL_DEVELOPMENT"
    INCIDENT = "INCIDENT"
    OPERATIONAL_CHANGE = "OPERATIONAL_CHANGE"
    PROCUREMENT = "PROCUREMENT"
    NORMATIVE_CHANGE = "NORMATIVE_CHANGE"

    @property
    def display_label(self) -> str:
        return _CATEGORY_DISPLAY_LABELS[self]


_CATEGORY_DISPLAY_LABELS = MappingProxyType(
    {
        CategoryId.TECHNICAL_DEVELOPMENT: "技術新知",
        CategoryId.INCIDENT: "事故事件",
        CategoryId.OPERATIONAL_CHANGE: "營運動態",
        CategoryId.PROCUREMENT: "採購事件",
        CategoryId.NORMATIVE_CHANGE: "規範變動",
    }
)


class CategoryResolutionReason(StrEnum):
    """Why one Event Group did not receive a unique primary Category."""

    NO_CATEGORY_DEFINING_ACTION = "NO_CATEGORY_DEFINING_ACTION"
    RECOMMENDATION_WITHOUT_ADOPTED_ACTION = "RECOMMENDATION_WITHOUT_ADOPTED_ACTION"
    CONFLICTING_CATEGORY_DEFINING_CLAIMS = "CONFLICTING_CATEGORY_DEFINING_CLAIMS"
    NO_UNIQUE_PRINCIPAL_ACTION = "NO_UNIQUE_PRINCIPAL_ACTION"
    INSUFFICIENT_CATEGORY_EVIDENCE = "INSUFFICIENT_CATEGORY_EVIDENCE"
    SEMANTIC_HELPER_UNAVAILABLE = "SEMANTIC_HELPER_UNAVAILABLE"
    SEMANTIC_HELPER_FAILURE = "SEMANTIC_HELPER_FAILURE"
    SEMANTIC_HELPER_INVALID_RESPONSE = "SEMANTIC_HELPER_INVALID_RESPONSE"


@dataclass(frozen=True, slots=True)
class IdentityMetadataSupport:
    """Exact source-content support for one formal identity metadata value."""

    field_name: Literal["country", "transit_system_name", "location"]
    start: int
    end: int

    def __post_init__(self) -> None:
        if not isinstance(self.field_name, str) or self.field_name not in {
            "country",
            "transit_system_name",
            "location",
        }:
            raise ValueError("unsupported metadata support field")
        if (
            isinstance(self.start, bool)
            or not isinstance(self.start, int)
            or isinstance(self.end, bool)
            or not isinstance(self.end, int)
        ):
            raise TypeError("metadata support offsets must be integers")
        if self.start < 0 or self.start >= self.end:
            raise ValueError("metadata support offsets must satisfy 0 <= start < end")


def _coerce_metadata_support(
    value: object,
) -> tuple[IdentityMetadataSupport, ...]:
    if value is None:
        raise TypeError("metadata_support must be a sequence")
    if isinstance(value, (str, bytes, bytearray, Mapping)):
        raise TypeError("metadata_support must be a sequence")
    try:
        entries = tuple(value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise TypeError("metadata_support must be a sequence") from exc
    output: list[IdentityMetadataSupport] = []
    for entry in entries:
        if isinstance(entry, IdentityMetadataSupport):
            output.append(entry)
        elif isinstance(entry, Mapping):
            if set(entry) != {"field_name", "start", "end"}:
                raise ValueError("metadata support mapping fields do not match schema")
            output.append(
                IdentityMetadataSupport(
                    field_name=entry["field_name"],
                    start=entry["start"],
                    end=entry["end"],
                )
            )
        else:
            raise TypeError("metadata_support must contain IdentityMetadataSupport values")
    return tuple(output)


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
    country: str | None = None
    transit_system_name: str | None = None
    metadata_support: tuple[IdentityMetadataSupport, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("country", "transit_system_name"):
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, str):
                raise TypeError(f"{field_name} must be a string or None")
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
        object.__setattr__(self, "metadata_support", _coerce_metadata_support(self.metadata_support))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "EventIdentityFacts":
        claims = value.get("non_identity_claims", {})
        references = value.get("evidence_references", ())
        support = value.get("metadata_support", ())
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
            country=value.get("country"),
            transit_system_name=value.get("transit_system_name"),
            metadata_support=support,
        )


def _validate_evidence_identity_metadata(
    substantive_content: str,
    facts: EventIdentityFacts | None,
    state: EvidenceState,
) -> None:
    if facts is None:
        return
    values = {
        "country": facts.country,
        "transit_system_name": facts.transit_system_name,
        "location": facts.location,
    }
    if state is EvidenceState.REJECTED:
        if (
            facts.country not in (None, "")
            or facts.transit_system_name not in (None, "")
            or facts.metadata_support
        ):
            raise ValueError("EVIDENCE_REJECTED cannot expose formal identity metadata")
        return

    supported_fields: set[str] = set()
    content_length = len(substantive_content)
    for support in facts.metadata_support:
        value = values[support.field_name]
        if not isinstance(value, str) or not value:
            raise ValueError("metadata support requires a non-empty governed value")
        if support.end > content_length:
            raise ValueError("metadata support exceeds substantive_content")
        slice_value = substantive_content[support.start : support.end]
        if not slice_value.strip():
            raise ValueError("metadata support must refer to nonblank content")
        if value not in slice_value:
            raise ValueError("metadata support does not contain its governed value")
        supported_fields.add(support.field_name)
    for field_name, value in values.items():
        if value not in (None, "") and field_name not in supported_fields:
            raise ValueError(f"{field_name} requires matching metadata support")


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
        if type(self.date_valid) is not bool:
            raise TypeError("TemporalResult date_valid must be a bool")
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
        _validate_evidence_identity_metadata(
            self.substantive_content,
            self.identity_facts,
            self.state,
        )


@dataclass(frozen=True, slots=True)
class CategoryResult:
    """Immutable authoritative Category outcome for one Event Group.

    Reportability and downstream workflow state intentionally do not belong
    to this result. An unresolved Category is terminal for the Event Group.
    """

    category_state: CategoryState
    event_id: str = ""
    primary_category_id: CategoryId | None = None
    primary_category: str | None = None
    subtype: str | None = None
    classification_reason: str | None = None
    category_resolution_reason: CategoryResolutionReason | None = None
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        try:
            state = CategoryState(self.category_state)
        except ValueError as exc:
            raise ValueError("CategoryResult requires a valid CategoryState") from exc
        object.__setattr__(self, "category_state", state)

        category_id = self.primary_category_id
        if category_id is not None:
            try:
                category_id = CategoryId(category_id)
            except ValueError as exc:
                raise ValueError("primary_category_id is not a canonical CategoryId") from exc
            object.__setattr__(self, "primary_category_id", category_id)

        resolution_reason = self.category_resolution_reason
        if resolution_reason is not None:
            try:
                resolution_reason = CategoryResolutionReason(resolution_reason)
            except ValueError as exc:
                raise ValueError("category_resolution_reason is not a valid reason") from exc
            object.__setattr__(self, "category_resolution_reason", resolution_reason)

        if not isinstance(self.provenance, Mapping):
            raise TypeError("CategoryResult provenance must be a mapping")
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))

        if state is CategoryState.CATEGORY_ASSIGNED:
            if not self.event_id.strip():
                raise ValueError("CATEGORY_ASSIGNED requires event_id")
            if category_id is None:
                raise ValueError("CATEGORY_ASSIGNED requires primary_category_id")
            if self.primary_category != category_id.display_label:
                raise ValueError("primary_category must match the canonical display label")
            if self.subtype is not None and (
                not isinstance(self.subtype, str)
                or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", self.subtype)
            ):
                raise ValueError(
                    "CATEGORY_ASSIGNED subtype must be snake_case when present"
                )
            if self.classification_reason != f"PRINCIPAL_ACTION_{category_id.value}":
                raise ValueError("classification_reason must identify the principal action")
            if resolution_reason is not None:
                raise ValueError("CATEGORY_ASSIGNED cannot carry a resolution reason")
        elif state is CategoryState.CATEGORY_UNRESOLVED:
            if not self.event_id.strip():
                raise ValueError("CATEGORY_UNRESOLVED requires event_id")
            if any(
                value is not None
                for value in (
                    category_id,
                    self.primary_category,
                    self.subtype,
                )
            ):
                raise ValueError("CATEGORY_UNRESOLVED cannot expose an assigned Category")
            if self.classification_reason != CategoryState.CATEGORY_UNRESOLVED.value:
                raise ValueError("CATEGORY_UNRESOLVED requires its terminal classification reason")
            if resolution_reason is None:
                raise ValueError("CATEGORY_UNRESOLVED requires a meaningful reason")
        else:
            if any(
                value is not None
                for value in (
                    category_id,
                    self.primary_category,
                    self.subtype,
                    self.classification_reason,
                    resolution_reason,
                )
            ):
                raise ValueError("NOT_EVALUATED cannot carry a Classifier decision")

    @classmethod
    def not_evaluated(
        cls,
        *,
        event_id: str = "",
        provenance: Mapping[str, Any] | None = None,
    ) -> "CategoryResult":
        """Represent an upstream stop without claiming a Classifier decision."""

        return cls(
            category_state=CategoryState.NOT_EVALUATED,
            event_id=event_id,
            provenance=provenance or {},
        )

    def as_mapping(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "category_state": self.category_state.value,
            "primary_category_id": (
                self.primary_category_id.value if self.primary_category_id else None
            ),
            "primary_category": self.primary_category,
            "subtype": self.subtype,
            "classification_reason": self.classification_reason,
            "category_resolution_reason": (
                self.category_resolution_reason.value
                if self.category_resolution_reason
                else None
            ),
            "provenance": dict(self.provenance),
        }


class EMSystemId(StrEnum):
    """Canonical machine IDs owned by the E&M Taxonomy stage."""

    ROLLING_STOCK = "ROLLING_STOCK"
    SIGNALLING = "SIGNALLING"
    POWER_SUPPLY = "POWER_SUPPLY"
    COMMUNICATIONS = "COMMUNICATIONS"
    AUTOMATIC_FARE_COLLECTION = "AUTOMATIC_FARE_COLLECTION"
    DEPOT_MAINTENANCE_EQUIPMENT = "DEPOT_MAINTENANCE_EQUIPMENT"
    PLATFORM_SCREEN_DOORS = "PLATFORM_SCREEN_DOORS"

    @property
    def display_label(self) -> str:
        return EM_SYSTEM_DISPLAY_LABELS[self]


# Mapping insertion order is the one canonical serialization order.  Consumers
# must derive their ordered IDs from this mapping rather than maintain another
# system registry or label list.
EM_SYSTEM_DISPLAY_LABELS = MappingProxyType(
    {
        EMSystemId.ROLLING_STOCK: "電聯車",
        EMSystemId.SIGNALLING: "號誌",
        EMSystemId.POWER_SUPPLY: "供電",
        EMSystemId.COMMUNICATIONS: "通訊",
        EMSystemId.AUTOMATIC_FARE_COLLECTION: "自動收費",
        EMSystemId.DEPOT_MAINTENANCE_EQUIPMENT: "機廠維修設備",
        EMSystemId.PLATFORM_SCREEN_DOORS: "月臺門",
    }
)


def canonical_em_system_ids() -> tuple[EMSystemId, ...]:
    """Return the canonical machine-ID order from the sole registry."""

    return tuple(EM_SYSTEM_DISPLAY_LABELS)


class TaxonomyState(StrEnum):
    """Terminal state vocabulary owned by the E&M Taxonomy stage."""

    TAXONOMY_EVALUATED = "TAXONOMY_EVALUATED"
    TAXONOMY_UNRESOLVED = "TAXONOMY_UNRESOLVED"
    NOT_EVALUATED = "NOT_EVALUATED"


class TaxonomyResolutionReason(StrEnum):
    """Why an executed taxonomy stage could not reach a reliable result."""

    INSUFFICIENT_SYSTEM_EVIDENCE = "INSUFFICIENT_SYSTEM_EVIDENCE"
    CONFLICTING_SYSTEM_EVIDENCE = "CONFLICTING_SYSTEM_EVIDENCE"


@dataclass(frozen=True, slots=True)
class TaxonomySupportSpan:
    """An exact source-preserving evidence span for one canonical E&M system.

    It may support a finalized assignment or participate in unresolved or
    conflicting provenance; the span itself does not establish assignment.
    Source content is intentionally not copied into this contract object.
    """

    system_id: EMSystemId
    candidate_id: str
    start: int
    end: int

    def __post_init__(self) -> None:
        try:
            system_id = EMSystemId(self.system_id)
        except ValueError as exc:
            raise ValueError("TaxonomySupportSpan requires a canonical EMSystemId") from exc
        object.__setattr__(self, "system_id", system_id)

        if not isinstance(self.candidate_id, str) or not self.candidate_id.strip():
            raise ValueError("TaxonomySupportSpan requires candidate_id")
        if isinstance(self.start, bool) or not isinstance(self.start, int):
            raise TypeError("TaxonomySupportSpan start must be an integer")
        if isinstance(self.end, bool) or not isinstance(self.end, int):
            raise TypeError("TaxonomySupportSpan end must be an integer")
        if self.start < 0 or self.end <= self.start:
            raise ValueError("TaxonomySupportSpan requires a non-empty [start, end) span")


@dataclass(frozen=True, slots=True)
class TaxonomyInsufficientEvidenceProvenance:
    """Non-authoritative diagnostic provenance for insufficient evidence."""

    member_candidate_ids: tuple[str, ...]
    diagnostic: str

    def __post_init__(self) -> None:
        try:
            member_candidate_ids = tuple(self.member_candidate_ids)
        except TypeError as exc:
            raise TypeError("member_candidate_ids must be iterable") from exc
        if not member_candidate_ids or any(
            not isinstance(candidate_id, str) or not candidate_id.strip()
            for candidate_id in member_candidate_ids
        ):
            raise ValueError("insufficient evidence provenance requires member candidate IDs")
        object.__setattr__(self, "member_candidate_ids", member_candidate_ids)

        if not isinstance(self.diagnostic, str) or not self.diagnostic.strip():
            raise ValueError("insufficient evidence provenance requires a diagnostic")


@dataclass(frozen=True, slots=True)
class TaxonomyConflictEvidenceProvenance:
    """Source-preserving spans identifying conflicting system evidence."""

    conflict_spans: tuple[TaxonomySupportSpan, ...]

    def __post_init__(self) -> None:
        try:
            conflict_spans = tuple(self.conflict_spans)
        except TypeError as exc:
            raise TypeError("conflict_spans must be iterable") from exc
        if not conflict_spans:
            raise ValueError("conflicting evidence provenance requires conflict spans")
        if any(not isinstance(span, TaxonomySupportSpan) for span in conflict_spans):
            raise TypeError("conflict_spans must contain TaxonomySupportSpan values")
        object.__setattr__(self, "conflict_spans", conflict_spans)


TaxonomyProvenance = (
    TaxonomyInsufficientEvidenceProvenance | TaxonomyConflictEvidenceProvenance
)


def _taxonomy_systems_in_canonical_order(value: object) -> tuple[EMSystemId, ...]:
    if value is None:
        raw_values: tuple[object, ...] = ()
    elif isinstance(value, (str, EMSystemId)):
        raw_values = (value,)
    else:
        try:
            raw_values = tuple(value)  # type: ignore[arg-type]
        except TypeError as exc:
            raise TypeError("TaxonomyResult systems must be an iterable") from exc

    systems: list[EMSystemId] = []
    for raw_value in raw_values:
        try:
            system_id = EMSystemId(raw_value)
        except ValueError as exc:
            raise ValueError("TaxonomyResult systems must use canonical EMSystemId values") from exc
        if system_id in systems:
            raise ValueError("TaxonomyResult systems must not contain duplicates")
        systems.append(system_id)

    system_set = set(systems)
    return tuple(system_id for system_id in canonical_em_system_ids() if system_id in system_set)


@dataclass(frozen=True, slots=True)
class TaxonomyResult:
    """Immutable authoritative result returned by the E&M Taxonomy stage."""

    taxonomy_state: TaxonomyState
    event_id: str = ""
    systems: tuple[EMSystemId, ...] = ()
    taxonomy_resolution_reason: TaxonomyResolutionReason | None = None
    support_spans: tuple[TaxonomySupportSpan, ...] = ()
    provenance: TaxonomyProvenance | None = None

    def __post_init__(self) -> None:
        try:
            state = TaxonomyState(self.taxonomy_state)
        except ValueError as exc:
            raise ValueError("TaxonomyResult requires a valid TaxonomyState") from exc
        object.__setattr__(self, "taxonomy_state", state)

        if not isinstance(self.event_id, str):
            raise TypeError("TaxonomyResult event_id must be a string")
        if state is not TaxonomyState.NOT_EVALUATED and not self.event_id.strip():
            raise ValueError("evaluated taxonomy results require event_id")

        systems = _taxonomy_systems_in_canonical_order(self.systems)
        object.__setattr__(self, "systems", systems)

        reason = self.taxonomy_resolution_reason
        if reason is not None:
            try:
                reason = TaxonomyResolutionReason(reason)
            except ValueError as exc:
                raise ValueError("TaxonomyResult has an invalid resolution reason") from exc
        object.__setattr__(self, "taxonomy_resolution_reason", reason)

        if self.support_spans is None:
            support_spans: tuple[TaxonomySupportSpan, ...] = ()
        else:
            try:
                support_spans = tuple(self.support_spans)
            except TypeError as exc:
                raise TypeError("TaxonomyResult support_spans must be iterable") from exc
        if any(not isinstance(span, TaxonomySupportSpan) for span in support_spans):
            raise TypeError("TaxonomyResult support_spans must contain TaxonomySupportSpan values")
        object.__setattr__(self, "support_spans", support_spans)

        if self.provenance is not None and not isinstance(
            self.provenance,
            (TaxonomyInsufficientEvidenceProvenance, TaxonomyConflictEvidenceProvenance),
        ):
            raise TypeError("TaxonomyResult provenance must use a typed provenance value")

        support_systems = {span.system_id for span in support_spans}

        if state is TaxonomyState.TAXONOMY_EVALUATED:
            if reason is not None:
                raise ValueError("TAXONOMY_EVALUATED cannot carry a resolution reason")
            if self.provenance is not None:
                raise ValueError("TAXONOMY_EVALUATED cannot carry unresolved provenance")
            if not support_systems.issubset(set(systems)):
                raise ValueError("support_spans cannot refer to a system absent from systems")
            if systems and support_systems != set(systems):
                raise ValueError("each assigned system requires system-specific support")
            if not systems and support_spans:
                raise ValueError("evaluated empty systems cannot carry support spans")
        elif state is TaxonomyState.TAXONOMY_UNRESOLVED:
            if systems:
                raise ValueError("TAXONOMY_UNRESOLVED requires empty systems")
            if reason is None:
                raise ValueError("TAXONOMY_UNRESOLVED requires a resolution reason")
            if support_spans:
                raise ValueError("TAXONOMY_UNRESOLVED cannot carry assigned-system support")
            if reason is TaxonomyResolutionReason.INSUFFICIENT_SYSTEM_EVIDENCE:
                if not isinstance(self.provenance, TaxonomyInsufficientEvidenceProvenance):
                    raise ValueError(
                        "INSUFFICIENT_SYSTEM_EVIDENCE requires typed insufficiency provenance"
                    )
            elif not isinstance(self.provenance, TaxonomyConflictEvidenceProvenance):
                raise ValueError(
                    "CONFLICTING_SYSTEM_EVIDENCE requires typed conflict provenance"
                )
        else:
            if systems:
                raise ValueError("NOT_EVALUATED requires empty systems")
            if reason is not None:
                raise ValueError("NOT_EVALUATED cannot carry a resolution reason")
            if support_spans:
                raise ValueError("NOT_EVALUATED cannot carry taxonomy support")
            if self.provenance is not None:
                raise ValueError("NOT_EVALUATED cannot carry taxonomy decision provenance")

    @classmethod
    def not_evaluated(cls, *, event_id: str = "") -> "TaxonomyResult":
        """Represent a taxonomy stage that was never reached."""

        return cls(taxonomy_state=TaxonomyState.NOT_EVALUATED, event_id=event_id)

    def as_mapping(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "taxonomy_state": self.taxonomy_state.value,
            "systems": [system_id.value for system_id in self.systems],
            "taxonomy_resolution_reason": (
                self.taxonomy_resolution_reason.value
                if self.taxonomy_resolution_reason
                else None
            ),
            "support_spans": [
                {
                    "system_id": span.system_id.value,
                    "candidate_id": span.candidate_id,
                    "start": span.start,
                    "end": span.end,
                }
                for span in self.support_spans
            ],
            "provenance": (
                {
                    "member_candidate_ids": list(self.provenance.member_candidate_ids),
                    "diagnostic": self.provenance.diagnostic,
                }
                if isinstance(self.provenance, TaxonomyInsufficientEvidenceProvenance)
                else {
                    "conflict_spans": [
                        {
                            "system_id": span.system_id.value,
                            "candidate_id": span.candidate_id,
                            "start": span.start,
                            "end": span.end,
                        }
                        for span in self.provenance.conflict_spans
                    ]
                    if isinstance(self.provenance, TaxonomyConflictEvidenceProvenance)
                    else None
                }
            ),
        }


class ReportabilityState(StrEnum):
    """The only authoritative terminal states owned by Reportability."""

    REPORTABLE = "REPORTABLE"
    NOT_REPORTABLE = "NOT_REPORTABLE"


class ReportabilityReason(StrEnum):
    """The only authoritative negative Reportability reason."""

    LOW_REPORTABILITY_VALUE = "LOW_REPORTABILITY_VALUE"


@dataclass(frozen=True, slots=True)
class ReportabilitySupportSpan:
    """Immutable source span resolved by the future Reportability owner."""

    candidate_id: str
    start: int
    end: int

    def __post_init__(self) -> None:
        if not isinstance(self.candidate_id, str) or not self.candidate_id.strip():
            raise ValueError("ReportabilitySupportSpan requires candidate_id")
        if isinstance(self.start, bool) or not isinstance(self.start, int):
            raise TypeError("ReportabilitySupportSpan start must be an integer")
        if isinstance(self.end, bool) or not isinstance(self.end, int):
            raise TypeError("ReportabilitySupportSpan end must be an integer")
        if self.start < 0 or self.start >= self.end:
            raise ValueError("ReportabilitySupportSpan requires a non-empty [start, end) span")


@dataclass(frozen=True, slots=True)
class ReportabilityEvidenceProvenance:
    """Immutable evidence provenance for one Reportability result."""

    examined_candidate_ids: tuple[str, ...]
    support_spans: tuple[ReportabilitySupportSpan, ...]
    rationale: str

    def __post_init__(self) -> None:
        if isinstance(self.examined_candidate_ids, (str, bytes, bytearray)):
            raise TypeError("examined_candidate_ids must be an iterable of IDs")
        try:
            candidate_ids = tuple(self.examined_candidate_ids)
        except TypeError as exc:
            raise TypeError("examined_candidate_ids must be an iterable of IDs") from exc
        if not candidate_ids:
            raise ValueError("Reportability provenance requires examined candidate IDs")
        if any(not isinstance(candidate_id, str) or not candidate_id.strip() for candidate_id in candidate_ids):
            raise ValueError("Reportability provenance requires non-empty candidate IDs")
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("Reportability provenance examined candidate IDs must be unique")
        object.__setattr__(self, "examined_candidate_ids", candidate_ids)

        if isinstance(self.support_spans, (str, bytes, bytearray)):
            raise TypeError("support_spans must contain ReportabilitySupportSpan values")
        try:
            support_spans = tuple(self.support_spans)
        except TypeError as exc:
            raise TypeError("support_spans must contain ReportabilitySupportSpan values") from exc
        if any(not isinstance(span, ReportabilitySupportSpan) for span in support_spans):
            raise TypeError("support_spans must contain ReportabilitySupportSpan values")
        if any(span.candidate_id not in candidate_ids for span in support_spans):
            raise ValueError("support span candidate IDs must be examined")
        object.__setattr__(self, "support_spans", support_spans)

        if not isinstance(self.rationale, str) or not self.rationale.strip():
            raise ValueError("Reportability provenance requires rationale")


@dataclass(frozen=True, slots=True)
class ReportabilityResult:
    """Immutable authoritative Reportability result."""

    event_id: str
    reportability_state: ReportabilityState
    reportability_reason: ReportabilityReason | None
    provenance: ReportabilityEvidenceProvenance

    def __post_init__(self) -> None:
        if not isinstance(self.event_id, str) or not self.event_id.strip():
            raise ValueError("ReportabilityResult requires event_id")
        try:
            state = ReportabilityState(self.reportability_state)
        except (TypeError, ValueError) as exc:
            raise ValueError("ReportabilityResult requires a valid ReportabilityState") from exc
        object.__setattr__(self, "reportability_state", state)

        reason = self.reportability_reason
        if reason is not None:
            try:
                reason = ReportabilityReason(reason)
            except (TypeError, ValueError) as exc:
                raise ValueError("ReportabilityResult has an invalid reason") from exc
        object.__setattr__(self, "reportability_reason", reason)

        if not isinstance(self.provenance, ReportabilityEvidenceProvenance):
            raise TypeError("ReportabilityResult requires typed evidence provenance")

        if state is ReportabilityState.REPORTABLE:
            if reason is not None:
                raise ValueError("REPORTABLE cannot carry a Reportability reason")
            if not self.provenance.support_spans:
                raise ValueError("REPORTABLE requires support spans")
        else:
            if reason is not ReportabilityReason.LOW_REPORTABILITY_VALUE:
                raise ValueError(
                    "NOT_REPORTABLE requires LOW_REPORTABILITY_VALUE"
                )
            if self.provenance.support_spans:
                raise ValueError("NOT_REPORTABLE cannot carry support spans")


@dataclass(frozen=True, slots=True)
class ReportabilitySemanticMember:
    """One complete EventGroup evidence member exposed to a provider."""

    candidate_id: str
    substantive_content: str

    def __post_init__(self) -> None:
        if not isinstance(self.candidate_id, str) or not self.candidate_id.strip():
            raise ValueError("Reportability provider member requires candidate_id")
        if not isinstance(self.substantive_content, str):
            raise TypeError("Reportability provider member requires substantive_content")

    def as_mapping(self) -> dict[str, str]:
        return {
            "candidate_id": self.candidate_id,
            "substantive_content": self.substantive_content,
        }


@dataclass(frozen=True, slots=True)
class ReportabilitySemanticRequest:
    """Immutable, deterministically ordered proposal-provider input."""

    event_id: str
    members: tuple[ReportabilitySemanticMember, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.event_id, str) or not self.event_id.strip():
            raise ValueError("Reportability provider request requires event_id")
        if isinstance(self.members, (str, bytes, bytearray)):
            raise TypeError("Reportability provider request members must be typed values")
        try:
            members = tuple(self.members)
        except TypeError as exc:
            raise TypeError("Reportability provider request members must be typed values") from exc
        if not members:
            raise ValueError("Reportability provider request requires members")
        if any(not isinstance(member, ReportabilitySemanticMember) for member in members):
            raise TypeError("Reportability provider request members must be typed values")
        candidate_ids = tuple(member.candidate_id for member in members)
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("Reportability provider request requires unique candidate IDs")
        if candidate_ids != tuple(sorted(candidate_ids)):
            raise ValueError("Reportability provider request members must be lexical candidate order")
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
class ReportabilitySemanticCitation:
    """Untrusted exact quote citation returned by a semantic provider."""

    candidate_id: str
    exact_quote: str

    def __post_init__(self) -> None:
        if not isinstance(self.candidate_id, str) or not self.candidate_id.strip():
            raise ValueError("Reportability citation requires candidate_id")
        if not isinstance(self.exact_quote, str) or not self.exact_quote.strip():
            raise ValueError("Reportability citation requires exact_quote")


@dataclass(frozen=True, slots=True)
class ReportabilitySemanticProposal:
    """Complete untrusted proposal returned by the semantic provider."""

    event_id: str
    proposed_state: ReportabilityState
    examined_candidate_ids: tuple[str, ...]
    support_citations: tuple[ReportabilitySemanticCitation, ...]
    rationale: str

    def __post_init__(self) -> None:
        if not isinstance(self.event_id, str) or not self.event_id.strip():
            raise ValueError("Reportability proposal requires event_id")
        try:
            state = ReportabilityState(self.proposed_state)
        except (TypeError, ValueError) as exc:
            raise ValueError("Reportability proposal requires a valid state") from exc
        object.__setattr__(self, "proposed_state", state)

        if isinstance(self.examined_candidate_ids, (str, bytes, bytearray)):
            raise TypeError("Reportability proposal examined IDs must be an iterable")
        try:
            examined_ids = tuple(self.examined_candidate_ids)
        except TypeError as exc:
            raise TypeError("Reportability proposal examined IDs must be an iterable") from exc
        if not examined_ids:
            raise ValueError("Reportability proposal requires examined candidate IDs")
        if any(not isinstance(candidate_id, str) or not candidate_id.strip() for candidate_id in examined_ids):
            raise ValueError("Reportability proposal requires non-empty candidate IDs")
        if len(examined_ids) != len(set(examined_ids)):
            raise ValueError("Reportability proposal examined candidate IDs must be unique")
        object.__setattr__(self, "examined_candidate_ids", examined_ids)

        if isinstance(self.support_citations, (str, bytes, bytearray)):
            raise TypeError("support_citations must contain ReportabilitySemanticCitation values")
        try:
            citations = tuple(self.support_citations)
        except TypeError as exc:
            raise TypeError("support_citations must contain ReportabilitySemanticCitation values") from exc
        if any(not isinstance(citation, ReportabilitySemanticCitation) for citation in citations):
            raise TypeError("support_citations must contain ReportabilitySemanticCitation values")
        object.__setattr__(self, "support_citations", citations)

        if not isinstance(self.rationale, str) or not self.rationale.strip():
            raise ValueError("Reportability proposal requires rationale")
        if state is ReportabilityState.REPORTABLE and not citations:
            raise ValueError("REPORTABLE proposal requires support citations")
        if state is ReportabilityState.NOT_REPORTABLE and citations:
            raise ValueError("NOT_REPORTABLE proposal cannot carry support citations")


class ReportabilitySemanticProposalProvider(Protocol):
    """Narrow proposal-only semantic provider interface."""

    def __call__(self, request: ReportabilitySemanticRequest) -> ReportabilitySemanticProposal:
        """Return one untrusted semantic proposal for the bounded request."""


class ReportabilityStageFailure(RuntimeError):
    """Typed technical failure; no :class:`ReportabilityResult` exists."""

    def __init__(self, reason: str, *, event_id: str = "") -> None:
        if not isinstance(reason, str) or not reason.strip():
            reason = "reportability stage failed"
        if not isinstance(event_id, str):
            raise TypeError("ReportabilityStageFailure event_id must be a string")
        self.reason = reason
        self.event_id = event_id
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class EventDecisionRecord:
    """Immutable structural handoff from Category/Taxonomy to downstream stages.

    This carrier references authoritative typed values and deliberately does
    not copy any Category or Taxonomy semantic fields.
    """

    event_group: EventGroup
    member_records: tuple[EventIdentityRecord, ...]
    category_result: CategoryResult
    taxonomy_result: TaxonomyResult

    def __post_init__(self) -> None:
        if not isinstance(self.event_group, EventGroup):
            raise TypeError("EventDecisionRecord requires an EventGroup")
        if not isinstance(self.member_records, tuple):
            raise TypeError("EventDecisionRecord member_records must be an immutable tuple")
        if any(not isinstance(record, EventIdentityRecord) for record in self.member_records):
            raise TypeError("EventDecisionRecord member_records must contain EventIdentityRecord values")
        if not isinstance(self.category_result, CategoryResult):
            raise TypeError("EventDecisionRecord requires a CategoryResult")
        if not isinstance(self.taxonomy_result, TaxonomyResult):
            raise TypeError("EventDecisionRecord requires a TaxonomyResult")

        event_id = self.event_group.event_id
        if self.category_result.event_id != event_id:
            raise ValueError("EventDecisionRecord CategoryResult event_id does not match EventGroup")
        if self.taxonomy_result.event_id != event_id:
            raise ValueError("EventDecisionRecord TaxonomyResult event_id does not match EventGroup")

        by_candidate: dict[str, EventIdentityRecord] = {}
        for record in self.member_records:
            candidate_id = record.candidate.candidate_id
            if candidate_id in by_candidate:
                raise ValueError("EventDecisionRecord member_records contain duplicate candidate IDs")
            by_candidate[candidate_id] = record

        expected_ids = self.event_group.member_candidate_ids
        if set(by_candidate) != set(expected_ids):
            raise ValueError("EventDecisionRecord member_records must match EventGroup membership exactly")

        # EventGroup membership is already canonicalized.  Rebuild only the
        # structural tuple in that order so caller input order cannot become a
        # second semantic truth.
        object.__setattr__(
            self,
            "member_records",
            tuple(by_candidate[candidate_id] for candidate_id in expected_ids),
        )


class DiscoveryIntent(StrEnum):
    """Canonical machine IDs owned by Search discovery."""

    TECHNOLOGY = "technology"
    MAJOR_INCIDENT = "major_incident"
    OPERATIONS = "operations"
    PROCUREMENT = "procurement"

    @property
    def display_label(self) -> str:
        return _DISCOVERY_INTENT_DISPLAY_LABELS[self]


_DISCOVERY_INTENT_DISPLAY_LABELS = MappingProxyType(
    {
        DiscoveryIntent.TECHNOLOGY: "technology",
        DiscoveryIntent.MAJOR_INCIDENT: "major incident",
        DiscoveryIntent.OPERATIONS: "operations",
        DiscoveryIntent.PROCUREMENT: "procurement",
    }
)


class RegionMode(StrEnum):
    """The two configured Search target modes."""

    SELECTED = "selected"
    GLOBAL = "global"


class SearchTerminalStatus(StrEnum):
    """Terminal status of one independently attempted discovery request."""

    SUCCESS_WITH_RESULTS = "SUCCESS_WITH_RESULTS"
    SUCCESS_ZERO_RESULTS = "SUCCESS_ZERO_RESULTS"
    TECHNICAL_FAILURE = "TECHNICAL_FAILURE"


class SearchTechnicalFailureClass(StrEnum):
    """Finite safe classes for technical provider failures."""

    NETWORK = "NETWORK"
    TIMEOUT = "TIMEOUT"
    AUTHENTICATION = "AUTHENTICATION"
    RATE_LIMIT = "RATE_LIMIT"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    UNKNOWN = "UNKNOWN"


class SearchProviderId(StrEnum):
    """Canonical executable provider IDs governed by the Search contract."""

    GOOGLE_NEWS_RSS = "google_news_rss"


class ProviderProfileEligibility(StrEnum):
    """Whether one market/profile/provider tuple is executable."""

    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True, slots=True)
class GoogleNewsRssEncoding:
    """Exact Google News RSS parameters frozen by provider capability config."""

    hl: str
    gl: str
    ceid: str

    def __post_init__(self) -> None:
        for field_name in ("hl", "gl", "ceid"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Google News RSS encoding requires non-empty {field_name}")


@dataclass(frozen=True, slots=True)
class ProviderProfileBinding:
    """Typed capability decision for one market/profile/provider tuple."""

    market_id: str
    language_profile_id: str
    provider_id: SearchProviderId | str
    eligibility: ProviderProfileEligibility | str
    encoding: GoogleNewsRssEncoding | None = None

    def __post_init__(self) -> None:
        for field_name in ("market_id", "language_profile_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"provider profile binding requires {field_name}")
        try:
            provider_id = SearchProviderId(self.provider_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("provider profile binding requires a canonical provider_id") from exc
        object.__setattr__(self, "provider_id", provider_id)
        try:
            eligibility = ProviderProfileEligibility(self.eligibility)
        except (TypeError, ValueError) as exc:
            raise ValueError("provider profile binding requires canonical eligibility") from exc
        object.__setattr__(self, "eligibility", eligibility)
        if eligibility is ProviderProfileEligibility.SUPPORTED:
            if not isinstance(self.encoding, GoogleNewsRssEncoding):
                raise ValueError("supported provider profile binding requires encoding")
        elif self.encoding is not None:
            raise ValueError("unsupported provider profile binding must not carry encoding")

    @property
    def key(self) -> tuple[str, str, SearchProviderId]:
        return (self.market_id, self.language_profile_id, self.provider_id)


class SearchInfrastructureFailureClass(StrEnum):
    """Safe mechanical classes for executor-level failures."""

    EXECUTION_ABORTED = "EXECUTION_ABORTED"
    INFRASTRUCTURE_UNAVAILABLE = "INFRASTRUCTURE_UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


class SearchInfrastructureStage(StrEnum):
    """Finite safe stages for executor-level failures."""

    EXECUTION = "execution"
    DISPATCH = "dispatch"
    OBSERVATION = "observation"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class SearchInfrastructureFailure:
    """Safe executor provenance; it carries no raw exception or domain result."""

    failure_class: SearchInfrastructureFailureClass
    stage: SearchInfrastructureStage | str

    def __post_init__(self) -> None:
        try:
            failure_class = SearchInfrastructureFailureClass(self.failure_class)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid Search infrastructure failure class") from exc
        object.__setattr__(self, "failure_class", failure_class)
        try:
            stage = SearchInfrastructureStage(self.stage)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid Search infrastructure failure stage") from exc
        object.__setattr__(self, "stage", stage)


@dataclass(frozen=True, slots=True)
class SearchPlanningLimits:
    """Configured bounded planning limits materialized with the registry."""

    max_concrete_requests_per_family: int
    max_plan_items: int

    def __post_init__(self) -> None:
        for field_name in ("max_concrete_requests_per_family", "max_plan_items"):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{field_name} must be a positive integer")


@dataclass(frozen=True, slots=True)
class LanguageProfileConfig:
    """Immutable language/profile configuration consumed by RegionRegistry."""

    profile_id: str
    display_name: str = ""
    locale: str = ""
    intent_vocabulary: Mapping[str, Mapping[str, tuple[str, ...]]] = field(default_factory=dict)
    enabled: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.profile_id, str) or not self.profile_id.strip():
            raise ValueError("language profile requires profile_id")
        if not isinstance(self.display_name, str) or not isinstance(self.locale, str):
            raise TypeError("language profile labels must be strings")
        if not isinstance(self.enabled, bool):
            raise TypeError("language profile enabled must be bool")
        vocabulary: dict[str, Mapping[str, tuple[str, ...]]] = {}
        for intent, groups in dict(self.intent_vocabulary).items():
            try:
                intent_id = DiscoveryIntent(intent).value
            except (TypeError, ValueError) as exc:
                raise ValueError("language profile contains an invalid discovery intent") from exc
            if not isinstance(groups, Mapping) or not groups:
                raise ValueError("language profile intent vocabulary requires groups")
            normalized_groups: dict[str, tuple[str, ...]] = {}
            for group_name, terms in dict(groups).items():
                if not isinstance(group_name, str) or not group_name.strip():
                    raise ValueError("language profile vocabulary group requires a name")
                terms = tuple(terms)
                if not terms or any(not isinstance(term, str) or not term.strip() for term in terms):
                    raise ValueError("language profile vocabulary terms must be non-empty")
                if len(terms) != len(set(terms)):
                    raise ValueError("language profile vocabulary terms must be unique")
                normalized_groups[group_name] = terms
            vocabulary[intent_id] = MappingProxyType(normalized_groups)
        missing_intents = {intent.value for intent in DiscoveryIntent} - set(vocabulary)
        if missing_intents:
            raise ValueError("language profile must expose all discovery intents")
        object.__setattr__(self, "intent_vocabulary", MappingProxyType(vocabulary))


@dataclass(frozen=True, slots=True)
class MarketConfig:
    """Immutable configured discovery target; it is not a factual Scope result."""

    market_id: str
    display_name: str
    primary_profiles: tuple[str, ...] = ()
    secondary_profiles: tuple[str, ...] = ()
    english_supplement_profiles: tuple[str, ...] = ()
    locale_hints: tuple[str, ...] = ()
    terminology_refs: tuple[str, ...] = ()
    enabled: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.market_id, str) or not self.market_id.strip():
            raise ValueError("market requires market_id")
        if not isinstance(self.display_name, str) or not self.display_name.strip():
            raise ValueError("market requires display_name")
        if not isinstance(self.enabled, bool):
            raise TypeError("market enabled must be bool")
        for field_name in (
            "primary_profiles",
            "secondary_profiles",
            "english_supplement_profiles",
            "locale_hints",
            "terminology_refs",
        ):
            values = getattr(self, field_name)
            if isinstance(values, (str, bytes, bytearray)):
                raise TypeError(f"{field_name} must be an immutable tuple")
            values = tuple(values)
            if any(not isinstance(value, str) or not value.strip() for value in values):
                raise ValueError(f"{field_name} must contain non-empty strings")
            if len(values) != len(set(values)):
                raise ValueError(f"{field_name} must not contain duplicates")
            object.__setattr__(self, field_name, values)

        primary = set(self.primary_profiles)
        secondary = set(self.secondary_profiles)
        supplement = set(self.english_supplement_profiles)
        if primary & secondary or primary & supplement or secondary & supplement:
            raise ValueError("market profile mappings must be disjoint")


@dataclass(frozen=True, slots=True)
class QueryFamilyConfig:
    """Bounded deterministic query composition configuration."""

    family_id: str
    templates: tuple[str, ...]
    vocabulary_groups: Mapping[str, tuple[str, ...]]
    provider_target: SearchProviderId | str
    anchor_terms: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.family_id, str) or not self.family_id.strip():
            raise ValueError("query family requires family_id")
        templates = tuple(self.templates)
        if not templates or any(not isinstance(value, str) or not value.strip() for value in templates):
            raise ValueError("query family requires non-empty templates")
        if len(templates) != len(set(templates)):
            raise ValueError("query family templates must be unique")
        object.__setattr__(self, "templates", templates)
        groups_by_intent: dict[str, tuple[str, ...]] = {}
        for intent, values in dict(self.vocabulary_groups).items():
            try:
                intent_id = DiscoveryIntent(intent).value
            except (TypeError, ValueError) as exc:
                raise ValueError("query family contains an invalid discovery intent") from exc
            values = tuple(values)
            if not values or any(not isinstance(value, str) or not value.strip() for value in values):
                raise ValueError("query family vocabulary groups must be non-empty")
            if len(values) != len(set(values)):
                raise ValueError("query family vocabulary groups must be unique")
            groups_by_intent[intent_id] = values
        missing = {intent.value for intent in DiscoveryIntent} - set(groups_by_intent)
        if missing:
            raise ValueError("query family must expose all discovery intents")
        object.__setattr__(self, "vocabulary_groups", MappingProxyType(groups_by_intent))
        anchors = tuple(self.anchor_terms)
        if any(not isinstance(value, str) or not value.strip() for value in anchors):
            raise ValueError("query family anchor terms must be non-empty strings")
        if len(anchors) != len(set(anchors)):
            raise ValueError("query family anchor terms must be unique")
        object.__setattr__(self, "anchor_terms", anchors)
        try:
            provider_target = SearchProviderId(self.provider_target)
        except (TypeError, ValueError) as exc:
            raise ValueError("query family requires a canonical provider_target") from exc
        object.__setattr__(self, "provider_target", provider_target)


@dataclass(frozen=True, slots=True)
class SearchPlanItem:
    """One frozen, independently-attemptable concrete discovery request."""

    plan_item_id: str
    market_id: str
    region_mode: RegionMode
    intent: DiscoveryIntent
    language_profile: str
    query_family_id: str
    provider_target: SearchProviderId | str
    query: str
    provider_encoding: GoogleNewsRssEncoding
    locale: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.plan_item_id, str) or not self.plan_item_id.strip():
            raise ValueError("SearchPlanItem requires plan_item_id")
        if not isinstance(self.market_id, str) or not self.market_id.strip():
            raise ValueError("SearchPlanItem requires market_id")
        try:
            mode = RegionMode(self.region_mode)
            intent = DiscoveryIntent(self.intent)
        except (TypeError, ValueError) as exc:
            raise ValueError("SearchPlanItem requires canonical region mode and intent") from exc
        object.__setattr__(self, "region_mode", mode)
        object.__setattr__(self, "intent", intent)
        for field_name in ("language_profile", "query_family_id", "query", "locale"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"SearchPlanItem requires {field_name}")
        try:
            provider_target = SearchProviderId(self.provider_target)
        except (TypeError, ValueError) as exc:
            raise ValueError("SearchPlanItem requires a canonical provider_target") from exc
        object.__setattr__(self, "provider_target", provider_target)
        if provider_target is SearchProviderId.GOOGLE_NEWS_RSS and not isinstance(self.provider_encoding, GoogleNewsRssEncoding):
            raise ValueError("SearchPlanItem requires provider_encoding for google_news_rss")

    @property
    def request(self) -> str:
        """Provider-compatible concrete request represented by this item."""

        return self.query


@dataclass(frozen=True, slots=True)
class SearchPlan:
    """Complete immutable Search plan frozen before any provider execution."""

    configuration_version: str
    region_mode: RegionMode
    items: tuple[SearchPlanItem, ...]
    plan_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.configuration_version, str) or not self.configuration_version.strip():
            raise ValueError("SearchPlan requires configuration_version")
        try:
            mode = RegionMode(self.region_mode)
        except (TypeError, ValueError) as exc:
            raise ValueError("SearchPlan requires a canonical region mode") from exc
        object.__setattr__(self, "region_mode", mode)
        items = tuple(self.items)
        if any(not isinstance(item, SearchPlanItem) for item in items):
            raise TypeError("SearchPlan items must be SearchPlanItem values")
        ids = tuple(item.plan_item_id for item in items)
        if len(ids) != len(set(ids)):
            raise ValueError("SearchPlan requires unique plan_item_id values")
        if any(item.region_mode is not mode for item in items):
            raise ValueError("SearchPlan item region mode must match plan")
        object.__setattr__(self, "items", items)
        if not isinstance(self.plan_id, str) or not self.plan_id.strip():
            raise ValueError("SearchPlan requires plan_id")

    def as_mapping(self) -> dict[str, Any]:
        return {
            "configuration_version": self.configuration_version,
            "region_mode": self.region_mode.value,
            "plan_id": self.plan_id,
            "items": [
                {
                    "plan_item_id": item.plan_item_id,
                    "market_id": item.market_id,
                    "intent": item.intent.value,
                    "language_profile": item.language_profile,
                    "query_family_id": item.query_family_id,
                    "provider_target": item.provider_target,
                    "query": item.query,
                    "locale": item.locale,
                    "provider_encoding": {
                        "hl": item.provider_encoding.hl,
                        "gl": item.provider_encoding.gl,
                        "ceid": item.provider_encoding.ceid,
                    },
                }
                for item in self.items
            ],
        }


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    """Mechanical provider result; title/snippet remain discovery metadata only."""

    title: str
    url: str
    publisher: str = ""
    published_at: str = ""
    snippet: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.title, str) or not self.title.strip():
            raise ValueError("DiscoveryResult requires title")
        if not isinstance(self.url, str) or not self.url.strip():
            raise ValueError("DiscoveryResult requires url")
        for field_name in ("publisher", "published_at", "snippet"):
            if not isinstance(getattr(self, field_name), str):
                raise TypeError("DiscoveryResult metadata must be strings")


@dataclass(frozen=True, slots=True)
class SearchAttemptResult:
    """Typed mechanical attempt outcome; it owns no downstream decisions."""

    plan_item_id: str
    status: SearchTerminalStatus
    results: tuple[DiscoveryResult, ...] = ()
    technical_failure_class: SearchTechnicalFailureClass | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.plan_item_id, str) or not self.plan_item_id.strip():
            raise ValueError("SearchAttemptResult requires plan_item_id")
        try:
            status = SearchTerminalStatus(self.status)
        except (TypeError, ValueError) as exc:
            raise ValueError("SearchAttemptResult requires a legal terminal status") from exc
        object.__setattr__(self, "status", status)
        results = tuple(self.results)
        if any(not isinstance(result, DiscoveryResult) for result in results):
            raise TypeError("SearchAttemptResult results must be DiscoveryResult values")
        object.__setattr__(self, "results", results)
        if status is SearchTerminalStatus.SUCCESS_ZERO_RESULTS and results:
            raise ValueError("SUCCESS_ZERO_RESULTS must contain no results")
        if status is SearchTerminalStatus.SUCCESS_WITH_RESULTS and not results:
            raise ValueError("SUCCESS_WITH_RESULTS requires results")
        if status is SearchTerminalStatus.TECHNICAL_FAILURE:
            if results:
                raise ValueError("TECHNICAL_FAILURE must not create synthetic results")
            try:
                failure_class = SearchTechnicalFailureClass(self.technical_failure_class)
            except (TypeError, ValueError) as exc:
                raise ValueError("TECHNICAL_FAILURE requires a safe failure class") from exc
            object.__setattr__(self, "technical_failure_class", failure_class)
        elif self.technical_failure_class is not None:
            raise ValueError("successful result must not carry technical failure class")


@dataclass(frozen=True, slots=True)
class SearchObservation:
    """Immutable observation only; it cannot alter plan or downstream decisions."""

    plan_item_id: str
    market_id: str
    intent: DiscoveryIntent
    language_profile: str
    query_family_id: str
    provider: SearchProviderId | str
    planned: bool
    attempted: bool
    terminal_status: SearchTerminalStatus | None
    raw_result_count: int
    technical_failure_class: SearchTechnicalFailureClass | None = None
    normalized_result_count: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.plan_item_id, str) or not self.plan_item_id.strip():
            raise ValueError("SearchObservation requires plan_item_id")
        if not isinstance(self.market_id, str) or not self.market_id.strip():
            raise ValueError("SearchObservation requires market_id")
        try:
            intent = DiscoveryIntent(self.intent)
        except (TypeError, ValueError) as exc:
            raise ValueError("SearchObservation requires canonical intent") from exc
        object.__setattr__(self, "intent", intent)
        for field_name in ("language_profile", "query_family_id"):
            if not isinstance(getattr(self, field_name), str) or not getattr(self, field_name).strip():
                raise ValueError(f"SearchObservation requires {field_name}")
        try:
            provider = SearchProviderId(self.provider)
        except (TypeError, ValueError) as exc:
            raise ValueError("SearchObservation requires a canonical provider") from exc
        object.__setattr__(self, "provider", provider)
        if not isinstance(self.planned, bool) or not isinstance(self.attempted, bool):
            raise TypeError("SearchObservation planned/attempted must be bool")
        if not self.planned and self.attempted:
            raise ValueError("an unplanned observation cannot be attempted")
        if not self.attempted and self.terminal_status is not None:
            raise ValueError("an unattempted observation cannot carry terminal status")
        if self.attempted and self.terminal_status is None:
            raise ValueError("an attempted observation requires terminal status")
        if self.terminal_status is not None:
            try:
                object.__setattr__(self, "terminal_status", SearchTerminalStatus(self.terminal_status))
            except (TypeError, ValueError) as exc:
                raise ValueError("SearchObservation requires a legal terminal status") from exc
        if (
            not isinstance(self.raw_result_count, int)
            or isinstance(self.raw_result_count, bool)
            or self.raw_result_count < 0
        ):
            raise ValueError("raw_result_count must be non-negative")
        if self.normalized_result_count is not None and (
            not isinstance(self.normalized_result_count, int)
            or isinstance(self.normalized_result_count, bool)
            or self.normalized_result_count < 0
        ):
            raise ValueError("normalized_result_count must be None or a non-negative integer")
        if not self.attempted:
            if self.terminal_status is not None:
                raise ValueError("an unattempted observation cannot carry terminal status")
            if self.technical_failure_class is not None:
                raise ValueError("an unattempted observation cannot carry failure class")
            if self.raw_result_count != 0:
                raise ValueError("an unattempted observation must have zero raw results")
            if self.normalized_result_count is not None:
                raise ValueError("an unattempted observation cannot be normalized")
        elif self.normalized_result_count is not None and self.terminal_status is None:
            raise ValueError("a normalized observation requires a terminal status")
        if self.terminal_status is SearchTerminalStatus.TECHNICAL_FAILURE:
            try:
                failure_class = SearchTechnicalFailureClass(self.technical_failure_class)
            except (TypeError, ValueError) as exc:
                raise ValueError("technical failure observation requires safe failure class") from exc
            object.__setattr__(self, "technical_failure_class", failure_class)
        elif self.technical_failure_class is not None:
            raise ValueError("successful observation must not carry technical failure class")


@dataclass(frozen=True, slots=True)
class SearchExecutionResult:
    """Immutable mechanical result for one complete frozen Search plan."""

    plan: SearchPlan
    attempt_results: tuple[SearchAttemptResult, ...] = ()
    unattempted_items: tuple[SearchPlanItem, ...] = ()
    infrastructure_failure: SearchInfrastructureFailure | None = None
    observations: tuple[SearchObservation, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.plan, SearchPlan):
            raise TypeError("SearchExecutionResult requires a SearchPlan")
        plan_items = {item.plan_item_id: item for item in self.plan.items}
        plan_order = {item_id: index for index, item_id in enumerate(plan_items)}

        attempts = tuple(self.attempt_results)
        if any(not isinstance(result, SearchAttemptResult) for result in attempts):
            raise TypeError("SearchExecutionResult attempts must be SearchAttemptResult values")
        attempt_ids = tuple(result.plan_item_id for result in attempts)
        if len(attempt_ids) != len(set(attempt_ids)):
            raise ValueError("SearchExecutionResult cannot contain duplicate attempt results")
        if any(item_id not in plan_items for item_id in attempt_ids):
            raise ValueError("SearchExecutionResult contains a foreign plan_item_id")

        unattempted = tuple(self.unattempted_items)
        if any(not isinstance(item, SearchPlanItem) for item in unattempted):
            raise TypeError("SearchExecutionResult unattempted items must be SearchPlanItem values")
        unattempted_ids = tuple(item.plan_item_id for item in unattempted)
        if len(unattempted_ids) != len(set(unattempted_ids)):
            raise ValueError("SearchExecutionResult cannot duplicate unattempted items")
        if any(item_id not in plan_items for item_id in unattempted_ids):
            raise ValueError("SearchExecutionResult contains a foreign unattempted plan_item_id")
        if set(attempt_ids) & set(unattempted_ids):
            raise ValueError("a plan item cannot be both attempted and unattempted")
        if set(attempt_ids) | set(unattempted_ids) != set(plan_items):
            raise ValueError("SearchExecutionResult must account for every frozen plan item")

        object.__setattr__(
            self,
            "attempt_results",
            tuple(sorted(attempts, key=lambda result: plan_order[result.plan_item_id])),
        )
        object.__setattr__(
            self,
            "unattempted_items",
            tuple(sorted(unattempted, key=lambda item: plan_order[item.plan_item_id])),
        )
        if self.infrastructure_failure is not None and not isinstance(
            self.infrastructure_failure, SearchInfrastructureFailure
        ):
            raise TypeError("SearchExecutionResult infrastructure_failure must be typed")

        observations = tuple(self.observations)
        if any(not isinstance(observation, SearchObservation) for observation in observations):
            raise TypeError("SearchExecutionResult observations must be SearchObservation values")
        observation_ids = tuple(observation.plan_item_id for observation in observations)
        if len(observation_ids) != len(set(observation_ids)):
            raise ValueError("SearchExecutionResult cannot duplicate observations")
        if any(item_id not in plan_items for item_id in observation_ids):
            raise ValueError("SearchExecutionResult observations contain a foreign plan_item_id")
        if set(observation_ids) != set(plan_items):
            raise ValueError("SearchExecutionResult requires exactly one observation per plan item")
        attempt_by_id = {result.plan_item_id: result for result in attempts}
        unattempted_id_set = set(unattempted_ids)
        for observation in observations:
            item = plan_items[observation.plan_item_id]
            if not observation.planned:
                raise ValueError("execution observations must be planned")
            if (
                observation.market_id != item.market_id
                or observation.intent is not item.intent
                or observation.language_profile != item.language_profile
                or observation.query_family_id != item.query_family_id
                or observation.provider is not item.provider_target
            ):
                raise ValueError("SearchExecutionResult observation does not match frozen plan metadata")
            if observation.attempted:
                result = attempt_by_id.get(observation.plan_item_id)
                if result is None or observation.terminal_status is not result.status:
                    raise ValueError("attempt observation must match its terminal result")
                if observation.normalized_result_count is not None:
                    raise ValueError("execution observations must not contain normalization results")
                if result.status is SearchTerminalStatus.SUCCESS_ZERO_RESULTS:
                    if observation.raw_result_count != 0:
                        raise ValueError("zero-result observation must have zero raw results")
                elif result.status is SearchTerminalStatus.SUCCESS_WITH_RESULTS:
                    if observation.raw_result_count != len(result.results):
                        raise ValueError("successful observation raw count must match results")
                elif observation.technical_failure_class is not result.technical_failure_class:
                    raise ValueError("technical failure observation must match its result")
                if result.status is not SearchTerminalStatus.TECHNICAL_FAILURE and observation.technical_failure_class is not None:
                    raise ValueError("successful observation must not carry failure class")
            elif observation.plan_item_id not in unattempted_id_set:
                raise ValueError("unattempted observation must match an unattempted item")
        object.__setattr__(
            self,
            "observations",
            tuple(sorted(observations, key=lambda observation: plan_order[observation.plan_item_id])),
        )

    @property
    def plan_id(self) -> str:
        return self.plan.plan_id

    @property
    def execution_complete(self) -> bool:
        return not self.unattempted_items and self.infrastructure_failure is None

    @property
    def has_technical_failures(self) -> bool:
        return any(result.status is SearchTerminalStatus.TECHNICAL_FAILURE for result in self.attempt_results)


ACQUISITION_ID_VERSION = "acquisition-id-v1"
CANDIDATE_ID_VERSION = "candidate-id-v1"


def _canonical_identity_json(value: Mapping[str, Any]) -> bytes:
    """Serialize a mechanical identity input without text normalization."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class AcquisitionRecord:
    """One immutable raw discovery result and its frozen plan provenance."""

    plan_id: str
    plan_item: SearchPlanItem
    provider_result_ordinal: int
    raw_result: DiscoveryResult

    def __post_init__(self) -> None:
        if not isinstance(self.plan_id, str) or not self.plan_id.strip():
            raise ValueError("AcquisitionRecord requires plan_id")
        if not isinstance(self.plan_item, SearchPlanItem):
            raise TypeError("AcquisitionRecord requires a SearchPlanItem")
        if (
            not isinstance(self.provider_result_ordinal, int)
            or isinstance(self.provider_result_ordinal, bool)
            or self.provider_result_ordinal < 0
        ):
            raise ValueError("provider_result_ordinal must be a non-negative integer")
        if not isinstance(self.raw_result, DiscoveryResult):
            raise TypeError("AcquisitionRecord requires a DiscoveryResult")

    @property
    def acquisition_id(self) -> str:
        """Return the CandidateNormalizer-owned deterministic occurrence ID."""

        return acquisition_id_for(self)


def acquisition_id_for(record: AcquisitionRecord) -> str:
    """Build the versioned ID for one raw discovery occurrence."""

    if not isinstance(record, AcquisitionRecord):
        raise TypeError("acquisition_id_for requires an AcquisitionRecord")
    raw = record.raw_result
    payload = {
        "version": ACQUISITION_ID_VERSION,
        "plan_id": record.plan_id,
        "plan_item_id": record.plan_item.plan_item_id,
        "provider_result_ordinal": record.provider_result_ordinal,
        "raw_result": {
            "title": raw.title,
            "url": raw.url,
            "publisher": raw.publisher,
            "published_at": raw.published_at,
            "snippet": raw.snippet,
        },
    }
    return "acq_" + hashlib.sha256(_canonical_identity_json(payload)).hexdigest()


def candidate_id_for_url(url: str) -> str:
    """Build a candidate ID from a validated URL's exact representation."""

    if not isinstance(url, str) or not url:
        raise ValueError("candidate_id_for_url requires a non-empty URL string")
    payload = {"version": CANDIDATE_ID_VERSION, "url": url}
    return "cand_" + hashlib.sha256(_canonical_identity_json(payload)).hexdigest()


class CandidateNormalizationFailureClass(StrEnum):
    """Finite mechanical failure classes for the future normalizer boundary."""

    INVALID_ACQUISITION = "INVALID_ACQUISITION"
    INVALID_URL = "INVALID_URL"
    INTERNAL_FAILURE = "INTERNAL_FAILURE"


@dataclass(frozen=True, slots=True)
class CandidateNormalizationFailure:
    """Safe typed failure; raw payloads and exception text never belong here."""

    failure_class: CandidateNormalizationFailureClass

    def __post_init__(self) -> None:
        try:
            value = CandidateNormalizationFailureClass(self.failure_class)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid CandidateNormalizationFailureClass") from exc
        object.__setattr__(self, "failure_class", value)


@dataclass(frozen=True, slots=True)
class AcquisitionOrigin:
    """Immutable association from one acquisition occurrence to one candidate."""

    acquisition_id: str
    record: AcquisitionRecord

    def __post_init__(self) -> None:
        if (
            not isinstance(self.acquisition_id, str)
            or re.fullmatch(r"acq_[0-9a-f]{64}", self.acquisition_id) is None
        ):
            raise ValueError("AcquisitionOrigin requires a canonical acquisition ID")
        if not isinstance(self.record, AcquisitionRecord):
            raise TypeError("AcquisitionOrigin requires an AcquisitionRecord")
        if self.acquisition_id != acquisition_id_for(self.record):
            raise ValueError("AcquisitionOrigin ID does not match its record")


@dataclass(frozen=True, slots=True)
class NormalizedCandidate:
    """One candidate with every immutable acquisition origin preserved."""

    candidate: CanonicalCandidate
    acquisition_origins: tuple[AcquisitionOrigin, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, CanonicalCandidate):
            raise TypeError("NormalizedCandidate requires a CanonicalCandidate")
        if self.candidate.candidate_id != candidate_id_for_url(self.candidate.url):
            raise ValueError("NormalizedCandidate candidate ID does not match candidate.url")
        origins = tuple(self.acquisition_origins)
        if not origins:
            raise ValueError("NormalizedCandidate requires acquisition origins")
        if any(not isinstance(origin, AcquisitionOrigin) for origin in origins):
            raise TypeError("acquisition_origins must contain AcquisitionOrigin values")
        ids = tuple(origin.acquisition_id for origin in origins)
        if len(ids) != len(set(ids)):
            raise ValueError("NormalizedCandidate acquisition origins must be unique")
        if any(origin.record.raw_result.url != self.candidate.url for origin in origins):
            raise ValueError("all acquisition origins must exactly match candidate.url")
        object.__setattr__(self, "acquisition_origins", tuple(sorted(origins, key=lambda item: item.acquisition_id)))


@dataclass(frozen=True, slots=True)
class CandidateNormalizationResult:
    """Immutable normalization result with no debug counts or domain outcomes."""

    normalized_candidates: tuple[NormalizedCandidate, ...] = ()

    def __post_init__(self) -> None:
        candidates = tuple(self.normalized_candidates)
        if any(not isinstance(candidate, NormalizedCandidate) for candidate in candidates):
            raise TypeError("normalized_candidates must contain NormalizedCandidate values")
        candidate_ids = tuple(item.candidate.candidate_id for item in candidates)
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("normalized candidate IDs must be unique")
        urls = tuple(item.candidate.url for item in candidates)
        if len(urls) != len(set(urls)):
            raise ValueError("normalized candidate URLs must be unique")
        origin_ids = [origin.acquisition_id for item in candidates for origin in item.acquisition_origins]
        if len(origin_ids) != len(set(origin_ids)):
            raise ValueError("acquisition IDs cannot map to multiple candidates")
        occurrence_records: dict[tuple[str, str, int], tuple[str, DiscoveryResult]] = {}
        for item in candidates:
            for origin in item.acquisition_origins:
                record = origin.record
                occurrence_key = (
                    record.plan_id,
                    record.plan_item.plan_item_id,
                    record.provider_result_ordinal,
                )
                prior = occurrence_records.get(occurrence_key)
                if prior is not None and prior != (origin.acquisition_id, record.raw_result):
                    raise ValueError("conflicting acquisition records share one occurrence identity")
                occurrence_records[occurrence_key] = (origin.acquisition_id, record.raw_result)
        object.__setattr__(self, "normalized_candidates", tuple(sorted(candidates, key=lambda item: item.candidate.candidate_id)))


@runtime_checkable
class SearchProvider(Protocol):
    """Phase 2B provider seam; implementations receive frozen plan items only."""

    def execute(self, request: SearchPlanItem) -> SearchAttemptResult:
        """Execute one technical discovery request and return a typed result."""
