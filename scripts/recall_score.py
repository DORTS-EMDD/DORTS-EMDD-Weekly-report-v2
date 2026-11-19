"""Score one run's selection audit against a recall gold answer (observation only).

    python -m scripts.recall_score acceptance/gold/recall_v1.json AUDIT [AUDIT ...]

AUDIT is a ``selection_audit.json`` or a recall-test job log (plain text, or the
JSON a log download returns) that carries the audit as ``AUDIT_B64`` lines.

A gold item names a period, a title (plus candidate-title aliases and keyword
sets that identify the same story), a star rating, whether it is expected in
the report, and its expected section (or several acceptable sections). An item with ``merge_into``
is the same event as the item it names: they form one gold group, and more than
one included Event for a group counts as a duplicate. The decision rule
(user decision 2026-11-19, rated by reference value to the Taipei rapid transit
department): three stars or more are included; two stars are included only in
the operations or incident section; one star is not included.

A gold group in the audit's period is correct when it is expected and included
in its expected section (it is a miss when not included, and a wrong section
when included elsewhere), or when it is not expected and not included. The
section comes from the Event's Category label through ReportService's formal
section table; this tool recomputes no decision and changes nothing.
"""

from __future__ import annotations

import argparse
import base64
import gzip
import json
from pathlib import Path
import re
import sys
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.weekly_report.contracts import CategoryId  # noqa: E402
from src.weekly_report.report_service import FORMAL_REPORT_SECTIONS  # noqa: E402

AUDIT_LINE_PREFIX = "AUDIT_B64 "
_SECTION_BY_LABEL = {
    category_id.display_label: title for category_id, title in FORMAL_REPORT_SECTIONS
}
_SECTION_BY_LABEL.update({category_id.value: title for category_id, title in FORMAL_REPORT_SECTIONS})
_SECTIONS = {title for _category, title in FORMAL_REPORT_SECTIONS}
_TWO_STAR_SECTIONS = {
    dict(FORMAL_REPORT_SECTIONS)[CategoryId.OPERATIONAL_CHANGE],
    dict(FORMAL_REPORT_SECTIONS)[CategoryId.INCIDENT],
}


def _norm(text: Any) -> str:
    return " ".join(str(text or "").split()).casefold()


def load_gold(path: str | Path) -> dict[str, Any]:
    gold = json.loads(Path(path).read_text(encoding="utf-8"))
    items = gold.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("gold has no items")
    ids = [item["id"] for item in items]
    if len(ids) != len(set(ids)):
        raise ValueError("gold item ids must be unique")
    by_id = {item["id"]: item for item in items}
    for item in items:
        target = item.get("merge_into")
        if target is not None:
            # A duplicate of another item: it carries no rating of its own.
            if target not in by_id or by_id[target].get("merge_into") is not None:
                raise ValueError(f"item {item['id']}: merge_into must name an unmerged item")
            if by_id[target]["period"] != item["period"]:
                raise ValueError(f"item {item['id']}: merged items share one period")
            continue
        stars, expected = item["stars"], item["expected"]
        sections = expected_sections(item)
        if stars not in (1, 2, 3, 4, 5):
            raise ValueError(f"item {item['id']}: stars must be 1..5")
        if expected not in ("INCLUDE", "EXCLUDE"):
            raise ValueError(f"item {item['id']}: expected must be INCLUDE or EXCLUDE")
        if (expected == "INCLUDE") != (stars >= 2):
            raise ValueError(f"item {item['id']}: expected contradicts the star rule")
        if expected == "INCLUDE" and (not sections or not set(sections) <= _SECTIONS):
            raise ValueError(f"item {item['id']}: expected_section must name formal report sections")
        if stars == 2 and expected == "INCLUDE" and not set(sections) <= _TWO_STAR_SECTIONS:
            raise ValueError(f"item {item['id']}: a two-star item belongs only in operations or incidents")
    return gold


def expected_sections(item: dict[str, Any]) -> list[str]:
    """One section, or several acceptable ones (for example operations or incidents)."""

    value = item.get("expected_section")
    if value is None:
        return []
    return [value] if isinstance(value, str) else list(value)


def item_matches(item: dict[str, Any], title: Any) -> bool:
    """A candidate title is the item's title or alias, or contains one keyword set."""

    key = _norm(title)
    if not key:
        return False
    if key in {_norm(text) for text in [item["title"], *item.get("aliases", ())]}:
        return True
    return any(all(_norm(word) in key for word in words) for words in item.get("keywords", ()))


def _audit_from_log(text: str) -> dict[str, Any]:
    try:
        wrapped = json.loads(text)
        if isinstance(wrapped, dict) and "logs_content" in wrapped:
            text = wrapped["logs_content"]
    except ValueError:
        pass
    chunks = []
    for line in text.splitlines():
        position = line.find(AUDIT_LINE_PREFIX)
        if position >= 0:
            chunks.append(line[position + len(AUDIT_LINE_PREFIX):].strip())
    if not chunks:
        raise ValueError("log carries no AUDIT_B64 lines")
    return json.loads(gzip.decompress(base64.b64decode("".join(chunks))).decode("utf-8"))


def load_audit(path: str | Path) -> dict[str, Any]:
    text = Path(path).read_text(encoding="utf-8")
    try:
        value = json.loads(text)
        if isinstance(value, dict) and "candidates" in value:
            return value
    except ValueError:
        pass
    return _audit_from_log(text)


def _groups(gold: dict[str, Any], period: dict[str, str]) -> dict[int, list[dict[str, Any]]]:
    groups: dict[int, list[dict[str, Any]]] = {}
    for item in gold["items"]:
        if item["period"] != period:
            continue
        groups.setdefault(item.get("merge_into") or item["id"], []).append(item)
    return groups


def score(gold: dict[str, Any], audit: dict[str, Any]) -> dict[str, Any]:
    period = audit.get("period")
    if not period:
        raise ValueError("audit has no period")
    groups = _groups(gold, period)
    candidates = {entry["candidate_id"]: entry for entry in audit.get("candidates", ())}
    included = [event for event in audit.get("events", ()) if event.get("final_report_included")]
    events_by_group: dict[int, list[dict[str, Any]]] = {}
    unlabeled = []
    for event in included:
        titles = [candidates.get(member, {}).get("discovery_title") for member in event.get("member_candidate_ids", ())]
        roots = {root for root, items in groups.items()
                 if any(item_matches(item, title) for item in items for title in titles)}
        label = (event.get("category") or {}).get("primary_category")
        record = {"event_id": event.get("event_id"), "section": _SECTION_BY_LABEL.get(label, label),
                  "titles": [title for title in titles if title]}
        if not roots:
            unlabeled.append(record)
        for root in roots:
            events_by_group.setdefault(root, []).append(record)

    rows, correct, duplicates = [], 0, 0
    for root, items in sorted(groups.items()):
        head = next(item for item in items if item["id"] == root)
        found = events_by_group.get(root, [])
        expected = head["expected"]
        if expected == "INCLUDE":
            sections = {record["section"] for record in found}
            if not found:
                outcome = "MISSED"
            elif sections & set(expected_sections(head)):
                outcome = "CORRECT"
            else:
                outcome = "WRONG_SECTION"
        else:
            outcome = "CORRECT" if not found else "FALSE_INCLUSION"
        duplicates += max(0, len(found) - 1)
        correct += outcome == "CORRECT"
        stage = None
        if not found:
            # Where the gold titles stopped in this run (observation from the audit).
            stops = sorted({f"{entry['terminal_stage']}:{entry['terminal_reason']}" for entry in candidates.values()
                            if any(item_matches(item, entry.get("discovery_title")) for item in items)})
            stage = stops or ["NOT_A_CANDIDATE"]
        rows.append({"gold_id": root, "merged_ids": [item["id"] for item in items if item["id"] != root],
                     "stars": head["stars"], "expected": expected, "expected_section": expected_sections(head),
                     "kind": head.get("kind", "report"),
                     "outcome": outcome, "included_events": len(found),
                     "included_sections": sorted({record["section"] for record in found}), "stopped_at": stage,
                     "title": head["title"]})
    labeled = len(rows)
    return {
        "period": period,
        "report_id": audit.get("report_id"),
        "gold_groups": labeled,
        "correct": correct,
        "accuracy": round(correct / labeled, 4) if labeled else None,
        "missed": sum(row["outcome"] == "MISSED" for row in rows),
        "wrong_section": sum(row["outcome"] == "WRONG_SECTION" for row in rows),
        "false_inclusions": sum(row["outcome"] == "FALSE_INCLUSION" for row in rows),
        "duplicates": duplicates,
        # Recall targets: items the user expected that the source run did not report.
        "recall_targets_found": sum(row["kind"] == "recall_target" and row["outcome"] == "CORRECT" for row in rows),
        "recall_targets": sum(row["kind"] == "recall_target" for row in rows),
        "included_events": len(included),
        "unlabeled_included_events": unlabeled,
        "rows": rows,
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("gold")
    parser.add_argument("audits", nargs="+")
    parser.add_argument("--json", action="store_true", help="print the full result as JSON")
    args = parser.parse_args(list(argv) if argv is not None else None)
    gold = load_gold(args.gold)
    results = [score(gold, load_audit(path)) for path in args.audits]
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=1))
        return 0
    total = {"gold_groups": 0, "correct": 0, "duplicates": 0}
    for result in results:
        period = f"{result['period']['start']}..{result['period']['end']}"
        print(f"== {period}  accuracy={result['correct']}/{result['gold_groups']} ({result['accuracy']})"
              f"  missed={result['missed']} wrong_section={result['wrong_section']}"
              f"  false_inclusions={result['false_inclusions']} duplicates={result['duplicates']}"
              f"  recall_targets={result['recall_targets_found']}/{result['recall_targets']}"
              f"  included_events={result['included_events']} unlabeled={len(result['unlabeled_included_events'])}")
        for row in result["rows"]:
            note = "" if row["outcome"] == "CORRECT" else f"  stopped_at={row['stopped_at']}" if row["stopped_at"] else f"  sections={row['included_sections']}"
            print(f"  {row['gold_id']!s:<4} {'★' * row['stars']:<5} {row['expected']:<7} {row['outcome']:<15}"
                  f" x{row['included_events']} {row['title'][:60]}{note}")
        for record in result["unlabeled_included_events"]:
            print(f"  NEW  {record['section']}  {record['titles'][0][:70] if record['titles'] else record['event_id']}")
        for key in total:
            total[key] += result[key]
    if len(results) > 1:
        accuracy = round(total["correct"] / total["gold_groups"], 4) if total["gold_groups"] else None
        print(f"== TOTAL accuracy={total['correct']}/{total['gold_groups']} ({accuracy}) duplicates={total['duplicates']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
