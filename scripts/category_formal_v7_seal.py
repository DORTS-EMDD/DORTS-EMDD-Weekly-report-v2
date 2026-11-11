"""Run the formal current-configuration Category seal for recovered v7.

This is acceptance-only orchestration. It recovers the exact accepted v7
guidance from its committed source, applies it in memory alongside the current
versioned response contract, and delegates all Category evaluation to the
existing evaluation harness. It does not change production Category source,
run EventIdentity, or run a production report.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.category_narrow_live_control as narrow  # noqa: E402
import scripts.category_narrow_v7_revaluation as accepted_v7  # noqa: E402
import scripts.category_semantic_evaluation as evaluation  # noqa: E402
from src.weekly_report import category_semantic_provider as provider  # noqa: E402


EXPECTED_HEAD = "c8c5c0e27bfffac61126d1a7d27c56785496311b"
EXPECTED_CONFIGURATION_FINGERPRINT = (
    "6282f2cb1495b6759fc4f7d81b6bad088fb609e97e6321772be80a3376259690"
)
PRIOR_ACCEPTED_DEPLOYMENT_FINGERPRINT = (
    "ab75a4fb9e278c8f93ee60fff8a1deaa9e0a2ef3a9db9086af09a43e8746bbe7"
)
GUIDANCE_IDENTITY = "category-principal-action-v7"
GUIDANCE_SOURCE_COMMIT = accepted_v7.V7_GUIDANCE_COMMIT
SEAL_ROUNDS = evaluation.FINAL_SEAL_ROUNDS
SEAL_GROUPS_PER_ROUND = evaluation.GROUPS_PER_ROUND
PLANNED_LOGICAL_CALLS = SEAL_ROUNDS * SEAL_GROUPS_PER_ROUND
EVIDENCE_DIR = ROOT / "docs" / "category-v4-final-seal"
TRACKED_RECORD_DIR = (
    ROOT / "acceptance" / "category_narrow_control_20261111_v7_new_contract"
)
PLAN_PATH = TRACKED_RECORD_DIR / "formal_seal_plan.json"
ASSESSMENT_PATH = TRACKED_RECORD_DIR / "formal_seal_assessment.json"


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _current_head() -> str:
    result = subprocess.run(
        ["git", "-c", f"safe.directory={ROOT}", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _prepare_configuration() -> tuple[list[dict[str, Any]], dict[tuple[str, str], dict[str, str]], dict[str, Any], str]:
    guidance = accepted_v7._recover_exact_v7_guidance()
    accepted_v7._apply_recovered_v7_guidance(guidance)
    _, fixtures = evaluation._load_population()
    specs, oracle, counts = evaluation._phase_a_reconcile(fixtures)
    leakage = evaluation._oracle_leakage_check(specs)
    if not leakage[0]:
        raise SystemExit(f"ORACLE_LEAKAGE_PREFLIGHT_FAILED: {leakage[1]}")
    if counts["total_fixtures"] != 85:
        raise SystemExit("FORMAL_SEAL_FIXTURE_COUNT_MISMATCH")
    if counts["category_reached_fixtures"] != 52:
        raise SystemExit("FORMAL_SEAL_CATEGORY_REACHED_COUNT_MISMATCH")
    if len(specs) != SEAL_GROUPS_PER_ROUND or len(oracle) != SEAL_GROUPS_PER_ROUND:
        raise SystemExit("FORMAL_SEAL_GROUP_COUNT_MISMATCH")
    keys = [(spec["case_id"], spec["group"].event_id) for spec in specs]
    if len(set(keys)) != len(keys):
        raise SystemExit("FORMAL_SEAL_DUPLICATE_GROUP_ORACLE_KEY")
    fingerprint = evaluation._configuration_fingerprint(specs, oracle)
    if fingerprint != EXPECTED_CONFIGURATION_FINGERPRINT:
        raise SystemExit("BLOCKED_CONFIGURATION_IDENTITY_MISMATCH")
    return specs, oracle, {**counts, "leakage": leakage[1]}, fingerprint


def _population_rows(
    specs: list[dict[str, Any]],
    oracle: dict[tuple[str, str], dict[str, str]],
) -> list[dict[str, Any]]:
    rows = []
    for spec in specs:
        payload = spec["request_payload"]
        rows.append(
            {
                "fixture_id": spec["case_id"],
                "event_group_id": spec["group"].event_id,
                "member_candidate_ids": spec["member_candidate_ids"],
                "request_payload_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
                "expected": dict(oracle[(spec["case_id"], spec["group"].event_id)]),
            }
        )
    return rows


def _plan(
    *,
    head: str,
    fingerprint: str,
    deployment: dict[str, Any],
    counts: dict[str, Any],
    population: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "accepted_head": head,
        "guidance_identity": GUIDANCE_IDENTITY,
        "guidance_source_commit": GUIDANCE_SOURCE_COMMIT,
        "response_contract_identity": provider.MAIAGENT_CATEGORY_MESSAGE_VERSION,
        "schema_identity": provider.CATEGORY_SEMANTIC_SCHEMA_VERSION,
        "configuration_fingerprint": fingerprint,
        "expected_configuration_fingerprint": EXPECTED_CONFIGURATION_FINGERPRINT,
        "formal_seal_population_source": (
            "golden/manifest.json plus category_semantic_evaluation._phase_a_reconcile; "
            "golden/category_boundary_manifest.json is an explicit EXTENSION excluded "
            "from the locked formal population"
        ),
        "boundary_extension_manifest": "golden/category_boundary_manifest.json",
        "boundary_extension_case_count": 10,
        "boundary_extension_formal_population_excluded": True,
        "boundary_extension_narrow_control": {
            "controls": ["G100", "G101", "G93", "G66"],
            "evidence": "acceptance/category_narrow_control_20261111_v7_new_contract",
            "result": "PASS / PASS / PASS for each control",
        },
        "total_golden_fixtures": counts["total_fixtures"],
        "category_reached_fixtures": counts["category_reached_fixtures"],
        "formal_seal_case_count": counts["total_fixtures"],
        "category_reached_fixture_count": counts["category_reached_fixtures"],
        "formal_seal_group_count": len(population),
        "population": population,
        "planned_rounds": SEAL_ROUNDS,
        "planned_groups_per_round": SEAL_GROUPS_PER_ROUND,
        "planned_logical_calls": PLANNED_LOGICAL_CALLS,
        "acceptance_version": evaluation.ACCEPTANCE_VERSION,
        "acceptance_evidence_version": evaluation.ACCEPTANCE_EVIDENCE_VERSION,
        "evaluation_harness_version": evaluation.EVALUATION_HARNESS_VERSION,
        "deployment_snapshot_contract_version": evaluation.DEPLOYMENT_SNAPSHOT_CONTRACT_VERSION,
        "deployment_fingerprint": deployment["DEPLOYMENT_FINGERPRINT"],
        "prior_accepted_deployment_fingerprint": PRIOR_ACCEPTED_DEPLOYMENT_FINGERPRINT,
        "deployment_changed": deployment["DEPLOYMENT_FINGERPRINT"]
        != PRIOR_ACCEPTED_DEPLOYMENT_FINGERPRINT,
        "runtime_helper_identity_fingerprint": deployment[
            "RUNTIME_HELPER_IDENTITY_FINGERPRINT"
        ],
        "same_runtime_helper_binding": deployment["SAME_RUNTIME_HELPER_BINDING"],
        "platform_review": deployment["PLATFORM_REVIEW"],
        "replacement_rounds": False,
        "semantic_retry_for_preferred_result": False,
        "new_category_semantic_calls_before_plan": 0,
        "production_report_run": "NO",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default=str(EVIDENCE_DIR))
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="validate identity, population, and deployment without semantic calls",
    )
    args = parser.parse_args(argv)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_paths = [
        out_dir / f"category-final-seal-round{index}.json"
        for index in range(1, SEAL_ROUNDS + 1)
    ]
    if any(path.exists() for path in report_paths):
        raise SystemExit("FORMAL_SEAL_OUTPUT_ALREADY_EXISTS; refusing overwrite")
    if PLAN_PATH.exists() or ASSESSMENT_PATH.exists():
        raise SystemExit("FORMAL_SEAL_BOOKKEEPING_ALREADY_EXISTS; refusing overwrite")

    head = _current_head()
    if head != EXPECTED_HEAD:
        raise SystemExit("BLOCKED_STARTING_HEAD_MISMATCH")
    if evaluation._proxy_blockers():
        raise SystemExit("BLOCKED_PROXY_VARIABLE_PRESENT")
    config = provider.MaiAgentCategorySemanticProviderConfig.from_environment()
    if config is None:
        raise SystemExit("BLOCKED_CATEGORY_CONFIGURATION_UNAVAILABLE")

    specs, oracle, counts, fingerprint = _prepare_configuration()
    readback, _ = narrow._fetch_chatbot_readback(config)
    snapshot = narrow._snapshot_from_readback(readback)
    review = narrow._deployment_review(readback)
    if any(value != "PASS" for key, value in review.items() if key.endswith("_STATUS")):
        raise SystemExit("BLOCKED_DEPLOYMENT_PLATFORM_REVIEW")
    deployment = evaluation._deployment_provenance_record(
        snapshot,
        runtime_helper_identity=config.chatbot_id,
    )
    deployment["PLATFORM_REVIEW"] = review
    if deployment.get("SAME_RUNTIME_HELPER_BINDING") != "PROVEN":
        raise SystemExit("BLOCKED_RUNTIME_HELPER_BINDING")
    if deployment.get("DEPLOYMENT_FINGERPRINT") != PRIOR_ACCEPTED_DEPLOYMENT_FINGERPRINT:
        raise SystemExit("BLOCKED_DEPLOYMENT_CHANGED")

    plan = _plan(
        head=head,
        fingerprint=fingerprint,
        deployment=deployment,
        counts=counts,
        population=_population_rows(specs, oracle),
    )
    if args.preflight_only:
        print(
            json.dumps(
                {
                    "PREFLIGHT": "PASS",
                    "ACCEPTED_HEAD": head,
                    "CONFIGURATION_FINGERPRINT": fingerprint,
                    "EXPECTED_CONFIGURATION_FINGERPRINT": EXPECTED_CONFIGURATION_FINGERPRINT,
                    "DEPLOYMENT_FINGERPRINT": deployment["DEPLOYMENT_FINGERPRINT"],
                    "SAME_RUNTIME_HELPER_BINDING": deployment["SAME_RUNTIME_HELPER_BINDING"],
                    "TOTAL_GOLDEN_FIXTURES": counts["total_fixtures"],
                    "CATEGORY_REACHED_FIXTURES": counts["category_reached_fixtures"],
                    "FORMAL_SEAL_CASE_COUNT": plan["formal_seal_case_count"],
                    "FORMAL_SEAL_GROUP_COUNT": plan["formal_seal_group_count"],
                    "BOUNDARY_EXTENSION_FORMAL_POPULATION_EXCLUDED": plan[
                        "boundary_extension_formal_population_excluded"
                    ],
                    "PLANNED_ROUNDS": SEAL_ROUNDS,
                    "PLANNED_GROUPS_PER_ROUND": SEAL_GROUPS_PER_ROUND,
                    "PLANNED_LOGICAL_CALLS": PLANNED_LOGICAL_CALLS,
                    "NEW_CATEGORY_SEMANTIC_CALLS": 0,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    _write_json(out_dir / "category-deployment-snapshot-v1.json", snapshot)
    _write_json(PLAN_PATH, plan)

    reports: list[dict[str, Any]] = []
    total_attempts = 0
    for round_index in range(1, SEAL_ROUNDS + 1):
        report = evaluation.run_evaluation(
            config=config,
            round_index=round_index,
            deployment_provenance=snapshot,
        )
        _write_json(report_paths[round_index - 1], report)
        reports.append(report)
        total_attempts += int(report.get("LIVE_CALL_COUNT", 0))
        if report.get("CATEGORY_53_GROUP_LIVE_ACCEPTANCE") != "PASS":
            assessment = {
                "CATEGORY_FORMAL_SEAL": "FINDINGS",
                "STOPPED_AFTER_ROUND": round_index,
                "EARLIEST_FAILED_FORMAL_CRITERION": report.get("BLOCKER")
                or report.get("FAILURE_BREAKDOWN"),
                "CONFIGURATION_FINGERPRINT": fingerprint,
                "DEPLOYMENT_FINGERPRINT": deployment["DEPLOYMENT_FINGERPRINT"],
                "ACTUAL_LOGICAL_CALLS": sum(len(item.get("RESULTS", [])) for item in reports),
                "TRANSPORT_ATTEMPTS": total_attempts,
                "REPLACEMENT_ROUNDS": False,
                "PRODUCTION_REPORT_RUN": "NO",
            }
            _write_json(ASSESSMENT_PATH, assessment)
            print(json.dumps(assessment, ensure_ascii=False, indent=2, sort_keys=True))
            return 2

    assessment = evaluation.assess_final_seal_batch(reports)
    assessment.update(
        {
            "CATEGORY_FORMAL_SEAL": assessment.get("CATEGORY_V4_FINAL_SEAL"),
            "ACCEPTED_HEAD": head,
            "GUIDANCE_IDENTITY": GUIDANCE_IDENTITY,
            "RESPONSE_CONTRACT_IDENTITY": provider.MAIAGENT_CATEGORY_MESSAGE_VERSION,
            "SCHEMA_IDENTITY": provider.CATEGORY_SEMANTIC_SCHEMA_VERSION,
            "EXPECTED_CONFIGURATION_FINGERPRINT": EXPECTED_CONFIGURATION_FINGERPRINT,
            "ACTUAL_LOGICAL_CALLS": sum(len(item.get("RESULTS", [])) for item in reports),
            "TRANSPORT_ATTEMPTS": total_attempts,
            "TRANSPORT_RETRIES": total_attempts - PLANNED_LOGICAL_CALLS,
            "UNSCOREABLE_CALLS": sum(
                not evaluation._report_has_complete_live_evidence(item)
                for item in reports
            ),
            "FORMAL_SEAL_POPULATION_SOURCE": plan["formal_seal_population_source"],
            "FORMAL_SEAL_CASE_COUNT": plan["formal_seal_case_count"],
            "FORMAL_SEAL_GROUP_COUNT": plan["formal_seal_group_count"],
            "REPLACEMENT_ROUNDS": False,
            "SEMANTIC_RETRY_FOR_PREFERRED_RESULT": False,
            "PRODUCTION_REPORT_RUN": "NO",
        }
    )
    _write_json(ASSESSMENT_PATH, assessment)
    print(json.dumps(assessment, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if assessment.get("CATEGORY_V4_FINAL_SEAL") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
