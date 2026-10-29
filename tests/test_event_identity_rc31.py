"""RC-31: the confirmation answer contract admits the separation it requires.

RC-25 tells the helper to return a separated record as its own one-record
group, but until RC-31 every confirmation request also carried the grouping
response schema with ``members.minItems = 2``. Replaying the recorded
2026-10-14..20 run offline, 2 of the 3 confirmations that separated a record
expressed it by leaving the record out (CONFIRMATION_INCOMPLETE) and 1 by a
one-record group. These tests pin the per-request schema, the owner outcomes
it leads to, and the observation of why a proposed pair stayed apart. Fixture
texts are generic; no rule depends on a project, city or publisher name.
"""

from __future__ import annotations

import json

from src.weekly_report.contracts import (
    EventIdentityFacts,
    EventIdentityGroupingRecord,
    EventIdentityGroupingRequest,
    IdentityMetadataSupport,
    RegionResolution,
    RegionResolutionBasis,
)
from src.weekly_report.debug_service import event_identity_projection
from src.weekly_report.event_identity import (
    EVENT_IDENTITY_CONFIRMATION_RESPONSE_SCHEMA,
    EVENT_IDENTITY_GROUPING_RESPONSE_SCHEMA,
    EventIdentity,
    grouping_response_schema,
)
from src.weekly_report.evidence_sentences import segment_evidence_sentences
from src.weekly_report.maiagent_event_identity_provider import (
    CONFIRMATION_SCHEMA_VERSION,
    PROMPT_VERSION,
    SCHEMA_VERSION,
    build_maiagent_event_identity_model_input,
)
from tests.test_event_identity_contract import _record
from tests.test_event_identity_grouping_rc15 import _Scripted, _confirm, _member


def _min_members(schema):
    return schema["properties"]["groups"]["items"]["properties"]["members"]["minItems"]


def _request(confirmation):
    records = tuple(
        EventIdentityGroupingRecord(f"R{index}", f"cand-{index}", segment_evidence_sentences("A tram line opened."), {})
        for index in (1, 2)
    )
    return EventIdentityGroupingRequest("event-identity-batch-1", records, confirmation=confirmation)


def _groups(run):
    return sorted(group.member_candidate_ids for group in run.groups)


def _unconfirmed(run):
    return event_identity_projection(run)["event_identity_unconfirmed_distribution"]


def _located(candidate_id, region_id, name, text, published_at="2026-10-27T09:00:00Z"):
    resolution = RegionResolution(
        RegionResolutionBasis.SOURCE_STATED, region_id=region_id, display_name=name,
        source_field="country", source_value=name, reference_version="geo-reference-v4",
    )
    facts = EventIdentityFacts(
        country=name,
        metadata_support=(IdentityMetadataSupport("country", 0, len(name)),),
        region_resolution=resolution,
    )
    return _record(candidate_id, facts=facts, body=f"{name}: {text}", published_at=published_at)


# --- the request contract -----------------------------------------------------


def test_a_confirmation_request_declares_a_schema_that_admits_one_record_groups():
    assert _min_members(EVENT_IDENTITY_CONFIRMATION_RESPONSE_SCHEMA) == 1
    payload = build_maiagent_event_identity_model_input(_request(confirmation=True))
    contract = payload["authoritative_response_contract"]
    assert _min_members(contract["json_schema"]) == 1
    assert payload["schema_version"] == contract["schema_version"] == CONFIRMATION_SCHEMA_VERSION


def test_a_grouping_request_keeps_its_two_member_schema_and_version():
    assert _min_members(EVENT_IDENTITY_GROUPING_RESPONSE_SCHEMA) == 2
    payload = build_maiagent_event_identity_model_input(_request(confirmation=False))
    assert payload["authoritative_response_contract"] == {
        "schema_version": SCHEMA_VERSION,
        "json_schema": EVENT_IDENTITY_GROUPING_RESPONSE_SCHEMA,
    }
    assert grouping_response_schema(_request(confirmation=False)) is EVENT_IDENTITY_GROUPING_RESPONSE_SCHEMA


def test_no_instruction_forbids_one_record_groups_in_a_confirmation():
    payload = build_maiagent_event_identity_model_input(_request(confirmation=True))
    assert PROMPT_VERSION == "event-identity-grouping-v5"
    forbidding = [line for line in payload["instructions"] if "do not return single-record groups" in line]
    assert forbidding and all(line.startswith("When event_identity_request.confirmation is false") for line in forbidding)
    assert any("single-record group" in line and "confirmation is true" in line for line in payload["instructions"])
    # The two schemas differ only in the member minimum.
    relaxed = json.loads(json.dumps(EVENT_IDENTITY_CONFIRMATION_RESPONSE_SCHEMA))
    relaxed["properties"]["groups"]["items"]["properties"]["members"]["minItems"] = 2
    assert relaxed == EVENT_IDENTITY_GROUPING_RESPONSE_SCHEMA


# --- owner outcomes -----------------------------------------------------------


def test_one_announcement_reported_by_two_outlets_in_different_words_merges():
    records = [
        _record("A", facts=None, body="The operator announced on 27 October a camera and AI driver-assist system for night maintenance vehicles."),
        _record("B", facts=None, body="Night track-maintenance cars will get an AI image-recognition assistant, the operator said on 27 October."),
    ]
    advisor = _Scripted({"groups": [{"members": [_member("A"), _member("B")]}]}, _confirm("A", "B"))
    run = EventIdentity(advisor).evaluate(records)
    assert _groups(run) == [("A", "B")]
    assert run.technical_gaps == ()
    assert advisor.requests[1].confirmation is True


def test_a_syndicated_reprint_and_its_original_merge():
    text = "A power bank caught fire on a platform at 15:00 on 26 October; staff put it out and trains resumed at 15:30."
    records = [
        _record("ORIGINAL", facts=None, body=text, url="https://original.invalid/article/X1"),
        _record("REPRINT", facts=None, body=text + " Police are investigating.", url="https://portal.invalid/news/X1"),
    ]
    run = EventIdentity(
        _Scripted({"groups": [{"members": [_member("ORIGINAL"), _member("REPRINT")]}]}, _confirm("ORIGINAL", "REPRINT"))
    ).evaluate(records)
    assert _groups(run) == [("ORIGINAL", "REPRINT")]


def test_same_system_on_different_dates_stays_apart_when_the_confirmation_separates_them():
    records = [
        _record("DAY1", facts=None, body="On 22 October several stations of the same line were closed for a demonstration."),
        _record("DAY3", facts=None, body="On 24 October other stations of the same line were closed for a demonstration."),
    ]
    run = EventIdentity(
        _Scripted({"groups": [{"members": [_member("DAY1"), _member("DAY3")]}]}, _confirm(separate=("DAY1", "DAY3")))
    ).evaluate(records)
    assert _groups(run) == [("DAY1",), ("DAY3",)]
    assert run.technical_gaps == ()  # a complete, explicit separation is no gap
    assert _unconfirmed(run) == {"SEPARATED": 1}


def test_a_complete_partition_confirms_the_same_event_and_separates_another_lifecycle_step():
    # Two reports of one test announcement and a report of the later opening.
    records = [
        _record("TEST1", facts=None, body="Line tests start in early November, the operator said on 26 October."),
        _record("TEST2", facts=None, body="The operator said on 26 October that trial runs begin in early November."),
        _record("OPEN", facts=None, body="The line opened to passengers on 21 October after its trial runs."),
    ]
    advisor = _Scripted(
        {"groups": [{"members": [_member("TEST1"), _member("TEST2"), _member("OPEN")]}]},
        _confirm("TEST1", "TEST2", separate=("OPEN",)),
    )
    run = EventIdentity(advisor).evaluate(records)
    assert _groups(run) == [("OPEN",), ("TEST1", "TEST2")]
    assert run.technical_gaps == ()
    assert _unconfirmed(run) == {"SEPARATED": 2}


def test_an_omitted_record_stays_unmerged_and_the_omission_is_observed():
    records = [
        _record("TEST1", facts=None, body="Line tests start in early November, the operator said on 26 October."),
        _record("TEST2", facts=None, body="The operator said on 26 October that trial runs begin in early November."),
        _record("OPEN", facts=None, body="The line opened to passengers on 21 October after its trial runs."),
    ]
    advisor = _Scripted(
        {"groups": [{"members": [_member("TEST1"), _member("TEST2"), _member("OPEN")]}]},
        _confirm("TEST1", "TEST2"),  # OPEN left out, as under the contradictory pre-RC-31 schema
    )
    run = EventIdentity(advisor).evaluate(records)
    assert _groups(run) == [("OPEN",), ("TEST1", "TEST2")]  # fail-closed: omission is never agreement
    assert [gap.failure_class for gap in run.technical_gaps] == ["CONFIRMATION_INCOMPLETE"]
    assert _unconfirmed(run) == {"OMITTED": 2}
    details = sorted(item.detail for item in run.diagnostics if item.reason == "PROPOSAL_NOT_CONFIRMED")
    assert details == ["event-identity-batch-1:group-1|size=3|OMITTED"] * 2


def test_an_omitted_record_never_falls_back_to_the_initial_proposal():
    records = [
        _record("A", facts=None, body="Trains were halted at 15:00 on 26 October after a fire on the platform."),
        _record("B", facts=None, body="A platform fire halted trains at 15:00 on 26 October."),
    ]
    run = EventIdentity(
        _Scripted({"groups": [{"members": [_member("A"), _member("B")]}]}, {"groups": [{"members": [_member("A")]}]})
    ).evaluate(records)
    assert _groups(run) == [("A",), ("B",)]
    assert [gap.failure_class for gap in run.technical_gaps] == ["CONFIRMATION_INCOMPLETE"]
    assert _unconfirmed(run) == {"OMITTED": 1}


def test_a_failed_confirmation_is_observed_as_such_and_merges_nothing():
    from src.weekly_report.contracts import SemanticProviderTechnicalFailure

    records = [
        _record("A", facts=None, body="Trains were halted at 15:00 on 26 October after a fire on the platform."),
        _record("B", facts=None, body="A platform fire halted trains at 15:00 on 26 October."),
    ]
    failure = SemanticProviderTechnicalFailure("HTTP_502", attempts=2, transient=True)
    run = EventIdentity(_Scripted({"groups": [{"members": [_member("A"), _member("B")]}]}, failure)).evaluate(records)
    assert _groups(run) == [("A",), ("B",)]
    assert _unconfirmed(run) == {"CONFIRMATION_FAILED": 1}


def test_a_topic_group_across_regions_is_not_over_merged():
    # A batch that groups by topic across countries: region conflicts are
    # dropped (RC-22) and the confirmation keeps only the true duplicate.
    records = [
        _located("JP1", "JP", "Japan", "An AI assistant for maintenance cars was announced on 27 October."),
        _located("JP2", "JP", "Japan", "Maintenance cars get an AI assistant, announced on 27 October."),
        _located("IT1", "IT", "Italy", "Tram tests begin in November."),
        _located("JP3", "JP", "Japan", "A platform fire halted trains on 26 October."),
    ]
    advisor = _Scripted(
        {"groups": [{"members": [_member(name) for name in ("JP1", "JP2", "IT1", "JP3")]}]},
        _confirm("JP1", "JP2", separate=("IT1", "JP3")),
    )
    run = EventIdentity(advisor).evaluate(records)
    assert _groups(run) == [("IT1",), ("JP1", "JP2"), ("JP3",)]
    assert run.technical_gaps == ()
    conflicts = [item for item in run.diagnostics if item.reason == "PROPOSAL_REGION_CONFLICT"]
    assert len(conflicts) == 3 and all(item.detail == "event-identity-batch-1:group-1|size=4" for item in conflicts)
    assert _unconfirmed(run) == {"SEPARATED": 2}
