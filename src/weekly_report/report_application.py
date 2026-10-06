"""Shared Search-to-Candidate application composition seam."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from .candidate_normalizer import CandidateNormalizationError, CandidateNormalizer
from .classifier import Classifier
from .contracts import (
    AcquisitionRecord,
    CandidateNormalizationFailure,
    CandidateNormalizationResult,
    CategoryResult,
    CategoryState,
    EvidenceResult,
    EvidenceState,
    EventGroup,
    EventIdentityRecord,
    EventIdentityRun,
    NormalizedCandidate,
    RegionMode,
    SearchExecutionResult,
    SearchObservation,
    SearchPlan,
    SearchTerminalStatus,
    ScopeResult,
    ScopeState,
    TemporalResult,
)
from .evidence_service import EvidenceService
from .event_identity import EventIdentity
from .region_registry import RegionRegistry
from .search_executor import SearchExecutor
from .search_planner import SearchPlanner
from .scope_classifier import ScopeClassifier
from .temporal_rule import TemporalRule


@dataclass(frozen=True, slots=True)
class ReportApplicationResult:
    """Immutable shared application result through the Event Identity boundary."""

    plan: SearchPlan
    execution: SearchExecutionResult
    acquisitions: tuple[AcquisitionRecord, ...] = ()
    normalization_result: CandidateNormalizationResult | None = None
    normalized_observations: tuple[SearchObservation, ...] = ()
    normalization_failure: CandidateNormalizationFailure | None = None
    # ``None`` means that the Evidence stage was not reached.  An empty tuple
    # means it completed for a legal zero-candidate population.
    evidence_results: tuple[EvidenceResult, ...] | None = None
    # Each later field is None until its stage is reached.  Empty tuples are
    # completed zero populations, not an unvisited stage.
    scope_results: tuple[ScopeResult, ...] | None = None
    temporal_results: tuple[TemporalResult, ...] | None = None
    event_identity_records: tuple[EventIdentityRecord, ...] | None = None
    event_identity_run: EventIdentityRun | None = None
    category_results: tuple[CategoryResult, ...] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.plan, SearchPlan):
            raise TypeError("ReportApplicationResult requires a SearchPlan")
        if not isinstance(self.execution, SearchExecutionResult):
            raise TypeError("ReportApplicationResult requires a SearchExecutionResult")
        if self.execution.plan != self.plan:
            raise ValueError("ReportApplicationResult plan must match execution")
        acquisitions = tuple(self.acquisitions)
        if any(not isinstance(item, AcquisitionRecord) for item in acquisitions):
            raise TypeError("ReportApplicationResult acquisitions must be typed")
        object.__setattr__(self, "acquisitions", acquisitions)
        observations = tuple(self.normalized_observations)
        if any(not isinstance(item, SearchObservation) for item in observations):
            raise TypeError("ReportApplicationResult observations must be typed")
        if observations and len(observations) != len(self.plan.items):
            raise ValueError("normalized observations must cover the plan")
        object.__setattr__(self, "normalized_observations", observations)
        if self.normalization_result is not None and not isinstance(
            self.normalization_result, CandidateNormalizationResult
        ):
            raise TypeError("ReportApplicationResult normalization_result must be typed")
        if self.normalization_failure is not None and not isinstance(
            self.normalization_failure, CandidateNormalizationFailure
        ):
            raise TypeError("ReportApplicationResult normalization_failure must be typed")
        if self.normalization_result is not None and self.normalization_failure is not None:
            raise ValueError("normalization result and failure are mutually exclusive")
        evidence_results = self.evidence_results
        if evidence_results is not None:
            if not self.execution.execution_complete or self.execution.has_technical_failures:
                raise ValueError("Evidence results require successful Search execution")
            evidence_results = tuple(evidence_results)
            if self.normalization_result is None or self.normalization_failure is not None:
                raise ValueError("Evidence results require completed normalization")
            if any(not isinstance(item, EvidenceResult) for item in evidence_results):
                raise TypeError("ReportApplicationResult evidence_results must be typed")
            if any(not isinstance(item.state, EvidenceState) for item in evidence_results):
                raise TypeError("EvidenceResult state must be an EvidenceState")
            candidates = self.normalized_candidates
            candidate_ids = tuple(item.candidate.candidate_id for item in candidates)
            result_ids = tuple(item.candidate_id for item in evidence_results)
            if len(result_ids) != len(set(result_ids)):
                raise ValueError("Evidence results must have unique candidate IDs")
            if result_ids != candidate_ids:
                raise ValueError("Evidence results must cover normalized candidates in order")
        object.__setattr__(self, "evidence_results", evidence_results)

        scope_results = self.scope_results
        if scope_results is not None:
            if evidence_results is None:
                raise ValueError("Scope results require completed Evidence")
            scope_results = tuple(scope_results)
            if any(not isinstance(result, ScopeResult) for result in scope_results):
                raise TypeError("ReportApplicationResult scope_results must be typed")
            admitted_ids = tuple(
                result.candidate_id
                for result in evidence_results
                if result.state is EvidenceState.READY
            )
            if len(scope_results) != len(admitted_ids):
                raise ValueError("Scope results must cover READY Evidence candidates")
            result_ids = tuple(result.candidate_id for result in scope_results)
            if result_ids != admitted_ids:
                raise ValueError("Scope results must cover READY candidates in order")
            if any(not isinstance(result.state, ScopeState) for result in scope_results):
                raise TypeError("ScopeResult state must be a ScopeState")
        object.__setattr__(self, "scope_results", scope_results)

        temporal_results = self.temporal_results
        if temporal_results is not None:
            if scope_results is None:
                raise ValueError("Temporal results require completed Scope")
            temporal_results = tuple(temporal_results)
            if any(not isinstance(result, TemporalResult) for result in temporal_results):
                raise TypeError("ReportApplicationResult temporal_results must be typed")
            if any(type(result.date_valid) is not bool for result in temporal_results):
                raise TypeError("TemporalResult date_valid must be a bool")
            scoped_ids = tuple(
                result.candidate_id
                for result in scope_results
                if result.state is ScopeState.IN_SCOPE
            )
            if len(temporal_results) != len(scoped_ids):
                raise ValueError("Temporal results must cover IN_SCOPE candidates")
            result_ids = tuple(result.candidate_id for result in temporal_results)
            if result_ids != scoped_ids:
                raise ValueError("Temporal results must cover IN_SCOPE candidates in order")
        object.__setattr__(self, "temporal_results", temporal_results)

        records = self.event_identity_records
        if records is not None:
            if temporal_results is None:
                raise ValueError("Event Identity records require completed Temporal")
            records = tuple(records)
            eligible_ids = tuple(
                result.candidate_id
                for result in temporal_results
                if result.date_valid is True
            )
            if len(records) != len(eligible_ids):
                raise ValueError("Event Identity records must cover date-valid candidates")
            if any(not isinstance(record, EventIdentityRecord) for record in records):
                raise TypeError("ReportApplicationResult event_identity_records must be typed")
            record_ids = tuple(record.candidate.candidate_id for record in records)
            if record_ids != eligible_ids:
                raise ValueError("Event Identity records must cover eligible candidates in order")
            candidate_by_id = {
                candidate.candidate.candidate_id: candidate.candidate
                for candidate in self.normalized_candidates
            }
            evidence_by_id = {
                result.candidate_id: result
                for result in evidence_results or ()
            }
            scope_by_id = {
                result.candidate_id: result
                for result in scope_results or ()
            }
            temporal_by_id = {
                result.candidate_id: result
                for result in temporal_results
            }
            for record in records:
                candidate_id = record.candidate.candidate_id
                if record.evidence.state is not EvidenceState.READY:
                    raise ValueError("Event Identity record requires READY Evidence")
                if record.scope.state is not ScopeState.IN_SCOPE:
                    raise ValueError("Event Identity record requires IN_SCOPE Scope")
                if record.temporal.date_valid is not True:
                    raise ValueError("Event Identity record requires valid Temporal result")
                if record.candidate is not candidate_by_id[candidate_id]:
                    raise ValueError("Event Identity record must preserve Candidate reference")
                if record.evidence is not evidence_by_id[candidate_id]:
                    raise ValueError("Event Identity record must preserve Evidence reference")
                if record.scope is not scope_by_id[candidate_id]:
                    raise ValueError("Event Identity record must preserve Scope reference")
                if record.temporal is not temporal_by_id[candidate_id]:
                    raise ValueError("Event Identity record must preserve Temporal reference")
        object.__setattr__(self, "event_identity_records", records)

        event_identity_run = self.event_identity_run
        if event_identity_run is not None:
            if records is None:
                raise ValueError("Event Identity run requires completed records")
            if not isinstance(event_identity_run, EventIdentityRun):
                raise TypeError("ReportApplicationResult event_identity_run must be typed")
            if not isinstance(event_identity_run.groups, tuple):
                raise TypeError("EventIdentityRun groups must be a tuple")
            expected_ids = tuple(record.candidate.candidate_id for record in records)
            seen_ids: list[str] = []
            seen_event_ids: set[str] = set()
            for group in event_identity_run.groups:
                if not isinstance(group, EventGroup):
                    raise TypeError("EventIdentityRun groups must contain EventGroup values")
                if group.event_id in seen_event_ids:
                    raise ValueError("Event Identity groups must have unique event IDs")
                seen_event_ids.add(group.event_id)
                seen_ids.extend(group.member_candidate_ids)
            if tuple(sorted(seen_ids)) != tuple(sorted(expected_ids)):
                raise ValueError("Event Identity groups must partition eligible candidates")
            if len(seen_ids) != len(set(seen_ids)):
                raise ValueError("Event Identity groups must not overlap")
        elif records is not None:
            raise ValueError("completed Event Identity records require an EventIdentityRun")
        object.__setattr__(self, "event_identity_run", event_identity_run)

        category_results = self.category_results
        if category_results is not None:
            if event_identity_run is None:
                raise ValueError("Category results require completed Event Identity")
            category_results = tuple(category_results)
            if any(not isinstance(result, CategoryResult) for result in category_results):
                raise TypeError("ReportApplicationResult category_results must be typed")
            groups = event_identity_run.groups
            if len(category_results) != len(groups):
                raise ValueError("Category results must cover EventGroups exactly")
            group_ids = tuple(group.event_id for group in groups)
            result_ids = tuple(result.event_id for result in category_results)
            if result_ids != group_ids:
                raise ValueError("Category results must match EventGroups in order")
            if len(result_ids) != len(set(result_ids)):
                raise ValueError("Category results must have unique event IDs")
            if any(result.category_state is CategoryState.NOT_EVALUATED for result in category_results):
                raise ValueError("invoked Category must not return NOT_EVALUATED")
        object.__setattr__(self, "category_results", category_results)

    @property
    def downstream_ready(self) -> bool:
        return (
            self.execution.execution_complete
            and not self.execution.has_technical_failures
            and self.normalization_result is not None
            and self.normalization_failure is None
        )

    @property
    def normalized_candidates(self):
        if self.normalization_result is None:
            return ()
        return self.normalization_result.normalized_candidates

    @property
    def evidence_stage_completed(self) -> bool:
        return self.evidence_results is not None

    @property
    def evidence_admitted_candidates(self) -> tuple[NormalizedCandidate, ...]:
        if self.evidence_results is None:
            return ()
        return tuple(
            candidate
            for candidate, evidence in zip(
                self.normalized_candidates, self.evidence_results, strict=True
            )
            if evidence.state is EvidenceState.READY
        )


class ReportApplication:
    """The single application orchestration owner for Search Phase 2B."""

    def __init__(
        self,
        registry: RegionRegistry,
        planner: SearchPlanner | None = None,
        executor: SearchExecutor | None = None,
        normalizer: CandidateNormalizer | None = None,
        evidence_service: EvidenceService | None = None,
        scope_classifier: ScopeClassifier | None = None,
        temporal_rule: TemporalRule | None = None,
        event_identity: EventIdentity | None = None,
        classifier: Classifier | None = None,
    ) -> None:
        if not isinstance(registry, RegionRegistry):
            raise TypeError("ReportApplication requires a RegionRegistry")
        if planner is not None and not isinstance(planner, SearchPlanner):
            raise TypeError("ReportApplication planner must be a SearchPlanner")
        if not isinstance(executor, SearchExecutor):
            raise TypeError("ReportApplication requires a SearchExecutor")
        if normalizer is not None and not isinstance(normalizer, CandidateNormalizer):
            raise TypeError("ReportApplication normalizer must be a CandidateNormalizer")
        if not isinstance(evidence_service, EvidenceService):
            raise TypeError("ReportApplication requires an EvidenceService")
        if scope_classifier is not None and not isinstance(scope_classifier, ScopeClassifier):
            raise TypeError("ReportApplication scope_classifier must be a ScopeClassifier")
        if temporal_rule is not None and not isinstance(temporal_rule, TemporalRule):
            raise TypeError("ReportApplication temporal_rule must be a TemporalRule")
        if event_identity is not None and not isinstance(event_identity, EventIdentity):
            raise TypeError("ReportApplication event_identity must be an EventIdentity")
        if classifier is not None and not isinstance(classifier, Classifier):
            raise TypeError("ReportApplication classifier must be a Classifier")
        self._registry = registry
        self._planner = planner or SearchPlanner(registry)
        self._executor = executor
        self._normalizer = normalizer or CandidateNormalizer()
        self._evidence_service = evidence_service
        self._scope_classifier = scope_classifier or ScopeClassifier()
        self._temporal_rule = temporal_rule or TemporalRule()
        self._event_identity = event_identity or EventIdentity()
        self._classifier = classifier or Classifier()

    @property
    def registry(self) -> RegionRegistry:
        return self._registry

    @property
    def planner(self) -> SearchPlanner:
        return self._planner

    @property
    def executor(self) -> SearchExecutor:
        return self._executor

    @property
    def normalizer(self) -> CandidateNormalizer:
        return self._normalizer

    @property
    def evidence_service(self) -> EvidenceService:
        return self._evidence_service

    @property
    def scope_classifier(self) -> ScopeClassifier:
        return self._scope_classifier

    @property
    def temporal_rule(self) -> TemporalRule:
        return self._temporal_rule

    @property
    def event_identity(self) -> EventIdentity:
        return self._event_identity

    @property
    def classifier(self) -> Classifier:
        return self._classifier

    def run(
        self,
        mode: RegionMode | str,
        intents: Iterable | None = None,
        *,
        period_start: date | str,
        period_end: date | str,
    ) -> ReportApplicationResult:
        self._temporal_rule.validate_period(period_start, period_end)
        plan = self._planner.plan(mode, intents=intents)
        execution = self._executor.execute(plan)
        if not execution.execution_complete or execution.has_technical_failures:
            return ReportApplicationResult(
                plan,
                execution,
                normalized_observations=execution.observations,
            )

        acquisitions = self._project_acquisitions(execution)
        try:
            normalized = self._normalizer.normalize(acquisitions)
        except CandidateNormalizationError as exc:
            return ReportApplicationResult(
                plan,
                execution,
                acquisitions=acquisitions,
                normalized_observations=self._normalized_observations(
                    execution, acquisitions, None
                ),
                normalization_failure=exc.failure,
            )

        evidence_results: list[EvidenceResult] = []
        for normalized_candidate in normalized.normalized_candidates:
            evidence = self._evidence_service.evaluate(normalized_candidate.candidate)
            if not isinstance(evidence, EvidenceResult):
                raise TypeError("EvidenceService must return an EvidenceResult")
            if not isinstance(evidence.state, EvidenceState):
                raise TypeError("EvidenceResult state must be an EvidenceState")
            if evidence.candidate_id != normalized_candidate.candidate.candidate_id:
                raise ValueError("EvidenceResult candidate_id does not match candidate")
            evidence_results.append(evidence)

        evidence_tuple = tuple(evidence_results)
        ready_pairs = tuple(
            (normalized_candidate, evidence)
            for normalized_candidate, evidence in zip(
                normalized.normalized_candidates, evidence_tuple, strict=True
            )
            if evidence.state is EvidenceState.READY
        )
        scope_results: list[ScopeResult] = []
        for normalized_candidate, evidence in ready_pairs:
            scope = self._scope_classifier.classify(
                evidence,
                candidate_title=normalized_candidate.candidate.title,
            )
            if not isinstance(scope, ScopeResult):
                raise TypeError("ScopeClassifier must return a ScopeResult")
            if not isinstance(scope.state, ScopeState):
                raise TypeError("ScopeResult state must be a ScopeState")
            if scope.candidate_id != normalized_candidate.candidate.candidate_id:
                raise ValueError("ScopeResult candidate_id does not match candidate")
            scope_results.append(scope)

        scope_tuple = tuple(scope_results)
        scope_by_id = {result.candidate_id: result for result in scope_tuple}
        ready_by_id = {
            normalized_candidate.candidate.candidate_id: (normalized_candidate, evidence)
            for normalized_candidate, evidence in ready_pairs
        }
        temporal_results: list[TemporalResult] = []
        for scope in scope_tuple:
            if scope.state is not ScopeState.IN_SCOPE:
                continue
            normalized_candidate, evidence = ready_by_id[scope.candidate_id]
            temporal = self._temporal_rule.evaluate(
                scope.candidate_id,
                evidence.source_date_facts,
                period_start,
                period_end,
                source_type=evidence.source_type,
                discovery_published_at=normalized_candidate.candidate.published_at,
                scope_result=scope,
            )
            if not isinstance(temporal, TemporalResult):
                raise TypeError("TemporalRule must return a TemporalResult")
            if temporal.candidate_id != scope.candidate_id:
                raise ValueError("TemporalResult candidate_id does not match candidate")
            temporal_results.append(temporal)

        temporal_tuple = tuple(temporal_results)
        event_identity_records = tuple(
            EventIdentityRecord(
                candidate=ready_by_id[temporal.candidate_id][0].candidate,
                evidence=ready_by_id[temporal.candidate_id][1],
                scope=scope_by_id[temporal.candidate_id],
                temporal=temporal,
            )
            for temporal in temporal_tuple
            if temporal.date_valid is True
        )
        event_identity_run = self._event_identity.evaluate(event_identity_records)
        if not isinstance(event_identity_run, EventIdentityRun):
            raise TypeError("EventIdentity must return an EventIdentityRun")
        category_results = self._classify_event_groups(
            event_identity_run,
            event_identity_records,
        )

        return ReportApplicationResult(
            plan,
            execution,
            acquisitions=acquisitions,
            normalization_result=normalized,
            normalized_observations=self._normalized_observations(
                execution, acquisitions, normalized
            ),
            evidence_results=evidence_tuple,
            scope_results=scope_tuple,
            temporal_results=temporal_tuple,
            event_identity_records=event_identity_records,
            event_identity_run=event_identity_run,
            category_results=category_results,
        )

    def _classify_event_groups(
        self,
        event_identity_run: EventIdentityRun,
        event_identity_records: tuple[EventIdentityRecord, ...],
    ) -> tuple[CategoryResult, ...]:
        groups = event_identity_run.groups
        if not isinstance(groups, tuple):
            raise TypeError("Category EventIdentityRun groups must be a tuple")
        if any(not isinstance(group, EventGroup) for group in groups):
            raise TypeError("Category EventIdentityRun groups must contain EventGroup values")

        record_by_id: dict[str, EventIdentityRecord] = {}
        for record in event_identity_records:
            if not isinstance(record, EventIdentityRecord):
                raise TypeError("Category Event Identity records must be typed")
            candidate_id = record.candidate.candidate_id
            if candidate_id in record_by_id:
                raise ValueError("Event Identity records contain duplicate candidate IDs")
            record_by_id[candidate_id] = record

        group_ids = tuple(group.event_id for group in groups)
        if len(group_ids) != len(set(group_ids)):
            raise ValueError("Category EventGroups must have unique event IDs")
        expected_member_ids = tuple(
            candidate_id
            for group in groups
            for candidate_id in group.member_candidate_ids
        )
        if len(expected_member_ids) != len(set(expected_member_ids)):
            raise ValueError("Category EventGroups must not overlap")
        if set(expected_member_ids) != set(record_by_id):
            raise ValueError("Category EventGroups must cover EventIdentity records exactly")

        projections: list[tuple[EventGroup, tuple[EventIdentityRecord, ...]]] = []
        for event_group in groups:
            try:
                member_records = tuple(
                    record_by_id[candidate_id]
                    for candidate_id in event_group.member_candidate_ids
                )
            except KeyError as exc:
                raise ValueError(
                    "Category member projection does not match EventGroup"
                ) from exc
            projections.append((event_group, member_records))

        results: list[CategoryResult] = []
        for event_group, member_records in projections:
            result = self._classifier.classify(event_group, member_records)
            if not isinstance(result, CategoryResult):
                raise TypeError("Classifier must return a CategoryResult")
            if result.category_state is CategoryState.NOT_EVALUATED:
                raise ValueError("invoked Classifier cannot return NOT_EVALUATED")
            if result.event_id != event_group.event_id:
                raise ValueError("CategoryResult event_id does not match EventGroup")
            results.append(result)
        return tuple(results)

    @staticmethod
    def _project_acquisitions(execution: SearchExecutionResult) -> tuple[AcquisitionRecord, ...]:
        records: list[AcquisitionRecord] = []
        item_by_id = {item.plan_item_id: item for item in execution.plan.items}
        for attempt in execution.attempt_results:
            if attempt.status is not SearchTerminalStatus.SUCCESS_WITH_RESULTS:
                continue
            item = item_by_id[attempt.plan_item_id]
            records.extend(
                AcquisitionRecord(
                    execution.plan.plan_id,
                    item,
                    ordinal,
                    raw_result,
                )
                for ordinal, raw_result in enumerate(attempt.results)
            )
        return tuple(records)

    @staticmethod
    def _normalized_observations(
        execution: SearchExecutionResult,
        acquisitions: tuple[AcquisitionRecord, ...],
        normalized: CandidateNormalizationResult | None,
    ) -> tuple[SearchObservation, ...]:
        if normalized is None:
            return tuple(
                SearchObservation(
                    item.plan_item_id,
                    item.market_id,
                    item.intent,
                    item.language_profile,
                    item.query_family_id,
                    item.provider_target,
                    observation.planned,
                    observation.attempted,
                    observation.terminal_status,
                    observation.raw_result_count,
                    observation.technical_failure_class,
                    None,
                )
                for item, observation in zip(execution.plan.items, execution.observations, strict=True)
            )
        candidate_ids_by_item: dict[str, set[str]] = {}
        for record in acquisitions:
            candidate_ids_by_item.setdefault(record.plan_item.plan_item_id, set()).add(
                next(
                    candidate.candidate.candidate_id
                    for candidate in normalized.normalized_candidates
                    if any(
                        origin.acquisition_id == record.acquisition_id
                        for origin in candidate.acquisition_origins
                    )
                )
            )
        projected: list[SearchObservation] = []
        for item, observation in zip(execution.plan.items, execution.observations, strict=True):
            count = None
            if observation.attempted and observation.terminal_status is SearchTerminalStatus.SUCCESS_ZERO_RESULTS:
                count = 0
            elif observation.attempted and observation.terminal_status is SearchTerminalStatus.SUCCESS_WITH_RESULTS:
                count = len(candidate_ids_by_item.get(item.plan_item_id, set()))
            projected.append(
                SearchObservation(
                    item.plan_item_id,
                    item.market_id,
                    item.intent,
                    item.language_profile,
                    item.query_family_id,
                    item.provider_target,
                    observation.planned,
                    observation.attempted,
                    observation.terminal_status,
                    observation.raw_result_count,
                    observation.technical_failure_class,
                    count,
                )
            )
        return tuple(projected)


def build_report_application(
    registry: RegionRegistry,
    executor: SearchExecutor,
    *,
    planner: SearchPlanner | None = None,
    normalizer: CandidateNormalizer | None = None,
    evidence_service: EvidenceService,
    scope_classifier: ScopeClassifier | None = None,
    temporal_rule: TemporalRule | None = None,
    event_identity: EventIdentity | None = None,
    classifier: Classifier | None = None,
) -> ReportApplication:
    """Construct the shared Search application seam without executing it."""

    return ReportApplication(
        registry,
        planner,
        executor,
        normalizer,
        evidence_service,
        scope_classifier,
        temporal_rule,
        event_identity,
        classifier,
    )


__all__ = [
    "ReportApplication",
    "ReportApplicationResult",
    "build_report_application",
]
