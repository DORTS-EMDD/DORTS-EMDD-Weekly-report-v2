"""Candidate-stage Scope owner and bounded semantic proposal seam."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Callable, Protocol

from .contracts import (
    EvidenceResult,
    EvidenceState,
    ScopeDiagnostic,
    ScopeResult,
    ScopeState,
    SemanticProviderConfigurationFailure,
    SemanticProviderTechnicalFailure,
)
from .exact_text import exact_occurrence_offsets


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

    def as_payload(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "candidate_title": self.candidate_title,
            "principal_content": self.principal_content,
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
    """Read-only facts emitted from the owner's existing validation pass."""

    first_rejection_predicate: str | None
    response_status: str
    scope_state: ScopeState
    diagnostic: ScopeDiagnostic


class ScopeSemanticHelper(Protocol):
    def __call__(self, request: ScopeSemanticRequest) -> ScopeSemanticResponse | Mapping[str, Any] | object:
        ...


SCOPE_PROPOSAL_SCHEMA_VERSION = "scope-semantic-proposal-v3"
SUPPORTED_SCOPE_MODE_FAMILIES = (
    "METRO", "MRT", "SUBWAY", "LIGHT_RAIL", "TRAM", "URBAN_RAIL", "AGT", "MONORAIL", "PEOPLE_MOVER"
)

_LABEL_DESCRIPTION = "Short exact source-surface substring naming the {role}; never a quotation of its own. It must appear inside the relation quotation that establishes it."

SCOPE_SEMANTIC_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "RC-8: endpoints are labels anchored inside relation quotations. Every nonempty quotation must be an exact unchanged source substring of principal_content; Python records every occurrence. action and target labels must appear inside the action_target quotation; the target_reference and system label must appear inside the target_system quotation (target_reference is the target label itself or a same-event reference to it, such as 'the five lines'); both relation quotations must lie inside the event_focus quotation.",
    "additionalProperties": False,
    "properties": {
        "candidate_id": {"type": "string"},
        "schema_version": {"type": "string", "enum": [SCOPE_PROPOSAL_SCHEMA_VERSION]},
        "event_focus": {"type": "object", "additionalProperties": False, "properties": {"status": {"type": "string", "enum": ["RESOLVED", "UNRESOLVED", "CONFLICTING"]}, "quote": {"type": "string", "description": "Required as a nonempty exact source quotation for RESOLVED or CONFLICTING; empty is allowed for UNRESOLVED. Every nonempty value is validated."}}, "required": ["status", "quote"]},
        "action": {"type": "object", "additionalProperties": False, "properties": {"label": {"type": "string", "description": _LABEL_DESCRIPTION.format(role="asserted action")}}, "required": ["label"]},
        "target": {"type": "object", "additionalProperties": False, "properties": {"label": {"type": "string", "description": _LABEL_DESCRIPTION.format(role="claimed affected target, or the station, platform, train or facility where the Candidate event takes place")}}, "required": ["label"]},
        "system": {"type": "object", "additionalProperties": False, "properties": {"label": {"type": "string", "description": _LABEL_DESCRIPTION.format(role="transport system") + " Empty is allowed when the system is unknown or unestablished. It may equal the target label when the action affects the system itself."}}, "required": ["label"]},
        "eligible_mode_family": {"type": "string", "enum": [*SUPPORTED_SCOPE_MODE_FAMILIES, "NON_ELIGIBLE", "UNKNOWN"]},
        "action_target": {"type": "object", "additionalProperties": False, "properties": {"status": {"type": "string", "enum": ["ESTABLISHED", "UNESTABLISHED", "CONFLICTING"]}, "relation": {"type": "string", "enum": ["AFFECTS", "LOCATED_AT", "MENTIONS", "UNRESOLVED"]}, "quote": {"type": "string", "description": "Required as a nonempty exact source quotation when status is ESTABLISHED or CONFLICTING; empty is allowed for UNESTABLISHED. Every nonempty value is validated. An ESTABLISHED or CONFLICTING relation quotation must contain the action and target labels. LOCATED_AT means the Candidate event takes place on or in the target station, platform, train, depot or track; proximity is never LOCATED_AT."}}, "required": ["status", "relation", "quote"]},
        "target_system": {"type": "object", "additionalProperties": False, "properties": {"status": {"type": "string", "enum": ["ESTABLISHED", "UNESTABLISHED", "CONFLICTING"]}, "relation": {"type": "string", "enum": ["BELONGS_TO", "PART_OF", "FUNCTIONS_FOR", "LOCATED_AT", "OWNED_BY", "OPERATED_BY", "UNRESOLVED"]}, "quote": {"type": "string", "description": "Required as a nonempty exact source quotation when status is ESTABLISHED or CONFLICTING; empty is allowed for UNESTABLISHED. Every nonempty value is validated. For an ESTABLISHED or CONFLICTING relation, the quotation must contain target_reference and the system label (the system label may be omitted only when it equals the target label). Only BELONGS_TO, PART_OF, and FUNCTIONS_FOR can support eligible membership."}, "target_reference": {"type": "string", "description": "Optional. The exact surface form inside this quotation that refers to the target when it differs from the target label: a same-event reference such as 'the five lines', 'the line', 'its' or '該線'. Omitted or empty means the target label itself."}}, "required": ["status", "relation", "quote"]},
        "ambiguity": {"type": "object", "additionalProperties": False, "properties": {"status": {"type": "string", "enum": ["NONE", "UNRESOLVED", "CONFLICTING"]}, "quote": {"type": "string", "description": "Required as a nonempty exact source quotation for CONFLICTING; empty is allowed for NONE or UNRESOLVED. Every nonempty value is validated."}}, "required": ["status", "quote"]},
        "noneligible_relation": {"type": "object", "additionalProperties": False, "properties": {"status": {"type": "string", "enum": ["ABSENT", "PRESENT", "UNRESOLVED"]}, "quote": {"type": "string", "description": "Concerns only the Candidate focus action's own target or system; other actions in the same document are never recorded here. Required as a nonempty exact source quotation for PRESENT; empty is allowed for ABSENT or UNRESOLVED. A PRESENT quotation must contain the target or system label. Every nonempty value is validated."}}, "required": ["status", "quote"]},
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


def _strict_record(value: object, keys: tuple[str, ...]) -> Mapping[str, Any] | None:
    if not isinstance(value, Mapping) or set(value) != set(keys):
        return None
    return value


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _locate_quote(content: str, value: object) -> tuple[tuple[ScopeSupportSpan, ...], str | None]:
    """Locate every exact occurrence (EXACT_TEXT_ALL_OCCURRENCES)."""

    quote = _text(value)
    if quote is None:
        return (), "QUOTE_MISSING"
    occurrences = exact_occurrence_offsets(content, quote)
    if not occurrences:
        return (), "QUOTE_NOT_FOUND"
    return tuple(ScopeSupportSpan(start, start + len(quote)) for start in occurrences), None


def _within_context(inner: str, context: str) -> bool:
    """Same-context rule: an endpoint must lie inside one context quotation.

    Every occurrence of ``context`` then contains an occurrence of ``inner``,
    so a relation can never be assembled from unrelated occurrences.
    """

    return inner.casefold() in context.casefold()


def _label_spans(content: str, contexts: tuple[ScopeSupportSpan, ...], label: str) -> tuple[ScopeSupportSpan, ...]:
    """Record the label's occurrences inside its establishing contexts only."""

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


def _proposal_support(
    proposal: Mapping[str, Any],
    request: ScopeSemanticRequest,
    rejected_predicates: list[str] | None = None,
):
    """Validate the complete relation and derive coordinates locally (RC-8)."""
    def reject(predicate: str):
        if rejected_predicates is not None:
            rejected_predicates.append(predicate)
        return None

    required = {"candidate_id", "schema_version", "event_focus", "action", "target", "system", "eligible_mode_family", "action_target", "target_system", "ambiguity", "noneligible_relation", "noneligible_kind", "event_status", "decision"}
    if set(proposal) != required:
        return reject("TOP_LEVEL_SHAPE")
    if proposal.get("candidate_id") != request.candidate_id:
        return reject("CANDIDATE_ID")
    if proposal.get("schema_version") != SCOPE_PROPOSAL_SCHEMA_VERSION:
        return reject("SCHEMA_VERSION")
    mode = proposal.get("eligible_mode_family")
    if mode not in (*SUPPORTED_SCOPE_MODE_FAMILIES, "NON_ELIGIBLE", "UNKNOWN"):
        return reject("MODE_FAMILY")
    if proposal.get("event_status") not in {"ASSERTED", "NEGATED", "CONDITIONAL", "UNASSERTED"}:
        return reject("EVENT_STATUS")
    if proposal.get("noneligible_kind") not in {"NONE", "EXCLUDED_TRANSPORT_MODE", "NON_URBAN_RAIL", "UNRESOLVED"}:
        return reject("NONELIGIBLE_KIND")
    decision = proposal.get("decision")
    if decision not in {item.value for item in ScopeSemanticSupport}:
        return reject("DECISION_ENUM")

    focus = _strict_record(proposal.get("event_focus"), ("status", "quote"))
    action = _strict_record(proposal.get("action"), ("label",))
    target = _strict_record(proposal.get("target"), ("label",))
    system = _strict_record(proposal.get("system"), ("label",))
    action_target = _strict_record(proposal.get("action_target"), ("status", "relation", "quote"))
    # target_reference is optional; omitted or empty means the target label.
    raw_target_system = proposal.get("target_system")
    target_system = _strict_record(raw_target_system, ("status", "relation", "quote", "target_reference")) or _strict_record(raw_target_system, ("status", "relation", "quote"))
    ambiguity = _strict_record(proposal.get("ambiguity"), ("status", "quote"))
    noneligible = _strict_record(proposal.get("noneligible_relation"), ("status", "quote"))
    if any(item is None for item in (focus, action, target, system, action_target, target_system, ambiguity, noneligible)):
        return reject("NESTED_RECORD_SHAPE")
    assert focus is not None and action is not None and target is not None and system is not None
    assert action_target is not None and target_system is not None and ambiguity is not None and noneligible is not None

    statuses = {"focus": focus["status"], "action_target": action_target["status"], "target_system": target_system["status"], "ambiguity": ambiguity["status"], "noneligible": noneligible["status"]}
    if statuses["focus"] not in {"RESOLVED", "UNRESOLVED", "CONFLICTING"} or statuses["action_target"] not in {"ESTABLISHED", "UNESTABLISHED", "CONFLICTING"} or statuses["target_system"] not in {"ESTABLISHED", "UNESTABLISHED", "CONFLICTING"} or statuses["ambiguity"] not in {"NONE", "UNRESOLVED", "CONFLICTING"} or statuses["noneligible"] not in {"ABSENT", "PRESENT", "UNRESOLVED"}:
        return reject("STATUS_CONSISTENCY")
    if action_target["relation"] not in {"AFFECTS", "LOCATED_AT", "MENTIONS", "UNRESOLVED"} or target_system["relation"] not in {"BELONGS_TO", "PART_OF", "FUNCTIONS_FOR", "LOCATED_AT", "OWNED_BY", "OPERATED_BY", "UNRESOLVED"}:
        return reject("RELATION_TYPE")
    kind = proposal["noneligible_kind"]
    action_target_claimed = statuses["action_target"] in {"ESTABLISHED", "CONFLICTING"}
    target_system_claimed = statuses["target_system"] in {"ESTABLISHED", "CONFLICTING"}

    content = request.principal_content
    quote_required = {
        "event_focus": statuses["focus"] in {"RESOLVED", "CONFLICTING"},
        "action_target": action_target_claimed,
        "target_system": target_system_claimed,
        "ambiguity": statuses["ambiguity"] == "CONFLICTING",
        "noneligible_relation": statuses["noneligible"] == "PRESENT",
    }
    spans: dict[str, tuple[ScopeSupportSpan, ...]] = {}
    quotes: dict[str, str] = {}
    records = (("event_focus", focus), ("action_target", action_target), ("target_system", target_system), ("ambiguity", ambiguity), ("noneligible_relation", noneligible))
    for name, record in records:
        quote = record["quote"]
        if quote == "" and not quote_required[name]:
            continue
        located, quote_failure = _locate_quote(content, quote)
        if not located:
            return reject(quote_failure or "QUOTE_NOT_FOUND")
        spans[name] = located
        quotes[name] = quote

    if statuses["noneligible"] == "ABSENT" and kind != "NONE":
        return reject("NONELIGIBLE_CONSISTENCY")
    if statuses["noneligible"] == "PRESENT" and (mode != "NON_ELIGIBLE" or kind not in {"EXCLUDED_TRANSPORT_MODE", "NON_URBAN_RAIL"}):
        return reject("NONELIGIBLE_CONSISTENCY")

    labels = {"action": _text(action["label"]), "target": _text(target["label"]), "system": _text(system["label"]), "target_reference": _text(target_system.get("target_reference"))}
    if labels["target_reference"] is None and target_system_claimed:
        labels["target_reference"] = labels["target"]
    if labels["action"] is None or labels["target"] is None or (target_system_claimed and labels["system"] is None):
        return reject("ENDPOINT_LABEL")
    # A label not anchored by a claimed relation asserts nothing, but it must
    # still be source text.
    for role, label in labels.items():
        if label is not None and label.casefold() not in content.casefold():
            return reject("ENDPOINT_LABEL")
    action_label, target_label, system_label = labels["action"], labels["target"], labels["system"]
    target_reference = labels["target_reference"]
    # The action must be distinguishable from what it acts on.  Target and
    # system may name the same entity when the action affects the system itself.
    if any(value is not None and action_label.casefold() == value.casefold() for value in (target_label, system_label, target_reference)):
        return reject("ENDPOINT_ROLE_DISTINCTNESS")

    # Same-context rule: each endpoint label must lie inside the relation
    # quotation that establishes it.
    if action_target_claimed:
        if not _within_context(action_label, quotes["action_target"]) or not _within_context(target_label, quotes["action_target"]):
            return reject("ACTION_TARGET_CONTAINMENT")
    if target_system_claimed:
        # The target may be referred to by a same-event reference (anaphora,
        # demonstrative, possessive) inside the target-system quotation; a
        # system that is the target itself needs no second mention.
        identity = system_label.casefold() == target_label.casefold()
        if not _within_context(target_reference, quotes["target_system"]) or not (identity or _within_context(system_label, quotes["target_system"])):
            return reject("TARGET_SYSTEM_CONTAINMENT")
        # A reference other than the target label is bounded to the Candidate
        # event: both relation quotations must lie inside a resolved focus.
        if target_reference.casefold() != target_label.casefold() and statuses["focus"] != "RESOLVED":
            return reject("TARGET_REFERENCE_CONTEXT")

    focus_text = quotes.get("event_focus")
    if focus_text is not None and statuses["focus"] == "RESOLVED":
        for name in ("action_target", "target_system"):
            if name in quotes and quote_required[name] and quotes[name] not in focus_text:
                return reject("EVENT_FOCUS_CONTAINMENT")

    if statuses["noneligible"] == "PRESENT":
        # SC-2: the noneligible relation concerns only the focus action's own
        # target or system.
        noneligible_text = quotes["noneligible_relation"]
        endpoints = [target_label] + ([system_label] if system_label is not None else [])
        if not any(_within_context(label, noneligible_text) for label in endpoints):
            return reject("NONELIGIBLE_RELATION_ENDPOINT")
        if focus_text is not None and statuses["focus"] == "RESOLVED":
            if noneligible_text not in focus_text:
                return reject("NONELIGIBLE_EVENT_FOCUS")

    positive = (decision == ScopeSemanticSupport.IN_SCOPE_SUPPORT.value and statuses["focus"] == "RESOLVED" and proposal["event_status"] == "ASSERTED" and statuses["action_target"] == "ESTABLISHED" and action_target["relation"] in _POSITIVE_ACTION_TARGET_RELATIONS and statuses["target_system"] == "ESTABLISHED" and target_system["relation"] in _POSITIVE_TARGET_SYSTEM_RELATIONS and statuses["ambiguity"] == "NONE" and statuses["noneligible"] == "ABSENT" and mode in SUPPORTED_SCOPE_MODE_FAMILIES)
    if decision == ScopeSemanticSupport.IN_SCOPE_SUPPORT.value and not positive:
        reject("POSITIVE_ACCEPTANCE_CONDITION")
    support = ScopeSemanticSupport.IN_SCOPE_SUPPORT if positive else ScopeSemanticSupport.OUT_OF_SCOPE_SUPPORT
    diagnostic = ScopeDiagnostic.NONE if positive else ScopeDiagnostic.SCOPE_NOT_ESTABLISHED
    if not positive and decision == ScopeSemanticSupport.OUT_OF_SCOPE_SUPPORT.value and mode == "NON_ELIGIBLE" and statuses["noneligible"] == "PRESENT" and statuses["focus"] == "RESOLVED" and proposal["event_status"] == "ASSERTED":
        diagnostic = ScopeDiagnostic(proposal["noneligible_kind"]) if proposal["noneligible_kind"] in {item.value for item in ScopeDiagnostic} else ScopeDiagnostic.SCOPE_NOT_ESTABLISHED

    # Endpoint provenance is bounded by the quotation that establishes it:
    # only label occurrences inside that context are recorded, so a repeated
    # string elsewhere in the source never appears as support.
    relation_support = {
        role: [{"start": span.start, "end": span.end} for span in located]
        for role, located in spans.items()
    }
    endpoint_contexts = {
        "action": spans.get("action_target", ()) if action_target_claimed else (),
        "target": spans.get("action_target", ()) if action_target_claimed else (),
        "target_reference": spans.get("target_system", ()) if target_system_claimed else (),
        "system": spans.get("target_system", ()) if target_system_claimed else (),
    }
    for role, contexts in endpoint_contexts.items():
        if contexts and labels[role] is not None:
            relation_support[role] = [{"start": span.start, "end": span.end} for span in _label_spans(content, contexts, labels[role])]
    return support, diagnostic, {"decision_basis": "scope_semantic_proposal", "schema_version": SCOPE_PROPOSAL_SCHEMA_VERSION, "candidate_event_focus": relation_support.get("event_focus"), "eligible_mode_family": mode, "action_target_relation": action_target["relation"], "target_system_relation": target_system["relation"], "endpoint_labels": dict(labels), "relation_support": relation_support}


def _coerce_response(value: object) -> ScopeSemanticResponse | None:
    if isinstance(value, ScopeSemanticResponse):
        return value
    if isinstance(value, Mapping):
        # Direct adapter output is the complete proposal. Legacy span-only
        # mappings are therefore rejected by the owner below.
        return ScopeSemanticResponse(proposal=value)
    return None


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
        def observe(result: ScopeResult, first_rejection: str | None, response_status: str) -> None:
            if observation_hook is None:
                return
            try:
                observation_hook(
                    ScopeValidationObservation(
                        first_rejection,
                        response_status,
                        result.state,
                        result.diagnostic,
                    )
                )
            except Exception:
                # Observation cannot change the owner's decision or failure behavior.
                return

        if evidence.state is not EvidenceState.READY:
            raise ValueError("ScopeClassifier requires EVIDENCE_READY evidence")
        if self._semantic_helper is None:
            result = self._out_of_scope(evidence.candidate_id, ScopeDiagnostic.SCOPE_NOT_ESTABLISHED, {"decision_basis": "scope_semantic_proposal", "helper": "not_configured"})
            observe(result, "HELPER_NOT_CONFIGURED", "NOT_CALLED")
            return result
        request = ScopeSemanticRequest(evidence.candidate_id, candidate_title, evidence.substantive_content, dict(evidence.provenance))
        try:
            response = _coerce_response(self._semantic_helper(request))
        except (SemanticProviderTechnicalFailure, SemanticProviderConfigurationFailure):
            # RC-6: a technical failure is not OUT_OF_SCOPE.
            raise
        except Exception as exc:
            result = self._out_of_scope(evidence.candidate_id, ScopeDiagnostic.SCOPE_NOT_ESTABLISHED, {"decision_basis": "scope_semantic_proposal", "helper_error": type(exc).__name__})
            observe(result, None, "PROVIDER_FAILURE")
            return result
        if response is None or response.proposal is None:
            result = self._out_of_scope(evidence.candidate_id, ScopeDiagnostic.SCOPE_NOT_ESTABLISHED, {"decision_basis": "scope_semantic_proposal", "helper_response": "invalid"})
            observe(result, "PROPOSAL_MISSING", "INVALID_RESPONSE")
            return result
        rejected_predicates: list[str] | None = [] if observation_hook is not None else None
        try:
            accepted = _proposal_support(response.proposal, request, rejected_predicates)
        except Exception:
            accepted = None
            if rejected_predicates is not None:
                rejected_predicates.append("VALIDATOR_EXCEPTION")
        first_rejection = rejected_predicates[0] if rejected_predicates else None
        if accepted is None:
            result = self._out_of_scope(evidence.candidate_id, ScopeDiagnostic.SCOPE_NOT_ESTABLISHED, {"decision_basis": "scope_semantic_proposal", "proposal": "rejected"})
            observe(result, first_rejection, "OWNER_REJECTED")
            return result
        support, diagnostic, provenance = accepted
        if support is ScopeSemanticSupport.IN_SCOPE_SUPPORT:
            result = ScopeResult(candidate_id=evidence.candidate_id, state=ScopeState.IN_SCOPE, provenance=provenance)
            observe(result, first_rejection, "OWNER_VALIDATED")
            return result
        result = self._out_of_scope(evidence.candidate_id, diagnostic, provenance)
        observe(result, first_rejection, "OWNER_VALIDATED")
        return result

    evaluate = classify

    @staticmethod
    def _out_of_scope(candidate_id: str, diagnostic: ScopeDiagnostic, provenance: Mapping[str, Any]) -> ScopeResult:
        return ScopeResult(candidate_id=candidate_id, state=ScopeState.OUT_OF_SCOPE, diagnostic=diagnostic, provenance=dict(provenance))


__all__ = ["SCOPE_PROPOSAL_SCHEMA_VERSION", "SCOPE_SEMANTIC_RESPONSE_SCHEMA", "SUPPORTED_SCOPE_MODE_FAMILIES", "ScopeClassifier", "ScopeSemanticHelper", "ScopeSemanticRequest", "ScopeSemanticResponse", "ScopeSemanticSupport", "ScopeSupportSpan", "ScopeValidationObservation"]
