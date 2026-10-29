"""Authoritative post-Writer validation and semantic proposal boundary."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field as dataclass_field
from enum import StrEnum
import re
from typing import Any, Protocol

from .evidence_sentences import EvidenceSentence, resolve_sentence_ids, segment_evidence_sentences
from .quantities import checked_quantities, is_grounded, stated_quantities
from .contracts import (
    SemanticProviderConfigurationFailure,
    ProposalContractViolation,
    SemanticProviderTechnicalFailure,
    TechnicalGap,
    TechnicalGapKind,
)
from .report_service import FormalReportMetadata, source_display_for
from .report_workflow import ReportWorkflowResult
from .writer import WriterFailure, WriterReportBlock


_HANGUL = "가-힣ᄀ-ᇿ㄰-㆏"
_HAN = "㐀-鿿豈-﫿"
_MIXED_WORD = re.compile(rf"[{_HAN}]{{0,4}}[{_HANGUL}]+[{_HAN}]{{1,4}}|[{_HAN}]{{1,4}}[{_HANGUL}]+")


def _mixed_script_words(text: str) -> list[str]:
    """Words in which Korean letters and Chinese characters are fused."""

    return _MIXED_WORD.findall(text)


# RC-24: a headline is plain text naming the event. Sections are assembled by
# Python, so a bracketed or bar-separated label prefix (【營運政策】, [營運政策],
# 重大事故｜) or an emoji/pictograph is never part of a valid headline.
_HEADLINE_LABEL = re.compile(r"^\s*(?:[【\[［〔][^】\]］〕]{1,12}[】\]］〕]|[^｜|]{1,12}[｜|])")
_PICTOGRAPH = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F]")


def _headline_decorations(headline: str) -> list[str]:
    """Label prefixes and pictographs a headline must not contain."""

    found = _PICTOGRAPH.findall(headline)
    label = _HEADLINE_LABEL.match(_PICTOGRAPH.sub("", headline))
    if label:
        found.append(label.group().strip())
    return found

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
    # RC-9: the helper reads and cites Python-segmented sentences.
    sentences: tuple[EvidenceSentence, ...] = dataclass_field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.candidate_id, str) or not self.candidate_id.strip():
            raise ValueError("Validation evidence source requires candidate_id")
        if not isinstance(self.substantive_content, str) or not self.substantive_content.strip():
            raise ValueError("Validation evidence source requires substantive_content")
        object.__setattr__(self, "sentences", segment_evidence_sentences(self.substantive_content))

    def as_mapping(self, source_ref: str) -> dict[str, object]:
        # RC-24: the helper sees a short Python-assigned reference, never the
        # candidate ID, so a citation cannot mis-type it.
        return {
            "source_ref": source_ref,
            "sentences": [sentence.as_mapping() for sentence in self.sentences],
        }


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
class ValidationWriterUnit:
    """One Validator-segmented assessment unit of a Writer prose field."""

    unit_id: str
    field_name: ValidationFieldName
    text: str

    def as_mapping(self) -> dict[str, str]:
        return {"unit_id": self.unit_id, "text": self.text}


_UNIT_TERMINATORS = frozenset("。！？；")
_UNIT_CLOSERS = frozenset("」』）〕】》〉”’\"')")


def segment_writer_field(
    field_name: ValidationFieldName | str,
    text: str,
) -> tuple[ValidationWriterUnit, ...]:
    """Deterministically split one Writer field into ordered assessment units.

    A unit ends after a run of full-width sentence terminators (with any
    closing quotes/brackets and trailing whitespace) or after a line break.
    ASCII periods never split, so decimals and abbreviations stay intact.
    Units without any letter or digit merge into the following unit (or the
    preceding one at the end).  Concatenating the units reproduces ``text``
    exactly; unit IDs are ``<field_name>-<1-based index>``.
    """

    name = ValidationFieldName(field_name)
    if not isinstance(text, str) or not text:
        raise ValueError("Writer field segmentation requires text")
    pieces: list[str] = []
    start = index = 0
    length = len(text)
    while index < length:
        character = text[index]
        if character in _UNIT_TERMINATORS or character == "\n":
            end = index + 1
            if character != "\n":
                while end < length and (text[end] in _UNIT_TERMINATORS or text[end] in _UNIT_CLOSERS):
                    end += 1
            while end < length and text[end].isspace():
                end += 1
            pieces.append(text[start:end])
            start = index = end
            continue
        index += 1
    if start < length:
        pieces.append(text[start:])
    merged: list[str] = []
    pending = ""
    for piece in pieces:
        if not any(character.isalnum() for character in piece):
            pending += piece
            continue
        merged.append(pending + piece)
        pending = ""
    if pending:
        if merged:
            merged[-1] += pending
        else:
            merged.append(pending)
    return tuple(
        ValidationWriterUnit(f"{name.value}-{position}", name, piece)
        for position, piece in enumerate(merged, start=1)
    )


@dataclass(frozen=True, slots=True)
class ValidationSemanticRequest:
    event_id: str
    evidence_sources: tuple[ValidationEvidenceSource, ...]
    writer_prose: ValidationWriterProse
    writer_units: tuple[ValidationWriterUnit, ...] = dataclass_field(init=False)

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
        prose = self.writer_prose.as_mapping()
        object.__setattr__(
            self,
            "writer_units",
            tuple(
                unit
                for name in ValidationFieldName
                for unit in segment_writer_field(name, prose[name.value])
            ),
        )

    def sources_by_ref(self) -> dict[str, ValidationEvidenceSource]:
        """``M1..Mn`` in source order (RC-24)."""

        return {f"M{index}": source for index, source in enumerate(self.evidence_sources, start=1)}

    def unit_ids_by_field(self) -> dict[ValidationFieldName, tuple[str, ...]]:
        return {
            name: tuple(unit.unit_id for unit in self.writer_units if unit.field_name is name)
            for name in ValidationFieldName
        }

    def as_payload(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "evidence_sources": [source.as_mapping(ref) for ref, source in self.sources_by_ref().items()],
            "writer_fields": [
                {
                    "field_name": name.value,
                    "units": [unit.as_mapping() for unit in self.writer_units if unit.field_name is name],
                }
                for name in ValidationFieldName
            ],
        }


@dataclass(frozen=True, slots=True)
class ValidationEvidenceCitation:
    source_ref: str
    sentence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.source_ref, str) or not self.source_ref.strip():
            raise ValueError("Validation citation requires source_ref")
        if isinstance(self.sentence_ids, str):
            raise ValueError("Validation citation sentence_ids must be an array")
        ids = tuple(self.sentence_ids)
        if not ids or any(not isinstance(value, str) or not value.strip() for value in ids):
            raise ValueError("Validation citation requires sentence_ids")
        object.__setattr__(self, "sentence_ids", ids)


@dataclass(frozen=True, slots=True)
class ValidationClaimUnit:
    unit_id: str
    assessment: ValidationUnitAssessment | str
    evidence_citations: tuple[ValidationEvidenceCitation, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.unit_id, str) or not self.unit_id:
            raise ValueError("Validation claim unit requires unit_id")
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
    unit_assessments: tuple[ValidationClaimUnit, ...]

    def __post_init__(self) -> None:
        try:
            field_name = ValidationFieldName(self.field_name)
        except (TypeError, ValueError) as exc:
            raise ValueError("Validation field assessment requires a valid field") from exc
        try:
            language = ValidationLanguageAssessment(self.language_assessment)
        except (TypeError, ValueError) as exc:
            raise ValueError("Validation field assessment requires a valid language assessment") from exc
        units = tuple(self.unit_assessments)
        if not units or any(not isinstance(unit, ValidationClaimUnit) for unit in units):
            raise ValueError("Validation field assessment requires unit assessments")
        object.__setattr__(self, "field_name", field_name)
        object.__setattr__(self, "language_assessment", language)
        object.__setattr__(self, "unit_assessments", units)


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
                "field_name", "language_assessment", "unit_assessments"
            }:
                raise ValueError("Validation field assessment fields do not match the exact schema")
            raw_units = raw_field["unit_assessments"]
            if not isinstance(raw_units, (list, tuple)):
                raise ValueError("Validation field unit_assessments must be an array")
            units: list[ValidationClaimUnit] = []
            for raw_unit in raw_units:
                if not isinstance(raw_unit, Mapping) or set(raw_unit) != {
                    "unit_id", "assessment", "evidence_citations"
                }:
                    raise ValueError("Validation claim unit fields do not match the exact schema")
                raw_citations = raw_unit["evidence_citations"]
                if not isinstance(raw_citations, (list, tuple)):
                    raise ValueError("Validation evidence_citations must be an array")
                citations: list[ValidationEvidenceCitation] = []
                for raw_citation in raw_citations:
                    if not isinstance(raw_citation, Mapping) or set(raw_citation) != {
                        "source_ref", "sentence_ids"
                    }:
                        raise ValueError("Validation citation fields do not match the exact schema")
                    try:
                        if not isinstance(raw_citation["sentence_ids"], (list, tuple)):
                            raise ValueError("sentence_ids must be an array")
                        citations.append(
                            ValidationEvidenceCitation(
                                raw_citation["source_ref"], tuple(raw_citation["sentence_ids"])
                            )
                        )
                    except (TypeError, ValueError) as exc:
                        raise _ValidationProposalCitationError from exc
                units.append(
                    ValidationClaimUnit(raw_unit["unit_id"], raw_unit["assessment"], tuple(citations))
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
        *,
        on_event_technical_gap: Callable[[TechnicalGap], None] | None = None,
    ) -> ValidationResult:
        """Validate each event independently.

        With ``on_event_technical_gap`` (the formal application), a provider
        technical failure or invalid semantic proposal for one event is a
        TechnicalGap for that event only, never a content FAIL; event-boundary
        invariant failures still abort.  Without it, they abort as before.
        """
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
            event_id = result.event_group.event_id
            try:
                reasons, feedback = self._semantic_assessment(result, block)
            except (SemanticProviderTechnicalFailure, ValidationStageFailure) as failure:
                if on_event_technical_gap is None:
                    raise
                on_event_technical_gap(self._technical_gap(event_id, failure))
                continue
            corrected = False
            if reasons and self._correction_provider is not None:
                correction_calls += 1
                corrected = True
                try:
                    # The Writer receives the unit-level findings, so it can
                    # remove or fix exactly the unsupported statements.
                    block = self._correction_provider(result, block, feedback)
                    if not isinstance(block, WriterReportBlock):
                        raise TypeError("correction provider must return WriterReportBlock")
                    self._validate_event_boundary(result, metadata, block)
                    reasons, _ = self._semantic_assessment(result, block)
                except (SemanticProviderTechnicalFailure, ValidationStageFailure, ProposalContractViolation, WriterFailure) as failure:
                    # A failed correction attempt is a technical gap for this
                    # event only; the initial block was already bounded.
                    if on_event_technical_gap is None:
                        if isinstance(failure, ValidationStageFailure):
                            raise
                        raise ValidationStageFailure(
                            ValidationStageFailureReason.CORRECTION_FAILURE, event_id=event_id
                        ) from None
                    on_event_technical_gap(self._technical_gap(event_id, failure, correction=True))
                    continue
                except Exception:
                    raise ValidationStageFailure(
                        ValidationStageFailureReason.CORRECTION_FAILURE,
                        event_id=event_id,
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
        # RC-31: the one source-label owner, never a second derivation.
        expected_display = source_display_for(canonical[0])
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

    @staticmethod
    def _technical_gap(event_id: str, failure: BaseException, *, correction: bool = False) -> TechnicalGap:
        if isinstance(failure, SemanticProviderTechnicalFailure):
            return TechnicalGap.from_failure("Validator", event_id, failure)
        if isinstance(failure, ValidationStageFailure):
            failure_class = failure.reason.value
        else:
            failure_class = "CORRECTION_FAILURE"
        if correction and not failure_class.startswith("CORRECTION"):
            failure_class = f"CORRECTION_{failure_class}"
        return TechnicalGap("Validator", event_id, TechnicalGapKind.PROPOSAL_CONTRACT_VIOLATION, failure_class, 1)

    def _semantic_reasons(
        self,
        result: ReportWorkflowResult,
        block: WriterReportBlock,
    ) -> tuple[str, ...]:
        return self._semantic_assessment(result, block)[0]

    def _semantic_assessment(
        self,
        result: ReportWorkflowResult,
        block: WriterReportBlock,
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Return the failure reasons and unit-level correction feedback."""

        # Traditional Chinese language (RC-20): Korean letters fused with
        # Chinese characters in one word are never acceptable prose, so this
        # deterministic check needs no helper call.
        mixed = [
            (field_name, word)
            for field_name in self._FIELD_NAMES
            for word in _mixed_script_words(getattr(block, field_name.value))
        ]
        decorations = _headline_decorations(block.headline)
        request = self._request_for_event(result, block)
        # Factual grounding (RC-29): every large amount and every measured
        # number the Writer states must be a quantity the Evidence states;
        # a language model's arithmetic is never the authority on magnitude.
        evidence_quantities = tuple(
            quantity
            for source in request.evidence_sources
            for quantity in stated_quantities(source.substantive_content)
        )
        ungrounded = [
            (field_name, quantity.text)
            for field_name in self._FIELD_NAMES
            for quantity in checked_quantities(getattr(block, field_name.value))
            if not is_grounded(quantity, evidence_quantities)
        ]
        if mixed or decorations or ungrounded:
            return (
                tuple(dict.fromkeys(
                    [f"language_{field_name.value}_mixed_script" for field_name, _ in mixed]
                    + (["format_headline_label"] if decorations else [])
                    + [f"factual_{field_name.value}_quantity_ungrounded" for field_name, _ in ungrounded]
                )),
                tuple(
                    [
                        f"{field_name.value}: '{word}' mixes Korean and Chinese characters; use the established "
                        "Traditional Chinese name or the complete original name"
                        for field_name, word in mixed
                    ]
                    + [
                        f"headline: remove '{item}'; the headline is plain text naming the event, without "
                        "symbols or category labels"
                        for item in decorations
                    ]
                    + [
                        f"{field_name.value}: '{text}' is not an amount or measurement the evidence states; give it "
                        "exactly as the evidence states it (same number, magnitude word and unit, or an exact "
                        "conversion), name a currency only as specifically as the evidence names it, and do not add "
                        "converted values the evidence does not state"
                        for field_name, text in ungrounded
                    ]
                ),
            )

        proposal = self._call_semantic_provider(request)
        self._validate_proposal_structure(request, proposal)
        reasons: list[str] = []
        feedback: list[str] = []
        unit_text = {unit.unit_id: unit.text for unit in request.writer_units}
        fields = {field.field_name: field for field in proposal.field_assessments}
        for field_name in self._FIELD_NAMES:
            field = fields[field_name]
            if field.language_assessment is not ValidationLanguageAssessment.TRADITIONAL_CHINESE:
                reasons.append(f"language_{field_name.value}")
                feedback.append(f"{field_name.value}: language {field.language_assessment.value}; rewrite in Traditional Chinese")
            allowed = (
                {ValidationUnitAssessment.SUPPORTED}
                if field_name is not ValidationFieldName.TAIPEI_INSIGHT
                else {ValidationUnitAssessment.SUPPORTED, ValidationUnitAssessment.ANALYSIS}
            )
            for unit in field.unit_assessments:
                if unit.assessment not in allowed:
                    reasons.append(f"semantic_{field_name.value}_{unit.assessment.value.lower()}")
                    feedback.append(f"{unit.unit_id} {unit.assessment.value}: {unit_text[unit.unit_id]}")
                elif not unit.evidence_citations:
                    raise ValidationStageFailure(
                        ValidationStageFailureReason.INVALID_CITATION,
                        event_id=request.event_id,
                    )
        return tuple(dict.fromkeys(reasons)), tuple(dict.fromkeys(feedback))

    def _call_semantic_provider(self, request: ValidationSemanticRequest) -> ValidationSemanticProposal:
        self.semantic_call_count += 1
        try:
            raw = self._semantic_provider(request)  # type: ignore[misc]
        except (SemanticProviderTechnicalFailure, SemanticProviderConfigurationFailure):
            # RC-6: a technical failure is never a semantic FAIL.
            raise
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
        sources = {ref: source.sentences for ref, source in request.sources_by_ref().items()}
        expected_units = request.unit_ids_by_field()
        for field in proposal.field_assessments:
            # Python owns segmentation; the proposal must assess every
            # Validator-supplied unit of this field exactly once.
            unit_ids = tuple(unit.unit_id for unit in field.unit_assessments)
            if len(unit_ids) != len(set(unit_ids)) or set(unit_ids) != set(expected_units[field.field_name]):
                raise ValidationStageFailure(
                    ValidationStageFailureReason.TEXT_COVERAGE_INVALID,
                    event_id=request.event_id,
                )
            for unit in field.unit_assessments:
                for citation in unit.evidence_citations:
                    if citation.source_ref not in sources:
                        raise ValidationStageFailure(
                            ValidationStageFailureReason.INVALID_CITATION,
                            event_id=request.event_id,
                        )
                    # RC-9: a citation names Python-segmented sentences of
                    # the cited source; unknown or repeated IDs are invalid.
                    if resolve_sentence_ids(sources[citation.source_ref], citation.sentence_ids) is None:
                        raise ValidationStageFailure(
                            ValidationStageFailureReason.INVALID_CITATION,
                            event_id=request.event_id,
                        )


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
    "ValidationWriterUnit",
    "segment_writer_field",
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
