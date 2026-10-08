"""MaiAgent adapter for the bounded Evidence semantic-judge seam.

The adapter is deliberately proposal-only.  It transports one complete,
stateless task to the already configured Structured Helper and returns the raw
proposal.  ``EvidenceService`` remains responsible for validation and for the
authoritative Evidence decision.
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
from .semantic_judge import JudgeMetadata, SemanticJudgeInput


TASK_IDENTITY = "evidence_source_candidate_match"
PROMPT_VERSION = "evidence-source-candidate-match-v1"
SCHEMA_VERSION = "evidence-semantic-judge-response-v1"
HELPER_VERSION = "maiagent-structured-helper-semantic-judge-adapter-v1"
PROVIDER_IDENTIFIER = "maiagent-structured-helper-evidence-semantic-judge"

# Explicit aliases make the task-level provenance names easy to discover while
# keeping one finite version value as the source of truth.
EVIDENCE_SEMANTIC_JUDGE_TASK_IDENTITY = TASK_IDENTITY
EVIDENCE_SEMANTIC_JUDGE_PROMPT_VERSION = PROMPT_VERSION
EVIDENCE_SEMANTIC_JUDGE_SCHEMA_VERSION = SCHEMA_VERSION
EVIDENCE_SEMANTIC_JUDGE_HELPER_VERSION = HELPER_VERSION
MAIAGENT_EVIDENCE_SEMANTIC_JUDGE_PROVIDER_IDENTIFIER = PROVIDER_IDENTIFIER


MAIAGENT_SEMANTIC_JUDGE_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "relation": {
            "type": "string",
            "enum": ["SAME_EVENT", "DIFFERENT_EVENT", "UNCERTAIN"],
        },
        "support_spans": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "segment_id": {"type": "string"},
                    "start": {"type": "integer"},
                    "end": {"type": "integer"},
                },
                "required": ["segment_id", "start", "end"],
            },
        },
        "conflict_spans": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "segment_id": {"type": "string"},
                    "start": {"type": "integer"},
                    "end": {"type": "integer"},
                },
                "required": ["segment_id", "start", "end"],
            },
        },
        "explanation": {"type": "string"},
    },
    "required": ["relation", "support_spans", "conflict_spans", "explanation"],
}

# Keep the private spelling available for focused tests and mechanical callers.
_MAIAGENT_SEMANTIC_JUDGE_RESPONSE_SCHEMA = MAIAGENT_SEMANTIC_JUDGE_RESPONSE_SCHEMA
MAIAGENT_EVIDENCE_SEMANTIC_JUDGE_RESPONSE_SCHEMA = MAIAGENT_SEMANTIC_JUDGE_RESPONSE_SCHEMA
_MAIAGENT_EVIDENCE_SEMANTIC_JUDGE_RESPONSE_SCHEMA = MAIAGENT_SEMANTIC_JUDGE_RESPONSE_SCHEMA


SEMANTIC_JUDGE_INSTRUCTIONS = (
    "Use only the current request; do not use persistent memory or any prior conversation.",
    "Compare the Candidate discovery context against the authoritative principal body supplied in this request.",
    "candidate_title and document_level_headlines are comparison context only.",
    "Authoritative semantic support and conflict evidence must come from principal_body_segments.",
    "support_spans and conflict_spans may reference only principal_body_segments and must use exact segment-relative Python Unicode half-open [start, end) offsets.",
    "Do not treat title or headline text as authoritative factual support.",
    "Return SAME_EVENT only when the supplied principal body substantively establishes the same event as the Candidate context.",
    "Return DIFFERENT_EVENT when the supplied principal body substantively establishes a different event.",
    "Return UNCERTAIN when the supplied principal body is insufficient to establish sameness or difference.",
    "Use no external knowledge and do not infer from publisher, domain, URL, geography, language, or any other unsupplied fact.",
    "Do not browse, search, use RAG, use tools, or retrieve external information.",
    "Do not decide Evidence READY or REJECTED; EvidenceService remains the authoritative decision owner.",
    "Return JSON only, with no Markdown, no prose outside JSON, and no extra fields.",
)
EVIDENCE_SEMANTIC_JUDGE_INSTRUCTIONS = SEMANTIC_JUDGE_INSTRUCTIONS


@dataclass(frozen=True, slots=True)
class MaiAgentSemanticJudgeConfig:
    """Mechanical configuration for the shared MaiAgent helper deployment."""

    api_base: str
    api_key: str = field(repr=False)
    chatbot_id: str = field(repr=False)
    model_identifier: str
    timeout_seconds: float = 45.0
    provider_identifier: str = PROVIDER_IDENTIFIER

    def __post_init__(self) -> None:
        values = {
            "api_base": self.api_base,
            "api_key": self.api_key,
            "chatbot_id": self.chatbot_id,
            "model_identifier": self.model_identifier,
            "provider_identifier": self.provider_identifier,
        }
        if any(not isinstance(value, str) for value in values.values()):
            raise ValueError("MaiAgent semantic judge configuration values must be strings")
        if any("\r" in value or "\n" in value for value in values.values()):
            raise ValueError("MaiAgent semantic judge configuration contains invalid characters")
        try:
            parsed = urlsplit(self.api_base)
            hostname = parsed.hostname
            parsed.port  # Force malformed port values to fail closed.
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
        if not self.model_identifier.strip():
            raise ValueError("model_identifier is required")
        if not self.provider_identifier.strip():
            raise ValueError("provider_identifier is required")
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
        model_identifier: str | None = None,
        timeout_seconds: float = 45.0,
        provider_identifier: str = PROVIDER_IDENTIFIER,
        dotenv_path: str | os.PathLike[str] | None = None,
    ) -> "MaiAgentSemanticJudgeConfig | None":
        """Load only the canonical shared helper values.

        The model identifier is intentionally an explicit construction input:
        this adapter never discovers a model and never invents an environment
        variable for one.
        """

        values = load_shared_maiagent_values(environ, dotenv_path=dotenv_path)
        api_base = values.get("MAIAGENT_API_BASE")
        api_key = values.get("MAIAGENT_API_KEY")
        chatbot_id = values.get("MAIAGENT_STRUCTURED_HELPER_CHATBOT_ID")
        if not all(
            isinstance(value, str) and value.strip()
            for value in (api_base, api_key, chatbot_id, model_identifier)
        ):
            return None
        return cls(
            api_base=api_base.strip(),
            api_key=api_key.strip(),
            chatbot_id=chatbot_id.strip(),
            model_identifier=model_identifier.strip(),
            timeout_seconds=timeout_seconds,
            provider_identifier=provider_identifier,
        )


# A descriptive compatibility alias for callers that name configs by provider.
MaiAgentSemanticJudgeProviderConfig = MaiAgentSemanticJudgeConfig


def build_maiagent_semantic_judge_model_input(
    request: SemanticJudgeInput,
) -> dict[str, Any]:
    """Build one complete, self-contained task for the Structured Helper."""

    if not isinstance(request, SemanticJudgeInput):
        raise TypeError("MaiAgent semantic judge input requires SemanticJudgeInput")
    return {
        "task_identity": TASK_IDENTITY,
        "prompt_version": PROMPT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "helper_version": HELPER_VERSION,
        "instructions": list(SEMANTIC_JUDGE_INSTRUCTIONS),
        "semantic_judge_request": request.as_payload(),
        "authoritative_response_contract": {
            "schema_version": SCHEMA_VERSION,
            "json_schema": MAIAGENT_SEMANTIC_JUDGE_RESPONSE_SCHEMA,
        },
    }


class MaiAgentSemanticJudgeProviderFailure(RuntimeError):
    """Safe provider failure without endpoint, body, or credential details."""


class MaiAgentSemanticJudgeProvider:
    """One-call proposal adapter; EvidenceService owns validation and authority."""

    def __init__(
        self,
        config: MaiAgentSemanticJudgeConfig,
        *,
        transport: MaiAgentJsonHttpTransport | None = None,
    ) -> None:
        if not isinstance(config, MaiAgentSemanticJudgeConfig):
            raise TypeError("MaiAgentSemanticJudgeProvider requires MaiAgentSemanticJudgeConfig")
        self._config = config
        self._transport = transport if transport is not None else UrllibMaiAgentJsonTransport()

    @property
    def metadata(self) -> JudgeMetadata:
        """Provenance consumed by EvidenceService's existing trace seam."""

        return JudgeMetadata(
            model_identifier=self._config.model_identifier,
            prompt_version=PROMPT_VERSION,
            schema_version=SCHEMA_VERSION,
        )

    @property
    def judge_metadata(self) -> JudgeMetadata:
        """Explicit alias for callers that name the provenance value directly."""

        return self.metadata

    def __call__(self, request: SemanticJudgeInput) -> object:
        if not isinstance(request, SemanticJudgeInput):
            raise TypeError("MaiAgentSemanticJudgeProvider accepts only SemanticJudgeInput")
        request_content = json.dumps(
            build_maiagent_semantic_judge_model_input(request),
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
            raise TimeoutError("MaiAgent semantic judge request timed out") from None
        except Exception:
            raise MaiAgentSemanticJudgeProviderFailure(
                "MaiAgent semantic judge transport failed"
            ) from None

        if not isinstance(response, MaiAgentHttpResponse) or response.status_code != 200:
            raise MaiAgentSemanticJudgeProviderFailure(
                "MaiAgent semantic judge request failed"
            )
        try:
            return parse_maiagent_response(response.body)
        except MaiAgentResponseError:
            # EvidenceService's existing validator owns the invalid-response
            # diagnostic.  No repair or correction request is permitted here.
            return None


# The shorter name reads naturally at the SemanticJudge injection seam.
MaiAgentSemanticJudge = MaiAgentSemanticJudgeProvider
MaiAgentSemanticJudgeAdapter = MaiAgentSemanticJudgeProvider
MaiAgentSemanticJudgeFailure = MaiAgentSemanticJudgeProviderFailure


def build_maiagent_semantic_judge(
    config: MaiAgentSemanticJudgeConfig | None = None,
    *,
    model_identifier: str | None = None,
    transport: MaiAgentJsonHttpTransport | None = None,
    environ: Mapping[str, str] | None = None,
    timeout_seconds: float = 45.0,
    provider_identifier: str = PROVIDER_IDENTIFIER,
    dotenv_path: str | os.PathLike[str] | None = None,
) -> MaiAgentSemanticJudgeProvider | None:
    """Construct the adapter without performing any network operation."""

    resolved = config
    if resolved is None:
        resolved = MaiAgentSemanticJudgeConfig.from_environment(
            environ,
            model_identifier=model_identifier,
            timeout_seconds=timeout_seconds,
            provider_identifier=provider_identifier,
            dotenv_path=dotenv_path,
        )
    if resolved is None:
        return None
    return MaiAgentSemanticJudgeProvider(resolved, transport=transport)


build_maiagent_semantic_judge_provider = build_maiagent_semantic_judge


__all__ = [
    "EVIDENCE_SEMANTIC_JUDGE_HELPER_VERSION",
    "EVIDENCE_SEMANTIC_JUDGE_INSTRUCTIONS",
    "EVIDENCE_SEMANTIC_JUDGE_PROMPT_VERSION",
    "EVIDENCE_SEMANTIC_JUDGE_SCHEMA_VERSION",
    "EVIDENCE_SEMANTIC_JUDGE_TASK_IDENTITY",
    "HELPER_VERSION",
    "MAIAGENT_EVIDENCE_SEMANTIC_JUDGE_PROVIDER_IDENTIFIER",
    "MAIAGENT_EVIDENCE_SEMANTIC_JUDGE_RESPONSE_SCHEMA",
    "MAIAGENT_SEMANTIC_JUDGE_RESPONSE_SCHEMA",
    "MaiAgentSemanticJudge",
    "MaiAgentSemanticJudgeAdapter",
    "MaiAgentSemanticJudgeConfig",
    "MaiAgentSemanticJudgeProvider",
    "MaiAgentSemanticJudgeProviderConfig",
    "MaiAgentSemanticJudgeProviderFailure",
    "MaiAgentSemanticJudgeFailure",
    "PROMPT_VERSION",
    "PROVIDER_IDENTIFIER",
    "SCHEMA_VERSION",
    "SEMANTIC_JUDGE_INSTRUCTIONS",
    "TASK_IDENTITY",
    "build_maiagent_semantic_judge",
    "build_maiagent_semantic_judge_model_input",
    "build_maiagent_semantic_judge_provider",
]
