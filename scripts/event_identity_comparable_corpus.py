"""Build the comparable multi-run EventIdentity occurrence-truth corpus.

This is an offline, observer-only manifest builder.  It deliberately admits
only a run with complete three-procedure RC-52 evidence and independently
supported occurrence truth into the primary denominator.  Legacy labelled
answers and title/audit-excerpt matrices are preserved as explicit secondary
or excluded strata instead of being silently pooled.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
COVERAGE_PATH = ROOT / "acceptance" / "phase_b_audit" / "event_identity_nomination_coverage.json"
RECORDED_ANSWERS_PATH = ROOT / "acceptance" / "event_identity" / "recorded_answers.json"
PHASE_B_MATRIX_PATH = ROOT / "acceptance" / "phase_b_audit" / "event_identity_proposal_confirmation_matrix.json"
CROSS_RUN_MATRIX_PATH = ROOT / "acceptance" / "phase_b_audit" / "cross_run_evidence_matrix.json"
PHASE_A_LABEL_PATH = ROOT / "acceptance" / "phase_a" / "runs" / "rc15_event_identity" / "expected_labels.json"

ANALYSIS_VERSION = "event-identity-comparable-corpus-v1"
PARTIAL_LABEL_RUNS = {19, 20}
PARTIAL_MATRIX_RUNS = {24, 25, 26, 29, 30, 31, 32, 33, 34}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def repo_relative(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def source_record(path: Path) -> dict[str, str]:
    return {"file": repo_relative(path), "sha256": sha256_file(path)}


def matrix_summaries(matrix: dict[str, Any]) -> dict[int, dict[str, Any]]:
    by_run: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in matrix.get("pairs", []):
        by_run[int(row["run"])].append(row)
    output: dict[int, dict[str, Any]] = {}
    for run, rows in sorted(by_run.items()):
        output[run] = {
            "row_count": len(rows),
            "proposal_count_zero": sum(row.get("prop_n") == 0 for row in rows),
            "proposal_count_one": sum(row.get("prop_n") == 1 for row in rows),
            "proposal_count_at_least_two": sum(row.get("prop_n", 0) >= 2 for row in rows),
            "confirmation_same_rows": sum(row.get("conf_same", 0) > 0 for row in rows),
            "confirmation_separated_rows": sum(row.get("conf_sep", 0) > 0 for row in rows),
            "final_duplicate_rows": sum(bool(row.get("final_duplicate")) for row in rows),
            "truth_independently_labelled": False,
            "contains_never_nominated_denominator": False,
        }
    return output


def build_run_inventory(
    cross_run: dict[str, Any],
    recorded: dict[str, Any],
    phase_b_matrix: dict[str, Any],
    coverage: dict[str, Any],
) -> list[dict[str, Any]]:
    cross_by_run = {int(row["run"]): row for row in cross_run.get("runs", []) if "run" in row}
    matrix_by_run = matrix_summaries(phase_b_matrix)
    historical = coverage["historical_labelled"]["runs"]
    inventory: list[dict[str, Any]] = []
    for run in range(12, 35):
        row = cross_by_run[run]
        prompt = row.get("prompts", {}).get("ei")
        base = {
            "run": run,
            "github_run_id": row.get("run_id"),
            "ref": row.get("ref"),
            "commit": row.get("commit"),
            "eventidentity_prompt": prompt,
            "artifact": row.get("artifact"),
            "status": row.get("status"),
        }
        if run in PARTIAL_LABEL_RUNS:
            run_id = "40999869397" if run == 19 else "41018554355"
            base.update(
                {
                    "classification": "COMPARABLE_PARTIAL",
                    "truth_source": "recorded_answers.labels (hand-checked occurrence labels; IDs-only corpus)",
                    "pair_evidence": {
                        "labelled_same_pairs": historical[run_id]["labelled_same_occurrence_pairs"],
                        "labelled_different_pairs": historical[run_id]["labelled_different_occurrence_pairs"],
                        "nomination_snapshots": historical[run_id]["nomination_observed_same_pairs"],
                        "confirmation_pairs": historical[run_id]["same_confirmation_observed_pairs"],
                    },
                    "rc52_three_procedure_complete": False,
                    "primary_exclusion_reason": (
                        "Hand-checked truth exists, but preserved answers are legacy snapshots: run #19 has three "
                        "nomination snapshots without a complete three-procedure RC-52 trace; run #20 has confirmation "
                        "snapshots without nomination coverage."
                    ),
                }
            )
        elif run in PARTIAL_MATRIX_RUNS:
            base.update(
                {
                    "classification": "COMPARABLE_PARTIAL",
                    "truth_source": "title/audit-excerpt judgment in phase-b matrix; not independent occurrence truth",
                    "pair_evidence": matrix_by_run[run],
                    "rc52_three_procedure_complete": False,
                    "primary_exclusion_reason": (
                        "Pair-level proposal/confirmation rows exist, but occurrence truth is not independently labelled "
                        "and the matrix contains proposal opportunities only, so never-nominated pairs are absent."
                    ),
                }
            )
        else:
            base.update(
                {
                    "classification": "NOT_COMPARABLE",
                    "truth_source": "none sufficient for this corpus",
                    "pair_evidence": None,
                    "rc52_three_procedure_complete": False,
                    "primary_exclusion_reason": (
                        "Preserved run summary does not provide both independently labelled occurrence truth and a "
                        "complete pair-level three-procedure nomination/confirmation trace."
                    ),
                }
            )
        inventory.append(base)

    run39 = coverage["run39"]
    inventory.append(
        {
            "run": 39,
            "github_run_id": "42548407130",
            "ref": "release/report-quality-wip",
            "commit": coverage.get("analysis_head"),
            "eventidentity_prompt": coverage.get("production_prompt"),
            "artifact": "selection_audit.json (hash preserved in prior observer artifact)",
            "status": "SUCCESS_WITH_TECHNICAL_GAPS",
            "classification": "COMPARABLE_FULL",
            "truth_source": "Run #39 forensic checkpoint: seven candidates independently established as one supported occurrence",
            "pair_evidence": {
                "labelled_same_pairs": run39["labelled_same_occurrence_pairs"],
                "labelled_different_pairs": run39["labelled_different_occurrence_pairs"],
                "complete_rc52_procedures": 3,
                "run39_replay": run39["recorded_replay"],
            },
            "rc52_three_procedure_complete": True,
            "primary_exclusion_reason": None,
        }
    )
    return sorted(inventory, key=lambda row: row["run"])


def build_secondary_pair_exclusions(coverage: dict[str, Any]) -> list[dict[str, Any]]:
    excluded: list[dict[str, Any]] = []
    run_map = {"40999869397": 19, "41018554355": 20}
    for run_id, run in run_map.items():
        for pair in coverage["historical_labelled"]["runs"][run_id]["pairs"]:
            excluded.append(
                {
                    "run": run,
                    "candidate_ids": pair["candidate_ids"],
                    "truth": pair["truth"],
                    "truth_source": pair["truth_source"],
                    "excluded_from_primary": True,
                    "exclusion_reason": "Legacy answer snapshots do not prove a complete comparable three-procedure RC-52 trace.",
                    "nomination_observations": pair["nomination_observations"],
                    "confirmation_observations": pair["confirmation_observations"],
                    "final_rc52_relation": pair.get("final_rc52_relation", "NOT_RECONSTRUCTABLE"),
                    "earliest_failure": "UNKNOWN_NOT_PROVEN",
                }
            )
    return excluded


def build_report() -> dict[str, Any]:
    coverage = load_json(COVERAGE_PATH)
    recorded = load_json(RECORDED_ANSWERS_PATH)
    phase_b_matrix = load_json(PHASE_B_MATRIX_PATH)
    cross_run = load_json(CROSS_RUN_MATRIX_PATH)

    inventory = build_run_inventory(cross_run, recorded, phase_b_matrix, coverage)
    primary_run = next(row for row in inventory if row["classification"] == "COMPARABLE_FULL")
    primary_pairs = coverage["run39"]["pairs"]
    primary_metrics = coverage["run39"]["metrics"]
    earliest = Counter(row["earliest_failure"] for row in primary_pairs)
    secondary_exclusions = build_secondary_pair_exclusions(coverage)
    matrix_by_run = matrix_summaries(phase_b_matrix)

    sources = {
        "nomination_coverage_artifact": source_record(COVERAGE_PATH),
        "recorded_answers": source_record(RECORDED_ANSWERS_PATH),
        "phase_b_proposal_confirmation_matrix": source_record(PHASE_B_MATRIX_PATH),
        "cross_run_evidence_matrix": source_record(CROSS_RUN_MATRIX_PATH),
        "phase_a_title_proxy_labels_excluded": source_record(PHASE_A_LABEL_PATH),
    }

    return {
        "analysis_version": ANALYSIS_VERSION,
        "production_prompt": coverage["production_prompt"],
        "authoritative_owner": "EventIdentity",
        "new_maiagent_calls": 0,
        "paid_validation_required_in_this_task": False,
        "sources": sources,
        "runs_reviewed": len(inventory),
        "run_inventory": inventory,
        "primary_comparable_denominator": {
            "classification": "COMPARABLE_FULL",
            "runs": [primary_run["run"]],
            "same_pairs": primary_pairs,
            "different_pairs": [],
            "same_pair_count": len(primary_pairs),
            "different_pair_count": 0,
            "independent_same_occurrence_clusters": 1,
            "independent_different_occurrence_clusters": 0,
            "cluster_note": (
                "All 21 pairs are combinations from one seven-record Run #39 occurrence. Pair-level counts are "
                "not 21 independent production incidents."
            ),
            "nomination_distribution": {
                "0_of_3": primary_metrics["same_nominated_0_of_3"],
                "1_of_3": primary_metrics["same_nominated_1_of_3"],
                "2_of_3": primary_metrics["same_nominated_2_of_3"],
                "3_of_3": primary_metrics["same_nominated_3_of_3"],
            },
            "same_with_lt2_joint_nominations": primary_metrics["same_with_lt2_joint_nominations"],
            "same_with_lt2_joint_nominations_rate": primary_metrics["same_with_lt2_joint_nominations"] / len(primary_pairs),
            "same_confirmation_reached": primary_metrics["same_reached_confirmation"],
            "same_confirmation_splits": primary_metrics["same_confirmation_splits"],
            "same_confirmation_split_rate": primary_metrics["same_confirmation_splits"]
            / primary_metrics["same_reached_confirmation"],
            "same_final_same": primary_metrics["same_final_same"],
            "same_final_not_same": len(primary_pairs) - primary_metrics["same_final_same"],
            "earliest_failure_counts": {
                "nomination_coverage": earliest["NOMINATION_COVERAGE"],
                "confirmation": earliest["CONFIRMATION"],
                "technical": 0,
                "rc52_aggregation_after_sufficient_nomination": 0,
                "other": earliest["COMPLETE_LINK"],
                "unknown": earliest["UNKNOWN"],
            },
            "technical_nomination_losses": primary_metrics["technical_nomination_losses"],
            "valid_semantic_nomination_misses": primary_metrics["valid_semantic_nomination_misses"],
        },
        "secondary_partial_labelled_pairs": {
            "pair_count": len(secondary_exclusions),
            "same_pair_count": sum(row["truth"] == "SAME_OCCURRENCE" for row in secondary_exclusions),
            "different_pair_count": sum(row["truth"] == "DIFFERENT_OCCURRENCE" for row in secondary_exclusions),
            "pairs": secondary_exclusions,
            "used_in_primary_hypothesis": False,
        },
        "excluded_unlabelled_matrix": {
            "runs": sorted(matrix_by_run),
            "row_count": len(phase_b_matrix.get("pairs", [])),
            "per_run": matrix_by_run,
            "used_in_primary_hypothesis": False,
            "reason": (
                "The matrix is an audit/title-excerpt judgment, not independent occurrence truth, and contains only "
                "pairs that reached a proposal; it cannot supply the required never-nominated denominator."
            ),
        },
        "rc44_variance": {
            "run": 19,
            "github_run_id": "40999869397",
            "prompt": "event-identity-grouping-v8",
            "request": "same 101-record request; three legacy nomination snapshots",
            "40_of_61": "first nomination snapshot: 40/61 hand-checked SAME pairs accepted",
            "52_of_61": "second nomination snapshot: 52/61 hand-checked SAME pairs accepted",
            "58_of_61": "reversed nomination snapshot: 58/61 hand-checked SAME pairs accepted",
            "union_60_of_61": "union of first and reversed nomination edges: 60/61 hand-checked SAME pairs",
            "primary_denominator_eligible": False,
            "comparability_reason": "Legacy v8 snapshots do not prove complete three-procedure RC-52 opportunity/confirmation evidence.",
        },
        "cluster_effect": {
            "pair_level_most_frequent_barrier": "NOMINATION_COVERAGE (7/11 non-final SAME pairs)",
            "cluster_level_most_frequent_barrier": "NOT_ESTABLISHED",
            "reason": "Only one independently labelled same-occurrence cluster is COMPARABLE_FULL; no cross-cluster replication exists.",
        },
        "different_occurrence_safety": {
            "primary_different_pairs": 0,
            "secondary_run19_different_jointly_nominated_pairs": 11,
            "secondary_run19_confirmation_correct_split_pairs": 2,
            "secondary_run20_confirmation_correct_split_pairs": 54,
            "secondary_confirmation_false_same_pairs": 0,
            "note": "Secondary figures are not primary evidence because their RC-52 procedure coverage is incomplete.",
        },
        "decision": {
            "primary_hypothesis": (
                "Across independently labelled SAME_OCCURRENCE production pairs with complete comparable RC-52 "
                "evidence, valid joint nomination in fewer than two procedures is the most frequent earliest barrier "
                "to final SAME."
            ),
            "result": "INCONCLUSIVE",
            "evidence": (
                "Run #39 alone shows nomination coverage 7/11 versus confirmation 1/11 and other/complete-link 3/11. "
                "No second independently labelled COMPARABLE_FULL run exists in the preserved evidence, and all 21 "
                "primary pairs come from one seven-record occurrence cluster."
            ),
            "numerator": 7,
            "denominator": 11,
            "most_frequent_pair_level_barrier": "NOMINATION_COVERAGE",
            "generalization_status": "NOT_PROVEN",
        },
        "architecture_acceptance": {
            "production_eventidentity_changed": False,
            "production_scope_changed": False,
            "downstream_rescue_added": False,
            "second_owner_added": False,
            "golden_expected_outcome_changed": False,
            "domain_rule_lock": "NO",
            "new_domain_rule_proposed": "NO",
            "observer_only": True,
        },
        "exclusion_summary": {
            "excluded_labelled_pair_count": len(secondary_exclusions),
            "excluded_unlabelled_matrix_row_count": len(phase_b_matrix.get("pairs", [])),
            "top_reasons": [
                {
                    "reason": "Incomplete or absent comparable three-procedure RC-52 trace",
                    "count": len(secondary_exclusions),
                },
                {
                    "reason": "No independent occurrence truth and proposal-only matrix denominator",
                    "count": len(phase_b_matrix.get("pairs", [])),
                },
                {
                    "reason": "Phase A title/leading-Evidence labels excluded from primary truth",
                    "count": 1,
                },
            ],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = build_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "runs_reviewed": report["runs_reviewed"],
                "comparable_full_runs": [row["run"] for row in report["run_inventory"] if row["classification"] == "COMPARABLE_FULL"],
                "primary_same_pairs": report["primary_comparable_denominator"]["same_pair_count"],
                "excluded_labelled_pairs": report["exclusion_summary"]["excluded_labelled_pair_count"],
                "hypothesis_result": report["decision"]["result"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
