from __future__ import annotations

from dataclasses import replace
from datetime import date
from unittest import TestCase

from src.weekly_report.contracts import (
    CategoryId,
    CategoryResult,
    CategoryState,
    EMSystemId,
    EventDecisionRecord,
    EventGroup,
    EventIdentityFacts,
    EventIdentityRecord,
    EvidenceResult,
    EvidenceState,
    IdentityMetadataSupport,
    ReportabilityEvidenceProvenance,
    ReportabilityResult,
    ReportabilityState,
    ReportabilitySupportSpan,
    ScopeResult,
    ScopeState,
    TaxonomyResult,
    TaxonomyState,
    TaxonomySupportSpan,
    TemporalResult,
)
from src.weekly_report.contracts import CanonicalCandidate
from src.weekly_report.report_service import (
    FormalMetadataDiagnosticReason,
    FormalMetadataFailure,
    FormalMetadataFailureReason,
    ReportService,
)
from src.weekly_report.report_workflow import ReportWorkflowResult


def _record(
    candidate_id: str,
    *,
    country: str | None = "Taiwan",
    transit_system_name: str | None = "Metro",
    location: str | None = "Taipei",
    controlling_date: date | None = date(2026, 9, 15),
    source_url: str = "https://WWW.News.Example.COM:8443/path/article?id=5#fragment",
) -> EventIdentityRecord:
    values = [value for value in (country, transit_system_name, location) if value]
    body = " ".join(values) or "authoritative body"
    support = []
    for field_name, value in (
        ("country", country),
        ("transit_system_name", transit_system_name),
        ("location", location),
    ):
        if value:
            start = body.index(value)
            support.append(IdentityMetadataSupport(field_name, start, start + len(value)))
    facts = EventIdentityFacts(
        country=country,
        transit_system_name=transit_system_name,
        location=location or "",
        metadata_support=tuple(support),
    )
    evidence = EvidenceResult(
        candidate_id,
        EvidenceState.READY,
        canonical_source_url=source_url,
        substantive_content=body,
        identity_facts=facts,
    )
    temporal = TemporalResult(
        candidate_id,
        True,
        controlling_calendar_date=controlling_date,
    )
    return EventIdentityRecord(
        CanonicalCandidate(candidate_id, f"Candidate {candidate_id}", f"https://candidate.test/{candidate_id}"),
        evidence,
        ScopeResult(candidate_id, ScopeState.IN_SCOPE),
        temporal,
    )


def _workflow_result(
    event_id: str = "E1",
    *,
    records: tuple[EventIdentityRecord, ...] | None = None,
    canonical_candidate_id: str | None = None,
    reportable: bool = True,
    systems: tuple[EMSystemId, ...] = (EMSystemId.SIGNALLING,),
) -> ReportWorkflowResult:
    records = records or (_record("C1"),)
    member_ids = tuple(record.candidate.candidate_id for record in records)
    canonical_candidate_id = canonical_candidate_id or member_ids[0]
    group = EventGroup(event_id, member_ids, canonical_candidate_id, ())
    category = CategoryResult(
        CategoryState.CATEGORY_ASSIGNED,
        event_id=event_id,
        primary_category_id=CategoryId.PROCUREMENT,
        primary_category=CategoryId.PROCUREMENT.display_label,
        classification_reason="PRINCIPAL_ACTION_PROCUREMENT",
    )
    taxonomy_support = ()
    if systems:
        taxonomy_support = tuple(
            TaxonomySupportSpan(system, member_ids[0], index, index + 1)
            for index, system in enumerate(systems)
        )
    taxonomy = TaxonomyResult(
        TaxonomyState.TAXONOMY_EVALUATED,
        event_id=event_id,
        systems=systems,
        support_spans=taxonomy_support,
    )
    decision = EventDecisionRecord(group, records, category, taxonomy)
    if not reportable:
        reportability = ReportabilityResult(
            event_id,
            ReportabilityState.NOT_REPORTABLE,
            "LOW_REPORTABILITY_VALUE",
            ReportabilityEvidenceProvenance(member_ids, (), "fixture"),
        )
    else:
        reportability = ReportabilityResult(
            event_id,
            ReportabilityState.REPORTABLE,
            None,
            ReportabilityEvidenceProvenance(
                member_ids,
                (ReportabilitySupportSpan(member_ids[0], 0, 1),),
                "fixture",
            ),
        )
    return ReportWorkflowResult(decision, reportability)


class ReportServiceTests(TestCase):
    def setUp(self) -> None:
        self.service = ReportService()

    def test_zero_input_returns_zero_tuple(self) -> None:
        self.assertEqual(self.service.project_formal_metadata(()), ())

    def test_projects_authoritative_fields_and_canonical_source(self) -> None:
        result = self.service.project_formal_metadata((_workflow_result(),))[0]
        self.assertEqual(result.event_id, "E1")
        self.assertEqual(result.display_date, "2026-09-15")
        self.assertEqual(result.country, "Taiwan")
        self.assertEqual(result.transit_system_name, "Metro")
        self.assertEqual(result.location, "Taipei")
        self.assertEqual(result.category, "採購事件")
        self.assertEqual(result.em_system_labels, ("號誌",))
        self.assertEqual(result.source_display, "www.news.example.com")
        self.assertEqual(
            result.source_url,
            "https://WWW.News.Example.COM:8443/path/article?id=5#fragment",
        )

    def test_required_metadata_collapses_exact_values_and_ignores_missing_members(self) -> None:
        records = (
            _record("C1", country=None, transit_system_name=None, location=None),
            _record("C2"),
        )
        result = self.service.project_formal_metadata(
            (_workflow_result(records=records, canonical_candidate_id="C1"),)
        )[0]
        self.assertEqual(result.country, "Taiwan")
        self.assertEqual(result.transit_system_name, "Metro")

    def test_repeated_identical_country_projects_exact_value(self) -> None:
        records = (_record("C1", country="Taiwan"), _record("C2", country="Taiwan"))
        result = self.service.project_formal_metadata(
            (_workflow_result(records=records),)
        )[0]
        self.assertEqual(result.country, "Taiwan")

    def test_repeated_identical_transit_system_projects_exact_value(self) -> None:
        records = (
            _record("C1", transit_system_name="Metro Alpha"),
            _record("C2", transit_system_name="Metro Alpha"),
        )
        result = self.service.project_formal_metadata(
            (_workflow_result(records=records),)
        )[0]
        self.assertEqual(result.transit_system_name, "Metro Alpha")

    def test_required_country_conflict_fails_without_canonical_preference(self) -> None:
        records = (_record("C1", country="Taiwan"), _record("C2", country="Japan"))
        with self.assertRaises(FormalMetadataFailure) as context:
            self.service.project_formal_metadata(
                (_workflow_result(records=records, canonical_candidate_id="C1"),)
            )
        self.assertEqual(context.exception.reason, FormalMetadataFailureReason.CONFLICTING_COUNTRY)
        self.assertEqual(context.exception.candidate_ids, ("C1", "C2"))

    def test_missing_system_fails(self) -> None:
        with self.assertRaises(FormalMetadataFailure) as context:
            self.service.project_formal_metadata(
                (_workflow_result(records=(_record("C1", transit_system_name=None),)),)
            )
        self.assertEqual(
            context.exception.reason,
            FormalMetadataFailureReason.MISSING_TRANSIT_SYSTEM_NAME,
        )

    def test_transit_system_conflict_fails_without_canonical_preference(self) -> None:
        records = (
            _record("C1", transit_system_name="Metro Alpha"),
            _record("C2", transit_system_name="Metro Beta"),
        )
        with self.assertRaises(FormalMetadataFailure) as context:
            self.service.project_formal_metadata(
                (_workflow_result(records=records, canonical_candidate_id="C1"),)
            )
        self.assertEqual(
            context.exception.reason,
            FormalMetadataFailureReason.CONFLICTING_TRANSIT_SYSTEM_NAME,
        )
        self.assertEqual(context.exception.candidate_ids, ("C1", "C2"))

    def test_location_conflict_is_omitted_with_diagnostic(self) -> None:
        records = (_record("C1", location="Taipei"), _record("C2", location="Kaohsiung"))
        result = self.service.project_formal_metadata(
            (_workflow_result(records=records),)
        )[0]
        self.assertIsNone(result.location)
        self.assertEqual(len(result.diagnostics), 1)
        self.assertEqual(
            result.diagnostics[0].reason,
            FormalMetadataDiagnosticReason.CONFLICTING_OPTIONAL_LOCATION,
        )
        self.assertEqual(result.diagnostics[0].candidate_ids, ("C1", "C2"))

    def test_all_missing_location_is_none_without_diagnostic(self) -> None:
        records = (_record("C1", location=None), _record("C2", location=None))
        result = self.service.project_formal_metadata(
            (_workflow_result(records=records),)
        )[0]
        self.assertIsNone(result.location)
        self.assertEqual(result.diagnostics, ())

    def test_repeated_identical_location_projects_exact_value(self) -> None:
        records = (_record("C1", location="Taipei"), _record("C2", location="Taipei"))
        result = self.service.project_formal_metadata(
            (_workflow_result(records=records),)
        )[0]
        self.assertEqual(result.location, "Taipei")
        self.assertEqual(result.diagnostics, ())

    def test_canonical_member_controls_date_and_source(self) -> None:
        records = (
            _record("C1", controlling_date=date(2026, 9, 1), source_url="https://first.test/a"),
            _record("C2", controlling_date=date(2026, 9, 15), source_url="https://SECOND.Test/b"),
        )
        result = self.service.project_formal_metadata(
            (_workflow_result(records=records, canonical_candidate_id="C2"),)
        )[0]
        self.assertEqual(result.display_date, "2026-09-15")
        self.assertEqual(result.source_display, "second.test")
        self.assertEqual(result.source_url, "https://SECOND.Test/b")

    def test_missing_canonical_date_does_not_fallback_to_alternate_member(self) -> None:
        records = (
            _record("C1", controlling_date=date(2026, 9, 1)),
            _record("C2", controlling_date=None),
        )
        with self.assertRaises(FormalMetadataFailure) as context:
            self.service.project_formal_metadata(
                (_workflow_result(records=records, canonical_candidate_id="C2"),)
            )
        self.assertEqual(context.exception.reason, FormalMetadataFailureReason.INVALID_CANONICAL_DATE)
        self.assertEqual(context.exception.candidate_ids, ("C2",))

    def test_invalid_source_does_not_fallback_to_candidate_url(self) -> None:
        records = (_record("C1", source_url="not-a-url"),)
        with self.assertRaises(FormalMetadataFailure) as context:
            self.service.project_formal_metadata((_workflow_result(records=records),))
        self.assertEqual(
            context.exception.reason,
            FormalMetadataFailureReason.INVALID_CANONICAL_SOURCE,
        )

    def test_invalid_source_whitespace_does_not_fallback_to_candidate_url(self) -> None:
        for source_url in (
            "https://bad host.example/news",
            "https://bad\thost.example/news",
            " https://valid.example/news",
            "https://valid.example/news\n",
        ):
            with self.subTest(source_url=repr(source_url)):
                records = (_record("C1", source_url=source_url),)
                with self.assertRaises(FormalMetadataFailure) as context:
                    self.service.project_formal_metadata((_workflow_result(records=records),))
                self.assertEqual(
                    context.exception.reason,
                    FormalMetadataFailureReason.INVALID_CANONICAL_SOURCE,
                )

    def test_structurally_inconsistent_category_fails_closed(self) -> None:
        valid = _workflow_result()
        inconsistent_category = CategoryResult.not_evaluated(event_id=valid.event_group.event_id)
        inconsistent_decision = replace(valid.decision, category_result=inconsistent_category)
        inconsistent = ReportWorkflowResult(inconsistent_decision, valid.reportability_result)
        with self.assertRaises(FormalMetadataFailure) as context:
            self.service.project_formal_metadata((inconsistent,))
        self.assertEqual(
            context.exception.reason,
            FormalMetadataFailureReason.STRUCTURAL_INCONSISTENCY,
        )

    def test_multiple_taxonomy_systems_preserve_canonical_labels_and_order(self) -> None:
        result = self.service.project_formal_metadata(
            (_workflow_result(systems=(EMSystemId.POWER_SUPPLY, EMSystemId.SIGNALLING)),)
        )[0]
        self.assertEqual(
            result.em_system_labels,
            (EMSystemId.SIGNALLING.display_label, EMSystemId.POWER_SUPPLY.display_label),
        )

    def test_evaluated_empty_taxonomy_projects_empty_labels(self) -> None:
        result = self.service.project_formal_metadata(
            (_workflow_result(systems=()),)
        )[0]
        self.assertEqual(result.em_system_labels, ())

    def test_three_event_projection_preserves_order_and_cardinality(self) -> None:
        ordered = (
            _workflow_result("E3", records=(_record("C3"),)),
            _workflow_result("E1", records=(_record("C1"),)),
            _workflow_result("E2", records=(_record("C2"),)),
        )
        projected = self.service.project_formal_metadata(ordered)
        self.assertEqual(tuple(item.event_id for item in projected), ("E3", "E1", "E2"))
        self.assertEqual(len(projected), len(ordered))

    def test_projection_rejects_non_tuple_container(self) -> None:
        with self.assertRaises(FormalMetadataFailure) as context:
            self.service.project_formal_metadata([_workflow_result()])
        self.assertEqual(
            context.exception.reason,
            FormalMetadataFailureReason.STRUCTURAL_INCONSISTENCY,
        )

    def test_projection_rejects_wrong_item_type(self) -> None:
        with self.assertRaises(FormalMetadataFailure) as context:
            self.service.project_formal_metadata((object(),))
        self.assertEqual(
            context.exception.reason,
            FormalMetadataFailureReason.STRUCTURAL_INCONSISTENCY,
        )

    def test_projection_rejects_duplicate_event_ids(self) -> None:
        first = _workflow_result("E1", records=(_record("C1"),))
        second = _workflow_result("E1", records=(_record("C2"),))
        with self.assertRaises(FormalMetadataFailure) as context:
            self.service.project_formal_metadata((first, second))
        self.assertEqual(
            context.exception.reason,
            FormalMetadataFailureReason.STRUCTURAL_INCONSISTENCY,
        )

    def test_non_reportable_input_fails_closed(self) -> None:
        with self.assertRaises(FormalMetadataFailure) as context:
            self.service.project_formal_metadata(
                (_workflow_result(reportable=False),)
            )
        self.assertEqual(context.exception.reason, FormalMetadataFailureReason.STRUCTURAL_INCONSISTENCY)

    def test_required_failure_does_not_return_partial_projection(self) -> None:
        valid = _workflow_result("E1")
        invalid = _workflow_result("E2", records=(_record("C2", country=None),))
        with self.assertRaises(FormalMetadataFailure) as context:
            self.service.project_formal_metadata((valid, invalid))
        self.assertEqual(context.exception.event_id, "E2")
        self.assertEqual(context.exception.reason, FormalMetadataFailureReason.MISSING_COUNTRY)


if __name__ == "__main__":
    import unittest

    unittest.main()
