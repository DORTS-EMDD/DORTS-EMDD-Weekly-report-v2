"""Run the predeclared 14-case, 3-round current Category live gate.

This gate is deliberately smaller than the formal 53-group seal.  It binds
the exact checked-in production configuration, freezes the current full
population fingerprint, and permits no replacement case or semantic retry.
The RC-6 transport retry remains inside one logical call and is accounted for
separately from the logical-call hard cap.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import urllib.parse
import urllib.request
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.category_semantic_evaluation as evaluation  # noqa: E402
import scripts.category_narrow_live_control as historical_control  # noqa: E402
from src.weekly_report.category_semantic_provider import (  # noqa: E402
    MaiAgentCategorySemanticProviderConfig,
)
from src.weekly_report.maiagent_transport import MAIAGENT_MAX_ATTEMPTS  # noqa: E402


BOUNDED_CASE_IDS = (
    "G08",
    "G11",
    "G12",
    "G19",
    "G55",
    "G80",
    "G03",
    "G64",
    "G78",
    "G84",
    "G100",
    "G101",
    "G93",
    "G66",
)
CONTROL_ROUNDS = 3
CASES_PER_ROUND = len(BOUNDED_CASE_IDS)
PLANNED_LOGICAL_CALLS = CONTROL_ROUNDS * CASES_PER_ROUND
HARD_CAP = PLANNED_LOGICAL_CALLS
TRANSPORT_ATTEMPT_HARD_CAP = PLANNED_LOGICAL_CALLS * MAIAGENT_MAX_ATTEMPTS
PRIOR_ACCEPTED_DEPLOYMENT_FINGERPRINT = (
    "ab75a4fb9e278c8f93ee60fff8a1deaa9e0a2ef3a9db9086af09a43e8746bbe7"
)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _fetch_chatbot_readback(config: MaiAgentCategorySemanticProviderConfig) -> tuple[dict[str, Any], bytes]:
    endpoint = (
        config.api_base.rstrip("/")
        + "/api/v1/chatbots/"
        + urllib.parse.quote(config.chatbot_id, safe="")
        + "/"
    )
    request = urllib.request.Request(
        endpoint,
        headers={"Authorization": f"Api-Key {config.api_key}", "Accept": "application/json"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=config.timeout_seconds) as response:
        raw = response.read()
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("MaiAgent chatbot read-back must be a JSON object")
    return data, raw


def _control_population() -> tuple[list[dict[str, Any]], dict[tuple[str, str], dict[str, str]]]:
    specs: list[dict[str, Any]] = []
    oracle: dict[tuple[str, str], dict[str, str]] = {}
    for case_id in BOUNDED_CASE_IDS:
        matches = sorted((ROOT / "golden" / "cases").glob(f"{case_id.lower()}_*.json"))
        if len(matches) != 1:
            raise ValueError(f"expected one fixture for {case_id}")
        fixture_path = matches[0]
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        fixture_specs = evaluation._group_specs_for_fixture(
            fixture, filename=str(fixture_path.relative_to(ROOT))
        )
        if len(fixture_specs) != 1:
            raise ValueError(f"control fixture {case_id} must produce one Event Group")
        spec = fixture_specs[0]
        expected = evaluation._expected_for_group(fixture, spec["group_count"])
        specs.append(spec)
        oracle[(spec["case_id"], spec["group"].event_id)] = expected
    return specs, oracle


def _full_configuration_fingerprint() -> str:
    _, fixtures = evaluation._load_population()
    specs, oracle, _ = evaluation._phase_a_reconcile(fixtures)
    return evaluation._configuration_fingerprint(specs, oracle)


def _run_round(
    *,
    round_index: int,
    config: MaiAgentCategorySemanticProviderConfig,
    snapshot: dict[str, Any],
    control_specs: list[dict[str, Any]],
    configuration_fingerprint: str,
) -> dict[str, Any]:
    original = {
        "load": evaluation._load_population,
        "fingerprint": evaluation._configuration_fingerprint,
        "total": evaluation.TOTAL_GOLDEN_FIXTURES,
        "reached": evaluation.CATEGORY_REACHED_FIXTURES,
        "groups": evaluation.GROUPS_PER_ROUND,
        "calls": evaluation.TOTAL_PLANNED_LIVE_CALLS,
        "budget": evaluation.LIVE_CALL_BUDGET,
    }

    def narrow_population():
        fixtures = [{"filename": spec["filename"], "fixture": spec["fixture"]} for spec in control_specs]
        return {"cases": fixtures}, fixtures

    try:
        evaluation._load_population = narrow_population
        evaluation._configuration_fingerprint = lambda specs, oracle: configuration_fingerprint
        evaluation.TOTAL_GOLDEN_FIXTURES = len(control_specs)
        evaluation.CATEGORY_REACHED_FIXTURES = len(control_specs)
        evaluation.GROUPS_PER_ROUND = len(control_specs)
        evaluation.TOTAL_PLANNED_LIVE_CALLS = PLANNED_LOGICAL_CALLS
        evaluation.LIVE_CALL_BUDGET = len(control_specs)
        return evaluation.run_evaluation(
            config=config,
            round_index=round_index,
            deployment_provenance=snapshot,
        )
    finally:
        evaluation._load_population = original["load"]
        evaluation._configuration_fingerprint = original["fingerprint"]
        evaluation.TOTAL_GOLDEN_FIXTURES = original["total"]
        evaluation.CATEGORY_REACHED_FIXTURES = original["reached"]
        evaluation.GROUPS_PER_ROUND = original["groups"]
        evaluation.TOTAL_PLANNED_LIVE_CALLS = original["calls"]
        evaluation.LIVE_CALL_BUDGET = original["budget"]


def _round_summary(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "round_index": report.get("ROUND_INDEX"),
        "status": report.get("CATEGORY_53_GROUP_LIVE_ACCEPTANCE"),
        "logical_calls": len(report.get("RESULTS", [])),
        "transport_attempts": report.get("TRANSPORT_ATTEMPT_COUNT", 0),
        "transport_retries": max(0, report.get("TRANSPORT_ATTEMPT_COUNT", 0) - len(report.get("RESULTS", []))),
        "authorized_transport_retries": report.get("AUTHORIZED_TRANSPORT_RETRY_COUNT"),
        "unauthorized_transport_retries": report.get("UNAUTHORIZED_TRANSPORT_RETRY_COUNT"),
        "transport_accounting_status": report.get("TRANSPORT_ACCOUNTING_STATUS"),
        "exact_matches": report.get("EXACT_CATEGORY_MATCH_COUNT"),
        "state_mismatches": report.get("CATEGORY_STATE_MISMATCH_COUNT"),
        "primary_mismatches": report.get("PRIMARY_CATEGORY_MISMATCH_COUNT"),
        "reason_mismatches": report.get("RESOLUTION_REASON_MISMATCH_COUNT"),
        "citation_concerns": report.get("SEMANTIC_CITATION_CONCERN_COUNT"),
        "unscoreable": sum(
            not evaluation._live_evidence_complete(row.get("acceptance_evidence", {}))
            for row in report.get("RESULTS", [])
        ),
        "by_case": {
            row["fixture_id"]: {
                "matches_golden": row.get("matches_golden"),
                "earliest_failure_type": row.get("earliest_failure_type"),
            }
            for row in report.get("RESULTS", [])
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out-dir",
        default=str(ROOT / "acceptance" / "category_relationship_contract_20261114" / "bounded"),
    )
    args = parser.parse_args(argv)
    out_dir = Path(args.out_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise SystemExit("BOUNDED_OUTPUT_ALREADY_EXISTS; refusing overwrite")

    if evaluation._proxy_blockers():
        raise SystemExit("BLOCKED_PROXY_VARIABLE_PRESENT")
    config = MaiAgentCategorySemanticProviderConfig.from_environment()
    if config is None:
        raise SystemExit("CATEGORY_MAIAGENT_CONFIGURATION_UNAVAILABLE")

    control_specs, control_oracle = _control_population()
    if len(control_specs) != CASES_PER_ROUND or len(control_oracle) != CASES_PER_ROUND:
        raise SystemExit("BOUNDED_CONTROL_POPULATION_MISMATCH")
    full_fingerprint = _full_configuration_fingerprint()

    production_identity, _, _, _ = evaluation._resolve_checked_in_production_configuration(
        category_config=config
    )
    _, full_fixtures = evaluation._load_population()
    full_specs, full_oracle, _ = evaluation._phase_a_reconcile(full_fixtures)
    target_identity = evaluation._target_configuration_identity(full_specs, full_oracle)
    binding = evaluation.enforce_category_configuration_binding(
        production=production_identity,
        target=target_identity,
        mode=evaluation.FORMAL_CURRENT_CONFIGURATION_SEAL,
    )
    if target_identity.configuration_fingerprint != full_fingerprint:
        raise SystemExit("FULL_CONFIGURATION_FINGERPRINT_DRIFT")

    readback, raw_readback = _fetch_chatbot_readback(config)
    snapshot = historical_control._snapshot_from_readback(readback)
    review = historical_control._deployment_review(readback)
    if any(value != "PASS" for key, value in review.items() if key.endswith("_STATUS")):
        raise SystemExit("DEPLOYMENT_CONTRACT_FINDING")
    deployment = evaluation._deployment_provenance_record(
        snapshot, runtime_helper_identity=config.chatbot_id
    )
    deployment["PLATFORM_REVIEW"] = review
    if deployment.get("SAME_RUNTIME_HELPER_BINDING") != "PROVEN":
        raise SystemExit("SAME_RUNTIME_HELPER_BINDING_NOT_PROVEN")
    if deployment.get("DEPLOYMENT_FINGERPRINT") != PRIOR_ACCEPTED_DEPLOYMENT_FINGERPRINT:
        raise SystemExit("BLOCKED_DEPLOYMENT_CHANGED")

    _write_json(out_dir / "category-deployment-snapshot-v1.json", snapshot)
    _write_json(
        out_dir / "bounded_plan.json",
        {
            "accepted_configuration_fingerprint": full_fingerprint,
            "production_configuration_identity": production_identity.as_mapping(),
            "target_configuration_identity": target_identity.as_mapping(),
            "formal_binding": binding,
            "bounded_cases": list(BOUNDED_CASE_IDS),
            "rounds": CONTROL_ROUNDS,
            "cases_per_round": CASES_PER_ROUND,
            "planned_logical_calls": PLANNED_LOGICAL_CALLS,
            "hard_cap": HARD_CAP,
            "transport_attempt_hard_cap": TRANSPORT_ATTEMPT_HARD_CAP,
            "deployment_fingerprint": deployment["DEPLOYMENT_FINGERPRINT"],
            "runtime_helper_identity_fingerprint": deployment["RUNTIME_HELPER_IDENTITY_FINGERPRINT"],
            "same_runtime_helper_binding": deployment["SAME_RUNTIME_HELPER_BINDING"],
            "readback_sha256": hashlib.sha256(raw_readback).hexdigest(),
            "expected_oracle": {
                f"{case_id}:{event_id}": expected
                for (case_id, event_id), expected in control_oracle.items()
            },
        },
    )

    reports: list[dict[str, Any]] = []
    total_attempts = 0
    for round_index in range(1, CONTROL_ROUNDS + 1):
        report = _run_round(
            round_index=round_index,
            config=config,
            snapshot=snapshot,
            control_specs=control_specs,
            configuration_fingerprint=full_fingerprint,
        )
        reports.append(report)
        total_attempts += int(report.get("TRANSPORT_ATTEMPT_COUNT", 0))
        _write_json(out_dir / f"round{round_index}.json", report)
        actual_logical_calls = sum(len(item.get("RESULTS", [])) for item in reports)
        if actual_logical_calls > HARD_CAP:
            raise SystemExit("BOUNDED_HARD_CAP_EXCEEDED")
        if total_attempts > TRANSPORT_ATTEMPT_HARD_CAP:
            raise SystemExit("BOUNDED_TRANSPORT_ATTEMPT_HARD_CAP_EXCEEDED")
        if report.get("CATEGORY_53_GROUP_LIVE_ACCEPTANCE") != "PASS":
            summary = {
                "verdict": "BOUNDED_ACCEPTANCE_FAIL",
                "earliest_failed_round": round_index,
                "earliest_failure": report.get("BLOCKER") or report.get("MISMATCH_DETAILS"),
                "actual_logical_calls": sum(len(item.get("RESULTS", [])) for item in reports),
                "transport_attempts": total_attempts,
                "planned_logical_calls": PLANNED_LOGICAL_CALLS,
                "hard_cap": HARD_CAP,
                "transport_attempt_hard_cap": TRANSPORT_ATTEMPT_HARD_CAP,
                "production_run": "NO",
                "event_identity_research_calls": 0,
            }
            _write_json(out_dir / "summary.json", summary)
            print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
            return 2

    summaries = [_round_summary(report) for report in reports]
    actual_logical_calls = sum(item["logical_calls"] for item in summaries)
    summary = {
        "verdict": "BOUNDED_ACCEPTANCE_PASS" if actual_logical_calls == PLANNED_LOGICAL_CALLS else "BOUNDED_ACCEPTANCE_FAIL",
        "configuration_fingerprint": full_fingerprint,
        "deployment_fingerprint": deployment["DEPLOYMENT_FINGERPRINT"],
        "same_runtime_helper_binding": deployment["SAME_RUNTIME_HELPER_BINDING"],
        "planned_logical_calls": PLANNED_LOGICAL_CALLS,
        "actual_logical_calls": actual_logical_calls,
        "transport_attempts": total_attempts,
        "transport_retries": total_attempts - actual_logical_calls,
        "hard_cap": HARD_CAP,
        "transport_attempt_hard_cap": TRANSPORT_ATTEMPT_HARD_CAP,
        "rounds": summaries,
        "production_run": "NO",
        "event_identity_research_calls": 0,
    }
    _write_json(out_dir / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary["verdict"] == "BOUNDED_ACCEPTANCE_PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
