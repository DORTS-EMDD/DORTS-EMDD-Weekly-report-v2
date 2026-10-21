"""Resumable external-I/O journal used by long acceptance runs."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from run_journal import BudgetExhausted, RunJournal, request_key  # noqa: E402


def _journal(tmp_path, *, http=10, maiagent=10, seconds=3600):
    return RunJournal(tmp_path / "journal", limits={"http": http, "maiagent": maiagent}, seconds_limit=seconds)


def _call(journal, key, live, **kwargs):
    return journal.call("fetch", "http", key, live, encode=lambda r: {"v": r}, decode=lambda d: d["v"], **kwargs)


def test_recorded_response_is_replayed_without_a_live_call(tmp_path):
    calls = []
    first = _journal(tmp_path)
    assert _call(first, "k", lambda: calls.append(1) or "page") == "page"
    resumed = _journal(tmp_path)
    assert _call(resumed, "k", lambda: calls.append(1) or "other") == "page"
    assert calls == [1]
    assert resumed.ledger["live"] == {"http": 1}
    assert resumed.ledger["replayed"] == {"fetch": 1}
    assert len(resumed.ledger["attempts"]) == 2


def test_budget_is_cumulative_across_attempts_and_prior_spend(tmp_path):
    first = _journal(tmp_path, http=3)
    first.record_prior_spend({"http": 2}, "attempt without journal")
    _call(first, "a", lambda: "x")
    resumed = _journal(tmp_path, http=3)
    resumed.record_prior_spend({"http": 2}, "booked once only")
    with pytest.raises(BudgetExhausted):
        _call(resumed, "b", lambda: "y")
    assert resumed.ledger["live"]["http"] == 3


def test_transient_outcomes_are_not_recorded(tmp_path):
    journal = _journal(tmp_path)
    with pytest.raises(TimeoutError):
        _call(journal, "t", lambda: (_ for _ in ()).throw(TimeoutError("slow")), keep_failure=lambda exc: False)
    assert _call(journal, "t", lambda: "now ok") == "now ok"
    assert _call(journal, "r", lambda: "503", keep_response=lambda r: r != "503") == "503"
    assert _call(journal, "r", lambda: "200", keep_response=lambda r: r != "503") == "200"
    assert journal.ledger["live"]["http"] == 4


def test_definitive_failure_replays_with_the_same_type_name(tmp_path):
    class SSLCertVerificationError(OSError):
        pass

    journal = _journal(tmp_path)
    with pytest.raises(SSLCertVerificationError):
        _call(journal, "f", lambda: (_ for _ in ()).throw(SSLCertVerificationError("bad cert")))
    resumed = _journal(tmp_path)
    with pytest.raises(OSError) as replayed:
        _call(resumed, "f", lambda: pytest.fail("must not call live"))
    assert type(replayed.value).__name__ == "SSLCertVerificationError"


def test_seed_never_overwrites_and_keys_are_unambiguous(tmp_path):
    journal = _journal(tmp_path)
    key = request_key("maiagent", b"body")
    assert journal.seed("maiagent", key, {"response": {"v": 1}}) is True
    assert journal.seed("maiagent", key, {"response": {"v": 2}}) is False
    assert request_key("ab", "c") != request_key("a", "bc")


def test_prior_seconds_count_against_the_wall_clock(tmp_path):
    journal = _journal(tmp_path, seconds=100)
    journal.record_prior_spend({"seconds": 150}, "killed attempt")
    with pytest.raises(BudgetExhausted):
        _call(journal, "late", lambda: "x")
