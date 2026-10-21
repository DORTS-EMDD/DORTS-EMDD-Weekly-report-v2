"""Shared Search-to-Candidate application composition seam."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from .candidate_normalizer import CandidateNormalizationError, CandidateNormalizer
from .debug_service import observe_stage
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
    SemanticProviderTechnicalFailure,
    TechnicalGap,
    TemporalResult,
)
from .evidence_service import EvidenceService
from .event_identity import EventIdentity
from .region_registry import RegionRegistry
from .search_executor import SearchExecutor
from .search_planner import SearchPlanner
from .scope_classifier import ScopeClassifier
from .temporal_rule import TemporalRule
from .ordering import Ordering
from .report_workflow import ReportWorkflow, ReportWorkflowResult
from .report_service import (
    FinalReportArtifact,
    FormalMetadataExclusion,
    FormalReportMetadata,
    ReportDisclosure,
    ReportService,
)
from .writer import ReportWriter, WriterReportBlock
from .validator import ValidationResult, Validator
from .delivery import DeliveryReceipt, DeliveryService


class SearchRuntimeAcceptance(StrEnum):
    """Application-owned continuation outcome for one Search execution."""

    BLOCK = "BLOCK"
    LEGAL_COMPLETED_SEARCH = "LEGAL_COMPLETED_SEARCH"
    PASS_WITH_GAPS = "PASS_WITH_GAPS"


def determine_search_runtime_acceptance(
    execution: SearchExecutionResult,
) -> SearchRuntimeAcceptance:
    """Apply the locked Model C Search continuation rule exactly once."""

    if not isinstance(execution, SearchExecutionResult):
        raise TypeError("search runtime acceptance requires SearchExecutionResult")
    if (
        not execution.execution_complete
        or execution.unattempted_items
        or execution.infrastructure_failure is not None
    ):
        return SearchRuntimeAcceptance.BLOCK
    legal_success_count = sum(
        attempt.status
        in {
            SearchTerminalStatus.SUCCESS_WITH_RESULTS,
            SearchTerminalStatus.SUCCESS_ZERO_RESULTS,
        }
        for attempt in execution.attempt_results
    )
    if legal_success_count == 0:
        return SearchRuntimeAcceptance.BLOCK
    if execution.has_technical_failures:
        return SearchRuntimeAcceptance.PASS_WITH_GAPS
    return SearchRuntimeAcceptance.LEGAL_COMPLETED_SEARCH


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
    downstream_results: tuple[ReportWorkflowResult, ...] | None = None
    ordered_results: tuple[ReportWorkflowResult, ...] | None = None
    formal_metadata: tuple[FormalReportMetadata, ...] | None = None
    writer_blocks: tuple[WriterReportBlock, ...] | None = None
    validation_result: ValidationResult | None = None
    final_report: FinalReportArtifact | None = None
    delivery_result: DeliveryReceipt | None = None
    # RC-6: subjects left unfinished by a technical failure; never a Domain
    # state.  RC-5: events excluded for legal event-level data insufficiency.
    technical_gaps: tuple[TechnicalGap, ...] = ()
    metadata_exclusions: tuple[FormalMetadataExclusion, ...] = ()

    @property
    def search_runtime_acceptance(self) -> SearchRuntimeAcceptance:
        return determine_search_runtime_acceptance(self.execution)

    def _gap_ids(self, *stages: str) -> frozenset[str]:
        return frozenset(gap.subject_id for gap in self.technical_gaps if gap.stage in stages)

    def __post_init__(self) -> None:
        gaps = tuple(self.technical_gaps)
        if any(not isinstance(gap, TechnicalGap) for gap in gaps):
            raise TypeError("ReportApplicationResult technical_gaps must be TechnicalGap values")
        if len({(gap.stage, gap.subject_id) for gap in gaps}) != len(gaps):
            raise ValueError("a subject can have at most one technical gap per stage")
        object.__setattr__(self, "technical_gaps", gaps)
        exclusions = tuple(self.metadata_exclusions)
        if any(not isinstance(item, FormalMetadataExclusion) for item in exclusions):
            raise TypeError("ReportApplicationResult metadata_exclusions must be typed")
        object.__setattr__(self, "metadata_exclusions", exclusions)
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
            if self.search_runtime_acceptance is SearchRuntimeAcceptance.BLOCK:
                raise ValueError("Evidence results require accepted Search execution")
            evidence_results = tuple(evidence_results)
            if self.normalization_result is None or self.normalization_failure is not None:
                raise ValueError("Evidence results require completed normalization")
            if any(not isinstance(item, EvidenceResult) for item in evidence_results):
                raise TypeError("ReportApplicationResult evidence_results must be typed")
            if any(not isinstance(item.state, EvidenceState) for item in evidence_results):
                raise TypeError("EvidenceResult state must be an EvidenceState")
            candidates = self.normalized_candidates
            evidence_gaps = self._gap_ids("Evidence")
            candidate_ids = tuple(
                item.candidate.candidate_id
                for item in candidates
                if item.candidate.candidate_id not in evidence_gaps
            )
            if not evidence_gaps <= {item.candidate.candidate_id for item in candidates}:
                raise ValueError("Evidence technical gaps must name normalized candidates")
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
            scope_gaps = self._gap_ids("Scope")
            admitted_ids = tuple(
                result.candidate_id
                for result in evidence_results
                if result.state is EvidenceState.READY and result.candidate_id not in scope_gaps
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
            category_gaps = self._gap_ids("Category")
            groups = tuple(group for group in event_identity_run.groups if group.event_id not in category_gaps)
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

        downstream_results = self.downstream_results
        if downstream_results is not None:
            if event_identity_run is None or category_results is None:
                raise ValueError("downstream results require completed Category")
            downstream_results = tuple(downstream_results)
            if any(not isinstance(result, ReportWorkflowResult) for result in downstream_results):
                raise TypeError(
                    "ReportApplicationResult downstream_results must be ReportWorkflowResult values"
                )
            downstream_gaps = self._gap_ids("Category", "Taxonomy", "Reportability")
            groups = tuple(group for group in event_identity_run.groups if group.event_id not in downstream_gaps)
            if len(downstream_results) != len(groups):
                raise ValueError("downstream results must cover EventGroups exactly")
            result_ids = tuple(result.event_group.event_id for result in downstream_results)
            if result_ids != tuple(group.event_id for group in groups):
                raise ValueError("downstream results must match EventGroups in order")
        object.__setattr__(self, "downstream_results", downstream_results)

        ordered_results = self.ordered_results
        if ordered_results is not None:
            if downstream_results is None:
                raise ValueError("ordered results require completed downstream results")
            if not isinstance(ordered_results, tuple):
                raise TypeError("ReportApplicationResult ordered_results must be a tuple")
            if any(not isinstance(result, ReportWorkflowResult) for result in ordered_results):
                raise TypeError(
                    "ReportApplicationResult ordered_results must be ReportWorkflowResult values"
                )
            eligible_results = tuple(
                result for result in downstream_results if result.downstream_eligible
            )
            if len(ordered_results) != len(eligible_results):
                raise ValueError("ordered results must preserve eligible cardinality")
            expected_references = {id(result) for result in eligible_results}
            actual_references = [id(result) for result in ordered_results]
            if len(actual_references) != len(set(actual_references)):
                raise ValueError("ordered results must not repeat references")
            if set(actual_references) != expected_references:
                raise ValueError("ordered results must preserve eligible references")
        object.__setattr__(self, "ordered_results", ordered_results)

        formal_metadata = self.formal_metadata
        if formal_metadata is not None:
            if ordered_results is None:
                raise ValueError("formal metadata requires completed ordered results")
            if not isinstance(formal_metadata, tuple):
                raise TypeError("ReportApplicationResult formal_metadata must be a tuple")
            if any(not isinstance(item, FormalReportMetadata) for item in formal_metadata):
                raise TypeError(
                    "ReportApplicationResult formal_metadata must be FormalReportMetadata values"
                )
            excluded_ids = {item.event_id for item in exclusions}
            ordered_ids = tuple(
                item.event_group.event_id
                for item in ordered_results
                if item.event_group.event_id not in excluded_ids
            )
            if len(formal_metadata) != len(ordered_ids):
                raise ValueError("formal metadata must preserve ordered cardinality")
            metadata_ids = tuple(item.event_id for item in formal_metadata)
            if metadata_ids != ordered_ids:
                raise ValueError("formal metadata must preserve ordered event IDs")
            if len(metadata_ids) != len(set(metadata_ids)):
                raise ValueError("formal metadata must have unique event IDs")
        object.__setattr__(self, "formal_metadata", formal_metadata)

        writer_blocks = self.writer_blocks
        if writer_blocks is not None:
            if ordered_results is None or formal_metadata is None:
                raise ValueError("writer blocks require completed formal metadata")
            writer_blocks = tuple(writer_blocks)
            if any(not isinstance(item, WriterReportBlock) for item in writer_blocks):
                raise TypeError("ReportApplicationResult writer_blocks must be typed")
            writer_gaps = self._gap_ids("Writer")
            if tuple(item.event_id for item in writer_blocks) != tuple(
                item.event_id for item in formal_metadata if item.event_id not in writer_gaps
            ):
                raise ValueError("writer blocks must preserve ordered event IDs")
        object.__setattr__(self, "writer_blocks", writer_blocks)

        validation_result = self.validation_result
        if validation_result is not None:
            if writer_blocks is None or formal_metadata is None:
                raise ValueError("validation result requires completed Writer and metadata")
            if not isinstance(validation_result, ValidationResult):
                raise TypeError("ReportApplicationResult validation_result must be typed")
        object.__setattr__(self, "validation_result", validation_result)

        final_report = self.final_report
        if final_report is not None:
            if validation_result is None or not isinstance(final_report, FinalReportArtifact):
                raise TypeError("ReportApplicationResult final_report requires ValidationResult")
        object.__setattr__(self, "final_report", final_report)

        delivery_result = self.delivery_result
        if delivery_result is not None:
            if final_report is None or not isinstance(delivery_result, DeliveryReceipt):
                raise TypeError("ReportApplicationResult delivery_result requires final_report")
        object.__setattr__(self, "delivery_result", delivery_result)

    @property
    def has_technical_gaps(self) -> bool:
        return bool(self.technical_gaps)

    @property
    def downstream_ready(self) -> bool:
        return (
            self.search_runtime_acceptance is not SearchRuntimeAcceptance.BLOCK
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
        ready_ids = {
            evidence.candidate_id
            for evidence in self.evidence_results
            if evidence.state is EvidenceState.READY
        }
        return tuple(
            candidate
            for candidate in self.normalized_candidates
            if candidate.candidate.candidate_id in ready_ids
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
        report_workflow: ReportWorkflow | None = None,
        ordering: Ordering | None = None,
        report_service: ReportService | None = None,
        writer: ReportWriter | None = None,
        validator: Validator | None = None,
        delivery: DeliveryService | None = None,
        delivery_recipient: str | None = None,
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
        if report_workflow is not None and not isinstance(report_workflow, ReportWorkflow):
            raise TypeError("ReportApplication report_workflow must be a ReportWorkflow")
        if ordering is not None and not isinstance(ordering, Ordering):
            raise TypeError("ReportApplication ordering must be an Ordering")
        if report_service is not None and not isinstance(report_service, ReportService):
            raise TypeError("ReportApplication report_service must be a ReportService")
        if writer is not None and not isinstance(writer, ReportWriter):
            raise TypeError("ReportApplication writer must be a ReportWriter")
        if validator is not None and not isinstance(validator, Validator):
            raise TypeError("ReportApplication validator must be a Validator")
        if delivery is not None and not isinstance(delivery, DeliveryService):
            raise TypeError("ReportApplication delivery must be a DeliveryService")
        if (writer is None) != (validator is None):
            raise ValueError("ReportApplication Writer and Validator must be injected together")
        if writer is not None and report_service is None:
            raise ValueError("ReportApplication final pipeline requires ReportService")
        if delivery_recipient is not None and (delivery is None or writer is None):
            raise ValueError("delivery_recipient requires the final downstream pipeline")
        if ordering is not None and report_workflow is None:
            raise ValueError("ReportApplication ordering requires a ReportWorkflow")
        self._registry = registry
        self._planner = planner or SearchPlanner(registry)
        self._executor = executor
        self._normalizer = normalizer or CandidateNormalizer()
        self._evidence_service = evidence_service
        self._scope_classifier = scope_classifier or ScopeClassifier()
        self._temporal_rule = temporal_rule or TemporalRule()
        self._event_identity = event_identity or EventIdentity()
        self._classifier = classifier or Classifier()
        self._report_workflow = report_workflow
        self._ordering = ordering
        self._report_service = report_service
        self._writer = writer
        self._validator = validator
        self._delivery = delivery
        self._delivery_recipient = delivery_recipient

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

    @property
    def report_workflow(self) -> ReportWorkflow | None:
        return self._report_workflow

    @property
    def ordering(self) -> Ordering | None:
        return self._ordering

    @property
    def report_service(self) -> ReportService | None:
        return self._report_service

    @property
    def writer(self) -> ReportWriter | None:
        return self._writer

    @property
    def validator(self) -> Validator | None:
        return self._validator

    @property
    def delivery(self) -> DeliveryService | None:
        return self._delivery

    def run(
        self,
        mode: RegionMode | str,
        intents: Iterable | None = None,
        *,
        period_start: date | str,
        period_end: date | str,
    ) -> ReportApplicationResult:
        self._temporal_rule.validate_period(period_start, period_end)
        with observe_stage("Search") as observation:
            plan = self._planner.plan(mode, intents=intents)
            observation.input_count = len(plan.items)
            execution = self._executor.execute(plan)
            observation.observe(execution, final=True)

        if determine_search_runtime_acceptance(execution) is SearchRuntimeAcceptance.BLOCK:
            return ReportApplicationResult(
                plan,
                execution,
                normalized_observations=execution.observations,
            )

        with observe_stage("Acquisition", len(execution.attempt_results)) as observation:
            acquisitions = self._project_acquisitions(execution)
            observation.observe(acquisitions, final=True)

        with observe_stage("Normalization", len(acquisitions)) as observation:
            try:
                normalized = self._normalizer.normalize(acquisitions)
            except CandidateNormalizationError as exc:
                observation.fail(exc)
                return ReportApplicationResult(
                    plan,
                    execution,
                    acquisitions=acquisitions,
                    normalized_observations=self._normalized_observations(
                        execution, acquisitions, None
                    ),
                    normalization_failure=exc.failure,
                )
            observation.observe(normalized, final=True)

        technical_gaps: list[TechnicalGap] = []
        with observe_stage("Evidence", len(normalized.normalized_candidates)) as observation:
            evidence_results: list[EvidenceResult] = []
            for normalized_candidate in normalized.normalized_candidates:
                try:
                    evidence = self._evidence_service.evaluate(normalized_candidate.candidate)
                except SemanticProviderTechnicalFailure as failure:
                    technical_gaps.append(
                        TechnicalGap.from_failure("Evidence", normalized_candidate.candidate.candidate_id, failure)
                    )
                    continue
                if not isinstance(evidence, EvidenceResult):
                    raise TypeError("EvidenceService must return an EvidenceResult")
                if not isinstance(evidence.state, EvidenceState):
                    raise TypeError("EvidenceResult state must be an EvidenceState")
                if evidence.candidate_id != normalized_candidate.candidate.candidate_id:
                    raise ValueError("EvidenceResult candidate_id does not match candidate")
                evidence_results.append(evidence)
                observation.observe(evidence_results)

            evidence_tuple = tuple(evidence_results)
            observation.observe(evidence_tuple, final=True)

        evidence_by_id = {evidence.candidate_id: evidence for evidence in evidence_tuple}
        ready_pairs = tuple(
            (normalized_candidate, evidence_by_id[normalized_candidate.candidate.candidate_id])
            for normalized_candidate in normalized.normalized_candidates
            if normalized_candidate.candidate.candidate_id in evidence_by_id
            and evidence_by_id[normalized_candidate.candidate.candidate_id].state is EvidenceState.READY
        )
        with observe_stage("Scope", len(ready_pairs)) as observation:
            scope_results: list[ScopeResult] = []
            for normalized_candidate, evidence in ready_pairs:
                try:
                    scope = self._scope_classifier.classify(
                        evidence,
                        candidate_title=normalized_candidate.candidate.title,
                    )
                except SemanticProviderTechnicalFailure as failure:
                    technical_gaps.append(
                        TechnicalGap.from_failure("Scope", normalized_candidate.candidate.candidate_id, failure)
                    )
                    continue
                if not isinstance(scope, ScopeResult):
                    raise TypeError("ScopeClassifier must return a ScopeResult")
                if not isinstance(scope.state, ScopeState):
                    raise TypeError("ScopeResult state must be a ScopeState")
                if scope.candidate_id != normalized_candidate.candidate.candidate_id:
                    raise ValueError("ScopeResult candidate_id does not match candidate")
                scope_results.append(scope)
                observation.observe(scope_results)

            scope_tuple = tuple(scope_results)
            observation.observe(scope_tuple, final=True)

        scope_by_id = {result.candidate_id: result for result in scope_tuple}
        ready_by_id = {
            normalized_candidate.candidate.candidate_id: (normalized_candidate, evidence)
            for normalized_candidate, evidence in ready_pairs
        }
        with observe_stage("Temporal", sum(scope.state is ScopeState.IN_SCOPE for scope in scope_tuple)) as observation:
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
                observation.observe(temporal_results)

            temporal_tuple = tuple(temporal_results)
            observation.observe(temporal_tuple, final=True)

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
        with observe_stage("EventIdentity", len(event_identity_records)) as observation:
            event_identity_run = self._event_identity.evaluate(event_identity_records)
            if not isinstance(event_identity_run, EventIdentityRun):
                raise TypeError("EventIdentity must return an EventIdentityRun")
            observation.observe(event_identity_run, final=True)

        category_results = self._classify_event_groups(
            event_identity_run,
            event_identity_records,
            technical_gaps,
        )
        downstream_results = self._run_downstream_workflow(
            event_identity_run,
            event_identity_records,
            category_results,
            technical_gaps,
        )
        ordered_results = self._run_ordering(downstream_results)
        formal_metadata, metadata_exclusions = self._run_formal_metadata_projection(ordered_results)
        writer_blocks, validation_result, final_report, delivery_result = self._run_final_pipeline(
            ordered_results, formal_metadata, metadata_exclusions, technical_gaps
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
            downstream_results=downstream_results,
            ordered_results=ordered_results,
            formal_metadata=formal_metadata,
            writer_blocks=writer_blocks,
            validation_result=validation_result,
            final_report=final_report,
            delivery_result=delivery_result,
            technical_gaps=tuple(technical_gaps),
            metadata_exclusions=metadata_exclusions,
        )

    def _run_final_pipeline(
        self,
        ordered_results: tuple[ReportWorkflowResult, ...] | None,
        formal_metadata: tuple[FormalReportMetadata, ...] | None,
        metadata_exclusions: tuple[FormalMetadataExclusion, ...] = (),
        technical_gaps: list[TechnicalGap] | None = None,
    ) -> tuple[
        tuple[WriterReportBlock, ...] | None,
        ValidationResult | None,
        FinalReportArtifact | None,
        DeliveryReceipt | None,
    ]:
        if self._writer is None or self._validator is None:
            return None, None, None, None
        if ordered_results is None or formal_metadata is None:
            return None, None, None, None
        gaps = technical_gaps if technical_gaps is not None else []
        excluded_ids = {item.event_id for item in metadata_exclusions}
        reportable = tuple(
            result for result in ordered_results if result.event_group.event_id not in excluded_ids
        )
        with observe_stage("Writer", len(reportable)) as observation:
            writer_blocks = self._writer.write(reportable, on_event_technical_gap=gaps.append)
            if not isinstance(writer_blocks, tuple):
                raise TypeError("ReportWriter must return a tuple")
            observation.observe(writer_blocks, final=True)

        written_ids = {block.event_id for block in writer_blocks}
        written_results = tuple(
            result for result in reportable if result.event_group.event_id in written_ids
        )
        written_metadata = tuple(item for item in formal_metadata if item.event_id in written_ids)
        with observe_stage("Validator", len(written_results)) as observation:
            validation_result = self._validator.validate(
                written_results,
                written_metadata,
                writer_blocks,
                on_event_technical_gap=gaps.append,
            )
            if not isinstance(validation_result, ValidationResult):
                raise TypeError("Validator must return a ValidationResult")
            observation.observe(validation_result, final=True)

        if self._report_service is None:
            raise ValueError("final pipeline requires ReportService")
        disclosure = ReportDisclosure(
            technical_gap_count=len(gaps),
            metadata_exclusion_count=len(metadata_exclusions),
            validation_failed_count=len(validation_result.failed),
        )
        with observe_stage("Assembly", validation_result.pass_count) as observation:
            final_report = self._report_service.assemble_final_report(
                validation_result, disclosure=disclosure
            )
            if not isinstance(final_report, FinalReportArtifact):
                raise TypeError("ReportService must return a FinalReportArtifact")
            observation.observe(final_report, final=True)

        delivery_result = None
        if self._delivery is not None and self._delivery_recipient is not None:
            with observe_stage("Delivery", 1) as observation:
                delivery_result = self._delivery.deliver(final_report, self._delivery_recipient)
                if not isinstance(delivery_result, DeliveryReceipt):
                    raise TypeError("DeliveryService must return a DeliveryReceipt")
                observation.observe(delivery_result, final=True)

        return writer_blocks, validation_result, final_report, delivery_result

    def _run_formal_metadata_projection(
        self,
        ordered_results: tuple[ReportWorkflowResult, ...] | None,
    ) -> tuple[tuple[FormalReportMetadata, ...] | None, tuple[FormalMetadataExclusion, ...]]:
        if self._report_service is None or ordered_results is None:
            return None, ()
        with observe_stage("FormalMetadata", len(ordered_results)) as observation:
            projection = self._report_service.project_formal_metadata_population(ordered_results)
            formal_metadata = projection.metadata
            if not isinstance(formal_metadata, tuple):
                raise TypeError("ReportService must return a tuple of formal metadata")
            observation.observe(formal_metadata, final=True)

        return formal_metadata, projection.exclusions

    def _run_downstream_workflow(
        self,
        event_identity_run: EventIdentityRun,
        event_identity_records: tuple[EventIdentityRecord, ...],
        category_results: tuple[CategoryResult, ...],
        technical_gaps: list[TechnicalGap] | None = None,
    ) -> tuple[ReportWorkflowResult, ...] | None:
        """Pass validated upstream values to the existing downstream owner."""

        if self._report_workflow is None:
            return None
        gaps = technical_gaps if technical_gaps is not None else []
        category_gap_ids = {gap.subject_id for gap in gaps if gap.stage == "Category"}
        groups = tuple(
            group for group in event_identity_run.groups if group.event_id not in category_gap_ids
        )
        if not groups:
            with observe_stage("Taxonomy", 0) as observation:
                observation.observe((), final=True)
            if self._report_workflow.reportability is not None:
                with observe_stage("Reportability", 0) as observation:
                    observation.observe((), final=True)
            return ()
        record_by_id = {
            record.candidate.candidate_id: record for record in event_identity_records
        }
        member_records = {
            group.event_id: tuple(
                record_by_id[candidate_id]
                for candidate_id in group.member_candidate_ids
            )
            for group in groups
        }
        gaps_before = len(gaps)
        downstream_results = self._report_workflow.run(
            groups,
            member_records,
            category_results,
            on_event_technical_gap=gaps.append,
        )
        if not isinstance(downstream_results, tuple):
            raise TypeError("ReportWorkflow must return a tuple")
        if any(not isinstance(result, ReportWorkflowResult) for result in downstream_results):
            raise TypeError(
                "ReportApplication requires complete ReportWorkflowResult values"
            )
        workflow_gap_ids = {gap.subject_id for gap in gaps[gaps_before:]}
        expected_ids = tuple(group.event_id for group in groups if group.event_id not in workflow_gap_ids)
        if len(downstream_results) != len(expected_ids):
            raise ValueError("ReportWorkflow results must cover EventGroups exactly")
        result_ids = tuple(result.event_group.event_id for result in downstream_results)
        if result_ids != expected_ids:
            raise ValueError("ReportWorkflow results must match EventGroups in order")
        if len(result_ids) != len(set(result_ids)):
            raise ValueError("ReportWorkflow results must have unique event IDs")
        return downstream_results

    def _run_ordering(
        self,
        downstream_results: tuple[ReportWorkflowResult, ...] | None,
    ) -> tuple[ReportWorkflowResult, ...] | None:
        if self._ordering is None or downstream_results is None:
            return None
        eligible_results = tuple(
            result for result in downstream_results if result.downstream_eligible
        )
        with observe_stage("Ordering", len(eligible_results)) as observation:
            ordered_results = self._ordering.order(eligible_results)
            self._validate_ordering_output(eligible_results, ordered_results)
            observation.observe(ordered_results, final=True)

        return ordered_results

    @staticmethod
    def _validate_ordering_output(
        eligible_results: tuple[ReportWorkflowResult, ...],
        ordered_results: tuple[ReportWorkflowResult, ...],
    ) -> None:
        if not isinstance(ordered_results, tuple):
            raise TypeError("Ordering must return a tuple")
        if any(not isinstance(result, ReportWorkflowResult) for result in ordered_results):
            raise TypeError("Ordering must return ReportWorkflowResult values")
        if len(ordered_results) != len(eligible_results):
            raise ValueError("Ordering output must preserve cardinality")
        expected_references = {id(result) for result in eligible_results}
        actual_references = [id(result) for result in ordered_results]
        if len(actual_references) != len(set(actual_references)):
            raise ValueError("Ordering output must not repeat references")
        if set(actual_references) != expected_references:
            raise ValueError("Ordering output must preserve exact references")

    def _classify_event_groups(
        self,
        event_identity_run: EventIdentityRun,
        event_identity_records: tuple[EventIdentityRecord, ...],
        technical_gaps: list[TechnicalGap] | None = None,
    ) -> tuple[CategoryResult, ...]:
        with observe_stage("Category") as observation:
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

            observation.input_count = len(groups)
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
                try:
                    result = self._classifier.classify(event_group, member_records)
                except SemanticProviderTechnicalFailure as failure:
                    if technical_gaps is None:
                        raise
                    technical_gaps.append(TechnicalGap.from_failure("Category", event_group.event_id, failure))
                    continue
                if not isinstance(result, CategoryResult):
                    raise TypeError("Classifier must return a CategoryResult")
                if result.category_state is CategoryState.NOT_EVALUATED:
                    raise ValueError("invoked Classifier cannot return NOT_EVALUATED")
                if result.event_id != event_group.event_id:
                    raise ValueError("CategoryResult event_id does not match EventGroup")
                results.append(result)
                observation.observe(results)
            observation.observe(results, final=True)
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
    report_workflow: ReportWorkflow,
    ordering: Ordering,
    report_service: ReportService,
    writer: ReportWriter | None = None,
    validator: Validator | None = None,
    delivery: DeliveryService | None = None,
    delivery_recipient: str | None = None,
) -> ReportApplication:
    """Construct a formal shared application with its complete downstream workflow."""

    if not isinstance(report_workflow, ReportWorkflow):
        raise TypeError("build_report_application requires a ReportWorkflow")
    if report_workflow.reportability is None:
        raise ValueError(
            "build_report_application requires a ReportWorkflow with Reportability"
        )
    if not isinstance(ordering, Ordering):
        raise TypeError("build_report_application requires an Ordering")
    if not isinstance(report_service, ReportService):
        raise TypeError("build_report_application requires a ReportService")

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
        report_workflow,
        ordering,
        report_service,
        writer,
        validator,
        delivery,
        delivery_recipient,
    )


__all__ = [
    "ReportApplication",
    "ReportApplicationResult",
    "SearchRuntimeAcceptance",
    "build_report_application",
    "determine_search_runtime_acceptance",
]
