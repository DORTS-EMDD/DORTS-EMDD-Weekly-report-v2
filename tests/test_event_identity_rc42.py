"""RC-42: per-member proposal validation and request presentation (section A.30).

Run 40985179898 lost a correct two-report group to one unresolvable citation
(CITATION_INVALID), and run 40838021391 a large group to one repeated record
(DUPLICATE_MEMBERSHIP): one member's defect voided every other member's pairs.
Validation is now per member. Records are ordered by publication time, not by
the weekday text of the RSS date, and each excerpt is numbered from S1 within
the request (a one-sentence excerpt that kept its document ID S2 was cited as
S1). Fixture texts are generic.
"""

from __future__ import annotations

from src.weekly_report.contracts import EventIdentityGroupingRecord, EventIdentityGroupingRequest
from src.weekly_report.debug_service import event_identity_projection
from src.weekly_report.event_identity import EventIdentity
from src.weekly_report.evidence_sentences import segment_evidence_sentences
from src.weekly_report.maiagent_event_identity_provider import PROMPT_VERSION, build_maiagent_event_identity_model_input
from tests.test_event_identity_contract import _record
from tests.test_event_identity_grouping_rc15 import _Scripted, _confirm, _member


def _scripted(*responses):
    """These tests examine one nomination's validation: the second nomination proposes nothing (RC-44)."""

    return _Scripted(*responses, second={"groups": []})

BODIES = {
    "A": "The council decided on 20 October to move the tram depot after surveys found a gas main.",
    "B": "A gas main under the plaza led the council to relocate the tram depot, it resolved on 20 October.",
    "C": "Councillors approved shifting the tram depot on 20 October, citing a gas main found in the survey.",
    "D": "Firefighters held an evacuation drill at an underground station on 21 October.",
}
UNGROUNDED = {"occurrence_sentence_ids": ["S9"]}
SINGLE = {"subject_sentence_ids": [], "occurrence_sentence_ids": [], "lifecycle_sentence_ids": []}


def _records():
    return [_record(name, facts=None, body=body) for name, body in BODIES.items()]


def _groups(run):
    return sorted(group.member_candidate_ids for group in run.groups)


def _gaps(run):
    return [(gap.subject_id, gap.failure_class) for gap in run.technical_gaps]


def _diagnostics(run, reason):
    return [(item.candidate_ids, item.detail) for item in run.diagnostics if item.reason == reason]


def _batch(*groups):
    return {"groups": [{"members": list(group)} for group in groups]}


# --- per-member validation ---------------------------------------------------------


def test_an_ungrounded_member_is_rejected_and_the_grounded_members_still_merge():
    advisor = _scripted(
        _batch([_member("A"), _member("B"), _member("C", **UNGROUNDED)], [_member("D", **SINGLE)]),
        _confirm("A", "B"),
    )
    run = EventIdentity(advisor).evaluate(_records())
    assert _groups(run) == [("A", "B"), ("C",), ("D",)]
    assert _gaps(run) == [("event-identity-batch-1:group-1", "CITATION_INVALID")]
    assert _diagnostics(run, "PROPOSAL_MEMBER_REJECTED") == [(("C",), "event-identity-batch-1:group-1|CITATION_INVALID")]
    # The rejected member is never sent to the confirmation, so it cannot be confirmed.
    assert [record.candidate_id for record in advisor.requests[1].records] == ["A", "B"]


def test_a_repeated_member_is_rejected_and_the_others_still_merge():
    advisor = _scripted(
        _batch([_member("A"), _member("B"), _member("C"), _member("A")], [_member("D", **SINGLE)]),
        _confirm("B", "C"),
    )
    run = EventIdentity(advisor).evaluate(_records())
    assert _groups(run) == [("A",), ("B", "C"), ("D",)]
    assert _gaps(run) == [("event-identity-batch-1:group-1", "DUPLICATE_MEMBERSHIP")]
    assert _diagnostics(run, "PROPOSAL_MEMBER_REJECTED") == [(("A",), "event-identity-batch-1:group-1|DUPLICATE_MEMBERSHIP")]


def test_both_defects_in_one_group_are_each_disclosed():
    records = _records() + [_record("E", facts=None, body="The council moved the tram depot on 20 October over a gas main.")]
    advisor = _scripted(
        _batch([_member("A"), _member("A"), _member("B"), _member("C", **UNGROUNDED), _member("E")]),
        _confirm("B", "E"),
    )
    run = EventIdentity(advisor).evaluate(records)
    assert ("B", "E") in _groups(run)
    assert _gaps(run) == [
        ("event-identity-batch-1:group-1", "DUPLICATE_MEMBERSHIP"),
        ("event-identity-batch-1:group-1", "CITATION_INVALID"),
    ]


def test_a_group_left_with_one_grounded_member_proposes_no_merge():
    run = EventIdentity(_scripted(_batch([_member("A"), _member("B", **UNGROUNDED)]))).evaluate(_records())
    assert _groups(run) == [("A",), ("B",), ("C",), ("D",)]
    assert _gaps(run) == [("event-identity-batch-1:group-1", "CITATION_INVALID")]
    # A is not "proposed alone": its partner was rejected.
    assert _diagnostics(run, "SINGLE_MEMBER_PROPOSAL") == []


def test_a_rejected_confirmation_member_leaves_its_pairs_unconfirmed_and_the_rest_confirmed():
    advisor = _scripted(
        _batch([_member("A"), _member("B"), _member("C")], [_member("D", **SINGLE)]),
        _batch([_member("A"), _member("B"), _member("C", **UNGROUNDED)]),
    )
    run = EventIdentity(advisor).evaluate(_records())
    assert _groups(run) == [("A", "B"), ("C",), ("D",)]
    assert _gaps(run) == [("event-identity-batch-1:group-1:confirmation:group-1", "CITATION_INVALID")]
    assert event_identity_projection(run)["event_identity_unconfirmed_distribution"] == {"MEMBER_INVALID": 2}


# --- instruction ------------------------------------------------------------------


def test_a_single_record_batch_group_proposes_nothing_and_needs_no_citation():
    advisor = _scripted(_batch([_member("A"), _member("B"), _member("C")], [_member("D", **SINGLE)]), _confirm("A", "B", "C"))
    run = EventIdentity(advisor).evaluate(_records())
    assert _groups(run) == [("A", "B", "C"), ("D",)]
    assert run.technical_gaps == ()
    assert _diagnostics(run, "SINGLE_MEMBER_PROPOSAL") == [(("D",), "")]


def test_the_instruction_says_omitted_details_do_not_make_a_different_occurrence():
    records = tuple(
        EventIdentityGroupingRecord(f"R{index}", f"cand-{index}", segment_evidence_sentences("A tram line opened."), {})
        for index in (1, 2)
    )
    instructions = build_maiagent_event_identity_model_input(EventIdentityGroupingRequest("b", records))["instructions"]
    assert PROMPT_VERSION == "event-identity-grouping-v8"
    line = [item for item in instructions if item.startswith("A record that leaves out a detail")]
    assert line == [
        "A record that leaves out a detail another record states (an actor, a date, a place, a figure), or states a "
        "non-identifying detail differently, is not thereby a different occurrence; decide from the details the "
        "records do state."
    ]
    # The fail-closed rule still stands beside it.
    assert any(item.startswith("When the evidence does not establish that two records report the same occurrence") for item in instructions)


# --- request presentation -----------------------------------------------------------


def test_records_are_ordered_by_publication_time_not_by_the_weekday_text():
    # RSS dates start with the weekday; Wed 21 must precede Fri 23 and Mon 26.
    records = [
        _record("MON26", facts=None, body="A tram derailed on 26 October.", published_at="Mon, 26 Oct 2026 03:00:00 GMT"),
        _record("FRI23", facts=None, body="A depot opened on 23 October.", published_at="Fri, 23 Oct 2026 09:00:00 GMT"),
        _record("WED21", facts=None, body="Wi-Fi started on 21 October.", published_at="Wed, 21 Oct 2026 07:00:00 GMT"),
        _record("ISO22", facts=None, body="A line closed on 22 October.", published_at="2026-10-22T05:00:00Z"),
    ]
    advisor = _scripted(_batch())
    EventIdentity(advisor).evaluate(records)
    assert [record.candidate_id for record in advisor.requests[0].records] == ["WED21", "ISO22", "FRI23", "MON26"]
    assert [record.record_id for record in advisor.requests[0].records] == ["R1", "R2", "R3", "R4"]


def test_each_excerpt_is_numbered_from_s1_and_keeps_its_document_ids_for_observation():
    from dataclasses import replace

    from src.weekly_report.contracts import ScopeResult, ScopeState

    body = "Page header. Menu text. The operator handed over the 1,000th car on 23 October."
    focus = [{"start": body.index("The operator"), "end": len(body)}]
    single = replace(
        _record("ONE", facts=None, body=body),
        scope=ScopeResult("ONE", ScopeState.IN_SCOPE, provenance={"candidate_event_focus": focus}),
    )
    other = _record("TWO", facts=None, body="The 1,000th car was handed over to the operator on 23 October.")
    advisor = _scripted(_batch([_member("ONE"), _member("TWO")]), _confirm("ONE", "TWO"))
    run = EventIdentity(advisor).evaluate([single, other])
    sent = {record.candidate_id: [s.sentence_id for s in record.sentences] for record in advisor.requests[0].records}
    assert sent == {"ONE": ["S1"], "TWO": ["S1"]}
    assert dict(run.proposal_excerpts) == {"ONE": ("S3",), "TWO": ("S1",)}
    # Citing S1 for a one-sentence excerpt now resolves, so the pair merges.
    assert _groups(run) == [("ONE", "TWO")] and run.technical_gaps == ()


def test_the_instruction_asks_every_citation_list_to_name_a_sentence():
    records = tuple(
        EventIdentityGroupingRecord(f"R{index}", f"cand-{index}", segment_evidence_sentences("A tram line opened."), {})
        for index in (1, 2)
    )
    instructions = build_maiagent_event_identity_model_input(EventIdentityGroupingRequest("b", records))["instructions"]
    citation = [line for line in instructions if line.startswith("For every member cite sentence_ids")]
    assert len(citation) == 1
    assert "Each of the three lists names at least one sentence" in citation[0]
    assert "cite the occurrence sentence as the step too" in citation[0]
