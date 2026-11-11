"""Run the predeclared narrow Category live boundary control.

This is acceptance-only orchestration.  It reuses the repaired Category
evaluation path, including its single Classifier owner, runtime binding and
per-call evidence chain.  It does not alter production Category behavior.
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
from src.weekly_report.category_semantic_provider import (  # noqa: E402
    MaiAgentCategorySemanticProviderConfig,
)


CONTROL_CASE_IDS = ("G100", "G101", "G93", "G66")
CONTROL_ROUNDS = 3
PLANNED_LOGICAL_CALLS = len(CONTROL_CASE_IDS) * CONTROL_ROUNDS
HARD_CAP = 24
ROLE_FORBIDDEN_MARKERS = (
    "category",
    "classifier",
    "technical_development",
    "operational_change",
    "evidence",
    "search",
    "knowledge base",
    "structured output",
    "json schema",
)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _fetch_chatbot_readback(
    config: MaiAgentCategorySemanticProviderConfig,
) -> tuple[dict[str, Any], bytes]:
    endpoint = (
        config.api_base.rstrip("/")
        + "/api/v1/chatbots/"
        + urllib.parse.quote(config.chatbot_id, safe="")
        + "/"
    )
    request = urllib.request.Request(
        endpoint,
        headers={
            "Authorization": f"Api-Key {config.api_key}",
            "Accept": "application/json",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=config.timeout_seconds) as response:
        raw = response.read()
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("MaiAgent chatbot read-back must be a JSON object")
    return data, raw


def _snapshot_from_readback(data: dict[str, Any]) -> dict[str, Any]:
    llm = data.get("llm")
    if not isinstance(llm, dict) or not isinstance(llm.get("name"), str):
        raise ValueError("MaiAgent read-back does not expose an exact model label")
    instructions = data.get("instructions")
    if not isinstance(instructions, str) or not instructions:
        raise ValueError("MaiAgent read-back does not expose role instructions")
    required_keys = ("id", "outputMode", "rawOutputFormat", "replyMode", "agentMode")
    if any(key not in data for key in required_keys):
        raise ValueError("MaiAgent read-back does not expose required observable settings")

    return {
        "snapshot_contract_version": evaluation.DEPLOYMENT_SNAPSHOT_CONTRACT_VERSION,
        "platform": {
            "provider": "MaiAgent",
            "chatbot_instance_id": data["id"],
            "model_identifier": llm["name"],
        },
        "role_instruction": {"content": instructions},
        # The platform read-back exposes text mode and no fixed output schema.
        # This records that observed state; the per-request Category schema
        # remains repository-controlled and is not claimed as platform state.
        "structured_output": {
            "schema": {
                "output_mode": data["outputMode"],
                "raw_output_format": data["rawOutputFormat"],
            }
        },
        "answer_mode": (
            f"reply_mode={data['replyMode']};"
            f"agent_mode={data['agentMode']};"
            f"output_mode={data['outputMode']}"
        ),
        "knowledge_base": {
            "state": "none configured" if not data.get("knowledgeBases") else "configured"
        },
        "skills_tools": {"selected": []},
        "generation_settings": {
            "custom_max_llm_output_tokens": data.get("customMaxLlmOutputTokens"),
            "max_agent_iterations": data.get("maxAgentIterations"),
            "agent_timeout_seconds": data.get("agentTimeoutSeconds"),
            "thinking_config": data.get("thinkingConfig"),
            "enable_size_based_tool_result_truncation": data.get(
                "enableSizeBasedToolResultTruncation"
            ),
            "tool_result_max_chars": data.get("toolResultMaxChars"),
            "enable_claude_stream_retry": data.get("enableClaudeStreamRetry"),
        },
        "context_memory_settings": {
            "member_memory_write": data.get("enableMemberMemoryWrite"),
            "member_memory_injection": data.get("enableMemberMemoryInjection"),
            "vector_memory": data.get("enableVectorMemory"),
            "cross_conversation_search": data.get("enableCrossConversationSearch"),
            "cross_conversation_lookback_days": data.get("crossConversationLookbackDays"),
            "file_workspace_available": data.get("fileWorkspaceAvailable"),
            "file_workspace_mode": data.get("fileWorkspaceMode"),
            "file_workspace_status": data.get("fileWorkspaceStatus"),
        },
        "unavailable_platform_facts": [
            "chatbot_configuration_revision",
            "complete_generation_parameter_set",
            "conversation_default_state",
            "platform_schema_identity",
            "platform_schema_version",
        ],
    }


def _deployment_review(data: dict[str, Any]) -> dict[str, str]:
    instructions = data["instructions"].lower()
    role_markers = [marker for marker in ROLE_FORBIDDEN_MARKERS if marker in instructions]
    model_ok = (
        isinstance(data.get("largeLanguageModel"), str)
        and isinstance(data.get("llm"), dict)
        and data.get("largeLanguageModel") == data["llm"].get("id")
        and isinstance(data["llm"].get("name"), str)
        and bool(data["llm"]["name"])
    )
    schema_ok = data.get("outputMode") == "text" and data.get("rawOutputFormat") is None
    context_flags = (
        "enableMemberMemoryWrite",
        "enableMemberMemoryInjection",
        "enableVectorMemory",
        "enableCrossConversationSearch",
        "enableSearchMessagesTool",
        "enableGetMessageContextTool",
        "enableReadAttachmentFullTextTool",
        "enableParseAttachmentContentTool",
        "enableListAvailableParsersTool",
    )
    context_ok = all(data.get(key) is False for key in context_flags)
    tools_ok = not any(data.get(key) for key in ("tools", "skills", "connectors")) and all(
        data.get(key) is False
        for key in (
            "enableToolSearching",
            "enableBrowserTool",
            "enableImageSearch",
            "enableCodeInterpreter",
        )
    )
    return {
        "PLATFORM_ROLE_STATUS": "PASS" if not role_markers else "FINDING",
        "PLATFORM_MODEL_STATUS": "PASS" if model_ok else "FINDING",
        "PLATFORM_SCHEMA_STATUS": "PASS" if schema_ok else "FINDING",
        "PLATFORM_CONTEXT_MEMORY_STATUS": "PASS" if context_ok else "FINDING",
        "PLATFORM_TOOLS_KNOWLEDGE_STATUS": (
            "PASS" if tools_ok and not data.get("knowledgeBases") else "FINDING"
        ),
        "ROLE_FORBIDDEN_MARKERS": ",".join(role_markers),
    }


def _control_population() -> tuple[list[dict[str, Any]], dict[tuple[str, str], dict[str, str]]]:
    specs: list[dict[str, Any]] = []
    oracle: dict[tuple[str, str], dict[str, str]] = {}
    for case_id in CONTROL_CASE_IDS:
        path = ROOT / "golden" / "cases" / f"{case_id.lower()}_"
        matches = sorted(path.parent.glob(path.name + "*.json"))
        if len(matches) != 1:
            raise ValueError(f"expected one fixture for {case_id}")
        fixture_path = matches[0]
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        fixture_specs = evaluation._group_specs_for_fixture(
            fixture,
            filename=str(fixture_path.relative_to(ROOT)),
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
    control_oracle: dict[tuple[str, str], dict[str, str]],
    configuration_fingerprint: str,
) -> dict[str, Any]:
    original_load_population = evaluation._load_population
    original_configuration_fingerprint = evaluation._configuration_fingerprint
    original_total = evaluation.TOTAL_GOLDEN_FIXTURES
    original_reached = evaluation.CATEGORY_REACHED_FIXTURES
    original_groups = evaluation.GROUPS_PER_ROUND
    original_total_calls = evaluation.TOTAL_PLANNED_LIVE_CALLS
    original_budget = evaluation.LIVE_CALL_BUDGET

    def narrow_population():
        fixtures = [
            {"filename": spec["filename"], "fixture": spec["fixture"]}
            for spec in control_specs
        ]
        return {"cases": fixtures}, fixtures

    try:
        evaluation._load_population = narrow_population
        evaluation._configuration_fingerprint = (
            lambda specs, oracle: configuration_fingerprint
        )
        evaluation.TOTAL_GOLDEN_FIXTURES = len(control_specs)
        evaluation.CATEGORY_REACHED_FIXTURES = len(control_specs)
        evaluation.GROUPS_PER_ROUND = len(control_specs)
        evaluation.TOTAL_PLANNED_LIVE_CALLS = CONTROL_ROUNDS * len(control_specs)
        evaluation.LIVE_CALL_BUDGET = len(control_specs)
        report = evaluation.run_evaluation(
            config=config,
            round_index=round_index,
            deployment_provenance=snapshot,
        )
    finally:
        evaluation._load_population = original_load_population
        evaluation._configuration_fingerprint = original_configuration_fingerprint
        evaluation.TOTAL_GOLDEN_FIXTURES = original_total
        evaluation.CATEGORY_REACHED_FIXTURES = original_reached
        evaluation.GROUPS_PER_ROUND = original_groups
        evaluation.TOTAL_PLANNED_LIVE_CALLS = original_total_calls
        evaluation.LIVE_CALL_BUDGET = original_budget

    if report.get("CONFIGURATION_FINGERPRINT") != configuration_fingerprint:
        raise RuntimeError("narrow report is not bound to the full current configuration")
    for row in report.get("RESULTS", []):
        expected = control_oracle[(row["fixture_id"], row["event_group_id"])]
        if row.get("expected") != expected:
            raise RuntimeError("narrow control expected outcome differs from fixture oracle")
    return report


def _round_summary(report: dict[str, Any]) -> dict[str, Any]:
    by_case = {
        row["fixture_id"]: {
            "matches_golden": row.get("matches_golden"),
            "earliest_failure_type": row.get("earliest_failure_type"),
            "actual": row.get("actual"),
            "expected": row.get("expected"),
            "acceptance_evidence_complete": evaluation._live_evidence_complete(
                row.get("acceptance_evidence", {})
            ),
        }
        for row in report.get("RESULTS", [])
    }
    attempts = report.get("LIVE_CALL_COUNT", 0)
    logical = len(report.get("RESULTS", []))
    return {
        "round_index": report.get("ROUND_INDEX"),
        "acceptance_status": report.get("CATEGORY_53_GROUP_LIVE_ACCEPTANCE"),
        "logical_calls": logical,
        "transport_attempts": attempts,
        "transport_retries": max(0, attempts - logical),
        "evidence_chain_status": report.get("ACCEPTANCE_EVIDENCE_CHAIN_STATUS"),
        "by_case": by_case,
    }


def _overall_conclusion(rounds: list[dict[str, Any]]) -> str:
    if any(
        item["evidence_chain_status"] != "COMPLETE"
        or any(not value["acceptance_evidence_complete"] for value in item["by_case"].values())
        for item in rounds
    ):
        return "ACCEPTANCE_INFRASTRUCTURE_FAILURE"
    states: dict[str, list[bool | None]] = {case_id: [] for case_id in CONTROL_CASE_IDS}
    for item in rounds:
        for case_id in CONTROL_CASE_IDS:
            states[case_id].append(item["by_case"].get(case_id, {}).get("matches_golden"))
    if any(any(value is None for value in values) for values in states.values()):
        return "ACCEPTANCE_INFRASTRUCTURE_FAILURE"
    if any(len(set(values)) > 1 for values in states.values()):
        return "STOCHASTIC_OR_INCONSISTENT"
    if all(states[case_id] == [True] * CONTROL_ROUNDS for case_id in CONTROL_CASE_IDS):
        return "CURRENT_LIVE_BOUNDARIES_PASS"
    if states["G100"] == [False] * CONTROL_ROUNDS and states["G101"] == [False] * CONTROL_ROUNDS:
        return "BOTH_BOUNDARIES_LIVE_SEMANTIC_FAILURE"
    if states["G100"] == [False] * CONTROL_ROUNDS:
        return "G100_LIVE_SEMANTIC_FAILURE"
    if states["G101"] == [False] * CONTROL_ROUNDS:
        return "G101_LIVE_SEMANTIC_FAILURE"
    return "OVER_CORRECTION_OR_NEIGHBOR_FAILURE"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out-dir",
        default=str(ROOT / "acceptance" / "category_narrow_control_20261111"),
    )
    parser.add_argument(
        "--snapshot-dir",
        default=str(ROOT / "docs" / "category-v4-final-seal"),
    )
    args = parser.parse_args()
    out_dir = Path(args.out_dir)
    snapshot_dir = Path(args.snapshot_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise SystemExit(f"refusing to overwrite non-empty output directory: {out_dir}")

    config = MaiAgentCategorySemanticProviderConfig.from_environment()
    if config is None:
        raise SystemExit("CATEGORY_MAIAGENT_CONFIGURATION_UNAVAILABLE")
    control_specs, control_oracle = _control_population()
    configuration_fingerprint = _full_configuration_fingerprint()
    if configuration_fingerprint != "695988ff08b5aa792c68abc6dc4ad243aea88f01fe6b2b7caa10ca174006d749":
        raise SystemExit("current configuration fingerprint differs from the predeclared repair")

    readback, raw_readback = _fetch_chatbot_readback(config)
    snapshot = _snapshot_from_readback(readback)
    review = _deployment_review(readback)
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
        "hard_cap_category_attempts": HARD_CAP,
        "configuration_fingerprint": configuration_fingerprint,
        "deployment_fingerprint": deployment_record["DEPLOYMENT_FINGERPRINT"],
        "runtime_helper_identity_fingerprint": deployment_record[
            "RUNTIME_HELPER_IDENTITY_FINGERPRINT"
        ],
        "same_runtime_helper_binding": deployment_record["SAME_RUNTIME_HELPER_BINDING"],
        "platform_review": review,
        "readback_sha256": hashlib.sha256(raw_readback).hexdigest(),
        "new_category_semantic_calls_before_plan": 0,
    }
    _write_json(out_dir / "narrow_control_plan.json", plan)

    reports: list[dict[str, Any]] = []
    total_attempts = 0
    for round_index in range(1, CONTROL_ROUNDS + 1):
        report = _run_round(
            round_index=round_index,
            config=config,
            snapshot=snapshot,
            control_specs=control_specs,
            control_oracle=control_oracle,
            configuration_fingerprint=configuration_fingerprint,
        )
        total_attempts += int(report.get("LIVE_CALL_COUNT", 0))
        if total_attempts > HARD_CAP:
            raise SystemExit("CATEGORY_SEMANTIC_HARD_CAP_EXCEEDED")
        serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
        if config.api_key.lower() in serialized.lower() or "authorization" in serialized.lower():
            raise SystemExit("SECRET_LEAK_IN_ACCEPTANCE_REPORT")
        reports.append(report)
        _write_json(out_dir / f"round{round_index}.json", report)

    round_summaries = [_round_summary(report) for report in reports]
    summary = {
        "verdict": _overall_conclusion(round_summaries),
        "configuration_fingerprint": configuration_fingerprint,
        "deployment_fingerprint": deployment_record["DEPLOYMENT_FINGERPRINT"],
        "runtime_helper_identity_fingerprint": deployment_record[
            "RUNTIME_HELPER_IDENTITY_FINGERPRINT"
        ],
        "same_runtime_helper_binding": deployment_record["SAME_RUNTIME_HELPER_BINDING"],
        "planned_rounds": CONTROL_ROUNDS,
        "planned_logical_category_calls": PLANNED_LOGICAL_CALLS,
        "actual_logical_category_calls": sum(item["logical_calls"] for item in round_summaries),
        "transport_attempts": total_attempts,
        "transport_retries": sum(item["transport_retries"] for item in round_summaries),
        "hard_cap": HARD_CAP,
        "rounds": round_summaries,
        "production_report_run": "NO",
        "writer_calls": 0,
        "event_identity_calls": 0,
    }
    _write_json(out_dir / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary["verdict"] == "CURRENT_LIVE_BOUNDARIES_PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
