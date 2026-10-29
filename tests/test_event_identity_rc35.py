"""RC-35: a confirmation answers one group per occurrence (section A.27).

A proposed group may hold more than one occurrence (section A.17). Until RC-35
the confirmation instruction described one occurrence group plus
single-record groups, so the second occurrence of a mixed group could not be
confirmed. The Python owner and the schema already accepted one group per
occurrence; these tests lock that answer shape and the unchanged guarantees.
Fixture texts are generic.
"""

from __future__ import annotations

from src.weekly_report.contracts import EventIdentityGroupingRecord, EventIdentityGroupingRequest
from src.weekly_report.debug_service import event_identity_projection
from src.weekly_report.event_identity import (
    EVENT_IDENTITY_CONFIRMATION_RESPONSE_SCHEMA,
    EVENT_IDENTITY_GROUPING_RESPONSE_SCHEMA,
    EventIdentity,
)
from src.weekly_report.evidence_sentences import segment_evidence_sentences
from src.weekly_report.maiagent_event_identity_provider import build_maiagent_event_identity_model_input
from tests.test_event_identity_contract import _record
from tests.test_event_identity_grouping_rc15 import _Scripted, _confirm, _member
from tests.test_event_identity_rc31 import _located


def _instructions(confirmation):
    records = tuple(
        EventIdentityGroupingRecord(f"R{index}", f"cand-{index}", segment_evidence_sentences("A tram line opened."), {})
        for index in (1, 2)
    )
    request = EventIdentityGroupingRequest("event-identity-batch-1", records, confirmation=confirmation)
    return build_maiagent_event_identity_model_input(request)["instructions"]


def _groups(run):
    return sorted(group.member_candidate_ids for group in run.groups)


def _records():
    return [
        _record("LAUNCH1", facts=None, body="The operator started 5G Wi-Fi service on every car of Lines 1 and 2 on 21 October."),
        _record("LAUNCH2", facts=None, body="From 21 October all cars on Lines 1 and 2 carry 5G-backed Wi-Fi, the operator said."),
        _record("RIDE1", facts=None, body="On 21 October the ministry held a ride event on Line 2 to check the upgraded Wi-Fi."),
        _record("RIDE2", facts=None, body="A vice minister and a citizen panel rode Line 2 on 21 October to test the new Wi-Fi."),
        _record("COUNCIL", facts=None, body="On 23 October a lawmaker urged the ministry to extend subway 5G Wi-Fi nationwide."),
    ]


_BATCH = {"groups": [{"members": [_member(name) for name in ("LAUNCH1", "LAUNCH2", "RIDE1", "RIDE2", "COUNCIL")]}]}


# --- the instruction --------------------------------------------------------------


def test_the_confirmation_instruction_asks_for_one_group_per_occurrence():
    confirmation = [line for line in _instructions(True) if "confirmation is true" in line]
    assert len(confirmation) == 1
    line = confirmation[0]
    assert "one group for each occurrence" in line
    assert "Never put records of different occurrences in one group" in line
    assert "single-record group" in line and "Do not leave any record out" in line
    # The pre-RC-35 wording allowed only one occurrence group per confirmation.
    assert "the records that report the same occurrence together in one group" not in line


def test_the_grouping_instruction_and_both_schemas_are_unchanged():
    batch_only = [line for line in _instructions(False) if line.startswith("When event_identity_request.confirmation is false")]
    assert batch_only == [
        "When event_identity_request.confirmation is false: return only groups of two or more records that report "
        "the same event. Leave every other record out; do not return single-record groups. Put all records of one "
        "event into a single group; never split one event across two groups."
    ]
    members = lambda schema: schema["properties"]["groups"]["items"]["properties"]["members"]["minItems"]  # noqa: E731
    assert (members(EVENT_IDENTITY_GROUPING_RESPONSE_SCHEMA), members(EVENT_IDENTITY_CONFIRMATION_RESPONSE_SCHEMA)) == (2, 1)


# --- owner outcomes (decision logic unchanged) -------------------------------------


def test_a_mixed_group_confirms_each_occurrence_and_keeps_them_apart():
    run = EventIdentity(
        _Scripted(_BATCH, _confirm("LAUNCH1", "LAUNCH2", also=[("RIDE1", "RIDE2")], separate=("COUNCIL",)))
    ).evaluate(_records())
    assert _groups(run) == [("COUNCIL",), ("LAUNCH1", "LAUNCH2"), ("RIDE1", "RIDE2")]
    assert run.technical_gaps == ()
    # 10 proposed pairs, 2 confirmed; the 8 across occurrences stay apart.
    assert event_identity_projection(run)["event_identity_unconfirmed_distribution"] == {"SEPARATED": 8}


def test_the_former_single_occurrence_answer_leaves_the_second_occurrence_unmerged():
    # The shape the pre-RC-35 wording called for; the owner treats it as before.
    run = EventIdentity(
        _Scripted(_BATCH, _confirm("LAUNCH1", "LAUNCH2", separate=("RIDE1", "RIDE2", "COUNCIL")))
    ).evaluate(_records())
    assert _groups(run) == [("COUNCIL",), ("LAUNCH1", "LAUNCH2"), ("RIDE1",), ("RIDE2",)]


def test_a_confirmation_never_adds_a_pair_the_batch_did_not_keep():
    records = [
        _located("JP1", "JP", "Japan", "Maintenance cars get an AI assistant, announced on 27 October."),
        _located("JP2", "JP", "Japan", "An AI assistant for maintenance cars was announced on 27 October."),
        _located("IT1", "IT", "Italy", "Tram tests begin in November."),
        _located("IT2", "IT", "Italy", "Trial runs on the tram line begin in November."),
    ]
    batch = {"groups": [{"members": [_member(name) for name in ("JP1", "JP2", "IT1", "IT2")]}]}
    # The confirmation also places the cross-region pair JP1/IT1 together: RC-22 already dropped it.
    run = EventIdentity(_Scripted(batch, _confirm("JP1", "JP2", "IT1", also=[("IT2",)]))).evaluate(records)
    assert _groups(run) == [("IT1",), ("IT2",), ("JP1", "JP2")]


def test_an_omitted_record_stays_undecided_when_other_occurrences_are_confirmed():
    run = EventIdentity(
        _Scripted(_BATCH, _confirm("LAUNCH1", "LAUNCH2", also=[("RIDE1", "RIDE2")]))  # COUNCIL left out
    ).evaluate(_records())
    assert _groups(run) == [("COUNCIL",), ("LAUNCH1", "LAUNCH2"), ("RIDE1", "RIDE2")]
    assert [gap.failure_class for gap in run.technical_gaps] == ["CONFIRMATION_INCOMPLETE"]
    unconfirmed = event_identity_projection(run)["event_identity_unconfirmed_distribution"]
    assert unconfirmed == {"OMITTED": 4, "SEPARATED": 4}


def test_one_group_holding_records_of_two_occurrences_is_the_helpers_error_not_masked():
    # Python cannot tell occurrences apart; it takes the confirmed group as given.
    # The instruction forbids this answer; the region check is the only Python guard.
    run = EventIdentity(
        _Scripted(_BATCH, _confirm("LAUNCH1", "LAUNCH2", "RIDE1", "RIDE2", separate=("COUNCIL",)))
    ).evaluate(_records())
    assert _groups(run) == [("COUNCIL",), ("LAUNCH1", "LAUNCH2", "RIDE1", "RIDE2")]
