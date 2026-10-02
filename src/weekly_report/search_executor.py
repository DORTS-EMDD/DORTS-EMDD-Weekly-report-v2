"""Sequential execution of one frozen SearchPlan."""

from __future__ import annotations

from collections.abc import Mapping
from time import sleep
from types import MappingProxyType

from .contracts import (
    SearchAttemptResult,
    SearchExecutionResult,
    SearchInfrastructureFailure,
    SearchInfrastructureFailureClass,
    SearchInfrastructureStage,
    SearchObservation,
    SearchPlan,
    SearchPlanItem,
    SearchProvider,
    SearchProviderId,
    SearchTechnicalFailureClass,
    SearchTerminalStatus,
)


class SearchExecutor:
    """The mechanical owner of ordered, one-attempt-per-item execution."""

    def __init__(
        self,
        dispatch: Mapping[SearchProviderId, SearchProvider],
        *,
        pacing_seconds: float = 0.0,
    ) -> None:
        if not isinstance(dispatch, Mapping):
            raise TypeError("SearchExecutor dispatch must be a mapping")
        if isinstance(pacing_seconds, bool) or float(pacing_seconds) < 0:
            raise ValueError("pacing_seconds must be non-negative")
        self._dispatch = MappingProxyType(dict(dispatch))
        self._pacing_seconds = float(pacing_seconds)

    @property
    def dispatch(self):
        return self._dispatch

    def execute(self, plan: SearchPlan) -> SearchExecutionResult:
        if not isinstance(plan, SearchPlan):
            raise TypeError("SearchExecutor requires a SearchPlan")

        attempts: list[SearchAttemptResult] = []
        observations: dict[str, SearchObservation] = {}
        infrastructure_failure: SearchInfrastructureFailure | None = None
        unattempted: tuple[SearchPlanItem, ...] = ()

        for index, item in enumerate(plan.items):
            provider = None
            if isinstance(item.provider_target, SearchProviderId):
                for key, candidate in self._dispatch.items():
                    if type(key) is SearchProviderId and key is item.provider_target:
                        provider = candidate
                        break
            if not isinstance(item.provider_target, SearchProviderId) or not isinstance(provider, SearchProvider):
                infrastructure_failure = SearchInfrastructureFailure(
                    SearchInfrastructureFailureClass.EXECUTION_ABORTED,
                    SearchInfrastructureStage.DISPATCH,
                )
                unattempted = tuple(plan.items[index:])
                break
            if self._pacing_seconds:
                sleep(self._pacing_seconds)
            try:
                value = provider.execute(item)
            except Exception:
                infrastructure_failure = SearchInfrastructureFailure(
                    SearchInfrastructureFailureClass.EXECUTION_ABORTED,
                    SearchInfrastructureStage.EXECUTION,
                )
                unattempted = tuple(plan.items[index:])
                break

            if not isinstance(value, SearchAttemptResult) or value.plan_item_id != item.plan_item_id:
                value = SearchAttemptResult(
                    item.plan_item_id,
                    SearchTerminalStatus.TECHNICAL_FAILURE,
                    technical_failure_class=SearchTechnicalFailureClass.UNKNOWN,
                )
            attempts.append(value)
            observations[item.plan_item_id] = self._attempt_observation(item, value)

        for item in unattempted:
            observations[item.plan_item_id] = self._unattempted_observation(item)

        return SearchExecutionResult(
            plan,
            attempt_results=tuple(attempts),
            unattempted_items=unattempted,
            infrastructure_failure=infrastructure_failure,
            observations=tuple(observations.values()),
        )

    @staticmethod
    def _attempt_observation(item: SearchPlanItem, result: SearchAttemptResult) -> SearchObservation:
        count = len(result.results) if result.status is SearchTerminalStatus.SUCCESS_WITH_RESULTS else 0
        return SearchObservation(
            item.plan_item_id,
            item.market_id,
            item.intent,
            item.language_profile,
            item.query_family_id,
            item.provider_target,
            True,
            True,
            result.status,
            count,
            result.technical_failure_class,
            None,
        )

    @staticmethod
    def _unattempted_observation(item: SearchPlanItem) -> SearchObservation:
        return SearchObservation(
            item.plan_item_id,
            item.market_id,
            item.intent,
            item.language_profile,
            item.query_family_id,
            item.provider_target,
            True,
            False,
            None,
            0,
            None,
            None,
        )


__all__ = ["SearchExecutor"]
