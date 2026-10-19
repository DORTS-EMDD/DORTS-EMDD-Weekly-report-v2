"""Candidate-stage Scope owner and bounded semantic proposal seam."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Callable, Protocol

from .contracts import EvidenceResult, EvidenceState, ScopeDiagnostic, ScopeResult, ScopeState


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


SCOPE_PROPOSAL_SCHEMA_VERSION = "scope-semantic-proposal-v1"
SUPPORTED_SCOPE_MODE_FAMILIES = (
    "METRO", "MRT", "SUBWAY", "LIGHT_RAIL", "TRAM", "URBAN_RAIL", "AGT", "MONORAIL", "PEOPLE_MOVER"
)

SCOPE_SEMANTIC_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "candidate_id": {"type": "string"},
        "schema_version": {"type": "string", "enum": [SCOPE_PROPOSAL_SCHEMA_VERSION]},
        "event_focus": {"type": "object", "additionalProperties": False, "properties": {"status": {"type": "string", "enum": ["RESOLVED", "UNRESOLVED", "CONFLICTING"]}, "quote": {"type": "string"}}, "required": ["status", "quote"]},
        "action": {"type": "object", "additionalProperties": False, "properties": {"label": {"type": "string"}, "quote": {"type": "string"}}, "required": ["label", "quote"]},
        "target": {"type": "object", "additionalProperties": False, "properties": {"label": {"type": "string"}, "quote": {"type": "string"}}, "required": ["label", "quote"]},
        "system": {"type": "object", "additionalProperties": False, "properties": {"label": {"type": "string"}, "quote": {"type": "string"}}, "required": ["label", "quote"]},
        "eligible_mode_family": {"type": "string", "enum": [*SUPPORTED_SCOPE_MODE_FAMILIES, "NON_ELIGIBLE", "UNKNOWN"]},
        "action_target": {"type": "object", "additionalProperties": False, "properties": {"status": {"type": "string", "enum": ["ESTABLISHED", "UNESTABLISHED", "CONFLICTING"]}, "relation": {"type": "string", "enum": ["AFFECTS", "LOCATED_AT", "MENTIONS", "UNRESOLVED"]}, "quote": {"type": "string"}}, "required": ["status", "relation", "quote"]},
        "target_system": {"type": "object", "additionalProperties": False, "properties": {"status": {"type": "string", "enum": ["ESTABLISHED", "UNESTABLISHED", "CONFLICTING"]}, "relation": {"type": "string", "enum": ["BELONGS_TO", "PART_OF", "FUNCTIONS_FOR", "LOCATED_AT", "OWNED_BY", "OPERATED_BY", "UNRESOLVED"]}, "quote": {"type": "string"}}, "required": ["status", "relation", "quote"]},
        "ambiguity": {"type": "object", "additionalProperties": False, "properties": {"status": {"type": "string", "enum": ["NONE", "UNRESOLVED", "CONFLICTING"]}, "quote": {"type": "string"}}, "required": ["status", "quote"]},
        "noneligible_relation": {"type": "object", "additionalProperties": False, "properties": {"status": {"type": "string", "enum": ["ABSENT", "PRESENT", "UNRESOLVED"]}, "quote": {"type": "string"}}, "required": ["status", "quote"]},
        "noneligible_kind": {"type": "string", "enum": ["NONE", "EXCLUDED_TRANSPORT_MODE", "NON_URBAN_RAIL", "UNRESOLVED"]},
        "event_status": {"type": "string", "enum": ["ASSERTED", "NEGATED", "CONDITIONAL", "UNASSERTED"]},
        "decision": {"type": "string", "enum": ["IN_SCOPE_SUPPORT", "OUT_OF_SCOPE_SUPPORT", "UNCERTAIN"]},
    },
    "required": ["candidate_id", "schema_version", "event_focus", "action", "target", "system", "eligible_mode_family", "action_target", "target_system", "ambiguity", "noneligible_relation", "noneligible_kind", "event_status", "decision"],
}


def _strict_record(value: object, keys: tuple[str, ...]) -> Mapping[str, Any] | None:
    if not isinstance(value, Mapping) or set(value) != set(keys):
        return None
    return value


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _locate_quote(content: str, value: object) -> tuple[ScopeSupportSpan | None, str | None]:
    quote = _text(value)
    if quote is None:
        return None, "QUOTE_MISSING"
    start = content.find(quote)
    if start < 0:
        return None, "QUOTE_NOT_FOUND"
    if content.find(quote, start + 1) >= 0:
        return None, "QUOTE_NOT_UNIQUE"
    return ScopeSupportSpan(start, start + len(quote)), None


def _proposal_support(
    proposal: Mapping[str, Any],
    request: ScopeSemanticRequest,
    rejected_predicates: list[str] | None = None,
):
    """Validate the complete relation and derive coordinates locally."""
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
    action = _strict_record(proposal.get("action"), ("label", "quote"))
    target = _strict_record(proposal.get("target"), ("label", "quote"))
    system = _strict_record(proposal.get("system"), ("label", "quote"))
    action_target = _strict_record(proposal.get("action_target"), ("status", "relation", "quote"))
    target_system = _strict_record(proposal.get("target_system"), ("status", "relation", "quote"))
    ambiguity = _strict_record(proposal.get("ambiguity"), ("status", "quote"))
    noneligible = _strict_record(proposal.get("noneligible_relation"), ("status", "quote"))
    if any(item is None for item in (focus, action, target, system, action_target, target_system, ambiguity, noneligible)):
        return reject("NESTED_RECORD_SHAPE")
    assert focus is not None and action is not None and target is not None and system is not None
    assert action_target is not None and target_system is not None and ambiguity is not None and noneligible is not None

    content = request.principal_content
    spans: dict[str, ScopeSupportSpan] = {}
    for name, record in (("event_focus", focus), ("action", action), ("target", target), ("system", system), ("action_target", action_target), ("target_system", target_system), ("ambiguity", ambiguity), ("noneligible_relation", noneligible)):
        span, quote_failure = _locate_quote(content, record["quote"])
        if span is None:
            return reject(quote_failure or "QUOTE_NOT_FOUND")
        spans[name] = span
    labels = {name: _text(record["label"]) for name, record in (("action", action), ("target", target), ("system", system))}
    if any(value is None for value in labels.values()):
        return reject("ENDPOINT_LABEL")
    endpoint_quotes = (action["quote"], target["quote"], system["quote"])
    if len(set(endpoint_quotes)) != 3:
        return reject("ENDPOINT_QUOTE_DISTINCTNESS")
    for name, label in labels.items():
        if label.casefold() not in content[spans[name].start:spans[name].end].casefold():
            return reject("ENDPOINT_LABEL")

    # Every material relation must be inside the selected event focus. This
    # blocks borrowing an eligible span from a separate independent event.
    focus_start, focus_end = spans["event_focus"].start, spans["event_focus"].end
    for name in ("action", "target", "system", "action_target", "target_system"):
        span = spans[name]
        if not (focus_start <= span.start and span.end <= focus_end):
            return reject("EVENT_FOCUS_CONTAINMENT")
    relation_text = content[spans["action_target"].start:spans["action_target"].end]
    system_text = content[spans["target_system"].start:spans["target_system"].end]
    if action["quote"] not in relation_text or target["quote"] not in relation_text:
        return reject("ACTION_TARGET_CONTAINMENT")
    if target["quote"] not in system_text or system["quote"] not in system_text:
        return reject("TARGET_SYSTEM_CONTAINMENT")

    statuses = {"focus": focus["status"], "action_target": action_target["status"], "target_system": target_system["status"], "ambiguity": ambiguity["status"], "noneligible": noneligible["status"]}
    if statuses["focus"] not in {"RESOLVED", "UNRESOLVED", "CONFLICTING"} or statuses["action_target"] not in {"ESTABLISHED", "UNESTABLISHED", "CONFLICTING"} or statuses["target_system"] not in {"ESTABLISHED", "UNESTABLISHED", "CONFLICTING"} or statuses["ambiguity"] not in {"NONE", "UNRESOLVED", "CONFLICTING"} or statuses["noneligible"] not in {"ABSENT", "PRESENT", "UNRESOLVED"}:
        return reject("STATUS_CONSISTENCY")
    if action_target["relation"] not in {"AFFECTS", "LOCATED_AT", "MENTIONS", "UNRESOLVED"} or target_system["relation"] not in {"BELONGS_TO", "PART_OF", "FUNCTIONS_FOR", "LOCATED_AT", "OWNED_BY", "OPERATED_BY", "UNRESOLVED"}:
        return reject("RELATION_TYPE")
    kind = proposal["noneligible_kind"]
    if statuses["noneligible"] == "ABSENT" and kind != "NONE":
        return reject("NONELIGIBLE_CONSISTENCY")
    if statuses["noneligible"] == "PRESENT" and (mode != "NON_ELIGIBLE" or kind not in {"EXCLUDED_TRANSPORT_MODE", "NON_URBAN_RAIL"}):
        return reject("NONELIGIBLE_CONSISTENCY")

    positive = (decision == ScopeSemanticSupport.IN_SCOPE_SUPPORT.value and statuses["focus"] == "RESOLVED" and proposal["event_status"] == "ASSERTED" and statuses["action_target"] == "ESTABLISHED" and action_target["relation"] == "AFFECTS" and statuses["target_system"] == "ESTABLISHED" and target_system["relation"] in {"BELONGS_TO", "PART_OF", "FUNCTIONS_FOR"} and statuses["ambiguity"] == "NONE" and statuses["noneligible"] == "ABSENT" and mode in SUPPORTED_SCOPE_MODE_FAMILIES)
    if decision == ScopeSemanticSupport.IN_SCOPE_SUPPORT.value and not positive:
        reject("POSITIVE_ACCEPTANCE_CONDITION")
    support = ScopeSemanticSupport.IN_SCOPE_SUPPORT if positive else ScopeSemanticSupport.OUT_OF_SCOPE_SUPPORT
    diagnostic = ScopeDiagnostic.NONE if positive else ScopeDiagnostic.SCOPE_NOT_ESTABLISHED
    if not positive and decision == ScopeSemanticSupport.OUT_OF_SCOPE_SUPPORT.value and mode == "NON_ELIGIBLE" and statuses["noneligible"] == "PRESENT":
        diagnostic = ScopeDiagnostic(proposal["noneligible_kind"]) if proposal["noneligible_kind"] in {item.value for item in ScopeDiagnostic} else ScopeDiagnostic.SCOPE_NOT_ESTABLISHED
    relation_support = {role: {"start": span.start, "end": span.end} for role, span in spans.items()}
    return support, diagnostic, {"decision_basis": "scope_semantic_proposal", "schema_version": SCOPE_PROPOSAL_SCHEMA_VERSION, "candidate_event_focus": relation_support["event_focus"], "eligible_mode_family": mode, "action_target_relation": action_target["relation"], "target_system_relation": target_system["relation"], "relation_support": relation_support}


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
