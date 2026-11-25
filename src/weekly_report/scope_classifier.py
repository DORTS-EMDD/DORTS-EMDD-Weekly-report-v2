"""Candidate-stage Scope owner and bounded semantic proposal seam."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable, Protocol

from .contracts import (
    EvidenceResult,
    EvidenceState,
    MonitoredCheckMonth,
    MonitoredStandardChange,
    ProposalContractViolation,
    StandardLifecycleAction,
    ScopeDiagnostic,
    ScopeResult,
    ScopeState,
    SemanticProviderConfigurationFailure,
    SemanticProviderTechnicalFailure,
)
from .monitored_standards import monitored_standards
from .evidence_sentences import (
    EvidenceSentence,
    cited_text,
    resolve_sentence_ids,
    segment_evidence_sentences,
)


class ScopeSemanticSupport(StrEnum):
    IN_SCOPE_SUPPORT = "IN_SCOPE_SUPPORT"
    OUT_OF_SCOPE_SUPPORT = "OUT_OF_SCOPE_SUPPORT"
    UNCERTAIN = "UNCERTAIN"


@dataclass(frozen=True, slots=True)
class ScopeSupportSpan:
    start: int
    end: int


_LABEL_LOCATIONS_NOTE = (
    "label_locations lists, for each label of your previous proposal, the sentence_ids whose text contains that "
    "label exactly, as found by Python. A label listed with no sentence_ids occurs in no sentence. Cite sentences "
    "that contain the labels the rule requires, or choose labels that the cited sentences contain."
)
_CORRECTION_INSTRUCTION = (
    "Your previous proposal broke the rule named in violated_rule, in the fields listed in fields_at_fault. "
    "Return one complete proposal, in the same schema, that obeys that rule. Keep every conclusion the source "
    "supports; change only what the rule requires and what follows from it. Cite only sentence_ids and copy "
    "labels exactly from one sentence. Do not explain."
)


@dataclass(frozen=True, slots=True)
class ScopeCorrection:
    """RC-75: what the one correction request tells the helper.

    Python names the contract predicate it rejected, the fields at fault and
    the rule in words, and returns the helper's own rejected proposal. The
    helper is stateless, so it needs its earlier answer to correct it. The
    text is Python's; no source text is added.
    """

    predicate: str
    fields: tuple[str, ...]
    rule: str
    rejected_proposal: Mapping[str, Any]
    # RC-85 (section A.66): Python-computed facts, the sentence_ids whose text
    # contains each label of the rejected proposal (empty when a label occurs
    # in no sentence). The proposal is still validated by Python afterwards.
    label_sentence_ids: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def as_payload(self) -> dict[str, Any]:
        payload = {
            "violated_rule": self.predicate,
            "fields_at_fault": list(self.fields),
            "rule": self.rule,
            "instruction": _CORRECTION_INSTRUCTION,
            "rejected_proposal": dict(self.rejected_proposal),
        }
        if self.label_sentence_ids:
            payload["label_locations"] = {name: list(ids) for name, ids in self.label_sentence_ids.items()}
            payload["label_locations_note"] = _LABEL_LOCATIONS_NOTE
        return payload

    def record(self, outcome: str) -> dict[str, Any]:
        """IDs-only observation of this correction: no source or proposal text."""

        return {
            "predicate": self.predicate,
            "fields": list(self.fields),
            "outcome": outcome,
            # RC-85: the label locations Python sent (sentence IDs only).
            "label_sentence_ids": {name: list(ids) for name, ids in self.label_sentence_ids.items()},
        }


@dataclass(frozen=True, slots=True)
class ScopeSemanticRequest:
    candidate_id: str
    candidate_title: str
    principal_content: str
    source_metadata: Mapping[str, Any]
    # RC-9: the helper reads and cites Python-segmented sentences.
    principal_sentences: tuple[EvidenceSentence, ...] = field(init=False)
    # RC-75: present only on the one correction request.
    correction: ScopeCorrection | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "principal_sentences", segment_evidence_sentences(self.principal_content))

    def as_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "candidate_id": self.candidate_id,
            "candidate_title": self.candidate_title,
            "principal_sentences": [sentence.as_mapping() for sentence in self.principal_sentences],
            "source_metadata": dict(self.source_metadata),
        }
        if self.correction is not None:
            payload["correction"] = self.correction.as_payload()
        return payload


@dataclass(frozen=True, slots=True)
class MonitoredStandardScopeRequest:
    """RC-59: the monthly check's question for one Candidate naming a monitored standard.

    ``monitored_identifiers`` are the identifiers Python found in the
    principal content; the helper may answer only one of them or null. The
    helper is not given the list and decides nothing.
    """

    candidate_id: str
    principal_content: str
    monitored_identifiers: tuple[str, ...]
    principal_sentences: tuple[EvidenceSentence, ...] = field(init=False)

    def __post_init__(self) -> None:
        identifiers = tuple(self.monitored_identifiers)
        if not identifiers or len(identifiers) != len(set(identifiers)):
            raise ValueError("MonitoredStandardScopeRequest requires unique monitored identifiers")
        object.__setattr__(self, "monitored_identifiers", identifiers)
        object.__setattr__(self, "principal_sentences", segment_evidence_sentences(self.principal_content))

    def as_payload(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "principal_sentences": [sentence.as_mapping() for sentence in self.principal_sentences],
            "monitored_identifiers": list(self.monitored_identifiers),
        }


MONITORED_STANDARD_PROPOSAL_FIELDS = frozenset(
    {"candidate_id", "changed_standard", "lifecycle_action", "sentence_ids", "rationale"}
)


def _monitored_change(
    value: object, request: MonitoredStandardScopeRequest, check_month: MonitoredCheckMonth
) -> MonitoredStandardChange | None:
    """Validate the helper's answer; Python owns list membership and citation (RC-59)."""

    if not isinstance(value, Mapping) or frozenset(value) != MONITORED_STANDARD_PROPOSAL_FIELDS:
        raise _Violation("MONITORED_STANDARD_SHAPE")
    if value["candidate_id"] != request.candidate_id:
        raise _Violation("MONITORED_STANDARD_CANDIDATE")
    if not isinstance(value["rationale"], str) or not value["rationale"].strip():
        raise _Violation("MONITORED_STANDARD_SHAPE")
    changed, action, sentence_ids = value["changed_standard"], value["lifecycle_action"], value["sentence_ids"]
    if not isinstance(sentence_ids, list):
        raise _Violation("MONITORED_STANDARD_SHAPE")
    if changed is None:
        if action is not None or sentence_ids:
            raise _Violation("MONITORED_STANDARD_SHAPE")
        return None
    if changed not in request.monitored_identifiers:
        raise _Violation("MONITORED_STANDARD_NOT_SUPPLIED")
    try:
        action = StandardLifecycleAction(action)
    except (TypeError, ValueError):
        raise _Violation("MONITORED_STANDARD_ACTION") from None
    cited = resolve_sentence_ids(request.principal_sentences, sentence_ids)
    if not sentence_ids or cited is None:
        raise _Violation("MONITORED_STANDARD_CITATION")
    if not any(changed in monitored_standards().identifiers_in(sentence.text) for sentence in cited):
        raise _Violation("MONITORED_STANDARD_NOT_IN_CITATION")
    return MonitoredStandardChange(changed, action, tuple(sentence.sentence_id for sentence in cited), check_month)


@dataclass(frozen=True, slots=True)
class ScopeSemanticResponse:
    """Helper response. A span-only response is intentionally never accepted."""

    support: ScopeSemanticSupport | str = ScopeSemanticSupport.UNCERTAIN
    support_spans: tuple[ScopeSupportSpan, ...] = ()
    diagnostic: ScopeDiagnostic = ScopeDiagnostic.SCOPE_NOT_ESTABLISHED
    # Kept for source compatibility with the previous seam; these fields do
    # not establish Scope without a complete ``proposal``.
    proposal: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ScopeValidationObservation:
    """Read-only facts emitted from the owner's existing validation pass.

    ``scope_state`` and ``diagnostic`` are None when the proposal violated its
    contract: no Scope decision exists for that Candidate.
    """

    first_rejection_predicate: str | None
    response_status: str
    scope_state: ScopeState | None
    diagnostic: ScopeDiagnostic | None
    # RC-75: the predicate that caused the one correction request, if any.
    correction_predicate: str | None = None


class ScopeProposalViolation(ProposalContractViolation):
    """RC-9: a parseable Scope proposal the owner cannot validate.

    It is a disclosed Candidate TechnicalGap, never OUT_OF_SCOPE: a system or
    helper defect must not be presented as news that failed the Scope rule.
    """

    def __init__(
        self,
        predicate: str,
        observation: Mapping[str, Any] | None = None,
        correction: Mapping[str, Any] | None = None,
    ) -> None:
        self.failure_class = predicate
        # RC-66, observation only: the rejected proposal's structure with
        # sentence IDs and no source text (see ``_rejected_proposal_shape``).
        self.observation = observation
        # RC-75, observation only: the correction request that preceded this gap.
        self.scope_correction = correction
        super().__init__(f"Scope proposal violated its contract: {predicate}")


_SHAPE_RECORDS = ("event_focus", "action_target", "target_system", "ambiguity", "noneligible_relation")
_SHAPE_LABELS = (("action", "label"), ("target", "label"), ("system", "label"), ("target_system", "target_reference"))


def _rejected_proposal_shape(proposal: object, request: "ScopeSemanticRequest") -> dict[str, Any] | None:
    """IDs-only facts about a rejected proposal, for the selection audit (RC-66).

    For each record: its status, relation and cited sentence IDs as proposed.
    For each label: its length and the sentence IDs whose text contains it
    (case-insensitive), so a reader can tell a label absent from the Evidence
    from one outside the cited or focus sentences. No label or source text is
    kept, and nothing here takes part in the decision.
    """

    try:
        if not isinstance(proposal, Mapping):
            return None
        shape: dict[str, Any] = {"records": {}, "labels": {}}
        for name in _SHAPE_RECORDS:
            record = proposal.get(name)
            if isinstance(record, Mapping):
                ids = record.get("sentence_ids")
                shape["records"][name] = {
                    "status": str(record.get("status")) if record.get("status") is not None else None,
                    "relation": str(record["relation"]) if isinstance(record.get("relation"), str) else None,
                    "sentence_ids": [str(item) for item in ids][:40] if isinstance(ids, (list, tuple)) else None,
                }
        for role, key in _SHAPE_LABELS:
            record = proposal.get(role)
            label = record.get(key) if isinstance(record, Mapping) else None
            if not isinstance(label, str) or not label.strip():
                continue
            folded = label.casefold()
            shape["labels"][role if key == "label" else "target_reference"] = {
                "length": len(label),
                "found_in_sentence_ids": [
                    sentence.sentence_id for sentence in request.principal_sentences if folded in sentence.text.casefold()
                ][:40],
            }
        for key in ("eligible_mode_family", "event_status", "decision", "noneligible_kind"):
            if isinstance(proposal.get(key), str):
                shape[key] = proposal[key]
        return shape
    except Exception:
        return None


class ScopeSemanticHelper(Protocol):
    def __call__(self, request: ScopeSemanticRequest) -> ScopeSemanticResponse | Mapping[str, Any] | object:
        ...


SCOPE_PROPOSAL_SCHEMA_VERSION = "scope-semantic-proposal-v4"
SUPPORTED_SCOPE_MODE_FAMILIES = (
    "METRO", "MRT", "SUBWAY", "LIGHT_RAIL", "TRAM", "URBAN_RAIL", "AGT", "MONORAIL", "PEOPLE_MOVER"
)

_LABEL_DESCRIPTION = "Short exact source-surface substring naming the {role}. It must appear inside the sentences cited by the relation that establishes it."
_SENTENCE_IDS = {"type": "array", "items": {"type": "string"}}


def _cited(description: str) -> dict[str, Any]:
    return {**_SENTENCE_IDS, "description": description}


SCOPE_SEMANTIC_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "RC-9: cite Evidence only by sentence_id from principal_sentences; never copy source text into a citation. action and target labels must appear inside the sentences cited by action_target; target_reference (or the target label) and the system label must appear inside the sentences cited by target_system; every relation sentence must lie within the event_focus sentence range.",
    "additionalProperties": False,
    "properties": {
        "candidate_id": {"type": "string"},
        "schema_version": {"type": "string", "enum": [SCOPE_PROPOSAL_SCHEMA_VERSION]},
        "event_focus": {"type": "object", "additionalProperties": False, "properties": {"status": {"type": "string", "enum": ["RESOLVED", "UNRESOLVED", "CONFLICTING"]}, "sentence_ids": _cited("Required and nonempty for RESOLVED or CONFLICTING: the sentences describing the Candidate event; the focus is the range from the first to the last cited sentence. Empty for UNRESOLVED.")}, "required": ["status", "sentence_ids"]},
        "action": {"type": "object", "additionalProperties": False, "properties": {"label": {"type": "string", "description": _LABEL_DESCRIPTION.format(role="asserted action")}}, "required": ["label"]},
        "target": {"type": "object", "additionalProperties": False, "properties": {"label": {"type": "string", "description": _LABEL_DESCRIPTION.format(role="claimed affected target, or the station, platform, train or facility where the Candidate event takes place")}}, "required": ["label"]},
        "system": {"type": "object", "additionalProperties": False, "properties": {"label": {"type": "string", "description": _LABEL_DESCRIPTION.format(role="transport system") + " Empty is allowed when the system is unknown or unestablished. It may equal the target label when the action affects the system itself."}}, "required": ["label"]},
        "eligible_mode_family": {"type": "string", "enum": [*SUPPORTED_SCOPE_MODE_FAMILIES, "NON_ELIGIBLE", "UNKNOWN"]},
        "action_target": {"type": "object", "additionalProperties": False, "properties": {"status": {"type": "string", "enum": ["ESTABLISHED", "UNESTABLISHED", "CONFLICTING"]}, "relation": {"type": "string", "enum": ["AFFECTS", "LOCATED_AT", "MENTIONS", "UNRESOLVED"]}, "sentence_ids": _cited("Required and nonempty when ESTABLISHED or CONFLICTING; empty for UNESTABLISHED. The cited sentences must contain the action and target labels. LOCATED_AT means the Candidate event takes place on or in the target station, platform, train, depot or track; proximity is never LOCATED_AT.")}, "required": ["status", "relation", "sentence_ids"]},
        "target_system": {"type": "object", "additionalProperties": False, "properties": {"status": {"type": "string", "enum": ["ESTABLISHED", "UNESTABLISHED", "CONFLICTING"]}, "relation": {"type": "string", "enum": ["BELONGS_TO", "PART_OF", "FUNCTIONS_FOR", "LOCATED_AT", "OWNED_BY", "OPERATED_BY", "UNRESOLVED"]}, "sentence_ids": _cited("Required and nonempty when ESTABLISHED or CONFLICTING; empty for UNESTABLISHED. The cited sentences must contain target_reference (or the target label) and the system label; the system label may be absent only when it equals the target label. Only BELONGS_TO, PART_OF, and FUNCTIONS_FOR can support eligible membership."), "target_reference": {"type": "string", "description": "Optional. The exact words in the cited sentences that refer to the target when the target label itself is absent there: a same-event reference such as 'the five lines', 'This', 'the line' or '該線'. Omitted or empty means the target label itself."}}, "required": ["status", "relation", "sentence_ids"]},
        "ambiguity": {"type": "object", "additionalProperties": False, "properties": {"status": {"type": "string", "enum": ["NONE", "UNRESOLVED", "CONFLICTING"]}, "sentence_ids": _cited("Required and nonempty for CONFLICTING; empty otherwise.")}, "required": ["status", "sentence_ids"]},
        "noneligible_relation": {"type": "object", "additionalProperties": False, "properties": {"status": {"type": "string", "enum": ["ABSENT", "PRESENT", "UNRESOLVED"]}, "sentence_ids": _cited("Concerns only the Candidate focus action's own target or system. Required and nonempty for PRESENT and must contain the target or system label; empty otherwise.")}, "required": ["status", "sentence_ids"]},
        "noneligible_kind": {"type": "string", "enum": ["NONE", "EXCLUDED_TRANSPORT_MODE", "NON_URBAN_RAIL", "UNRESOLVED"]},
        "event_status": {"type": "string", "enum": ["ASSERTED", "NEGATED", "CONDITIONAL", "UNASSERTED"]},
        "decision": {"type": "string", "enum": ["IN_SCOPE_SUPPORT", "OUT_OF_SCOPE_SUPPORT", "UNCERTAIN"]},
    },
    "required": ["candidate_id", "schema_version", "event_focus", "action", "target", "system", "eligible_mode_family", "action_target", "target_system", "ambiguity", "noneligible_relation", "noneligible_kind", "event_status", "decision"],
}

# D1: an action affecting the target, or a Candidate event taking place on or
# in a station/platform/train/facility that belongs to the eligible system.
_POSITIVE_ACTION_TARGET_RELATIONS = frozenset({"AFFECTS", "LOCATED_AT"})
_POSITIVE_TARGET_SYSTEM_RELATIONS = frozenset({"BELONGS_TO", "PART_OF", "FUNCTIONS_FOR"})


class _Violation(Exception):
    def __init__(self, predicate: str, fields: tuple[str, ...] | None = None) -> None:
        super().__init__(predicate)
        self.predicate = predicate
        # The proposal fields at fault, when the check can name them (RC-75).
        self.fields = fields


# RC-75: the rule in words and the default fields, per contract predicate. A
# check that can name the exact fields passes them to ``_Violation`` instead.
_CORRECTION_RULES: dict[str, tuple[tuple[str, ...], str]] = {
    "TOP_LEVEL_SHAPE": (("proposal",), "The proposal must contain exactly the top-level fields of the response schema and no others."),
    "CANDIDATE_ID": (("candidate_id",), "candidate_id must equal the candidate_id of the request exactly."),
    "SCHEMA_VERSION": (("schema_version",), "schema_version must be the value the response schema requires."),
    "MODE_FAMILY": (("eligible_mode_family",), "eligible_mode_family must be one of the values the response schema lists."),
    "EVENT_STATUS": (("event_status",), "event_status must be one of the values the response schema lists."),
    "NONELIGIBLE_KIND": (("noneligible_kind",), "noneligible_kind must be one of the values the response schema lists."),
    "DECISION_ENUM": (("decision",), "decision must be one of the values the response schema lists."),
    "NESTED_RECORD_SHAPE": (
        ("event_focus", "action", "target", "system", "action_target", "target_system", "ambiguity", "noneligible_relation"),
        "Each nested record must contain exactly the fields the response schema lists for it, and sentence_ids must be a list.",
    ),
    "STATUS_CONSISTENCY": (
        ("event_focus.status", "action_target.status", "target_system.status", "ambiguity.status", "noneligible_relation.status"),
        "Each status must be one of the values the response schema lists for that record.",
    ),
    "RELATION_TYPE": (("action_target.relation", "target_system.relation"), "Each relation must be one of the values the response schema lists for that record."),
    "CITATION_MISSING": (("sentence_ids",), "A record whose status requires a citation must cite at least one sentence_id."),
    "CITATION_INVALID": (("sentence_ids",), "Every cited sentence_id must be one of the principal_sentences ids of the request."),
    "NONELIGIBLE_CONSISTENCY": (
        ("noneligible_kind", "noneligible_relation.status", "eligible_mode_family"),
        "noneligible_kind must be NONE exactly when noneligible_relation is ABSENT; PRESENT needs EXCLUDED_TRANSPORT_MODE or NON_URBAN_RAIL with a NON_ELIGIBLE or UNKNOWN mode family.",
    ),
    "ENDPOINT_LABEL": (
        ("action.label", "target.label", "system.label"),
        "Every label must be a non-empty exact substring of one source sentence, copied character for character in the source's own language and form; do not translate, paraphrase or conjugate it.",
    ),
    "ENDPOINT_ROLE_DISTINCTNESS": (("action.label", "target.label", "system.label"), "action.label must differ from target.label and system.label."),
    "EVENT_FOCUS_CONTAINMENT": (
        ("event_focus.sentence_ids", "action_target.sentence_ids", "target_system.sentence_ids"),
        "Every sentence cited by action_target must lie within the range from the first to the last event_focus sentence. Sentences cited by target_system must too, unless target_system names the same target as action_target (target_reference omitted or equal to target.label); then target_system may cite other sentences of the document, each of which must contain target.label, that state which system that target belongs to.",
    ),
    "NONELIGIBLE_EVENT_FOCUS": (
        ("event_focus.sentence_ids", "noneligible_relation.sentence_ids"),
        "Every sentence cited by noneligible_relation must lie within the range from the first to the last event_focus sentence.",
    ),
    "ACTION_TARGET_CONTAINMENT": (
        ("action.label", "target.label", "action_target.sentence_ids", "event_focus.sentence_ids"),
        "The sentences cited by action_target must contain the action label or the target label, and both labels must lie within the event_focus sentences.",
    ),
    "TARGET_SYSTEM_CONTAINMENT": (
        ("target_system.target_reference", "target.label", "system.label", "target_system.sentence_ids"),
        "The sentences cited by target_system must contain the target label (or target_reference) and the system label; when target_reference differs from the target label, both must also lie within the event_focus sentences.",
    ),
    "TARGET_REFERENCE_CONTEXT": (("target_system.target_reference", "event_focus.status"), "A target_reference different from target.label needs a RESOLVED event_focus."),
    "NONELIGIBLE_RELATION_ENDPOINT": (
        ("noneligible_relation.sentence_ids", "target.label", "system.label"),
        "The sentences cited by noneligible_relation must contain the target label or the system label.",
    ),
}


_LABEL_FIELDS = (
    ("action.label", ("action", "label")),
    ("target.label", ("target", "label")),
    ("system.label", ("system", "label")),
    ("target_system.target_reference", ("target_system", "target_reference")),
)


def _label_sentence_ids(
    proposal: Mapping[str, Any], sentences: tuple[EvidenceSentence, ...]
) -> dict[str, tuple[str, ...]]:
    """RC-85: where each proposed label occurs, by the same containment test the validator uses."""

    located: dict[str, tuple[str, ...]] = {}
    for name, (record, key) in _LABEL_FIELDS:
        value = proposal.get(record) if isinstance(proposal, Mapping) else None
        label = _text(value.get(key)) if isinstance(value, Mapping) else None
        if label is None:
            continue
        located[name] = tuple(sentence.sentence_id for sentence in sentences if _within(label, sentence.text))
    return located


def _correction_for(
    rejected: "_Violation",
    proposal: Mapping[str, Any],
    sentences: tuple[EvidenceSentence, ...] = (),
) -> ScopeCorrection | None:
    """Build the one correction request for a rejected proposal, or None.

    Only a predicate with a stated rule is corrected; every correctable
    predicate names the fields at fault, and the request carries the
    sentence_ids that contain each proposed label (RC-85).
    """

    entry = _CORRECTION_RULES.get(rejected.predicate)
    if entry is None:
        return None
    default_fields, rule = entry
    return ScopeCorrection(
        rejected.predicate,
        tuple(rejected.fields or default_fields),
        rule,
        dict(proposal),
        _label_sentence_ids(proposal, sentences),
    )


def _strict_record(value: object, keys: tuple[str, ...]) -> Mapping[str, Any] | None:
    if not isinstance(value, Mapping) or set(value) != set(keys):
        return None
    return value


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _within(label: str, text: str) -> bool:
    return label.casefold() in text.casefold()


def _label_spans(content: str, contexts: tuple[EvidenceSentence, ...], label: str) -> tuple[ScopeSupportSpan, ...]:
    """Record the label's occurrences inside its establishing sentences only."""

    folded_label = label.casefold()
    found: set[tuple[int, int]] = set()
    for context in contexts:
        segment = content[context.start:context.end]
        folded = segment.casefold()
        # Case-insensitive offsets are only exact when folding keeps length.
        haystack, needle = (folded, folded_label) if len(folded) == len(segment) and len(folded_label) == len(label) else (segment, label)
        position = haystack.find(needle)
        while position >= 0:
            found.add((context.start + position, context.start + position + len(needle)))
            position = haystack.find(needle, position + 1)
    return tuple(ScopeSupportSpan(start, end) for start, end in sorted(found))


def _proposal_support(proposal: Mapping[str, Any], request: ScopeSemanticRequest):
    """Validate the complete relation and derive coordinates locally (RC-8/RC-9).

    Raises ``_Violation`` when the proposal breaks its contract; returns the
    owner's decision otherwise.
    """

    required = {"candidate_id", "schema_version", "event_focus", "action", "target", "system", "eligible_mode_family", "action_target", "target_system", "ambiguity", "noneligible_relation", "noneligible_kind", "event_status", "decision"}
    if set(proposal) != required:
        raise _Violation("TOP_LEVEL_SHAPE")
    if proposal.get("candidate_id") != request.candidate_id:
        raise _Violation("CANDIDATE_ID")
    if proposal.get("schema_version") != SCOPE_PROPOSAL_SCHEMA_VERSION:
        raise _Violation("SCHEMA_VERSION")
    mode = proposal.get("eligible_mode_family")
    if mode not in (*SUPPORTED_SCOPE_MODE_FAMILIES, "NON_ELIGIBLE", "UNKNOWN"):
        raise _Violation("MODE_FAMILY")
    if proposal.get("event_status") not in {"ASSERTED", "NEGATED", "CONDITIONAL", "UNASSERTED"}:
        raise _Violation("EVENT_STATUS")
    kind = proposal.get("noneligible_kind")
    if kind not in {"NONE", "EXCLUDED_TRANSPORT_MODE", "NON_URBAN_RAIL", "UNRESOLVED"}:
        raise _Violation("NONELIGIBLE_KIND")
    decision = proposal.get("decision")
    if decision not in {item.value for item in ScopeSemanticSupport}:
        raise _Violation("DECISION_ENUM")

    focus = _strict_record(proposal.get("event_focus"), ("status", "sentence_ids"))
    action = _strict_record(proposal.get("action"), ("label",))
    target = _strict_record(proposal.get("target"), ("label",))
    system = _strict_record(proposal.get("system"), ("label",))
    action_target = _strict_record(proposal.get("action_target"), ("status", "relation", "sentence_ids"))
    # target_reference is optional; omitted or empty means the target label.
    raw_target_system = proposal.get("target_system")
    target_system = _strict_record(raw_target_system, ("status", "relation", "sentence_ids", "target_reference")) or _strict_record(raw_target_system, ("status", "relation", "sentence_ids"))
    ambiguity = _strict_record(proposal.get("ambiguity"), ("status", "sentence_ids"))
    noneligible = _strict_record(proposal.get("noneligible_relation"), ("status", "sentence_ids"))
    records = {"event_focus": focus, "action_target": action_target, "target_system": target_system, "ambiguity": ambiguity, "noneligible_relation": noneligible}
    if any(item is None for item in (action, target, system, *records.values())):
        raise _Violation("NESTED_RECORD_SHAPE")
    assert action is not None and target is not None and system is not None and target_system is not None and action_target is not None

    statuses = {name: record["status"] for name, record in records.items()}  # type: ignore[index]
    if statuses["event_focus"] not in {"RESOLVED", "UNRESOLVED", "CONFLICTING"} or statuses["action_target"] not in {"ESTABLISHED", "UNESTABLISHED", "CONFLICTING"} or statuses["target_system"] not in {"ESTABLISHED", "UNESTABLISHED", "CONFLICTING"} or statuses["ambiguity"] not in {"NONE", "UNRESOLVED", "CONFLICTING"} or statuses["noneligible_relation"] not in {"ABSENT", "PRESENT", "UNRESOLVED"}:
        raise _Violation("STATUS_CONSISTENCY")
    if action_target["relation"] not in {"AFFECTS", "LOCATED_AT", "MENTIONS", "UNRESOLVED"} or target_system["relation"] not in {"BELONGS_TO", "PART_OF", "FUNCTIONS_FOR", "LOCATED_AT", "OWNED_BY", "OPERATED_BY", "UNRESOLVED"}:
        raise _Violation("RELATION_TYPE")
    action_target_claimed = statuses["action_target"] in {"ESTABLISHED", "CONFLICTING"}
    target_system_claimed = statuses["target_system"] in {"ESTABLISHED", "CONFLICTING"}
    citation_required = {
        "event_focus": statuses["event_focus"] in {"RESOLVED", "CONFLICTING"},
        "action_target": action_target_claimed,
        "target_system": target_system_claimed,
        "ambiguity": statuses["ambiguity"] == "CONFLICTING",
        "noneligible_relation": statuses["noneligible_relation"] == "PRESENT",
    }

    # RC-9: citations are sentence IDs produced by Python segmentation.
    sentences = request.principal_sentences
    cited: dict[str, tuple[EvidenceSentence, ...]] = {}
    for name, record in records.items():
        ids = record["sentence_ids"]  # type: ignore[index]
        if not isinstance(ids, (list, tuple)):
            raise _Violation("NESTED_RECORD_SHAPE", (f"{name}.sentence_ids",))
        if not ids:
            if citation_required[name]:
                raise _Violation("CITATION_MISSING", (f"{name}.sentence_ids",))
            continue
        resolved = resolve_sentence_ids(sentences, ids)
        if resolved is None:
            raise _Violation("CITATION_INVALID", (f"{name}.sentence_ids",))
        cited[name] = resolved

    if statuses["noneligible_relation"] == "ABSENT" and kind != "NONE":
        raise _Violation("NONELIGIBLE_CONSISTENCY")
    if statuses["noneligible_relation"] == "PRESENT" and (mode in SUPPORTED_SCOPE_MODE_FAMILIES or kind not in {"EXCLUDED_TRANSPORT_MODE", "NON_URBAN_RAIL"}):
        raise _Violation("NONELIGIBLE_CONSISTENCY")

    content = request.principal_content
    labels = {"action": _text(action["label"]), "target": _text(target["label"]), "system": _text(system["label"]), "target_reference": _text(target_system.get("target_reference"))}
    if labels["target_reference"] is None and target_system_claimed:
        labels["target_reference"] = labels["target"]
    empty_roles = tuple(
        f"{role}.label"
        for role, required in (("action", True), ("target", True), ("system", target_system_claimed))
        if required and labels[role] is None
    )
    if empty_roles:
        raise _Violation("ENDPOINT_LABEL", empty_roles)
    # A label not anchored by a claimed relation asserts nothing, but it must
    # still be source text.
    not_source = tuple(
        "target_system.target_reference" if role == "target_reference" else f"{role}.label"
        for role, label in labels.items()
        if label is not None and not _within(label, content)
    )
    if not_source:
        raise _Violation("ENDPOINT_LABEL", not_source)
    action_label, target_label, system_label, target_reference = labels["action"], labels["target"], labels["system"], labels["target_reference"]
    # The action must be distinguishable from what it acts on.  Target and
    # system may name the same entity when the action affects the system itself.
    if any(value is not None and action_label.casefold() == value.casefold() for value in (target_label, system_label, target_reference)):
        raise _Violation("ENDPOINT_ROLE_DISTINCTNESS")

    # Every relation lies inside the resolved Candidate focus: no borrowing
    # from a separate event in the same document. RC-75 (user decision
    # 2026-11-19): the one exception is a target_system relation that states
    # which system the focus action's own target belongs to. It may cite other
    # sentences of the same document when the action-to-target relation is
    # established inside the focus and the relation's target is that same
    # target label; the sentence then describes the same target, not another
    # event. Nothing else leaves the focus.
    system_outside_focus = False
    if statuses["event_focus"] == "RESOLVED":
        focus_sentences = cited["event_focus"]
        first, last = focus_sentences[0].start, focus_sentences[-1].end
        for name in ("action_target", "target_system", "noneligible_relation"):
            if name in cited and any(sentence.start < first or sentence.end > last for sentence in cited[name]):
                if (
                    name == "target_system"
                    and target_system_claimed
                    and action_target_claimed
                    and labels["target_reference"] is not None
                    and labels["target_reference"].casefold() == labels["target"].casefold()
                    # User decision (tightened 2026-11-19): each sentence outside
                    # the focus names the focus target itself, so it describes
                    # that target and not another event (the RC-17 guarantee).
                    and all(
                        _within(labels["target"], sentence.text)
                        for sentence in cited[name]
                        if sentence.start < first or sentence.end > last
                    )
                ):
                    system_outside_focus = True
                    continue
                if name == "noneligible_relation":
                    raise _Violation("NONELIGIBLE_EVENT_FOCUS")
                raise _Violation("EVENT_FOCUS_CONTAINMENT", (f"{name}.sentence_ids", "event_focus.sentence_ids"))

    # Same-context rule (RC-8, RC-17): a relation's cited sentences contain at
    # least one of its endpoints, and every endpoint lies inside the resolved
    # Candidate event focus range. Without a resolved focus, both endpoints
    # must lie inside the relation's own sentences.
    focus_range: tuple[EvidenceSentence, ...] = ()
    if statuses["event_focus"] == "RESOLVED":
        focus_first, focus_last = cited["event_focus"][0].start, cited["event_focus"][-1].end
        focus_range = tuple(sentence for sentence in sentences if focus_first <= sentence.start and sentence.end <= focus_last)
    focus_text = cited_text(focus_range)

    def anchored(relation: str, endpoints: tuple[str, ...]) -> bool:
        text = cited_text(cited[relation])
        if not focus_range or (relation == "target_system" and system_outside_focus):
            # Without a focus, or for the RC-75 system relation that leaves it,
            # the relation's own sentences must contain every endpoint.
            return all(_within(endpoint, text) for endpoint in endpoints)
        return any(_within(endpoint, text) for endpoint in endpoints) and all(_within(endpoint, focus_text) for endpoint in endpoints)

    if action_target_claimed and not anchored("action_target", (action_label, target_label)):
        raise _Violation("ACTION_TARGET_CONTAINMENT")
    if target_system_claimed:
        identity = system_label.casefold() == target_label.casefold()
        if not anchored("target_system", (target_reference,) if identity else (target_reference, system_label)):
            raise _Violation("TARGET_SYSTEM_CONTAINMENT")
        # A reference other than the target label is bounded to the Candidate
        # event: both relations must lie inside a resolved focus.
        if target_reference.casefold() != target_label.casefold() and statuses["event_focus"] != "RESOLVED":
            raise _Violation("TARGET_REFERENCE_CONTEXT")

    if statuses["noneligible_relation"] == "PRESENT":
        # SC-2: the noneligible relation concerns only the focus action's own
        # target or system.
        text = cited_text(cited["noneligible_relation"])
        endpoints = [target_label] + ([system_label] if system_label is not None else [])
        if not any(_within(label, text) for label in endpoints):
            raise _Violation("NONELIGIBLE_RELATION_ENDPOINT")

    positive = (decision == ScopeSemanticSupport.IN_SCOPE_SUPPORT.value and statuses["event_focus"] == "RESOLVED" and proposal["event_status"] == "ASSERTED" and statuses["action_target"] == "ESTABLISHED" and action_target["relation"] in _POSITIVE_ACTION_TARGET_RELATIONS and statuses["target_system"] == "ESTABLISHED" and target_system["relation"] in _POSITIVE_TARGET_SYSTEM_RELATIONS and statuses["ambiguity"] == "NONE" and statuses["noneligible_relation"] == "ABSENT" and mode in SUPPORTED_SCOPE_MODE_FAMILIES)
    # A well-formed proposal whose own relations do not establish an eligible
    # relation is a legitimate owner decision, not a violation.
    first_rejection = "POSITIVE_ACCEPTANCE_CONDITION" if decision == ScopeSemanticSupport.IN_SCOPE_SUPPORT.value and not positive else None
    support = ScopeSemanticSupport.IN_SCOPE_SUPPORT if positive else ScopeSemanticSupport.OUT_OF_SCOPE_SUPPORT
    diagnostic = ScopeDiagnostic.NONE if positive else ScopeDiagnostic.SCOPE_NOT_ESTABLISHED
    if not positive and statuses["noneligible_relation"] == "PRESENT" and statuses["event_focus"] == "RESOLVED" and proposal["event_status"] == "ASSERTED":
        diagnostic = ScopeDiagnostic(kind)

    relation_support = {
        name: [{"start": sentence.start, "end": sentence.end} for sentence in located]
        for name, located in cited.items()
    }
    # Endpoint provenance records the label inside its establishing context:
    # the resolved focus range (RC-17), otherwise the relation's sentences.
    system_context = (focus_range or cited.get("target_system", ())) if target_system_claimed else ()
    if system_outside_focus:
        # RC-75: the system relation's own sentences establish the system label.
        system_context = tuple(sorted({*focus_range, *cited["target_system"]}, key=lambda sentence: sentence.start))
    endpoint_contexts = {
        "action": (focus_range or cited.get("action_target", ())) if action_target_claimed else (),
        "target": (focus_range or cited.get("action_target", ())) if action_target_claimed else (),
        "target_reference": system_context,
        "system": system_context,
    }
    for role, contexts in endpoint_contexts.items():
        if contexts and labels[role] is not None:
            relation_support[role] = [{"start": span.start, "end": span.end} for span in _label_spans(content, contexts, labels[role])]
    cited_ids = {name: [sentence.sentence_id for sentence in located] for name, located in cited.items()}
    provenance = {"decision_basis": "scope_semantic_proposal", "schema_version": SCOPE_PROPOSAL_SCHEMA_VERSION, "candidate_event_focus": relation_support.get("event_focus"), "eligible_mode_family": mode, "action_target_relation": action_target["relation"], "target_system_relation": target_system["relation"], "endpoint_labels": dict(labels), "cited_sentence_ids": cited_ids, "relation_support": relation_support}
    return support, diagnostic, provenance, first_rejection


def _coerce_response(value: object) -> ScopeSemanticResponse | None:
    if isinstance(value, ScopeSemanticResponse):
        return value
    if isinstance(value, Mapping):
        # Direct adapter output is the complete proposal. Legacy span-only
        # mappings are therefore rejected by the owner below.
        return ScopeSemanticResponse(proposal=value)
    return None


def _same_document_metadata(provenance: Mapping[str, Any]) -> dict[str, Any]:
    """Project the helper's allowed same-document factual metadata.

    The principal document's own headlines are facts of the document.
    Acquisition diagnostics (timings, redirects, excluded regions, URLs) are
    not, and a timing value would also make every request unique.
    """

    headlines = provenance.get("principal_source_headlines")
    if not isinstance(headlines, (list, tuple)):
        return {}
    return {"principal_source_headlines": [str(item) for item in headlines if str(item).strip()]}


class ScopeClassifier:
    """The sole authoritative owner of IN_SCOPE / OUT_OF_SCOPE."""

    def __init__(self, semantic_helper: ScopeSemanticHelper | None = None) -> None:
        self._semantic_helper = semantic_helper

    def classify(
        self,
        evidence: EvidenceResult,
        *,
        candidate_title: str = "",
        observation_hook: Callable[[ScopeValidationObservation], None] | None = None,
        monitored_check: MonitoredCheckMonth | None = None,
    ) -> ScopeResult:
        def observe(
            result: ScopeResult | None,
            first_rejection: str | None,
            response_status: str,
            correction_predicate: str | None = None,
        ) -> None:
            if observation_hook is None:
                return
            try:
                observation_hook(
                    ScopeValidationObservation(
                        first_rejection,
                        response_status,
                        None if result is None else result.state,
                        None if result is None else result.diagnostic,
                        correction_predicate,
                    )
                )
            except Exception:
                # Observation cannot change the owner's decision or failure behavior.
                return

        def violation(predicate: str, observation: Mapping[str, Any] | None = None) -> ScopeProposalViolation:
            observe(None, predicate, "PROPOSAL_VIOLATION")
            return ScopeProposalViolation(predicate, observation)

        if evidence.state is not EvidenceState.READY:
            raise ValueError("ScopeClassifier requires EVIDENCE_READY evidence")
        if self._semantic_helper is None:
            result = self._out_of_scope(evidence.candidate_id, ScopeDiagnostic.SCOPE_NOT_ESTABLISHED, {"decision_basis": "scope_semantic_proposal", "helper": "not_configured"})
            observe(result, "HELPER_NOT_CONFIGURED", "NOT_CALLED")
            return result
        if monitored_check is not None:
            # RC-59 (section A.43): in the monthly check, a Candidate that is a
            # proven formal lifecycle change of a monitored standard is in
            # scope on that basis alone. Nothing else changes the rule below.
            identifiers = monitored_standards().identifiers_in(evidence.substantive_content)
            if identifiers:
                monitored_request = MonitoredStandardScopeRequest(
                    evidence.candidate_id, evidence.substantive_content, identifiers
                )
                try:
                    raw = self._semantic_helper(monitored_request)
                except (SemanticProviderTechnicalFailure, SemanticProviderConfigurationFailure):
                    raise
                except Exception:
                    raise violation("PROVIDER_FAILURE") from None
                try:
                    change = _monitored_change(raw, monitored_request, monitored_check)
                except _Violation as rejected:
                    raise violation(rejected.predicate) from None
                if change is not None:
                    by_id = {sentence.sentence_id: sentence for sentence in monitored_request.principal_sentences}
                    focus = [{"start": by_id[sid].start, "end": by_id[sid].end} for sid in change.sentence_ids]
                    result = ScopeResult(
                        candidate_id=evidence.candidate_id,
                        state=ScopeState.IN_SCOPE,
                        provenance={
                            "decision_basis": "monitored_standard_lifecycle_change",
                            "monitored_standard": change.identifier,
                            "lifecycle_action": change.lifecycle_action.value,
                            "check_month": change.check_month.label,
                            # The lifecycle sentences are the Candidate event (RC-20).
                            "candidate_event_focus": focus,
                        },
                        monitored_standard=change,
                    )
                    observe(result, None, "OWNER_VALIDATED")
                    return result
        request = ScopeSemanticRequest(
            evidence.candidate_id,
            candidate_title,
            evidence.substantive_content,
            _same_document_metadata(evidence.provenance),
        )
        try:
            response = _coerce_response(self._semantic_helper(request))
        except (SemanticProviderTechnicalFailure, SemanticProviderConfigurationFailure):
            # RC-6: a technical failure is not OUT_OF_SCOPE.
            raise
        except Exception:
            raise violation("PROVIDER_FAILURE") from None
        if response is None or response.proposal is None:
            raise violation("PROPOSAL_MISSING")
        correction_record: dict[str, Any] | None = None
        try:
            support, diagnostic, provenance, first_rejection = _proposal_support(response.proposal, request)
        except _Violation as rejected:
            correction = _correction_for(rejected, response.proposal, request.principal_sentences)
            if correction is None:
                raise violation(rejected.predicate, _rejected_proposal_shape(response.proposal, request)) from None
            # RC-75 (user decision 2026-11-19): like the Validator's one rewrite,
            # a contract violation gets one correction request that names the
            # rule and the fields at fault. It is not an RC-6 transport retry
            # and is counted apart from it. A second violation is the gap.
            corrected_request = ScopeSemanticRequest(
                request.candidate_id,
                request.candidate_title,
                request.principal_content,
                request.source_metadata,
                correction,
            )
            try:
                second = _coerce_response(self._semantic_helper(corrected_request))
            except (SemanticProviderTechnicalFailure, SemanticProviderConfigurationFailure) as failure:
                failure.scope_correction = correction.record("TRANSPORT_FAILURE")  # type: ignore[attr-defined]
                raise
            except Exception:
                raise self._corrected_violation(
                    observe, "PROVIDER_FAILURE", None, correction.record("PROVIDER_FAILURE"), rejected.predicate
                ) from None
            if second is None or second.proposal is None:
                raise self._corrected_violation(
                    observe, "PROPOSAL_MISSING", None, correction.record("PROPOSAL_MISSING"), rejected.predicate
                ) from None
            try:
                support, diagnostic, provenance, first_rejection = _proposal_support(second.proposal, corrected_request)
            except _Violation as again:
                raise self._corrected_violation(
                    observe,
                    again.predicate,
                    _rejected_proposal_shape(second.proposal, corrected_request),
                    {**correction.record("STILL_VIOLATED"), "second_predicate": again.predicate},
                    rejected.predicate,
                ) from None
            except Exception:
                raise self._corrected_violation(
                    observe, "VALIDATOR_EXCEPTION", None, correction.record("VALIDATOR_EXCEPTION"), rejected.predicate
                ) from None
            correction_record = correction.record("ACCEPTED")
        except Exception:
            raise violation("VALIDATOR_EXCEPTION") from None
        if correction_record is not None:
            provenance = {**provenance, "scope_correction": correction_record}
        if support is ScopeSemanticSupport.IN_SCOPE_SUPPORT:
            result = ScopeResult(candidate_id=evidence.candidate_id, state=ScopeState.IN_SCOPE, provenance=provenance)
        else:
            result = self._out_of_scope(evidence.candidate_id, diagnostic, provenance)
        observe(
            result,
            first_rejection,
            "OWNER_VALIDATED",
            None if correction_record is None else correction_record["predicate"],
        )
        return result

    @staticmethod
    def _corrected_violation(
        observe: Callable[..., None],
        predicate: str,
        shape: Mapping[str, Any] | None,
        correction: Mapping[str, Any],
        first_predicate: str,
    ) -> ScopeProposalViolation:
        observe(None, predicate, "PROPOSAL_VIOLATION", first_predicate)
        return ScopeProposalViolation(predicate, shape, correction)

    evaluate = classify

    @staticmethod
    def _out_of_scope(candidate_id: str, diagnostic: ScopeDiagnostic, provenance: Mapping[str, Any]) -> ScopeResult:
        return ScopeResult(candidate_id=candidate_id, state=ScopeState.OUT_OF_SCOPE, diagnostic=diagnostic, provenance=dict(provenance))


__all__ = ["MONITORED_STANDARD_PROPOSAL_FIELDS", "MonitoredStandardScopeRequest", "SCOPE_PROPOSAL_SCHEMA_VERSION", "SCOPE_SEMANTIC_RESPONSE_SCHEMA", "SUPPORTED_SCOPE_MODE_FAMILIES", "ScopeClassifier", "ScopeCorrection", "ScopeProposalViolation", "ScopeSemanticHelper", "ScopeSemanticRequest", "ScopeSemanticResponse", "ScopeSemanticSupport", "ScopeSupportSpan", "ScopeValidationObservation"]
