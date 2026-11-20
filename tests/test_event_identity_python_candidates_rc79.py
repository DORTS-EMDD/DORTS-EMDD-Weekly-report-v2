"""RC-79 (section A.60): Python nominates candidate pairs; the confirmation still decides."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

from src.weekly_report import event_identity as event_identity_module
from src.weekly_report.debug_service import event_identity_projection
from src.weekly_report.event_identity import PYTHON_CANDIDATE_SUBJECT, EventIdentity
from src.weekly_report.event_identity_candidates import (
    FEATURE_MAX_RECORDS,
    candidate_pairs,
    feature_terms,
    generic_terms,
)
from tests.test_event_dedup_golden import EventDedupGoldenTests, _ScriptedGroups
from tests.test_event_identity_contract import _grounded_member, _record

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "src" / "weekly_report" / "event_identity_candidates.py").read_text(encoding="utf-8")


def _stub(candidate_id, title, published_at="Wed, 28 Oct 2026 07:00:00 GMT", region=None, publisher="P"):
    return NS(candidate=NS(candidate_id=candidate_id, title=title, publisher=publisher, published_at=published_at), region=region)


def _differ(left, right):
    return bool(left.region and right.region and left.region != right.region)


def _pairs(records, focus=None):
    return candidate_pairs(records, focus_text=focus or {}, different_regions=_differ)


def test_feature_terms_by_script_and_generic_words_excluded():
    terms = feature_terms("東京メトロ東西線に「ぱとれーる」登場！ モニタリング装置 Flexity tram metro November")
    assert "ぱとれーる" in terms  # a quoted span of any script
    assert "モニタリング" in terms  # a katakana run
    assert "東西線" in terms  # a Han three-character window
    assert "flexity" in terms  # a Latin word of four letters or more
    # Governed mode words, their windows and month names are not features.
    assert not {"メトロ", "tram", "metro", "november"} & terms
    assert "地下鉄" not in feature_terms("地下鉄の駅")
    assert "メトロ" in generic_terms() and "地下鉄" in generic_terms()


def test_no_system_operator_or_publisher_name_is_written_in_the_rule():
    for name in ("東京", "Metro", "Yahoo", "ぱとれーる", "Flexity", "위례"):
        assert name not in SOURCE.split('"""', 2)[2].replace("metro, tram", ""), name


def test_pairs_need_a_shared_term_72_hours_and_no_region_conflict():
    a = _stub("a", "「ぱとれーる」公開", region="JP")
    b = _stub("b", "「ぱとれーる」報道", region=None, published_at="Thu, 29 Oct 2026 06:00:00 GMT")
    c = _stub("c", "「ぱとれーる」車両", region="KR")
    # a-c: established regions differ; a record without a region pairs with both.
    assert set(_pairs([a, b, c])) == {("a", "b"), ("b", "c")}
    late = _stub("d", "「ぱとれーる」車両", published_at="Mon, 02 Nov 2026 08:00:00 GMT")
    undated = _stub("e", "「ぱとれーる」車両", published_at="")
    assert _pairs([a, late]) == {}  # more than 72 hours apart
    assert _pairs([a, undated]) == {}  # no publication time


def test_a_term_in_more_than_the_limit_of_records_is_not_a_feature():
    records = [_stub(f"r{i}", "Flexity premiere") for i in range(FEATURE_MAX_RECORDS + 1)]
    assert _pairs(records) == {}
    assert len(_pairs(records[:FEATURE_MAX_RECORDS])) == 3


def test_the_publisher_suffix_is_not_a_feature():
    a = _stub("a", "Erste Fahrt - Holding Graz", publisher="Holding Graz")
    b = _stub("b", "Neue Linie - Holding Graz", publisher="Holding Graz")
    assert _pairs([a, b]) == {}


class _ConfirmOnly(_ScriptedGroups):
    """Batch nominations propose nothing; confirmations answer from a script."""

    def __init__(self, confirmation, procedures=None):
        super().__init__([], confirmation)
        self.procedures, self.subjects = procedures, []

    def __call__(self, request):
        self.subjects.append(request.batch_id)
        if request.confirmation and self.procedures is not None:
            suffix = request.batch_id.split(":", 1)[0][len(PYTHON_CANDIDATE_SUBJECT):]
            if suffix not in self.procedures:
                return {"groups": [{"members": [_grounded_member(r.record_id)]} for r in request.records]}
        return super().__call__(request)


def _patrail():
    case = next(item for item in EventDedupGoldenTests._load_event_dedup_cases() if item["case_id"] == "ED29")
    return EventDedupGoldenTests._materialize_case(case)


def test_ed29_is_merged_only_through_the_python_candidate_and_its_confirmation():
    records = _patrail()
    advisor = _ConfirmOnly([[record.candidate.candidate_id for record in records]])
    run = EventIdentity(advisor).evaluate(records)
    assert [len(group.member_candidate_ids) for group in run.groups] == [2]
    assert any(subject.startswith(PYTHON_CANDIDATE_SUBJECT) for subject in advisor.subjects)
    projection = event_identity_projection(run)
    assert projection["event_identity_python_candidates"] == {"PAIRS": 1, "SAME": 1}
    assert set(projection["event_identity_confirmed_pairs"]) == {"PYTHON", "PYTHON_P2", "PYTHON_P3"}
    # Without the Python nomination the helper never asks, so they stay apart.
    with patch.object(event_identity_module, "candidate_pairs", lambda *args, **kwargs: {}):
        alone = EventIdentity(_ConfirmOnly([[record.candidate.candidate_id for record in records]])).evaluate(records)
    assert len(alone.groups) == 2


def test_rc52_still_needs_two_procedures_to_confirm_a_python_pair():
    records = _patrail()
    ids = [record.candidate.candidate_id for record in records]
    once = EventIdentity(_ConfirmOnly([ids], procedures={""})).evaluate(records)
    assert len(once.groups) == 2
    assert "PROPOSAL_NOT_AGREED" in {item.reason for item in once.diagnostics}
    twice = EventIdentity(_ConfirmOnly([ids], procedures={"", "-p3"})).evaluate(records)
    assert len(twice.groups) == 1


def test_a_separating_confirmation_keeps_a_python_pair_apart():
    records = _patrail()
    run = EventIdentity(_ConfirmOnly([[records[0].candidate.candidate_id], [records[1].candidate.candidate_id]])).evaluate(records)
    assert len(run.groups) == 2
    assert {"PYTHON_CANDIDATE", "PROPOSAL_NOT_CONFIRMED"} <= {item.reason for item in run.diagnostics}


def test_an_established_region_conflict_is_never_nominated():
    left = _record("L", title="「ぱとれーる」公開", published_at="2026-10-28T08:00:00Z")
    right = _record("R", title="「ぱとれーる」公開", published_at="2026-10-28T09:00:00Z")
    with patch.object(event_identity_module, "_different_established_regions", lambda a, b: True):
        run = EventIdentity(_ConfirmOnly([["L", "R"]])).evaluate([left, right])
    assert "PYTHON_CANDIDATE" not in {item.reason for item in run.diagnostics}
    assert len(run.groups) == 2


def test_the_audit_records_the_pairs_and_the_replay_nominates_them(tmp_path):
    import scripts.event_identity_replay as replay

    records = _patrail()
    advisor = _ConfirmOnly([[record.candidate.candidate_id for record in records]])
    run = EventIdentity(advisor).evaluate(records)
    pairs = sorted(list(item.candidate_ids) for item in run.diagnostics if item.reason == "PYTHON_CANDIDATE")
    audit = {
        "candidates": [
            {"candidate_id": record.candidate.candidate_id, "published_at": record.candidate.published_at,
             "event_identity": {"proposal_excerpt_sentence_ids": ["S1", "S2"]}, "evidence": {}, "region": None}
            for record in records
        ],
        "events": [{"member_candidate_ids": list(group.member_candidate_ids)} for group in run.groups],
        "event_identity_exchanges": list(run.proposal_exchanges),
        "event_identity_python_candidates": pairs,
    }
    replayed = replay.replay(json.loads(json.dumps(audit)))
    assert [group.member_candidate_ids for group in replayed.groups] == [group.member_candidate_ids for group in run.groups]
