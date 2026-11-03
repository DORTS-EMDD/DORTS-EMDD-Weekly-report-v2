"""RC-51 (section A.37): Evidence context after the Scope focus, focus-bound occurrence.

Live run 41405830454 left 34 same-event pairs apart. For most failing records
Event Identity was sent only the Scope focus (often one sentence) while the
details matching the other records were in the next sentences of the same,
hash-verified Evidence. RC-51 sends those sentences as context, marked apart
from the focus, in the room the focus leaves; the focus alone states the
record's event, and Python rejects a member whose occurrence citation leaves
its focus. These tests pin the information flow and the occurrence boundary;
they say nothing about the helper's recall.
"""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256

from src.weekly_report.contracts import EventIdentityGroupingRequest
from src.weekly_report.event_identity import (
    BATCH_CHARACTER_LIMIT,
    LEAD_TIERS,
    EventIdentity,
    _grouping_record,
    _grouping_requests,
    _validate_grouping_proposal,
)
from src.weekly_report.evidence_sentences import segment_evidence_sentences
from src.weekly_report.maiagent_event_identity_provider import (
    EVENT_IDENTITY_INSTRUCTIONS,
    build_maiagent_event_identity_model_input,
)
from tests.test_event_identity_contract import _record
from tests.test_event_identity_grouping_rc15 import _confirm, _member, _Scripted


def _focused(candidate_id, body, focus_ids):
    record = _record(candidate_id, facts=None, body=body)
    spans = [
        {"start": sentence.start, "end": sentence.end}
        for sentence in segment_evidence_sentences(body)
        if sentence.sentence_id in focus_ids
    ]
    return replace(record, scope=replace(record.scope, provenance={"candidate_event_focus": spans}))


# A launch record whose context also reports a separate ride event (the
# demonstrated Incheon risk), and a record whose focus is that ride event.
LAUNCH = (
    "The operator switched every car of Line 1 to 5G Wi-Fi on 21 October. "
    "All 272 cars received new access points. "
    "The ministry held a ride event on Line 2 that day."
)
RIDE = "The ministry held a ride event on Line 2 on 21 October to check the new Wi-Fi."


def _cite(candidate_id, occurrence, subject=("S1",)):
    return _member(
        candidate_id,
        subject_sentence_ids=list(subject),
        occurrence_sentence_ids=list(occurrence),
        lifecycle_sentence_ids=list(occurrence),
    )


def test_context_follows_the_focus_and_is_marked_apart():
    body = "Page header. The tram line opened on 3 May. It runs 12 km. Riders praised it."
    sent = _grouping_record(_focused("A", body, {"S2"}), "R1")
    assert [s.text for s in sent.focus_sentences] == ["The tram line opened on 3 May."]
    assert sent.source_sentence_ids == ("S2", "S3", "S4") and sent.context_sentence_count == 2
    assert [item["role"] for item in sent.as_payload()["evidence_sentences"]] == ["focus", "context", "context"]
    assert [item["sentence_id"] for item in sent.as_payload()["evidence_sentences"]] == ["S1", "S2", "S3"]


def test_a_record_without_a_focus_still_presents_its_lead_and_no_context():
    body = "The tram line opened on 3 May. It runs 12 km."
    sent = _grouping_record(_record("A", facts=None, body=body), "R1")
    assert sent.context_sentence_count == 0 and sent.source_sentence_ids == ("S1", "S2")


def test_the_focus_is_never_shortened_and_the_limits_bound_focus_and_context_together():
    long_focus = " ".join(f"Fact {index} of the opening." for index in range(1, 7))
    body = long_focus + " A later sentence."
    sent = _grouping_record(_focused("A", body, {f"S{index}" for index in range(1, 7)}), "R1")
    assert sent.context_sentence_count == 0 and len(sent.sentences) == LEAD_TIERS[0][0]
    wide = "The line opened. " + " ".join("X" * 300 + "." for _ in range(5))
    sent = _grouping_record(_focused("B", wide, {"S1"}), "R1")
    assert sum(len(s.text) for s in sent.sentences) <= LEAD_TIERS[0][1]
    assert sent.context_sentence_count == 2


def test_an_oversized_run_shortens_context_before_it_lowers_the_focus_tier():
    filler = " ".join(f"Detail {index} " + "y" * 120 + "." for index in range(5))
    records = [_focused(f"C{index:03d}", f"Event {index} happened on Line {index}. {filler}", {"S1"}) for index in range(120)]
    requests, limits, context_limit = _grouping_requests(records)
    focus_only = [_grouping_record(record, "R1", LEAD_TIERS[0], 0) for record in records]
    assert sum(len(str(item.as_payload())) for item in focus_only) < BATCH_CHARACTER_LIMIT
    assert limits == LEAD_TIERS[0] and 0 <= context_limit < LEAD_TIERS[0][0] - 1
    sent = requests[0].records
    assert [[s.text for s in item.focus_sentences] for item in sent] == [[s.text for s in item.sentences] for item in focus_only]
    assert all(item.context_sentence_count <= context_limit for item in sent)
    advisor = _Scripted({"groups": []})
    run = EventIdentity(advisor).evaluate(records)
    assert run.proposal_excerpt_limits == f"{LEAD_TIERS[0][0]}x{LEAD_TIERS[0][1]}+context{context_limit}"


def test_construction_is_deterministic():
    records = [_focused("L", LAUNCH, {"S1"}), _focused("R", RIDE, {"S1"})]
    first, second = _grouping_requests(records), _grouping_requests(list(reversed(records)))
    assert [r.as_payload() for r in first[0][0].records] == [r.as_payload() for r in second[0][0].records]


def test_an_occurrence_cited_only_in_context_is_rejected_and_never_merges():
    # The helper groups the launch record with the ride event through its
    # context sentence (S3): Python rejects that member, the pair stays apart.
    records = [_focused("L", LAUNCH, {"S1"}), _focused("R", RIDE, {"S1"})]
    advisor = _Scripted({"groups": [{"members": [_cite("L", ["S3"]), _cite("R", ["S1"])]}]})
    run = EventIdentity(advisor).evaluate(records)
    assert sorted(group.member_candidate_ids for group in run.groups) == [("L",), ("R",)]
    # Once per nomination (RC-44 sends the batch twice).
    assert [gap.failure_class for gap in run.technical_gaps] == ["OCCURRENCE_OUTSIDE_FOCUS"] * 2
    assert not any(request.confirmation for request in advisor.requests)


def test_a_focus_occurrence_with_context_details_merges_after_confirmation():
    other = _focused("O", "Line 1 now has 5G Wi-Fi in every car. The operator replaced 272 access points.", {"S1"})
    records = [_focused("L", LAUNCH, {"S1"}), other]
    nomination = {"groups": [{"members": [_cite("L", ["S1"], subject=("S1", "S2")), _cite("O", ["S1"], subject=("S2",))]}]}
    advisor = _Scripted(nomination, _confirm("L", "O"))
    run = EventIdentity(advisor).evaluate(records)
    assert sorted(group.member_candidate_ids for group in run.groups) == [("L", "O")]
    confirmation = next(request for request in advisor.requests if request.confirmation)
    assert {record.candidate_id: record.context_sentence_count for record in confirmation.records} == {"L": 2, "O": 1}


def test_the_guard_applies_to_confirmations_and_leaves_other_members_standing():
    records = [_focused(name, LAUNCH, {"S1"}) for name in ("A", "B", "C")]
    request = EventIdentityGroupingRequest(
        "b", tuple(_grouping_record(record, f"R{index}") for index, record in enumerate(records, start=1)), confirmation=True
    )
    raw = {"groups": [{"members": [
        {**_cite("A", ["S1"]), "record_id": "R1"},
        {**_cite("B", ["S1"]), "record_id": "R2"},
        {**_cite("C", ["S3"]), "record_id": "R3"},
    ]}]}
    ((accepted, violations),) = _validate_grouping_proposal(raw, request)
    assert accepted == ("A", "B")
    assert [(item.failure_class, item.candidate_ids) for item in violations] == [("OCCURRENCE_OUTSIDE_FOCUS", ("C",))]


def test_a_focus_anchored_occurrence_citation_may_add_context_details():
    # The Live helper cited several sentences for 83 of 103 members; citing
    # the focus plus a context detail of the same drill is not rejected, and
    # the pair still needs its confirmation (RC-23).
    a = _focused("A", "The operator held a fire drill at Duryu station on 20 October. Smoke filled the platform in the scenario. Crews entered the tunnel by trolley.", {"S1"})
    b = _focused("B", "A fire drill was held at Duryu station on 20 October. Smoke filled the platform in the scenario. Crews entered the tunnel by trolley.", {"S1", "S2", "S3"})
    nomination = {"groups": [{"members": [_cite("A", ["S1", "S2"]), _cite("B", ["S1", "S2"])]}]}
    run = EventIdentity(_Scripted(nomination, _confirm("A", "B"))).evaluate([a, b])
    assert [group.member_candidate_ids for group in run.groups] == [("A", "B")] and run.technical_gaps == ()
    separated = EventIdentity(_Scripted(nomination, _confirm(separate=("A", "B")))).evaluate([a, b])
    assert sorted(group.member_candidate_ids for group in separated.groups) == [("A",), ("B",)]


V10_LINE_SHA256 = (
    "22f235ccfd8e9201b5d63a859cd717cfc749f23db8a19467f3206000ee5bb2bf",
    "4a6c1d0dfb868769f46c4d173f735b4de2cb8a71f4390e5e09835717b0730baf",
    "495ac553eb1a8a9bb56be4191e59e4a2225878c6aeec215ad462b35e899c46f2",
    "8d1ea24649a67d980f29270eef9027326c9999d200f810dbbcec085292fa7d05",
)


def test_v10_lines_are_unchanged_and_the_role_line_states_the_boundary():
    digests = [sha256(line.encode("utf-8")).hexdigest() for line in EVENT_IDENTITY_INSTRUCTIONS]
    assert [digest for digest in digests if digest in V10_LINE_SHA256] == list(V10_LINE_SHA256)
    (line,) = [item for item in EVENT_IDENTITY_INSTRUCTIONS if item.startswith("Each evidence sentence has a role.")]
    for phrase in (
        "A record's event is only what its focus sentences report",
        "an occurrence that only context sentences report is not the record's event and never joins or separates records",
        "occurrence_sentence_ids must name at least one focus sentence that states the event",
        "may add a context sentence only when it states a detail of that same event",
    ):
        assert phrase in line, phrase
    payload = build_maiagent_event_identity_model_input(
        EventIdentityGroupingRequest("b", (_grouping_record(_focused("L", LAUNCH, {"S1"}), "R1"), _grouping_record(_focused("R", RIDE, {"S1"}), "R2")))
    )
    assert "context" in str(payload)
