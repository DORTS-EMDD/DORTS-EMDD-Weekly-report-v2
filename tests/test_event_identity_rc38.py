"""RC-38: dates in Event Identity (section A.28).

Publication and reporting dates are never occurrence evidence; a stated
occurrence-date disagreement alone neither establishes different events nor
the same event; records stay apart unless other Evidence identifies one
occurrence. These tests lock the instruction and the unchanged owner
behaviour; fixtures are generic.
"""

from __future__ import annotations

import json

from src.weekly_report.contracts import EventIdentityFacts, EventIdentityGroupingRecord, EventIdentityGroupingRequest
from src.weekly_report.event_identity import EventIdentity
from src.weekly_report.evidence_sentences import segment_evidence_sentences
from src.weekly_report.maiagent_event_identity_provider import PROMPT_VERSION, build_maiagent_event_identity_model_input
from tests.test_event_identity_contract import _record
from tests.test_event_identity_grouping_rc15 import _Scripted, _confirm, _member


def _instructions(confirmation):
    records = tuple(
        EventIdentityGroupingRecord(f"R{index}", f"cand-{index}", segment_evidence_sentences("A tram line opened."), {})
        for index in (1, 2)
    )
    request = EventIdentityGroupingRequest("event-identity-batch-1", records, confirmation=confirmation)
    return build_maiagent_event_identity_model_input(request)["instructions"]


def _facts(date, **overrides):
    values = {
        "action": "audit_release",
        "lifecycle_step": "findings_published",
        "subject": "line-2-construction-audit",
        "occurrence_context": "line-2 comprehensive audit findings release",
        "occurrence_date": date,
    }
    values.update(overrides)
    return EventIdentityFacts.from_mapping(values)


def _groups(run):
    return sorted(group.member_candidate_ids for group in run.groups)


# --- the instruction ---------------------------------------------------------------


def test_every_request_carries_the_date_rule():
    for confirmation in (False, True):
        dates = [line for line in _instructions(confirmation) if line.startswith("Dates:")]
        assert len(dates) == 1
        line = dates[0]
        assert "publication, update or reporting date" in line and "never evidence of when an occurrence happened" in line
        assert "the difference alone shows neither that they are different occurrences nor that they are the same" in line
        assert "Put them together only when the other evidence identifies one and the same occurrence" in line
        assert "separate occurrences of the same kind" in line
        assert "Never treat one record's date as the correct one" in line


def test_the_existing_same_event_definition_is_unchanged():
    definition = [line for line in _instructions(False) if line.startswith("Same event means")]
    assert definition == [
        "Same event means one real-world occurrence at one time: the same accident, failure, opening, contract award, "
        "announcement, decision or test. Different lifecycle steps of the same project (for example a train delivery, "
        "a construction milestone and an opening date), different statements or meetings about the same project, and "
        "separate incidents on the same line are different events. Two incidents on consecutive days are different "
        "events. Occurrences in different cities, countries or systems are different events, even when they are of "
        "the same kind (for example two emergency drills or two construction milestones)."
    ]


# --- owner behaviour (unchanged Python) ----------------------------------------------


def test_a_date_mismatch_alone_leaves_records_undecided_and_apart():
    run = EventIdentity().evaluate(
        [_record("DATE25", facts=_facts("2026-10-25")), _record("DATE26", facts=_facts("2026-10-26"))]
    )
    assert _groups(run) == [("DATE25",), ("DATE26",)]
    # Undecided (UNCERTAIN), never a DISTINCT finding: Python has no such relation.
    assert {item.reason for item in run.diagnostics} == {"INSUFFICIENT_IDENTITY"}


def test_identical_stated_dates_still_merge_on_the_exact_fact_path():
    run = EventIdentity().evaluate(
        [_record("A", facts=_facts("2026-10-25")), _record("B", facts=_facts("2026-10-25"))]
    )
    assert _groups(run) == [("A", "B")]


def test_a_confirmed_proposal_is_not_overridden_by_a_date_mismatch():
    records = [_record("DATE25", facts=_facts("2026-10-25")), _record("DATE26", facts=_facts("2026-10-26"))]
    run = EventIdentity(
        _Scripted({"groups": [{"members": [_member("DATE25"), _member("DATE26")]}]}, _confirm("DATE25", "DATE26"))
    ).evaluate(records)
    assert _groups(run) == [("DATE25", "DATE26")]


def test_an_unconfirmed_proposal_with_a_date_mismatch_stays_apart():
    records = [_record("DATE25", facts=_facts("2026-10-25")), _record("DATE26", facts=_facts("2026-10-26"))]
    run = EventIdentity(
        _Scripted({"groups": [{"members": [_member("DATE25"), _member("DATE26")]}]}, _confirm(separate=("DATE25", "DATE26")))
    ).evaluate(records)
    assert _groups(run) == [("DATE25",), ("DATE26",)]


def test_publication_dates_are_not_identity_and_existing_date_golden_is_unchanged():
    from pathlib import Path

    golden = json.loads((Path(__file__).resolve().parents[1] / "golden" / "event_dedup_cases.json").read_text(encoding="utf-8"))
    cases = {case["case_id"]: case for case in golden["cases"]}
    # ED09: same facts, different publication dates -> one event.
    assert [record.get("published_at") for record in cases["ED09"]["records"]] == ["2026-09-15", "2026-09-16"]
    assert cases["ED09"]["expected_group_sizes"] == [2]
    # ED06: separate occurrences of one kind on different dates -> apart.
    assert cases["ED06"]["expected_group_sizes"] == [1, 1]
    assert cases["ED20"]["expected_group_sizes"] == [1, 1] and cases["ED21"]["expected_group_sizes"] == [2]


def test_ed21_is_a_domain_case_whose_evidence_identifies_one_occurrence():
    # Merge gate: ED21's expected outcome must rest on its Evidence, not only on
    # the scripted helper answer; ED20 carries the same facts without such Evidence.
    from pathlib import Path

    golden = json.loads((Path(__file__).resolve().parents[1] / "golden" / "event_dedup_cases.json").read_text(encoding="utf-8"))
    cases = {case["case_id"]: case for case in golden["cases"]}
    ed20, ed21 = cases["ED20"], cases["ED21"]
    assert [record["facts"] for record in ed21["records"]] == [record["facts"] for record in ed20["records"]]
    assert all("body" not in record for record in ed20["records"])
    bodies = [record["body"] for record in ed21["records"]]
    for anchor in ("city audit committee", "comprehensive audit of the Line 2 construction office", "24 violations",
                   "overpaid indirect construction costs", "depot overhead line"):
        assert all(anchor in body for body in bodies), anchor
    assert "25 October" in bodies[0] and "26 October" in bodies[1]
