"""The single V2 owner of candidate-to-candidate Event Identity."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256
import json
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

from .contracts import (
    EvidenceState,
    EventGroup,
    EventIdentityBasis,
    EventIdentityDiagnostic,
    EventIdentityFacts,
    EventIdentityRecord,
    EventIdentityRelation,
    EventIdentityRun,
    EventIdentitySemanticDecision,
    EventIdentitySemanticRequest,
    EventIdentitySupportSpan,
    ScopeState,
    UnresolvedClaim,
)


class EventIdentitySemanticAdvisor(Protocol):
    """Narrow advisory seam; the owner retains the final grouping decision."""

    def __call__(self, request: EventIdentitySemanticRequest) -> object:
        """Return one structured pair proposal."""


class InvalidEventIdentitySemanticResponse(ValueError):
    """The semantic advisor did not return the locked structured response."""


class EventIdentity:
    """Sole authoritative owner for Candidate-to-Candidate Event Equivalence."""

    CONTRACT_VERSION = "event-identity-v1"
    _IDENTITY_FIELDS = (
        "action",
        "lifecycle_step",
        "subject",
        "asset",
        "project",
        "package",
        "location",
        "occurrence_context",
        "occurrence_date",
    )
    _SPECIFIC_ANCHORS = (
        "subject",
        "asset",
        "project",
        "package",
        "location",
    )
    _SUPPORT_ROLES = frozenset({"occurrence", "subject", "lifecycle"})
    _FIRST_HAND_ROLES = frozenset(
        {"first_party", "first_hand", "operator_notice", "government_notice"}
    )

    def __init__(self, semantic_advisor: EventIdentitySemanticAdvisor | None = None):
        self._semantic_advisor = semantic_advisor

    def group(self, records: Sequence[EventIdentityRecord]) -> tuple[EventGroup, ...]:
        """Return deterministic groups; diagnostics are available from evaluate()."""

        return self.evaluate(records).groups

    def evaluate(self, records: Sequence[EventIdentityRecord]) -> EventIdentityRun:
        """Validate upstream eligibility, compare records, and form safe groups."""

        diagnostics: list[EventIdentityDiagnostic] = []
        eligible: list[EventIdentityRecord] = []
        seen_ids: set[str] = set()
        for record in records:
            candidate_id = record.candidate.candidate_id
            if candidate_id in seen_ids:
                raise ValueError(f"duplicate candidate_id: {candidate_id}")
            seen_ids.add(candidate_id)
            if not self._eligible(record):
                diagnostics.append(
                    EventIdentityDiagnostic((candidate_id,), "UPSTREAM_NOT_ELIGIBLE")
                )
                continue
            eligible.append(record)

        ordered = sorted(eligible, key=_record_sort_key)
        groups: list[list[EventIdentityRecord]] = []
        relation_cache: dict[tuple[str, str], tuple[EventIdentityRelation, str]] = {}

        for record in ordered:
            compatible: list[int] = []
            for index, members in enumerate(groups):
                relations = [
                    self._relation(member, record, relation_cache)
                    for member in members
                ]
                if all(relation is EventIdentityRelation.SAME_EVENT for relation, _ in relations):
                    compatible.append(index)
                else:
                    self._record_uncertainty_diagnostics(
                        members,
                        record,
                        relations,
                        diagnostics,
                    )

            if len(compatible) == 1:
                groups[compatible[0]].append(record)
                continue

            if len(compatible) > 1:
                merged_members = [
                    member
                    for index in compatible
                    for member in groups[index]
                ] + [record]
                if self._group_is_invariant(merged_members, relation_cache):
                    first = compatible[0]
                    groups[first] = merged_members
                    for index in reversed(compatible[1:]):
                        del groups[index]
                else:
                    selected = min(
                        compatible,
                        key=lambda index: _group_sort_key(groups[index]),
                    )
                    groups[selected].append(record)
                    diagnostics.append(
                        EventIdentityDiagnostic(
                            tuple(
                                sorted(
                                    item.candidate.candidate_id
                                    for item in merged_members
                                )
                            ),
                            "INSUFFICIENT_IDENTITY",
                            "candidate placed in the stable compatible group; alternate association is unresolved",
                        )
                    )
                continue

            groups.append([record])

        output = tuple(
            sorted(
                (self._make_group(members, relation_cache) for members in groups),
                key=lambda group: group.member_candidate_ids,
            )
        )
        return EventIdentityRun(output, tuple(diagnostics))

    @staticmethod
    def _eligible(record: EventIdentityRecord) -> bool:
        return (
            record.evidence.state is EvidenceState.READY
            and record.scope.state is ScopeState.IN_SCOPE
            and record.temporal.date_valid
        )

    def _relation(
        self,
        left: EventIdentityRecord,
        right: EventIdentityRecord,
        cache: dict[tuple[str, str], tuple[EventIdentityRelation, str]],
    ) -> tuple[EventIdentityRelation, str]:
        key = tuple(sorted((left.candidate.candidate_id, right.candidate.candidate_id)))
        if key in cache:
            return cache[key]

        deterministic = self._deterministic_relation(left, right)
        if deterministic is not None:
            cache[key] = deterministic
            return deterministic

        if self._semantic_advisor is None:
            result = (EventIdentityRelation.UNCERTAIN, "INSUFFICIENT_IDENTITY")
            cache[key] = result
            return result

        request = _semantic_request(left, right)
        try:
            raw = self._semantic_advisor(request)
            decision = _validate_semantic_response(raw, request)
        except Exception:
            result = (EventIdentityRelation.UNCERTAIN, "SEMANTIC_ADVISOR_INVALID")
            cache[key] = result
            return result

        if decision.relation is EventIdentityRelation.SAME_EVENT:
            result = (EventIdentityRelation.SAME_EVENT, "SEMANTIC_SAME_EVENT")
        elif decision.relation is EventIdentityRelation.DISTINCT_EVENT:
            result = (EventIdentityRelation.DISTINCT_EVENT, "SEMANTIC_DISTINCT_EVENT")
        else:
            result = (EventIdentityRelation.UNCERTAIN, "INSUFFICIENT_IDENTITY")
        cache[key] = result
        return result

    def _deterministic_relation(
        self,
        left: EventIdentityRecord,
        right: EventIdentityRecord,
    ) -> tuple[EventIdentityRelation, str] | None:
        left_facts = left.identity_facts
        right_facts = right.identity_facts
        if left_facts is not None and right_facts is not None:
            relation = self._fact_relation(left_facts, right_facts)
            if relation is not None:
                return relation

        if _same_materialized_source(left, right):
            return EventIdentityRelation.SAME_EVENT, "EXACT_SOURCE_BODY"

        if left_facts is None or right_facts is None:
            return None

        return self._fact_relation(left_facts, right_facts)

    def _fact_relation(
        self,
        left_facts: EventIdentityFacts,
        right_facts: EventIdentityFacts,
    ) -> tuple[EventIdentityRelation, str] | None:
        left_action = _fact_value(left_facts, "action")
        right_action = _fact_value(right_facts, "action")
        left_lifecycle = _fact_value(left_facts, "lifecycle_step")
        right_lifecycle = _fact_value(right_facts, "lifecycle_step")
        if not left_action or not right_action or left_action != right_action:
            return None
        if (
            not left_lifecycle
            or not right_lifecycle
            or left_lifecycle != right_lifecycle
        ):
            return None

        for field_name in (*self._SPECIFIC_ANCHORS, "occurrence_context"):
            left_value = _fact_value(left_facts, field_name)
            right_value = _fact_value(right_facts, field_name)
            if left_value and right_value and left_value != right_value:
                return None

        left_context = _fact_value(left_facts, "occurrence_context")
        right_context = _fact_value(right_facts, "occurrence_context")
        if not left_context or not right_context or left_context != right_context:
            return None

        left_date = _fact_value(left_facts, "occurrence_date")
        right_date = _fact_value(right_facts, "occurrence_date")
        if left_date and right_date and left_date != right_date:
            return None

        matching_anchors = [
            field_name
            for field_name in self._SPECIFIC_ANCHORS
            if (
                value := _fact_value(left_facts, field_name)
            )
            and value == _fact_value(right_facts, field_name)
        ]
        if not matching_anchors:
            return None
        return (
            EventIdentityRelation.SAME_EVENT,
            ",".join(("occurrence_context", *matching_anchors)),
        )

    def _group_is_invariant(
        self,
        members: Sequence[EventIdentityRecord],
        cache: dict[tuple[str, str], tuple[EventIdentityRelation, str]],
    ) -> bool:
        return all(
            self._relation(left, right, cache)[0] is EventIdentityRelation.SAME_EVENT
            for index, left in enumerate(members)
            for right in members[index + 1 :]
        )

    @staticmethod
    def _record_uncertainty_diagnostics(
        members: Sequence[EventIdentityRecord],
        record: EventIdentityRecord,
        relations: Sequence[tuple[EventIdentityRelation, str]],
        diagnostics: list[EventIdentityDiagnostic],
    ) -> None:
        for member, (relation, reason) in zip(members, relations):
            if relation is not EventIdentityRelation.UNCERTAIN:
                continue
            diagnostics.append(
                EventIdentityDiagnostic(
                    tuple(sorted((member.candidate.candidate_id, record.candidate.candidate_id))),
                    reason,
                )
            )

    def _make_group(
        self,
        members: Sequence[EventIdentityRecord],
        relation_cache: Mapping[tuple[str, str], tuple[EventIdentityRelation, str]],
    ) -> EventGroup:
        ordered = tuple(sorted(members, key=_candidate_id_sort_key))
        ids = tuple(record.candidate.candidate_id for record in ordered)
        canonical = min(ordered, key=_canonical_sort_key).candidate.candidate_id
        basis = tuple(_identity_basis(record) for record in ordered)
        unresolved = _unresolved_claims(ordered)
        event_id = _event_id(ids)
        return EventGroup(event_id, ids, canonical, basis, unresolved)


def _record_sort_key(record: EventIdentityRecord) -> tuple[str, str]:
    return (
        _normalise_url(record.evidence.canonical_source_url or record.candidate.url),
        record.candidate.candidate_id,
    )


def _candidate_id_sort_key(record: EventIdentityRecord) -> tuple[str]:
    return (record.candidate.candidate_id,)


def _group_sort_key(members: Sequence[EventIdentityRecord]) -> tuple[str, ...]:
    return tuple(sorted(member.candidate.candidate_id for member in members))


def _canonical_sort_key(record: EventIdentityRecord) -> tuple[int, str, str]:
    provenance = record.evidence.provenance
    role = str(provenance.get("source_role", "")).casefold()
    first_hand = provenance.get("first_hand_source") is True or role in EventIdentity._FIRST_HAND_ROLES
    return (
        0 if first_hand else 1,
        _normalise_url(record.evidence.canonical_source_url or record.candidate.url),
        record.candidate.candidate_id,
    )


def _identity_basis(record: EventIdentityRecord) -> EventIdentityBasis:
    facts = record.identity_facts
    if facts is None:
        fields = ("principal_body",)
        references = ("principal_body",)
    else:
        fields = tuple(
            field_name
            for field_name in EventIdentity._IDENTITY_FIELDS
            if _fact_value(facts, field_name)
        )
        references = facts.evidence_references or ("principal_body",)
    return EventIdentityBasis(record.candidate.candidate_id, fields, references)


def _unresolved_claims(
    members: Sequence[EventIdentityRecord],
) -> tuple[UnresolvedClaim, ...]:
    by_key: dict[str, list[tuple[str, str]]] = {}
    for member in members:
        facts = member.identity_facts
        if facts is None:
            continue
        for key, value in facts.non_identity_claims.items():
            by_key.setdefault(key, []).append((member.candidate.candidate_id, value))
    unresolved = []
    for key, values in sorted(by_key.items()):
        distinct_values = {value for _, value in values}
        if len(distinct_values) > 1:
            unresolved.append(UnresolvedClaim(key, tuple(sorted(values))))
    return tuple(unresolved)


def _event_id(member_ids: tuple[str, ...]) -> str:
    payload = {
        "contract_version": EventIdentity.CONTRACT_VERSION,
        "member_candidate_ids": list(member_ids),
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "evt_" + sha256(serialized.encode("utf-8")).hexdigest()[:24]


def _same_materialized_source(left: EventIdentityRecord, right: EventIdentityRecord) -> bool:
    left_url = _normalise_url(left.evidence.canonical_source_url or left.candidate.url)
    right_url = _normalise_url(right.evidence.canonical_source_url or right.candidate.url)
    return bool(
        left_url
        and left_url == right_url
        and left.evidence.substantive_content
        and left.evidence.substantive_content == right.evidence.substantive_content
    )


def _fact_value(facts: EventIdentityFacts, field_name: str) -> str:
    return str(getattr(facts, field_name, "") or "").strip().casefold()


def _normalise_url(value: str) -> str:
    try:
        parsed = urlsplit(value.strip())
    except ValueError:
        return ""
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.netloc:
        return ""
    return urlunsplit(
        (
            parsed.scheme.casefold(),
            parsed.netloc.casefold(),
            parsed.path.rstrip("/") or "/",
            parsed.query,
            "",
        )
    )


def _semantic_request(
    left: EventIdentityRecord,
    right: EventIdentityRecord,
) -> EventIdentitySemanticRequest:
    return EventIdentitySemanticRequest(
        left_candidate_id=left.candidate.candidate_id,
        right_candidate_id=right.candidate.candidate_id,
        left_headline=str(left.evidence.provenance.get("principal_headline", "")),
        right_headline=str(right.evidence.provenance.get("principal_headline", "")),
        left_body=left.evidence.substantive_content,
        right_body=right.evidence.substantive_content,
        left_source_url=left.evidence.canonical_source_url,
        right_source_url=right.evidence.canonical_source_url,
        left_source_type=left.evidence.source_type,
        right_source_type=right.evidence.source_type,
        left_identity_facts=left.identity_facts,
        right_identity_facts=right.identity_facts,
    )


def _validate_semantic_response(
    raw: object,
    request: EventIdentitySemanticRequest,
) -> EventIdentitySemanticDecision:
    if isinstance(raw, EventIdentitySemanticDecision):
        decision = raw
    else:
        if not isinstance(raw, Mapping):
            raise InvalidEventIdentitySemanticResponse("response must be an object")
        expected = {"relation", "support_spans", "contradictions", "missing_support"}
        if set(raw) != expected:
            raise InvalidEventIdentitySemanticResponse("response fields do not match schema")
        relation = raw["relation"]
        try:
            relation_enum = EventIdentityRelation(relation)
        except (TypeError, ValueError) as exc:
            raise InvalidEventIdentitySemanticResponse("invalid relation") from exc
        spans = _parse_support_spans(raw["support_spans"], request)
        contradictions = _parse_strings(raw["contradictions"], "contradictions")
        missing_support = _parse_strings(raw["missing_support"], "missing_support")
        decision = EventIdentitySemanticDecision(
            relation_enum,
            spans,
            contradictions,
            missing_support,
        )

    _validate_decision(decision, request)
    return decision


def _validate_decision(
    decision: EventIdentitySemanticDecision,
    request: EventIdentitySemanticRequest,
) -> None:
    bodies = {
        request.left_candidate_id: request.left_body,
        request.right_candidate_id: request.right_body,
    }
    for span in decision.support_spans:
        if span.candidate_id not in bodies or span.role not in EventIdentity._SUPPORT_ROLES:
            raise InvalidEventIdentitySemanticResponse("support span has an unknown target")
        if (
            isinstance(span.start, bool)
            or not isinstance(span.start, int)
            or isinstance(span.end, bool)
            or not isinstance(span.end, int)
            or span.start < 0
            or span.start >= span.end
            or span.end > len(bodies[span.candidate_id])
        ):
            raise InvalidEventIdentitySemanticResponse("support span is out of range")
    if decision.relation is EventIdentityRelation.SAME_EVENT:
        required = {
            (candidate_id, role)
            for candidate_id in (request.left_candidate_id, request.right_candidate_id)
            for role in EventIdentity._SUPPORT_ROLES
        }
        supplied = {(span.candidate_id, span.role) for span in decision.support_spans}
        if not required.issubset(supplied) or decision.contradictions or decision.missing_support:
            raise InvalidEventIdentitySemanticResponse("SAME_EVENT is insufficiently grounded")
    elif decision.relation is EventIdentityRelation.DISTINCT_EVENT:
        if not decision.support_spans or not decision.contradictions:
            raise InvalidEventIdentitySemanticResponse(
                "DISTINCT_EVENT is insufficiently grounded"
            )


def _parse_support_spans(
    raw: object,
    request: EventIdentitySemanticRequest,
) -> tuple[EventIdentitySupportSpan, ...]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        raise InvalidEventIdentitySemanticResponse("support_spans must be an array")
    bodies = {
        request.left_candidate_id: request.left_body,
        request.right_candidate_id: request.right_body,
    }
    output = []
    for value in raw:
        if not isinstance(value, Mapping) or set(value) != {"candidate_id", "role", "start", "end"}:
            raise InvalidEventIdentitySemanticResponse("invalid support span")
        candidate_id = value["candidate_id"]
        role = value["role"]
        start = value["start"]
        end = value["end"]
        if candidate_id not in bodies or role not in EventIdentity._SUPPORT_ROLES:
            raise InvalidEventIdentitySemanticResponse("support span has an unknown target")
        if (
            isinstance(start, bool)
            or not isinstance(start, int)
            or isinstance(end, bool)
            or not isinstance(end, int)
            or start < 0
            or start >= end
            or end > len(bodies[candidate_id])
        ):
            raise InvalidEventIdentitySemanticResponse("support span is out of range")
        output.append(EventIdentitySupportSpan(candidate_id, role, start, end))
    return tuple(output)


def _parse_strings(raw: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        raise InvalidEventIdentitySemanticResponse(f"{field_name} must be an array")
    if not all(isinstance(value, str) for value in raw):
        raise InvalidEventIdentitySemanticResponse(f"{field_name} must contain strings")
    return tuple(raw)
