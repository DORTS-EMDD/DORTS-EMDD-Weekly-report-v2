"""The sole formal-report Writer owner.

The Writer is deliberately small: it serialises one already ordered event at a
time, makes one isolated provider request, and accepts only the four prose
fields that the model owns.  All report metadata remains a Python projection
owned by :mod:`report_service`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import json
import math
import os
from pathlib import Path
import re
from typing import Any, Protocol
from urllib.parse import quote, urlsplit

from .maiagent_transport import (
    MaiAgentHttpResponse,
    MaiAgentJsonHttpTransport,
    MaiAgentResponseError,
    UrllibMaiAgentJsonTransport,
    parse_maiagent_response,
)
from .report_workflow import ReportWorkflowResult


WRITER_CHATBOT_ENVIRONMENT_KEY = "MAIAGENT_CHATBOT_ID"
STRUCTURED_HELPER_CHATBOT_ENVIRONMENT_KEY = "MAIAGENT_STRUCTURED_HELPER_CHATBOT_ID"
WRITER_RESPONSE_FIELDS = ("event_id", "headline", "factual_summary", "taipei_insight")


@dataclass(frozen=True, slots=True)
class WriterReportBlock:
    """The only model-authored values permitted past the Writer boundary."""

    event_id: str
    headline: str
    factual_summary: str
    taipei_insight: str

    def __post_init__(self) -> None:
        if not isinstance(self.event_id, str) or not self.event_id.strip():
            raise ValueError("WriterReportBlock requires event_id")
        for field_name in ("headline", "factual_summary", "taipei_insight"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"WriterReportBlock requires nonblank {field_name}")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "WriterReportBlock":
        if not isinstance(value, Mapping):
            raise TypeError("Writer response must be an object")
        if set(value) != set(WRITER_RESPONSE_FIELDS):
            raise ValueError("Writer response fields do not match the exact schema")
        return cls(*(value[field] for field in WRITER_RESPONSE_FIELDS))


class WriterFailure(RuntimeError):
    """A nonzero Writer population failed closed."""


class WriterProviderFailure(WriterFailure):
    """A single isolated provider call failed."""


class WriterResponseError(WriterFailure):
    """A provider response did not satisfy the exact Writer schema."""


class WriterPopulationError(WriterFailure):
    """The Writer could not produce a complete ordered population."""


class WriterProvider(Protocol):
    def __call__(self, request: Mapping[str, Any]) -> object:
        """Return one untrusted response object for one event."""


def _load_writer_values(
    environ: Mapping[str, str] | None = None,
    *,
    dotenv_path: str | os.PathLike[str] | None = None,
) -> dict[str, str | None]:
    """Read Writer setting names without ever exposing credential contents."""

    process = os.environ if environ is None else environ
    keys = (
        "MAIAGENT_API_BASE",
        "MAIAGENT_API_KEY",
        WRITER_CHATBOT_ENVIRONMENT_KEY,
        STRUCTURED_HELPER_CHATBOT_ENVIRONMENT_KEY,
    )
    values: dict[str, str | None] = {key: None for key in keys}
    env_file = Path(dotenv_path) if dotenv_path is not None else Path(__file__).resolve().parents[2] / ".env"
    dotenv_values: dict[str, str] = {}
    if env_file.is_file():
        try:
            for line in env_file.read_text(encoding="utf-8").splitlines():
                match = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$", line)
                if match:
                    raw = match.group(2)
                    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {"'", '"'}:
                        raw = raw[1:-1]
                    dotenv_values[match.group(1)] = raw
        except (OSError, UnicodeError):
            dotenv_values = {}
    for key in keys:
        if key in process:
            values[key] = str(process[key])
        elif key in dotenv_values:
            values[key] = dotenv_values[key]
    return values


@dataclass(frozen=True, slots=True)
class MaiAgentWriterProviderConfig:
    """Mechanical configuration for the distinct MaiAgent Writer chatbot."""

    api_base: str
    api_key: str = field(repr=False)
    chatbot_id: str = field(repr=False)
    timeout_seconds: float = 45.0

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) for value in (self.api_base, self.api_key, self.chatbot_id)):
            raise ValueError("MaiAgent Writer configuration values must be strings")
        if any("\r" in value or "\n" in value for value in (self.api_base, self.api_key, self.chatbot_id)):
            raise ValueError("MaiAgent Writer configuration contains invalid characters")
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
        if not self.api_key.strip() or not self.chatbot_id.strip():
            raise ValueError("MaiAgent Writer API key and chatbot ID are required")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(float(self.timeout_seconds))
            or self.timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be positive")

    @property
    def completion_endpoint(self) -> str:
        return f"{self.api_base.rstrip('/')}/api/v1/chatbots/{quote(self.chatbot_id, safe='')}/completions/"

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        timeout_seconds: float = 45.0,
        dotenv_path: str | os.PathLike[str] | None = None,
    ) -> "MaiAgentWriterProviderConfig | None":
        values = _load_writer_values(environ, dotenv_path=dotenv_path)
        api_base, api_key, chatbot_id = (
            values.get("MAIAGENT_API_BASE"),
            values.get("MAIAGENT_API_KEY"),
            values.get(WRITER_CHATBOT_ENVIRONMENT_KEY),
        )
        if not all(isinstance(value, str) and value.strip() for value in (api_base, api_key, chatbot_id)):
            return None
        helper_id = values.get(STRUCTURED_HELPER_CHATBOT_ENVIRONMENT_KEY)
        if isinstance(helper_id, str) and helper_id.strip() == chatbot_id.strip():
            raise ValueError("Writer chatbot ID must differ from Structured Helper chatbot ID")
        return cls(api_base.strip(), api_key.strip(), chatbot_id.strip(), timeout_seconds)


WRITER_INSTRUCTIONS = (
    "You are the formal weekly-report Writer. Use only authoritative evidence supplied in this request.",
    "Return Traditional Chinese formal prose grounded in the supplied evidence.",
    "Write only headline, factual_summary, and taipei_insight.",
    "Do not search, browse, use tools, RAG, outside knowledge, or metadata.",
    "Do not infer or author date, country, transit system, location, category, taxonomy, source, or URL.",
    "Taipei insight may give professional implications but must not assert unsupplied Taipei Metro facts.",
    "Return JSON only with exactly event_id, headline, factual_summary, taipei_insight.",
)


def build_maiagent_writer_model_input(result: ReportWorkflowResult) -> dict[str, Any]:
    """Build one bounded event request from the canonical evidence member."""

    if not isinstance(result, ReportWorkflowResult):
        raise TypeError("Writer input requires ReportWorkflowResult values")
    canonical_id = result.event_group.canonical_candidate_id
    records = tuple(
        record for record in result.member_records
        if record.candidate.candidate_id == canonical_id
    )
    if len(records) != 1:
        raise ValueError("Writer requires exactly one canonical member")
    evidence = records[0].evidence
    content = evidence.substantive_content
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Writer requires authoritative substantive content")
    return {
        "task_identity": "formal_report_writer",
        "prompt_version": "formal-report-writer-v1",
        "schema_version": "writer-report-block-v1",
        "instructions": list(WRITER_INSTRUCTIONS),
        "writer_request": {
            "event_id": result.event_group.event_id,
            "authoritative_evidence": {"substantive_content": content},
        },
        "authoritative_response_contract": {"fields": list(WRITER_RESPONSE_FIELDS)},
    }


class MaiAgentWriterProvider:
    """One non-streaming Writer request; no retries or response repair."""

    def __init__(
        self,
        config: MaiAgentWriterProviderConfig,
        *,
        transport: MaiAgentJsonHttpTransport | None = None,
    ) -> None:
        if not isinstance(config, MaiAgentWriterProviderConfig):
            raise TypeError("MaiAgentWriterProvider requires MaiAgentWriterProviderConfig")
        self._config = config
        self._transport = transport if transport is not None else UrllibMaiAgentJsonTransport()
        self.last_status_code: int | None = None
        self.call_count = 0

    def __call__(self, request: Mapping[str, Any]) -> object:
        if not isinstance(request, Mapping):
            raise TypeError("Writer provider request must be a mapping")
        body = json.dumps(
            {
                "message": {
                    "role": "user",
                    "content": json.dumps(request, ensure_ascii=False, separators=(",", ":")),
                },
                "conversation": None,
                "attachments": [],
                "is_streaming": False,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        self.call_count += 1
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
            raise WriterProviderFailure("MaiAgent Writer request timed out") from None
        except Exception:
            raise WriterProviderFailure("MaiAgent Writer provider transport failed") from None
        if not isinstance(response, MaiAgentHttpResponse):
            raise WriterProviderFailure("MaiAgent Writer provider response was invalid")
        self.last_status_code = response.status_code
        if response.status_code != 200:
            raise WriterProviderFailure("MaiAgent Writer provider request failed")
        try:
            return parse_maiagent_response(response.body)
        except MaiAgentResponseError:
            raise WriterResponseError("MaiAgent Writer provider response was invalid") from None


def _contains_traditional_chinese(value: str) -> bool:
    # A conservative language gate: formal Writer prose must contain Han
    # characters.  Semantic grounding remains the Validator's responsibility.
    return bool(re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", value))


class ReportWriter:
    """Sole Writer owner for an already ordered REPORTABLE population."""

    def __init__(
        self,
        provider: WriterProvider | None = None,
        *,
        config: MaiAgentWriterProviderConfig | None = None,
        transport: MaiAgentJsonHttpTransport | None = None,
    ) -> None:
        if provider is not None and config is not None:
            raise ValueError("ReportWriter accepts provider or config, not both")
        if provider is None and config is not None:
            provider = MaiAgentWriterProvider(config, transport=transport)
        self._provider = provider
        self.call_count = 0
        self.correction_call_count = 0
        self.last_http_status: int | None = None

    @classmethod
    def from_environment(
        cls,
        *,
        environ: Mapping[str, str] | None = None,
        timeout_seconds: float = 45.0,
        dotenv_path: str | os.PathLike[str] | None = None,
        transport: MaiAgentJsonHttpTransport | None = None,
    ) -> "ReportWriter | None":
        config = MaiAgentWriterProviderConfig.from_environment(
            environ, timeout_seconds=timeout_seconds, dotenv_path=dotenv_path
        )
        return None if config is None else cls(config=config, transport=transport)

    def write(self, ordered_results: tuple[ReportWorkflowResult, ...]) -> tuple[WriterReportBlock, ...]:
        if not isinstance(ordered_results, tuple):
            raise TypeError("ReportWriter.write requires a tuple")
        if any(not isinstance(result, ReportWorkflowResult) for result in ordered_results):
            raise TypeError("ReportWriter.write requires ReportWorkflowResult values")
        if not ordered_results:
            return ()
        if self._provider is None:
            raise WriterProviderFailure("MaiAgent Writer configuration is unavailable")

        blocks: list[WriterReportBlock] = []
        failures: list[str] = []
        for result in ordered_results:
            self.call_count += 1
            event_id = result.event_group.event_id
            try:
                request = build_maiagent_writer_model_input(result)
                raw = self._provider(request)
                if isinstance(self._provider, MaiAgentWriterProvider):
                    self.last_http_status = self._provider.last_status_code
                block = raw if isinstance(raw, WriterReportBlock) else WriterReportBlock.from_mapping(raw)  # type: ignore[arg-type]
                if block.event_id != event_id:
                    raise ValueError("Writer response event_id does not match request")
                if any(not _contains_traditional_chinese(getattr(block, name)) for name in ("headline", "factual_summary", "taipei_insight")):
                    raise ValueError("Writer response must use Traditional Chinese formal prose")
                blocks.append(block)
            except Exception as exc:
                failures.append(f"{event_id}:{type(exc).__name__}")
        if failures:
            raise WriterPopulationError("Writer population failed: " + ",".join(failures))
        output_ids = tuple(block.event_id for block in blocks)
        input_ids = tuple(result.event_group.event_id for result in ordered_results)
        if output_ids != input_ids or len(output_ids) != len(set(output_ids)):
            raise WriterPopulationError("Writer output population does not match ordered input")
        return tuple(blocks)

    def correct(
        self,
        result: ReportWorkflowResult,
        block: WriterReportBlock,
        reasons: tuple[str, ...] = (),
    ) -> WriterReportBlock:
        """Make one isolated semantic correction request for one event.

        This method is intentionally separate from ``write``; callers count it
        as Validator-directed correction, never as Writer transport retry.
        """

        if self._provider is None:
            raise WriterProviderFailure("MaiAgent Writer configuration is unavailable")
        self.correction_call_count += 1
        request = build_maiagent_writer_model_input(result)
        request = dict(request)
        request["correction"] = {"previous_block": {name: getattr(block, name) for name in WRITER_RESPONSE_FIELDS}, "reasons": list(reasons)}
        raw = self._provider(request)
        corrected = raw if isinstance(raw, WriterReportBlock) else WriterReportBlock.from_mapping(raw)  # type: ignore[arg-type]
        if corrected.event_id != result.event_group.event_id:
            raise WriterResponseError("Writer correction event_id does not match request")
        if any(not _contains_traditional_chinese(getattr(corrected, name)) for name in ("headline", "factual_summary", "taipei_insight")):
            raise WriterResponseError("Writer correction must use Traditional Chinese formal prose")
        return corrected


__all__ = [
    "WRITER_CHATBOT_ENVIRONMENT_KEY",
    "STRUCTURED_HELPER_CHATBOT_ENVIRONMENT_KEY",
    "WRITER_RESPONSE_FIELDS",
    "WriterReportBlock",
    "WriterFailure",
    "WriterProviderFailure",
    "WriterResponseError",
    "WriterPopulationError",
    "MaiAgentWriterProviderConfig",
    "MaiAgentWriterProvider",
    "build_maiagent_writer_model_input",
    "ReportWriter",
]
