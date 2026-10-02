"""Shared Search-to-Candidate application composition seam."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .candidate_normalizer import CandidateNormalizationError, CandidateNormalizer
from .contracts import (
    AcquisitionRecord,
    CandidateNormalizationFailure,
    CandidateNormalizationResult,
    RegionMode,
    SearchExecutionResult,
    SearchObservation,
    SearchPlan,
    SearchTerminalStatus,
)
from .region_registry import RegionRegistry
from .search_executor import SearchExecutor
from .search_planner import SearchPlanner


@dataclass(frozen=True, slots=True)
class ReportApplicationResult:
    """Immutable Search composition output before Evidence acquisition."""

    plan: SearchPlan
    execution: SearchExecutionResult
    acquisitions: tuple[AcquisitionRecord, ...] = ()
    normalization_result: CandidateNormalizationResult | None = None
    normalized_observations: tuple[SearchObservation, ...] = ()
    normalization_failure: CandidateNormalizationFailure | None = None

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


class ReportApplication:
    """The single application orchestration owner for Search Phase 2B."""

    def __init__(
        self,
        registry: RegionRegistry,
        planner: SearchPlanner | None = None,
        executor: SearchExecutor | None = None,
        normalizer: CandidateNormalizer | None = None,
    ) -> None:
        if not isinstance(registry, RegionRegistry):
            raise TypeError("ReportApplication requires a RegionRegistry")
        if planner is not None and not isinstance(planner, SearchPlanner):
            raise TypeError("ReportApplication planner must be a SearchPlanner")
        if not isinstance(executor, SearchExecutor):
            raise TypeError("ReportApplication requires a SearchExecutor")
        if normalizer is not None and not isinstance(normalizer, CandidateNormalizer):
            raise TypeError("ReportApplication normalizer must be a CandidateNormalizer")
        self._registry = registry
        self._planner = planner or SearchPlanner(registry)
        self._executor = executor
        self._normalizer = normalizer or CandidateNormalizer()

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

    def run(
        self,
        mode: RegionMode | str,
        intents: Iterable | None = None,
    ) -> ReportApplicationResult:
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

        return ReportApplicationResult(
            plan,
            execution,
            acquisitions=acquisitions,
            normalization_result=normalized,
            normalized_observations=self._normalized_observations(
                execution, acquisitions, normalized
            ),
        )

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
) -> ReportApplication:
    """Construct the shared Search application seam without executing it."""

    return ReportApplication(registry, planner, executor, normalizer)


__all__ = [
    "ReportApplication",
    "ReportApplicationResult",
    "build_report_application",
]
