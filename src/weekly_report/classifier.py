"""The sole production owner of Category decisions for post-dedup Event Groups."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Protocol

from .source_refs import cited_spans, source_payload, source_refs
from .contracts import (
    ProposalContractViolation,
    SemanticProviderConfigurationFailure,
    SemanticProviderTechnicalFailure,
    CategoryId,
    CategoryResolutionReason,
    CategoryResult,
    CategoryState,
    EvidenceState,
    EventGroup,
    EventIdentityFacts,
    EventIdentityRecord,
    ScopeState,
)


_CATEGORY_GUIDANCE = (
    "Read the supplied authoritative substantive Evidence for this one already-grouped Event Group and return only advisory action/lifecycle observations and evidence-grounded relationships.",
    "Do not return a Category ID, Category state, unresolved reason, confidence, ranking, or final Category decision. The Python Classifier is the sole Category owner and will apply the contract after validating your observations.",
    "Each source has a Python-assigned source_ref (M1, M2, ...) and sentence_ids. Every action observation and every examined-evidence citation must cite supplied source_ref and sentence_ids. Never copy or retype source text or identifiers into a citation.",
    "Return each materially relevant current action as an action observation. Use one unique action_id per observation, action_kind from the supplied closed set, subject_kind, lifecycle_relation, adoption_status, and citations. One complete observation for one occurrence is valid; do not split one occurrence merely because the Evidence contains several verbs or aspects.",
    "principal_action_id is the action_id of the one principal current or lifecycle action only when the Evidence supports a unique principal action. Use null when there is no unique principal action or the evidence is insufficient. Do not use ordering, category preference, source order, or keyword counts to choose it.",
    "relationships may contain only the two evidence-grounded relationship families COMMON_DECISION_MEMBERSHIP and SAME_OCCURRENCE_DEPENDENCE. Do not return a Category decision or Category precedence in a relationship.",
    "A COMMON_DECISION_MEMBERSHIP relationship names every action_id that the Evidence supports as a constituent aspect of one specific authority decision or principal occurrence. Do not infer it from the same Category, source, date, announcement, sentence, citation, EventGroup, or ordering.",
    "A SAME_OCCURRENCE_DEPENDENCE relationship names principal_action_id, dependent_action_id, and dependence_kind CONSEQUENCE, RESPONSE, RECOVERY, or DESCRIPTIVE_ASPECT only when the Evidence supports that the dependent observation is part of the same principal occurrence rather than an independent defining action. Do not infer it from citation or sentence overlap, shared source, temporal proximity, EventGroup membership, keywords, or ordering.",
    "Every relationship must carry its own citations to the supplied Evidence. The relationship citations must support the relationship itself; action citations alone do not establish coherence, containment, causation, consequence, or dependence. When the Evidence supports multiple returned observations as constituent or dependent aspects of one occurrence or decision, preserve that supported relationship in the returned proposal, whether or not a principal_action_id is present. Use null or an empty relationship set when no relationship is supported; do not manufacture or backfill one.",
    "action_kind values describe evidence-grounded actions, not Categories: RESEARCH_RESULT, PROTOTYPE, PILOT, EXPERIMENT, APPLIED_TECHNICAL_TEST, DEPLOYMENT, SUBSTANTIVE_TECHNICAL_DEVELOPMENT, PASSENGER_SERVICE_OPENING, SERVICE_CHANGE, TIMETABLE_CHANGE, FARE_CHANGE, OPERATING_PRACTICE_CHANGE, OPERATIONAL_GOVERNANCE, OPERATIONAL_DISPUTE, INVESTIGATION_FINDINGS, INCIDENT, PROCUREMENT_TENDER, PROCUREMENT_BID_INVITATION, PROCUREMENT_SELECTION, PROCUREMENT_AWARD, PROCUREMENT_OPTION, NORMATIVE_CHANGE, RECOMMENDATION, PROJECT_STEP, FUTURE_PLAN, STATEMENT, STATISTICS, RANKING, BACKGROUND, CONFLICTING_ACTION_CLAIMS, UNKNOWN.",
    "subject_kind values are TECHNOLOGY_METHOD_MATERIAL, PASSENGER_SERVICE, PROCUREMENT_ACTION, NORMATIVE_DOCUMENT, INCIDENT_SUBJECT, PROJECT, RECOMMENDATION, or OTHER. lifecycle_relation values are TECHNOLOGY_ITSELF, OPERATING_SERVICE, PROJECT_DELIVERY, PRE_OPENING, PROCUREMENT_LIFECYCLE, NORMATIVE_LIFECYCLE, INCIDENT_OCCURRENCE, BACKGROUND, or NONE. adoption_status values are COMPLETED, IMPLEMENTED, ADOPTED, FORMAL, PLANNED, RECOMMENDED, ANNOUNCED, NOT_APPLICABLE, or UNKNOWN.",
    "A technology action is about the technology, method, or material itself only when subject_kind is TECHNOLOGY_METHOD_MATERIAL and lifecycle_relation is TECHNOLOGY_ITSELF. A pilot or deployment of technology on an operating urban-rail system remains an action about the technology itself. A later acceptance or commissioning observation does not erase an evidenced completed technology deployment.",
    "Installation, integration, testing, commissioning, acceptance, inspections, trial runs, and equipment work that are merely steps of constructing, opening, accepting, or inspecting a line, station, or depot must be represented with PROJECT_DELIVERY or PRE_OPENING and must not be presented as a technology-itself deployment.",
    "An activity that uses, teaches, exercises, presents, exhibits, discusses, or enforces a technology, service, procurement, or rule is not itself the corresponding listed action. A training session, drill, meeting, exchange, or exhibition must not be represented as a technology-itself action.",
    "Passenger or revenue service openings and actual service, timetable, fare, operating-practice, dispute, or operational-governance actions concern a running passenger transport service; a station shop, clinic, booth, project publicity, staffing, or project management before opening does not.",
    "A procurement action must have taken place. A planned, expected, or future tender, selection, or award is FUTURE_PLAN with PLANNED or ANNOUNCED adoption, not a completed procurement action.",
    "A formal normative change may be a published or revised regulation, mandatory technical rule, standard, applicable formal guidance, operator-wide specification, or formal draft/consultation. Citing an existing standard, a recommendation, a procurement specification, a penalty under an existing rule, or ordinary advice is not a normative change.",
    "An unadopted recommendation is RECOMMENDATION with RECOMMENDED or PLANNED adoption. A completed incident investigation or safety-governance report with no new normative rule is INVESTIGATION_FINDINGS, not the earlier incident.",
    "Project steps, plans, statistics, rankings, statements, criticisms, demands, questions, and background-only actions have no Category-defining action. When the evidence contains no unique listed principal action, leave principal_action_id null and preserve all examined citations.",
    "Do not infer from titles, snippets, discovery intent, publisher, URL, report period, taxonomy, Reportability, outside knowledge, or a language/event/country-specific rule. Event identity is already decided; do not merge or split Event Groups.",
    "Subtype is optional descriptive metadata only. It may be null or a concise descriptive string, but it must not express a Category decision or change the action observations.",
)


_CATEGORY_ACTION_KINDS = (
    "RESEARCH_RESULT",
    "PROTOTYPE",
    "PILOT",
    "EXPERIMENT",
    "APPLIED_TECHNICAL_TEST",
    "DEPLOYMENT",
    "SUBSTANTIVE_TECHNICAL_DEVELOPMENT",
    "PASSENGER_SERVICE_OPENING",
    "SERVICE_CHANGE",
    "TIMETABLE_CHANGE",
    "FARE_CHANGE",
    "OPERATING_PRACTICE_CHANGE",
    "OPERATIONAL_GOVERNANCE",
    "OPERATIONAL_DISPUTE",
    "INVESTIGATION_FINDINGS",
    "INCIDENT",
    "PROCUREMENT_TENDER",
    "PROCUREMENT_BID_INVITATION",
    "PROCUREMENT_SELECTION",
    "PROCUREMENT_AWARD",
    "PROCUREMENT_OPTION",
    "NORMATIVE_CHANGE",
    "RECOMMENDATION",
    "PROJECT_STEP",
    "FUTURE_PLAN",
    "STATEMENT",
    "STATISTICS",
    "RANKING",
    "BACKGROUND",
    "CONFLICTING_ACTION_CLAIMS",
    "UNKNOWN",
)
_CATEGORY_SUBJECT_KINDS = (
    "TECHNOLOGY_METHOD_MATERIAL",
    "PASSENGER_SERVICE",
    "PROCUREMENT_ACTION",
    "NORMATIVE_DOCUMENT",
    "INCIDENT_SUBJECT",
    "PROJECT",
    "RECOMMENDATION",
    "OTHER",
)
_CATEGORY_LIFECYCLE_RELATIONS = (
    "TECHNOLOGY_ITSELF",
    "OPERATING_SERVICE",
    "PROJECT_DELIVERY",
    "PRE_OPENING",
    "PROCUREMENT_LIFECYCLE",
    "NORMATIVE_LIFECYCLE",
    "INCIDENT_OCCURRENCE",
    "BACKGROUND",
    "NONE",
)
_CATEGORY_ADOPTION_STATUSES = (
    "COMPLETED",
    "IMPLEMENTED",
    "ADOPTED",
    "FORMAL",
    "PLANNED",
    "RECOMMENDED",
    "ANNOUNCED",
    "NOT_APPLICABLE",
    "UNKNOWN",
)
_CATEGORY_RELATIONSHIP_TYPES = (
    "COMMON_DECISION_MEMBERSHIP",
    "SAME_OCCURRENCE_DEPENDENCE",
)
_CATEGORY_DEPENDENCE_KINDS = (
    "CONSEQUENCE",
    "RESPONSE",
    "RECOVERY",
    "DESCRIPTIVE_ASPECT",
)


@dataclass(frozen=True, slots=True)
class CategorySourceEvidence:
    """One source's principal body and evidence-backed action facts."""

    candidate_id: str
    substantive_content: str
    action_facts: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not self.candidate_id:
            raise ValueError("Category source requires candidate_id")
        if not self.substantive_content.strip():
            raise ValueError("Category source requires substantive content")
        if not isinstance(self.action_facts, Mapping):
            raise TypeError("action_facts must be a mapping")
        object.__setattr__(self, "action_facts", MappingProxyType(dict(self.action_facts)))

    def as_mapping(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "substantive_content": self.substantive_content,
            "action_facts": dict(self.action_facts),
        }


@dataclass(frozen=True, slots=True)
class CategorySemanticRequest:
    """Bounded, source-preserving input for the Classifier's semantic helper.

    Candidate search metadata and canonical-source preference are deliberately
    absent. Sources are presented as Python-assigned references (RC-16); a
    reference is a citation handle, not rank or priority.
    """

    sources: tuple[CategorySourceEvidence, ...]
    unresolved_claims: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = ()

    def __post_init__(self) -> None:
        ids = tuple(source.candidate_id for source in self.sources)
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("Category request requires unique source candidate IDs")
        if ids != tuple(sorted(ids)):
            raise ValueError("Category request sources must be in stable ID order")

    @property
    def source_refs(self) -> dict[str, str]:
        return source_refs(tuple(source.candidate_id for source in self.sources))

    def as_payload(self) -> dict[str, Any]:
        ref_of = {candidate_id: ref for ref, candidate_id in self.source_refs.items()}
        return {
            "contract_reference": "docs/ARCHITECTURE_CONTRACT.md §L, §A.10",
            "guidance": list(_CATEGORY_GUIDANCE),
            "source_order_is_authoritative": False,
            "sources": [
                {
                    **source_payload(ref_of[source.candidate_id], source.substantive_content),
                    "action_facts": dict(source.action_facts),
                }
                for source in self.sources
            ],
            "unresolved_event_claims": [
                {
                    "claim_key": claim_key,
                    "source_values": [
                        {"source_ref": ref_of[candidate_id], "value": value}
                        for candidate_id, value in candidate_values
                    ],
                }
                for claim_key, candidate_values in self.unresolved_claims
            ],
        }


@dataclass(frozen=True, slots=True)
class CategoryEvidenceSpan:
    """Classifier-canonicalized citation span into one supplied source body."""

    candidate_id: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class CategoryCitation:
    """An untrusted source reference and sentence IDs from a Category proposal."""

    source_ref: str
    sentence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CategoryActionProposal:
    """Untrusted, evidence-cited action/lifecycle observation from the Helper."""

    action_id: str
    action_kind: str
    subject_kind: str
    lifecycle_relation: str
    adoption_status: str
    citations: tuple[CategoryCitation, ...]


@dataclass(frozen=True, slots=True)
class CategoryRelationshipProposal:
    """Untrusted, evidence-cited relationship between advisory observations."""

    relationship_type: str
    member_action_ids: tuple[str, ...] = ()
    principal_action_id: str | None = None
    dependent_action_id: str | None = None
    dependence_kind: str | None = None
    citations: tuple[CategoryCitation, ...] = ()


@dataclass(frozen=True, slots=True)
class CategorySemanticResponse:
    """Untrusted advisory action observations; Classifier validates and decides."""

    actions: tuple[CategoryActionProposal, ...] = ()
    principal_action_id: str | None = None
    subtype: str | None = None
    examined_citations: tuple[CategoryCitation, ...] = ()
    relationships: tuple[CategoryRelationshipProposal, ...] = ()


@dataclass(frozen=True, slots=True)
class CategorySemanticHelperResult:
    """A proposal plus non-decision provider metadata for Classifier tracing."""

    proposal: object
    provenance: Mapping[str, str]

    def __post_init__(self) -> None:
        if not isinstance(self.provenance, Mapping):
            raise TypeError("helper provenance must be a mapping")
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))


class CategorySemanticHelper(Protocol):
    """Advisory no-search helper; it does not own the Category decision."""

    def __call__(self, request: CategorySemanticRequest) -> object:
        """Return a structured proposal based only on the supplied request."""


class InvalidCategorySemanticResponse(ValueError):
    """Raised when a semantic proposal fails the Classifier response contract."""

    def __init__(
        self,
        message: str,
        *,
        provenance: Mapping[str, str] | None = None,
        predicate: str | None = None,
    ) -> None:
        super().__init__(message)
        self.provenance = MappingProxyType(dict(provenance or {}))
        # Observation only (RC-66): the contract predicate that failed. It
        # names the gap in the TechnicalGap signature and decides nothing.
        self.predicate = predicate


class CategoryProposalViolation(ProposalContractViolation):
    """A Category proposal the owner cannot validate (RC-16).

    It isolates the EventGroup as a disclosed technical gap; it is never
    ``CATEGORY_UNRESOLVED``, which is reserved for domain reasons.
    """

    def __init__(self, message: str, predicate: str | None = None) -> None:
        super().__init__(message)
        if predicate is None:
            predicate = "CITATION_INVALID" if "citation" in message else "PROPOSAL_INVALID"
        self.failure_class = predicate


@dataclass(frozen=True, slots=True)
class _ValidatedCategoryResponse:
    actions: tuple[CategoryActionProposal, ...]
    principal_action_id: str | None
    subtype: str | None
    action_citation_spans: tuple[tuple[str, tuple[CategoryEvidenceSpan, ...]], ...]
    examined_citation_spans: tuple[CategoryEvidenceSpan, ...]
    relationships: tuple[CategoryRelationshipProposal, ...]
    relationship_citation_spans: tuple[tuple[CategoryRelationshipProposal, tuple[CategoryEvidenceSpan, ...]], ...]


_RESPONSE_FIELDS = frozenset(
    {"actions", "principal_action_id", "subtype", "examined_citations", "relationships"}
)
_ACTION_FIELDS = frozenset(
    {
        "action_id",
        "action_kind",
        "subject_kind",
        "lifecycle_relation",
        "adoption_status",
        "citations",
    }
)
_CITATION_FIELDS = frozenset({"source_ref", "sentence_ids"})
_RELATIONSHIP_FIELDS = frozenset(
    {
        "relationship_type",
        "member_action_ids",
        "principal_action_id",
        "dependent_action_id",
        "dependence_kind",
        "citations",
    }
)
_DOMAIN_UNRESOLVED_REASONS = frozenset(
    {
        CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION,
        CategoryResolutionReason.RECOMMENDATION_WITHOUT_ADOPTED_ACTION,
        CategoryResolutionReason.CONFLICTING_CATEGORY_DEFINING_CLAIMS,
        CategoryResolutionReason.NO_UNIQUE_PRINCIPAL_ACTION,
        CategoryResolutionReason.INSUFFICIENT_CATEGORY_EVIDENCE,
    }
)


def _citation_from_value(value: object) -> CategoryCitation:
    if isinstance(value, CategoryCitation):
        source_ref, sentence_ids = value.source_ref, value.sentence_ids
    else:
        if not isinstance(value, Mapping) or frozenset(value) != _CITATION_FIELDS:
            raise InvalidCategorySemanticResponse("citation fields do not match schema")
        source_ref = value["source_ref"]
        sentence_ids = value["sentence_ids"]
    if not isinstance(source_ref, str) or not source_ref:
        raise InvalidCategorySemanticResponse("citation source_ref must be a string")
    if not isinstance(sentence_ids, (list, tuple)):
        raise InvalidCategorySemanticResponse("citation sentence_ids must be an array")
    if not sentence_ids or not all(isinstance(sentence_id, str) and sentence_id for sentence_id in sentence_ids):
        raise InvalidCategorySemanticResponse("citation sentence_ids must contain non-empty strings")
    return CategoryCitation(source_ref, tuple(sentence_ids))


def _parse_citations(
    value: object,
    request: CategorySemanticRequest,
) -> tuple[CategoryEvidenceSpan, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise InvalidCategorySemanticResponse("citations must be an array")
    source_text = {source.candidate_id: source.substantive_content for source in request.sources}
    refs = request.source_refs
    spans: list[CategoryEvidenceSpan] = []
    for raw_citation in value:
        citation = _citation_from_value(raw_citation)
        candidate_id = refs.get(citation.source_ref)
        if candidate_id is None:
            raise InvalidCategorySemanticResponse("citation references an unknown source")
        resolved = cited_spans(source_text[candidate_id], citation.sentence_ids)
        if resolved is None:
            raise InvalidCategorySemanticResponse("citation sentence_ids do not resolve in the source")
        for start, end in resolved:
            span = CategoryEvidenceSpan(candidate_id, start, end)
            if span not in spans:
                spans.append(span)
    return tuple(spans)


def _category_action_from_value(value: object) -> CategoryActionProposal:
    if isinstance(value, CategoryActionProposal):
        action = value
    else:
        if not isinstance(value, Mapping) or frozenset(value) != _ACTION_FIELDS:
            raise InvalidCategorySemanticResponse("action fields do not match schema", predicate="ACTION_SHAPE")
        raw_citations = value["citations"]
        if not isinstance(raw_citations, Sequence) or isinstance(raw_citations, (str, bytes, bytearray)):
            raise InvalidCategorySemanticResponse("action citations must be an array", predicate="ACTION_CITATION")
        try:
            action = CategoryActionProposal(
                action_id=value["action_id"],
                action_kind=value["action_kind"],
                subject_kind=value["subject_kind"],
                lifecycle_relation=value["lifecycle_relation"],
                adoption_status=value["adoption_status"],
                citations=tuple(_citation_from_value(item) for item in raw_citations),
            )
        except (KeyError, TypeError) as exc:
            raise InvalidCategorySemanticResponse("action fields have invalid types", predicate="ACTION_SHAPE") from exc
    if (
        not isinstance(action.action_id, str)
        or not action.action_id
        or not isinstance(action.action_kind, str)
        or action.action_kind not in _CATEGORY_ACTION_KINDS
        or not isinstance(action.subject_kind, str)
        or action.subject_kind not in _CATEGORY_SUBJECT_KINDS
        or not isinstance(action.lifecycle_relation, str)
        or action.lifecycle_relation not in _CATEGORY_LIFECYCLE_RELATIONS
        or not isinstance(action.adoption_status, str)
        or action.adoption_status not in _CATEGORY_ADOPTION_STATUSES
        or not action.citations
        or not isinstance(action.citations, (list, tuple))
        or not all(isinstance(citation, CategoryCitation) for citation in action.citations)
    ):
        raise InvalidCategorySemanticResponse("action observation is outside the advisory contract", predicate="ACTION_FIELDS")
    return action


def _category_relationship_from_value(value: object) -> CategoryRelationshipProposal:
    if isinstance(value, CategoryRelationshipProposal):
        relationship = value
    else:
        if not isinstance(value, Mapping) or frozenset(value) != _RELATIONSHIP_FIELDS:
            raise InvalidCategorySemanticResponse(
                "relationship fields do not match schema",
                predicate="RELATIONSHIP_SHAPE",
            )
        raw_member_action_ids = value["member_action_ids"]
        raw_citations = value["citations"]
        try:
            relationship = CategoryRelationshipProposal(
                relationship_type=value["relationship_type"],
                member_action_ids=tuple(raw_member_action_ids),
                principal_action_id=value["principal_action_id"],
                dependent_action_id=value["dependent_action_id"],
                dependence_kind=value["dependence_kind"],
                citations=tuple(_citation_from_value(item) for item in raw_citations),
            )
        except (KeyError, TypeError) as exc:
            raise InvalidCategorySemanticResponse(
                "relationship fields have invalid types",
                predicate="RELATIONSHIP_SHAPE",
            ) from exc

    if (
        not isinstance(relationship.relationship_type, str)
        or relationship.relationship_type not in _CATEGORY_RELATIONSHIP_TYPES
        or not isinstance(relationship.member_action_ids, (list, tuple))
        or not all(isinstance(action_id, str) and action_id for action_id in relationship.member_action_ids)
        or len(set(relationship.member_action_ids)) != len(relationship.member_action_ids)
        or not isinstance(relationship.citations, (list, tuple))
        or not relationship.citations
        or not all(isinstance(citation, CategoryCitation) for citation in relationship.citations)
    ):
        raise InvalidCategorySemanticResponse(
            "relationship is outside the advisory contract",
            predicate="RELATIONSHIP_FIELDS",
        )

    if relationship.relationship_type == "COMMON_DECISION_MEMBERSHIP":
        if (
            len(relationship.member_action_ids) < 2
            or relationship.principal_action_id is not None
            or relationship.dependent_action_id is not None
            or relationship.dependence_kind is not None
        ):
            raise InvalidCategorySemanticResponse(
                "common-decision relationship has invalid endpoints",
                predicate="RELATIONSHIP_ENDPOINT",
            )
    else:
        if (
            relationship.member_action_ids
            or not isinstance(relationship.principal_action_id, str)
            or not relationship.principal_action_id
            or not isinstance(relationship.dependent_action_id, str)
            or not relationship.dependent_action_id
            or relationship.principal_action_id == relationship.dependent_action_id
            or relationship.dependence_kind not in _CATEGORY_DEPENDENCE_KINDS
        ):
            raise InvalidCategorySemanticResponse(
                "same-occurrence relationship has invalid endpoints",
                predicate="RELATIONSHIP_ENDPOINT",
            )
    return relationship


def _parse_relationships(
    value: object,
    request: CategorySemanticRequest,
    actions: tuple[CategoryActionProposal, ...],
) -> tuple[
    tuple[CategoryRelationshipProposal, ...],
    tuple[tuple[CategoryRelationshipProposal, tuple[CategoryEvidenceSpan, ...]], ...],
]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise InvalidCategorySemanticResponse(
            "relationships must be an array",
            predicate="RELATIONSHIP_SHAPE",
        )

    action_ids = {action.action_id for action in actions}
    relationships: list[CategoryRelationshipProposal] = []
    relationship_spans: list[
        tuple[CategoryRelationshipProposal, tuple[CategoryEvidenceSpan, ...]]
    ] = []
    common_memberships: set[frozenset[str]] = set()
    dependency_pairs: dict[tuple[str, str], str] = {}
    for raw_relationship in value:
        relationship = _category_relationship_from_value(raw_relationship)
        endpoints = (
            relationship.member_action_ids
            if relationship.relationship_type == "COMMON_DECISION_MEMBERSHIP"
            else (relationship.principal_action_id, relationship.dependent_action_id)
        )
        if any(action_id not in action_ids for action_id in endpoints):
            raise InvalidCategorySemanticResponse(
                "relationship references an unknown action",
                predicate="RELATIONSHIP_ENDPOINT",
            )
        spans = _parse_citations(relationship.citations, request)
        if not spans:
            raise InvalidCategorySemanticResponse(
                "relationship requires evidence support",
                predicate="RELATIONSHIP_CITATION",
            )

        if relationship.relationship_type == "COMMON_DECISION_MEMBERSHIP":
            membership = frozenset(relationship.member_action_ids)
            if membership in common_memberships:
                raise InvalidCategorySemanticResponse(
                    "duplicate common-decision relationship",
                    predicate="RELATIONSHIP_CONTRADICTION",
                )
            common_memberships.add(membership)
        else:
            pair = (relationship.principal_action_id, relationship.dependent_action_id)
            reverse = (pair[1], pair[0])
            previous_kind = dependency_pairs.get(pair)
            if previous_kind is not None:
                raise InvalidCategorySemanticResponse(
                    "duplicate or contradictory same-occurrence relationship",
                    predicate="RELATIONSHIP_CONTRADICTION",
                )
            if reverse in dependency_pairs:
                raise InvalidCategorySemanticResponse(
                    "opposed same-occurrence relationships are contradictory",
                    predicate="RELATIONSHIP_CONTRADICTION",
                )
            dependency_pairs[pair] = relationship.dependence_kind or ""

        relationships.append(relationship)
        relationship_spans.append((relationship, spans))
    return tuple(relationships), tuple(relationship_spans)


def _parse_action_observations(
    value: object,
    request: CategorySemanticRequest,
) -> tuple[tuple[CategoryActionProposal, ...], tuple[tuple[str, tuple[CategoryEvidenceSpan, ...]], ...]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise InvalidCategorySemanticResponse("actions must be an array", predicate="ACTION_SHAPE")
    actions: list[CategoryActionProposal] = []
    action_spans: list[tuple[str, tuple[CategoryEvidenceSpan, ...]]] = []
    action_ids: set[str] = set()
    source_text = {source.candidate_id: source.substantive_content for source in request.sources}
    refs = request.source_refs
    for raw_action in value:
        action = _category_action_from_value(raw_action)
        if action.action_id in action_ids:
            raise InvalidCategorySemanticResponse("action_id values must be unique", predicate="ACTION_ID")
        action_ids.add(action.action_id)
        spans: list[CategoryEvidenceSpan] = []
        for raw_citation in action.citations:
            candidate_id = refs.get(raw_citation.source_ref)
            if candidate_id is None:
                raise InvalidCategorySemanticResponse("action citation references an unknown source", predicate="CITATION_INVALID")
            resolved = cited_spans(source_text[candidate_id], raw_citation.sentence_ids)
            if resolved is None:
                raise InvalidCategorySemanticResponse("action citation sentence_ids do not resolve", predicate="CITATION_INVALID")
            for start, end in resolved:
                span = CategoryEvidenceSpan(candidate_id, start, end)
                if span not in spans:
                    spans.append(span)
        if not spans:
            raise InvalidCategorySemanticResponse("action observation requires a citation", predicate="ACTION_CITATION")
        actions.append(action)
        action_spans.append((action.action_id, tuple(spans)))
    return tuple(actions), tuple(action_spans)


def _validate_response(
    raw_response: object,
    request: CategorySemanticRequest,
) -> _ValidatedCategoryResponse:
    if isinstance(raw_response, CategorySemanticResponse):
        payload = {
            "actions": raw_response.actions,
            "principal_action_id": raw_response.principal_action_id,
            "subtype": raw_response.subtype,
            "examined_citations": raw_response.examined_citations,
            "relationships": raw_response.relationships,
        }
    elif isinstance(raw_response, Mapping):
        payload = raw_response
    else:
        raise InvalidCategorySemanticResponse("response must be an object", predicate="RESPONSE_SHAPE")

    if frozenset(payload) != _RESPONSE_FIELDS:
        raise InvalidCategorySemanticResponse("response fields do not match schema", predicate="RESPONSE_SHAPE")
    actions, action_spans = _parse_action_observations(payload["actions"], request)
    principal_action_id = payload["principal_action_id"]
    if principal_action_id is not None and not isinstance(principal_action_id, str):
        raise InvalidCategorySemanticResponse("principal_action_id must be a string or null", predicate="PRINCIPAL_ACTION")
    if principal_action_id is not None and principal_action_id not in {action.action_id for action in actions}:
        raise InvalidCategorySemanticResponse("principal_action_id must name a supplied action", predicate="PRINCIPAL_ACTION")
    subtype = payload["subtype"]
    if subtype is not None and not isinstance(subtype, str):
        raise InvalidCategorySemanticResponse("subtype must be a string or null", predicate="SUBTYPE_TYPE")
    examined_spans = _parse_citations(payload["examined_citations"], request)
    if not examined_spans:
        raise InvalidCategorySemanticResponse("examined_citations must contain at least one supported sentence", predicate="CITATION_INVALID")
    relationships, relationship_spans = _parse_relationships(
        payload["relationships"],
        request,
        actions,
    )
    dependent_action_ids = {
        relationship.dependent_action_id
        for relationship in relationships
        if relationship.relationship_type == "SAME_OCCURRENCE_DEPENDENCE"
    }
    if principal_action_id is not None and principal_action_id in dependent_action_ids:
        raise InvalidCategorySemanticResponse(
            "principal_action_id conflicts with a dependent relationship endpoint",
            predicate="RELATIONSHIP_CONTRADICTION",
        )
    return _ValidatedCategoryResponse(
        actions=actions,
        principal_action_id=principal_action_id,
        subtype=subtype,
        action_citation_spans=action_spans,
        examined_citation_spans=examined_spans,
        relationships=relationships,
        relationship_citation_spans=relationship_spans,
    )


def _action_facts(facts: EventIdentityFacts | None) -> dict[str, Any]:
    if facts is None:
        return {}
    values: dict[str, Any] = {}
    for key in (
        "action",
        "lifecycle_step",
        "subject",
        "asset",
        "project",
        "package",
        "location",
        "occurrence_context",
    ):
        value = getattr(facts, key)
        if value.strip():
            values[key] = value
    if facts.non_identity_claims:
        values["source_claims"] = dict(sorted(facts.non_identity_claims.items()))
    return values


def _request_for(
    event_group: EventGroup,
    records: Sequence[EventIdentityRecord],
) -> CategorySemanticRequest:
    record_by_id: dict[str, EventIdentityRecord] = {}
    for record in records:
        if not isinstance(record, EventIdentityRecord):
            raise TypeError("Classifier requires EventIdentityRecord inputs")
        candidate_id = record.candidate.candidate_id
        if candidate_id in record_by_id:
            raise ValueError("Event Group records must have unique candidate IDs")
        record_by_id[candidate_id] = record

    if set(record_by_id) != set(event_group.member_candidate_ids):
        raise ValueError("records must match exactly the Event Group members")

    sources: list[CategorySourceEvidence] = []
    for candidate_id in sorted(event_group.member_candidate_ids):
        record = record_by_id[candidate_id]
        if record.evidence.state is not EvidenceState.READY:
            raise ValueError("Classifier requires EVIDENCE_READY for every Event Group member")
        if record.scope.state is not ScopeState.IN_SCOPE:
            raise ValueError("Classifier requires IN_SCOPE for every Event Group member")
        if not record.temporal.date_valid:
            raise ValueError("Classifier requires DATE_VALID for every Event Group member")
        sources.append(
            CategorySourceEvidence(
                candidate_id=candidate_id,
                substantive_content=record.evidence.substantive_content,
                action_facts=_action_facts(record.evidence.identity_facts),
            )
        )

    unresolved_claims = tuple(
        sorted(
            (
                claim.claim_key,
                tuple(sorted(claim.candidate_values)),
            )
            for claim in event_group.unresolved_claims
        )
    )
    return CategorySemanticRequest(tuple(sources), unresolved_claims)


def _span_provenance(spans: tuple[CategoryEvidenceSpan, ...]) -> list[dict[str, Any]]:
    return [
        {"candidate_id": span.candidate_id, "start": span.start, "end": span.end}
        for span in spans
    ]


def _provider_provenance(value: object) -> dict[str, str]:
    allowed = {
        "provider_identifier",
        "model_identifier",
        "prompt_version",
        "schema_version",
        "helper_version",
    }
    if not isinstance(value, Mapping):
        return {}
    return {
        key: item
        for key, item in value.items()
        if key in allowed and isinstance(key, str) and isinstance(item, str)
    }


_TECHNICAL_ACTION_KINDS = frozenset(
    {
        "RESEARCH_RESULT",
        "PROTOTYPE",
        "PILOT",
        "EXPERIMENT",
        "APPLIED_TECHNICAL_TEST",
        "DEPLOYMENT",
        "SUBSTANTIVE_TECHNICAL_DEVELOPMENT",
    }
)
_OPERATIONAL_ACTION_KINDS = frozenset(
    {
        "PASSENGER_SERVICE_OPENING",
        "SERVICE_CHANGE",
        "TIMETABLE_CHANGE",
        "FARE_CHANGE",
        "OPERATING_PRACTICE_CHANGE",
        "OPERATIONAL_GOVERNANCE",
        "OPERATIONAL_DISPUTE",
        "INVESTIGATION_FINDINGS",
    }
)
_PROCUREMENT_ACTION_KINDS = frozenset(
    {
        "PROCUREMENT_TENDER",
        "PROCUREMENT_BID_INVITATION",
        "PROCUREMENT_SELECTION",
        "PROCUREMENT_AWARD",
        "PROCUREMENT_OPTION",
    }
)
_COMPLETED_ACTION_STATUSES = frozenset({"COMPLETED", "IMPLEMENTED", "ADOPTED", "FORMAL"})
_PROJECT_LIFECYCLE_RELATIONS = frozenset({"PROJECT_DELIVERY", "PRE_OPENING", "BACKGROUND"})
_DIRECT_PASSENGER_OPERATIONAL_ACTION_KINDS = frozenset(
    {
        "PASSENGER_SERVICE_OPENING",
        "SERVICE_CHANGE",
        "TIMETABLE_CHANGE",
        "FARE_CHANGE",
        "OPERATIONAL_DISPUTE",
    }
)
_OPERATING_PRACTICE_ACTION_KINDS = frozenset(
    {
        "OPERATING_PRACTICE_CHANGE",
        "OPERATIONAL_GOVERNANCE",
    }
)


def _classify_action_observation(
    action: CategoryActionProposal,
) -> tuple[CategoryId | None, CategoryResolutionReason]:
    """Apply the §L mapping to one validated, advisory action observation."""

    if action.action_kind in _TECHNICAL_ACTION_KINDS:
        if (
            action.subject_kind != "TECHNOLOGY_METHOD_MATERIAL"
            or action.lifecycle_relation in _PROJECT_LIFECYCLE_RELATIONS
            or action.adoption_status in {"PLANNED", "RECOMMENDED", "ANNOUNCED", "UNKNOWN"}
        ):
            return None, CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION
        return CategoryId.TECHNICAL_DEVELOPMENT, CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION

    if action.action_kind in _OPERATIONAL_ACTION_KINDS:
        if action.action_kind == "INVESTIGATION_FINDINGS":
            if action.adoption_status in {"PLANNED", "RECOMMENDED", "ANNOUNCED", "UNKNOWN"}:
                return None, CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION
            return CategoryId.OPERATIONAL_CHANGE, CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION
        if action.lifecycle_relation != "OPERATING_SERVICE" or action.adoption_status not in _COMPLETED_ACTION_STATUSES:
            return None, CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION
        if (
            action.action_kind in _DIRECT_PASSENGER_OPERATIONAL_ACTION_KINDS
            and action.subject_kind != "PASSENGER_SERVICE"
        ):
            return None, CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION
        if (
            action.action_kind in _OPERATING_PRACTICE_ACTION_KINDS
            and action.subject_kind not in {"PASSENGER_SERVICE", "OTHER"}
        ):
            return None, CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION
        return CategoryId.OPERATIONAL_CHANGE, CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION

    if action.action_kind in _PROCUREMENT_ACTION_KINDS:
        if action.adoption_status not in _COMPLETED_ACTION_STATUSES:
            return None, CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION
        return CategoryId.PROCUREMENT, CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION

    if action.action_kind == "NORMATIVE_CHANGE":
        if (
            action.subject_kind != "NORMATIVE_DOCUMENT"
            or action.lifecycle_relation != "NORMATIVE_LIFECYCLE"
            or action.adoption_status not in {"COMPLETED", "IMPLEMENTED", "ADOPTED", "FORMAL", "PLANNED"}
        ):
            return None, CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION
        return CategoryId.NORMATIVE_CHANGE, CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION

    if action.action_kind == "INCIDENT":
        if action.lifecycle_relation != "INCIDENT_OCCURRENCE" or action.adoption_status in {"PLANNED", "RECOMMENDED", "ANNOUNCED", "UNKNOWN"}:
            return None, CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION
        return CategoryId.INCIDENT, CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION

    if action.action_kind == "RECOMMENDATION":
        return None, CategoryResolutionReason.RECOMMENDATION_WITHOUT_ADOPTED_ACTION
    if action.action_kind == "CONFLICTING_ACTION_CLAIMS":
        return None, CategoryResolutionReason.CONFLICTING_CATEGORY_DEFINING_CLAIMS
    if action.action_kind == "UNKNOWN":
        return None, CategoryResolutionReason.INSUFFICIENT_CATEGORY_EVIDENCE
    return None, CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION


def _unresolved_reason_without_principal(
    actions: tuple[CategoryActionProposal, ...],
) -> CategoryResolutionReason:
    if any(action.action_kind == "RECOMMENDATION" for action in actions):
        if all(action.action_kind in {"RECOMMENDATION", "FUTURE_PLAN", "STATEMENT", "BACKGROUND"} for action in actions):
            return CategoryResolutionReason.RECOMMENDATION_WITHOUT_ADOPTED_ACTION
    if any(action.action_kind == "UNKNOWN" for action in actions):
        return CategoryResolutionReason.INSUFFICIENT_CATEGORY_EVIDENCE
    if any(action.action_kind == "CONFLICTING_ACTION_CLAIMS" for action in actions):
        return CategoryResolutionReason.CONFLICTING_CATEGORY_DEFINING_CLAIMS
    category_defining = [
        action
        for action in actions
        if _classify_action_observation(action)[0] is not None
    ]
    if len(category_defining) > 1:
        return CategoryResolutionReason.NO_UNIQUE_PRINCIPAL_ACTION
    return CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION


def _common_decision_covers(
    relationships: tuple[CategoryRelationshipProposal, ...],
    action_ids: set[str],
) -> bool:
    """Return whether one explicit relationship accounts for every action."""

    if len(action_ids) < 2:
        return False
    return any(
        relationship.relationship_type == "COMMON_DECISION_MEMBERSHIP"
        and action_ids.issubset(set(relationship.member_action_ids))
        for relationship in relationships
    )


def _dependent_action_ids(
    relationships: tuple[CategoryRelationshipProposal, ...],
    category_by_action_id: Mapping[str, CategoryId | None],
) -> frozenset[str]:
    """Apply only explicitly proposed same-occurrence relationships.

    A dependent observation is removed from the set of competing defining
    actions only when its named principal is itself a validated §L defining
    action.  Citation overlap, source identity, and action ordering never
    participate in this decision.
    """

    return frozenset(
        relationship.dependent_action_id
        for relationship in relationships
        if (
            relationship.relationship_type == "SAME_OCCURRENCE_DEPENDENCE"
            and category_by_action_id.get(relationship.principal_action_id) is not None
            and category_by_action_id.get(relationship.dependent_action_id) is not None
        )
    )


def _relationship_provenance(
    relationships: tuple[
        tuple[CategoryRelationshipProposal, tuple[CategoryEvidenceSpan, ...]],
        ...
    ],
) -> list[dict[str, Any]]:
    return [
        {
            "relationship_type": relationship.relationship_type,
            "member_action_ids": list(relationship.member_action_ids),
            "principal_action_id": relationship.principal_action_id,
            "dependent_action_id": relationship.dependent_action_id,
            "dependence_kind": relationship.dependence_kind,
            "validated_spans": _span_provenance(spans),
        }
        for relationship, spans in relationships
    ]


class Classifier:
    """Sole authoritative owner of Category for an eligible Event Group.

    The injected semantic helper proposes cited action/lifecycle observations,
    never a Category result. This class validates those observations, applies
    the §L mapping once, and owns the terminal state. A proposal it cannot validate raises
    :class:`CategoryProposalViolation`, a disclosed technical gap (RC-16).
    """

    def __init__(self, semantic_helper: CategorySemanticHelper | None = None) -> None:
        self._semantic_helper = semantic_helper

    def classify(
        self,
        event_group: EventGroup,
        records: Sequence[EventIdentityRecord],
    ) -> CategoryResult:
        """Classify exactly one already-grouped Event Group without external I/O."""

        request = _request_for(event_group, records)
        if self._semantic_helper is None:
            return self._unresolved(
                event_group,
                CategoryResolutionReason.SEMANTIC_HELPER_UNAVAILABLE,
                {"decision_basis": "semantic_helper_unavailable"},
            )

        try:
            helper_result = self._semantic_helper(request)
        except (SemanticProviderTechnicalFailure, SemanticProviderConfigurationFailure):
            # RC-6: never converted into CATEGORY_UNRESOLVED.
            raise
        except InvalidCategorySemanticResponse as exc:
            violation = CategoryProposalViolation(str(exc), exc.predicate)
        except Exception as exc:
            return self._unresolved(
                event_group,
                CategoryResolutionReason.SEMANTIC_HELPER_FAILURE,
                {
                    "decision_basis": "semantic_helper_failure",
                    "helper_error_type": type(exc).__name__,
                    **_provider_provenance(getattr(exc, "provenance", None)),
                },
            )
        else:
            violation = None
        if violation is not None:
            # Raised outside the handler: no provider-controlled context.
            raise violation

        helper_provenance: dict[str, str] = {}
        raw_response = helper_result
        if isinstance(helper_result, CategorySemanticHelperResult):
            raw_response = helper_result.proposal
            helper_provenance = _provider_provenance(helper_result.provenance)

        try:
            response = _validate_response(raw_response, request)
        except InvalidCategorySemanticResponse as exc:
            violation = CategoryProposalViolation(str(exc), exc.predicate)
        else:
            violation = None
        if violation is not None:
            raise violation

        provenance = {
            "decision_basis": "classifier_authoritative_domain_mechanism",
            "helper_proposal_role": "advisory_action_lifecycle_relationships",
            "source_candidate_ids": [source.candidate_id for source in request.sources],
            "validated_action_spans": {
                action_id: _span_provenance(spans)
                for action_id, spans in response.action_citation_spans
            },
            "validated_examined_spans": _span_provenance(response.examined_citation_spans),
            "validated_relationships": _relationship_provenance(response.relationship_citation_spans),
            "principal_action_id": response.principal_action_id,
            **helper_provenance,
        }
        category_by_action_id = {
            action.action_id: _classify_action_observation(action)[0]
            for action in response.actions
        }
        dependent_action_ids = _dependent_action_ids(
            response.relationships,
            category_by_action_id,
        )
        defining_actions = tuple(
            action
            for action in response.actions
            if category_by_action_id[action.action_id] is not None
            and action.action_id not in dependent_action_ids
        )
        defining_categories = {
            category_by_action_id[action.action_id]
            for action in defining_actions
        }
        if not defining_categories:
            return self._unresolved(
                event_group,
                _unresolved_reason_without_principal(response.actions),
                provenance,
            )
        action_by_id = {action.action_id: action for action in response.actions}
        selected_action = action_by_id.get(response.principal_action_id or "")
        if (
            selected_action is None
            or category_by_action_id.get(selected_action.action_id) is None
            or selected_action.action_id not in {action.action_id for action in defining_actions}
        ):
            selected_action = None

        if len(defining_actions) > 1 and not _common_decision_covers(
            response.relationships,
            {action.action_id for action in defining_actions},
        ):
            return self._unresolved(
                event_group,
                CategoryResolutionReason.NO_UNIQUE_PRINCIPAL_ACTION,
                provenance,
            )
        if len(defining_categories) > 1 and selected_action is None:
            return self._unresolved(
                event_group,
                CategoryResolutionReason.NO_UNIQUE_PRINCIPAL_ACTION,
                provenance,
            )

        category_id = (
            category_by_action_id[selected_action.action_id]
            if len(defining_categories) > 1 and selected_action is not None
            else next(iter(defining_categories))
        )
        provenance["authoritative_action_ids"] = [action.action_id for action in defining_actions]
        if selected_action is not None:
            provenance["authoritative_action_kind"] = selected_action.action_kind
            provenance["authoritative_lifecycle_relation"] = selected_action.lifecycle_relation
        elif len(defining_actions) > 1:
            provenance["authoritative_action_resolution"] = "COHERENT_COMMON_DECISION_ACTION_SET"
        return CategoryResult(
            category_state=CategoryState.CATEGORY_ASSIGNED,
            event_id=event_group.event_id,
            primary_category_id=category_id,
            primary_category=category_id.display_label,
            subtype=response.subtype,
            classification_reason=f"PRINCIPAL_ACTION_{category_id.value}",
            provenance=provenance,
        )

    evaluate = classify

    @staticmethod
    def _unresolved(
        event_group: EventGroup,
        reason: CategoryResolutionReason,
        provenance: Mapping[str, Any],
    ) -> CategoryResult:
        return CategoryResult(
            category_state=CategoryState.CATEGORY_UNRESOLVED,
            event_id=event_group.event_id,
            classification_reason=CategoryState.CATEGORY_UNRESOLVED.value,
            category_resolution_reason=reason,
            provenance=provenance,
        )
