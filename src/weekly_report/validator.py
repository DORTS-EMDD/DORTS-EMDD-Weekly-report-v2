"""Authoritative post-Writer validation and semantic proposal boundary."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol
from urllib.parse import urlparse

from .report_service import FormalReportMetadata
from .report_workflow import ReportWorkflowResult
from .writer import WriterReportBlock


class ValidationLanguageAssessment(StrEnum):
    TRADITIONAL_CHINESE = "TRADITIONAL_CHINESE"
    NOT_TRADITIONAL_CHINESE = "NOT_TRADITIONAL_CHINESE"
    UNCERTAIN = "UNCERTAIN"


class ValidationUnitAssessment(StrEnum):
    SUPPORTED = "SUPPORTED"
    ANALYSIS = "ANALYSIS"
    UNSUPPORTED = "UNSUPPORTED"
    UNCERTAIN = "UNCERTAIN"


class ValidationFieldName(StrEnum):
    HEADLINE = "headline"
    FACTUAL_SUMMARY = "factual_summary"
    TAIPEI_INSIGHT = "taipei_insight"


class ValidationStageFailureReason(StrEnum):
    MISSING_SEMANTIC_PROVIDER = "MISSING_SEMANTIC_PROVIDER"
    PROVIDER_FAILURE = "PROVIDER_FAILURE"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    EVENT_ID_MISMATCH = "EVENT_ID_MISMATCH"
    FIELD_SET_MISMATCH = "FIELD_SET_MISMATCH"
    TEXT_COVERAGE_INVALID = "TEXT_COVERAGE_INVALID"
    INVALID_CITATION = "INVALID_CITATION"
    AMBIGUOUS_CITATION = "AMBIGUOUS_CITATION"
    SOURCE_INTEGRITY_FAILURE = "SOURCE_INTEGRITY_FAILURE"
    METADATA_INTEGRITY_FAILURE = "METADATA_INTEGRITY_FAILURE"
    EVENT_POPULATION_FAILURE = "EVENT_POPULATION_FAILURE"
    CORRECTION_FAILURE = "CORRECTION_FAILURE"


class ValidationStageFailure(RuntimeError):
    """Safe whole-run technical inability to complete authoritative validation."""

    def __init__(
        self,
        reason: ValidationStageFailureReason | str,
        *,
        event_id: str = "",
    ) -> None:
        try:
            canonical = ValidationStageFailureReason(reason)
        except (TypeError, ValueError) as exc:
            raise ValueError("ValidationStageFailure requires a finite reason") from exc
        if not isinstance(event_id, str):
            raise TypeError("ValidationStageFailure event_id must be a string")
        self.reason = canonical
        self.event_id = event_id
        super().__init__(f"validation stage failed: {canonical.value}")


class ValidationPopulationError(ValidationStageFailure):
    """The Writer handoff did not preserve the authoritative population."""

    def __init__(self, message: str = "validation population failed") -> None:
        super().__init__(ValidationStageFailureReason.EVENT_POPULATION_FAILURE)
        self.message = message


class _ValidationProposalCitationError(ValueError):
    """Internal parser marker for a malformed citation value."""


@dataclass(frozen=True, slots=True)
class ValidationEvidenceSource:
    candidate_id: str
    substantive_content: str

    def __post_init__(self) -> None:
        if not isinstance(self.candidate_id, str) or not self.candidate_id.strip():
            raise ValueError("Validation evidence source requires candidate_id")
        if not isinstance(self.substantive_content, str) or not self.substantive_content.strip():
            raise ValueError("Validation evidence source requires substantive_content")

    def as_mapping(self) -> dict[str, str]:
        return {"candidate_id": self.candidate_id, "substantive_content": self.substantive_content}


@dataclass(frozen=True, slots=True)
class ValidationWriterProse:
    headline: str
    factual_summary: str
    taipei_insight: str

    def __post_init__(self) -> None:
        for field_name in ("headline", "factual_summary", "taipei_insight"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Validation writer prose requires nonblank {field_name}")

    def as_mapping(self) -> dict[str, str]:
        return {
            "headline": self.headline,
            "factual_summary": self.factual_summary,
            "taipei_insight": self.taipei_insight,
        }


@dataclass(frozen=True, slots=True)
class ValidationSemanticRequest:
    event_id: str
    evidence_sources: tuple[ValidationEvidenceSource, ...]
    writer_prose: ValidationWriterProse

    def __post_init__(self) -> None:
        if not isinstance(self.event_id, str) or not self.event_id.strip():
            raise ValueError("Validation semantic request requires event_id")
        sources = tuple(self.evidence_sources)
        if not sources or any(not isinstance(source, ValidationEvidenceSource) for source in sources):
            raise TypeError("Validation semantic request evidence_sources must be typed")
        source_ids = tuple(source.candidate_id for source in sources)
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("Validation semantic request sources require unique candidate IDs")
        if not isinstance(self.writer_prose, ValidationWriterProse):
            raise TypeError("Validation semantic request writer_prose must be typed")
        object.__setattr__(self, "evidence_sources", sources)

    def as_payload(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "evidence_sources": [source.as_mapping() for source in self.evidence_sources],
            "writer_prose": self.writer_prose.as_mapping(),
        }


@dataclass(frozen=True, slots=True)
class ValidationEvidenceCitation:
    candidate_id: str
    exact_quote: str

    def __post_init__(self) -> None:
        if not isinstance(self.candidate_id, str) or not self.candidate_id.strip():
            raise ValueError("Validation citation requires candidate_id")
        if not isinstance(self.exact_quote, str) or not self.exact_quote.strip():
            raise ValueError("Validation citation requires exact_quote")


@dataclass(frozen=True, slots=True)
class ValidationClaimUnit:
    writer_quote: str
    assessment: ValidationUnitAssessment | str
    evidence_citations: tuple[ValidationEvidenceCitation, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.writer_quote, str) or not self.writer_quote:
            raise ValueError("Validation claim unit requires writer_quote")
        try:
            assessment = ValidationUnitAssessment(self.assessment)
        except (TypeError, ValueError) as exc:
            raise ValueError("Validation claim unit requires a valid assessment") from exc
        object.__setattr__(self, "assessment", assessment)
        citations = tuple(self.evidence_citations)
        if any(not isinstance(citation, ValidationEvidenceCitation) for citation in citations):
            raise TypeError("Validation claim citations must be typed")
        object.__setattr__(self, "evidence_citations", citations)


@dataclass(frozen=True, slots=True)
class ValidationFieldAssessment:
    field_name: ValidationFieldName | str
    language_assessment: ValidationLanguageAssessment | str
    units: tuple[ValidationClaimUnit, ...]

    def __post_init__(self) -> None:
        try:
            field_name = ValidationFieldName(self.field_name)
        except (TypeError, ValueError) as exc:
            raise ValueError("Validation field assessment requires a valid field") from exc
        try:
            language = ValidationLanguageAssessment(self.language_assessment)
        except (TypeError, ValueError) as exc:
            raise ValueError("Validation field assessment requires a valid language assessment") from exc
        units = tuple(self.units)
        if not units or any(not isinstance(unit, ValidationClaimUnit) for unit in units):
            raise ValueError("Validation field assessment requires claim units")
        object.__setattr__(self, "field_name", field_name)
        object.__setattr__(self, "language_assessment", language)
        object.__setattr__(self, "units", units)


@dataclass(frozen=True, slots=True)
class ValidationSemanticProposal:
    event_id: str
    field_assessments: tuple[ValidationFieldAssessment, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.event_id, str) or not self.event_id.strip():
            raise ValueError("Validation proposal requires event_id")
        assessments = tuple(self.field_assessments)
        if any(not isinstance(item, ValidationFieldAssessment) for item in assessments):
            raise TypeError("Validation proposal field assessments must be typed")
        object.__setattr__(self, "field_assessments", assessments)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ValidationSemanticProposal":
        if not isinstance(value, Mapping) or set(value) != {"event_id", "field_assessments"}:
            raise ValueError("Validation proposal fields do not match the exact schema")
        raw_assessments = value["field_assessments"]
        if not isinstance(raw_assessments, (list, tuple)):
            raise ValueError("Validation proposal field_assessments must be an array")
        parsed_fields: list[ValidationFieldAssessment] = []
        for raw_field in raw_assessments:
            if not isinstance(raw_field, Mapping) or set(raw_field) != {
                "field_name", "language_assessment", "units"
            }:
                raise ValueError("Validation field assessment fields do not match the exact schema")
            raw_units = raw_field["units"]
            if not isinstance(raw_units, (list, tuple)):
                raise ValueError("Validation field units must be an array")
            units: list[ValidationClaimUnit] = []
            for raw_unit in raw_units:
                if not isinstance(raw_unit, Mapping) or set(raw_unit) != {
                    "writer_quote", "assessment", "evidence_citations"
                }:
                    raise ValueError("Validation claim unit fields do not match the exact schema")
                raw_citations = raw_unit["evidence_citations"]
                if not isinstance(raw_citations, (list, tuple)):
                    raise ValueError("Validation evidence_citations must be an array")
                citations: list[ValidationEvidenceCitation] = []
                for raw_citation in raw_citations:
                    if not isinstance(raw_citation, Mapping) or set(raw_citation) != {
                        "candidate_id", "exact_quote"
                    }:
                        raise ValueError("Validation citation fields do not match the exact schema")
                    try:
                        citations.append(
                            ValidationEvidenceCitation(
                                raw_citation["candidate_id"], raw_citation["exact_quote"]
                            )
                        )
                    except (TypeError, ValueError) as exc:
                        raise _ValidationProposalCitationError from exc
                units.append(
                    ValidationClaimUnit(raw_unit["writer_quote"], raw_unit["assessment"], tuple(citations))
                )
            parsed_fields.append(
                ValidationFieldAssessment(
                    raw_field["field_name"], raw_field["language_assessment"], tuple(units)
                )
            )
        return cls(value["event_id"], tuple(parsed_fields))


class ValidationSemanticProposalProvider(Protocol):
    def __call__(self, request: ValidationSemanticRequest) -> object:
        """Return one untrusted semantic proposal for the bounded request."""


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


class Validator:
    """Sole post-Writer validation owner."""

    _FIELD_NAMES = tuple(ValidationFieldName)

    def __init__(
        self,
        correction_provider: CorrectionProvider | None = None,
        semantic_provider: ValidationSemanticProposalProvider | None = None,
    ) -> None:
        self._correction_provider = correction_provider
        self._semantic_provider = semantic_provider
        self.semantic_call_count = 0

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
        if self._semantic_provider is None:
            raise ValidationStageFailure(ValidationStageFailureReason.MISSING_SEMANTIC_PROVIDER)

        passed: list[ValidatedReportEvent] = []
        failed: list[ValidationEventFailure] = []
        correction_calls = 0
        for result, metadata, initial_block in zip(ordered_results, formal_metadata, writer_blocks, strict=True):
            self._validate_event_boundary(result, metadata, initial_block)
            block = initial_block
            reasons = self._semantic_reasons(result, block)
            corrected = False
            if reasons and self._correction_provider is not None:
                correction_calls += 1
                corrected = True
                try:
                    block = self._correction_provider(result, block, tuple(reasons))
                    if not isinstance(block, WriterReportBlock):
                        raise TypeError("correction provider must return WriterReportBlock")
                    self._validate_event_boundary(result, metadata, block)
                    reasons = self._semantic_reasons(result, block)
                except ValidationStageFailure:
                    raise
                except Exception:
                    raise ValidationStageFailure(
                        ValidationStageFailureReason.CORRECTION_FAILURE,
                        event_id=result.event_group.event_id,
                    ) from None
            if reasons:
                failed.append(ValidationEventFailure(result.event_group.event_id, reasons, corrected))
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

    def _validate_event_boundary(
        self,
        result: ReportWorkflowResult,
        metadata: FormalReportMetadata,
        block: WriterReportBlock,
    ) -> None:
        event_id = result.event_group.event_id
        if block.event_id != event_id or metadata.event_id != event_id:
            raise ValidationStageFailure(ValidationStageFailureReason.EVENT_ID_MISMATCH, event_id=event_id)
        for field_name in ("headline", "factual_summary", "taipei_insight"):
            value = getattr(block, field_name, None)
            if not isinstance(value, str) or not value.strip():
                raise ValidationStageFailure(
                    ValidationStageFailureReason.TEXT_COVERAGE_INVALID,
                    event_id=event_id,
                )

        canonical_id = result.event_group.canonical_candidate_id
        canonical = tuple(
            record for record in result.member_records
            if record.candidate.candidate_id == canonical_id
        )
        if len(canonical) != 1:
            raise ValidationStageFailure(
                ValidationStageFailureReason.SOURCE_INTEGRITY_FAILURE,
                event_id=event_id,
            )
        evidence = canonical[0].evidence
        if metadata.source_url != evidence.canonical_source_url:
            raise ValidationStageFailure(
                ValidationStageFailureReason.METADATA_INTEGRITY_FAILURE,
                event_id=event_id,
            )
        try:
            expected_display = (urlparse(evidence.canonical_source_url).hostname or "").lower()
        except (TypeError, ValueError):
            expected_display = ""
        if not expected_display or metadata.source_display != expected_display:
            raise ValidationStageFailure(
                ValidationStageFailureReason.METADATA_INTEGRITY_FAILURE,
                event_id=event_id,
            )
        if not isinstance(evidence.substantive_content, str) or not evidence.substantive_content.strip():
            raise ValidationStageFailure(
                ValidationStageFailureReason.SOURCE_INTEGRITY_FAILURE,
                event_id=event_id,
            )

    def _request_for_event(
        self,
        result: ReportWorkflowResult,
        block: WriterReportBlock,
    ) -> ValidationSemanticRequest:
        canonical_id = result.event_group.canonical_candidate_id
        canonical = tuple(
            record for record in result.member_records
            if record.candidate.candidate_id == canonical_id
        )
        if len(canonical) != 1:
            raise ValidationStageFailure(
                ValidationStageFailureReason.SOURCE_INTEGRITY_FAILURE,
                event_id=result.event_group.event_id,
            )
        evidence = canonical[0].evidence
        return ValidationSemanticRequest(
            result.event_group.event_id,
            (ValidationEvidenceSource(canonical_id, evidence.substantive_content),),
            ValidationWriterProse(block.headline, block.factual_summary, block.taipei_insight),
        )

    def _semantic_reasons(
        self,
        result: ReportWorkflowResult,
        block: WriterReportBlock,
    ) -> tuple[str, ...]:
        request = self._request_for_event(result, block)
        proposal = self._call_semantic_provider(request)
        self._validate_proposal_structure(request, proposal)
        reasons: list[str] = []
        fields = {field.field_name: field for field in proposal.field_assessments}
        for field_name in self._FIELD_NAMES:
            field = fields[field_name]
            if field.language_assessment is not ValidationLanguageAssessment.TRADITIONAL_CHINESE:
                reasons.append(f"language_{field_name.value}")
            allowed = (
                {ValidationUnitAssessment.SUPPORTED}
                if field_name is not ValidationFieldName.TAIPEI_INSIGHT
                else {ValidationUnitAssessment.SUPPORTED, ValidationUnitAssessment.ANALYSIS}
            )
            for unit in field.units:
                if unit.assessment not in allowed:
                    reasons.append(f"semantic_{field_name.value}_{unit.assessment.value.lower()}")
                elif not unit.evidence_citations:
                    raise ValidationStageFailure(
                        ValidationStageFailureReason.INVALID_CITATION,
                        event_id=request.event_id,
                    )
        return tuple(dict.fromkeys(reasons))

    def _call_semantic_provider(self, request: ValidationSemanticRequest) -> ValidationSemanticProposal:
        self.semantic_call_count += 1
        try:
            raw = self._semantic_provider(request)  # type: ignore[misc]
        except ValidationStageFailure:
            raise
        except Exception:
            raise ValidationStageFailure(
                ValidationStageFailureReason.PROVIDER_FAILURE,
                event_id=request.event_id,
            ) from None
        try:
            proposal = raw if isinstance(raw, ValidationSemanticProposal) else ValidationSemanticProposal.from_mapping(raw)
        except _ValidationProposalCitationError:
            raise ValidationStageFailure(
                ValidationStageFailureReason.INVALID_CITATION,
                event_id=request.event_id,
            ) from None
        except Exception:
            raise ValidationStageFailure(
                ValidationStageFailureReason.INVALID_RESPONSE,
                event_id=request.event_id,
            ) from None
        return proposal

    def _validate_proposal_structure(
        self,
        request: ValidationSemanticRequest,
        proposal: ValidationSemanticProposal,
    ) -> None:
        if proposal.event_id != request.event_id:
            raise ValidationStageFailure(
                ValidationStageFailureReason.EVENT_ID_MISMATCH,
                event_id=request.event_id,
            )
        fields = tuple(item.field_name for item in proposal.field_assessments)
        if (
            len(fields) != len(self._FIELD_NAMES)
            or len(set(fields)) != len(fields)
            or set(fields) != set(self._FIELD_NAMES)
        ):
            raise ValidationStageFailure(
                ValidationStageFailureReason.FIELD_SET_MISMATCH,
                event_id=request.event_id,
            )
        sources = {source.candidate_id: source.substantive_content for source in request.evidence_sources}
        prose = request.writer_prose.as_mapping()
        for field in proposal.field_assessments:
            original = prose[field.field_name.value]
            if "".join(unit.writer_quote for unit in field.units) != original:
                raise ValidationStageFailure(
                    ValidationStageFailureReason.TEXT_COVERAGE_INVALID,
                    event_id=request.event_id,
                )
            for unit in field.units:
                for citation in unit.evidence_citations:
                    if citation.candidate_id not in sources:
                        raise ValidationStageFailure(
                            ValidationStageFailureReason.INVALID_CITATION,
                            event_id=request.event_id,
                        )
                    occurrences = _exact_occurrences(sources[citation.candidate_id], citation.exact_quote)
                    if not occurrences:
                        raise ValidationStageFailure(
                            ValidationStageFailureReason.INVALID_CITATION,
                            event_id=request.event_id,
                        )
                    if len(occurrences) != 1:
                        raise ValidationStageFailure(
                            ValidationStageFailureReason.AMBIGUOUS_CITATION,
                            event_id=request.event_id,
                        )


def _exact_occurrences(source: str, quote: str) -> tuple[int, ...]:
    if not isinstance(quote, str) or not quote:
        return ()
    positions: list[int] = []
    start = 0
    while True:
        index = source.find(quote, start)
        if index < 0:
            return tuple(positions)
        positions.append(index)
        start = index + 1


ReportValidator = Validator


__all__ = [
    "ValidationLanguageAssessment",
    "ValidationUnitAssessment",
    "ValidationFieldName",
    "ValidationStageFailureReason",
    "ValidationStageFailure",
    "ValidationPopulationError",
    "ValidationEvidenceSource",
    "ValidationWriterProse",
    "ValidationSemanticRequest",
    "ValidationEvidenceCitation",
    "ValidationClaimUnit",
    "ValidationFieldAssessment",
    "ValidationSemanticProposal",
    "ValidationSemanticProposalProvider",
    "ValidationEventFailure",
    "ValidatedReportEvent",
    "ValidationResult",
    "CorrectionProvider",
    "Validator",
    "ReportValidator",
]
