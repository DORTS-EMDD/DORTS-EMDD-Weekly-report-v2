"""Test-only: pin Event Identity to one proposal procedure (RC-52, section A.38).

Production runs the RC-23/RC-44 proposal procedure AGREEMENT_PROCEDURES times
and needs AGREEMENT_REQUIRED of them to confirm a pair. Tests that pin the
mechanics of one procedure (its requests, gaps and diagnostics in order)
import this autouse fixture; the agreement across procedures is pinned in
tests/test_event_identity_rc52.py, and Golden runs with the production values.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.weekly_report import event_identity


@pytest.fixture(autouse=True)
def _single_proposal_procedure(monkeypatch):
    monkeypatch.setattr(event_identity, "AGREEMENT_PROCEDURES", 1)
    monkeypatch.setattr(event_identity, "AGREEMENT_REQUIRED", 1)


def single_proposal_procedure(test):
    """Decorator form for a single test in a module that otherwise runs the production values."""

    return patch.multiple(event_identity, AGREEMENT_PROCEDURES=1, AGREEMENT_REQUIRED=1)(test)
