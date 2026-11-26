"""Shared test configuration."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_search_waits(monkeypatch):
    # RC-88: production Search waits 1 s between requests and 60 s before the
    # one retry of a RATE_LIMIT. Offline tests that compose the production
    # runner must not sleep; tests/test_search_executor_rc88.py checks the
    # waits with an injected clock and the production values directly.
    from src.weekly_report import production_runner

    monkeypatch.setattr(production_runner, "SEARCH_PACING_SECONDS", 0.0)
    monkeypatch.setattr(production_runner, "SEARCH_RATE_LIMIT_RETRY_SECONDS", 0.0)
