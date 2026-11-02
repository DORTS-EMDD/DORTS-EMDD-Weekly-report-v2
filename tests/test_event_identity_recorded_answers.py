"""Section A.34: real helper answers on real live records, re-derived by the production owner.

``acceptance/event_identity/recorded_answers.json`` holds Event Identity helper
answers recorded on the records of live runs 40999869397 and 41018554355 (IDs
only, no source text) with hand-checked occurrence labels. Unlike Golden, whose
helper answers are scripted, these are what the helper actually returned; the
test re-derives each answer's outcome through the production validator and pins
it, so the measured variance is reproducible evidence rather than a log.
"""

from __future__ import annotations

from itertools import combinations
import json
from pathlib import Path
import re

from src.weekly_report.contracts import EventIdentityGroupingRecord, EventIdentityGroupingRequest
from src.weekly_report.event_identity import _validate_grouping_proposal
from src.weekly_report.evidence_sentences import segment_evidence_sentences

CORPUS = json.loads(
    (Path(__file__).resolve().parents[1] / "acceptance" / "event_identity" / "recorded_answers.json").read_text(encoding="utf-8")
)

# (run, kind, records, labelled same-occurrence pairs merged, of, differently labelled pairs merged)
MEASURED = [
    ("40999869397", "nomination", 101, 40, 61, 0),
    ("40999869397", "nomination", 101, 52, 61, 9),
    ("40999869397", "nomination_reversed", 101, 58, 61, 2),
    ("40999869397", "confirmation", 8, 28, 28, 0),
    ("40999869397", "confirmation", 6, 0, 0, 0),
    ("40999869397", "confirmation", 3, 1, 1, 0),
    ("41018554355", "confirmation", 15, 42, 51, 0),
    ("41018554355", "confirmation", 15, 42, 51, 0),
    ("41018554355", "confirmation", 15, 34, 51, 0),
    ("41018554355", "confirmation", 4, 6, 6, 0),
    ("41018554355", "confirmation", 4, 6, 6, 0),
]


def _pairs(answer):
    records = tuple(
        EventIdentityGroupingRecord(
            record_id,
            value["candidate_id"],
            segment_evidence_sentences("\n".join(f"Sentence {index}." for index in range(value["sentences"]))),
            {},
        )
        for record_id, value in answer["records"].items()
    )
    request = EventIdentityGroupingRequest("corpus", records, confirmation=answer["kind"] == "confirmation")
    accepted = {tuple(sorted(pair)) for members, _ in _validate_grouping_proposal(answer["response"], request) for pair in combinations(members, 2)}
    return accepted, [record.candidate_id for record in records]


def _measure(answer):
    labels = CORPUS["labels"][answer["run"]]
    accepted, present = _pairs(answer)
    labelled = [candidate for candidate in present if candidate in labels]
    same = {tuple(sorted(pair)) for pair in combinations(labelled, 2) if labels[pair[0]] == labels[pair[1]]}
    different = {tuple(sorted(pair)) for pair in combinations(labelled, 2) if labels[pair[0]] != labels[pair[1]]}
    return len(accepted & same), len(same), len(accepted & different)


def test_every_recorded_answer_reproduces_its_measured_outcome():
    measured = [
        (answer["run"], answer["kind"], len(answer["records"]), *_measure(answer)) for answer in CORPUS["answers"]
    ]
    assert measured == MEASURED


def test_one_unchanged_request_gave_three_different_nominations():
    # The same 101-record request, prompt and records: 66%, 85% and (reversed) 95%.
    first, second, reversed_ = (answer for answer in CORPUS["answers"] if answer["kind"].startswith("nomination"))
    assert first["records"] == second["records"] == reversed_["records"] or {
        value["candidate_id"] for value in first["records"].values()
    } == {value["candidate_id"] for value in reversed_["records"].values()}
    assert _measure(first)[:2] == (40, 61) and _measure(second)[:2] == (52, 61) and _measure(reversed_)[:2] == (58, 61)
    labels = CORPUS["labels"]["40999869397"]
    union = _pairs(first)[0] | _pairs(reversed_)[0]
    labelled = [candidate for candidate in _pairs(first)[1] if candidate in labels]
    same = {tuple(sorted(pair)) for pair in combinations(labelled, 2) if labels[pair[0]] == labels[pair[1]]}
    assert len(union & same) == 60


def test_a_confirmation_verdict_depends_on_the_other_records_in_the_request():
    # The same lawmaker-announced launch report: separated from the launch group
    # in a 15-record confirmation, merged with it in a 4-record one.
    large = [answer for answer in CORPUS["answers"] if answer["run"] == "41018554355" and len(answer["records"]) == 15]
    small = [answer for answer in CORPUS["answers"] if answer["run"] == "41018554355" and len(answer["records"]) == 4]
    shared = set.intersection(*({record["candidate_id"] for record in answer["records"].values()} for answer in large + small))
    assert len(shared) == 4
    for answer in large[:2]:
        assert _measure(answer) == (42, 51, 0)
    for answer in small:
        assert _measure(answer) == (6, 6, 0)


def test_the_corpus_holds_identifiers_only():
    candidate = re.compile(r"cand_[0-9a-f]{64}")
    sentence = re.compile(r"S[1-9][0-9]*|INVALID")
    for answer in CORPUS["answers"]:
        assert set(answer) == {"run", "kind", "prompt_version", "records", "response"}
        assert all(candidate.fullmatch(value["candidate_id"]) and set(value) == {"candidate_id", "sentences"} for value in answer["records"].values())
        for group in answer["response"]["groups"]:
            for member in group["members"]:
                assert all(sentence.fullmatch(value) for key, values in member.items() if key != "record_id" for value in values)
    assert all(candidate.fullmatch(cid) for labels in CORPUS["labels"].values() for cid in labels)
