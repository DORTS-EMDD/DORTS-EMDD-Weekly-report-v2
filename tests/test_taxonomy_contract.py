"""Owner-level tests for the typed E&M Taxonomy contract."""

from dataclasses import FrozenInstanceError
from unittest import TestCase

from src.weekly_report.contracts import (
    EM_SYSTEM_DISPLAY_LABELS,
    EMSystemId,
    TaxonomyConflictEvidenceProvenance,
    TaxonomyInsufficientEvidenceProvenance,
    TaxonomyResolutionReason,
    TaxonomyResult,
    TaxonomyState,
    TaxonomySupportSpan,
    canonical_em_system_ids,
)


def _span(
    system_id: EMSystemId,
    *,
    candidate_id: str = "C1",
    start: int = 0,
    end: int = 4,
) -> TaxonomySupportSpan:
    return TaxonomySupportSpan(
        system_id=system_id,
        candidate_id=candidate_id,
        start=start,
        end=end,
    )


def _insufficient_provenance(
    member_candidate_ids: tuple[str, ...] = ("C1", "C2"),
    diagnostic: str = "No member evidence establishes a supported system.",
) -> TaxonomyInsufficientEvidenceProvenance:
    return TaxonomyInsufficientEvidenceProvenance(
        member_candidate_ids=member_candidate_ids,
        diagnostic=diagnostic,
    )


def _conflict_provenance() -> TaxonomyConflictEvidenceProvenance:
    return TaxonomyConflictEvidenceProvenance(
        conflict_spans=(
            _span(EMSystemId.SIGNALLING, candidate_id="C1"),
            _span(EMSystemId.POWER_SUPPLY, candidate_id="C2"),
        )
    )


class TaxonomyContractTests(TestCase):
    def test_registry_has_exactly_seven_systems_and_exact_labels(self):
        expected = {
            EMSystemId.ROLLING_STOCK: "電聯車",
            EMSystemId.SIGNALLING: "號誌",
            EMSystemId.POWER_SUPPLY: "供電",
            EMSystemId.COMMUNICATIONS: "通訊",
            EMSystemId.AUTOMATIC_FARE_COLLECTION: "自動收費",
            EMSystemId.DEPOT_MAINTENANCE_EQUIPMENT: "機廠維修設備",
            EMSystemId.PLATFORM_SCREEN_DOORS: "月臺門",
        }
        self.assertEqual(len(EMSystemId), 7)
        self.assertEqual(
            {system.name: system.value for system in EMSystemId},
            {
                "ROLLING_STOCK": "ROLLING_STOCK",
                "SIGNALLING": "SIGNALLING",
                "POWER_SUPPLY": "POWER_SUPPLY",
                "COMMUNICATIONS": "COMMUNICATIONS",
                "AUTOMATIC_FARE_COLLECTION": "AUTOMATIC_FARE_COLLECTION",
                "DEPOT_MAINTENANCE_EQUIPMENT": "DEPOT_MAINTENANCE_EQUIPMENT",
                "PLATFORM_SCREEN_DOORS": "PLATFORM_SCREEN_DOORS",
            },
        )
        self.assertEqual(dict(EM_SYSTEM_DISPLAY_LABELS), expected)
        self.assertEqual({system.display_label for system in EMSystemId}, set(expected.values()))

    def test_taxonomy_enum_values_are_exact_and_persistable(self):
        self.assertEqual(len(TaxonomyState), 3)
        self.assertEqual(
            {state.name: state.value for state in TaxonomyState},
            {
                "TAXONOMY_EVALUATED": "TAXONOMY_EVALUATED",
                "TAXONOMY_UNRESOLVED": "TAXONOMY_UNRESOLVED",
                "NOT_EVALUATED": "NOT_EVALUATED",
            },
        )
        self.assertEqual(len(TaxonomyResolutionReason), 2)
        self.assertEqual(
            {reason.name: reason.value for reason in TaxonomyResolutionReason},
            {
                "INSUFFICIENT_SYSTEM_EVIDENCE": "INSUFFICIENT_SYSTEM_EVIDENCE",
                "CONFLICTING_SYSTEM_EVIDENCE": "CONFLICTING_SYSTEM_EVIDENCE",
            },
        )

    def test_registry_order_is_the_canonical_order(self):
        self.assertEqual(
            canonical_em_system_ids(),
            (
                EMSystemId.ROLLING_STOCK,
                EMSystemId.SIGNALLING,
                EMSystemId.POWER_SUPPLY,
                EMSystemId.COMMUNICATIONS,
                EMSystemId.AUTOMATIC_FARE_COLLECTION,
                EMSystemId.DEPOT_MAINTENANCE_EQUIPMENT,
                EMSystemId.PLATFORM_SCREEN_DOORS,
            ),
        )

    def test_evaluated_one_system_requires_system_support(self):
        result = TaxonomyResult(
            taxonomy_state=TaxonomyState.TAXONOMY_EVALUATED,
            event_id="E1",
            systems=[EMSystemId.SIGNALLING],
            support_spans=[_span(EMSystemId.SIGNALLING)],
        )
        self.assertEqual(result.systems, (EMSystemId.SIGNALLING,))
        self.assertIsNone(result.taxonomy_resolution_reason)

    def test_evaluated_multiple_systems_are_canonically_ordered(self):
        result = TaxonomyResult(
            taxonomy_state=TaxonomyState.TAXONOMY_EVALUATED,
            event_id="E1",
            systems=[EMSystemId.POWER_SUPPLY, EMSystemId.SIGNALLING],
            support_spans=[
                _span(EMSystemId.POWER_SUPPLY),
                _span(EMSystemId.SIGNALLING),
            ],
        )
        self.assertEqual(
            result.systems,
            (EMSystemId.SIGNALLING, EMSystemId.POWER_SUPPLY),
        )

    def test_source_or_input_order_does_not_change_result_order(self):
        forward = TaxonomyResult(
            taxonomy_state=TaxonomyState.TAXONOMY_EVALUATED,
            event_id="E1",
            systems=[EMSystemId.SIGNALLING, EMSystemId.POWER_SUPPLY],
            support_spans=[
                _span(EMSystemId.SIGNALLING),
                _span(EMSystemId.POWER_SUPPLY),
            ],
        )
        reverse = TaxonomyResult(
            taxonomy_state=TaxonomyState.TAXONOMY_EVALUATED,
            event_id="E1",
            systems=[EMSystemId.POWER_SUPPLY, EMSystemId.SIGNALLING],
            support_spans=[
                _span(EMSystemId.POWER_SUPPLY),
                _span(EMSystemId.SIGNALLING),
            ],
        )
        self.assertEqual(forward.systems, reverse.systems)

    def test_duplicate_systems_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicates"):
            TaxonomyResult(
                taxonomy_state=TaxonomyState.TAXONOMY_EVALUATED,
                event_id="E1",
                systems=[EMSystemId.SIGNALLING, EMSystemId.SIGNALLING],
                support_spans=[_span(EMSystemId.SIGNALLING)],
            )

    def test_evaluated_empty_is_valid_and_distinct(self):
        result = TaxonomyResult(
            taxonomy_state=TaxonomyState.TAXONOMY_EVALUATED,
            event_id="E1",
            systems=[],
        )
        self.assertEqual(result.systems, ())
        self.assertIsNone(result.taxonomy_resolution_reason)
        self.assertNotEqual(result.taxonomy_state, TaxonomyState.TAXONOMY_UNRESOLVED)

    def test_evaluated_with_reason_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "cannot carry"):
            TaxonomyResult(
                taxonomy_state=TaxonomyState.TAXONOMY_EVALUATED,
                event_id="E1",
                systems=[],
                taxonomy_resolution_reason=(
                    TaxonomyResolutionReason.INSUFFICIENT_SYSTEM_EVIDENCE
                ),
            )

    def test_unresolved_requires_empty_systems_and_valid_reason(self):
        for reason in TaxonomyResolutionReason:
            result = TaxonomyResult(
                taxonomy_state=TaxonomyState.TAXONOMY_UNRESOLVED,
                event_id="E1",
                systems=[],
                taxonomy_resolution_reason=reason,
                provenance=(
                    _insufficient_provenance()
                    if reason is TaxonomyResolutionReason.INSUFFICIENT_SYSTEM_EVIDENCE
                    else _conflict_provenance()
                ),
            )
            self.assertEqual(result.systems, ())

    def test_unresolved_requires_reason_specific_typed_provenance(self):
        for reason in TaxonomyResolutionReason:
            with self.subTest(reason=reason):
                with self.assertRaisesRegex(ValueError, "typed"):
                    TaxonomyResult(
                        taxonomy_state=TaxonomyState.TAXONOMY_UNRESOLVED,
                        event_id="E1",
                        systems=[],
                        taxonomy_resolution_reason=reason,
                    )

        with self.assertRaisesRegex(ValueError, "typed insufficiency"):
            TaxonomyResult(
                taxonomy_state=TaxonomyState.TAXONOMY_UNRESOLVED,
                event_id="E1",
                systems=[],
                taxonomy_resolution_reason=(
                    TaxonomyResolutionReason.INSUFFICIENT_SYSTEM_EVIDENCE
                ),
                provenance=_conflict_provenance(),
            )
        with self.assertRaisesRegex(ValueError, "typed conflict"):
            TaxonomyResult(
                taxonomy_state=TaxonomyState.TAXONOMY_UNRESOLVED,
                event_id="E1",
                systems=[],
                taxonomy_resolution_reason=TaxonomyResolutionReason.CONFLICTING_SYSTEM_EVIDENCE,
                provenance=_insufficient_provenance(),
            )

    def test_insufficient_provenance_requires_ids_and_diagnostic(self):
        with self.assertRaises(ValueError):
            TaxonomyInsufficientEvidenceProvenance(member_candidate_ids=(), diagnostic="why")
        with self.assertRaises(ValueError):
            TaxonomyInsufficientEvidenceProvenance(member_candidate_ids=("C1",), diagnostic="")

    def test_conflict_provenance_requires_source_preserving_spans(self):
        with self.assertRaises(ValueError):
            TaxonomyConflictEvidenceProvenance(conflict_spans=())
        with self.assertRaises(TypeError):
            TaxonomyConflictEvidenceProvenance(conflict_spans=("not-a-span",))

    def test_unresolved_with_assigned_systems_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "requires empty systems"):
            TaxonomyResult(
                taxonomy_state=TaxonomyState.TAXONOMY_UNRESOLVED,
                event_id="E1",
                systems=[EMSystemId.SIGNALLING],
                taxonomy_resolution_reason=(
                    TaxonomyResolutionReason.CONFLICTING_SYSTEM_EVIDENCE
                ),
            )

    def test_unresolved_with_null_or_invalid_reason_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "requires a resolution reason"):
            TaxonomyResult(
                taxonomy_state=TaxonomyState.TAXONOMY_UNRESOLVED,
                event_id="E1",
                systems=[],
            )
        with self.assertRaisesRegex(ValueError, "invalid resolution reason"):
            TaxonomyResult(
                taxonomy_state=TaxonomyState.TAXONOMY_UNRESOLVED,
                event_id="E1",
                systems=[],
                taxonomy_resolution_reason="OTHER",
            )

    def test_unresolved_cannot_carry_assigned_system_support(self):
        with self.assertRaisesRegex(ValueError, "cannot carry assigned-system support"):
            TaxonomyResult(
                taxonomy_state=TaxonomyState.TAXONOMY_UNRESOLVED,
                event_id="E1",
                systems=[],
                taxonomy_resolution_reason=(
                    TaxonomyResolutionReason.INSUFFICIENT_SYSTEM_EVIDENCE
                ),
                support_spans=[_span(EMSystemId.SIGNALLING)],
            )

    def test_not_evaluated_is_empty_without_reason_or_support(self):
        result = TaxonomyResult.not_evaluated(event_id="E1")
        self.assertEqual(result.taxonomy_state, TaxonomyState.NOT_EVALUATED)
        self.assertEqual(result.systems, ())
        self.assertIsNone(result.taxonomy_resolution_reason)
        self.assertEqual(result.support_spans, ())

    def test_not_evaluated_with_systems_reason_support_or_provenance_is_rejected(self):
        cases = (
            {"systems": [EMSystemId.SIGNALLING]},
            {"taxonomy_resolution_reason": TaxonomyResolutionReason.CONFLICTING_SYSTEM_EVIDENCE},
            {"support_spans": [_span(EMSystemId.SIGNALLING)]},
            {"provenance": {"stage": "not-reached"}},
        )
        for invalid_fields in cases:
            with self.subTest(invalid_fields=invalid_fields):
                with self.assertRaises((TypeError, ValueError)):
                    TaxonomyResult(
                        taxonomy_state=TaxonomyState.NOT_EVALUATED,
                        event_id="E1",
                        **invalid_fields,
                    )

    def test_noncanonical_system_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "canonical EMSystemId"):
            TaxonomyResult(
                taxonomy_state=TaxonomyState.TAXONOMY_EVALUATED,
                event_id="E1",
                systems=["VERTICAL_TRANSPORT"],
            )

    def test_support_cannot_refer_to_absent_system(self):
        with self.assertRaisesRegex(ValueError, "absent from systems"):
            TaxonomyResult(
                taxonomy_state=TaxonomyState.TAXONOMY_EVALUATED,
                event_id="E1",
                systems=[],
                support_spans=[_span(EMSystemId.SIGNALLING)],
            )

    def test_each_assigned_system_requires_support(self):
        with self.assertRaisesRegex(ValueError, "requires system-specific support"):
            TaxonomyResult(
                taxonomy_state=TaxonomyState.TAXONOMY_EVALUATED,
                event_id="E1",
                systems=[EMSystemId.SIGNALLING, EMSystemId.POWER_SUPPLY],
                support_spans=[_span(EMSystemId.SIGNALLING)],
            )

    def test_duplicate_support_does_not_duplicate_system_assignment(self):
        result = TaxonomyResult(
            taxonomy_state=TaxonomyState.TAXONOMY_EVALUATED,
            event_id="E1",
            systems=[EMSystemId.SIGNALLING],
            support_spans=[
                _span(EMSystemId.SIGNALLING),
                _span(EMSystemId.SIGNALLING),
            ],
        )
        self.assertEqual(result.systems, (EMSystemId.SIGNALLING,))

    def test_support_span_requires_exact_nonempty_bounds(self):
        with self.assertRaises(ValueError):
            _span(EMSystemId.SIGNALLING, start=-1)
        with self.assertRaises(ValueError):
            _span(EMSystemId.SIGNALLING, start=4, end=4)

    def test_contract_objects_are_immutable(self):
        span = _span(EMSystemId.SIGNALLING)
        result = TaxonomyResult(
            taxonomy_state=TaxonomyState.TAXONOMY_EVALUATED,
            event_id="E1",
            systems=[EMSystemId.SIGNALLING],
            support_spans=[span],
        )
        with self.assertRaises(FrozenInstanceError):
            result.systems = ()  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            span.end = 5  # type: ignore[misc]
        unresolved = TaxonomyResult(
            taxonomy_state=TaxonomyState.TAXONOMY_UNRESOLVED,
            event_id="E1",
            taxonomy_resolution_reason=TaxonomyResolutionReason.INSUFFICIENT_SYSTEM_EVIDENCE,
            provenance=_insufficient_provenance(),
        )
        with self.assertRaises(FrozenInstanceError):
            unresolved.provenance.diagnostic = "changed"  # type: ignore[union-attr]
        with self.assertRaises(FrozenInstanceError):
            unresolved.provenance.member_candidate_ids = ()  # type: ignore[union-attr]
        conflict = TaxonomyConflictEvidenceProvenance(
            conflict_spans=[_span(EMSystemId.SIGNALLING)]
        )
        with self.assertRaises(FrozenInstanceError):
            conflict.conflict_spans[0].end = 5  # type: ignore[misc]

    def test_provenance_caller_mutation_is_isolated(self):
        member_ids = ["C1", "C2"]
        insufficiency = TaxonomyInsufficientEvidenceProvenance(
            member_candidate_ids=member_ids,
            diagnostic="No supported system evidence.",
        )
        member_ids.append("C3")
        self.assertEqual(insufficiency.member_candidate_ids, ("C1", "C2"))

        spans = [_span(EMSystemId.SIGNALLING), _span(EMSystemId.POWER_SUPPLY)]
        conflict = TaxonomyConflictEvidenceProvenance(conflict_spans=spans)
        spans.clear()
        self.assertEqual(len(conflict.conflict_spans), 2)

    def test_result_caller_owned_collections_are_isolated(self):
        systems = [EMSystemId.SIGNALLING]
        spans = [_span(EMSystemId.SIGNALLING)]
        result = TaxonomyResult(
            taxonomy_state=TaxonomyState.TAXONOMY_EVALUATED,
            event_id="E1",
            systems=systems,
            support_spans=spans,
        )
        systems.clear()
        spans.clear()
        self.assertEqual(result.systems, (EMSystemId.SIGNALLING,))
        self.assertEqual(len(result.support_spans), 1)
