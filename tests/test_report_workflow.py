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
    ReportabilityStageFailure,
    ReportabilityEvidenceProvenance,
    ReportabilityReason,
    ReportabilityResult,
    ReportabilityState,
)
from src.weekly_report.report_workflow import (
    ReportWorkflow,
    ReportWorkflowResult,
    build_report_workflow,
)
from src.weekly_report.reportability import Reportability
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


class _ReportabilityProvider:
    def __init__(self, states=None, failures=()):
        self.calls = []
        self.states = states or {}
        self.failures = set(failures)

    def __call__(self, request):
        self.calls.append(request)
        if request.event_id in self.failures:
            raise RuntimeError("provider failure")
        state = self.states.get(request.event_id, ReportabilityState.NOT_REPORTABLE)
        if state is ReportabilityState.REPORTABLE:
            member = request.members[0]
            quote = member.substantive_content[:4]
            return {
                "event_id": request.event_id,
                "proposed_state": state,
                "examined_candidate_ids": request.member_candidate_ids,
                "support_citations": [{"candidate_id": member.candidate_id, "exact_quote": quote}],
                "rationale": "authoritative evidence supports the event",
            }
        return {
            "event_id": request.event_id,
            "proposed_state": state,
            "examined_candidate_ids": request.member_candidate_ids,
            "support_citations": [],
            "rationale": "authoritative evidence does not support reporting value",
        }


def _workflow_reportability(*, states=None, failures=()):
    provider = _ReportabilityProvider(states=states, failures=failures)
    return provider, Reportability(provider)


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

    def test_taxonomy_only_lower_level_seam_returns_event_decision_records(self):
        group = _group("A")
        owner = _RecordingTaxonomy({group.event_id: _evaluated(group)})

        result = ReportWorkflow(owner).run(
            (group,), {group.event_id: (_record("A"),)}, {group.event_id: _assigned(group)}
        )

        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], EventDecisionRecord)
        self.assertNotIsInstance(result[0], ReportWorkflowResult)

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
        taxonomy_provider = _Provider()
        reportability_provider = _ReportabilityProvider()
        workflow = build_report_workflow(
            taxonomy_proposal_provider=taxonomy_provider,
            reportability_proposal_provider=reportability_provider,
        )
        self.assertIs(workflow.taxonomy._proposal_provider, taxonomy_provider)
        self.assertIsInstance(workflow.reportability, Reportability)
        self.assertEqual(taxonomy_provider.calls, [])
        self.assertEqual(reportability_provider.calls, [])

    def test_invalid_input_is_rejected_without_semantic_fallback(self):
        owner = _RecordingTaxonomy()
        with self.assertRaises(TypeError):
            ReportWorkflow(owner).run(("not an EventGroup",), {}, {})


class ReportabilityWorkflowIntegrationTests(unittest.TestCase):
    def _run(self, groups, categories, taxonomy_results, *, states=None, failures=()):
        taxonomy = _RecordingTaxonomy(
            outcomes={group.event_id: taxonomy_results[group.event_id] for group in groups}
        )
        provider, reportability = _workflow_reportability(states=states, failures=failures)
        workflow = ReportWorkflow(taxonomy, reportability=reportability)
        records = {
            group.event_id: tuple(_record(candidate_id, f"body for {candidate_id}") for candidate_id in group.member_candidate_ids)
            for group in groups
        }
        categories_by_id = {
            group.event_id: categories[group.event_id](group)
            if callable(categories[group.event_id])
            else categories[group.event_id]
            for group in groups
        }
        return workflow.run(groups, records, categories_by_id), provider

    def test_assigned_and_evaluated_reaches_reportability(self):
        group = _group("A")
        result, provider = self._run(
            (group,), {"E1": _assigned}, {"E1": _evaluated(group)},
        )
        self.assertIsInstance(result[0], ReportWorkflowResult)
        self.assertEqual(len(provider.calls), 1)
        self.assertIsNotNone(result[0].reportability_result)

    def test_evaluated_empty_taxonomy_still_reaches_reportability(self):
        group = _group("A")
        result, provider = self._run(
            (group,), {"E1": _assigned}, {"E1": _evaluated(group)},
        )
        self.assertEqual(result[0].taxonomy_result.systems, ())
        self.assertEqual(len(provider.calls), 1)

    def test_category_unresolved_does_not_call_reportability(self):
        group = _group("A")
        result, provider = self._run(
            (group,), {"E1": _unresolved}, {"E1": TaxonomyResult.not_evaluated(event_id="E1")},
        )
        self.assertEqual(provider.calls, [])
        self.assertIsNone(result[0].reportability_result)
        self.assertEqual(result[0].reportability_state, "NOT_EVALUATED")

    def test_taxonomy_unresolved_does_not_call_reportability(self):
        group = _group("A")
        result, provider = self._run(
            (group,), {"E1": _assigned}, {"E1": _unresolved_taxonomy(group)},
        )
        self.assertEqual(provider.calls, [])
        self.assertIs(result[0].reportability_result, None)

    def test_reportable_is_downstream_eligible(self):
        group = _group("A")
        result, _ = self._run(
            (group,), {"E1": _assigned}, {"E1": _evaluated(group)},
            states={"E1": ReportabilityState.REPORTABLE},
        )
        self.assertTrue(result[0].downstream_eligible)
        self.assertIs(result[0].reportability_state, ReportabilityState.REPORTABLE)

    def test_not_reportable_is_terminal_before_downstream(self):
        group = _group("A")
        result, _ = self._run(
            (group,), {"E1": _assigned}, {"E1": _evaluated(group)},
            states={"E1": ReportabilityState.NOT_REPORTABLE},
        )
        self.assertFalse(result[0].downstream_eligible)
        self.assertIs(result[0].reportability_state, ReportabilityState.NOT_REPORTABLE)

    def test_upstream_terminal_has_projection_without_result(self):
        groups = (_group("A", event_id="E1"), _group("B", event_id="E2"))
        result, provider = self._run(
            groups,
            {"E1": _unresolved, "E2": _not_evaluated},
            {"E1": TaxonomyResult.not_evaluated(event_id="E1"), "E2": TaxonomyResult.not_evaluated(event_id="E2")},
        )
        self.assertEqual(len(result), 2)
        self.assertTrue(all(item.reportability_result is None for item in result))
        self.assertEqual(provider.calls, [])

    def test_owner_is_called_once_for_each_reached_event(self):
        groups = (_group("A", event_id="E1"), _group("B", event_id="E2"))
        result, provider = self._run(
            groups,
            {"E1": _assigned, "E2": _assigned},
            {"E1": _evaluated(groups[0]), "E2": _evaluated(groups[1])},
        )
        self.assertEqual([request.event_id for request in provider.calls], ["E1", "E2"])
        self.assertEqual(len(result), 2)

    def test_complete_reached_population_is_evaluated_before_return(self):
        groups = tuple(_group(candidate, event_id=f"E{index}") for index, candidate in enumerate(("A", "B", "C"), 1))
        result, provider = self._run(
            groups,
            {group.event_id: _assigned for group in groups},
            {group.event_id: _evaluated(group) for group in groups},
        )
        self.assertEqual(len(provider.calls), 3)
        self.assertEqual(len(result), 3)

    def test_reportability_failure_aborts_formal_workflow(self):
        groups = (_group("A", event_id="E1"), _group("B", event_id="E2"))
        taxonomy = _RecordingTaxonomy({"E1": _evaluated(groups[0]), "E2": _evaluated(groups[1])})
        provider, reportability = _workflow_reportability(failures={"E2"})
        workflow = ReportWorkflow(taxonomy, reportability=reportability)
        records = {group.event_id: (_record(group.member_candidate_ids[0], "body"),) for group in groups}
        categories = {group.event_id: _assigned(group) for group in groups}
        with self.assertRaises(ReportabilityStageFailure):
            workflow.run(groups, records, categories)
        self.assertEqual([request.event_id for request in provider.calls], ["E1", "E2"])

    def test_no_partial_downstream_population_escapes_after_failure(self):
        group = _group("A")
        taxonomy = _RecordingTaxonomy({"E1": _evaluated(group)})
        _, reportability = _workflow_reportability(failures={"E1"})
        workflow = ReportWorkflow(taxonomy, reportability=reportability)
        with self.assertRaises(ReportabilityStageFailure):
            workflow.run((group,), {"E1": (_record("A", "body"),)}, {"E1": _assigned(group)})

    def test_zero_reportable_events_is_valid(self):
        groups = (_group("A", event_id="E1"), _group("B", event_id="E2"))
        result, _ = self._run(
            groups,
            {"E1": _assigned, "E2": _assigned},
            {"E1": _evaluated(groups[0]), "E2": _evaluated(groups[1])},
            states={"E1": ReportabilityState.NOT_REPORTABLE, "E2": ReportabilityState.NOT_REPORTABLE},
        )
        self.assertEqual(sum(item.downstream_eligible for item in result), 0)

    def test_no_minimum_count_policy_is_applied(self):
        group = _group("A")
        result, _ = self._run(
            (group,), {"E1": _assigned}, {"E1": _evaluated(group)},
            states={"E1": ReportabilityState.REPORTABLE},
        )
        self.assertEqual(len(result), 1)

    def test_no_top_n_quota_balance_or_backfill_is_applied(self):
        groups = (_group("A", event_id="E1"), _group("B", event_id="E2"))
        result, _ = self._run(
            groups,
            {"E1": _assigned, "E2": _assigned},
            {"E1": _evaluated(groups[0]), "E2": _evaluated(groups[1])},
            states={"E1": ReportabilityState.REPORTABLE, "E2": ReportabilityState.REPORTABLE},
        )
        self.assertEqual(len(result), 2)
        self.assertTrue(all(item.downstream_eligible for item in result))

    def test_taxonomy_system_count_does_not_infer_reportability(self):
        group = _group("A")
        result, provider = self._run(
            (group,), {"E1": _assigned}, {"E1": _evaluated(group, system=EMSystemId.POWER_SUPPLY)},
            states={"E1": ReportabilityState.NOT_REPORTABLE},
        )
        self.assertEqual(len(provider.calls), 1)
        self.assertIs(result[0].reportability_state, ReportabilityState.NOT_REPORTABLE)

    def test_category_does_not_infer_reportability(self):
        group = _group("A")
        result, provider = self._run(
            (group,), {"E1": _assigned}, {"E1": _evaluated(group)},
            states={"E1": ReportabilityState.NOT_REPORTABLE},
        )
        self.assertEqual(len(provider.calls), 1)
        self.assertIs(result[0].reportability_state, ReportabilityState.NOT_REPORTABLE)

    def test_keyword_or_procurement_amount_does_not_infer_reportability(self):
        group = _group("A")
        provider, reportability = _workflow_reportability(states={"E1": ReportabilityState.NOT_REPORTABLE})
        taxonomy = _RecordingTaxonomy({"E1": _evaluated(group)})
        workflow = ReportWorkflow(taxonomy, reportability=reportability)
        workflow.run(
            (group,), {"E1": (_record("A", "procurement amount USD 3000000 maintenance"),)}, {"E1": _assigned(group)}
        )
        self.assertEqual(len(provider.calls), 1)

    def test_category_and_taxonomy_are_not_mutated(self):
        group = _group("A")
        category = _assigned(group)
        taxonomy_result = _evaluated(group, system=EMSystemId.POWER_SUPPLY)
        result, _ = self._run(
            (group,), {"E1": category}, {"E1": taxonomy_result},
            states={"E1": ReportabilityState.NOT_REPORTABLE},
        )
        self.assertIs(result[0].category_result, category)
        self.assertIs(result[0].taxonomy_result, taxonomy_result)

    def test_authoritative_reportability_result_is_preserved_unchanged(self):
        group = _group("A")
        expected = ReportabilityResult(
            event_id="E1",
            reportability_state=ReportabilityState.NOT_REPORTABLE,
            reportability_reason=ReportabilityReason.LOW_REPORTABILITY_VALUE,
            provenance=ReportabilityEvidenceProvenance(
                examined_candidate_ids=("A",), support_spans=(), rationale="fixed result"
            ),
        )

        class Owner:
            def evaluate(self, record):
                return expected

        taxonomy = _RecordingTaxonomy({"E1": _evaluated(group)})
        result = ReportWorkflow(taxonomy, reportability=Owner()).run(
            (group,), {"E1": (_record("A"),)}, {"E1": _assigned(group)}
        )
        self.assertIs(result[0].reportability_result, expected)

    def test_reached_order_and_member_order_are_deterministic(self):
        groups = (_group("B", "A", event_id="E1"), _group("C", event_id="E2"))
        result, provider = self._run(
            groups,
            {"E1": _assigned, "E2": _assigned},
            {"E1": _evaluated(groups[0]), "E2": _evaluated(groups[1])},
        )
        self.assertEqual([item.event_group.event_id for item in result], ["E1", "E2"])
        self.assertEqual(provider.calls[0].member_candidate_ids, ("A", "B"))

    def test_build_factory_injects_reportability_provider_without_eager_call(self):
        provider = _ReportabilityProvider()
        workflow = build_report_workflow(reportability_proposal_provider=provider)
        self.assertIsInstance(workflow.reportability, Reportability)
        self.assertEqual(provider.calls, [])


if __name__ == "__main__":
    unittest.main()
