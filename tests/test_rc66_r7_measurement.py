"""Offline tests for the RC66-R7 measurement-only infrastructure."""

from __future__ import annotations

import json

import pytest

from scripts.rc66_r7_measurement import BudgetExceeded, MeteredTransport, _batch_score
from src.weekly_report.event_identity import EventIdentity
from src.weekly_report.maiagent_transport import MaiAgentHttpResponse
from tests.test_event_identity_contract import _record


def _empty_response() -> MaiAgentHttpResponse:
    return MaiAgentHttpResponse(200, b'{"content":"{\\"groups\\":[]}"}')


def test_measurement_reads_the_authoritative_event_identity_observation_surface():
    advisor = lambda _request: {"groups": []}
    run = EventIdentity(advisor).evaluate([
        _record("A", facts=None, body="A report about one occurrence."),
        _record("B", facts=None, body="B report about another occurrence."),
    ])

    assert hasattr(run, "proposal_exchanges")
    assert not hasattr(run, "exchanges")
    summary = _batch_score(run, {"A": "A", "B": "B"}, {"A", "B"})
    assert summary["proposal_exchanges"] == len(run.proposal_exchanges)


def test_call_ledger_reserves_before_network_and_survives_reload(tmp_path):
    journal = tmp_path / "rc66_r7_call_journal.json"
    meter = MeteredTransport(4, journal, prior_call_upper_bound=0)
    observed: dict[str, object] = {}

    def fake_transport(_endpoint, *, headers, body, timeout_seconds):
        del headers, body, timeout_seconds
        persisted = json.loads(journal.read_text(encoding="utf-8"))
        observed.update(persisted)
        return _empty_response()

    meter._real = fake_transport
    meter("https://example.invalid", headers={}, body=b"one", timeout_seconds=1)

    assert observed["attempted_calls"] == 1
    assert observed["log"][0]["state"] == "IN_FLIGHT"
    final = json.loads(journal.read_text(encoding="utf-8"))
    assert final["attempted_calls"] == 1
    assert final["completed_calls"] == 1
    assert final["remaining_calls"] == 3

    resumed = MeteredTransport(4, journal)
    assert resumed.calls == 1
    assert resumed.completed_calls == 1
    assert resumed.remaining_calls == 3


def test_call_ledger_fails_closed_at_cumulative_cap(tmp_path):
    journal = tmp_path / "rc66_r7_call_journal.json"
    meter = MeteredTransport(4, journal, prior_call_upper_bound=3)
    meter._real = lambda *_args, **_kwargs: _empty_response()
    meter("https://example.invalid", headers={}, body=b"one", timeout_seconds=1)

    resumed = MeteredTransport(4, journal)
    with pytest.raises(BudgetExceeded):
        resumed("https://example.invalid", headers={}, body=b"two", timeout_seconds=1)
    assert resumed.calls == 4
    assert resumed.remaining_calls == 0


def test_new_campaign_requires_an_explicit_prior_bound(tmp_path):
    with pytest.raises(RuntimeError, match="prior-call count"):
        MeteredTransport(4, tmp_path / "missing.json")
