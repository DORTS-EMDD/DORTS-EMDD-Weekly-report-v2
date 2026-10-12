"""Mechanical formal metadata projection and final report assembly.

``ReportService`` consumes already ordered, reportable workflow results and
Validation-PASS prose.  It does not select events, infer metadata, or rewrite
model prose.  The upstream Evidence, Temporal, Category, Taxonomy,
Reportability, and Ordering results remain authoritative; the values below are
immutable downstream projections and assembly records.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
import hashlib
import json
from typing import Any
from urllib.parse import urlparse

from .candidate_normalizer import _valid_exact_http_url
from .contracts import (
    CategoryState,
    EMSystemId,
    EventGroup,
    EventIdentityRecord,
    EvidenceState,
    ReportabilityState,
    ScopeState,
    TaxonomyState,
)
from .report_workflow import ReportWorkflowResult


class FormalMetadataFailureReason(StrEnum):
    """Finite reasons that abort a formal metadata projection."""

    MISSING_COUNTRY = "MISSING_COUNTRY"
    CONFLICTING_COUNTRY = "CONFLICTING_COUNTRY"
    MISSING_TRANSIT_SYSTEM_NAME = "MISSING_TRANSIT_SYSTEM_NAME"
    CONFLICTING_TRANSIT_SYSTEM_NAME = "CONFLICTING_TRANSIT_SYSTEM_NAME"
    INVALID_CANONICAL_MEMBER = "INVALID_CANONICAL_MEMBER"
    INVALID_CANONICAL_DATE = "INVALID_CANONICAL_DATE"
    INVALID_CANONICAL_SOURCE = "INVALID_CANONICAL_SOURCE"
    STRUCTURAL_INCONSISTENCY = "STRUCTURAL_INCONSISTENCY"


class FormalMetadataDiagnosticReason(StrEnum):
    """Finite non-failing diagnostics emitted with a projection."""

    CONFLICTING_OPTIONAL_LOCATION = "CONFLICTING_OPTIONAL_LOCATION"


@dataclass(frozen=True, slots=True)
class FormalMetadataDiagnostic:
    """Minimal provenance for an optional metadata observation."""

    event_id: str
    field_name: str
    reason: FormalMetadataDiagnosticReason
    candidate_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.event_id, str) or not self.event_id.strip():
            raise ValueError("FormalMetadataDiagnostic requires event_id")
        if not isinstance(self.field_name, str) or not self.field_name.strip():
            raise ValueError("FormalMetadataDiagnostic requires field_name")
        try:
            reason = FormalMetadataDiagnosticReason(self.reason)
        except (TypeError, ValueError) as exc:
            raise ValueError("FormalMetadataDiagnostic requires a finite reason") from exc
        object.__setattr__(self, "reason", reason)
        candidate_ids = tuple(self.candidate_ids)
        if any(not isinstance(candidate_id, str) or not candidate_id.strip() for candidate_id in candidate_ids):
            raise ValueError("FormalMetadataDiagnostic candidate_ids must be non-empty strings")
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("FormalMetadataDiagnostic candidate_ids must be unique")
        object.__setattr__(self, "candidate_ids", candidate_ids)


@dataclass(frozen=True, slots=True)
class FormalReportMetadata:
    """Immutable mechanical metadata projection consumed by the future Writer."""

    event_id: str
    display_date: str
    country: str
    transit_system_name: str
    location: str | None
    category: str
    em_system_labels: tuple[str, ...]
    source_display: str
    source_url: str
    diagnostics: tuple[FormalMetadataDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "event_id",
            "display_date",
            "country",
            "transit_system_name",
            "category",
            "source_display",
            "source_url",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"FormalReportMetadata requires {field_name}")
        if len(self.display_date) != 10 or self.display_date[4] != "-" or self.display_date[7] != "-":
            raise ValueError("FormalReportMetadata display_date must be YYYY-MM-DD")
        try:
            parsed_date = date.fromisoformat(self.display_date)
        except ValueError as exc:
            raise ValueError("FormalReportMetadata display_date must be YYYY-MM-DD") from exc
        if parsed_date.isoformat() != self.display_date:
            raise ValueError("FormalReportMetadata display_date must be YYYY-MM-DD")
        if self.location is not None and not isinstance(self.location, str):
            raise TypeError("FormalReportMetadata location must be a string or None")
        labels = tuple(self.em_system_labels)
        if any(not isinstance(label, str) or not label.strip() for label in labels):
            raise ValueError("FormalReportMetadata em_system_labels must be non-empty strings")
        if len(labels) != len(set(labels)):
            raise ValueError("FormalReportMetadata em_system_labels must be unique")
        object.__setattr__(self, "em_system_labels", labels)
        diagnostics = tuple(self.diagnostics)
        if any(not isinstance(item, FormalMetadataDiagnostic) for item in diagnostics):
            raise TypeError("FormalReportMetadata diagnostics must be typed")
        object.__setattr__(self, "diagnostics", diagnostics)


@dataclass(frozen=True, slots=True)
class FinalReportBlock:
    """One mechanically assembled Validation-PASS event.

    ``metadata`` remains the exact ReportService projection.  The three prose
    fields are the only values supplied by the Writer/Validator boundary.
    """

    metadata: FormalReportMetadata
    headline: str
    factual_summary: str
    taipei_insight: str

    def __post_init__(self) -> None:
        if not isinstance(self.metadata, FormalReportMetadata):
            raise TypeError("FinalReportBlock requires FormalReportMetadata")
        for field_name in ("headline", "factual_summary", "taipei_insight"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"FinalReportBlock requires nonblank {field_name}")

    @property
    def event_id(self) -> str:
        return self.metadata.event_id

    @property
    def display_date(self) -> str:
        return self.metadata.display_date

    @property
    def country(self) -> str:
        return self.metadata.country

    @property
    def transit_system_name(self) -> str:
        return self.metadata.transit_system_name

    @property
    def location(self) -> str | None:
        return self.metadata.location

    @property
    def category(self) -> str:
        return self.metadata.category

    @property
    def em_system_labels(self) -> tuple[str, ...]:
        return self.metadata.em_system_labels

    @property
    def source_display(self) -> str:
        return self.metadata.source_display

    @property
    def source_url(self) -> str:
        return self.metadata.source_url


@dataclass(frozen=True, slots=True)
class FinalReportSection:
    """A stable category section preserving the Ordering subsequence."""

    category: str
    events: tuple[FinalReportBlock, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.category, str) or not self.category.strip():
            raise ValueError("FinalReportSection requires category")
        events = tuple(self.events)
        if any(not isinstance(event, FinalReportBlock) for event in events):
            raise TypeError("FinalReportSection events must be FinalReportBlock values")
        object.__setattr__(self, "events", events)


@dataclass(frozen=True, slots=True)
class FinalReportArtifact:
    """The authoritative assembled artifact handed to DeliveryService."""

    report_id: str
    artifact_id: str
    artifact_version: str
    events: tuple[FinalReportBlock, ...]
    sections: tuple[FinalReportSection, ...]
    content: str

    def __post_init__(self) -> None:
        for field_name in ("report_id", "artifact_id", "artifact_version", "content"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"FinalReportArtifact requires {field_name}")
        events = tuple(self.events)
        sections = tuple(self.sections)
        if any(not isinstance(event, FinalReportBlock) for event in events):
            raise TypeError("FinalReportArtifact events must be FinalReportBlock values")
        if any(not isinstance(section, FinalReportSection) for section in sections):
            raise TypeError("FinalReportArtifact sections must be FinalReportSection values")
        flattened = tuple(event for section in sections for event in section.events)
        if flattened != events:
            raise ValueError("FinalReportArtifact sections must preserve event order")
        object.__setattr__(self, "events", events)
        object.__setattr__(self, "sections", sections)

    @property
    def event_count(self) -> int:
        return len(self.events)

    @property
    def no_event(self) -> bool:
        return not self.events


class FormalMetadataFailure(RuntimeError):
    """Typed fail-closed error for a formal metadata projection."""

    def __init__(
        self,
        reason: FormalMetadataFailureReason,
        *,
        event_id: str = "",
        candidate_ids: tuple[str, ...] = (),
    ) -> None:
        try:
            reason = FormalMetadataFailureReason(reason)
        except (TypeError, ValueError) as exc:
            raise ValueError("FormalMetadataFailure requires a finite reason") from exc
        if not isinstance(event_id, str):
            raise TypeError("FormalMetadataFailure event_id must be a string")
        candidate_ids = tuple(candidate_ids)
        if any(not isinstance(candidate_id, str) or not candidate_id.strip() for candidate_id in candidate_ids):
            raise ValueError("FormalMetadataFailure candidate_ids must be non-empty strings")
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("FormalMetadataFailure candidate_ids must be unique")
        self.reason = reason
        self.event_id = event_id
        self.candidate_ids = candidate_ids
        super().__init__(f"formal metadata failure: {reason.value}")


class ReportService:
    """Sole mechanical owner of metadata projection and final assembly."""

    def project_formal_metadata(
        self,
        ordered_results: tuple[ReportWorkflowResult, ...],
    ) -> tuple[FormalReportMetadata, ...]:
        """Project the authoritative Ordering output without changing it."""

        if not isinstance(ordered_results, tuple):
            raise FormalMetadataFailure(FormalMetadataFailureReason.STRUCTURAL_INCONSISTENCY)
        if not ordered_results:
            return ()

        seen_event_ids: set[str] = set()
        projected: list[FormalReportMetadata] = []
        for result in ordered_results:
            if not isinstance(result, ReportWorkflowResult):
                raise FormalMetadataFailure(FormalMetadataFailureReason.STRUCTURAL_INCONSISTENCY)
            event_id = result.event_group.event_id
            if event_id in seen_event_ids:
                raise FormalMetadataFailure(
                    FormalMetadataFailureReason.STRUCTURAL_INCONSISTENCY,
                    event_id=event_id,
                )
            seen_event_ids.add(event_id)
            if not result.downstream_eligible:
                raise FormalMetadataFailure(
                    FormalMetadataFailureReason.STRUCTURAL_INCONSISTENCY,
                    event_id=event_id,
                )
            projected.append(self._project_one(result))
        return tuple(projected)

    def assemble_final_report(self, validation_result: Any) -> FinalReportArtifact:
        """Assemble only Validation-PASS prose with exact projected metadata.

        ``ValidationResult`` is imported lazily by callers to keep this owner
        independent from the Validator module.  The method accepts its typed
        public shape (``passed`` containing ``ValidatedReportEvent`` values)
        and performs no semantic filtering or metadata derivation.
        """

        passed = getattr(validation_result, "passed", None)
        if passed is None or not isinstance(passed, tuple):
            raise TypeError("ReportService assembly requires a ValidationResult")
        assembled: list[FinalReportBlock] = []
        for item in passed:
            result = getattr(item, "result", None)
            metadata = getattr(item, "metadata", None)
            block = getattr(item, "block", None)
            if not isinstance(result, ReportWorkflowResult):
                raise TypeError("Validation-PASS item result is invalid")
            if not isinstance(metadata, FormalReportMetadata):
                raise TypeError("Validation-PASS item metadata is invalid")
            event_id = result.event_group.event_id
            if metadata.event_id != event_id:
                raise FormalMetadataFailure(
                    FormalMetadataFailureReason.STRUCTURAL_INCONSISTENCY,
                    event_id=event_id,
                )
            if any(not isinstance(getattr(block, name, None), str) or not getattr(block, name).strip() for name in ("headline", "factual_summary", "taipei_insight")):
                raise ValueError("Validation-PASS item prose is incomplete")
            assembled.append(
                FinalReportBlock(
                    metadata=metadata,
                    headline=block.headline,
                    factual_summary=block.factual_summary,
                    taipei_insight=block.taipei_insight,
                )
            )

        events = tuple(assembled)
        sections_by_category: dict[str, list[FinalReportBlock]] = {}
        category_order: list[str] = []
        for event in events:
            if event.category not in sections_by_category:
                sections_by_category[event.category] = []
                category_order.append(event.category)
            sections_by_category[event.category].append(event)
        sections = tuple(
            FinalReportSection(category, tuple(sections_by_category[category]))
            for category in category_order
        )
        content = self._render_final_content(events, sections)
        identity_payload = {
            "events": [
                {
                    "event_id": event.event_id,
                    "metadata": {
                        "display_date": event.display_date,
                        "country": event.country,
                        "transit_system_name": event.transit_system_name,
                        "location": event.location,
                        "category": event.category,
                        "em_system_labels": list(event.em_system_labels),
                        "source_display": event.source_display,
                        "source_url": event.source_url,
                    },
                    "headline": event.headline,
                    "factual_summary": event.factual_summary,
                    "taipei_insight": event.taipei_insight,
                }
                for event in events
            ],
        }
        digest = hashlib.sha256(
            json.dumps(identity_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return FinalReportArtifact(
            report_id=f"weekly-report-{digest[:16]}",
            artifact_id=f"formal-report-{digest}",
            artifact_version="v1",
            events=events,
            sections=sections,
            content=content,
        )

    def assemble(self, validation_result: Any) -> FinalReportArtifact:
        """Short alias for the final assembly seam."""

        return self.assemble_final_report(validation_result)

    def assemble_report(self, validation_result: Any) -> FinalReportArtifact:
        """Compatibility name for callers describing the artifact as a report."""

        return self.assemble_final_report(validation_result)

    @staticmethod
    def _render_final_content(
        events: tuple[FinalReportBlock, ...],
        sections: tuple[FinalReportSection, ...],
    ) -> str:
        if not events:
            return "本期無符合正式報導條件之事件。"
        lines = ["捷運技術週報", ""]
        for section in sections:
            lines.extend((f"【{section.category}】", ""))
            for event in section.events:
                lines.extend(
                    (
                        f"{event.headline}",
                        f"日期：{event.display_date}",
                        f"國家／地區：{event.country}",
                        f"運輸系統：{event.transit_system_name}",
                    )
                )
                if event.location:
                    lines.append(f"地點：{event.location}")
                if event.em_system_labels:
                    lines.append(f"相關系統：{'、'.join(event.em_system_labels)}")
                lines.extend(
                    (
                        f"事件摘要：{event.factual_summary}",
                        f"臺北捷運局啟示：{event.taipei_insight}",
                        f"來源：{event.source_display}",
                        f"來源網址：{event.source_url}",
                        "",
                    )
                )
        return "\n".join(lines).rstrip() + "\n"

    def _project_one(self, result: ReportWorkflowResult) -> FormalReportMetadata:
        event_group = result.event_group
        event_id = event_group.event_id
        records = result.member_records
        if not isinstance(event_group, EventGroup) or not isinstance(records, tuple):
            self._fail(FormalMetadataFailureReason.STRUCTURAL_INCONSISTENCY, event_id)
        if any(not isinstance(record, EventIdentityRecord) for record in records):
            self._fail(FormalMetadataFailureReason.STRUCTURAL_INCONSISTENCY, event_id)

        member_ids = tuple(record.candidate.candidate_id for record in records)
        if member_ids != event_group.member_candidate_ids:
            self._fail(
                FormalMetadataFailureReason.STRUCTURAL_INCONSISTENCY,
                event_id,
                member_ids,
            )
        canonical_members = tuple(
            record
            for record in records
            if record.candidate.candidate_id == event_group.canonical_candidate_id
        )
        if len(canonical_members) != 1:
            self._fail(
                FormalMetadataFailureReason.INVALID_CANONICAL_MEMBER,
                event_id,
                member_ids,
            )
        canonical_member = canonical_members[0]

        self._validate_upstream_result(result)
        country = self._resolve_required(
            event_id,
            records,
            "country",
            FormalMetadataFailureReason.MISSING_COUNTRY,
            FormalMetadataFailureReason.CONFLICTING_COUNTRY,
        )
        transit_system_name = self._resolve_required(
            event_id,
            records,
            "transit_system_name",
            FormalMetadataFailureReason.MISSING_TRANSIT_SYSTEM_NAME,
            FormalMetadataFailureReason.CONFLICTING_TRANSIT_SYSTEM_NAME,
        )
        location, diagnostics = self._resolve_location(event_id, records)

        controlling_date = canonical_member.temporal.controlling_calendar_date
        if canonical_member.temporal.date_valid is not True or type(controlling_date) is not date:
            self._fail(FormalMetadataFailureReason.INVALID_CANONICAL_DATE, event_id, (canonical_member.candidate.candidate_id,))
        display_date = controlling_date.isoformat()

        source_url = canonical_member.evidence.canonical_source_url
        source_display = self._source_display(event_id, source_url, canonical_member.candidate.candidate_id)

        category_result = result.category_result
        if (
            category_result.category_state is not CategoryState.CATEGORY_ASSIGNED
            or category_result.event_id != event_id
            or not isinstance(category_result.primary_category, str)
            or not category_result.primary_category.strip()
        ):
            self._fail(FormalMetadataFailureReason.STRUCTURAL_INCONSISTENCY, event_id)
        taxonomy_result = result.taxonomy_result
        if (
            taxonomy_result.taxonomy_state is not TaxonomyState.TAXONOMY_EVALUATED
            or taxonomy_result.event_id != event_id
            or any(not isinstance(system, EMSystemId) for system in taxonomy_result.systems)
        ):
            self._fail(FormalMetadataFailureReason.STRUCTURAL_INCONSISTENCY, event_id)
        em_system_labels = tuple(system.display_label for system in taxonomy_result.systems)

        return FormalReportMetadata(
            event_id=event_id,
            display_date=display_date,
            country=country,
            transit_system_name=transit_system_name,
            location=location,
            category=category_result.primary_category,
            em_system_labels=em_system_labels,
            source_display=source_display,
            source_url=source_url,
            diagnostics=diagnostics,
        )

    @staticmethod
    def _validate_upstream_result(result: ReportWorkflowResult) -> None:
        event_id = result.event_group.event_id
        reportability = result.reportability_result
        if (
            reportability is None
            or reportability.event_id != event_id
            or reportability.reportability_state is not ReportabilityState.REPORTABLE
        ):
            raise FormalMetadataFailure(
                FormalMetadataFailureReason.STRUCTURAL_INCONSISTENCY,
                event_id=event_id,
            )
        if result.category_result.event_id != event_id or result.taxonomy_result.event_id != event_id:
            raise FormalMetadataFailure(
                FormalMetadataFailureReason.STRUCTURAL_INCONSISTENCY,
                event_id=event_id,
            )
        if (
            result.category_result.category_state is not CategoryState.CATEGORY_ASSIGNED
            or result.taxonomy_result.taxonomy_state is not TaxonomyState.TAXONOMY_EVALUATED
        ):
            raise FormalMetadataFailure(
                FormalMetadataFailureReason.STRUCTURAL_INCONSISTENCY,
                event_id=event_id,
            )
        for record in result.member_records:
            if (
                record.evidence.state is not EvidenceState.READY
                or record.scope.state is not ScopeState.IN_SCOPE
                or record.temporal.date_valid is not True
            ):
                raise FormalMetadataFailure(
                    FormalMetadataFailureReason.STRUCTURAL_INCONSISTENCY,
                    event_id=event_id,
                    candidate_ids=(record.candidate.candidate_id,),
                )

    @staticmethod
    def _resolve_required(
        event_id: str,
        records: tuple[EventIdentityRecord, ...],
        field_name: str,
        missing_reason: FormalMetadataFailureReason,
        conflict_reason: FormalMetadataFailureReason,
    ) -> str:
        populated: list[tuple[str, str]] = []
        for record in records:
            facts = record.evidence.identity_facts
            value = getattr(facts, field_name, None) if facts is not None else None
            if isinstance(value, str) and value.strip():
                populated.append((record.candidate.candidate_id, value))
        distinct: list[str] = []
        for _, value in populated:
            if value not in distinct:
                distinct.append(value)
        if not distinct:
            raise FormalMetadataFailure(
                missing_reason,
                event_id=event_id,
                candidate_ids=tuple(record.candidate.candidate_id for record in records),
            )
        if len(distinct) > 1:
            raise FormalMetadataFailure(
                conflict_reason,
                event_id=event_id,
                candidate_ids=tuple(candidate_id for candidate_id, _ in populated),
            )
        return distinct[0]

    @staticmethod
    def _resolve_location(
        event_id: str,
        records: tuple[EventIdentityRecord, ...],
    ) -> tuple[str | None, tuple[FormalMetadataDiagnostic, ...]]:
        populated: list[tuple[str, str]] = []
        for record in records:
            facts = record.evidence.identity_facts
            value = getattr(facts, "location", None) if facts is not None else None
            if isinstance(value, str) and value.strip():
                populated.append((record.candidate.candidate_id, value))
        distinct: list[str] = []
        for _, value in populated:
            if value not in distinct:
                distinct.append(value)
        if len(distinct) <= 1:
            return (distinct[0] if distinct else None), ()
        return None, (
            FormalMetadataDiagnostic(
                event_id=event_id,
                field_name="location",
                reason=FormalMetadataDiagnosticReason.CONFLICTING_OPTIONAL_LOCATION,
                candidate_ids=tuple(candidate_id for candidate_id, _ in populated),
            ),
        )

    @staticmethod
    def _source_display(event_id: str, source_url: str, candidate_id: str) -> str:
        if not _valid_exact_http_url(source_url):
            raise FormalMetadataFailure(
                FormalMetadataFailureReason.INVALID_CANONICAL_SOURCE,
                event_id=event_id,
                candidate_ids=(candidate_id,),
            )
        parsed = None
        try:
            parsed = urlparse(source_url)
            hostname = parsed.hostname
            _ = parsed.port
        except (TypeError, ValueError):
            hostname = None
        if parsed is None or parsed.scheme.lower() not in {"http", "https"}:
            hostname = None
        if not hostname:
            raise FormalMetadataFailure(
                FormalMetadataFailureReason.INVALID_CANONICAL_SOURCE,
                event_id=event_id,
                candidate_ids=(candidate_id,),
            )
        return hostname.lower()

    @staticmethod
    def _fail(
        reason: FormalMetadataFailureReason,
        event_id: str,
        candidate_ids: tuple[str, ...] = (),
    ) -> None:
        raise FormalMetadataFailure(reason, event_id=event_id, candidate_ids=candidate_ids)


# Descriptive aliases keep the single ReportService owner discoverable to
# callers that use either "artifact" or "assembly" terminology.
FinalReportEvent = FinalReportBlock
ReportAssembly = FinalReportArtifact
ReportAssemblyResult = FinalReportArtifact


__all__ = [
    "FormalMetadataDiagnostic",
    "FormalMetadataDiagnosticReason",
    "FormalMetadataFailure",
    "FormalMetadataFailureReason",
    "FormalReportMetadata",
    "FinalReportBlock",
    "FinalReportEvent",
    "FinalReportSection",
    "FinalReportArtifact",
    "ReportAssembly",
    "ReportAssemblyResult",
    "ReportService",
]
