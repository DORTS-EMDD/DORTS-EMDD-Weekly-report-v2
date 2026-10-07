"""Mechanical formal metadata projection for the pre-Writer boundary.

``ReportService`` consumes the already ordered, reportable workflow results.
It does not select events, infer metadata, or assemble report prose.  The
upstream Evidence, Temporal, Category, Taxonomy, Reportability, and Ordering
results remain the authoritative decisions; the values below are an immutable
downstream display projection of those decisions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
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
    """Sole mechanical owner of the formal metadata projection seam."""

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


__all__ = [
    "FormalMetadataDiagnostic",
    "FormalMetadataDiagnosticReason",
    "FormalMetadataFailure",
    "FormalMetadataFailureReason",
    "FormalReportMetadata",
    "ReportService",
]
