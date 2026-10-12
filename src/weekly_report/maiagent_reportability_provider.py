"""MaiAgent adapter for the bounded Reportability proposal seam.

The adapter is proposal-only.  ``Reportability`` remains the sole
authoritative owner of the final state, population checks, quote validation,
and canonical source spans.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import json
import math
import os
from typing import Any
from urllib.parse import quote, urlsplit

from .contracts import ReportabilitySemanticRequest
from .maiagent_transport import (
    MaiAgentHttpResponse,
    MaiAgentJsonHttpTransport,
    MaiAgentResponseError,
    UrllibMaiAgentJsonTransport,
    load_shared_maiagent_values,
    parse_maiagent_response,
)


TASK_IDENTITY = "reportability_semantic_proposal"
PROMPT_VERSION = "reportability-principal-body-v1"
SCHEMA_VERSION = "reportability-semantic-proposal-v1"
HELPER_VERSION = "maiagent-structured-helper-reportability-adapter-v1"
PROVIDER_IDENTIFIER = "maiagent-structured-helper-reportability"

REPORTABILITY_TASK_IDENTITY = TASK_IDENTITY
REPORTABILITY_PROMPT_VERSION = PROMPT_VERSION
REPORTABILITY_SCHEMA_VERSION = SCHEMA_VERSION
REPORTABILITY_HELPER_VERSION = HELPER_VERSION
MAIAGENT_REPORTABILITY_PROVIDER_IDENTIFIER = PROVIDER_IDENTIFIER


REPORTABILITY_INSTRUCTIONS = (
    "You are a stateless proposal-only semantic helper for the Python Reportability owner.",
    "Use only the supplied authoritative substantive_content in the current request.",
    "Inspect every supplied member exactly once before proposing a state.",
    "Return exactly REPORTABLE or NOT_REPORTABLE.",
    "examined_candidate_ids must cover every supplied member exactly once.",
    "REPORTABLE requires at least one exact positive source quote.",
    "Each support citation must name a supplied candidate_id.",
    "Copy every exact_quote unchanged from that candidate's supplied substantive_content.",
    "NOT_REPORTABLE must not fabricate negative evidence or citations.",
    "Do not return numeric offsets, start, end, support_spans, scores, or rankings.",
    "Do not search, browse, use tools, RAG, or outside knowledge.",
    "Do not infer from publisher reputation, snippets, URLs, or any unsupplied fact.",
    "Do not decide Category, Taxonomy, Ordering, or write the formal report.",
    "Do not output ReportabilityResult; Python Reportability remains authoritative.",
    "Return JSON only with no Markdown, prose outside JSON, or extra fields.",
)


MAIAGENT_REPORTABILITY_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "event_id": {"type": "string"},
        "proposed_state": {
            "type": "string",
            "enum": ["REPORTABLE", "NOT_REPORTABLE"],
        },
        "examined_candidate_ids": {
            "type": "array",
            "items": {"type": "string"},
        },
        "support_citations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "candidate_id": {"type": "string"},
                    "exact_quote": {"type": "string"},
                },
                "required": ["candidate_id", "exact_quote"],
            },
        },
        "rationale": {"type": "string"},
    },
    "required": [
        "event_id",
        "proposed_state",
        "examined_candidate_ids",
        "support_citations",
        "rationale",
    ],
}

# Descriptive aliases keep one schema object discoverable for focused callers.
REPORTABILITY_RESPONSE_SCHEMA = MAIAGENT_REPORTABILITY_RESPONSE_SCHEMA
_MAIAGENT_REPORTABILITY_RESPONSE_SCHEMA = MAIAGENT_REPORTABILITY_RESPONSE_SCHEMA


@dataclass(frozen=True, slots=True)
class MaiAgentReportabilityProviderConfig:
    """Mechanical configuration for the shared Structured Helper."""

    api_base: str
    api_key: str = field(repr=False)
    chatbot_id: str = field(repr=False)
    timeout_seconds: float = 45.0

    def __post_init__(self) -> None:
        values = (self.api_base, self.api_key, self.chatbot_id)
        if any(not isinstance(value, str) for value in values):
            raise ValueError("MaiAgent Reportability configuration values must be strings")
        if any("\r" in value or "\n" in value for value in values):
            raise ValueError("MaiAgent Reportability configuration contains invalid characters")
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
    ) -> "MaiAgentReportabilityProviderConfig | None":
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


def build_maiagent_reportability_model_input(
    request: ReportabilitySemanticRequest,
) -> dict[str, Any]:
    """Build one complete, bounded, stateless task input."""

    if not isinstance(request, ReportabilitySemanticRequest):
        raise TypeError("MaiAgent Reportability input requires ReportabilitySemanticRequest")
    return {
        "task_identity": TASK_IDENTITY,
        "prompt_version": PROMPT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "helper_version": HELPER_VERSION,
        "instructions": list(REPORTABILITY_INSTRUCTIONS),
        "reportability_request": request.as_payload(),
        "authoritative_response_contract": {
            "schema_version": SCHEMA_VERSION,
            "json_schema": MAIAGENT_REPORTABILITY_RESPONSE_SCHEMA,
        },
    }


class MaiAgentReportabilityProviderFailure(RuntimeError):
    """Safe technical failure without provider-controlled details."""


class MaiAgentReportabilityProposalProvider:
    """One-call proposal adapter; Reportability remains authoritative."""

    def __init__(
        self,
        config: MaiAgentReportabilityProviderConfig,
        *,
        transport: MaiAgentJsonHttpTransport | None = None,
    ) -> None:
        if not isinstance(config, MaiAgentReportabilityProviderConfig):
            raise TypeError(
                "MaiAgentReportabilityProposalProvider requires MaiAgentReportabilityProviderConfig"
            )
        self._config = config
        self._transport = transport if transport is not None else UrllibMaiAgentJsonTransport()

    def __call__(self, request: ReportabilitySemanticRequest) -> object:
        if not isinstance(request, ReportabilitySemanticRequest):
            raise TypeError(
                "MaiAgent Reportability provider accepts only ReportabilitySemanticRequest"
            )
        request_content = json.dumps(
            build_maiagent_reportability_model_input(request),
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
            raise TimeoutError("MaiAgent Reportability request timed out") from None
        except Exception:
            raise MaiAgentReportabilityProviderFailure(
                "MaiAgent Reportability provider transport failed"
            ) from None

        if not isinstance(response, MaiAgentHttpResponse) or response.status_code != 200:
            raise MaiAgentReportabilityProviderFailure(
                "MaiAgent Reportability provider request failed"
            )
        try:
            return parse_maiagent_response(response.body)
        except MaiAgentResponseError:
            raise MaiAgentReportabilityProviderFailure(
                "MaiAgent Reportability provider response was invalid"
            ) from None


MaiAgentReportabilityProvider = MaiAgentReportabilityProposalProvider
MaiAgentReportabilityAdapter = MaiAgentReportabilityProposalProvider
MaiAgentReportabilityFailure = MaiAgentReportabilityProviderFailure


def build_maiagent_reportability_provider(
    config: MaiAgentReportabilityProviderConfig | None = None,
    *,
    transport: MaiAgentJsonHttpTransport | None = None,
    environ: Mapping[str, str] | None = None,
    timeout_seconds: float = 45.0,
    dotenv_path: str | os.PathLike[str] | None = None,
) -> MaiAgentReportabilityProposalProvider | None:
    """Construct the adapter without performing network I/O."""

    resolved = config
    if resolved is None:
        resolved = MaiAgentReportabilityProviderConfig.from_environment(
            environ,
            timeout_seconds=timeout_seconds,
            dotenv_path=dotenv_path,
        )
    if resolved is None:
        return None
    return MaiAgentReportabilityProposalProvider(resolved, transport=transport)


build_maiagent_reportability_proposal_provider = build_maiagent_reportability_provider


__all__ = [
    "HELPER_VERSION",
    "MAIAGENT_REPORTABILITY_PROVIDER_IDENTIFIER",
    "MAIAGENT_REPORTABILITY_RESPONSE_SCHEMA",
    "MaiAgentReportabilityAdapter",
    "MaiAgentReportabilityFailure",
    "MaiAgentReportabilityProposalProvider",
    "MaiAgentReportabilityProvider",
    "MaiAgentReportabilityProviderConfig",
    "MaiAgentReportabilityProviderFailure",
    "PROMPT_VERSION",
    "PROVIDER_IDENTIFIER",
    "REPORTABILITY_HELPER_VERSION",
    "REPORTABILITY_INSTRUCTIONS",
    "REPORTABILITY_PROMPT_VERSION",
    "REPORTABILITY_RESPONSE_SCHEMA",
    "REPORTABILITY_SCHEMA_VERSION",
    "REPORTABILITY_TASK_IDENTITY",
    "SCHEMA_VERSION",
    "TASK_IDENTITY",
    "build_maiagent_reportability_model_input",
    "build_maiagent_reportability_proposal_provider",
    "build_maiagent_reportability_provider",
]
