"""Post-Writer validation with an explicit event-level correction boundary."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import re
from typing import Any
from urllib.parse import urlparse

from .report_service import FormalReportMetadata
from .report_workflow import ReportWorkflowResult
from .writer import WriterReportBlock


class ValidationPopulationError(ValueError):
    """The Writer handoff did not preserve the authoritative population."""


@dataclass(frozen=True, slots=True)
class ValidationEventFailure:
    event_id: str
    reasons: tuple[str, ...]
    corrected: bool = False


@dataclass(frozen=True, slots=True)
class ValidatedReportEvent:
    """One Validation-PASS event retaining exact upstream references."""

    result: ReportWorkflowResult
    metadata: FormalReportMetadata
    block: WriterReportBlock

    @property
    def event_id(self) -> str:
        return self.result.event_group.event_id


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Immutable event-level Validation outcome."""

    ordered_results: tuple[ReportWorkflowResult, ...]
    formal_metadata: tuple[FormalReportMetadata, ...]
    passed: tuple[ValidatedReportEvent, ...]
    failed: tuple[ValidationEventFailure, ...] = ()
    correction_calls: int = 0

    def __post_init__(self) -> None:
        for field_name, expected_type in (
            ("ordered_results", ReportWorkflowResult),
            ("formal_metadata", FormalReportMetadata),
        ):
            values = tuple(getattr(self, field_name))
            if any(not isinstance(value, expected_type) for value in values):
                raise TypeError(f"ValidationResult {field_name} has invalid values")
            object.__setattr__(self, field_name, values)
        passed = tuple(self.passed)
        if any(not isinstance(value, ValidatedReportEvent) for value in passed):
            raise TypeError("ValidationResult passed values must be typed")
        object.__setattr__(self, "passed", passed)
        failed = tuple(self.failed)
        if any(not isinstance(value, ValidationEventFailure) for value in failed):
            raise TypeError("ValidationResult failed values must be typed")
        object.__setattr__(self, "failed", failed)
        if isinstance(self.correction_calls, bool) or not isinstance(self.correction_calls, int) or self.correction_calls < 0:
            raise ValueError("ValidationResult correction_calls must be non-negative")

    @property
    def passed_events(self) -> tuple[ValidatedReportEvent, ...]:
        return self.passed

    @property
    def failed_event_ids(self) -> tuple[str, ...]:
        return tuple(item.event_id for item in self.failed)

    @property
    def pass_count(self) -> int:
        return len(self.passed)

    @property
    def final_report_count(self) -> int:
        return self.pass_count


CorrectionProvider = Callable[
    [ReportWorkflowResult, WriterReportBlock, tuple[str, ...]], WriterReportBlock
]


_TAIPEI_ASSERTION = re.compile(
    r"(?:臺北捷運|台北捷運|北捷).{0,24}(?:已|目前|現有|採用|安裝|使用|建置|發生|規定|要求|採購|維修|配置|擁有)"
)


def _contains_han(value: str) -> bool:
    return bool(re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", value))


def _content_tokens(value: str) -> set[str]:
    return {
        token.casefold()
        for token in re.findall(r"[\u3400-\u9fff]{2,}|[A-Za-z0-9][A-Za-z0-9_-]{2,}", value)
    }


class Validator:
    """Sole post-Writer validation owner."""

    def __init__(self, correction_provider: CorrectionProvider | None = None) -> None:
        self._correction_provider = correction_provider

    def validate(
        self,
        ordered_results: tuple[ReportWorkflowResult, ...],
        formal_metadata: tuple[FormalReportMetadata, ...],
        writer_blocks: tuple[WriterReportBlock, ...],
    ) -> ValidationResult:
        ordered_results = self._require_tuple(ordered_results, ReportWorkflowResult, "ordered_results")
        formal_metadata = self._require_tuple(formal_metadata, FormalReportMetadata, "formal_metadata")
        writer_blocks = self._require_tuple(writer_blocks, WriterReportBlock, "writer_blocks")
        expected_ids = tuple(item.event_group.event_id for item in ordered_results)
        metadata_ids = tuple(item.event_id for item in formal_metadata)
        block_ids = tuple(item.event_id for item in writer_blocks)
        if len(formal_metadata) != len(ordered_results) or metadata_ids != expected_ids:
            raise ValidationPopulationError("FormalReportMetadata population does not match Ordering")
        if len(writer_blocks) != len(ordered_results) or block_ids != expected_ids:
            raise ValidationPopulationError("Writer population does not match Ordering")
        if len(set(block_ids)) != len(block_ids):
            raise ValidationPopulationError("Writer population contains duplicate event IDs")
        if not ordered_results:
            return ValidationResult(ordered_results, formal_metadata, ())

        passed: list[ValidatedReportEvent] = []
        failed: list[ValidationEventFailure] = []
        correction_calls = 0
        for result, metadata, block in zip(ordered_results, formal_metadata, writer_blocks, strict=True):
            reasons = self._event_reasons(result, metadata, block)
            corrected = False
            if reasons and self._correction_provider is not None:
                correction_calls += 1
                corrected = True
                try:
                    block = self._correction_provider(result, block, tuple(reasons))
                    if not isinstance(block, WriterReportBlock):
                        raise TypeError("correction provider must return WriterReportBlock")
                    if block.event_id != result.event_group.event_id:
                        raise ValueError("correction changed event_id")
                    reasons = self._event_reasons(result, metadata, block)
                except Exception as exc:
                    reasons = tuple(reasons) + (f"correction:{type(exc).__name__}",)
            if reasons:
                failed.append(ValidationEventFailure(result.event_group.event_id, tuple(dict.fromkeys(reasons)), corrected))
            else:
                passed.append(ValidatedReportEvent(result, metadata, block))
        return ValidationResult(ordered_results, formal_metadata, tuple(passed), tuple(failed), correction_calls)

    @staticmethod
    def _require_tuple(values: object, item_type: type[Any], name: str) -> tuple[Any, ...]:
        if not isinstance(values, tuple):
            raise TypeError(f"Validator {name} must be a tuple")
        if any(not isinstance(value, item_type) for value in values):
            raise TypeError(f"Validator {name} has invalid values")
        return values

    @classmethod
    def _event_reasons(
        cls,
        result: ReportWorkflowResult,
        metadata: FormalReportMetadata,
        block: WriterReportBlock,
    ) -> tuple[str, ...]:
        reasons: list[str] = []
        event_id = result.event_group.event_id
        if block.event_id != event_id or metadata.event_id != event_id:
            reasons.append("event_id_mismatch")
        for field_name in ("headline", "factual_summary", "taipei_insight"):
            value = getattr(block, field_name, None)
            if not isinstance(value, str) or not value.strip():
                reasons.append(f"blank_{field_name}")
            elif not _contains_han(value):
                reasons.append(f"non_traditional_chinese_{field_name}")

        canonical_id = result.event_group.canonical_candidate_id
        canonical = tuple(record for record in result.member_records if record.candidate.candidate_id == canonical_id)
        if len(canonical) != 1:
            reasons.append("canonical_member_integrity")
            return tuple(dict.fromkeys(reasons))
        evidence = canonical[0].evidence
        if metadata.source_url != evidence.canonical_source_url:
            reasons.append("source_url_mismatch")
        try:
            parsed = urlparse(evidence.canonical_source_url)
            expected_display = (parsed.hostname or "").lower()
        except (TypeError, ValueError):
            expected_display = ""
        if not expected_display or metadata.source_display != expected_display:
            reasons.append("source_display_mismatch")

        body = evidence.substantive_content
        if not isinstance(body, str) or not body.strip():
            reasons.append("missing_authoritative_evidence")
        else:
            body_tokens = _content_tokens(body)
            summary_tokens = _content_tokens(block.factual_summary)
            if body_tokens and not (body_tokens & summary_tokens):
                reasons.append("factual_grounding")
            if _TAIPEI_ASSERTION.search(block.taipei_insight) and not _TAIPEI_ASSERTION.search(body):
                reasons.append("unsupported_taipei_assertion")
        return tuple(dict.fromkeys(reasons))


ReportValidator = Validator


__all__ = [
    "ValidationPopulationError",
    "ValidationEventFailure",
    "ValidatedReportEvent",
    "ValidationResult",
    "CorrectionProvider",
    "Validator",
    "ReportValidator",
]
