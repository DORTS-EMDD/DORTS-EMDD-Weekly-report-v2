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
PROMPT_VERSION = "scope-event-target-system-v1"
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
    "Resolve the candidate event, its asserted action, actual affected target, and the transport system that target belongs to.",
    "Use exactly one canonical eligible_mode_family: METRO, MRT, SUBWAY, LIGHT_RAIL, TRAM, URBAN_RAIL, AGT, MONORAIL, or PEOPLE_MOVER. Urban maglev maps to URBAN_RAIL; AGT and People Mover remain distinct choices.",
    "IN_SCOPE_SUPPORT requires source-grounded action-to-target and target-to-system relations for an eligible urban-rail family.",
    "A location, operator, ownership identity, generic equipment word, or nearby station is not a target-to-system relation.",
    "Use AFFECTS only for action-to-target evidence; use BELONGS_TO, PART_OF, or FUNCTIONS_FOR for an eligible target-to-system relation. LOCATED_AT, OWNED_BY, and OPERATED_BY do not establish eligibility.",
    "Record noneligible, ambiguous, contradictory, negated, conditional, and unasserted events explicitly.",
    "Copy exact source quotations for the event focus and every material relationship; do not emit offsets.",
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
            raise MaiAgentScopeProviderFailure("MaiAgent Scope provider transport failed") from None
        if not isinstance(response, MaiAgentHttpResponse) or response.status_code != 200:
            raise MaiAgentScopeProviderFailure("MaiAgent Scope provider request failed")
        try:
            return parse_maiagent_response(response.body)
        except MaiAgentResponseError:
            raise MaiAgentScopeProviderFailure("MaiAgent Scope provider response was invalid") from None


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
