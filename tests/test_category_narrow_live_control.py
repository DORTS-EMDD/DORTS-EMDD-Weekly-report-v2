"""Offline tests for the bounded Category live-control orchestrator."""

from __future__ import annotations

import unittest

import scripts.category_narrow_live_control as control
import scripts.category_semantic_evaluation as evaluation


def _readback() -> dict:
    return {
        "id": "helper-instance",
        "instructions": "Answer bounded user requests using provided context only.",
        "largeLanguageModel": "model-uuid",
        "llm": {"id": "model-uuid", "name": "model-label"},
        "replyMode": "agent",
        "agentMode": "normal",
        "outputMode": "text",
        "rawOutputFormat": None,
        "knowledgeBases": [],
        "databases": [],
        "skills": [],
        "tools": [],
        "connectors": [],
        "customMaxLlmOutputTokens": None,
        "maxAgentIterations": 20,
        "agentTimeoutSeconds": 600,
        "thinkingConfig": None,
        "enableSizeBasedToolResultTruncation": False,
        "toolResultMaxChars": 8000,
        "enableClaudeStreamRetry": False,
        "enableMemberMemoryWrite": False,
        "enableMemberMemoryInjection": False,
        "enableVectorMemory": False,
        "enableCrossConversationSearch": False,
        "crossConversationLookbackDays": 90,
        "fileWorkspaceAvailable": True,
        "fileWorkspaceMode": "none",
        "fileWorkspaceStatus": {"folder": None, "state": None},
        "enableSearchMessagesTool": False,
        "enableGetMessageContextTool": False,
        "enableReadAttachmentFullTextTool": False,
        "enableParseAttachmentContentTool": False,
        "enableListAvailableParsersTool": False,
        "enableToolSearching": False,
        "enableBrowserTool": False,
        "enableImageSearch": False,
        "enableCodeInterpreter": False,
    }


class CategoryNarrowLiveControlTests(unittest.TestCase):
    def test_control_population_uses_existing_golden_oracles(self):
        specs, oracle = control._control_population()
        self.assertEqual(
            [spec["case_id"] for spec in specs],
            list(control.CONTROL_CASE_IDS),
        )
        self.assertEqual(len(oracle), len(control.CONTROL_CASE_IDS))
        self.assertEqual(
            oracle[("G100", specs[0]["group"].event_id)],
            {
                "category_state": "CATEGORY_UNRESOLVED",
                "category_resolution_reason": "NO_CATEGORY_DEFINING_ACTION",
            },
        )
        self.assertEqual(
            oracle[("G101", specs[1]["group"].event_id)],
            {"category_state": "CATEGORY_ASSIGNED", "primary_category_id": "TECHNICAL_DEVELOPMENT"},
        )

    def test_snapshot_mapping_and_platform_review_are_observer_only(self):
        readback = _readback()
        snapshot = control._snapshot_from_readback(readback)
        self.assertEqual(
            snapshot["snapshot_contract_version"],
            evaluation.DEPLOYMENT_SNAPSHOT_CONTRACT_VERSION,
        )
        self.assertEqual(snapshot["platform"]["chatbot_instance_id"], "helper-instance")
        self.assertEqual(snapshot["structured_output"]["schema"]["output_mode"], "text")
        record = evaluation._deployment_provenance_record(
            snapshot,
            runtime_helper_identity="helper-instance",
        )
        self.assertEqual(record["SAME_RUNTIME_HELPER_BINDING"], "PROVEN")
        review = control._deployment_review(readback)
        self.assertEqual(
            {key: value for key, value in review.items() if key.endswith("_STATUS")},
            {
                "PLATFORM_ROLE_STATUS": "PASS",
                "PLATFORM_MODEL_STATUS": "PASS",
                "PLATFORM_SCHEMA_STATUS": "PASS",
                "PLATFORM_CONTEXT_MEMORY_STATUS": "PASS",
                "PLATFORM_TOOLS_KNOWLEDGE_STATUS": "PASS",
            },
        )

    def test_conclusion_requires_all_rounds_and_all_controls(self):
        rounds = [
            {
                "evidence_chain_status": "COMPLETE",
                "by_case": {
                    case_id: {"matches_golden": True, "acceptance_evidence_complete": True}
                    for case_id in control.CONTROL_CASE_IDS
                },
            }
            for _ in range(control.CONTROL_ROUNDS)
        ]
        self.assertEqual(
            control._overall_conclusion(rounds),
            "CURRENT_LIVE_BOUNDARIES_PASS",
        )
        rounds[1]["by_case"]["G101"]["matches_golden"] = False
        self.assertEqual(
            control._overall_conclusion(rounds),
            "STOCHASTIC_OR_INCONSISTENT",
        )
        for item in rounds:
            item["by_case"]["G101"]["matches_golden"] = False
        self.assertEqual(control._overall_conclusion(rounds), "G101_LIVE_SEMANTIC_FAILURE")


if __name__ == "__main__":
    unittest.main()
