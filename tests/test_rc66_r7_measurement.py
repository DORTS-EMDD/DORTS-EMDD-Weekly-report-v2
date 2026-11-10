"""Offline tests for the RC66-R7 measurement-only infrastructure."""

from __future__ import annotations

import json

import pytest

from scripts.rc66_r7_measurement import (
    REQUIRED_DIRECT_GROUP_NAMES,
    BudgetExceeded,
    MeteredTransport,
    _batch_score,
    _full_focus,
)
from src.weekly_report.event_identity import _grouping_record
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


def test_new_campaign_identity_is_not_interchangeable_with_another_journal(tmp_path):
    journal = tmp_path / "rc66_r7_campaign_a.json"
    MeteredTransport(4, journal, prior_call_upper_bound=0, campaign_id="RC66-R7-CAMPAIGN-A")
    with pytest.raises(RuntimeError, match="invalid"):
        MeteredTransport(4, journal, campaign_id="RC66-R7-CAMPAIGN-B")


def test_scoreable_units_are_checkpointed_and_reloaded(tmp_path):
    journal = tmp_path / "rc66_r7_campaign.json"
    meter = MeteredTransport(4, journal, prior_call_upper_bound=0, campaign_id="RC66-R7-CAMPAIGN-A")
    assert meter.begin_unit("baseline|round-1|cited_focus_rc52", {"prompt": "baseline", "round": 1})
    meter.complete_unit("baseline|round-1|cited_focus_rc52", "rounds", {"events": 1})

    resumed = MeteredTransport(4, journal, campaign_id="RC66-R7-CAMPAIGN-A")
    assert resumed.completed_units["baseline|round-1|cited_focus_rc52"]["state"] == "SCOREABLE_COMPLETE"
    assert not resumed.begin_unit("baseline|round-1|cited_focus_rc52", {"prompt": "baseline", "round": 1})


def test_bh2_focus_is_the_validated_range_between_first_and_last_cited_sentence():
    record = _record("A", body="One. Two. Three. Four.", focus=("S2", "S4"))
    focused = _full_focus(record)
    grouping = _grouping_record(focused, "R1")

    assert grouping is not None
    assert grouping.source_sentence_ids == ("S2", "S3", "S4")


def test_frozen_direct_confirmation_groups_remain_explicit_and_complete():
    assert REQUIRED_DIRECT_GROUP_NAMES == (
        "mixed_incheon",
        "mixed_sydney",
        "pure_daegu",
        "pure_seoul",
        "pure_kim",
        "pure_ulsan",
        "incident_followup",
        "mega_29_group4",
        "mega_29_group5",
        "mega_31_group3",
    )
