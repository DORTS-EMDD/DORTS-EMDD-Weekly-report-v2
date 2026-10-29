"""RC-30: which Event Identity request failed, and why, is observable (Debug only).

Run 40653585176 merged nothing (63 records -> 63 events) with one EventIdentity
TechnicalGap, but neither the trace nor the run summary said whether the batch,
one group or one confirmation failed, or with which failure class. These tests
pin the observation and the unchanged grouping outcomes it observes.
"""

from __future__ import annotations

from src.weekly_report.contracts import SemanticProviderTechnicalFailure, TechnicalGapKind
from src.weekly_report.debug_service import event_identity_projection, technical_gap_signature
from src.weekly_report.event_identity import EventIdentity, proposal_subject_level
from tests.test_event_identity_contract import _record
from tests.test_event_identity_grouping_rc15 import _Scripted, _confirm, _member


def _station_reports():
    """Two sources of one occurrence and a different occurrence at the same station."""
    return [
        _record("JA", facts=None, published_at="2026-10-26T09:00:00Z",
                body="醍醐駅で10月26日、乗客のモバイルバッテリーが発火した。列車は一時運転を見合わせた。"),
        _record("EN", facts=None, published_at="2026-10-26T12:00:00Z",
                body="A passenger's power bank caught fire at Daigo Station on October 26. Trains were briefly halted."),
        _record("OTHER", facts=None, published_at="2026-10-21T08:00:00Z",
                body="醍醐駅のエスカレーターが10月21日に故障し、終日停止した。"),
    ]


def _groups(run):
    return sorted(group.member_candidate_ids for group in run.groups)


def test_two_sources_of_one_occurrence_merge_and_another_occurrence_at_the_same_station_does_not():
    advisor = _Scripted({"groups": [{"members": [_member("JA"), _member("EN")]}, {"members": [_member("OTHER")]}]},
                        _confirm("EN", "JA"))
    run = EventIdentity(advisor).evaluate(_station_reports())
    assert _groups(run) == [("EN", "JA"), ("OTHER",)]
    assert run.technical_gaps == ()
    projection = event_identity_projection(run)
    assert projection["event_identity_gap_distribution"] == {}
    assert projection["event_identity_diagnostic_distribution"]["SINGLE_MEMBER_PROPOSAL"] == 1


def test_an_unknown_record_voids_the_whole_batch_and_is_observed_as_a_batch_gap():
    # Contract section A.15: an unknown record_id invalidates the whole response.
    advisor = _Scripted({"groups": [{"members": [_member("JA"), _member("EN")]}, {"members": [_member("R99")]}]})
    run = EventIdentity(advisor).evaluate(_station_reports())
    assert _groups(run) == [("EN",), ("JA",), ("OTHER",)]
    assert len(advisor.requests) == 1
    assert event_identity_projection(run)["event_identity_gap_distribution"] == {
        "EventIdentity:BATCH:PROPOSAL_CONTRACT_VIOLATION:UNKNOWN_RECORD": 1
    }


def test_a_wrong_shape_voids_the_whole_batch_and_is_observed_as_a_batch_gap():
    run = EventIdentity(_Scripted({"groups": [{"members": [_member("JA"), _member("EN")]}], "note": "x"})).evaluate(
        _station_reports()
    )
    assert _groups(run) == [("EN",), ("JA",), ("OTHER",)]
    assert event_identity_projection(run)["event_identity_gap_distribution"] == {
        "EventIdentity:BATCH:PROPOSAL_CONTRACT_VIOLATION:SCHEMA_INVALID": 1
    }


def test_a_transport_failure_after_retry_is_observed_with_its_failure_class():
    failure = SemanticProviderTechnicalFailure("HTTP_502", attempts=2, transient=True)
    run = EventIdentity(_Scripted(failure)).evaluate(_station_reports())
    assert _groups(run) == [("EN",), ("JA",), ("OTHER",)]
    assert [gap.kind for gap in run.technical_gaps] == [TechnicalGapKind.TRANSIENT_FAILURE_AFTER_RETRY]
    assert event_identity_projection(run)["event_identity_gap_distribution"] == {
        "EventIdentity:BATCH:TRANSIENT_FAILURE_AFTER_RETRY:HTTP_502": 1
    }


def test_an_invalid_group_is_observed_at_group_level_and_other_groups_still_merge():
    records = _station_reports() + [
        _record("B1", facts=None, body="Line 2 trains were fitted with 5G Wi-Fi on October 21."),
        _record("B2", facts=None, body="2号線の全列車に10月21日、5G Wi-Fiが導入された。"),
    ]
    advisor = _Scripted(
        {"groups": [
            {"members": [_member("JA", subject_sentence_ids=["S99"]), _member("EN")]},
            {"members": [_member("B1"), _member("B2")]},
        ]},
        _confirm("B1", "B2"),
    )
    run = EventIdentity(advisor).evaluate(records)
    assert ("B1", "B2") in _groups(run)
    assert ("EN", "JA") not in _groups(run)
    assert event_identity_projection(run)["event_identity_gap_distribution"] == {
        "EventIdentity:GROUP:PROPOSAL_CONTRACT_VIOLATION:CITATION_INVALID": 1
    }


def test_an_incomplete_confirmation_is_observed_at_confirmation_level():
    advisor = _Scripted({"groups": [{"members": [_member("JA"), _member("EN")]}]}, {"groups": []})
    run = EventIdentity(advisor).evaluate(_station_reports())
    assert _groups(run) == [("EN",), ("JA",), ("OTHER",)]
    projection = event_identity_projection(run)
    assert projection["event_identity_gap_distribution"] == {
        "EventIdentity:CONFIRMATION:PROPOSAL_CONTRACT_VIOLATION:CONFIRMATION_INCOMPLETE": 1
    }
    assert projection["event_identity_diagnostic_distribution"]["PROPOSAL_NOT_CONFIRMED"] == 1


def test_an_invalid_confirmation_group_is_observed_at_confirmation_group_level():
    advisor = _Scripted(
        {"groups": [{"members": [_member("JA"), _member("EN")]}]},
        {"groups": [{"members": [_member("JA"), _member("JA"), _member("EN")]}]},
    )
    run = EventIdentity(advisor).evaluate(_station_reports())
    assert _groups(run) == [("EN",), ("JA",), ("OTHER",)]
    assert event_identity_projection(run)["event_identity_gap_distribution"] == {
        "EventIdentity:CONFIRMATION_GROUP:PROPOSAL_CONTRACT_VIOLATION:DUPLICATE_MEMBERSHIP": 1
    }


def test_subject_levels_follow_the_subject_ids_event_identity_forms():
    assert proposal_subject_level("event-identity-batch-1") == "BATCH"
    assert proposal_subject_level("event-identity-batch-1:group-3") == "GROUP"
    assert proposal_subject_level("event-identity-batch-1:group-3:confirmation") == "CONFIRMATION"
    assert proposal_subject_level("event-identity-batch-1:group-3:confirmation:group-1") == "CONFIRMATION_GROUP"


def test_signatures_carry_no_record_ids_or_source_text():
    records = [
        _record("cand_secret_a", facts=None, body="醍醐駅で10月26日、モバイルバッテリーが発火した。"),
        _record("cand_secret_b", facts=None, body="A power bank caught fire at Daigo Station on October 26."),
    ]
    advisor = _Scripted({"groups": [{"members": [_member("cand_secret_a"), _member("R99")]}]})
    run = EventIdentity(advisor).evaluate(records)
    rendered = repr(event_identity_projection(run)) + "".join(technical_gap_signature(gap) for gap in run.technical_gaps)
    for secret in ("cand_secret", "R99", "醍醐", "Daigo", "event-identity-batch"):
        assert secret not in rendered
