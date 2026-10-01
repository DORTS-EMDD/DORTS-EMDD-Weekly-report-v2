"""Configured Responses API adapter for the Classifier's semantic helper.

The adapter has no Category authority. It sends only CategorySemanticRequest,
returns a strict structured proposal, and records non-decision provenance.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .classifier import (
    CategorySemanticHelperResult,
    CategorySemanticRequest,
    Classifier,
    InvalidCategorySemanticResponse,
    _DOMAIN_UNRESOLVED_REASONS,
)
from .contracts import CategoryId, CategoryResolutionReason, CategoryState


CATEGORY_SEMANTIC_PROMPT_VERSION = "category-principal-action-v2"
CATEGORY_SEMANTIC_SCHEMA_VERSION = "category-proposal-v4"
CATEGORY_SEMANTIC_HELPER_VERSION = "responses-adapter-v1"
MAIAGENT_CATEGORY_SEMANTIC_HELPER_VERSION = "maiagent-chatbot-adapter-v2"
MAIAGENT_CATEGORY_PROVIDER_IDENTIFIER = "maiagent-chatbot-completions"
MAIAGENT_CATEGORY_MESSAGE_VERSION = "category-full-response-contract-v1"
_ENV_ENDPOINT = "CATEGORY_SEMANTIC_API_URL"
_ENV_MODEL = "CATEGORY_SEMANTIC_MODEL"
_ENV_API_KEY = "CATEGORY_SEMANTIC_API_KEY"
_MAIAGENT_ENV_API_BASE = "MAIAGENT_API_BASE"
_MAIAGENT_ENV_API_KEY = "MAIAGENT_API_KEY"
_MAIAGENT_ENV_CATEGORY_CHATBOT_ID = "CATEGORY_MAIAGENT_CHATBOT_ID"
_MAIAGENT_CONFIG_KEYS = (
    _MAIAGENT_ENV_API_BASE,
    _MAIAGENT_ENV_API_KEY,
    _MAIAGENT_ENV_CATEGORY_CHATBOT_ID,
)


_SYSTEM_PROMPT = """You are a constrained semantic advisor to Classifier, the sole authoritative Category decision owner.
Use only the supplied JSON input and its guidance. Do not browse, search, retrieve external information, or infer from discovery metadata. Do not prefer a source by order, publisher, canonical status, popularity, or priority. Preserve each source's claims separately. Return citations as candidate_id plus a non-empty exact quote copied from that candidate's substantive source content. Citations support the proposal as a whole; do not label citations as support or conflict and do not calculate offsets.
Return only the requested structured JSON proposal, with no surrounding prose. Classifier validates the proposal and owns the terminal decision. Do not change Event Groups or decide taxonomy or reportability."""


_CITATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "candidate_id": {"type": "string", "minLength": 1},
        "quote": {"type": "string", "minLength": 1},
    },
    "required": ["candidate_id", "quote"],
}
_CATEGORY_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "category_state": {
            "type": "string",
            "enum": [CategoryState.CATEGORY_ASSIGNED.value, CategoryState.CATEGORY_UNRESOLVED.value],
        },
        "primary_category_id": {
            "anyOf": [
                {"type": "string", "enum": [item.value for item in CategoryId]},
                {"type": "null"},
            ]
        },
        "subtype": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "category_resolution_reason": {
            "anyOf": [
                {
                    "type": "string",
                    "enum": sorted(reason.value for reason in _DOMAIN_UNRESOLVED_REASONS),
                },
                {"type": "null"},
            ]
        },
        "citations": {"type": "array", "minItems": 1, "items": _CITATION_SCHEMA},
    },
    "required": [
        "category_state",
        "primary_category_id",
        "subtype",
        "category_resolution_reason",
        "citations",
    ],
    "oneOf": [
        {
            "properties": {
                "category_state": {"const": CategoryState.CATEGORY_ASSIGNED.value},
                "primary_category_id": {
                    "type": "string",
                    "enum": [item.value for item in CategoryId],
                },
                "subtype": {
                    "anyOf": [
                        {"type": "null"},
                        # `$` may match before a final line terminator. This
                        # lookahead requires the subtype to consume the true
                        # end of the string, matching Classifier.fullmatch.
                        {
                            "type": "string",
                            "pattern": "^[a-z][a-z0-9_]{0,63}(?![\\s\\S])",
                        },
                    ]
                },
                "category_resolution_reason": {"type": "null"},
            }
        },
        {
            "properties": {
                "category_state": {"const": CategoryState.CATEGORY_UNRESOLVED.value},
                "primary_category_id": {"type": "null"},
                "subtype": {"type": "null"},
                "category_resolution_reason": {
                    "type": "string",
                    "enum": sorted(reason.value for reason in _DOMAIN_UNRESOLVED_REASONS),
                },
            },
        },
    ],
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
class CategorySemanticProviderConfig:
    endpoint: str
    model_identifier: str
    api_key: str
    timeout_seconds: float = 45.0
    provider_identifier: str = "responses-api-compatible"

    def __post_init__(self) -> None:
        parsed = urlsplit(self.endpoint)
        if not parsed.scheme or not parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("Category semantic endpoint must be an absolute URL without query or fragment")
        if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1"}:
            raise ValueError("Category semantic endpoint must use HTTPS")
        if not self.model_identifier.strip() or not self.api_key.strip():
            raise ValueError("Category semantic model and API key are required")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "CategorySemanticProviderConfig | None":
        values = os.environ if environ is None else environ
        endpoint = values.get(_ENV_ENDPOINT, "").strip()
        model = values.get(_ENV_MODEL, "").strip()
        api_key = values.get(_ENV_API_KEY, "").strip()
        if not (endpoint and model and api_key):
            return None
        return cls(endpoint=endpoint, model_identifier=model, api_key=api_key)


class JsonHttpTransport(Protocol):
    def __call__(
        self,
        endpoint: str,
        *,
        headers: Mapping[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> bytes:
        """Make one JSON HTTP request and return its response body."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str):
        return None


class UrllibJsonTransport:
    """Minimal HTTPS JSON transport. It performs one request and no retries."""

    def __call__(
        self,
        endpoint: str,
        *,
        headers: Mapping[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> bytes:
        request = Request(endpoint, data=body, headers=dict(headers), method="POST")
        opener = build_opener(_NoRedirect)
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                return response.read()
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise RuntimeError("Category semantic provider transport failed") from exc


class CategorySemanticProvider:
    """Call one configured structured-output model and return its proposal."""

    def __init__(
        self,
        config: CategorySemanticProviderConfig,
        *,
        transport: JsonHttpTransport | None = None,
    ) -> None:
        self._config = config
        self._transport = transport or UrllibJsonTransport()

    def __call__(self, request: CategorySemanticRequest) -> CategorySemanticHelperResult:
        if not isinstance(request, CategorySemanticRequest):
            raise TypeError("CategorySemanticProvider accepts only CategorySemanticRequest")
        body = json.dumps(
            {
                "model": self._config.model_identifier,
                "instructions": _SYSTEM_PROMPT,
                "input": json.dumps(request.as_payload(), ensure_ascii=False, separators=(",", ":")),
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "category_semantic_proposal",
                        "strict": True,
                        "schema": _CATEGORY_RESPONSE_SCHEMA,
                    }
                },
                "store": False,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        provenance = self._provenance()
        try:
            response_bytes = self._transport(
                self._config.endpoint,
                headers={
                    "Authorization": f"Bearer {self._config.api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                body=body,
                timeout_seconds=self._config.timeout_seconds,
            )
        except Exception as exc:
            raise CategorySemanticProviderFailure(provenance) from exc
        try:
            proposal = _parse_provider_response(response_bytes)
        except InvalidCategorySemanticResponse as exc:
            raise InvalidCategorySemanticResponse(str(exc), provenance=provenance) from exc
        return CategorySemanticHelperResult(
            proposal=proposal,
            provenance=provenance,
        )

    def _provenance(self) -> dict[str, str]:
        return {
            "provider_identifier": self._config.provider_identifier,
            "model_identifier": self._config.model_identifier,
            "prompt_version": CATEGORY_SEMANTIC_PROMPT_VERSION,
            "schema_version": CATEGORY_SEMANTIC_SCHEMA_VERSION,
            "helper_version": CATEGORY_SEMANTIC_HELPER_VERSION,
        }


class CategorySemanticProviderFailure(RuntimeError):
    """Transport/provider failure with redacted non-decision provenance."""

    def __init__(self, provenance: Mapping[str, str]) -> None:
        super().__init__("Category semantic provider request failed")
        self.provenance = dict(provenance)


def _parse_provider_response(response_bytes: bytes) -> dict[str, Any]:
    if not response_bytes:
        raise InvalidCategorySemanticResponse("provider returned an empty response")
    try:
        envelope = json.loads(response_bytes)
    except (UnicodeDecodeError, TypeError, ValueError) as exc:
        raise InvalidCategorySemanticResponse("provider response envelope is invalid JSON") from exc
    if not isinstance(envelope, Mapping):
        raise InvalidCategorySemanticResponse("provider response envelope must be an object")
    if envelope.get("status") != "completed" or envelope.get("error"):
        raise InvalidCategorySemanticResponse("provider response is not completed or contains an error")

    output = envelope.get("output")
    if not isinstance(output, list):
        raise InvalidCategorySemanticResponse("provider response has no structured output")
    text_parts: list[str] = []
    for item in output:
        if not isinstance(item, Mapping):
            continue
        for content in item.get("content", ()) if isinstance(item.get("content"), list) else ():
            if not isinstance(content, Mapping):
                continue
            if content.get("type") == "refusal":
                raise InvalidCategorySemanticResponse("provider refused the Category proposal")
            if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                text_parts.append(content["text"])
    if len(text_parts) != 1 or not text_parts[0].strip():
        raise InvalidCategorySemanticResponse("provider returned no single structured proposal")
    try:
        proposal = json.loads(text_parts[0])
    except (TypeError, ValueError) as exc:
        raise InvalidCategorySemanticResponse("provider proposal is invalid JSON") from exc
    if not isinstance(proposal, dict):
        raise InvalidCategorySemanticResponse("provider proposal must be a JSON object")
    return proposal


def build_category_classifier(
    config: CategorySemanticProviderConfig | None = None,
    *,
    transport: JsonHttpTransport | None = None,
) -> Classifier:
    """Build the reusable production Category component from explicit config.

    Missing configuration produces the existing fail-closed Classifier path.
    This is the composition seam; it intentionally does not create a pipeline.
    """

    resolved = config if config is not None else CategorySemanticProviderConfig.from_environment()
    if resolved is None:
        return Classifier()
    return Classifier(CategorySemanticProvider(resolved, transport=transport))


@dataclass(frozen=True, slots=True)
class MaiAgentCategorySemanticProviderConfig:
    """Configuration for the dedicated Category chatbot completion endpoint."""

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
        """Read Category settings from process env, then repo-root .env.

        Process values override .env values, including an explicitly empty
        process value. Only the three MaiAgent Category keys are read.
        """

        process_values = os.environ if environ is None else environ
        dotenv: Mapping[str, Any] = {}
        if not all(
            key in process_values and str(process_values[key]).strip()
            for key in _MAIAGENT_CONFIG_KEYS
        ):
            env_file = (
                Path(dotenv_path)
                if dotenv_path is not None
                else Path(__file__).resolve().parents[2] / ".env"
            )
            try:
                # python-dotenv is optional when all settings are supplied by
                # the process environment. Missing/invalid .env fails closed.
                from dotenv import dotenv_values

                dotenv = dotenv_values(env_file)
            except (ImportError, OSError, UnicodeError, ValueError):
                dotenv = {}

        merged = {key: dotenv.get(key) for key in _MAIAGENT_CONFIG_KEYS}
        for key in _MAIAGENT_CONFIG_KEYS:
            if key in process_values:
                merged[key] = process_values[key]

        api_base = merged[_MAIAGENT_ENV_API_BASE]
        api_key = merged[_MAIAGENT_ENV_API_KEY]
        chatbot_id = merged[_MAIAGENT_ENV_CATEGORY_CHATBOT_ID]
        if not all(isinstance(value, str) and value.strip() for value in (api_base, api_key, chatbot_id)):
            return None
        return cls(
            api_base=api_base.strip(),
            api_key=api_key.strip(),
            chatbot_id=chatbot_id.strip(),
        )


@dataclass(frozen=True, slots=True)
class MaiAgentHttpResponse:
    """HTTP status and body returned by one MaiAgent completion request."""

    status_code: int
    body: bytes


class MaiAgentJsonHttpTransport(Protocol):
    def __call__(
        self,
        endpoint: str,
        *,
        headers: Mapping[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> MaiAgentHttpResponse:
        """Make one request without redirects/retries and return its status/body."""


class UrllibMaiAgentJsonTransport:
    """One non-stream MaiAgent POST; redirects and retries are disabled."""

    def __call__(
        self,
        endpoint: str,
        *,
        headers: Mapping[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> MaiAgentHttpResponse:
        request = Request(endpoint, data=body, headers=dict(headers), method="POST")
        opener = build_opener(_NoRedirect)
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                return MaiAgentHttpResponse(response.status, response.read())
        except HTTPError as exc:
            # The provider needs only the status to fail closed. Do not retain
            # an error body or an exception string that could reveal the URL.
            return MaiAgentHttpResponse(exc.code, b"")
        except (URLError, TimeoutError, OSError):
            raise RuntimeError("MaiAgent Category transport failed") from None


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
        except Exception:
            raise CategorySemanticProviderFailure(provenance) from None

        if not isinstance(response, MaiAgentHttpResponse) or response.status_code != 200:
            raise CategorySemanticProviderFailure(provenance)
        try:
            proposal = _parse_maiagent_response(response.body)
        except InvalidCategorySemanticResponse as exc:
            raise InvalidCategorySemanticResponse(
                str(exc), provenance=provenance
            ) from None
        return CategorySemanticHelperResult(proposal=proposal, provenance=provenance)

    @staticmethod
    def _provenance() -> dict[str, str]:
        return {
            "provider_identifier": MAIAGENT_CATEGORY_PROVIDER_IDENTIFIER,
            "prompt_version": MAIAGENT_CATEGORY_MESSAGE_VERSION,
            "schema_version": CATEGORY_SEMANTIC_SCHEMA_VERSION,
            "helper_version": MAIAGENT_CATEGORY_SEMANTIC_HELPER_VERSION,
        }


def _parse_maiagent_response(response_body: bytes) -> dict[str, Any]:
    """Parse only outer JSON → top-level content string → proposal JSON."""

    if not isinstance(response_body, bytes) or not response_body:
        raise InvalidCategorySemanticResponse("MaiAgent response body is empty or invalid")
    try:
        envelope = json.loads(response_body)
    except (UnicodeDecodeError, TypeError, ValueError):
        raise InvalidCategorySemanticResponse("MaiAgent response envelope is invalid JSON") from None
    if not isinstance(envelope, dict):
        raise InvalidCategorySemanticResponse("MaiAgent response envelope must be an object")
    content = envelope.get("content")
    if not isinstance(content, str):
        raise InvalidCategorySemanticResponse("MaiAgent response has no top-level content string")
    try:
        proposal = json.loads(content)
    except (TypeError, ValueError):
        raise InvalidCategorySemanticResponse("MaiAgent content is invalid proposal JSON") from None
    if not isinstance(proposal, dict):
        raise InvalidCategorySemanticResponse("MaiAgent proposal must be an object")
    return proposal


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
