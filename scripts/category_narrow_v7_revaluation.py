"""Run the bounded fresh live re-evaluation of the recovered v7 guidance.

This acceptance-only wrapper recovers the exact rejected v7 guidance from its
recorded source commit, combines it with the current versioned response
contract, and reuses the existing narrow-control harness. It never changes
production Category source and never runs a full seal or production report.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import urllib.parse
import urllib.request
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.category_narrow_live_control as live  # noqa: E402
import scripts.category_semantic_evaluation as evaluation  # noqa: E402
from src.weekly_report import category_semantic_provider as provider  # noqa: E402
from src.weekly_report import classifier as classifier_module  # noqa: E402


V7_GUIDANCE_COMMIT = "8aa225d74cf8afae52c77368298949586fc31db9"
V7_GUIDANCE_PATH = "src/weekly_report/classifier.py"
V7_PROMPT_IDENTITY = "category-principal-action-v7"
CONTROL_ROUNDS = live.CONTROL_ROUNDS
CONTROL_CASE_IDS = live.CONTROL_CASE_IDS
PLANNED_LOGICAL_CALLS = live.PLANNED_LOGICAL_CALLS
HARD_CAP = PLANNED_LOGICAL_CALLS
OUT_DIR = ROOT / "acceptance" / "category_narrow_control_20261111_v7_new_contract"


def _write_json(path: Path, value: object) -> None:
    live._write_json(path, value)


def _recover_exact_v7_guidance() -> tuple[str, ...]:
    completed = subprocess.run(
        [
            "git",
            f"-c",
            f"safe.directory={ROOT}",
            "show",
            f"{V7_GUIDANCE_COMMIT}:{V7_GUIDANCE_PATH}",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    tree = ast.parse(completed.stdout, filename=V7_GUIDANCE_PATH)
    for node in tree.body:
        targets: tuple[ast.expr, ...]
        if isinstance(node, ast.Assign):
            targets = tuple(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = (node.target,)
        else:
            continue
        if any(isinstance(target, ast.Name) and target.id == "_CATEGORY_GUIDANCE" for target in targets):
            value = ast.literal_eval(node.value)
            if not isinstance(value, tuple) or not all(isinstance(item, str) for item in value):
                raise RuntimeError("recovered v7 guidance is not an exact string tuple")
            return value
    raise RuntimeError("recovered v7 guidance assignment was not found")


def _apply_recovered_v7_guidance(guidance: tuple[str, ...]) -> None:
    classifier_module._CATEGORY_GUIDANCE = guidance
    evaluation._CATEGORY_GUIDANCE = guidance
    provider.CATEGORY_SEMANTIC_PROMPT_VERSION = V7_PROMPT_IDENTITY
    evaluation.CATEGORY_SEMANTIC_PROMPT_VERSION = V7_PROMPT_IDENTITY


def _fetch_readback(config: provider.MaiAgentCategorySemanticProviderConfig) -> tuple[dict[str, Any], bytes]:
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    parser.add_argument(
        "--snapshot-dir",
        default=str(ROOT / "docs" / "category-v4-final-seal"),
    )
    args = parser.parse_args(argv)
    out_dir = Path(args.out_dir)
    snapshot_dir = Path(args.snapshot_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise SystemExit(f"refusing to overwrite non-empty output directory: {out_dir}")

    config = provider.MaiAgentCategorySemanticProviderConfig.from_environment()
    if config is None:
        raise SystemExit("CATEGORY_MAIAGENT_CONFIGURATION_UNAVAILABLE")

    guidance = _recover_exact_v7_guidance()
    control_specs, control_oracle = live._control_population()
    new_contract_baseline_fingerprint = live._full_configuration_fingerprint()
    if new_contract_baseline_fingerprint == "695988ff08b5aa792c68abc6dc4ad243aea88f01fe6b2b7caa10ca174006d749":
        raise SystemExit("response_contract_identity_did_not_change")

    _apply_recovered_v7_guidance(guidance)
    v7_configuration_fingerprint = live._full_configuration_fingerprint()
    if v7_configuration_fingerprint == new_contract_baseline_fingerprint:
        raise SystemExit("recovered_v7_guidance_did_not_change_configuration")

    readback, raw_readback = _fetch_readback(config)
    snapshot = live._snapshot_from_readback(readback)
    review = live._deployment_review(readback)
    deployment_record = evaluation._deployment_provenance_record(
        snapshot,
        runtime_helper_identity=config.chatbot_id,
    )
    if deployment_record["SAME_RUNTIME_HELPER_BINDING"] != "PROVEN":
        raise SystemExit("SAME_RUNTIME_HELPER_BINDING_NOT_PROVEN")
    if any(value != "PASS" for key, value in review.items() if key.endswith("_STATUS")):
        raise SystemExit("DEPLOYMENT_CONTRACT_FINDING")

    snapshot_dir.mkdir(parents=True, exist_ok=True)
    _write_json(snapshot_dir / "category-deployment-snapshot-v1.json", snapshot)
    plan = {
        "control_set": list(CONTROL_CASE_IDS),
        "control_set_justification": {
            "G100": "locked pre-opening signalling boundary",
            "G101": "locked operating-subway technology deployment boundary",
            "G93": "adjacent pre-opening test control against technical pollution",
            "G66": "adjacent operating timetable control against universal technology precedence",
        },
        "expected_outcomes": {
            case_id: control_oracle[(spec["case_id"], spec["group"].event_id)]
            for case_id, spec in zip(CONTROL_CASE_IDS, control_specs)
        },
        "planned_rounds": CONTROL_ROUNDS,
        "planned_logical_category_calls": PLANNED_LOGICAL_CALLS,
        "hard_cap_category_calls": HARD_CAP,
        "configuration_fingerprint": v7_configuration_fingerprint,
        "new_contract_baseline_configuration_fingerprint": new_contract_baseline_fingerprint,
        "guidance_identity": V7_PROMPT_IDENTITY,
        "guidance_source_commit": V7_GUIDANCE_COMMIT,
        "response_contract_identity": provider.MAIAGENT_CATEGORY_MESSAGE_VERSION,
        "schema_identity": provider.CATEGORY_SEMANTIC_SCHEMA_VERSION,
        "deployment_fingerprint": deployment_record["DEPLOYMENT_FINGERPRINT"],
        "runtime_helper_identity_fingerprint": deployment_record[
            "RUNTIME_HELPER_IDENTITY_FINGERPRINT"
        ],
        "same_runtime_helper_binding": deployment_record["SAME_RUNTIME_HELPER_BINDING"],
        "platform_review": review,
        "readback_sha256": hashlib.sha256(raw_readback).hexdigest(),
        "new_category_semantic_calls_before_plan": 0,
        "old_v7_formal_acceptance": "REJECTED",
        "production_report_run": "NO",
    }
    _write_json(out_dir / "narrow_control_plan.json", plan)

    reports: list[dict[str, Any]] = []
    total_attempts = 0
    actual_logical_calls = 0
    for round_index in range(1, CONTROL_ROUNDS + 1):
        report = live._run_round(
            round_index=round_index,
            config=config,
            snapshot=snapshot,
            control_specs=control_specs,
            control_oracle=control_oracle,
            configuration_fingerprint=v7_configuration_fingerprint,
        )
        logical_calls = int(report.get("CATEGORY_REACHED_GROUPS", 0))
        if logical_calls == 0:
            logical_calls = len(report.get("RESULTS", []))
        actual_logical_calls += logical_calls
        total_attempts += int(report.get("LIVE_CALL_COUNT", 0))
        if actual_logical_calls > HARD_CAP or total_attempts > HARD_CAP:
            raise SystemExit("CATEGORY_SEMANTIC_HARD_CAP_EXCEEDED")
        serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
        if config.api_key.lower() in serialized.lower() or "authorization" in serialized.lower():
            raise SystemExit("SECRET_LEAK_IN_ACCEPTANCE_REPORT")
        reports.append(report)
        _write_json(out_dir / f"round{round_index}.json", report)

    round_summaries = [live._round_summary(report) for report in reports]
    summary = {
        "verdict": live._overall_conclusion(round_summaries),
        "configuration_fingerprint": v7_configuration_fingerprint,
        "new_contract_baseline_configuration_fingerprint": new_contract_baseline_fingerprint,
        "guidance_identity": V7_PROMPT_IDENTITY,
        "guidance_source_commit": V7_GUIDANCE_COMMIT,
        "response_contract_identity": provider.MAIAGENT_CATEGORY_MESSAGE_VERSION,
        "schema_identity": provider.CATEGORY_SEMANTIC_SCHEMA_VERSION,
        "deployment_fingerprint": deployment_record["DEPLOYMENT_FINGERPRINT"],
        "runtime_helper_identity_fingerprint": deployment_record[
            "RUNTIME_HELPER_IDENTITY_FINGERPRINT"
        ],
        "same_runtime_helper_binding": deployment_record["SAME_RUNTIME_HELPER_BINDING"],
        "exact_v7_guidance_recovered": True,
        "planned_rounds": CONTROL_ROUNDS,
        "planned_logical_category_calls": PLANNED_LOGICAL_CALLS,
        "actual_logical_category_calls": actual_logical_calls,
        "transport_attempts": total_attempts,
        "transport_retries": max(0, total_attempts - actual_logical_calls),
        "hard_cap": HARD_CAP,
        "rounds": round_summaries,
        "production_report_run": "NO",
        "writer_calls": 0,
        "event_identity_calls": 0,
        "old_v7_formal_acceptance": "REJECTED",
    }
    _write_json(out_dir / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary["verdict"] == "CURRENT_LIVE_BOUNDARIES_PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
