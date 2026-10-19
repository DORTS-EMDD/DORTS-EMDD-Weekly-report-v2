"""MaiAgent adapter for the authorized Scope semantic proposal task.

This module owns transport mechanics for one task only.  It never constructs
or returns ``ScopeResult``; Python ``ScopeClassifier`` validates the proposal
and remains the authoritative owner.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import json
import math
import os
from typing import Any
from urllib.parse import quote, urlsplit

from .maiagent_transport import (
    MaiAgentHttpResponse,
    MaiAgentJsonHttpTransport,
    MaiAgentResponseError,
    UrllibMaiAgentJsonTransport,
    load_shared_maiagent_values,
    parse_maiagent_response,
)
from .scope_classifier import (
    SCOPE_PROPOSAL_SCHEMA_VERSION,
    SCOPE_SEMANTIC_RESPONSE_SCHEMA,
    ScopeSemanticRequest,
)


TASK_IDENTITY = "scope_semantic_proposal"
PROMPT_VERSION = "scope-event-target-system-v3"
SCHEMA_VERSION = SCOPE_PROPOSAL_SCHEMA_VERSION
HELPER_VERSION = "maiagent-structured-helper-scope-adapter-v1"
PROVIDER_IDENTIFIER = "maiagent-structured-helper-scope"

SCOPE_TASK_IDENTITY = TASK_IDENTITY
SCOPE_PROMPT_VERSION = PROMPT_VERSION
SCOPE_SCHEMA_VERSION = SCHEMA_VERSION
SCOPE_HELPER_VERSION = HELPER_VERSION
MAIAGENT_SCOPE_PROVIDER_IDENTIFIER = PROVIDER_IDENTIFIER

SCOPE_SEMANTIC_INSTRUCTIONS = (
    "You are a stateless proposal-only semantic helper for the Python ScopeClassifier.",
    "Use only the supplied authoritative principal_content and same-document metadata.",
    "Interpret in order: identify the Candidate event, its asserted action, what the action actually affects, and the transport system that affected target belongs to or for which it functions; only then propose an eligible mode if supported.",
    "The affected target is not automatically the operator, owner, city, publisher, nearby station, route, or whole Metro system. For example, installed platform-door equipment is the target, and irrigation near a station remains irrigation equipment. Do not infer target-system membership from transport vocabulary or proximity.",
    "When the source supports eligibility, use exactly one canonical eligible_mode_family: METRO, MRT, SUBWAY, LIGHT_RAIL, TRAM, URBAN_RAIL, AGT, MONORAIL, or PEOPLE_MOVER. Urban maglev maps to URBAN_RAIL; AGT and People Mover remain distinct. NON_ELIGIBLE and UNKNOWN are valid when their respective noneligible or unresolved status is supported; do not force an eligible family.",
    "Citation policy: event_focus requires a nonempty exact quotation for RESOLVED or CONFLICTING and may be empty for UNRESOLVED. The asserted action and claimed affected target each require their own nonempty exact source quotation.",
    "system, action_target, and target_system require nonempty exact quotations when their relation status is ESTABLISHED or CONFLICTING. Their quotations may be empty when status is UNESTABLISHED and no affirmative relation is established. ambiguity requires a quotation only for CONFLICTING; NONE and UNRESOLVED may be empty. noneligible_relation requires a quotation only for PRESENT; ABSENT and UNRESOLVED may be empty.",
    "Each nonempty action.label, target.label, and system.label must be an exact source-surface substring within its own endpoint quote. Do not translate, paraphrase, normalize, conjugate, nominalize, replace with a synonym, or invent endpoint labels; retain the original language and surface form.",
    "Every nonempty quotation, including optional quotations, must be a contiguous exact substring copied from principal_content, occur exactly once, preserve spelling and punctuation, and identify only evidence it supports. Never invent or reconstruct a quotation or offsets to represent absence or uncertainty.",
    "For an ESTABLISHED or CONFLICTING action_target relation, its quotation must contain the exact selected action.quote and target.quote endpoints. For an ESTABLISHED or CONFLICTING target_system relation, its quotation must contain the exact selected target.quote and system.quote endpoints within the selected event. A noneligible PRESENT quotation must identify the target or system involved.",
    "A bounded relation quotation may span multiple sentences only when the source genuinely expresses the relation across them. Select a relevant contiguous excerpt rather than the whole source, and do not choose an action endpoint broader than the relation quotation can contain.",
    "The selected event_focus.quote must encompass the source material supporting the established relationships attributed to that Candidate event. Do not borrow support from a separate independent event in the same document.",
    "IN_SCOPE_SUPPORT requires a RESOLVED Candidate event, an ASSERTED action, an established AFFECTS action-to-target relation, and an established eligible target-to-system relation supported by exact endpoint quotations.",
    "A location, operator identity, ownership identity, generic equipment word, or nearby station is not target-to-system membership. Use AFFECTS only for action-to-target evidence; use BELONGS_TO, PART_OF, or FUNCTIONS_FOR for eligible membership. LOCATED_AT, OWNED_BY, and OPERATED_BY never establish eligibility.",
    "Interpret source-grounded anaphora, demonstratives, possessives, component relationships, and cross-sentence grammatical references, including Japanese and French constructions. These may support a relationship only when the supplied source clearly connects the actual affected target to the system; preserve UNCERTAIN if the antecedent or relation remains ambiguous, and do not use outside knowledge.",
    "Interpret action-to-target independently from target eligibility: when the source clearly establishes an action affecting a target, mark action_target ESTABLISHED even if target_system is UNESTABLISHED or a supported noneligible relationship. Do not mark a clear action unresolved merely because overall Scope is negative.",
    "When noneligible_relation.status is ABSENT, noneligible_kind must be NONE. When status is PRESENT, provide exact supporting evidence, use mode NON_ELIGIBLE, and choose only a supported kind: EXCLUDED_TRANSPORT_MODE or NON_URBAN_RAIL. For a genuinely unresolved noneligible relationship, use UNRESOLVED status and kind consistently; do not invent a negative relationship to force a diagnostic.",
    "Record noneligible, ambiguous, contradictory, negated, conditional, and unasserted events explicitly. Use UNESTABLISHED or UNRESOLVED when evidence does not establish a relation; do not label uncertainty as an affirmative relation merely to fill a citation field.",
    "Do not force a positive proposal or output IN_SCOPE_SUPPORT to satisfy a benchmark. A complete citation is a necessary mechanical condition, not independent proof of a semantic relation.",
    "Do not search, browse, use tools, retrieve external knowledge, or return a ScopeResult or diagnostic.",
    "Return exactly the supplied JSON schema with no extra fields and no prose outside JSON.",
)


MAIAGENT_SCOPE_RESPONSE_SCHEMA = SCOPE_SEMANTIC_RESPONSE_SCHEMA
SCOPE_RESPONSE_SCHEMA = MAIAGENT_SCOPE_RESPONSE_SCHEMA


@dataclass(frozen=True, slots=True)
class MaiAgentScopeProviderConfig:
    api_base: str
    api_key: str = field(repr=False)
    chatbot_id: str = field(repr=False)
    timeout_seconds: float = 45.0

    def __post_init__(self) -> None:
        values = (self.api_base, self.api_key, self.chatbot_id)
        if any(not isinstance(value, str) for value in values):
            raise ValueError("MaiAgent Scope configuration values must be strings")
        if any("\r" in value or "\n" in value for value in values):
            raise ValueError("MaiAgent Scope configuration contains invalid characters")
        try:
            parsed = urlsplit(self.api_base)
            hostname = parsed.hostname
            parsed.port
        except (TypeError, ValueError):
            raise ValueError("MaiAgent API base must be an absolute HTTPS origin") from None
        if parsed.scheme != "https" or not parsed.netloc or hostname is None or parsed.username is not None or parsed.password is not None or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("MaiAgent API base must be an absolute HTTPS origin")
        if not self.api_key.strip() or not self.chatbot_id.strip():
            raise ValueError("MaiAgent Scope API key and chatbot ID are required")
        if isinstance(self.timeout_seconds, bool) or not isinstance(self.timeout_seconds, (int, float)) or not math.isfinite(float(self.timeout_seconds)) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

    @property
    def completion_endpoint(self) -> str:
        return f"{self.api_base.rstrip('/')}/api/v1/chatbots/{quote(self.chatbot_id, safe='')}/completions/"

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None, *, timeout_seconds: float = 45.0, dotenv_path: str | os.PathLike[str] | None = None):
        values = load_shared_maiagent_values(environ, dotenv_path=dotenv_path)
        api_base, api_key, chatbot_id = (values.get(key) for key in ("MAIAGENT_API_BASE", "MAIAGENT_API_KEY", "MAIAGENT_STRUCTURED_HELPER_CHATBOT_ID"))
        if not all(isinstance(value, str) and value.strip() for value in (api_base, api_key, chatbot_id)):
            return None
        return cls(api_base.strip(), api_key.strip(), chatbot_id.strip(), timeout_seconds)


def build_maiagent_scope_model_input(request: ScopeSemanticRequest) -> dict[str, Any]:
    if not isinstance(request, ScopeSemanticRequest):
        raise TypeError("MaiAgent Scope input requires ScopeSemanticRequest")
    return {
        "task_identity": TASK_IDENTITY,
        "prompt_version": PROMPT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "helper_version": HELPER_VERSION,
        "instructions": list(SCOPE_SEMANTIC_INSTRUCTIONS),
        "scope_request": request.as_payload(),
        "authoritative_response_contract": {"schema_version": SCHEMA_VERSION, "json_schema": MAIAGENT_SCOPE_RESPONSE_SCHEMA},
    }


class MaiAgentScopeProviderFailure(RuntimeError):
    """Safe technical provider failure without provider-controlled details."""

    def __init__(self, message: str, *, failure_category: str = "PROVIDER_FAILURE") -> None:
        super().__init__(message)
        self.failure_category = failure_category


class MaiAgentScopeProposalProvider:
    def __init__(self, config: MaiAgentScopeProviderConfig, *, transport: MaiAgentJsonHttpTransport | None = None) -> None:
        if not isinstance(config, MaiAgentScopeProviderConfig):
            raise TypeError("MaiAgentScopeProposalProvider requires MaiAgentScopeProviderConfig")
        self._config = config
        self._transport = transport if transport is not None else UrllibMaiAgentJsonTransport()

    def __call__(self, request: ScopeSemanticRequest) -> object:
        if not isinstance(request, ScopeSemanticRequest):
            raise TypeError("MaiAgent Scope provider accepts only ScopeSemanticRequest")
        request_content = json.dumps(build_maiagent_scope_model_input(request), ensure_ascii=False, separators=(",", ":"))
        body = json.dumps({"message": {"role": "user", "content": request_content}, "conversation": None, "attachments": [], "is_streaming": False}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        try:
            response = self._transport(self._config.completion_endpoint, headers={"Authorization": f"Api-Key {self._config.api_key}", "Content-Type": "application/json", "Accept": "application/json"}, body=body, timeout_seconds=float(self._config.timeout_seconds))
        except TimeoutError:
            raise TimeoutError("MaiAgent Scope request timed out") from None
        except Exception:
            raise MaiAgentScopeProviderFailure("MaiAgent Scope provider transport failed", failure_category="TRANSPORT") from None
        if not isinstance(response, MaiAgentHttpResponse) or response.status_code != 200:
            raise MaiAgentScopeProviderFailure("MaiAgent Scope provider request failed", failure_category="HTTP_STATUS")
        try:
            return parse_maiagent_response(response.body)
        except MaiAgentResponseError:
            raise MaiAgentScopeProviderFailure("MaiAgent Scope provider response was invalid", failure_category="RESPONSE_PARSE") from None


MaiAgentScopeProvider = MaiAgentScopeProposalProvider
MaiAgentScopeAdapter = MaiAgentScopeProposalProvider
MaiAgentScopeFailure = MaiAgentScopeProviderFailure


def build_maiagent_scope_provider(config: MaiAgentScopeProviderConfig | None = None, *, transport: MaiAgentJsonHttpTransport | None = None, environ: Mapping[str, str] | None = None, timeout_seconds: float = 45.0, dotenv_path: str | os.PathLike[str] | None = None) -> MaiAgentScopeProposalProvider | None:
    resolved = config or MaiAgentScopeProviderConfig.from_environment(environ, timeout_seconds=timeout_seconds, dotenv_path=dotenv_path)
    return None if resolved is None else MaiAgentScopeProposalProvider(resolved, transport=transport)


build_maiagent_scope_proposal_provider = build_maiagent_scope_provider

__all__ = [
    "HELPER_VERSION", "MAIAGENT_SCOPE_PROVIDER_IDENTIFIER", "MAIAGENT_SCOPE_RESPONSE_SCHEMA", "MaiAgentScopeAdapter", "MaiAgentScopeFailure", "MaiAgentScopeProposalProvider", "MaiAgentScopeProvider", "MaiAgentScopeProviderConfig", "MaiAgentScopeProviderFailure", "PROMPT_VERSION", "PROVIDER_IDENTIFIER", "SCHEMA_VERSION", "SCOPE_HELPER_VERSION", "SCOPE_PROMPT_VERSION", "SCOPE_RESPONSE_SCHEMA", "SCOPE_SCHEMA_VERSION", "SCOPE_SEMANTIC_INSTRUCTIONS", "SCOPE_TASK_IDENTITY", "TASK_IDENTITY", "build_maiagent_scope_model_input", "build_maiagent_scope_proposal_provider", "build_maiagent_scope_provider",
]
