"""F2 (section A.32, RC-25): only a pair a confirmation actually decided is final.

RC-44 lets a later nomination send only pairs that no earlier confirmation
decided. A confirmation decides a pair only when it placed both records,
together or apart. Before F2 every pair sent to a confirmation counted as
decided, so a technical failure, an omitted record or a rejected member left
the pair unaskable for the rest of the procedure. False-merge protection is
unchanged: SAME still needs a proposal, region compatibility, a confirmation
and (RC-52) two of three procedures.
"""

from __future__ import annotations

import copy

from src.weekly_report import event_identity
from src.weekly_report.contracts import SemanticProviderTechnicalFailure
from src.weekly_report.event_identity import EventIdentity
from tests.test_event_identity_contract import _record
from tests.test_event_identity_grouping_rc15 import _confirm, _member
from tests.event_identity_single_procedure import single_proposal_procedure

BODIES = {
    "A": "The operator started 5G Wi-Fi on every car of Lines 1 and 2 on 21 October.",
    "B": "From 21 October all cars on Lines 1 and 2 carry 5G Wi-Fi, the operator said.",
    "C": "Every car of Lines 1 and 2 has had 5G Wi-Fi since 21 October.",
}


def _records():
    return [_record(name, facts=None, body=body, published_at=f"2026-10-21T0{index}:00:00Z") for index, (name, body) in enumerate(BODIES.items())]


def _groups(run):
    return sorted(group.member_candidate_ids for group in run.groups)


def _batch(*groups):
    return {"groups": [{"members": [_member(name) for name in group]} for group in groups]}


TIMEOUT = SemanticProviderTechnicalFailure("TIMEOUT", attempts=2, transient=True)


class _Helper:
    """Answers by request: nominations from ``nominate``, confirmations by subject.

    ``confirm`` maps a confirmation subject (without the -p2/-p3 procedure
    suffix) to an answer, an exception, or a callable of the full subject;
    anything unlisted confirms nothing.
    """

    def __init__(self, nominate, confirm):
        self.nominate = nominate
        self.confirm = confirm
        self.subjects = []

    def __call__(self, request):
        self.subjects.append(request.batch_id)
        key = request.batch_id.replace("-p2", "").replace("-p3", "")
        if request.confirmation:
            answer = self.confirm.get(key, {"groups": []})
            if callable(answer):
                answer = answer(request.batch_id)
        else:
            answer = self.nominate
        if isinstance(answer, BaseException):
            raise answer
        answer = copy.deepcopy(answer)
        ids = {record.candidate_id: record.record_id for record in request.records}
        for group in answer["groups"]:
            for member in group["members"]:
                member["record_id"] = ids[member["record_id"]]
        return answer

    def confirmations(self):
        return [subject for subject in self.subjects if subject.endswith("confirmation")]


FIRST = "event-identity-batch-1:group-1:confirmation"
SECOND = "event-identity-batch-1-n2:group-1:confirmation"


@single_proposal_procedure
def test_a_failed_confirmation_leaves_the_pair_open_for_the_second_nomination():
    helper = _Helper(_batch(("A", "B")), {FIRST: TIMEOUT, SECOND: _confirm("A", "B")})
    run = EventIdentity(helper).evaluate(_records())
    assert helper.confirmations() == [FIRST, SECOND]
    assert _groups(run) == [("A", "B"), ("C",)]
    assert [(gap.subject_id, gap.failure_class) for gap in run.technical_gaps] == [(FIRST, "TIMEOUT")]


@single_proposal_procedure
def test_an_omitted_record_leaves_its_pairs_open_for_the_second_nomination():
    helper = _Helper(_batch(("A", "B", "C")), {FIRST: _confirm("A", "B"), SECOND: _confirm("A", "B", "C")})
    run = EventIdentity(helper).evaluate(_records())
    assert helper.confirmations() == [FIRST, SECOND]
    assert _groups(run) == [("A", "B", "C")]


@single_proposal_procedure
def test_a_rejected_confirmation_member_leaves_its_pairs_open():
    repeated = {"groups": [{"members": [_member("A"), _member("A"), _member("B")]}]}
    helper = _Helper(_batch(("A", "B")), {FIRST: repeated, SECOND: _confirm("A", "B")})
    run = EventIdentity(helper).evaluate(_records())
    assert helper.confirmations() == [FIRST, SECOND]
    assert _groups(run) == [("A", "B"), ("C",)]


@single_proposal_procedure
def test_a_pair_confirmed_same_is_decided_and_never_asked_again():
    helper = _Helper(_batch(("A", "B")), {FIRST: _confirm("A", "B")})
    run = EventIdentity(helper).evaluate(_records())
    assert helper.confirmations() == [FIRST]
    assert _groups(run) == [("A", "B"), ("C",)]


@single_proposal_procedure
def test_a_pair_separated_is_decided_and_never_asked_again():
    helper = _Helper(_batch(("A", "B")), {FIRST: _confirm(separate=("A", "B")), SECOND: _confirm("A", "B")})
    run = EventIdentity(helper).evaluate(_records())
    assert helper.confirmations() == [FIRST]
    assert _groups(run) == [("A",), ("B",), ("C",)]


@single_proposal_procedure
def test_only_the_undecided_pairs_are_asked_again():
    # The first confirmation separates A and B and omits C: A-B is decided;
    # A-C and B-C are not. The second confirmation groups all three, but only
    # the undecided pairs count, so A-B stays apart (no complete link).
    helper = _Helper(
        _batch(("A", "B", "C")),
        {FIRST: {"groups": [{"members": [_member("A")]}, {"members": [_member("B")]}]}, SECOND: _confirm("A", "B", "C")},
    )
    run = EventIdentity(helper).evaluate(_records())
    assert helper.confirmations() == [FIRST, SECOND]
    assert not any(set(group.member_candidate_ids) >= {"A", "B"} for group in run.groups)
    not_confirmed = [item.candidate_ids for item in run.diagnostics if item.reason == "PROPOSAL_NOT_CONFIRMED"]
    assert ("A", "B") in not_confirmed  # recorded by the first confirmation only
    confirmed = [item for item in run.diagnostics if item.reason == "PROPOSAL_CONFIRMED"]
    assert [item.detail for item in confirmed] == ["event-identity-batch-1-n2:group-1|pairs=2"]


def test_rc52_agreement_still_needs_two_procedures():
    # Procedure 1 recovers the pair through its second nomination; procedure 2
    # confirms at once; procedure 3 fails both confirmations: 2 of 3, SAME.
    def first(subject):
        return _confirm("A", "B") if "-p2" in subject else TIMEOUT

    def second(subject):
        return TIMEOUT if "-p3" in subject else _confirm("A", "B")

    run = EventIdentity(_Helper(_batch(("A", "B")), {FIRST: first, SECOND: second})).evaluate(_records())
    assert _groups(run) == [("A", "B"), ("C",)]

    # Only procedure 1 confirms (through its second nomination): not agreed.
    def only_first_procedure(subject):
        return TIMEOUT if "-p" in subject else _confirm("A", "B")

    run = EventIdentity(_Helper(_batch(("A", "B")), {FIRST: TIMEOUT, SECOND: only_first_procedure})).evaluate(_records())
    assert _groups(run) == [("A",), ("B",), ("C",)]
    assert [item.detail for item in run.diagnostics if item.reason == "PROPOSAL_NOT_AGREED"] == [
        f"confirmed=1/{event_identity.AGREEMENT_PROCEDURES}"
    ]
