"""RC-32: what the grouping helper was shown for each record is observable.

Run 40817530617 kept three duplicate sets. Reconstructing the requests offline
showed the decisive Evidence was in the excerpts for two of them, and that
one record's excerpt (its Scope event focus) left out the sentences that
describe its occurrence. Answering this needed the published pages fetched
again; these tests pin the Debug-only observation that records the excerpt
sentence IDs and limits instead, and that it changes no grouping outcome.
"""

from __future__ import annotations

from dataclasses import replace

from src.weekly_report.event_identity import LEAD_TIERS, EventIdentity
from src.weekly_report.evidence_sentences import segment_evidence_sentences
from tests.test_event_identity_contract import _record
from tests.test_event_identity_grouping_rc15 import _Scripted, _confirm, _member


def _focused(candidate_id, body, focus_ids):
    record = _record(candidate_id, facts=None, body=body)
    spans = [
        {"start": sentence.start, "end": sentence.end}
        for sentence in segment_evidence_sentences(body)
        if sentence.sentence_id in focus_ids
    ]
    return replace(record, scope=replace(record.scope, provenance={"candidate_event_focus": spans}))


def _lede():
    return _member("LEDE", subject_sentence_ids=["S2"], occurrence_sentence_ids=["S2"], lifecycle_sentence_ids=["S2"])


def _records():
    return [
        _focused(
            "LEDE",
            "Page header text. The ministry confirmed the upgrade results on 21 October. "
            "It held a ride event on Line 2 that day. Eleven citizens took part.",
            {"S2"},
        ),
        _focused("EVENT", "The ministry held a ride event on Line 2 on 21 October to check the new Wi-Fi.", {"S1"}),
    ]


def test_the_run_records_the_sentences_each_record_was_sent_with_and_the_limits():
    advisor = _Scripted({"groups": [{"members": [_lede(), _member("EVENT")]}]}, {"groups": [{"members": [_lede(), _member("EVENT")]}]})
    run = EventIdentity(advisor).evaluate(_records())
    sent = {record.candidate_id: tuple(s.sentence_id for s in record.sentences) for record in advisor.requests[0].records}
    assert dict(run.proposal_excerpts) == sent == {"LEDE": ("S2",), "EVENT": ("S1",)}
    assert run.proposal_excerpt_limits == f"{LEAD_TIERS[0][0]}x{LEAD_TIERS[0][1]}"
    assert sorted(group.member_candidate_ids for group in run.groups) == [("EVENT", "LEDE")]


def test_the_observation_changes_no_grouping_outcome():
    advisor = _Scripted({"groups": [{"members": [_lede(), _member("EVENT")]}]}, {"groups": [{"members": [_lede()]}, {"members": [_member("EVENT")]}]})
    run = EventIdentity(advisor).evaluate(_records())
    assert sorted(group.member_candidate_ids for group in run.groups) == [("EVENT",), ("LEDE",)]
    assert [item.reason for item in run.diagnostics if item.reason == "PROPOSAL_NOT_CONFIRMED"] == ["PROPOSAL_NOT_CONFIRMED"]


def test_without_a_grouping_request_nothing_is_recorded():
    run = EventIdentity().evaluate(_records())
    assert dict(run.proposal_excerpts) == {} and run.proposal_excerpt_limits == ""
