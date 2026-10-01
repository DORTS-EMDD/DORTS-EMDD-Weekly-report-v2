"""The sole production owner of Category decisions for post-dedup Event Groups."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Protocol

from .contracts import (
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
    "Classify the evidenced principal current action or lifecycle action of this one Event Group.",
    "Choose exactly one canonical Category when one principal action is supported; otherwise return CATEGORY_UNRESOLVED.",
    "Every semantic proposal, whether CATEGORY_ASSIGNED or CATEGORY_UNRESOLVED, must include at least one citation grounded in supplied evidence.",
    "Each citation must contain a supplied candidate_id and a non-empty exact quote from that candidate's substantive source content. Citations support the proposal as a whole; do not label them support or conflict citations. Never fabricate or rewrite a quote.",
    "TECHNICAL_DEVELOPMENT covers research results, prototypes, pilots, experiments, applied technical tests, technical deployments, and substantive technical development.",
    "INCIDENT covers an actual urban-rail accident, unexpected failure, safety incident, or cybersecurity incident. An actual passenger, staff, or public safety incident in an in-scope urban-rail context remains INCIDENT even when injury is minor or no train, system, evacuation, service, or project impact occurs.",
    "Severity and report value do not determine Category; they belong to downstream Reportability.",
    "OPERATIONAL_CHANGE covers actual passenger or revenue service openings, service or timetable or fare changes, operating-practice changes, evidenced operational disputes, and operational governance actions.",
    "PROCUREMENT covers formal tenders, bid invitations, supplier selections, awards, exercised options, and equivalent formal procurement actions, including innovative, first-of-kind, AI, CBTC, cybersecurity, and pilot-purpose procurements.",
    "NORMATIVE_CHANGE covers published or revised regulations, mandatory technical rules, standards, applicable formal guidance, operator-wide specifications, and formal draft or consultation procedures.",
    "A technology name, equipment mention, procurement object, supplier award, or delivery alone is not technical development.",
    "An ordinary passenger complaint, request, feedback record, or operator log does not by itself establish OPERATIONAL_CHANGE. Without evidenced operator adoption, a service change, a formal operational decision, or another Category-defining action, return CATEGORY_UNRESOLVED with NO_CATEGORY_DEFINING_ACTION.",
    "A completed incident investigation or report whose current principal action is publishing substantive investigation or safety-governance findings, and which establishes no new normative rule, is OPERATIONAL_CHANGE. Do not classify it as INCIDENT only because it discusses an earlier incident or failure.",
    "RECOMMENDATION_WITHOUT_ADOPTED_ACTION applies when evidence establishes a recommendation, proposal, or suggestion, but no competent authority or operator adopted the recommended action and no other Category-defining action controls the event.",
    "NO_CATEGORY_DEFINING_ACTION applies when the supplied content establishes no Category-defining action. Do not use it as a generic substitute when evidence positively establishes an unadopted recommendation.",
    "INSUFFICIENT_CATEGORY_EVIDENCE applies when the supplied evidence is insufficient to determine what Category-defining action occurred; this is distinct from evidence affirmatively establishing that no Category-defining action exists.",
    "Recommendations without adoption, procurement-specific specifications, and citations of existing standards do not by themselves establish an operational dispute or normative change.",
    "Do not rank categories, vote by keywords, infer from source order, or prefer a canonical source. Preserve each source and its claims separately.",
    "CONFLICTING_CATEGORY_DEFINING_CLAIMS applies only when competing evidence disagrees about the action or event fact that determines Category itself and the supplied authoritative evidence cannot resolve the disagreement. Differences only in duration, count, magnitude, exact timing, or consequence extent are not Category conflicts when the Category-defining action remains the same.",
    "NO_UNIQUE_PRINCIPAL_ACTION applies when evidence consistently establishes multiple equal independent Category-defining actions but no unique principal action can be identified; sources need not contradict each other.",
    "Material disagreement about the category-defining action, or multiple equal independent actions without one principal action, requires CATEGORY_UNRESOLVED with the corresponding reason above.",
    "When CATEGORY_ASSIGNED, category_resolution_reason must be null.",
    "Subtype is optional descriptive metadata, may be null when no useful subtype is needed, and never changes the primary Category.",
    "Event identity is already decided. Do not merge or split Event Groups. Ignore discovery metadata, report period, taxonomy, and Reportability.",
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
    absent. Candidate IDs are opaque citation handles, not rank or priority.
    """

    sources: tuple[CategorySourceEvidence, ...]
    unresolved_claims: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = ()

    def __post_init__(self) -> None:
        ids = tuple(source.candidate_id for source in self.sources)
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("Category request requires unique source candidate IDs")
        if ids != tuple(sorted(ids)):
            raise ValueError("Category request sources must be in stable ID order")

    def as_payload(self) -> dict[str, Any]:
        return {
            "contract_reference": "docs/ARCHITECTURE_CONTRACT.md §L",
            "guidance": list(_CATEGORY_GUIDANCE),
            "source_order_is_authoritative": False,
            "sources": [source.as_mapping() for source in self.sources],
            "unresolved_event_claims": [
                {
                    "claim_key": claim_key,
                    "candidate_values": [
                        {"candidate_id": candidate_id, "value": value}
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
    """An untrusted exact source quote supplied in a Category proposal."""

    candidate_id: str
    quote: str


@dataclass(frozen=True, slots=True)
class CategorySemanticResponse:
    """Untrusted structured helper response; Classifier validates it."""

    category_state: CategoryState | str
    primary_category_id: CategoryId | str | None = None
    subtype: str | None = None
    category_resolution_reason: CategoryResolutionReason | str | None = None
    citations: tuple[CategoryCitation, ...] = ()


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

    def __init__(self, message: str, *, provenance: Mapping[str, str] | None = None) -> None:
        super().__init__(message)
        self.provenance = MappingProxyType(dict(provenance or {}))


@dataclass(frozen=True, slots=True)
class _ValidatedCategoryResponse:
    category_state: CategoryState
    primary_category_id: CategoryId | None
    subtype: str | None
    category_resolution_reason: CategoryResolutionReason | None
    citation_spans: tuple[CategoryEvidenceSpan, ...]


_RESPONSE_FIELDS = frozenset(
    {
        "category_state",
        "primary_category_id",
        "subtype",
        "category_resolution_reason",
        "citations",
    }
)
_CITATION_FIELDS = frozenset({"candidate_id", "quote"})
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
        candidate_id, quote = value.candidate_id, value.quote
    else:
        if not isinstance(value, Mapping) or frozenset(value) != _CITATION_FIELDS:
            raise InvalidCategorySemanticResponse("citation fields do not match schema")
        candidate_id = value["candidate_id"]
        quote = value["quote"]
    if not isinstance(candidate_id, str) or not candidate_id:
        raise InvalidCategorySemanticResponse("citation candidate_id must be a string")
    if not isinstance(quote, str) or not quote:
        raise InvalidCategorySemanticResponse("citation quote must be a non-empty string")
    return CategoryCitation(candidate_id, quote)


def _unique_quote_offset(source: str, quote: str) -> int:
    """Return the sole exact quote occurrence, counting overlaps; fail closed otherwise."""

    first = source.find(quote)
    if first < 0:
        raise InvalidCategorySemanticResponse("citation quote does not occur in source content")
    second = source.find(quote, first + 1)
    if second >= 0:
        raise InvalidCategorySemanticResponse("citation quote occurs more than once in source content")
    return first


def _parse_citations(
    value: object,
    request: CategorySemanticRequest,
) -> tuple[CategoryEvidenceSpan, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise InvalidCategorySemanticResponse("citations must be an array")
    source_text = {source.candidate_id: source.substantive_content for source in request.sources}
    spans: list[CategoryEvidenceSpan] = []
    for raw_citation in value:
        citation = _citation_from_value(raw_citation)
        body = source_text.get(citation.candidate_id)
        if body is None:
            raise InvalidCategorySemanticResponse("citation references an unknown candidate")
        start = _unique_quote_offset(body, citation.quote)
        end = start + len(citation.quote)
        if body[start:end] != citation.quote:
            raise InvalidCategorySemanticResponse("citation quote does not exactly match source content")
        spans.append(CategoryEvidenceSpan(citation.candidate_id, start, end))
    return tuple(spans)


def _validate_response(
    raw_response: object,
    request: CategorySemanticRequest,
) -> _ValidatedCategoryResponse:
    if isinstance(raw_response, CategorySemanticResponse):
        payload = {
            "category_state": raw_response.category_state,
            "primary_category_id": raw_response.primary_category_id,
            "subtype": raw_response.subtype,
            "category_resolution_reason": raw_response.category_resolution_reason,
            "citations": raw_response.citations,
        }
    elif isinstance(raw_response, Mapping):
        payload = raw_response
    else:
        raise InvalidCategorySemanticResponse("response must be an object")

    if frozenset(payload) != _RESPONSE_FIELDS:
        raise InvalidCategorySemanticResponse("response fields do not match schema")
    try:
        state = CategoryState(payload["category_state"])
    except (TypeError, ValueError) as exc:
        raise InvalidCategorySemanticResponse("invalid category_state") from exc
    if state not in {CategoryState.CATEGORY_ASSIGNED, CategoryState.CATEGORY_UNRESOLVED}:
        raise InvalidCategorySemanticResponse("helper cannot return NOT_EVALUATED")

    raw_category_id = payload["primary_category_id"]
    if raw_category_id is None:
        category_id = None
    else:
        try:
            category_id = CategoryId(raw_category_id)
        except (TypeError, ValueError) as exc:
            raise InvalidCategorySemanticResponse("invalid primary_category_id") from exc

    subtype = payload["subtype"]
    raw_reason = payload["category_resolution_reason"]
    if raw_reason is None:
        resolution_reason = None
    else:
        try:
            resolution_reason = CategoryResolutionReason(raw_reason)
        except (TypeError, ValueError) as exc:
            raise InvalidCategorySemanticResponse("invalid category_resolution_reason") from exc

    citation_spans = _parse_citations(payload["citations"], request)
    if not citation_spans:
        raise InvalidCategorySemanticResponse("a semantic outcome requires at least one citation")

    if state is CategoryState.CATEGORY_ASSIGNED:
        if category_id is None:
            raise InvalidCategorySemanticResponse("assigned response requires a Category ID")
        if subtype is not None and (
            not isinstance(subtype, str)
            or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", subtype)
        ):
            raise InvalidCategorySemanticResponse(
                "assigned response subtype must be snake_case when present"
            )
        if resolution_reason is not None:
            raise InvalidCategorySemanticResponse("assigned response cannot carry a resolution reason")
    else:
        if category_id is not None or subtype is not None:
            raise InvalidCategorySemanticResponse("unresolved response cannot carry an assigned Category")
        if resolution_reason not in _DOMAIN_UNRESOLVED_REASONS:
            raise InvalidCategorySemanticResponse("unresolved response requires a domain reason")
    return _ValidatedCategoryResponse(
        category_state=state,
        primary_category_id=category_id,
        subtype=subtype,
        category_resolution_reason=resolution_reason,
        citation_spans=citation_spans,
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


class Classifier:
    """Sole authoritative owner of Category for an eligible Event Group.

    The injected semantic helper proposes a structured interpretation of the
    supplied source evidence. This class validates the proposal, owns the
    terminal state, and fails closed to CATEGORY_UNRESOLVED.
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
        except InvalidCategorySemanticResponse as exc:
            return self._unresolved(
                event_group,
                CategoryResolutionReason.SEMANTIC_HELPER_INVALID_RESPONSE,
                {
                    "decision_basis": "semantic_helper_invalid_response",
                    "validation_error": str(exc),
                    **_provider_provenance(exc.provenance),
                },
            )
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

        helper_provenance: dict[str, str] = {}
        raw_response = helper_result
        if isinstance(helper_result, CategorySemanticHelperResult):
            raw_response = helper_result.proposal
            helper_provenance = _provider_provenance(helper_result.provenance)

        try:
            response = _validate_response(raw_response, request)
        except InvalidCategorySemanticResponse as exc:
            return self._unresolved(
                event_group,
                CategoryResolutionReason.SEMANTIC_HELPER_INVALID_RESPONSE,
                {
                    "decision_basis": "semantic_helper_invalid_response",
                    "validation_error": str(exc),
                    **helper_provenance,
                },
            )

        provenance = {
            "decision_basis": "constrained_semantic_helper",
            "source_candidate_ids": [source.candidate_id for source in request.sources],
            # Kept as the stable internal provenance key. Under proposal v4 it
            # means whole-proposal citations, with no support/conflict role split.
            "validated_support_spans": _span_provenance(response.citation_spans),
            **helper_provenance,
        }
        if response.category_state is CategoryState.CATEGORY_UNRESOLVED:
            return self._unresolved(
                event_group,
                response.category_resolution_reason,
                provenance,
            )

        category_id = response.primary_category_id
        if category_id is None:
            return self._unresolved(
                event_group,
                CategoryResolutionReason.SEMANTIC_HELPER_INVALID_RESPONSE,
                {"decision_basis": "semantic_helper_invalid_response"},
            )
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
