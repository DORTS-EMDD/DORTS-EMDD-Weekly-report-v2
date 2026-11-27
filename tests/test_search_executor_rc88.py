"""RC-88: Search spacing and one delayed retry of a RATE_LIMIT attempt (user decision 2026-11-26)."""

from __future__ import annotations

import pytest

from src.weekly_report import production_runner, search_executor
from src.weekly_report.contracts import (
    SearchAttemptResult,
    SearchExecutionResult,
    SearchTechnicalFailureClass,
    SearchTerminalStatus,
)
from src.weekly_report.search_executor import SearchExecutor
from src.weekly_report.contracts import SearchProviderId
from tests.test_search_executor import FakeProvider, _plan


def _failure(item_id, failure_class):
    return SearchAttemptResult(item_id, SearchTerminalStatus.TECHNICAL_FAILURE, technical_failure_class=failure_class)


def _run(outcomes, **kwargs):
    """outcomes: plan_item_id -> list of results returned in turn."""
    pending = {key: list(value) for key, value in outcomes.items()}
    clock = []

    def outcome(item):
        queue = pending.get(item.plan_item_id)
        if queue:
            return queue.pop(0)
        return SearchAttemptResult(item.plan_item_id, SearchTerminalStatus.SUCCESS_ZERO_RESULTS)

    provider = FakeProvider(outcome)
    executor = SearchExecutor({SearchProviderId.GOOGLE_NEWS_RSS: provider}, sleep=clock.append, **kwargs)
    return executor.execute(_plan()), provider.calls, clock


def test_production_values():
    assert search_executor.SEARCH_PACING_SECONDS == 1.0
    assert search_executor.SEARCH_RATE_LIMIT_RETRY_SECONDS == 60.0


def test_spacing_between_requests_but_not_before_the_first():
    result, calls, clock = _run({}, pacing_seconds=1.0, rate_limit_retry_seconds=60.0)
    assert calls == ["item-0", "item-1", "item-2"]
    assert clock == [1.0, 1.0]
    assert result.rate_limit_retried_item_ids == ()


def test_a_rate_limit_is_retried_once_after_the_delay_and_the_retry_is_final():
    rate = _failure("item-1", SearchTechnicalFailureClass.RATE_LIMIT)
    result, calls, clock = _run({"item-1": [rate]}, pacing_seconds=1.0, rate_limit_retry_seconds=60.0)
    assert calls == ["item-0", "item-1", "item-1", "item-2"]
    assert clock == [1.0, 60.0, 1.0]
    assert result.rate_limit_retried_item_ids == ("item-1",)
    assert result.attempt_results[1].status is SearchTerminalStatus.SUCCESS_ZERO_RESULTS


def test_a_second_rate_limit_stays_a_disclosed_gap():
    rate = _failure("item-0", SearchTechnicalFailureClass.RATE_LIMIT)
    result, calls, clock = _run({"item-0": [rate, rate]}, pacing_seconds=1.0, rate_limit_retry_seconds=60.0)
    assert calls == ["item-0", "item-0", "item-1", "item-2"]  # no third attempt
    assert clock == [60.0, 1.0, 1.0]
    assert result.attempt_results[0].technical_failure_class is SearchTechnicalFailureClass.RATE_LIMIT
    assert result.rate_limit_retried_item_ids == ("item-0",)


@pytest.mark.parametrize(
    "failure_class",
    [c for c in SearchTechnicalFailureClass if c is not SearchTechnicalFailureClass.RATE_LIMIT],
)
def test_other_failures_are_not_retried(failure_class):
    result, calls, clock = _run({"item-1": [_failure("item-1", failure_class)]}, pacing_seconds=1.0, rate_limit_retry_seconds=60.0)
    assert calls == ["item-0", "item-1", "item-2"]
    assert clock == [1.0, 1.0]
    assert result.attempt_results[1].technical_failure_class is failure_class


def test_without_a_retry_delay_nothing_is_retried():
    rate = _failure("item-1", SearchTechnicalFailureClass.RATE_LIMIT)
    result, calls, clock = _run({"item-1": [rate]})
    assert calls == ["item-0", "item-1", "item-2"] and clock == []


def test_retried_ids_must_be_attempted_items():
    result, _, _ = _run({})
    with pytest.raises(ValueError):
        SearchExecutionResult(
            result.plan,
            attempt_results=result.attempt_results[:2],
            unattempted_items=result.plan.items[2:],
            observations=result.observations,
            rate_limit_retried_item_ids=("item-2",),
        )


def test_production_runner_uses_the_production_waits():
    # tests/conftest.py sets the runner's waits to 0 for offline runs; the
    # runner reads them from search_executor's production constants.
    import inspect

    source = inspect.getsource(production_runner.ProductionRunner.from_environment)
    assert "pacing_seconds=SEARCH_PACING_SECONDS" in source
    assert "rate_limit_retry_seconds=SEARCH_RATE_LIMIT_RETRY_SECONDS" in source


def test_the_run_summary_shows_the_retries():
    from datetime import date

    from src.weekly_report.contracts import RegionMode

    result = production_runner.ProductionRunResult(
        production_runner.ProductionRunStatus.SUCCESS,
        date(2026, 11, 16),
        date(2026, 11, 22),
        RegionMode.SELECTED,
        {},
        search_rate_limit_retries=3,
    )
    assert "search_rate_limit_retries=3" in result.summary()
    with pytest.raises(ValueError):
        production_runner.ProductionRunResult(
            production_runner.ProductionRunStatus.SUCCESS, date(2026, 11, 16), date(2026, 11, 22),
            RegionMode.SELECTED, {}, search_rate_limit_retries=-1,
        )


def test_the_date_operators_come_first():
    from datetime import date
    from urllib.parse import parse_qs, urlsplit

    from src.weekly_report.contracts import SearchWindow
    from src.weekly_report.google_news_rss_provider import GoogleNewsRssProvider
    from src.weekly_report.region_registry import RegionRegistry
    from src.weekly_report.search_planner import SearchPlanner

    plan = SearchPlanner(RegionRegistry.from_file()).plan(
        "selected", window=SearchWindow(date(2026, 11, 16), date(2026, 11, 22))
    )
    for item in plan.items:
        q = parse_qs(urlsplit(GoogleNewsRssProvider.request_url(item)).query)["q"][0]
        assert q == f"after:2026-11-16 before:2026-11-23 {item.query}"
        if item.query_family_id != "urban_rail_or_groups_compact":
            assert len(q) <= 200  # Google News reads only the first 200 characters (RC-88)
