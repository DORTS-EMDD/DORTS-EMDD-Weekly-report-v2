"""Sequential execution of one frozen SearchPlan."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import time
from types import MappingProxyType

from .debug_service import observe_progress

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


# RC-88 (user decision 2026-11-26): production spacing between Search requests
# and the delay before the one retry of a rate-limited request.
SEARCH_PACING_SECONDS = 1.0
SEARCH_RATE_LIMIT_RETRY_SECONDS = 60.0


class SearchExecutor:
    """The mechanical owner of ordered execution: one attempt per item, plus
    one delayed retry of an attempt that ended RATE_LIMIT (RC-88)."""

    def __init__(
        self,
        dispatch: Mapping[SearchProviderId, SearchProvider],
        *,
        pacing_seconds: float = 0.0,
        rate_limit_retry_seconds: float | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not isinstance(dispatch, Mapping):
            raise TypeError("SearchExecutor dispatch must be a mapping")
        if isinstance(pacing_seconds, bool) or float(pacing_seconds) < 0:
            raise ValueError("pacing_seconds must be non-negative")
        if rate_limit_retry_seconds is not None and (
            isinstance(rate_limit_retry_seconds, bool) or float(rate_limit_retry_seconds) < 0
        ):
            raise ValueError("rate_limit_retry_seconds must be non-negative or None")
        if not callable(sleep):
            raise TypeError("sleep must be callable")
        self._dispatch = MappingProxyType(dict(dispatch))
        self._pacing_seconds = float(pacing_seconds)
        self._retry_seconds = None if rate_limit_retry_seconds is None else float(rate_limit_retry_seconds)
        self._sleep = sleep

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
        retried: list[str] = []
        sent = 0

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
            try:
                # RC-88: the spacing comes before every request except the first.
                if self._pacing_seconds and sent:
                    self._sleep(self._pacing_seconds)
                sent += 1
                value = provider.execute(item)
                if (
                    self._retry_seconds is not None
                    and isinstance(value, SearchAttemptResult)
                    and value.status is SearchTerminalStatus.TECHNICAL_FAILURE
                    and value.technical_failure_class is SearchTechnicalFailureClass.RATE_LIMIT
                ):
                    # RC-88: one identical request after the delay; its result
                    # is final, and a second RATE_LIMIT stays a disclosed gap.
                    retried.append(item.plan_item_id)
                    self._sleep(self._retry_seconds)
                    value = provider.execute(item)
            except Exception:
                value = SearchAttemptResult(
                    item.plan_item_id,
                    SearchTerminalStatus.TECHNICAL_FAILURE,
                    technical_failure_class=SearchTechnicalFailureClass.UNKNOWN,
                )
                attempts.append(value)
                observations[item.plan_item_id] = self._attempt_observation(item, value)
                observe_progress("Search", attempts)
                infrastructure_failure = SearchInfrastructureFailure(
                    SearchInfrastructureFailureClass.EXECUTION_ABORTED,
                    SearchInfrastructureStage.EXECUTION,
                )
                unattempted = tuple(plan.items[index + 1 :])
                break

            if not isinstance(value, SearchAttemptResult) or value.plan_item_id != item.plan_item_id:
                value = SearchAttemptResult(
                    item.plan_item_id,
                    SearchTerminalStatus.TECHNICAL_FAILURE,
                    technical_failure_class=SearchTechnicalFailureClass.UNKNOWN,
                )
            attempts.append(value)
            observations[item.plan_item_id] = self._attempt_observation(item, value)
            observe_progress("Search", attempts)

        for item in unattempted:
            observations[item.plan_item_id] = self._unattempted_observation(item)

        return SearchExecutionResult(
            plan,
            attempt_results=tuple(attempts),
            unattempted_items=unattempted,
            infrastructure_failure=infrastructure_failure,
            observations=tuple(observations.values()),
            rate_limit_retried_item_ids=tuple(retried),
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


__all__ = ["SEARCH_PACING_SECONDS", "SEARCH_RATE_LIMIT_RETRY_SECONDS", "SearchExecutor"]
