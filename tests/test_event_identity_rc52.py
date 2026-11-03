"""RC-52 (section A.38): SAME needs agreement of independent proposal procedures.

The user-authorized measurement (acceptance report sections 54-56) ran the
RC-48 procedure three times on the same labelled records. Each RC-48
false merge came from a single run; counting a pair as SAME only when two of
three independent procedures confirmed it merged no differently labelled
pair on any corpus. These tests run with the production values.
"""

from __future__ import annotations

import json
import re

from src.weekly_report.contracts import SemanticProviderTechnicalFailure
from src.weekly_report.debug_service import event_identity_projection
from src.weekly_report.event_identity import (
    AGREEMENT_PROCEDURES,
    AGREEMENT_REQUIRED,
    PROCEDURE_SUFFIX,
    SECOND_NOMINATION_SUFFIX,
    EventIdentity,
)
from tests.test_event_identity_contract import _grounded_member, _record

_PROCEDURE = re.compile(rf"{re.escape(PROCEDURE_SUFFIX)}(\d+)")


def _procedure(batch_id):
    match = _PROCEDURE.search(batch_id)
    return int(match.group(1)) if match else 1


class _PerProcedure:
    """A helper whose answers differ by procedure: ``answers[procedure]`` is a list of groups.

    The same groups are proposed by the first nomination and kept by every
    confirmation of that procedure; second nominations propose nothing unless
    ``second`` names groups for that procedure. ``fail`` lists procedures whose
    first nomination fails technically.
    """

    def __init__(self, answers, second=None, fail=()):
        self.answers, self.second, self.fail = answers, second or {}, set(fail)
        self.requests = []

    def __call__(self, request):
        self.requests.append(request.batch_id)
        procedure = _procedure(request.batch_id)
        if not request.confirmation and procedure in self.fail and not request.batch_id.endswith(SECOND_NOMINATION_SUFFIX):
            raise SemanticProviderTechnicalFailure("CONNECTION", attempts=2, transient=True)
        record_ids = {record.candidate_id: record.record_id for record in request.records}
        if request.batch_id.endswith(SECOND_NOMINATION_SUFFIX):
            groups = self.second.get(procedure, [])
        else:
            groups = self.answers.get(procedure, [])
        if request.confirmation:
            # Keep the procedure's groups among the supplied records; the rest alone.
            kept = [[c for c in group if c in record_ids] for group in self.answers.get(procedure, [])]
            kept = [group for group in kept if len(group) > 1]
            placed = {c for group in kept for c in group}
            groups = kept + [[c] for c in record_ids if c not in placed]
        return {
            "groups": [
                {"members": [_grounded_member(record_ids[c]) for c in group]}
                for group in groups
                if all(c in record_ids for c in group) and (request.confirmation or len(group) > 1)
            ]
        }


def _records(*ids):
    return [_record(candidate_id, facts=None, body=f"Report {candidate_id} of an urban rail occurrence.") for candidate_id in ids]


def _groups(run):
    return sorted(group.member_candidate_ids for group in run.groups)


def test_the_production_values_are_two_of_three():
    assert (AGREEMENT_PROCEDURES, AGREEMENT_REQUIRED) == (3, 2)


def test_a_pair_confirmed_by_two_procedures_is_same():
    advisor = _PerProcedure({1: [["A", "B"]], 2: [["A", "B"]], 3: []})
    run = EventIdentity(advisor).evaluate(_records("A", "B", "C"))
    assert _groups(run) == [("A", "B"), ("C",)]


def test_one_procedures_wrong_merge_is_never_same():
    # The RC-48 false merges each came from a single run.
    advisor = _PerProcedure({1: [["A", "B"]], 2: [], 3: []})
    run = EventIdentity(advisor).evaluate(_records("A", "B"))
    assert _groups(run) == [("A",), ("B",)]
    assert [(d.candidate_ids, d.detail) for d in run.diagnostics if d.reason == "PROPOSAL_NOT_AGREED"] == [
        (("A", "B"), "confirmed=1/3")
    ]


def test_a_pair_one_procedure_omits_is_recovered_by_the_other_two():
    advisor = _PerProcedure({1: [["A", "B"]], 2: [["A", "B", "C"]], 3: [["A", "B", "C"]]})
    run = EventIdentity(advisor).evaluate(_records("A", "B", "C"))
    assert _groups(run) == [("A", "B", "C")]


def test_procedures_are_independent_and_separately_identified():
    # Procedure 1 separates the pair; procedures 2 and 3 still ask about it.
    advisor = _PerProcedure({1: [], 2: [["A", "B"]], 3: [["A", "B"]]}, second={1: [["A", "B"]]})
    run = EventIdentity(advisor).evaluate(_records("A", "B"))
    assert _groups(run) == [("A", "B")]
    nominations = [batch for batch in advisor.requests if ":" not in batch]
    assert nominations == [
        "event-identity-batch-1",
        "event-identity-batch-1-n2",
        "event-identity-batch-1-p2",
        "event-identity-batch-1-p2-n2",
        "event-identity-batch-1-p3",
        "event-identity-batch-1-p3-n2",
    ]
    assert {batch.split(":")[0] for batch in advisor.requests if batch.endswith(":confirmation")} == {
        "event-identity-batch-1-n2",
        "event-identity-batch-1-p2",
        "event-identity-batch-1-p3",
    }


def test_a_failed_procedure_is_a_gap_and_the_other_two_still_decide():
    advisor = _PerProcedure({1: [["A", "B"]], 2: [["A", "B"]], 3: [["A", "B"]]}, fail={2})
    run = EventIdentity(advisor).evaluate(_records("A", "B"))
    assert _groups(run) == [("A", "B")]
    assert [(gap.subject_id, gap.failure_class) for gap in run.technical_gaps] == [("event-identity-batch-1-p2", "CONNECTION")]
    advisor = _PerProcedure({1: [["A", "B"]], 2: [["A", "B"]], 3: []}, fail={2})
    assert _groups(EventIdentity(advisor).evaluate(_records("A", "B"))) == [("A",), ("B",)]


def test_complete_link_still_needs_every_pair_agreed():
    # A-B and B-C agreed, A-C confirmed once: no transitive merge (ED10).
    advisor = _PerProcedure({1: [["A", "B", "C"]], 2: [["A", "B"], ["B", "C"]], 3: [["A", "B"], ["B", "C"]]})
    run = EventIdentity(advisor).evaluate(_records("A", "B", "C"))
    assert ("A", "B", "C") not in _groups(run)


def test_exact_source_and_region_paths_need_no_agreement():
    same_page = [
        _record("P1", facts=None, url="https://fixtures.invalid/page", body="One page about one occurrence."),
        _record("P2", facts=None, url="https://fixtures.invalid/page", body="One page about one occurrence."),
    ]
    assert _groups(EventIdentity(_PerProcedure({})).evaluate(same_page)) == [("P1", "P2")]


def test_the_summary_counts_each_procedures_confirmations_apart():
    advisor = _PerProcedure({1: [["A", "B"]], 2: [["A", "B"]], 3: [["A", "B"]]})
    run = EventIdentity(advisor).evaluate(_records("A", "B"))
    assert event_identity_projection(run)["event_identity_confirmed_pairs"] == {"FIRST": 1, "FIRST_P2": 1, "FIRST_P3": 1}


def test_recorded_exchanges_name_every_procedure_for_replay():
    advisor = _PerProcedure({1: [["A", "B"]], 2: [["A", "B"]], 3: []})
    run = EventIdentity(advisor).evaluate(_records("A", "B"))
    subjects = [exchange["subject"] for exchange in run.proposal_exchanges]
    assert subjects == advisor.requests
    assert len(set(subjects)) == len(subjects)
    json.dumps(list(run.proposal_exchanges))


def test_a_pipeline_run_with_three_procedures_replays_exactly():
    from scripts.event_identity_replay import audited_groups, recorded_procedures, replay
    from tests.test_event_identity_contract import _SemanticAdvisor
    from tests.test_event_identity_replay import _audit

    audit = _audit(_SemanticAdvisor())
    subjects = [exchange["subject"] for exchange in audit["event_identity_exchanges"]]
    assert any(PROCEDURE_SUFFIX + "3" in subject for subject in subjects)
    assert recorded_procedures(audit["event_identity_exchanges"]) == AGREEMENT_PROCEDURES
    assert {group.member_candidate_ids for group in replay(audit).groups} == audited_groups(audit)
