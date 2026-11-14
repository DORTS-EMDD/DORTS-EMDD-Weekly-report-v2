"""MaiAgent Structured Helper adapter for the Classifier's Category proposal.

The adapter has no Category authority. It sends only CategorySemanticRequest,
returns strict cited action/lifecycle observations and evidence-grounded
relationships, and records non-decision
provenance. The Classifier owns the Category mapping and terminal result.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import os
from typing import Any
from urllib.parse import quote, urlsplit

from .classifier import (
    CategorySemanticHelperResult,
    CategorySemanticRequest,
    _CATEGORY_ACTION_KINDS,
    _CATEGORY_ADOPTION_STATUSES,
    _CATEGORY_LIFECYCLE_RELATIONS,
    _CATEGORY_DEPENDENCE_KINDS,
    _CATEGORY_RELATIONSHIP_TYPES,
    _CATEGORY_SUBJECT_KINDS,
    Classifier,
    InvalidCategorySemanticResponse,
)
from .maiagent_transport import (
    MaiAgentHttpResponse,
    MaiAgentJsonHttpTransport,
    MaiAgentResponseError,
    UrllibMaiAgentJsonTransport,
    load_shared_maiagent_values,
    parse_maiagent_response,
    MAIAGENT_HELPER_TIMEOUT_SECONDS,
    request_maiagent_proposal,
)


CATEGORY_SEMANTIC_PROMPT_VERSION = "category-principal-action-relationship-v8"
CATEGORY_SEMANTIC_SCHEMA_VERSION = "category-action-lifecycle-relationship-proposal-v1"
MAIAGENT_CATEGORY_SEMANTIC_HELPER_VERSION = "maiagent-chatbot-adapter-v4"
MAIAGENT_CATEGORY_PROVIDER_IDENTIFIER = "maiagent-chatbot-completions"
MAIAGENT_CATEGORY_MESSAGE_VERSION = "category-action-lifecycle-relationship-response-contract-v1"
_MAIAGENT_ENV_API_BASE = "MAIAGENT_API_BASE"
_MAIAGENT_ENV_API_KEY = "MAIAGENT_API_KEY"
_MAIAGENT_ENV_STRUCTURED_HELPER_CHATBOT_ID = "MAIAGENT_STRUCTURED_HELPER_CHATBOT_ID"
_MAIAGENT_CONFIG_KEYS = (
    _MAIAGENT_ENV_API_BASE,
    _MAIAGENT_ENV_API_KEY,
    _MAIAGENT_ENV_STRUCTURED_HELPER_CHATBOT_ID,
)


_CITATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "source_ref": {"type": "string", "minLength": 1},
        "sentence_ids": {"type": "array", "minItems": 1, "items": {"type": "string"}},
    },
    "required": ["source_ref", "sentence_ids"],
}
_ACTION_PROPOSAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "action_id": {"type": "string", "minLength": 1},
        "action_kind": {"type": "string", "enum": list(_CATEGORY_ACTION_KINDS)},
        "subject_kind": {"type": "string", "enum": list(_CATEGORY_SUBJECT_KINDS)},
        "lifecycle_relation": {"type": "string", "enum": list(_CATEGORY_LIFECYCLE_RELATIONS)},
        "adoption_status": {"type": "string", "enum": list(_CATEGORY_ADOPTION_STATUSES)},
        "citations": {"type": "array", "minItems": 1, "items": _CITATION_SCHEMA},
    },
    "required": ["action_id", "action_kind", "subject_kind", "lifecycle_relation", "adoption_status", "citations"],
}
_RELATIONSHIP_PROPOSAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "relationship_type": {"type": "string", "enum": list(_CATEGORY_RELATIONSHIP_TYPES)},
        "member_action_ids": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
        },
        "principal_action_id": {"anyOf": [{"type": "string", "minLength": 1}, {"type": "null"}]},
        "dependent_action_id": {"anyOf": [{"type": "string", "minLength": 1}, {"type": "null"}]},
        "dependence_kind": {
            "anyOf": [
                {"type": "string", "enum": list(_CATEGORY_DEPENDENCE_KINDS)},
                {"type": "null"},
            ]
        },
        "citations": {"type": "array", "minItems": 1, "items": _CITATION_SCHEMA},
    },
    "required": [
        "relationship_type",
        "member_action_ids",
        "principal_action_id",
        "dependent_action_id",
        "dependence_kind",
        "citations",
    ],
}
_CATEGORY_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "actions": {"type": "array", "items": _ACTION_PROPOSAL_SCHEMA},
        "principal_action_id": {"anyOf": [{"type": "string", "minLength": 1}, {"type": "null"}]},
        "subtype": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "examined_citations": {"type": "array", "minItems": 1, "items": _CITATION_SCHEMA},
        "relationships": {"type": "array", "items": _RELATIONSHIP_PROPOSAL_SCHEMA},
    },
    "required": ["actions", "principal_action_id", "subtype", "examined_citations", "relationships"],
}


_MAIAGENT_UNSUPPORTED_SCHEMA_KEYWORDS = frozenset(
    {
        "oneOf",
        "allOf",
        "if",
        "then",
        "else",
        "const",
        "minItems",
        "maxItems",
        "minLength",
        "pattern",
        "minimum",
    }
)


def build_maiagent_category_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
    """Project the authoritative schema to MaiAgent's supported keyword set.

    This projection retains provider-expressible JSON shape only. Classifier
    remains responsible for all state, reason, citation, and source-bound rules
    omitted by the provider's Structured Outputs implementation.
    """

    if not isinstance(schema, Mapping):
        raise TypeError("Category response schema must be a mapping")

    def project(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {
                key: project(child)
                for key, child in value.items()
                if key not in _MAIAGENT_UNSUPPORTED_SCHEMA_KEYWORDS
            }
        if isinstance(value, list):
            return [project(item) for item in value]
        return value

    projected = project(schema)
    if not isinstance(projected, dict):
        raise TypeError("Projected Category response schema must be an object")
    return projected


_MAIAGENT_CATEGORY_RESPONSE_SCHEMA = build_maiagent_category_schema(
    _CATEGORY_RESPONSE_SCHEMA
)


def build_maiagent_category_model_input(
    request: CategorySemanticRequest,
) -> dict[str, Any]:
    """Build the model input from the bounded request and authoritative schema."""

    if not isinstance(request, CategorySemanticRequest):
        raise TypeError("MaiAgent model input requires CategorySemanticRequest")
    return {
        "category_request": request.as_payload(),
        "authoritative_response_contract": {
            "schema_version": CATEGORY_SEMANTIC_SCHEMA_VERSION,
            "json_schema": _CATEGORY_RESPONSE_SCHEMA,
        },
    }


@dataclass(frozen=True, slots=True)
class MaiAgentCategorySemanticProviderConfig:
    """Configuration for the shared stateless Structured Helper endpoint."""

    api_base: str
    api_key: str
    chatbot_id: str
    timeout_seconds: float = MAIAGENT_HELPER_TIMEOUT_SECONDS

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
        if not self.api_key.strip() or not self.chatbot_id.strip():
            raise ValueError("MaiAgent Category API key and chatbot ID are required")
        if any(char in self.api_key + self.chatbot_id for char in "\r\n"):
            raise ValueError("MaiAgent Category configuration contains invalid characters")
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
        dotenv_path: str | os.PathLike[str] | None = None,
    ) -> "MaiAgentCategorySemanticProviderConfig | None":
        """Read shared helper settings with process-environment precedence."""

        merged = load_shared_maiagent_values(environ, dotenv_path=dotenv_path)

        api_base = merged[_MAIAGENT_ENV_API_BASE]
        api_key = merged[_MAIAGENT_ENV_API_KEY]
        chatbot_id = merged[_MAIAGENT_ENV_STRUCTURED_HELPER_CHATBOT_ID]
        if not all(isinstance(value, str) and value.strip() for value in (api_base, api_key, chatbot_id)):
            return None
        return cls(
            api_base=api_base.strip(),
            api_key=api_key.strip(),
            chatbot_id=chatbot_id.strip(),
        )


class MaiAgentCategorySemanticProvider:
    """Thin adapter from MaiAgent's confirmed envelope to Classifier input."""

    def __init__(
        self,
        config: MaiAgentCategorySemanticProviderConfig,
        *,
        transport: MaiAgentJsonHttpTransport | None = None,
    ) -> None:
        self._config = config
        self._transport = transport or UrllibMaiAgentJsonTransport()

    def __call__(self, request: CategorySemanticRequest) -> CategorySemanticHelperResult:
        if not isinstance(request, CategorySemanticRequest):
            raise TypeError("MaiAgentCategorySemanticProvider accepts only CategorySemanticRequest")

        request_content = json.dumps(
            build_maiagent_category_model_input(request),
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
        provenance = self._provenance()
        # Technical failures propagate as typed SemanticProviderTechnicalFailure
        # after the shared bounded retry; the Classifier validates the proposal.
        proposal = request_maiagent_proposal(
            self._transport,
            self._config.completion_endpoint,
            headers={
                "Authorization": f"Api-Key {self._config.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            body=body,
            timeout_seconds=self._config.timeout_seconds,
            task="category_semantic_proposal",
        )
        return CategorySemanticHelperResult(proposal=proposal, provenance=provenance)

    @staticmethod
    def _provenance() -> dict[str, str]:
        return {
            "provider_identifier": MAIAGENT_CATEGORY_PROVIDER_IDENTIFIER,
            "prompt_version": CATEGORY_SEMANTIC_PROMPT_VERSION,
            "schema_version": CATEGORY_SEMANTIC_SCHEMA_VERSION,
            "helper_version": MAIAGENT_CATEGORY_SEMANTIC_HELPER_VERSION,
        }


def _parse_maiagent_response(response_body: bytes) -> dict[str, Any]:
    try:
        return parse_maiagent_response(response_body)
    except MaiAgentResponseError as exc:
        raise InvalidCategorySemanticResponse(str(exc)) from None


def build_maiagent_category_classifier(
    config: MaiAgentCategorySemanticProviderConfig | None = None,
    *,
    transport: MaiAgentJsonHttpTransport | None = None,
    environ: Mapping[str, str] | None = None,
    dotenv_path: str | os.PathLike[str] | None = None,
) -> Classifier:
    """Build a Category-only MaiAgent classifier; missing config fails closed."""

    resolved = config if config is not None else MaiAgentCategorySemanticProviderConfig.from_environment(
        environ,
        dotenv_path=dotenv_path,
    )
    if resolved is None:
        return Classifier()
    return Classifier(MaiAgentCategorySemanticProvider(resolved, transport=transport))
