"""RC-44: each batch is nominated twice, the second time in reverse order (section A.32).

Runs 40985179898 and 40999869397 left duplicates that the batch never
proposed; replays of one request proposed them in some calls and not in
others. A pair proposed by either nomination now goes to confirmation; the
region check, the confirmation and complete-link grouping are unchanged, and
a pair's verdict from an earlier nomination is never asked again.
Fixture texts are generic.
"""

from __future__ import annotations

from src.weekly_report.event_identity import SECOND_NOMINATION_SUFFIX, EventIdentity
from tests.test_event_identity_contract import _record
from tests.test_event_identity_grouping_rc15 import _Scripted, _confirm, _member
from tests.test_event_identity_rc31 import _located

BODIES = {
    "A": "The operator started 5G Wi-Fi on every car of Lines 1 and 2 on 21 October.",
    "B": "From 21 October all cars on Lines 1 and 2 carry 5G Wi-Fi, the operator said.",
    "C": "Every car of Lines 1 and 2 has had 5G Wi-Fi since 21 October.",
    "D": "Firefighters held an evacuation drill at an underground station on 21 October.",
}


def _records():
    return [_record(name, facts=None, body=body, published_at=f"2026-10-21T0{index}:00:00Z") for index, (name, body) in enumerate(BODIES.items())]


def _groups(run):
    return sorted(group.member_candidate_ids for group in run.groups)


def _batch(*groups):
    return {"groups": [{"members": [_member(name) for name in group]} for group in groups]}


def test_the_second_nomination_shows_the_same_records_in_reverse_order():
    advisor = _Scripted(_batch(), second=_batch())
    EventIdentity(advisor).evaluate(_records())
    first, second = advisor.requests
    assert second.batch_id == first.batch_id + SECOND_NOMINATION_SUFFIX
    assert [record.candidate_id for record in second.records] == [record.candidate_id for record in reversed(first.records)]
    assert [record.record_id for record in second.records] == ["R1", "R2", "R3", "R4"]
    assert [record.sentences for record in second.records] == [record.sentences for record in reversed(first.records)]
    assert not second.confirmation


def test_a_pair_only_the_second_nomination_proposes_is_confirmed_and_merged():
    # The first call leaves C out; the second proposes all three reports.
    advisor = _Scripted(_batch(("A", "B")), _confirm("A", "B"), _confirm("A", "B", "C"), second=_batch(("A", "B", "C")))
    run = EventIdentity(advisor).evaluate(_records())
    assert _groups(run) == [("A", "B", "C"), ("D",)]
    assert run.technical_gaps == ()
    assert [request.batch_id for request in advisor.requests] == [
        "event-identity-batch-1",
        "event-identity-batch-1:group-1:confirmation",
        "event-identity-batch-1-n2",
        "event-identity-batch-1-n2:group-1:confirmation",
    ]


def test_a_pair_still_needs_its_confirmation():
    advisor = _Scripted(_batch(), _confirm(separate=("A", "B")), second=_batch(("A", "B")))
    run = EventIdentity(advisor).evaluate(_records())
    assert _groups(run) == [("A",), ("B",), ("C",), ("D",)]
    assert [item.detail for item in run.diagnostics if item.reason == "PROPOSAL_NOT_CONFIRMED"] == [
        "event-identity-batch-1-n2:group-1|size=2|SEPARATED"
    ]


def test_an_earlier_verdict_stands_and_is_never_asked_again():
    # The first confirmation separates A and B; the second nomination proposes
    # them again with C. Only the new pairs go to its confirmation, and even a
    # confirmation answer that groups all three cannot reverse the A-B verdict.
    advisor = _Scripted(
        _batch(("A", "B")),
        _confirm(separate=("A", "B")),
        _confirm("A", "B", "C"),
        second=_batch(("A", "B", "C")),
    )
    run = EventIdentity(advisor).evaluate(_records())
    assert not any(set(group.member_candidate_ids) >= {"A", "B"} for group in run.groups)
    not_confirmed = [item.candidate_ids for item in run.diagnostics if item.reason == "PROPOSAL_NOT_CONFIRMED"]
    assert not_confirmed == [("A", "B")]  # recorded once, by the first confirmation


def test_the_same_proposal_twice_costs_no_second_confirmation():
    advisor = _Scripted(_batch(("A", "B", "C")), _confirm("A", "B", "C"), second=_batch(("C", "B", "A")))
    run = EventIdentity(advisor).evaluate(_records())
    assert _groups(run) == [("A", "B", "C"), ("D",)]
    assert [request.confirmation for request in advisor.requests] == [False, True, False]


def test_the_region_check_applies_to_the_second_nomination_too():
    records = [
        _located("TW", "TW", "Taiwan", "a power failure stopped the metro on 21 October."),
        _located("VN", "VN", "Vietnam", "a power failure stopped the metro on 21 October."),
    ]
    advisor = _Scripted(_batch(), second=_batch(("TW", "VN")))
    run = EventIdentity(advisor).evaluate(records)
    assert _groups(run) == [("TW",), ("VN",)]
    assert not any(request.confirmation for request in advisor.requests)
    assert [item.reason for item in run.diagnostics if item.reason == "PROPOSAL_REGION_CONFLICT"] == ["PROPOSAL_REGION_CONFLICT"]


def test_a_failed_second_nomination_is_a_disclosed_gap_and_keeps_the_first():
    from src.weekly_report.contracts import SemanticProviderTechnicalFailure

    failure = SemanticProviderTechnicalFailure("TIMEOUT", attempts=2, transient=True)
    advisor = _Scripted(_batch(("A", "B")), _confirm("A", "B"), second=failure)
    run = EventIdentity(advisor).evaluate(_records())
    assert ("A", "B") in _groups(run)
    assert [(gap.subject_id, gap.failure_class) for gap in run.technical_gaps] == [("event-identity-batch-1-n2", "TIMEOUT")]


def test_a_confirmed_pair_records_the_nomination_that_proposed_it():
    # Section A.33 (observation only): run 41018554355 could not show whether
    # the second nomination contributed any merge.
    from src.weekly_report.debug_service import event_identity_projection

    advisor = _Scripted(_batch(("A", "B")), _confirm("A", "B"), _confirm("A", "B", "C"), second=_batch(("A", "B", "C")))
    run = EventIdentity(advisor).evaluate(_records())
    confirmed = [(item.candidate_ids, item.detail) for item in run.diagnostics if item.reason == "PROPOSAL_CONFIRMED"]
    assert confirmed == [
        (("A", "B"), "event-identity-batch-1:group-1|pairs=1"),
        (("A", "B", "C"), "event-identity-batch-1-n2:group-1|pairs=2"),
    ]
    assert event_identity_projection(run)["event_identity_confirmed_pairs"] == {"FIRST": 1, "SECOND": 2}


def test_the_attribution_changes_no_grouping_outcome(monkeypatch):
    from src.weekly_report import event_identity as module

    def scripted():
        return _Scripted(_batch(("A", "B")), _confirm("A", "B"), _confirm("A", "B", "C"), second=_batch(("A", "B", "C")))

    observed = EventIdentity(scripted()).evaluate(_records())
    real = module.EventIdentityDiagnostic

    def drop_confirmed(candidate_ids, reason, detail=""):
        return real(candidate_ids, "UPSTREAM_NOT_ELIGIBLE" if reason == "PROPOSAL_CONFIRMED" else reason, detail)

    monkeypatch.setattr(module, "EventIdentityDiagnostic", drop_confirmed)
    unobserved = EventIdentity(scripted()).evaluate(_records())
    assert observed.groups == unobserved.groups
    assert observed.technical_gaps == unobserved.technical_gaps
