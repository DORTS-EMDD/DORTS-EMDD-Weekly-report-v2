"""RC-47 (section A.35): failure-path cases moved verbatim out of the Event Dedup Golden.

ED22, ED23 and ED25 script a helper defect (a citation to a sentence the record
does not have, a record listed twice in one group, a confirmation that wrongly
separates two reports) and lock the owner's fail-closed answer to it. Their
records are, word for word, the reports of one council decision that Golden
ED24 locks as one Event, so their expected outcomes are mechanism contracts,
not the domain truth of their Evidence. They run here through the Golden
harness, the same EventIdentity owner and the same assertions as the Golden
runner; each case object is pinned by hash and by its expected outcome, so it
cannot be weakened or rewritten to fit a later implementation. The domain
truth stays in Golden (ED24, [3]).
"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest

from src.weekly_report.event_identity import EventIdentity
from tests import test_event_dedup_golden as golden_harness

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / "tests" / "fixtures" / "event_identity_failure_path_cases.json").read_text(encoding="utf-8"))
GOLDEN = json.loads((ROOT / "golden" / "event_dedup_cases.json").read_text(encoding="utf-8"))
CASES = {case["case_id"]: case for case in FIXTURE["cases"]}
MOVED = ("ED22", "ED23", "ED25")

# The case objects exactly as they stood in golden/event_dedup_cases.json before the move.
PINNED_SHA256 = {
    "ED22": "b038093fd1bb4747e20cd6c42e4dbdb040add0d5e16106468a6e867da865170a",
    "ED23": "ba644ba76744a4a0672013cafecc53a1469a46b2ade97470033fef68fa122bae",
    "ED25": "1c2af8056e26630c7d7b10fd9d57fd3e1e2e1c1bec61c666e3a1cd5eed24e78c",
}
# (expected_group_count, expected_group_sizes, expected_technical_gaps)
PINNED_EXPECTED = {
    "ED22": (2, [1, 2], ["CITATION_INVALID"]),
    "ED23": (2, [1, 2], ["DUPLICATE_MEMBERSHIP"]),
    "ED25": (2, [1, 1], []),
}


def _digest(case):
    return sha256(json.dumps(case, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _evaluate(case):
    harness = golden_harness.EventDedupGoldenTests
    return EventIdentity(harness._advisor_for_case(case)).evaluate(harness._materialize_case(case))


def test_the_fixture_holds_the_moved_cases_unchanged():
    assert tuple(CASES) == MOVED
    assert {case_id: _digest(case) for case_id, case in CASES.items()} == PINNED_SHA256
    for case_id, (count, sizes, gaps) in PINNED_EXPECTED.items():
        case = CASES[case_id]
        assert (case["expected_group_count"], case["expected_group_sizes"], case["expected_technical_gaps"]) == (count, sizes, gaps)


@pytest.mark.parametrize("case_id", MOVED)
def test_each_failure_path_contract_still_holds(case_id):
    # The Golden runner's assertions, unchanged (test_event_dedup_golden).
    case = CASES[case_id]
    result = _evaluate(case)
    assert len(result.groups) == case["expected_group_count"]
    assert sorted(len(group.member_candidate_ids) for group in result.groups) == case["expected_group_sizes"]
    members = [candidate_id for group in result.groups for candidate_id in group.member_candidate_ids]
    assert len(members) == len(set(members))
    assert [gap.failure_class for gap in result.technical_gaps] == case["expected_technical_gaps"]


def test_only_the_moved_cases_left_the_golden():
    golden_ids = [case["case_id"] for case in GOLDEN["cases"]]
    assert golden_ids == [f"ED{number:02d}" for number in range(1, 27) if f"ED{number:02d}" not in MOVED]


def test_golden_ed24_still_locks_their_evidence_as_one_event():
    ed24 = next(case for case in GOLDEN["cases"] if case["case_id"] == "ED24")
    assert (ed24["expected_group_count"], ed24["expected_group_sizes"], ed24["expected_technical_gaps"]) == (1, [3], [])
    bodies = {record["candidate_id"]: record["body"] for record in ed24["records"]}
    for case in CASES.values():
        # Same reports, word for word: only the scripted helper answers differ.
        assert all(record["body"] == bodies[record["candidate_id"]] for record in case["records"])
    result = _evaluate(ed24)
    assert [group.member_candidate_ids for group in result.groups] == [("NEWS1", "NEWS2", "NEWS3")]
