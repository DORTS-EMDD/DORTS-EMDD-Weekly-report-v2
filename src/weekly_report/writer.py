"""The sole formal-report Writer owner.

The Writer is deliberately small: it serialises one already ordered event at a
time, makes one isolated provider request, and accepts only the four prose
fields that the model owns.  All report metadata remains a Python projection
owned by :mod:`report_service`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import json
import math
import os
from pathlib import Path
import re
from typing import Any, Protocol
from urllib.parse import quote, urlsplit

from .evidence_sentences import event_focus_sentences
from .maiagent_transport import (
    MaiAgentHttpResponse,
    MaiAgentJsonHttpTransport,
    MaiAgentResponseError,
    UrllibMaiAgentJsonTransport,
    parse_maiagent_response,
    MAIAGENT_WRITER_TIMEOUT_SECONDS,
    request_maiagent_proposal,
)
from .report_workflow import ReportWorkflowResult
from .contracts import (
    SemanticProviderConfigurationFailure,
    SemanticProviderTechnicalFailure,
    TechnicalGap,
    TechnicalGapKind,
)


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
            # Surrounding whitespace is layout, never content.
            object.__setattr__(self, field_name, value.strip())

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
    timeout_seconds: float = MAIAGENT_WRITER_TIMEOUT_SECONDS

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
        timeout_seconds: float = MAIAGENT_WRITER_TIMEOUT_SECONDS,
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
    "The headline is one plain-text line naming the event. Do not add emoji, symbols, or a category, section or label prefix such as 【營運政策】, [營運政策] or 重大事故｜; the report assembles its own sections.",
    "Write about the event, not about this request: never mention the request, its inputs or this task (for example 候選資料, event_focus or 提供的資料).",
    "Do not search, browse, use tools, RAG, outside knowledge, or metadata.",
    "Do not infer or author date, country, transit system, location, category, taxonomy, source, or URL.",
    "Taipei insight may give professional implications but must not assert unsupplied Taipei Metro facts.",
    "Audience: engineers of an urban rail authority. factual_summary states, in two to five sentences, what happened, to which line, system or equipment, who acted, and the key technical, schedule and quantity facts the evidence gives.",
    "Every statement must be directly supported by the evidence. Keep the values of numbers, units, dates and times exactly as stated, but write them in Traditional Chinese report style (for example 10月11日, 9月18日, 2027年年中, 25,474人次); do not add a year, day or time the evidence does not give.",
    "The reported event is the one described by event_focus, which quotes the evidence sentences that identify it: write the headline and factual_summary about that event, use the rest of the evidence only for details of the same event, and never report another event the article mentions.",
    "Keep a proper name of a place, line, station, product or organization in its original form unless the evidence gives its Chinese name or it has a widely established Traditional Chinese name; never guess a translation.",
    "Korean and Japanese names: use the established Traditional Chinese name when one exists (for example 蔚山, 光州, 慶尚南道, 名古屋, 東京地下鐵); otherwise keep the complete original name unchanged. Never mix scripts inside one name or word (not 경남道長 or 울산市議會).",
    "Translate technical terms into Traditional Chinese; do not leave common English words such as turnkey untranslated.",
    "When the request contains a correction, rewrite the previous block so that every listed statement is removed or corrected to match the evidence, keep the supported statements, and add no new facts.",
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
        "prompt_version": "formal-report-writer-v5",
        "schema_version": "writer-report-block-v1",
        "instructions": list(WRITER_INSTRUCTIONS),
        "writer_request": {
            "event_id": result.event_group.event_id,
            "authoritative_evidence": {"substantive_content": content},
            # RC-20: the Candidate event Scope identified in this evidence.
            "event_focus": [
                sentence.text
                for sentence in event_focus_sentences(content, dict(records[0].scope.provenance).get("candidate_event_focus"))
            ],
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
        # Technical failures propagate as typed SemanticProviderTechnicalFailure
        # after the shared bounded retry (never a semantic redraft).
        proposal = request_maiagent_proposal(
            self._transport,
            self._config.completion_endpoint,
            headers={
                "Authorization": f"Api-Key {self._config.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            body=body,
            timeout_seconds=float(self._config.timeout_seconds),
            task="writer",
        )
        self.last_status_code = 200
        return proposal


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
        timeout_seconds: float = MAIAGENT_WRITER_TIMEOUT_SECONDS,
        dotenv_path: str | os.PathLike[str] | None = None,
        transport: MaiAgentJsonHttpTransport | None = None,
    ) -> "ReportWriter | None":
        config = MaiAgentWriterProviderConfig.from_environment(
            environ, timeout_seconds=timeout_seconds, dotenv_path=dotenv_path
        )
        return None if config is None else cls(config=config, transport=transport)

    def write(
        self,
        ordered_results: tuple[ReportWorkflowResult, ...],
        *,
        on_event_technical_gap: Callable[[TechnicalGap], None] | None = None,
    ) -> tuple[WriterReportBlock, ...]:
        """Draft one block per event.

        Without ``on_event_technical_gap`` any event failure fails the whole
        population.  With it (the formal application), a typed provider
        technical failure or an invalid response for one event is reported as a
        TechnicalGap and only that event is omitted (RC-5/RC-6).  Input-build
        failures and configuration failures still fail the run.
        """

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
        expected_ids: list[str] = []
        for result in ordered_results:
            self.call_count += 1
            event_id = result.event_group.event_id
            try:
                request = build_maiagent_writer_model_input(result)
                try:
                    raw = self._provider(request)
                except SemanticProviderConfigurationFailure:
                    raise
                except SemanticProviderTechnicalFailure as failure:
                    if on_event_technical_gap is None:
                        raise
                    on_event_technical_gap(TechnicalGap.from_failure("Writer", event_id, failure))
                    continue
                if isinstance(self._provider, MaiAgentWriterProvider):
                    self.last_http_status = self._provider.last_status_code
                try:
                    block = raw if isinstance(raw, WriterReportBlock) else WriterReportBlock.from_mapping(raw)  # type: ignore[arg-type]
                    if block.event_id != event_id:
                        raise ValueError("Writer response event_id does not match request")
                except Exception:
                    if on_event_technical_gap is None:
                        raise
                    on_event_technical_gap(
                        TechnicalGap("Writer", event_id, TechnicalGapKind.PROPOSAL_CONTRACT_VIOLATION, "RESPONSE_INVALID", 1)
                    )
                    continue
                blocks.append(block)
                expected_ids.append(event_id)
            except SemanticProviderConfigurationFailure:
                raise
            except Exception as exc:
                if on_event_technical_gap is not None:
                    raise
                failures.append(f"{event_id}:{type(exc).__name__}")
        if failures:
            raise WriterPopulationError("Writer population failed: " + ",".join(failures))
        output_ids = tuple(block.event_id for block in blocks)
        if output_ids != tuple(expected_ids) or len(output_ids) != len(set(output_ids)):
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
