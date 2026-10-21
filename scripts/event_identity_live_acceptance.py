"""RC-15 live acceptance for the Event Identity grouping proposal (test-only).

Replays the Event Identity inputs of an archived production run (candidate IDs
and authoritative Evidence text, rebuilt offline) through the unchanged
EventIdentity owner and the production MaiAgent provider. No HTTP other than
MaiAgent is made; every MaiAgent call counts against a hard budget. The result
is scored against same-event labels recorded before the call.
"""

from __future__ import annotations

import argparse
from itertools import combinations
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.weekly_report.event_identity import EventIdentity  # noqa: E402
from src.weekly_report.maiagent_event_identity_provider import build_maiagent_event_identity_provider  # noqa: E402
from src.weekly_report.maiagent_transport import MaiAgentHttpResponse, UrllibMaiAgentJsonTransport  # noqa: E402
from tests.test_event_identity_contract import _record  # noqa: E402


class BudgetExceeded(BaseException):
    """Hard stop; not an Exception so no owner can swallow it."""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", required=True, type=Path)
    parser.add_argument("--expected", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--maiagent-budget", type=int, default=6)
    parser.add_argument("--replay", type=Path, help="serve responses saved by a previous run (no network)")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    real = UrllibMaiAgentJsonTransport()
    if args.replay is not None:
        def real(endpoint, *, headers, body, timeout_seconds):  # noqa: F811 - offline replay
            index = len(calls)
            if (args.replay / f"{index:02d}_request.json").read_bytes() != body:
                raise SystemExit("replayed request differs from the recorded request")
            return MaiAgentHttpResponse(200, (args.replay / f"{index:02d}_response.json").read_bytes())
    calls: list[dict] = []

    def transport(endpoint, *, headers, body, timeout_seconds):
        if len(calls) >= args.maiagent_budget:
            raise BudgetExceeded(f"MaiAgent budget {args.maiagent_budget} reached")
        index = len(calls) + 1
        (args.out / f"{index:02d}_request.json").write_bytes(body)
        started = time.monotonic()
        record = {"index": index, "request_bytes": len(body)}
        calls.append(record)
        try:
            response = real(endpoint, headers=headers, body=body, timeout_seconds=timeout_seconds)
        except BaseException as exc:
            record.update(outcome=type(exc).__name__, seconds=round(time.monotonic() - started, 1))
            raise
        record.update(outcome=f"HTTP_{response.status_code}", seconds=round(time.monotonic() - started, 1))
        (args.out / f"{index:02d}_response.json").write_bytes(response.body or b"")
        return response

    provider = build_maiagent_event_identity_provider(transport=transport)
    if provider is None:
        parser.error("MaiAgent helper configuration is unavailable")
    sources = json.loads(args.records.read_text(encoding="utf-8"))
    records = [_record(item["candidate_id"], facts=None, body=item["substantive_content"]) for item in sources]
    started = time.monotonic()
    result = EventIdentity(provider).evaluate(records)
    seconds = round(time.monotonic() - started, 1)

    short = {item["candidate_id"]: item["candidate_id"][5:13] for item in sources}
    titles = {short[item["candidate_id"]]: item["title"] for item in sources}
    merged_pairs = {
        frozenset((short[left], short[right]))
        for group in result.groups
        for left, right in combinations(group.member_candidate_ids, 2)
    }
    expected = json.loads(args.expected.read_text(encoding="utf-8"))
    expected_pairs = {
        frozenset(pair) for group in expected["same_event_groups"].values() for pair in combinations(group, 2)
    }
    ambiguous_pairs = {
        frozenset(pair) for group in expected["ambiguous_not_scored"] for pair in combinations(group, 2)
    } - expected_pairs
    apart_pairs = {frozenset(pair) for group in expected["must_stay_apart"] for pair in combinations(group, 2)}
    scored = merged_pairs - ambiguous_pairs
    summary = {
        "records": len(records),
        "events": len(result.groups),
        "maiagent_calls": calls,
        "seconds": seconds,
        "technical_gaps": [[gap.stage, gap.subject_id, gap.failure_class] for gap in result.technical_gaps],
        "pair_precision": [len(scored & expected_pairs), len(scored)],
        "pair_recall": [len(merged_pairs & expected_pairs), len(expected_pairs)],
        "must_stay_apart_violations": sorted(sorted(pair) for pair in merged_pairs & apart_pairs),
        "unexpected_merges": sorted(sorted(pair) for pair in scored - expected_pairs),
        "missed_pairs": sorted(sorted(pair) for pair in expected_pairs - merged_pairs),
        "groups": [
            [f"{short[member]} {titles[short[member]][:70]}" for member in group.member_candidate_ids]
            for group in result.groups
            if len(group.member_candidate_ids) > 1
        ],
    }
    (args.out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({key: summary[key] for key in summary if key != "groups"}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
