import unittest
from dataclasses import fields

from src.weekly_report.contracts import (
    CanonicalCandidate,
    CategoryId,
    CategoryResolutionReason,
    CategoryResult,
    CategoryState,
    EMSystemId,
    EventDecisionRecord,
    EventGroup,
    EventIdentityRecord,
    EvidenceResult,
    EvidenceState,
    ScopeResult,
    ScopeState,
    TaxonomyConflictEvidenceProvenance,
    TaxonomyInsufficientEvidenceProvenance,
    TaxonomyResolutionReason,
    TaxonomyResult,
    TaxonomyState,
    TaxonomySupportSpan,
    TemporalResult,
)
from src.weekly_report.report_workflow import ReportWorkflow, build_report_workflow
from src.weekly_report.taxonomy import TaxonomyStageFailure


def _record(candidate_id: str, body: str = "authoritative body") -> EventIdentityRecord:
    return EventIdentityRecord(
        candidate=CanonicalCandidate(
            candidate_id=candidate_id,
            title=f"Title {candidate_id}",
            url=f"https://example.test/{candidate_id}",
        ),
        evidence=EvidenceResult(
            candidate_id=candidate_id,
            state=EvidenceState.READY,
            canonical_source_url=f"https://example.test/{candidate_id}",
            source_type="authoritative",
            substantive_content=body,
        ),
        scope=ScopeResult(candidate_id, ScopeState.IN_SCOPE),
        temporal=TemporalResult(candidate_id, date_valid=True),
    )


def _group(*candidate_ids: str, event_id: str = "E1") -> EventGroup:
    ids = tuple(sorted(candidate_ids))
    return EventGroup(event_id, ids, ids[0], identity_basis=())


def _assigned(group: EventGroup) -> CategoryResult:
    return CategoryResult(
        category_state=CategoryState.CATEGORY_ASSIGNED,
        event_id=group.event_id,
        primary_category_id=CategoryId.TECHNICAL_DEVELOPMENT,
        primary_category=CategoryId.TECHNICAL_DEVELOPMENT.display_label,
        classification_reason="PRINCIPAL_ACTION_TECHNICAL_DEVELOPMENT",
    )


def _unresolved(group: EventGroup) -> CategoryResult:
    return CategoryResult(
        category_state=CategoryState.CATEGORY_UNRESOLVED,
        event_id=group.event_id,
        classification_reason=CategoryState.CATEGORY_UNRESOLVED.value,
        category_resolution_reason=CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION,
    )


def _not_evaluated(group: EventGroup) -> CategoryResult:
    return CategoryResult.not_evaluated(event_id=group.event_id)


def _evaluated(group: EventGroup, *, system: EMSystemId | None = None) -> TaxonomyResult:
    if system is None:
        return TaxonomyResult(
            taxonomy_state=TaxonomyState.TAXONOMY_EVALUATED,
            event_id=group.event_id,
        )
    return TaxonomyResult(
        taxonomy_state=TaxonomyState.TAXONOMY_EVALUATED,
        event_id=group.event_id,
        systems=(system,),
        support_spans=(TaxonomySupportSpan(system, group.member_candidate_ids[0], 0, 4),),
    )


def _unresolved_taxonomy(group: EventGroup) -> TaxonomyResult:
    return TaxonomyResult(
        taxonomy_state=TaxonomyState.TAXONOMY_UNRESOLVED,
        event_id=group.event_id,
        taxonomy_resolution_reason=TaxonomyResolutionReason.INSUFFICIENT_SYSTEM_EVIDENCE,
        provenance=TaxonomyInsufficientEvidenceProvenance(
            group.member_candidate_ids,
            "no canonical system established",
        ),
    )


class _RecordingTaxonomy:
    def __init__(self, outcomes=None, failures=None):
        self.calls = []
        self.outcomes = outcomes or {}
        self.failures = failures or {}

    def evaluate(self, event_group, member_records, category_result):
        self.calls.append((event_group, tuple(member_records), category_result))
        if event_group.event_id in self.failures:
            raise self.failures[event_group.event_id]
        return self.outcomes[event_group.event_id]


class _Provider:
    def __init__(self):
        self.calls = []

    def __call__(self, request):
        self.calls.append(request)
        return None


class EventDecisionRecordTests(unittest.TestCase):
    def test_is_frozen_and_contains_only_structural_fields(self):
        group = _group("B", "A")
        category = _assigned(group)
        taxonomy = _evaluated(group)
        record = EventDecisionRecord(group, (_record("B"), _record("A")), category, taxonomy)
        self.assertEqual(record.member_records[0].candidate.candidate_id, "A")
        self.assertEqual(
            {field.name for field in fields(EventDecisionRecord)},
            {"event_group", "member_records", "category_result", "taxonomy_result"},
        )
        with self.assertRaises(AttributeError):
            record.category_result = category

    def test_rejects_wrong_types_and_event_id_mismatches(self):
        group = _group("A")
        taxonomy = _evaluated(group)
        with self.assertRaises(TypeError):
            EventDecisionRecord(group, [_record("A")], _assigned(group), taxonomy)
        with self.assertRaises(ValueError):
            EventDecisionRecord(group, (_record("A"),), _assigned(_group("A", event_id="OTHER")), taxonomy)
        with self.assertRaises(ValueError):
            EventDecisionRecord(
                group,
                (_record("A"),),
                _assigned(group),
                TaxonomyResult.not_evaluated(event_id="OTHER"),
            )

    def test_rejects_duplicate_and_membership_mismatch(self):
        group = _group("A", "B")
        category = _assigned(group)
        taxonomy = _evaluated(group)
        with self.assertRaises(ValueError):
            EventDecisionRecord(group, (_record("A"), _record("A")), category, taxonomy)
        with self.assertRaises(ValueError):
            EventDecisionRecord(group, (_record("A"), _record("C")), category, taxonomy)


class ReportWorkflowTests(unittest.TestCase):
    def _run_one(self, category, taxonomy_result, *, records=None):
        group = _group("A")
        owner = _RecordingTaxonomy(outcomes={group.event_id: taxonomy_result(group) if callable(taxonomy_result) else taxonomy_result})
        workflow = ReportWorkflow(owner)
        records = records or (_record("A"),)
        result = workflow.run((group,), {group.event_id: records}, {group.event_id: category(group) if callable(category) else category})
        return group, owner, result

    def test_assigned_category_invokes_taxonomy(self):
        group = _group("A")
        owner = _RecordingTaxonomy({group.event_id: _evaluated(group)})
        result = ReportWorkflow(owner).run(
            (group,), {group.event_id: (_record("A"),)}, {group.event_id: _assigned(group)}
        )
        self.assertEqual(len(owner.calls), 1)
        self.assertEqual(result[0].taxonomy_result.taxonomy_state, TaxonomyState.TAXONOMY_EVALUATED)

    def test_unresolved_and_not_evaluated_categories_are_routed_to_owner(self):
        for category_factory in (_unresolved, _not_evaluated):
            group = _group("A")
            owner = _RecordingTaxonomy({group.event_id: TaxonomyResult.not_evaluated(event_id=group.event_id)})
            result = ReportWorkflow(owner).run(
                (group,), {group.event_id: (_record("A"),)}, {group.event_id: category_factory(group)}
            )
            self.assertEqual(len(owner.calls), 1)
            self.assertEqual(result[0].taxonomy_result.taxonomy_state, TaxonomyState.NOT_EVALUATED)

    def test_preserves_all_taxonomy_dispositions(self):
        group = _group("A")
        cases = (
            (_evaluated(group), _assigned(group)),
            (_unresolved_taxonomy(group), _assigned(group)),
            (TaxonomyResult.not_evaluated(event_id=group.event_id), _not_evaluated(group)),
        )
        for taxonomy_result, category in cases:
            owner = _RecordingTaxonomy({group.event_id: taxonomy_result})
            result = ReportWorkflow(owner).run(
                (group,), {group.event_id: (_record("A"),)}, {group.event_id: category}
            )
            self.assertIs(result[0].taxonomy_result, taxonomy_result)

    def test_evaluated_empty_and_non_empty_systems_survive_unchanged(self):
        for system in (None, EMSystemId.POWER_SUPPLY):
            group = _group("A")
            outcome = _evaluated(group, system=system)
            owner = _RecordingTaxonomy({group.event_id: outcome})
            result = ReportWorkflow(owner).run(
                (group,), {group.event_id: (_record("A", "abcd evidence"),)}, {group.event_id: _assigned(group)}
            )
            self.assertIs(result[0].taxonomy_result, outcome)
            self.assertEqual(result[0].taxonomy_result.systems, outcome.systems)

    def test_taxonomy_failure_aborts_without_partial_success_or_retry(self):
        first = _group("A", event_id="E1")
        second = _group("B", event_id="E2")
        failure = TaxonomyStageFailure("technical taxonomy failure", event_id=second.event_id)
        owner = _RecordingTaxonomy(
            {first.event_id: _evaluated(first)},
            {second.event_id: failure},
        )
        workflow = ReportWorkflow(owner)
        with self.assertRaises(TaxonomyStageFailure) as raised:
            workflow.run(
                (first, second),
                {"E1": (_record("A"),), "E2": (_record("B"),)},
                {"E1": _assigned(first), "E2": _assigned(second)},
            )
        self.assertIs(raised.exception, failure)
        self.assertEqual([call[0].event_id for call in owner.calls], ["E1", "E2"])

    def test_input_order_is_preserved_for_groups_and_members_are_structurally_aligned(self):
        first = _group("B", "A", event_id="E1")
        second = _group("C", event_id="E2")
        owner = _RecordingTaxonomy(
            {"E1": _evaluated(first), "E2": _evaluated(second)},
        )
        result = ReportWorkflow(owner).run(
            (first, second),
            {"E1": (_record("B"), _record("A")), "E2": (_record("C"),)},
            {"E1": _assigned(first), "E2": _assigned(second)},
        )
        self.assertEqual([record.event_group.event_id for record in result], ["E1", "E2"])
        self.assertEqual([record.candidate.candidate_id for record in owner.calls[0][1]], ["B", "A"])

    def test_build_factory_injects_provider_without_calling_it(self):
        provider = _Provider()
        workflow = build_report_workflow(taxonomy_proposal_provider=provider)
        self.assertIs(workflow.taxonomy._proposal_provider, provider)
        self.assertEqual(provider.calls, [])

    def test_invalid_input_is_rejected_without_semantic_fallback(self):
        owner = _RecordingTaxonomy()
        with self.assertRaises(TypeError):
            ReportWorkflow(owner).run(("not an EventGroup",), {}, {})


if __name__ == "__main__":
    unittest.main()
