"""Scope-only stability acceptance (test-only; not production code).

Replays the archived principal content of the Phase A Scope requests and calls
only the production Scope helper through the unchanged ScopeClassifier, for a
fixed number of rounds. No Evidence fetch, Search request, Writer call or
email is made. MaiAgent calls are counted against an explicit budget and
bodies are kept in the local scratch directory only.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from phase_a_acceptance import (  # noqa: E402
    Budget,
    CountingMaiAgentTransport,
    HarnessAbort,
    fake_maiagent,
    load_environ,
)
from weekly_report.contracts import (  # noqa: E402
    EvidenceResult,
    EvidenceState,
    SemanticProviderTechnicalFailure,
)
from weekly_report.maiagent_scope_provider import PROMPT_VERSION, build_maiagent_scope_provider  # noqa: E402
from weekly_report.maiagent_transport import UrllibMaiAgentJsonTransport  # noqa: E402
from weekly_report.scope_classifier import SCOPE_PROPOSAL_SCHEMA_VERSION, ScopeClassifier  # noqa: E402


def archived_scope_requests(source_scratch: Path, slot_by_candidate: dict[str, str]) -> list[tuple[str, dict[str, Any]]]:
    items: list[tuple[str, dict[str, Any]]] = []
    for path in sorted((source_scratch / "maiagent").glob("*_scope_semantic_proposal_request.json")):
        content = json.loads(json.loads(path.read_text(encoding="utf-8"))["message"]["content"])
        request = content["scope_request"]
        items.append((slot_by_candidate.get(request["candidate_id"], request["candidate_id"]), request))
    seen: set[str] = set()
    unique = []
    for slot, request in items:
        if request["candidate_id"] not in seen:
            seen.add(request["candidate_id"])
            unique.append((slot, request))
    return sorted(unique)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-summary", required=True, help="summary.json of the live run whose Scope requests are replayed")
    parser.add_argument("--source-scratch", required=True, help="scratch dir of that live run")
    parser.add_argument("--out", required=True)
    parser.add_argument("--scratch", required=True)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--maiagent-budget", type=int, default=45)
    parser.add_argument("--seconds", type=int, default=15 * 60)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    out, scratch = Path(args.out), Path(args.scratch)
    out.mkdir(parents=True, exist_ok=True)
    (scratch / "maiagent").mkdir(parents=True, exist_ok=True)
    source_summary = json.loads(Path(args.source_summary).read_text(encoding="utf-8"))
    items = archived_scope_requests(Path(args.source_scratch), source_summary["slot_by_candidate"])

    budget = Budget(0, args.maiagent_budget, args.seconds)
    transport = CountingMaiAgentTransport(
        fake_maiagent if args.dry_run else UrllibMaiAgentJsonTransport(), budget, scratch / "maiagent"
    )
    provider = build_maiagent_scope_provider(transport=transport, environ=load_environ(args.dry_run))
    if provider is None:
        print("Scope helper configuration missing")
        return 1
    classifier = ScopeClassifier(provider)

    rounds: list[dict[str, Any]] = []
    slots = [slot for slot, _ in items]

    def write_summary(abort: str | None) -> dict[str, Any]:
        # Written after every call so a hard termination keeps completed work.
        per_slot = {}
        for slot in slots:
            states = [r["outcomes"].get(slot, {}).get("state") for r in rounds]
            per_slot[slot] = {"states": states, "stable": len(set(states)) == 1 and None not in states}
        summary = {
            "purpose": "RC-8 Scope stability acceptance on archived Phase A Evidence",
            "prompt_version": PROMPT_VERSION,
            "schema_version": SCOPE_PROPOSAL_SCHEMA_VERSION,
            "source_summary": args.source_summary,
            "abort": abort,
            "wall_clock_seconds": round(budget.elapsed(), 1),
            "budgets": {"evidence_http": [0, 0], "maiagent_calls": [budget.maiagent_used, budget.maiagent_limit], "seconds": budget.seconds},
            "rounds_completed": sum(1 for r in rounds if len(r["outcomes"]) == len(slots)),
            "unstable_slots": [slot for slot, value in per_slot.items() if not value["stable"]],
            "in_scope_counts_by_round": [Counter(o["state"] for o in r["outcomes"].values()).get("IN_SCOPE", 0) for r in rounds],
            "per_slot": per_slot,
            "rounds": rounds,
            "maiagent_calls": transport.calls,
        }
        (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
        return summary

    abort = None
    for round_index in range(1, args.rounds + 1):
        if abort:
            break
        outcomes: dict[str, Any] = {}
        rounds.append({"round": round_index, "outcomes": outcomes})
        for slot, request in items:
            evidence = EvidenceResult(
                request["candidate_id"],
                EvidenceState.READY,
                substantive_content=request["principal_content"],
                provenance=dict(request["source_metadata"]),
            )
            observations = []
            first_call = budget.maiagent_used + 1
            try:
                result = classifier.classify(
                    evidence, candidate_title=request["candidate_title"], observation_hook=observations.append
                )
            except SemanticProviderTechnicalFailure as failure:
                outcomes[slot] = {"state": "TECHNICAL_GAP", "failure_class": failure.failure_class, "calls": [first_call, budget.maiagent_used]}
                write_summary(abort)
                continue
            except HarnessAbort as stop:
                abort = str(stop)
                break
            observation = observations[0] if observations else None
            provenance = dict(result.provenance)
            outcomes[slot] = {
                "state": result.state.value,
                "diagnostic": result.diagnostic.value,
                "first_rejection_predicate": None if observation is None else observation.first_rejection_predicate,
                "response_status": None if observation is None else observation.response_status,
                "mode": provenance.get("eligible_mode_family"),
                "relations": [provenance.get("action_target_relation"), provenance.get("target_system_relation")],
                "labels": provenance.get("endpoint_labels"),
                "calls": [first_call, budget.maiagent_used],
            }
            write_summary(abort)

    summary = write_summary(abort)
    print(json.dumps({k: summary[k] for k in ("abort", "wall_clock_seconds", "budgets", "rounds_completed", "unstable_slots", "in_scope_counts_by_round")}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
