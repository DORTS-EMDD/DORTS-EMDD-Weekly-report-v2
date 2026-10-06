from __future__ import annotations

from datetime import date
from dataclasses import replace
from unittest import TestCase

from src.weekly_report.contracts import (
    CanonicalCandidate,
    CategoryId,
    CategoryResult,
    CategoryState,
    EvidenceResult,
    EvidenceState,
    EventDecisionRecord,
    EventGroup,
    EventIdentityFacts,
    EventIdentityRecord,
    EMSystemId,
    ReportabilityEvidenceProvenance,
    ReportabilityReason,
    ReportabilityResult,
    ReportabilityState,
    ReportabilitySupportSpan,
    ScopeResult,
    ScopeState,
    SourceDateKind,
    TaxonomyResult,
    TaxonomySupportSpan,
    TaxonomyState,
    TemporalResult,
)
from src.weekly_report.ordering import Ordering
from src.weekly_report.report_workflow import ReportWorkflowResult


def _event(
    event_id: str,
    canonical_candidate_id: str,
    dates: dict[str, date | str | None],
    *,
    reportability_state: ReportabilityState = ReportabilityState.REPORTABLE,
    category_id: CategoryId = CategoryId.PROCUREMENT,
    taxonomy_systems: tuple[EMSystemId, ...] = (),
    publisher: str = "",
    locations: dict[str, str] | None = None,
) -> ReportWorkflowResult:
    records = []
    for candidate_id, controlling_date in dates.items():
        candidate = CanonicalCandidate(
            candidate_id=candidate_id,
            title=f"title-{candidate_id}",
            url=f"https://example.test/{candidate_id}",
            publisher=publisher,
        )
        records.append(
            EventIdentityRecord(
                candidate=candidate,
                evidence=EvidenceResult(
                    candidate_id,
                    EvidenceState.READY,
                    substantive_content="authoritative content",
                    identity_facts=EventIdentityFacts(
                        location=(locations or {}).get(candidate_id, "")
                    ),
                ),
                scope=ScopeResult(candidate_id, ScopeState.IN_SCOPE),
                temporal=TemporalResult(
                    candidate_id,
                    True,
                    controlling_calendar_date=controlling_date,
                    controlling_date_kind=SourceDateKind.ORIGINAL_PUBLICATION,
                ),
            )
        )
    group = EventGroup(
        event_id,
        tuple(sorted(dates)),
        canonical_candidate_id,
        (),
    )
    category = CategoryResult(
        CategoryState.CATEGORY_ASSIGNED,
        event_id=event_id,
        primary_category_id=category_id,
        primary_category=category_id.display_label,
        classification_reason=f"PRINCIPAL_ACTION_{category_id.value}",
    )
    taxonomy_spans = tuple(
        TaxonomySupportSpan(system_id, canonical_candidate_id, 0, 1)
        for system_id in taxonomy_systems
    )
    taxonomy = TaxonomyResult(
        TaxonomyState.TAXONOMY_EVALUATED,
        event_id=event_id,
        systems=taxonomy_systems,
        support_spans=taxonomy_spans,
    )
    decision = EventDecisionRecord(group, tuple(records), category, taxonomy)
    if reportability_state is ReportabilityState.REPORTABLE:
        reportability = ReportabilityResult(
            event_id,
            ReportabilityState.REPORTABLE,
            None,
            ReportabilityEvidenceProvenance(
                tuple(sorted(dates)),
                (ReportabilitySupportSpan(next(iter(dates)), 0, 1),),
                "fixture reportability result",
            ),
        )
    else:
        reportability = ReportabilityResult(
            event_id,
            ReportabilityState.NOT_REPORTABLE,
            ReportabilityReason.LOW_REPORTABILITY_VALUE,
            ReportabilityEvidenceProvenance(
                tuple(sorted(dates)),
                (),
                "fixture reportability result",
            ),
        )
    return ReportWorkflowResult(decision, reportability)


class OrderingTests(TestCase):
    def test_zero_returns_zero(self):
        self.assertEqual(Ordering().order(()), ())

    def test_singleton_validates_and_preserves_reference(self):
        event = _event("E1", "C1", {"C1": date(2026, 9, 18)})
        result = Ordering().order((event,))
        self.assertEqual(result, (event,))
        self.assertIs(result[0], event)

    def test_singleton_still_requires_canonical_date(self):
        event = _event("E1", "C1", {"C1": None})
        with self.assertRaises(ValueError):
            Ordering().order((event,))

    def test_orders_newer_date_then_exact_event_id_and_preserves_all_references(self):
        older = _event("E2", "C2", {"C2": date(2026, 9, 10)})
        newer = _event("E1", "C1", {"C1": date(2026, 9, 18)})
        same_date_high = _event("E9", "C9", {"C9": date(2026, 9, 18)})
        ordered = Ordering().order((older, same_date_high, newer))
        self.assertEqual(tuple(item.event_group.event_id for item in ordered), ("E1", "E9", "E2"))
        self.assertEqual(len(ordered), 3)
        self.assertTrue(all(any(item is original for original in (older, newer, same_date_high)) for item in ordered))

    def test_canonical_member_date_is_the_only_date_used(self):
        canonical_late = _event(
            "E1",
            "C2",
            {"C1": date(2026, 9, 30), "C2": date(2026, 9, 10)},
        )
        canonical_early = _event("E2", "C3", {"C3": date(2026, 9, 11)})
        ordered = Ordering().order((canonical_early, canonical_late))
        self.assertEqual(tuple(item.event_group.event_id for item in ordered), ("E2", "E1"))

    def test_input_permutation_and_repeated_calls_are_deterministic(self):
        events = (
            _event("E3", "C3", {"C3": date(2026, 9, 17)}),
            _event("E1", "C1", {"C1": date(2026, 9, 17)}),
            _event("E2", "C2", {"C2": date(2026, 9, 18)}),
        )
        expected = ("E2", "E1", "E3")
        self.assertEqual(tuple(item.event_group.event_id for item in Ordering().order(events)), expected)
        self.assertEqual(tuple(item.event_group.event_id for item in Ordering().order(tuple(reversed(events)))), expected)

    def test_wrong_container_and_item_types_fail_closed(self):
        with self.assertRaises(TypeError):
            Ordering().order([])
        with self.assertRaises(TypeError):
            Ordering().order((object(),))

    def test_ineligible_results_fail_closed(self):
        event = _event(
            "E1",
            "C1",
            {"C1": date(2026, 9, 18)},
            reportability_state=ReportabilityState.NOT_REPORTABLE,
        )
        with self.assertRaises(ValueError):
            Ordering().order((event,))
        with self.assertRaises(ValueError):
            Ordering().order((replace(event, reportability_result=None),))

    def test_duplicate_event_ids_are_rejected_without_deduplication(self):
        first = _event("E1", "C1", {"C1": date(2026, 9, 18)})
        second = _event("E1", "C2", {"C2": date(2026, 9, 17)})
        with self.assertRaises(ValueError):
            Ordering().order((first, second))

    def test_missing_or_duplicate_canonical_members_are_rejected(self):
        missing = _event("E1", "C1", {"C1": date(2026, 9, 18)})
        object.__setattr__(missing.event_group, "canonical_candidate_id", "missing")
        with self.assertRaises(ValueError):
            Ordering().order((missing,))

        duplicate = _event("E2", "C2", {"C2": date(2026, 9, 18)})
        object.__setattr__(
            duplicate.decision,
            "member_records",
            duplicate.member_records + (duplicate.member_records[0],),
        )
        with self.assertRaises(ValueError):
            Ordering().order((duplicate,))

    def test_category_and_taxonomy_do_not_add_comparators(self):
        first = _event("E1", "C1", {"C1": date(2026, 9, 17)})
        second = _event("E2", "C2", {"C2": date(2026, 9, 18)})
        self.assertEqual(
            tuple(item.event_group.event_id for item in Ordering().order((first, second))),
            ("E2", "E1"),
        )

    def test_category_difference_does_not_change_order(self):
        first = _event("E1", "C1", {"C1": date(2026, 9, 18)}, category_id=CategoryId.INCIDENT)
        second = _event("E2", "C2", {"C2": date(2026, 9, 17)}, category_id=CategoryId.TECHNICAL_DEVELOPMENT)
        self.assertEqual(
            tuple(item.event_group.event_id for item in Ordering().order((second, first))),
            ("E1", "E2"),
        )

    def test_taxonomy_difference_does_not_change_order(self):
        first = _event(
            "E1", "C1", {"C1": date(2026, 9, 18)}, taxonomy_systems=(EMSystemId.POWER_SUPPLY,)
        )
        second = _event(
            "E2", "C2", {"C2": date(2026, 9, 17)}, taxonomy_systems=(EMSystemId.SIGNALLING,)
        )
        self.assertEqual(
            tuple(item.event_group.event_id for item in Ordering().order((second, first))),
            ("E1", "E2"),
        )

    def test_geography_does_not_change_exact_event_id_tie_break(self):
        first = _event(
            "E2",
            "C2",
            {"C2": date(2026, 9, 18)},
            locations={"C2": "Amsterdam"},
        )
        second = _event(
            "E1",
            "C1",
            {"C1": date(2026, 9, 18)},
            locations={"C1": "Zurich"},
        )
        first_location = first.member_records[0].evidence.identity_facts.location
        second_location = second.member_records[0].evidence.identity_facts.location
        self.assertNotEqual(first_location, second_location)
        self.assertEqual(
            tuple(item.event_group.event_id for item in Ordering().order((first, second))),
            ("E1", "E2"),
        )

    def test_invalid_canonical_date_type_fails_closed(self):
        event = _event("E1", "C1", {"C1": "2026-09-18"})
        with self.assertRaises(ValueError):
            Ordering().order((event,))

    def test_large_population_preserves_all_references_without_top_n(self):
        events = tuple(
            _event(f"E{index:02d}", f"C{index:02d}", {f"C{index:02d}": date(2026, 9, index + 1)})
            for index in range(12)
        )
        ordered = Ordering().order(tuple(reversed(events)))
        self.assertEqual(len(ordered), 12)
        self.assertEqual(
            tuple(item.event_group.event_id for item in ordered),
            tuple(f"E{index:02d}" for index in range(11, -1, -1)),
        )
        self.assertEqual({id(item) for item in ordered}, {id(item) for item in events})

    def test_member_group_membership_mismatch_fails_closed(self):
        event = _event(
            "E1", "C1", {"C1": date(2026, 9, 18), "C2": date(2026, 9, 17)}
        )
        object.__setattr__(event.decision, "member_records", (event.member_records[0],))
        with self.assertRaises(ValueError):
            Ordering().order((event,))


if __name__ == "__main__":
    import unittest

    unittest.main()
