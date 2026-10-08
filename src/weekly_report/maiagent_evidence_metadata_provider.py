"""MaiAgent adapter for the bounded Evidence metadata proposal seam."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from typing import Any
from urllib.parse import quote, urlsplit

from .evidence_metadata import EvidenceMetadataRequest
from .maiagent_transport import (
    MaiAgentHttpResponse,
    MaiAgentJsonHttpTransport,
    MaiAgentResponseError,
    UrllibMaiAgentJsonTransport,
    load_shared_maiagent_values,
    parse_maiagent_response,
)


EVIDENCE_METADATA_PROMPT_VERSION = "evidence-metadata-principal-body-v2"
EVIDENCE_METADATA_SCHEMA_VERSION = "evidence-metadata-proposal-v2"
EVIDENCE_METADATA_HELPER_VERSION = "maiagent-structured-helper-adapter-v2"
MAIAGENT_EVIDENCE_METADATA_PROVIDER_IDENTIFIER = "maiagent-structured-helper-metadata"


MAIAGENT_EVIDENCE_METADATA_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "observations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "field_name": {
                        "type": "string",
                        "enum": ["country", "transit_system_name", "location"],
                    },
                    "value": {"type": "string", "minLength": 1},
                    "segment_id": {"type": "string"},
                },
                "required": ["field_name", "value", "segment_id"],
            },
        },
    },
    "required": ["observations"],
}

# Keep the private spelling available for focused tests and mechanical callers.
_MAIAGENT_EVIDENCE_METADATA_RESPONSE_SCHEMA = MAIAGENT_EVIDENCE_METADATA_RESPONSE_SCHEMA


EVIDENCE_METADATA_INSTRUCTIONS = (
    "You are a stateless proposal-only Evidence metadata helper.",
    "Use only the supplied principal_body_segments in the current request.",
    "Return exact nonblank source-surface strings only; do not translate or normalize aliases.",
    "The only governed fields are country, transit_system_name, and location.",
    "Do not infer geography, country from a city, or a transit system from an operator or outside knowledge.",
    "Do not search, browse, use RAG, use tools, retrieve external knowledge, or supplement the supplied source.",
    "For every observation, return the segment_id containing the exact source-surface value.",
    "Do not return start, end, support_spans, offsets, or any other coordinate fields; Python derives canonical spans.",
    "Do not calculate, repair, normalize, or guess character offsets.",
    "Do not retry, fall back, rescue, or repair a missing, ambiguous, or malformed observation.",
    "Return only the requested JSON object. Do not return prose, Markdown, explanations, or extra fields.",
)


@dataclass(frozen=True, slots=True)
class MaiAgentEvidenceMetadataProviderConfig:
    """Shared MaiAgent completion configuration for the metadata adapter."""

    api_base: str
    api_key: str
    chatbot_id: str
    timeout_seconds: float = 45.0

    def __post_init__(self) -> None:
        try:
            parsed = urlsplit(self.api_base)
            hostname = parsed.hostname
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
        if not all(
            isinstance(value, str) and value.strip()
            for value in (self.api_key, self.chatbot_id)
        ):
            raise ValueError("MaiAgent API key and structured helper chatbot ID are required")
        if any(char in self.api_key + self.chatbot_id for char in "\r\n"):
            raise ValueError("MaiAgent configuration contains invalid characters")
        if self.timeout_seconds <= 0:
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
        dotenv_path: str | None = None,
    ) -> "MaiAgentEvidenceMetadataProviderConfig | None":
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
        )


def build_maiagent_evidence_metadata_model_input(
    request: EvidenceMetadataRequest,
) -> dict[str, Any]:
    """Build the complete per-call task contract from the bounded request."""

    if not isinstance(request, EvidenceMetadataRequest):
        raise TypeError("MaiAgent metadata input requires EvidenceMetadataRequest")
    return {
        "task_identity": "evidence_metadata_extraction",
        "prompt_version": EVIDENCE_METADATA_PROMPT_VERSION,
        "schema_version": EVIDENCE_METADATA_SCHEMA_VERSION,
        "helper_version": EVIDENCE_METADATA_HELPER_VERSION,
        "instructions": list(EVIDENCE_METADATA_INSTRUCTIONS),
        "evidence_metadata_request": {
            "candidate_id": request.candidate_id,
            "principal_body_segments": [
                {"segment_id": segment.segment_id, "text": segment.text}
                for segment in request.principal_body_segments
            ],
        },
        "authoritative_response_contract": {
            "schema_version": EVIDENCE_METADATA_SCHEMA_VERSION,
            "json_schema": MAIAGENT_EVIDENCE_METADATA_RESPONSE_SCHEMA,
        },
    }


class MaiAgentEvidenceMetadataExtractor:
    """Proposal-only adapter; EvidenceService owns validation and authority."""

    def __init__(
        self,
        config: MaiAgentEvidenceMetadataProviderConfig,
        *,
        transport: MaiAgentJsonHttpTransport | None = None,
    ) -> None:
        self._config = config
        self._transport = transport or UrllibMaiAgentJsonTransport()

    def __call__(self, request: EvidenceMetadataRequest) -> object:
        if not isinstance(request, EvidenceMetadataRequest):
            raise TypeError("MaiAgentEvidenceMetadataExtractor accepts only EvidenceMetadataRequest")
        request_content = json.dumps(
            build_maiagent_evidence_metadata_model_input(request),
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
                timeout_seconds=self._config.timeout_seconds,
            )
        except TimeoutError:
            raise
        except Exception:
            raise RuntimeError("MaiAgent metadata provider transport failed") from None

        if not isinstance(response, MaiAgentHttpResponse) or response.status_code != 200:
            raise RuntimeError("MaiAgent metadata provider request failed")
        try:
            return parse_maiagent_response(response.body)
        except MaiAgentResponseError:
            # Return an invalid raw object so EvidenceService records its
            # existing invalid_response diagnostic and performs no salvage.
            return None


def build_maiagent_evidence_metadata_extractor(
    config: MaiAgentEvidenceMetadataProviderConfig | None = None,
    *,
    transport: MaiAgentJsonHttpTransport | None = None,
    environ: Mapping[str, str] | None = None,
    dotenv_path: str | None = None,
) -> MaiAgentEvidenceMetadataExtractor | None:
    """Build the metadata extractor, failing closed when shared config is absent."""

    resolved = config or MaiAgentEvidenceMetadataProviderConfig.from_environment(
        environ,
        dotenv_path=dotenv_path,
    )
    if resolved is None:
        return None
    return MaiAgentEvidenceMetadataExtractor(resolved, transport=transport)


__all__ = [
    "EVIDENCE_METADATA_HELPER_VERSION",
    "EVIDENCE_METADATA_INSTRUCTIONS",
    "EVIDENCE_METADATA_PROMPT_VERSION",
    "EVIDENCE_METADATA_SCHEMA_VERSION",
    "MAIAGENT_EVIDENCE_METADATA_PROVIDER_IDENTIFIER",
    "MAIAGENT_EVIDENCE_METADATA_RESPONSE_SCHEMA",
    "MaiAgentEvidenceMetadataProviderConfig",
    "MaiAgentEvidenceMetadataExtractor",
    "build_maiagent_evidence_metadata_model_input",
    "build_maiagent_evidence_metadata_extractor",
]
