"""Section A.36 (RC-48): the confirmed Event Identity rules R1-R5.

R1: the only DISTINCT basis is an established-region conflict (RC-22); it is
recorded as DISTINCT_EVENT and no helper output produces one. R2: the region
conflict precedes every SAME path, and the exact-source path also needs the
same Scope Candidate-event focus (one page can report several events). R3-R5
are helper-applied rules carried by the instruction (prompt v10). Fixture
texts are generic.
"""

from __future__ import annotations

from hashlib import sha256

from src.weekly_report.contracts import (
    EventIdentityFacts,
    EventIdentityGroupingRecord,
    EventIdentityGroupingRequest,
    IdentityMetadataSupport,
    RegionResolution,
    RegionResolutionBasis,
)
from src.weekly_report.debug_service import event_identity_projection
from src.weekly_report.event_identity import EventIdentity, EventIdentityRelation
from src.weekly_report.evidence_sentences import segment_evidence_sentences
from src.weekly_report.maiagent_event_identity_provider import PROMPT_VERSION, build_maiagent_event_identity_model_input
from tests.test_event_identity_contract import _facts, _record
from tests.test_event_identity_grouping_rc15 import _Scripted, _confirm, _member
from tests.test_event_identity_rc31 import _located

PAGE = "https://fixtures.invalid/roundup"
ROUNDUP = (
    "Metro roundup for the week. On 20 October the tram operator opened a new stop on Line 3. "
    "On 22 October a signal failure stopped Line 5 trains for an hour."
)


def _groups(run):
    return sorted(group.member_candidate_ids for group in run.groups)


def _relation(left, right, proposed=None):
    return EventIdentity()._relation(left, right, {}, proposed or {})


TWO_COUNTRIES = f"Korea Japan: {ROUNDUP}"


def _region_facts(name, region_id, **identity):
    """Identity facts whose EvidenceService region is established from ``name`` in TWO_COUNTRIES."""

    start = TWO_COUNTRIES.index(name)
    return EventIdentityFacts(
        **identity,
        country=name,
        metadata_support=(IdentityMetadataSupport("country", start, start + len(name)),),
        region_resolution=RegionResolution(
            RegionResolutionBasis.SOURCE_STATED, region_id=region_id, display_name=name,
            source_field="country", source_value=name, reference_version="geo-reference-v4",
        ),
    )


# --- R2: the exact-source path needs the same Candidate event ---------------------


def test_one_page_with_two_candidate_events_is_not_one_event_by_exact_source():
    stop = _record("STOP", facts=None, body=ROUNDUP, url=PAGE, focus=("S2",))
    failure = _record("FAILURE", facts=None, body=ROUNDUP, url=PAGE, focus=("S3",))
    assert _relation(stop, failure) == (EventIdentityRelation.UNCERTAIN, "INSUFFICIENT_IDENTITY")
    assert _groups(EventIdentity().evaluate([stop, failure])) == [("FAILURE",), ("STOP",)]


def test_one_page_with_the_same_candidate_event_is_one_event():
    first = _record("FIRST", facts=None, body=ROUNDUP, url=PAGE, focus=("S2",))
    second = _record("SECOND", facts=None, body=ROUNDUP, url=PAGE, focus=("S2",))
    assert _relation(first, second) == (EventIdentityRelation.SAME_EVENT, "EXACT_SOURCE_BODY")


def test_a_focus_recorded_for_only_one_record_is_not_the_same_focus():
    with_focus = _record("WITH", facts=None, body=ROUNDUP, url=PAGE, focus=("S2",))
    without = _record("WITHOUT", facts=None, body=ROUNDUP, url=PAGE)
    assert _relation(with_focus, without)[0] is EventIdentityRelation.UNCERTAIN


def test_records_without_a_recorded_focus_still_match_by_exact_source():
    first = _record("FIRST", facts=None, body=ROUNDUP, url=PAGE)
    second = _record("SECOND", facts=None, body=ROUNDUP, url=PAGE)
    assert _relation(first, second) == (EventIdentityRelation.SAME_EVENT, "EXACT_SOURCE_BODY")


def test_two_candidate_events_on_one_page_go_to_the_helper_path():
    # Not merged by the page; the helper's confirmed proposal decides as for any pair.
    stop = _record("STOP", facts=None, body=ROUNDUP, url=PAGE, focus=("S2",))
    failure = _record("FAILURE", facts=None, body=ROUNDUP, url=PAGE, focus=("S3",))
    advisor = _Scripted({"groups": [{"members": [_member("STOP"), _member("FAILURE")]}]}, _confirm(separate=("STOP", "FAILURE")), second={"groups": []})
    run = EventIdentity(advisor).evaluate([stop, failure])
    assert _groups(run) == [("FAILURE",), ("STOP",)]
    assert [request.confirmation for request in advisor.requests] == [False, True, False]


# --- R1, R2: the region conflict is the only DISTINCT basis and comes first -------


def test_a_region_conflict_is_distinct_and_precedes_exact_source():
    # Same page, text and focus; the established regions differ.
    korea_page = _record("KR", facts=_region_facts("Korea", "KR"), body=TWO_COUNTRIES, url=PAGE, focus=("S2",))
    japan_page = _record("JP", facts=_region_facts("Japan", "JP"), body=TWO_COUNTRIES, url=PAGE, focus=("S2",))
    assert _relation(korea_page, japan_page) == (EventIdentityRelation.DISTINCT_EVENT, "DISTINCT_REGION")
    run = EventIdentity().evaluate([korea_page, japan_page])
    assert _groups(run) == [("JP",), ("KR",)]
    assert [(item.candidate_ids, item.reason) for item in run.diagnostics] == [(("JP", "KR"), "DISTINCT_REGION")]
    assert event_identity_projection(run)["event_identity_diagnostic_distribution"] == {"DISTINCT_REGION": 1}


def test_a_region_conflict_precedes_the_exact_fact_path():
    identity = {
        key: getattr(_facts(), key)
        for key in ("action", "lifecycle_step", "subject", "asset", "project", "package", "occurrence_context", "occurrence_date")
    }
    # Different pages with the same exact identity facts: SAME without regions, DISTINCT across regions.
    same = [_record(name, facts=EventIdentityFacts(**identity), body=TWO_COUNTRIES) for name in ("A", "B")]
    assert _relation(*same)[0] is EventIdentityRelation.SAME_EVENT
    apart = [
        _record("A", facts=_region_facts("Korea", "KR", **identity), body=TWO_COUNTRIES),
        _record("B", facts=_region_facts("Japan", "JP", **identity), body=TWO_COUNTRIES),
    ]
    assert _relation(*apart) == (EventIdentityRelation.DISTINCT_EVENT, "DISTINCT_REGION")


def test_a_confirmed_proposal_across_regions_stays_distinct():
    korea, japan = _located("KR", "KR", "Korea", "The line opened."), _located("JP", "JP", "Japan", "The line opened.")
    advisor = _Scripted({"groups": [{"members": [_member("KR"), _member("JP")]}]}, second={"groups": []})
    run = EventIdentity(advisor).evaluate([korea, japan])
    assert _groups(run) == [("JP",), ("KR",)]
    assert {item.reason for item in run.diagnostics} == {"PROPOSAL_REGION_CONFLICT", "DISTINCT_REGION"}
    assert not any(request.confirmation for request in advisor.requests)


def test_an_unestablished_region_never_separates():
    korea = _located("KR", "KR", "Korea", "x").evidence.identity_facts
    first = _record("FIRST", facts=EventIdentityFacts(country=korea.country, metadata_support=korea.metadata_support, region_resolution=korea.region_resolution), body=f"Korea: {ROUNDUP}", url=PAGE)
    second = _record("SECOND", facts=None, body=f"Korea: {ROUNDUP}", url=PAGE)
    assert _relation(first, second) == (EventIdentityRelation.SAME_EVENT, "EXACT_SOURCE_BODY")


# --- R3-R5: the helper instruction (prompt v10) ------------------------------------


def _instructions():
    records = tuple(
        EventIdentityGroupingRecord(f"R{index}", f"cand-{index}", segment_evidence_sentences("A tram line opened."), {})
        for index in (1, 2)
    )
    return build_maiagent_event_identity_model_input(EventIdentityGroupingRequest("b", records))["instructions"]


def _line(prefix):
    lines = [item for item in _instructions() if item.startswith(prefix)]
    assert len(lines) == 1, prefix
    return lines[0]


def test_the_instruction_is_version_ten():
    assert PROMPT_VERSION == "event-identity-grouping-v10"


def test_r3_occurrence_granularity_is_stated():
    line = _line("Occurrences: one occurrence is one specific act or happening")
    for phrase in (
        "at one time or over one continuous period",
        "a tender; a contract award or signing; a delivery; a test or trial run without passengers; the completion or start of use",
        "a trial service that carries passengers is a start of use",
        "the later release of its investigation or audit findings, and a later decision or measure are different occurrences",
        "a milestone and an activity held to mark or verify it",
        "the completion of an installation and the start of its use, when the evidence identifies the same deliverable",
        "a report that an act is scheduled for a date and a report that it took place on that date, when the evidence identifies the same scheduled act of the same subject",
    ):
        assert phrase in line, phrase
    mixed = _line("A record's event is what its sentences report as news.")
    assert "only with the records of the one whose specific details it shares" in mixed
    assert "keep it apart from both (in a confirmation, as its own single-record group)" in mixed


def test_r4_dates_are_compared_on_stated_fields_and_never_inferred():
    line = _line("Which date is an occurrence's date:")
    for phrase in (
        "a day on which it was still continuing is not its date",
        "for a decision, the day it was made, not the day it takes effect",
        "The day someone announced or said that something happened is not that occurrence's date.",
        "Never turn a relative or incomplete expression (yesterday, Tuesday, this month, 'on the 25th') into a calendar date from a publication time, a country or a time zone.",
        "Compare two dates only on the year, month and day that both state",
        "the 25th and 25 October agree; Tuesday and 21 October are not compared",
        "Disagreeing dates follow the date rule above",
    ):
        assert phrase in line, phrase
    # The RC-38 date rule it refers to is unchanged and comes first.
    instructions = _instructions()
    assert instructions.index(_line("Dates: ")) < instructions.index(line)
    assert "Never treat one record's date as the correct one." in _line("Dates: ")


def test_r5_subject_identity_allows_translation_and_forbids_outside_knowledge():
    line = _line("Subject: the specific line, system")
    for phrase in (
        "translations, transliterations, romanizations or script variants of each other name the same subject",
        "short forms or descriptions that a record itself ties to the name",
        "specific details that both records state and that match (counts, named places, named parties, times)",
        "Do not use knowledge outside the evidence (for example which operator runs a line or which city a line is in)",
        "do not fill a gap in one record with another record's content",
        "never rely on the same city, country, system, topic or project alone",
        "'Line 2' without a city) and no specific detail matches, keep the records apart",
    ):
        assert phrase in line, phrase


# SHA-256 of each instruction line of prompt v9 (commit cd12cc6..a30fe69): v10 only adds lines.
V9_LINE_SHA256 = (
    "a8f690f124c1208e788b78ed7b05cd955d83fe6ae94bc75f03b69098d7d17df3",
    "619871ac530babc6c128a051121edd3bbfffdb3849ecb6c898cd9345ce54f949",
    "87c73804d0b652dc8e522a5e76147201d126f20d8fe25cba4d4fe41b62253300",
    "27de694f6d33c44878620c14c035fe3a00425cf1d3809e0337efff286e3dc099",
    "73d79e1204d58bd1982e4523586bd0c181df59c6ef298072bc4c6ddd2fc6d3bc",
    "c5000642abcf7d113347645c3e0f6955f6f3e368938fabfaa547e8657ff0ed56",
    "5779de1a067c7c1558904106db868fad3ac42157d5d6aab12ecc5dd4d1854cde",
    "c54426f49ccbf651a629944717011e2fa1e6ddc8aefc1645dd77ea9ca0a51e12",
    "7b3f49a557a6de3a62cadb808165c01acced34984d59556bbe77f65602c2f902",
    "d8784eba545851b038016cf933fb834ba3f06941ed46b3737aad74f055b2e449",
    "b05af7f0903eaf65592aa55180cd73c44c5d3dc519184708644e8db07a2329c9",
    "f1f2138a26280e3fd1bb06e8c61417059302f067bf28b92f6598a5c5fcafc08d",
    "1c99b95d10619f6db78dae480f74c9e20b6ddcec5f64cdc527582601b0fb4a9e",
)


def test_every_v9_line_is_kept_byte_identical_and_in_order():
    digests = [sha256(line.encode("utf-8")).hexdigest() for line in _instructions()]
    assert [digest for digest in digests if digest in V9_LINE_SHA256] == list(V9_LINE_SHA256)
    assert len(digests) == len(V9_LINE_SHA256) + 4


def test_the_v9_lines_are_unchanged():
    for prefix, phrase in (
        ("Same event means one real-world occurrence at one time", "Two incidents on consecutive days are different events."),
        ("Who announced or reported an occurrence", "neither the same topic nor a different announcer alone settles it"),
        ("A record that leaves out a detail another record states", "decide from the details the records do state"),
        ("When the evidence does not establish that two records report the same occurrence", "Similar topics, the same city, the same system or the same project are not sufficient."),
        ("Do not search, browse, use tools, retrieve external knowledge", "none are supplied"),
    ):
        assert phrase in _line(prefix), prefix
