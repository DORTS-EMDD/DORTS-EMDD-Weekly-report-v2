"""Small immutable contracts for the V2 Evidence boundary."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping, Protocol


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
