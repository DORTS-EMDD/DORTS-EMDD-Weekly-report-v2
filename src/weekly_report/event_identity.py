"""The single V2 owner of candidate-to-candidate Event Identity."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
import json
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

from .contracts import (
    EVENT_TECHNICAL_FAILURES,
    EvidenceState,
    EventGroup,
    EventIdentityBasis,
    EventIdentityDiagnostic,
    EventIdentityFacts,
    EventIdentityGroupingRecord,
    EventIdentityGroupingRequest,
    EventIdentityRecord,
    EventIdentityRelation,
    EventIdentityRun,
    ProposalContractViolation,
    ScopeState,
    TechnicalGap,
    UnresolvedClaim,
)
from .evidence_sentences import event_focus_sentences, resolve_sentence_ids, segment_evidence_sentences


# RC-15/RC-18 bounds (contract sections A.9, A.12). The request payload is
# the only batch bound; leads shrink before a run is ever split, because
# duplicates in different batches cannot be merged.
LEAD_TIERS = ((6, 900), (4, 600), (3, 450), (2, 300))
LEAD_SENTENCE_LIMIT, LEAD_CHARACTER_LIMIT = LEAD_TIERS[0]
BATCH_CHARACTER_LIMIT = 66_000

EVENT_IDENTITY_GROUPING_RESPONSE_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "groups": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "members": {
                        "type": "array",
                        "minItems": 2,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "record_id": {"type": "string"},
                                "subject_sentence_ids": {"type": "array", "items": {"type": "string"}},
                                "occurrence_sentence_ids": {"type": "array", "items": {"type": "string"}},
                                "lifecycle_sentence_ids": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": [
                                "record_id",
                                "subject_sentence_ids",
                                "occurrence_sentence_ids",
                                "lifecycle_sentence_ids",
                            ],
                        },
                    },
                },
                "required": ["members"],
            },
        },
    },
    "required": ["groups"],
}
# RC-31: a confirmation places a separated record as its own one-record group
# (RC-25), so its declared schema admits one-member groups. Before RC-31 the
# confirmation was sent the grouping schema above, whose ``minItems: 2``
# forbade the very answer the instruction required; the helper resolved the
# contradiction by leaving separated records out (CONFIRMATION_INCOMPLETE).
EVENT_IDENTITY_CONFIRMATION_RESPONSE_SCHEMA: dict[str, object] = json.loads(
    json.dumps(EVENT_IDENTITY_GROUPING_RESPONSE_SCHEMA)
)
EVENT_IDENTITY_CONFIRMATION_RESPONSE_SCHEMA["properties"]["groups"]["items"]["properties"]["members"]["minItems"] = 1  # type: ignore[index]


def grouping_response_schema(request: EventIdentityGroupingRequest) -> dict[str, object]:
    """The response schema the helper is held to for this request."""

    return EVENT_IDENTITY_CONFIRMATION_RESPONSE_SCHEMA if request.confirmation else EVENT_IDENTITY_GROUPING_RESPONSE_SCHEMA


_MEMBER_KEYS = frozenset(
    EVENT_IDENTITY_GROUPING_RESPONSE_SCHEMA["properties"]["groups"]["items"]  # type: ignore[index]
    ["properties"]["members"]["items"]["required"]
)
_CITATION_KEYS = tuple(sorted(_MEMBER_KEYS - {"record_id"}))


class EventIdentityGroupingAdvisor(Protocol):
    """Proposal-only seam (RC-15); the owner retains the grouping decision."""

    def __call__(self, request: EventIdentityGroupingRequest) -> object:
        """Return one parsed grouping proposal object."""


class EventIdentityProposalViolation(ProposalContractViolation):
    """A parseable grouping proposal (or one group of it) broke its contract."""

    def __init__(self, failure_class: str, candidate_ids: tuple[str, ...] = ()) -> None:
        super().__init__(failure_class)
        self.failure_class = failure_class
        # RC-40/RC-42 (observation only): the members a group rejected.
        self.candidate_ids = candidate_ids


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
    _FIRST_HAND_ROLES = frozenset(
        {"first_party", "first_hand", "operator_notice", "government_notice"}
    )

    def __init__(self, grouping_advisor: EventIdentityGroupingAdvisor | None = None):
        self._grouping_advisor = grouping_advisor

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

        technical_gaps: list[TechnicalGap] = []
        excerpts: dict[str, tuple[str, ...]] = {}
        proposed, excerpt_limits = self._proposed_relations(eligible, diagnostics, technical_gaps, excerpts)
        ordered = sorted(eligible, key=_record_sort_key)
        groups: list[list[EventIdentityRecord]] = []
        relation_cache: dict[tuple[str, str], tuple[EventIdentityRelation, str]] = {}

        for record in ordered:
            compatible: list[int] = []
            for index, members in enumerate(groups):
                relations = [
                    self._relation(member, record, relation_cache, proposed)
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
                if self._group_is_invariant(merged_members, relation_cache, proposed):
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
        return EventIdentityRun(output, tuple(diagnostics), tuple(technical_gaps), excerpts, excerpt_limits)

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
        proposed: Mapping[tuple[str, str], tuple[EventIdentityRelation, str]],
    ) -> tuple[EventIdentityRelation, str]:
        key = _pair_key(left.candidate.candidate_id, right.candidate.candidate_id)
        if key in cache:
            return cache[key]

        result = self._deterministic_relation(left, right) or proposed.get(
            key, (EventIdentityRelation.UNCERTAIN, "INSUFFICIENT_IDENTITY")
        )
        cache[key] = result
        return result

    def _proposed_relations(
        self,
        eligible: Sequence[EventIdentityRecord],
        diagnostics: list[EventIdentityDiagnostic],
        technical_gaps: list[TechnicalGap],
        excerpts: dict[str, tuple[str, ...]],
    ) -> tuple[dict[tuple[str, str], tuple[EventIdentityRelation, str]], str]:
        """Validate the RC-15 grouping proposals into SAME_EVENT pair relations.

        Also fills ``excerpts`` with the sentence IDs each record was sent with
        and returns the excerpt limits used (RC-32, observation only).
        """

        relations: dict[tuple[str, str], tuple[EventIdentityRelation, str]] = {}
        if self._grouping_advisor is None:
            return relations, ""
        requests, (sentence_limit, character_limit) = _grouping_requests(eligible)
        for request in requests:
            excerpts.update((record.candidate_id, record.source_sentence_ids) for record in request.records)
        excerpt_limits = f"{sentence_limit}x{character_limit}" if requests else ""
        by_id = {record.candidate.candidate_id: record for record in eligible}
        if len(requests) > 1:
            # Pairs in different batches cannot be merged; keep that visible.
            diagnostics.append(
                EventIdentityDiagnostic(
                    tuple(sorted(record.candidate_id for request in requests[1:] for record in request.records)),
                    "PROPOSAL_BATCH_SPLIT",
                    f"{len(requests)} batches",
                )
            )
        for request in requests:
            try:
                proposal = _validate_grouping_proposal(self._grouping_advisor(request), request)
            except EVENT_TECHNICAL_FAILURES as failure:
                technical_gaps.append(TechnicalGap.from_failure("EventIdentity", request.batch_id, failure))
                continue
            for index, (outcome, violations) in enumerate(proposal, start=1):
                group_subject = f"{request.batch_id}:group-{index}"
                for violation in violations:
                    technical_gaps.append(TechnicalGap.from_failure("EventIdentity", group_subject, violation))
                    _record_rejected_members(diagnostics, group_subject, violation)
                if len(outcome) < 2:
                    if outcome and not violations:
                        diagnostics.append(EventIdentityDiagnostic(outcome, "SINGLE_MEMBER_PROPOSAL"))
                    continue
                pairs = []
                for position, left_id in enumerate(outcome):
                    for right_id in outcome[position + 1 :]:
                        if _different_established_regions(by_id[left_id], by_id[right_id]):
                            # RC-22: one occurrence happens in one country/region.
                            diagnostics.append(
                                EventIdentityDiagnostic(
                                    tuple(sorted((left_id, right_id))),
                                    "PROPOSAL_REGION_CONFLICT",
                                    f"{group_subject}|size={len(outcome)}",
                                )
                            )
                            continue
                        pairs.append(_pair_key(left_id, right_id))
                if not pairs:
                    continue
                confirmed, placement = self._confirmed_pairs(
                    [by_id[candidate_id] for candidate_id in outcome],
                    f"{group_subject}:confirmation",
                    technical_gaps,
                    diagnostics,
                )
                for pair in pairs:
                    if pair not in confirmed:
                        # Observation only (RC-31): why the pair stayed apart.
                        diagnostics.append(
                            EventIdentityDiagnostic(
                                pair,
                                "PROPOSAL_NOT_CONFIRMED",
                                f"{group_subject}|size={len(outcome)}|{_unconfirmed_outcome(pair, placement)}",
                            )
                        )
                        continue
                    relations[pair] = (EventIdentityRelation.SAME_EVENT, "SEMANTIC_GROUP_PROPOSAL")
        return relations, excerpt_limits

    def _confirmed_pairs(
        self,
        members: Sequence[EventIdentityRecord],
        batch_id: str,
        technical_gaps: list[TechnicalGap],
        diagnostics: list[EventIdentityDiagnostic],
    ) -> tuple[set[tuple[str, str]], dict[str, str] | None]:
        """RC-23: re-run the grouping task on one proposed group's members alone.

        Only pairs that the confirmation proposes together again are confirmed;
        a failed or invalid confirmation confirms nothing and is a disclosed gap.
        RC-25: the confirmation must place every record (a separated record as
        a one-record group); an omitted record is undecided, so its pairs stay
        unconfirmed and the omission is a disclosed gap.

        Also returns where the confirmation placed each candidate (``PLACED``,
        ``OMITTED`` or ``MEMBER_INVALID``), or None when the confirmation failed
        as a whole; this only explains unconfirmed pairs and decides nothing.
        """

        ordered = sorted(members, key=_publication_sort_key)
        records = tuple(
            _grouping_record(record, f"R{index}") for index, record in enumerate(ordered, start=1)
        )
        request = EventIdentityGroupingRequest(batch_id, records, confirmation=True)
        try:
            raw = self._grouping_advisor(request)
            proposal = _validate_grouping_proposal(raw, request)
        except EVENT_TECHNICAL_FAILURES as failure:
            technical_gaps.append(TechnicalGap.from_failure("EventIdentity", batch_id, failure))
            return set(), None
        named = {member["record_id"] for group in raw["groups"] for member in group["members"]}
        if any(record.record_id not in named for record in records):
            technical_gaps.append(
                TechnicalGap.from_failure(
                    "EventIdentity", batch_id, EventIdentityProposalViolation("CONFIRMATION_INCOMPLETE")
                )
            )
        placement = {
            record.candidate_id: "MEMBER_INVALID" if record.record_id in named else "OMITTED" for record in records
        }
        confirmed: set[tuple[str, str]] = set()
        for index, (outcome, violations) in enumerate(proposal, start=1):
            for violation in violations:
                technical_gaps.append(TechnicalGap.from_failure("EventIdentity", f"{batch_id}:group-{index}", violation))
                _record_rejected_members(diagnostics, f"{batch_id}:group-{index}", violation)
            placement.update(dict.fromkeys(outcome, "PLACED"))
            for position, left_id in enumerate(outcome):
                for right_id in outcome[position + 1 :]:
                    confirmed.add(_pair_key(left_id, right_id))
        return confirmed, placement

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
        proposed: Mapping[tuple[str, str], tuple[EventIdentityRelation, str]],
    ) -> bool:
        return all(
            self._relation(left, right, cache, proposed)[0] is EventIdentityRelation.SAME_EVENT
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


def _record_rejected_members(
    diagnostics: list[EventIdentityDiagnostic],
    subject: str,
    violation: EventIdentityProposalViolation,
) -> None:
    """RC-40/RC-42 (observation only): which members a proposal group rejected.

    The members are rejected exactly as section A.30 requires; this only
    records the group subject, the failure class and the rejected candidate
    IDs, so a run can show which records lost their pairs. No source text is
    kept.
    """

    if violation.candidate_ids:
        diagnostics.append(
            EventIdentityDiagnostic(violation.candidate_ids, "PROPOSAL_MEMBER_REJECTED", f"{subject}|{violation.failure_class}")
        )


def _unconfirmed_outcome(pair: tuple[str, str], placement: Mapping[str, str] | None) -> str:
    """Why a proposed pair was not confirmed, for its diagnostic only."""

    if placement is None:
        return "CONFIRMATION_FAILED"
    states = {placement[candidate_id] for candidate_id in pair}
    for state in ("OMITTED", "MEMBER_INVALID"):
        if state in states:
            return state
    return "SEPARATED"


def _pair_key(left_id: str, right_id: str) -> tuple[str, str]:
    return tuple(sorted((left_id, right_id)))  # type: ignore[return-value]


def _advisor_identity_facts(facts: EventIdentityFacts | None) -> dict[str, str]:
    """Identity-only projection (section K): never country, system name or support."""

    if facts is None:
        return {}
    return {
        field_name: str(getattr(facts, field_name) or "")
        for field_name in ("event_key", *EventIdentity._IDENTITY_FIELDS)
    }


def _different_established_regions(left: EventIdentityRecord, right: EventIdentityRecord) -> bool:
    """True when EvidenceService established different regions for the two records."""

    regions = []
    for record in (left, right):
        resolution = getattr(record.evidence.identity_facts, "region_resolution", None)
        if resolution is None or not resolution.established:
            return False
        regions.append(resolution.region_id)
    return regions[0] != regions[1]


def _grouping_record(
    record: EventIdentityRecord,
    record_id: str,
    lead_limits: tuple[int, int] = LEAD_TIERS[0],
) -> EventIdentityGroupingRecord | None:
    sentence_limit, character_limit = lead_limits
    lead = []
    characters = 0
    content = record.evidence.substantive_content
    # RC-20: compare Candidate events, so the excerpt is the Candidate's own
    # Scope event focus; without a recorded focus it is the document lead.
    focus = event_focus_sentences(content, dict(record.scope.provenance).get("candidate_event_focus"))
    for sentence in focus or segment_evidence_sentences(content):
        if len(lead) >= sentence_limit or (lead and characters + len(sentence.text) > character_limit):
            break
        lead.append(sentence)
        characters += len(sentence.text)
    if not lead:
        return None
    # RC-42: within a request the excerpt is numbered S1, S2, … in order. A
    # record whose only sentence kept its document ID (say S2) was cited as S1
    # and lost its group; the RC-9 IDs are kept for observation only.
    numbered = tuple(replace(sentence, sentence_id=f"S{index}") for index, sentence in enumerate(lead, start=1))
    return EventIdentityGroupingRecord(
        record_id,
        record.candidate.candidate_id,
        numbered,
        _advisor_identity_facts(record.identity_facts),
        tuple(sentence.sentence_id for sentence in lead),
    )


def _publication_sort_key(record: EventIdentityRecord) -> tuple[str, str, str]:
    """Order records by discovery publication time (sections A.9, A.12), then candidate ID.

    The RSS value is RFC 822 text that starts with the weekday name, so sorting
    the raw string ordered a week by weekday name (RC-42). A value that parses
    neither as RFC 822 nor as ISO 8601 sorts first, as a missing value did.
    """

    raw = str(record.candidate.published_at or "").strip()
    instant = ""
    if raw:
        try:
            parsed = parsedate_to_datetime(raw)
        except (TypeError, ValueError, IndexError):
            try:
                parsed = datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith(("Z", "z")) else raw)
            except ValueError:
                parsed = None
        if parsed is not None:
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            instant = parsed.astimezone(timezone.utc).isoformat()
    return instant, raw, record.candidate.candidate_id


def _payload_size(record: EventIdentityGroupingRecord) -> int:
    return len(json.dumps(record.as_payload(), ensure_ascii=False))


def proposal_subject_level(subject_id: str) -> str:
    """Which request an EventIdentity TechnicalGap names, for observation only.

    Subjects are formed in ``_proposed_relations`` and ``_confirmed_pairs``:
    a batch, one group of a batch proposal, a group's confirmation request,
    or one group of a confirmation response.
    """

    parts = subject_id.split(":")
    if len(parts) == 1:
        return "BATCH"
    if parts[-1] == "confirmation":
        return "CONFIRMATION"
    return "CONFIRMATION_GROUP" if "confirmation" in parts else "GROUP"


def _grouping_requests(
    eligible: Sequence[EventIdentityRecord],
) -> tuple[list[EventIdentityGroupingRequest], tuple[int, int]]:
    """One request for the whole run whenever its payload fits (RC-18).

    The first lead tier whose total payload fits the bound is used for every
    record. Only when even the shortest leads do not fit is the run split into
    consecutive batches ordered by discovery publication time. Also returns
    the lead tier used.
    """

    ordered = sorted(eligible, key=_publication_sort_key)
    for lead_limits in LEAD_TIERS:
        built = [_grouping_record(record, f"R{index}", lead_limits) for index, record in enumerate(ordered, start=1)]
        kept = [item for item in built if item is not None]
        if sum(_payload_size(item) for item in kept) <= BATCH_CHARACTER_LIMIT:
            records = [replace(item, record_id=f"R{index}") for index, item in enumerate(kept, start=1)]
            requests = [EventIdentityGroupingRequest("event-identity-batch-1", tuple(records))] if len(records) >= 2 else []
            return requests, lead_limits

    batches: list[list[EventIdentityRecord]] = [[]]
    characters = 0
    for record in ordered:
        grouping_record = _grouping_record(record, "R1", LEAD_TIERS[-1])
        if grouping_record is None:
            continue
        size = _payload_size(grouping_record)
        if batches[-1] and characters + size > BATCH_CHARACTER_LIMIT:
            batches.append([])
            characters = 0
        batches[-1].append(record)
        characters += size
    requests = []
    for batch in (batch for batch in batches if len(batch) >= 2):
        records = tuple(
            _grouping_record(record, f"R{index}", LEAD_TIERS[-1]) for index, record in enumerate(batch, start=1)
        )
        requests.append(EventIdentityGroupingRequest(f"event-identity-batch-{len(requests) + 1}", records))
    return requests, LEAD_TIERS[-1]


def _validate_grouping_proposal(
    raw: object,
    request: EventIdentityGroupingRequest,
) -> list[tuple[tuple[str, ...], tuple[EventIdentityProposalViolation, ...]]]:
    """Return, per proposed group, its accepted member IDs and its rejected members.

    Raises EventIdentityProposalViolation when the whole response is invalid
    (wrong shape or an unknown record). A record may be named in several
    groups (RC-21): each group only proposes SAME_EVENT pairs, and the
    complete-link grouping merges a record only with records proposed with it.
    RC-42: validation is per member. A record named twice in one group
    (``DUPLICATE_MEMBERSHIP``) and, in a group of two or more records, a record
    whose citation does not resolve (``CITATION_INVALID``) is rejected; the
    group's other members stand. A one-record group proposes no merge and
    needs no citation.
    """

    if not isinstance(raw, Mapping) or set(raw) != {"groups"} or not isinstance(raw["groups"], list):
        raise EventIdentityProposalViolation("SCHEMA_INVALID")
    records = {record.record_id: record for record in request.records}
    for group in raw["groups"]:
        if not isinstance(group, Mapping) or set(group) != {"members"} or not isinstance(group["members"], list):
            raise EventIdentityProposalViolation("SCHEMA_INVALID")
        for member in group["members"]:
            if (
                not isinstance(member, Mapping)
                or set(member) != _MEMBER_KEYS
                or not isinstance(member["record_id"], str)
                or any(not isinstance(member[key], list) for key in _CITATION_KEYS)
            ):
                raise EventIdentityProposalViolation("SCHEMA_INVALID")
            if member["record_id"] not in records:
                raise EventIdentityProposalViolation("UNKNOWN_RECORD")

    outcomes: list[tuple[tuple[str, ...], tuple[EventIdentityProposalViolation, ...]]] = []
    for group in raw["groups"]:
        listings: dict[str, list[Mapping[str, object]]] = {}
        for member in group["members"]:
            listings.setdefault(member["record_id"], []).append(member)
        repeated = [record_id for record_id, items in listings.items() if len(items) > 1]
        ungrounded = [
            record_id
            for record_id, items in listings.items()
            if len(listings) > 1
            and record_id not in repeated
            and any(
                resolve_sentence_ids(records[record_id].sentences, item[key]) is None
                for item in items
                for key in _CITATION_KEYS
            )
        ]
        accepted = tuple(
            records[record_id].candidate_id for record_id in listings if record_id not in repeated + ungrounded
        )
        violations = tuple(
            EventIdentityProposalViolation(failure_class, tuple(sorted(records[record_id].candidate_id for record_id in rejected)))
            for failure_class, rejected in (("DUPLICATE_MEMBERSHIP", repeated), ("CITATION_INVALID", ungrounded))
            if rejected
        )
        outcomes.append((accepted, violations))
    return outcomes
