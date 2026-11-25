"""scripts/recall_score.py: scoring a selection audit against a recall gold answer."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.recall_score import load_gold, score  # noqa: E402

PERIOD = {"start": "2026-10-27", "end": "2026-10-29"}


def _gold(tmp_path, items):
    path = tmp_path / "gold.json"
    path.write_text(json.dumps({"version": "test", "items": items}, ensure_ascii=False), encoding="utf-8")
    return load_gold(path)


def _item(id_, title, stars, section=None, merge_into=None, period=PERIOD):
    return {"id": id_, "period": period, "title": title, "stars": stars,
            "expected": "INCLUDE" if stars >= 2 else "EXCLUDE", "expected_section": section,
            "merge_into": merge_into}


def _audit(events):
    candidates, rows = [], []
    for number, (titles, label, included) in enumerate(events):
        ids = [f"c{number}_{i}" for i in range(len(titles))]
        candidates += [{"candidate_id": cid, "discovery_title": title, "terminal_stage": "FINAL_REPORT" if included else "REPORTABILITY",
                        "terminal_reason": "INCLUDED" if included else "LOW_REPORTABILITY_VALUE"} for cid, title in zip(ids, titles)]
        rows.append({"event_id": f"e{number}", "member_candidate_ids": ids, "final_report_included": included,
                     "category": {"primary_category": label}})
    return {"period": PERIOD, "candidates": candidates, "events": rows}


def test_correct_missed_wrong_section_false_inclusion_and_duplicates(tmp_path):
    gold = _gold(tmp_path, [
        _item(1, "A tech", 3, "技術新知"),
        _item(2, "B ops", 2, "營運動態"),
        _item(3, "C low", 1),
        _item(4, "D tech", 3, "技術新知"),
        _item(5, "A tech again", 3, "技術新知", merge_into=1),
        _item(6, "E incident", 3, "事故及安全事件"),
    ])
    audit = _audit([
        (["A tech"], "技術新知", True),
        (["A tech again"], "技術新知", True),        # same gold group: a duplicate
        (["B ops"], "技術新知", True),               # two stars outside ops/incident
        (["C low"], "營運動態", True),               # one star included
        (["D tech"], "技術新知", False),             # dropped
        (["F new"], "營運動態", True),               # not in the gold
    ])
    result = score(gold, audit)
    outcomes = {row["gold_id"]: row["outcome"] for row in result["rows"]}
    assert outcomes == {1: "CORRECT", 2: "WRONG_SECTION", 3: "FALSE_INCLUSION", 4: "MISSED", 6: "MISSED"}
    assert result["duplicates"] == 1
    assert result["correct"] == 1 and result["gold_groups"] == 5
    stopped = {row["gold_id"]: row["stopped_at"] for row in result["rows"]}
    assert stopped[4] == ["REPORTABILITY:LOW_REPORTABILITY_VALUE"] and stopped[6] == ["NOT_A_CANDIDATE"]
    assert [record["titles"] for record in result["unlabeled_included_events"]] == [["F new"]]


def test_items_of_other_periods_are_not_scored(tmp_path):
    gold = _gold(tmp_path, [_item(1, "A", 3, "技術新知"),
                            _item(2, "Z", 3, "技術新知", period={"start": "2026-02-04", "end": "2026-02-06"})])
    assert score(gold, _audit([(["A"], "TECHNICAL_DEVELOPMENT", True)]))["rows"][0]["outcome"] == "CORRECT"
    assert score(gold, _audit([]))["gold_groups"] == 1


@pytest.mark.parametrize("bad", [
    {"stars": 1, "expected": "INCLUDE", "expected_section": "營運動態"},
    {"stars": 2, "expected": "INCLUDE", "expected_section": "技術新知"},
    {"stars": 3, "expected": "INCLUDE", "expected_section": "Other"},
])
def test_gold_must_follow_the_star_rule(tmp_path, bad):
    item = {**_item(1, "A", 3, "技術新知"), **bad}
    with pytest.raises(ValueError):
        _gold(tmp_path, [item])


def test_recall_v1_gold_matches_the_user_answer():
    gold = load_gold(ROOT / "acceptance" / "gold" / "recall_v1.json")
    items = {item["id"]: item for item in gold["items"]}
    assert sorted(items) == list(range(1, 48))
    assert [i for i, item in items.items() if item["kind"] == "recall_target"] == [18, 19, 20, 21, 22, 42, 43, 44, 45, 47]
    assert items[15]["merge_into"] == 11 and items[16]["merge_into"] == 14
    assert {i for i, item in items.items() if item.get("expected") == "EXCLUDE"} == {1, 6, 13, 25, 26, 33, 38, 46}
    # v2 (2026-11-20): Sydney ★★ operations, Nice ★★★ procurement, Gwangju ★ (announced plan).
    assert (items[23]["stars"], items[23]["expected_section"]) == (2, "營運動態")
    assert (items[24]["stars"], items[24]["expected_section"]) == (3, "機電標案及採購動態")
    # v2.2 (2026-11-21): signal-failure collision ★★★ incidents, Danhai LRT seats ★★ incidents or operations.
    assert (items[27]["stars"], items[27]["expected_section"]) == (3, "事故及安全事件")
    assert items[28]["stars"] == 2 and set(items[28]["expected_section"]) == {"事故及安全事件", "營運動態"}
    assert gold["version"] == "recall-v3"
    assert items[7]["stars"] == 5 and items[7]["expected_section"] == "技術新知"
    assert set(items[3]["expected_section"]) == {"營運動態", "事故及安全事件"}
    assert set(items[10]["expected_section"]) == {"營運動態", "事故及安全事件"}
