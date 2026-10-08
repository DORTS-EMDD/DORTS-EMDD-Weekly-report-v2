"""MaiAgent adapter for the bounded E&M Taxonomy proposal seam.

This module is a stateless transport adapter only.  The :class:`Taxonomy`
owner remains responsible for all semantic validation, exact quote
localization, provenance rules, and construction of ``TaxonomyResult``.
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
from .taxonomy import TaxonomySemanticRequest
from .contracts import canonical_em_system_ids


TASK_IDENTITY = "taxonomy_semantic_proposal"
PROMPT_VERSION = "taxonomy-principal-body-v1"
SCHEMA_VERSION = "taxonomy-semantic-proposal-v1"
HELPER_VERSION = "maiagent-structured-helper-taxonomy-adapter-v1"
PROVIDER_IDENTIFIER = "maiagent-structured-helper-taxonomy"

TAXONOMY_TASK_IDENTITY = TASK_IDENTITY
TAXONOMY_PROMPT_VERSION = PROMPT_VERSION
TAXONOMY_SCHEMA_VERSION = SCHEMA_VERSION
TAXONOMY_HELPER_VERSION = HELPER_VERSION
MAIAGENT_TAXONOMY_PROVIDER_IDENTIFIER = PROVIDER_IDENTIFIER


TAXONOMY_INSTRUCTIONS = (
    "You are a stateless proposal-only semantic helper for the Python Taxonomy owner.",
    "Inspect every supplied EventGroup member and use only its authoritative substantive_content.",
    "Classify only the existing canonical E&M system IDs in the supplied response schema.",
    "Use the repository's canonical system registry; do not create another registry, primary system, ranking, or eighth system.",
    "Preserve every valid multilabel outcome; system order has no semantic priority.",
    "Map subsystems according to evidence-supported technical function; onboard signalling and radio follow their technical function.",
    "SCADA requires evidence of a concrete controlled or monitored system function.",
    "OCC requires evidence of a concrete system function.",
    "Cybersecurity requires evidence of an affected technical object.",
    "Generic depot, train, network, station, platform, equipment, or system wording alone does not establish a mapping.",
    "Maintenance software follows the technical object being monitored, diagnosed, inspected, maintained, or predicted; workflow, AI, analytics, deployment location, or user alone does not establish a system.",
    "TAXONOMY_EVALUATED may contain zero or more systems; evaluated-empty is legal only when the evidence establishes no reasonable canonical mapping.",
    "TAXONOMY_UNRESOLVED is legal when a parent system cannot be reliably determined.",
    "Use CONFLICTING_SYSTEM_EVIDENCE only for genuinely competing supported hypotheses.",
    "Every assigned system requires system-specific support with an exact quote from the named supplied member.",
    "Exact quotes must be copied from the named substantive_content member; do not paraphrase, normalize, synthesize, or borrow across sources.",
    "INSUFFICIENT_SYSTEM_EVIDENCE provenance must identify all supplied members as required by the owner contract.",
    "Do not propose NOT_EVALUATED and do not create a final TaxonomyResult.",
    "Do not use external knowledge, search, RAG, tools, conversation history, or surrounding messages.",
    "Return JSON only, with no Markdown, no prose outside JSON, and no extra fields.",
)


def _citation_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "system_id": {
                "type": "string",
                "enum": [system.value for system in canonical_em_system_ids()],
            },
            "candidate_id": {"type": "string"},
            "exact_quote": {"type": "string"},
        },
        "required": ["system_id", "candidate_id", "exact_quote"],
    }


MAIAGENT_TAXONOMY_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "event_id": {"type": "string"},
        "taxonomy_state": {
            "type": "string",
            "enum": ["TAXONOMY_EVALUATED", "TAXONOMY_UNRESOLVED"],
        },
        "systems": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": [system.value for system in canonical_em_system_ids()],
            },
        },
        "taxonomy_resolution_reason": {
            "type": ["string", "null"],
            "enum": [None, "INSUFFICIENT_SYSTEM_EVIDENCE", "CONFLICTING_SYSTEM_EVIDENCE"],
        },
        "support_citations": {
            "type": "array",
            "items": _citation_schema(),
        },
        "conflict_citations": {
            "type": "array",
            "items": _citation_schema(),
        },
        "insufficient_provenance": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "properties": {
                "member_candidate_ids": {"type": "array", "items": {"type": "string"}},
                "diagnostic": {"type": "string"},
            },
            "required": ["member_candidate_ids", "diagnostic"],
        },
    },
    "required": [
        "event_id",
        "taxonomy_state",
        "systems",
        "taxonomy_resolution_reason",
        "support_citations",
        "conflict_citations",
        "insufficient_provenance",
    ],
}

# Descriptive aliases keep the task-specific schema discoverable without
# introducing a second schema object or a second system registry.
TAXONOMY_RESPONSE_SCHEMA = MAIAGENT_TAXONOMY_RESPONSE_SCHEMA
_MAIAGENT_TAXONOMY_RESPONSE_SCHEMA = MAIAGENT_TAXONOMY_RESPONSE_SCHEMA


@dataclass(frozen=True, slots=True)
class MaiAgentTaxonomyProviderConfig:
    """Mechanical configuration for the shared Structured Helper."""

    api_base: str
    api_key: str = field(repr=False)
    chatbot_id: str = field(repr=False)
    timeout_seconds: float = 45.0

    def __post_init__(self) -> None:
        values = (self.api_base, self.api_key, self.chatbot_id)
        if any(not isinstance(value, str) for value in values):
            raise ValueError("MaiAgent Taxonomy configuration values must be strings")
        if any("\r" in value or "\n" in value for value in values):
            raise ValueError("MaiAgent Taxonomy configuration contains invalid characters")
        try:
            parsed = urlsplit(self.api_base)
            hostname = parsed.hostname
            parsed.port
        except (TypeError, ValueError):
            raise ValueError("MaiAgent API base must be an absolute HTTPS origin") from None
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("MaiAgent API base must be an absolute HTTPS origin")
        if not self.api_key.strip():
            raise ValueError("MaiAgent API key is required")
        if not self.chatbot_id.strip():
            raise ValueError("MaiAgent structured helper chatbot ID is required")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(float(self.timeout_seconds))
            or self.timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be positive")

    @property
    def completion_endpoint(self) -> str:
        chatbot_id = quote(self.chatbot_id, safe="")
        return (
            f"{self.api_base.rstrip('/')}/api/v1/chatbots/"
            f"{chatbot_id}/completions/"
        )

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        timeout_seconds: float = 45.0,
        dotenv_path: str | os.PathLike[str] | None = None,
    ) -> "MaiAgentTaxonomyProviderConfig | None":
        values = load_shared_maiagent_values(environ, dotenv_path=dotenv_path)
        api_base = values.get("MAIAGENT_API_BASE")
        api_key = values.get("MAIAGENT_API_KEY")
        chatbot_id = values.get("MAIAGENT_STRUCTURED_HELPER_CHATBOT_ID")
        if not all(
            isinstance(value, str) and value.strip()
            for value in (api_base, api_key, chatbot_id)
        ):
            return None
        return cls(
            api_base=api_base.strip(),
            api_key=api_key.strip(),
            chatbot_id=chatbot_id.strip(),
            timeout_seconds=timeout_seconds,
        )


class MaiAgentTaxonomyProviderFailure(RuntimeError):
    """Safe technical failure; no credential or raw provider data is retained."""


class MaiAgentTaxonomyProposalProvider:
    """One-call proposal adapter; Taxonomy remains the authoritative owner."""

    def __init__(
        self,
        config: MaiAgentTaxonomyProviderConfig,
        *,
        transport: MaiAgentJsonHttpTransport | None = None,
    ) -> None:
        if not isinstance(config, MaiAgentTaxonomyProviderConfig):
            raise TypeError("MaiAgentTaxonomyProposalProvider requires MaiAgentTaxonomyProviderConfig")
        self._config = config
        self._transport = transport if transport is not None else UrllibMaiAgentJsonTransport()

    def __call__(self, request: TaxonomySemanticRequest) -> object:
        if not isinstance(request, TaxonomySemanticRequest):
            raise TypeError("MaiAgentTaxonomyProposalProvider accepts only TaxonomySemanticRequest")
        request_content = json.dumps(
            build_maiagent_taxonomy_model_input(request),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        body = json.dumps(
            {
                "message": {"role": "user", "content": request_content},
                "conversation": None,
                "attachments": [],
                "is_streaming": False,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        try:
            response = self._transport(
                self._config.completion_endpoint,
                headers={
                    "Authorization": f"Api-Key {self._config.api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                body=body,
                timeout_seconds=float(self._config.timeout_seconds),
            )
        except TimeoutError:
            raise TimeoutError("MaiAgent Taxonomy request timed out") from None
        except Exception:
            raise MaiAgentTaxonomyProviderFailure(
                "MaiAgent Taxonomy provider transport failed"
            ) from None

        if not isinstance(response, MaiAgentHttpResponse) or response.status_code != 200:
            raise MaiAgentTaxonomyProviderFailure(
                "MaiAgent Taxonomy provider request failed"
            )
        try:
            return parse_maiagent_response(response.body)
        except MaiAgentResponseError:
            raise MaiAgentTaxonomyProviderFailure(
                "MaiAgent Taxonomy provider response was invalid"
            ) from None


def build_maiagent_taxonomy_model_input(
    request: TaxonomySemanticRequest,
) -> dict[str, Any]:
    """Build one complete task-specific Structured Helper input."""

    if not isinstance(request, TaxonomySemanticRequest):
        raise TypeError("MaiAgent Taxonomy model input requires TaxonomySemanticRequest")
    return {
        "task_identity": TASK_IDENTITY,
        "prompt_version": PROMPT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "helper_version": HELPER_VERSION,
        "instructions": list(TAXONOMY_INSTRUCTIONS),
        "taxonomy_request": request.as_payload(),
        "authoritative_response_contract": {
            "schema_version": SCHEMA_VERSION,
            "json_schema": MAIAGENT_TAXONOMY_RESPONSE_SCHEMA,
        },
    }


def build_maiagent_taxonomy_provider(
    config: MaiAgentTaxonomyProviderConfig | None = None,
    *,
    transport: MaiAgentJsonHttpTransport | None = None,
    environ: Mapping[str, str] | None = None,
    timeout_seconds: float = 45.0,
    dotenv_path: str | os.PathLike[str] | None = None,
) -> MaiAgentTaxonomyProposalProvider | None:
    """Construct the adapter without making a network call."""

    resolved = config
    if resolved is None:
        resolved = MaiAgentTaxonomyProviderConfig.from_environment(
            environ,
            timeout_seconds=timeout_seconds,
            dotenv_path=dotenv_path,
        )
    if resolved is None:
        return None
    return MaiAgentTaxonomyProposalProvider(resolved, transport=transport)


# Naming aliases for callers that use the protocol or adapter terminology.
MaiAgentTaxonomyProvider = MaiAgentTaxonomyProposalProvider
MaiAgentTaxonomyAdapter = MaiAgentTaxonomyProposalProvider
MaiAgentTaxonomyFailure = MaiAgentTaxonomyProviderFailure
build_maiagent_taxonomy_proposal_provider = build_maiagent_taxonomy_provider


__all__ = [
    "HELPER_VERSION",
    "MAIAGENT_TAXONOMY_PROVIDER_IDENTIFIER",
    "MAIAGENT_TAXONOMY_RESPONSE_SCHEMA",
    "MaiAgentTaxonomyAdapter",
    "MaiAgentTaxonomyFailure",
    "MaiAgentTaxonomyProposalProvider",
    "MaiAgentTaxonomyProvider",
    "MaiAgentTaxonomyProviderConfig",
    "MaiAgentTaxonomyProviderFailure",
    "PROMPT_VERSION",
    "PROVIDER_IDENTIFIER",
    "SCHEMA_VERSION",
    "TASK_IDENTITY",
    "TAXONOMY_HELPER_VERSION",
    "TAXONOMY_INSTRUCTIONS",
    "TAXONOMY_PROMPT_VERSION",
    "TAXONOMY_RESPONSE_SCHEMA",
    "TAXONOMY_SCHEMA_VERSION",
    "TAXONOMY_TASK_IDENTITY",
    "build_maiagent_taxonomy_model_input",
    "build_maiagent_taxonomy_proposal_provider",
    "build_maiagent_taxonomy_provider",
]
