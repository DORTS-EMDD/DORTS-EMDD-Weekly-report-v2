"""Deterministic Candidate-stage Temporal owner."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, datetime
from typing import Any

from .contracts import (
    ScopeResult,
    ScopeState,
    SourceDateFact,
    SourceDateKind,
    TemporalDiagnostic,
    TemporalResult,
)


_CONTROLLING_KINDS = {
    SourceDateKind.ORIGINAL_PUBLICATION,
    SourceDateKind.NOTICE_ISSUED,
    SourceDateKind.NOTICE_PUBLISHED,
}
_FORMAL_NOTICE_SOURCE_TYPES = {
    "award",
    "award_notice",
    "formal_notice",
    "government_notice",
    "government_operator_notice",
    "operator_notice",
    "procurement",
    "procurement_notice",
    "tender",
    "tender_notice",
}
_UNKNOWN_SOURCE_TYPES = {"", "web_source"}


def _calendar_date(value: object) -> date | None:
    """Parse a source-expressed calendar date without timezone conversion."""

    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = str(value or "").strip()
    if not raw:
        return None
    if len(raw) == 10:
        try:
            return date.fromisoformat(raw)
        except ValueError:
            return None
    normalised = raw[:-1] + "+00:00" if raw.endswith(("Z", "z")) else raw
    try:
        return datetime.fromisoformat(normalised).date()
    except ValueError:
        # Permit a source to retain a named timezone suffix for provenance
        # while parsing the ISO local date/time portion without applying it.
        if "[" in normalised and normalised.endswith("]"):
            try:
                return datetime.fromisoformat(normalised.split("[", 1)[0]).date()
            except ValueError:
                pass
        return None


def _coerce_fact(value: SourceDateFact | Mapping[str, Any]) -> SourceDateFact:
    if isinstance(value, SourceDateFact):
        return value
    if isinstance(value, Mapping):
        return SourceDateFact.from_mapping(value)
    raise TypeError("source_date_facts must contain SourceDateFact or mappings")


def _coerce_kind(value: SourceDateKind | str) -> SourceDateKind | None:
    try:
        return SourceDateKind(value)
    except (TypeError, ValueError):
        return None


class TemporalRule:
    """The sole authoritative owner of DATE_VALID and Temporal diagnostics."""

    def evaluate(
        self,
        candidate_id: str,
        source_date_facts: Iterable[SourceDateFact | Mapping[str, Any]],
        period_start: date | str,
        period_end: date | str,
        *,
        source_type: str = "",
        discovery_published_at: str = "",
        scope_result: ScopeResult | None = None,
    ) -> TemporalResult:
        """Evaluate inclusive report-period eligibility from source facts only."""

        if scope_result is not None and scope_result.state is not ScopeState.IN_SCOPE:
            raise ValueError("TemporalRule requires an IN_SCOPE ScopeResult")
        start = self._required_calendar_date(period_start, "period_start")
        end = self._required_calendar_date(period_end, "period_end")
        if start > end:
            raise ValueError("period_start must not be after period_end")

        facts = tuple(_coerce_fact(value) for value in source_date_facts)
        if not facts:
            diagnostic = (
                TemporalDiagnostic.DATE_PROVENANCE_INVALID
                if str(discovery_published_at or "").strip()
                else TemporalDiagnostic.DATE_MISSING
            )
            return self._invalid(candidate_id, diagnostic, source_type=source_type)

        valid_facts: list[tuple[SourceDateFact, SourceDateKind]] = []
        invalid_provenance = False
        for fact in facts:
            kind = _coerce_kind(fact.date_kind)
            if (
                not str(fact.raw_date_value or "").strip()
                or kind is None
                or fact.principal_document_association != candidate_id
                or not str(fact.source_node_or_field_provenance or "").strip()
            ):
                invalid_provenance = True
                continue
            valid_facts.append((fact, kind))

        if not valid_facts:
            return self._invalid(
                candidate_id,
                TemporalDiagnostic.DATE_PROVENANCE_INVALID,
                source_type=source_type,
            )

        controlling = self._controlling_facts(valid_facts, source_type)
        if not controlling:
            return self._invalid(
                candidate_id,
                TemporalDiagnostic.DATE_PROVENANCE_INVALID,
                source_type=source_type,
            )

        parsed: list[tuple[SourceDateFact, SourceDateKind, date]] = []
        for fact, kind in controlling:
            parsed_date = _calendar_date(fact.raw_date_value)
            if parsed_date is None:
                return self._invalid(
                    candidate_id,
                    TemporalDiagnostic.DATE_UNPARSEABLE,
                    source_type=source_type,
                )
            parsed.append((fact, kind, parsed_date))

        controlling_dates = {item[2] for item in parsed}
        if len(controlling_dates) > 1:
            return self._invalid(
                candidate_id,
                TemporalDiagnostic.DATE_CONFLICT,
                source_type=source_type,
                extra={
                    "controlling_date_facts": [
                        {
                            "raw_date_value": fact.raw_date_value,
                            "date_kind": kind.value,
                            "calendar_date": parsed_date.isoformat(),
                        }
                        for fact, kind, parsed_date in parsed
                    ]
                },
            )

        selected_fact, selected_kind, selected_date = parsed[0]
        provenance = {
            "source_type": source_type,
            "controlling_raw_date_value": selected_fact.raw_date_value,
            "controlling_date_kind": selected_kind.value,
            "controlling_calendar_date": selected_date.isoformat(),
            "source_node_or_field_provenance": selected_fact.source_node_or_field_provenance,
            "explicit_timezone_or_offset": selected_fact.explicit_timezone_or_offset,
            "ignored_non_controlling_facts": [
                {
                    "raw_date_value": fact.raw_date_value,
                    "date_kind": kind.value,
                }
                for fact, kind in valid_facts
                if (fact, kind) not in controlling
            ],
        }
        if invalid_provenance:
            provenance["invalid_non_controlling_facts_present"] = True
        if start <= selected_date <= end:
            return TemporalResult(
                candidate_id=candidate_id,
                date_valid=True,
                diagnostic=TemporalDiagnostic.NONE,
                controlling_calendar_date=selected_date,
                controlling_date_kind=selected_kind,
                provenance=provenance,
            )
        return TemporalResult(
            candidate_id=candidate_id,
            date_valid=False,
            diagnostic=TemporalDiagnostic.OUT_OF_RANGE,
            controlling_calendar_date=selected_date,
            controlling_date_kind=selected_kind,
            provenance=provenance,
        )

    check = evaluate

    @staticmethod
    def _required_calendar_date(value: date | str, name: str) -> date:
        parsed = _calendar_date(value)
        if parsed is None:
            raise ValueError(f"{name} must be an ISO calendar date")
        return parsed

    @staticmethod
    def _controlling_facts(
        facts: list[tuple[SourceDateFact, SourceDateKind]],
        source_type: str,
    ) -> list[tuple[SourceDateFact, SourceDateKind]]:
        by_kind = {kind: [item for item in facts if item[1] is kind] for kind in _CONTROLLING_KINDS}
        normalised_source_type = "_".join(
            str(source_type or "").casefold().replace("-", "_").replace("/", "_").split()
        )
        if normalised_source_type in _FORMAL_NOTICE_SOURCE_TYPES:
            if by_kind[SourceDateKind.NOTICE_PUBLISHED]:
                return by_kind[SourceDateKind.NOTICE_PUBLISHED]
            if by_kind[SourceDateKind.NOTICE_ISSUED]:
                return by_kind[SourceDateKind.NOTICE_ISSUED]
            return by_kind[SourceDateKind.ORIGINAL_PUBLICATION]
        if normalised_source_type in _UNKNOWN_SOURCE_TYPES:
            # Existing callers may not yet carry a canonical source type.  In
            # that limited case, prefer an original publication when present;
            # otherwise retain compatibility with a single notice fact.
            if by_kind[SourceDateKind.ORIGINAL_PUBLICATION]:
                return by_kind[SourceDateKind.ORIGINAL_PUBLICATION]
            if by_kind[SourceDateKind.NOTICE_PUBLISHED]:
                return by_kind[SourceDateKind.NOTICE_PUBLISHED]
            return by_kind[SourceDateKind.NOTICE_ISSUED]
        # Explicit non-notice source types (article, bulletin, press release,
        # project release, and future canonical equivalents) are controlled by
        # their original publication fact.  Notice-like facts cannot override
        # that source type, and cannot stand in for a missing publication.
        return by_kind[SourceDateKind.ORIGINAL_PUBLICATION]

    @staticmethod
    def _invalid(
        candidate_id: str,
        diagnostic: TemporalDiagnostic,
        *,
        source_type: str,
        extra: Mapping[str, Any] | None = None,
    ) -> TemporalResult:
        provenance = {"source_type": source_type}
        if extra:
            provenance.update(extra)
        return TemporalResult(
            candidate_id=candidate_id,
            date_valid=False,
            diagnostic=diagnostic,
            provenance=provenance,
        )


__all__ = ["TemporalRule"]
