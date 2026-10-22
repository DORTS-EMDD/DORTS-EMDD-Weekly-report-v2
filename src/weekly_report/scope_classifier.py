"""Candidate-stage Scope owner and bounded semantic proposal seam."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable, Protocol

from .contracts import (
    EvidenceResult,
    EvidenceState,
    ProposalContractViolation,
    ScopeDiagnostic,
    ScopeResult,
    ScopeState,
    SemanticProviderConfigurationFailure,
    SemanticProviderTechnicalFailure,
)
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


@dataclass(frozen=True, slots=True)
class ScopeSemanticRequest:
    candidate_id: str
    candidate_title: str
    principal_content: str
    source_metadata: Mapping[str, Any]
    # RC-9: the helper reads and cites Python-segmented sentences.
    principal_sentences: tuple[EvidenceSentence, ...] = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "principal_sentences", segment_evidence_sentences(self.principal_content))

    def as_payload(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "candidate_title": self.candidate_title,
            "principal_sentences": [sentence.as_mapping() for sentence in self.principal_sentences],
            "source_metadata": dict(self.source_metadata),
        }


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


class ScopeProposalViolation(ProposalContractViolation):
    """RC-9: a parseable Scope proposal the owner cannot validate.

    It is a disclosed Candidate TechnicalGap, never OUT_OF_SCOPE: a system or
    helper defect must not be presented as news that failed the Scope rule.
    """

    def __init__(self, predicate: str) -> None:
        self.failure_class = predicate
        super().__init__(f"Scope proposal violated its contract: {predicate}")


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
    def __init__(self, predicate: str) -> None:
        super().__init__(predicate)
        self.predicate = predicate


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
            raise _Violation("NESTED_RECORD_SHAPE")
        if not ids:
            if citation_required[name]:
                raise _Violation("CITATION_MISSING")
            continue
        resolved = resolve_sentence_ids(sentences, ids)
        if resolved is None:
            raise _Violation("CITATION_INVALID")
        cited[name] = resolved

    if statuses["noneligible_relation"] == "ABSENT" and kind != "NONE":
        raise _Violation("NONELIGIBLE_CONSISTENCY")
    if statuses["noneligible_relation"] == "PRESENT" and (mode in SUPPORTED_SCOPE_MODE_FAMILIES or kind not in {"EXCLUDED_TRANSPORT_MODE", "NON_URBAN_RAIL"}):
        raise _Violation("NONELIGIBLE_CONSISTENCY")

    content = request.principal_content
    labels = {"action": _text(action["label"]), "target": _text(target["label"]), "system": _text(system["label"]), "target_reference": _text(target_system.get("target_reference"))}
    if labels["target_reference"] is None and target_system_claimed:
        labels["target_reference"] = labels["target"]
    if labels["action"] is None or labels["target"] is None or (target_system_claimed and labels["system"] is None):
        raise _Violation("ENDPOINT_LABEL")
    # A label not anchored by a claimed relation asserts nothing, but it must
    # still be source text.
    for label in labels.values():
        if label is not None and not _within(label, content):
            raise _Violation("ENDPOINT_LABEL")
    action_label, target_label, system_label, target_reference = labels["action"], labels["target"], labels["system"], labels["target_reference"]
    # The action must be distinguishable from what it acts on.  Target and
    # system may name the same entity when the action affects the system itself.
    if any(value is not None and action_label.casefold() == value.casefold() for value in (target_label, system_label, target_reference)):
        raise _Violation("ENDPOINT_ROLE_DISTINCTNESS")

    # Every relation lies inside the resolved Candidate focus: no borrowing
    # from a separate event in the same document.
    if statuses["event_focus"] == "RESOLVED":
        focus_sentences = cited["event_focus"]
        first, last = focus_sentences[0].start, focus_sentences[-1].end
        for name in ("action_target", "target_system", "noneligible_relation"):
            if name in cited and any(sentence.start < first or sentence.end > last for sentence in cited[name]):
                raise _Violation("NONELIGIBLE_EVENT_FOCUS" if name == "noneligible_relation" else "EVENT_FOCUS_CONTAINMENT")

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
        if not focus_range:
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
    endpoint_contexts = {
        "action": (focus_range or cited.get("action_target", ())) if action_target_claimed else (),
        "target": (focus_range or cited.get("action_target", ())) if action_target_claimed else (),
        "target_reference": (focus_range or cited.get("target_system", ())) if target_system_claimed else (),
        "system": (focus_range or cited.get("target_system", ())) if target_system_claimed else (),
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
    ) -> ScopeResult:
        def observe(result: ScopeResult | None, first_rejection: str | None, response_status: str) -> None:
            if observation_hook is None:
                return
            try:
                observation_hook(
                    ScopeValidationObservation(
                        first_rejection,
                        response_status,
                        None if result is None else result.state,
                        None if result is None else result.diagnostic,
                    )
                )
            except Exception:
                # Observation cannot change the owner's decision or failure behavior.
                return

        def violation(predicate: str) -> ScopeProposalViolation:
            observe(None, predicate, "PROPOSAL_VIOLATION")
            return ScopeProposalViolation(predicate)

        if evidence.state is not EvidenceState.READY:
            raise ValueError("ScopeClassifier requires EVIDENCE_READY evidence")
        if self._semantic_helper is None:
            result = self._out_of_scope(evidence.candidate_id, ScopeDiagnostic.SCOPE_NOT_ESTABLISHED, {"decision_basis": "scope_semantic_proposal", "helper": "not_configured"})
            observe(result, "HELPER_NOT_CONFIGURED", "NOT_CALLED")
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
        try:
            support, diagnostic, provenance, first_rejection = _proposal_support(response.proposal, request)
        except _Violation as rejected:
            raise violation(rejected.predicate) from None
        except Exception:
            raise violation("VALIDATOR_EXCEPTION") from None
        if support is ScopeSemanticSupport.IN_SCOPE_SUPPORT:
            result = ScopeResult(candidate_id=evidence.candidate_id, state=ScopeState.IN_SCOPE, provenance=provenance)
        else:
            result = self._out_of_scope(evidence.candidate_id, diagnostic, provenance)
        observe(result, first_rejection, "OWNER_VALIDATED")
        return result

    evaluate = classify

    @staticmethod
    def _out_of_scope(candidate_id: str, diagnostic: ScopeDiagnostic, provenance: Mapping[str, Any]) -> ScopeResult:
        return ScopeResult(candidate_id=candidate_id, state=ScopeState.OUT_OF_SCOPE, diagnostic=diagnostic, provenance=dict(provenance))


__all__ = ["SCOPE_PROPOSAL_SCHEMA_VERSION", "SCOPE_SEMANTIC_RESPONSE_SCHEMA", "SUPPORTED_SCOPE_MODE_FAMILIES", "ScopeClassifier", "ScopeProposalViolation", "ScopeSemanticHelper", "ScopeSemanticRequest", "ScopeSemanticResponse", "ScopeSemanticSupport", "ScopeSupportSpan", "ScopeValidationObservation"]
