"""Offline checks for Category Event Group oracle reconciliation and harness gates."""

from __future__ import annotations

from copy import deepcopy
import unittest
from unittest.mock import patch

import scripts.category_semantic_evaluation as evaluation
from src.weekly_report.category_semantic_provider import MaiAgentCategorySemanticProviderConfig
from src.weekly_report.contracts import CategoryState


class _AssignedProcurementStub:
    def __init__(self, *, cite_inside_ascii_word: bool = False):
        self.call_count = 0
        self.payloads: list[dict] = []
        self.cite_inside_ascii_word = cite_inside_ascii_word

    def __call__(self, request):
        self.call_count += 1
        self.payloads.append(request.as_payload())
        source = request.sources[0]
        content = source.substantive_content
        start, end = 0, len(content)
        if self.cite_inside_ascii_word:
            found = False
            for candidate_start in range(1, len(content) - 1):
                if not all(
                    character.isascii() and character.isalnum()
                    for character in (content[candidate_start - 1], content[candidate_start])
                ):
                    continue
                for candidate_end in range(len(content) - 1, candidate_start, -1):
                    if not all(
                        character.isascii() and character.isalnum()
                        for character in (content[candidate_end - 1], content[candidate_end])
                    ):
                        continue
                    candidate_quote = content[candidate_start:candidate_end]
                    first = content.find(candidate_quote)
                    if first == candidate_start and content.find(candidate_quote, first + 1) < 0:
                        start, end = candidate_start, candidate_end
                        found = True
                        break
                if found:
                    break
        quote = content[start:end]
        return {
            "category_state": CategoryState.CATEGORY_ASSIGNED.value,
            "primary_category_id": "PROCUREMENT",
            "subtype": None,
            "category_resolution_reason": None,
            "citations": [{"candidate_id": source.candidate_id, "quote": quote}],
        }


def _deployment_snapshot() -> dict:
    return {
        "snapshot_contract_version": evaluation.DEPLOYMENT_SNAPSHOT_CONTRACT_VERSION,
        "platform": {
            "provider": "MaiAgent",
            "chatbot_instance_id": "category-instance-123",
            "model_identifier": "GPT-5.6 Luna (OpenAI)",
        },
        "role_instruction": {
            "content": "Use only category_request and authoritative_response_contract.\nOutput one JSON object.",
        },
        "structured_output": {
            "schema": {
                "type": "object",
                "properties": {"category_state": {"type": "string"}},
                "additionalProperties": False,
            },
        },
        "answer_mode": "RAG QA",
        "knowledge_base": {"state": "none configured"},
        "skills_tools": {"selected": ["structured-output"]},
        "generation_settings": {"model_max_output_tokens": 128000},
        "context_memory_settings": {"conversation_memory": "enabled"},
        "unavailable_platform_facts": [
            "chatbot_configuration_revision",
            "complete_generation_parameter_set",
            "platform_schema_identity",
            "platform_schema_version",
        ],
    }


class CategorySemanticEvaluationHarnessTests(unittest.TestCase):
    def setUp(self):
        self.manifest, self.fixtures = evaluation._load_population()

    def test_phase_a_reconciles_fixture_oracles_to_all_53_event_groups(self):
        specs, oracle_by_group, counts = evaluation._phase_a_reconcile(self.fixtures)

        self.assertEqual(counts["total_fixtures"], 85)
        self.assertEqual(counts["category_reached_fixtures"], 52)
        self.assertEqual(counts["fixture_assigned"], 46)
        self.assertEqual(counts["fixture_unresolved"], 6)
        self.assertEqual(counts["fixture_not_evaluated"], 33)
        self.assertEqual(counts["prepared_event_groups"], 53)
        self.assertEqual(counts["group_level_assigned"], 47)
        self.assertEqual(counts["group_level_unresolved"], 6)
        self.assertEqual(len(oracle_by_group), 53)

        g13 = [row for row in counts["mapping_rows"] if row["fixture_id"] == "G13"]
        self.assertEqual(len(g13), 2)
        self.assertEqual(
            [row["fixture_candidate_ids"] for row in g13],
            [["C1"], ["C2"]],
        )
        self.assertTrue(all(
            row["expected"] == {
                "category_state": "CATEGORY_ASSIGNED",
                "primary_category_id": "PROCUREMENT",
            }
            for row in g13
        ))

    def test_all_53_request_payloads_exclude_oracle_and_fixture_identity(self):
        specs, _, counts = evaluation._phase_a_reconcile(self.fixtures)

        self.assertEqual(counts["prepared_event_groups"], 53)
        passed, failures = evaluation._oracle_leakage_check(specs)
        self.assertTrue(passed, failures)
        for spec in specs:
            self.assertNotIn(spec["case_id"], spec["request_payload"])
            self.assertNotIn(spec["filename"], spec["request_payload"])

    def test_offline_stub_uses_one_classifier_proposal_per_group_and_ignores_subtype(self):
        provider = _AssignedProcurementStub(cite_inside_ascii_word=True)

        report = evaluation.run_evaluation(provider=provider)

        self.assertEqual(provider.call_count, 53)
        self.assertEqual(len(provider.payloads), 53)
        self.assertEqual(report["CATEGORY_53_GROUP_LIVE_ACCEPTANCE"], "NOT_LIVE_TEST")
        self.assertEqual(report["PREPARED_EVENT_GROUPS"], 53)
        self.assertEqual(report["ORACLE_MAPPING"], "PASS")
        self.assertEqual(report["ORACLE_LEAKAGE_CHECK"], "PASS")
        self.assertEqual(report["MAIAGENT_ADAPTER_USED"], "NO")
        self.assertEqual(report["RESPONSES_ADAPTER_USED"], "NO")
        self.assertEqual(report["ACCEPTANCE_VERSION"], evaluation.ACCEPTANCE_VERSION)
        self.assertEqual(report["ROUND_INDEX"], 1)
        self.assertEqual(report["PLANNED_ROUNDS"], 3)
        self.assertEqual(report["GROUPS_PER_ROUND"], 53)
        self.assertEqual(report["TOTAL_PLANNED_LIVE_CALLS"], 159)
        self.assertEqual(len(report["CONFIGURATION_FINGERPRINT"]), 64)
        self.assertEqual(
            report["DEPLOYMENT_PROVENANCE_STATUS"],
            "DEPLOYMENT_PROVENANCE_UNAVAILABLE",
        )

        g13 = [row for row in report["RESULTS"] if row["fixture_id"] == "G13"]
        self.assertEqual(len(g13), 2)
        for row in g13:
            self.assertTrue(row["matches_golden"])
            self.assertIsNone(row["actual"]["subtype"])
            self.assertEqual(row["semantic_citation_review"], "HUMAN_REVIEW_REQUIRED")
            self.assertTrue(row["semantic_citation_concerns"])
            self.assertEqual(row["citations"][0]["quote"], row["citations"][0]["resolved_substring"])
            self.assertIsInstance(row["citations"][0]["resolved_start"], int)
            self.assertIsInstance(row["citations"][0]["resolved_end"], int)
            self.assertEqual(row["earliest_failure_type"], None)

    def test_old_g82_conflict_citation_message_is_not_string_classified(self):
        class InvalidResult:
            provenance = {"validation_error": "conflict citations require a conflict reason"}
            category_resolution_reason = type("Reason", (), {"value": "SEMANTIC_HELPER_INVALID_RESPONSE"})()

        self.assertEqual(
            evaluation._first_failure(InvalidResult(), {}, None),
            "CLASSIFIER_INVALID_RESPONSE",
        )

    def test_all_six_proxy_variables_block_before_transport(self):
        self.assertEqual(
            evaluation._proxy_blockers({name: "" for name in evaluation.PROXY_ENV_VARS}),
            list(evaluation.PROXY_ENV_VARS),
        )
        calls = []

        def forbidden_transport(*args, **kwargs):
            calls.append((args, kwargs))
            raise AssertionError("transport must not be called when proxy gate blocks")

        config = MaiAgentCategorySemanticProviderConfig(
            api_base="https://maiagent.invalid",
            api_key="test-only",
            chatbot_id="category-test-only",
        )
        with patch.object(evaluation, "_proxy_blockers", return_value=["HTTP_PROXY"]):
            report = evaluation.run_evaluation(config=config, transport=forbidden_transport)

        self.assertEqual(report["BLOCKER"], "LOCAL_PROXY_VARIABLES_MUST_BE_ABSENT")
        self.assertEqual(report["LIVE_CALL_COUNT"], 0)
        self.assertEqual(calls, [])

    def test_configuration_fingerprint_is_deterministic_and_relevant(self):
        specs, oracle, _ = evaluation._phase_a_reconcile(self.fixtures)
        first = evaluation._configuration_fingerprint(specs, oracle)
        second = evaluation._configuration_fingerprint(specs, oracle)
        self.assertEqual(first, second)

        with patch.object(
            evaluation,
            "_CATEGORY_GUIDANCE",
            evaluation._CATEGORY_GUIDANCE + ("A reviewed generic rule change.",),
        ):
            changed = evaluation._configuration_fingerprint(specs, oracle)
        self.assertNotEqual(first, changed)

        with patch.dict(
            "os.environ",
            {
                "UNRELATED_DEBUG_TIMESTAMP": "2099-01-01T00:00:00Z",
                "UNRELATED_RANDOM_VALUE": "123456789",
            },
        ):
            irrelevant_environment = evaluation._configuration_fingerprint(specs, oracle)
        self.assertEqual(first, irrelevant_environment)

        specs[0]["irrelevant_debug_artifact"] = {
            "timestamp": "2099-01-01T00:00:00Z",
            "random": 123456789,
        }
        irrelevant_artifact = evaluation._configuration_fingerprint(specs, oracle)
        self.assertEqual(first, irrelevant_artifact)

    def test_final_seal_requires_all_three_complete_zero_error_rounds(self):
        fingerprint = "a" * 64

        def passing_round(index):
            return {
                "CATEGORY_53_GROUP_LIVE_ACCEPTANCE": "PASS",
                "ACCEPTANCE_VERSION": evaluation.ACCEPTANCE_VERSION,
                "CONFIGURATION_FINGERPRINT": fingerprint,
                "DEPLOYMENT_PROVENANCE_STATUS": "OBSERVED_AND_FROZEN",
                "DEPLOYMENT_SNAPSHOT_CONTRACT_VERSION": evaluation.DEPLOYMENT_SNAPSHOT_CONTRACT_VERSION,
                "DEPLOYMENT_FINGERPRINT": "b" * 64,
                "ROUND_INDEX": index,
                "LIVE_CALL_COUNT": 53,
                "HTTP_200_COUNT": 53,
                "CLASSIFIER_ACCEPTED_COUNT": 53,
                "CLASSIFIER_INVALID_COUNT": 0,
                "CATEGORY_STATE_MISMATCH_COUNT": 0,
                "PRIMARY_CATEGORY_MISMATCH_COUNT": 0,
                "RESOLUTION_REASON_MISMATCH_COUNT": 0,
                "EXACT_CATEGORY_MATCH_COUNT": 53,
            }

        reports = [passing_round(index) for index in (1, 2, 3)]
        passed = evaluation.assess_final_seal_batch(reports)
        self.assertEqual(passed["CATEGORY_V4_FINAL_SEAL"], "PASS")
        self.assertEqual(passed["FAILED_ROUNDS"], [])

        reports[1]["RESOLUTION_REASON_MISMATCH_COUNT"] = 1
        reports[1]["EXACT_CATEGORY_MATCH_COUNT"] = 52
        reports[1]["CATEGORY_53_GROUP_LIVE_ACCEPTANCE"] = "FINDINGS"
        failed = evaluation.assess_final_seal_batch(reports)
        self.assertEqual(failed["CATEGORY_V4_FINAL_SEAL"], "FINDINGS")
        self.assertEqual([item["round_index"] for item in failed["FAILED_ROUNDS"]], [2])

        incomplete = evaluation.assess_final_seal_batch(reports[:2])
        self.assertEqual(incomplete["CATEGORY_V4_FINAL_SEAL"], "BLOCKED")

        missing_deployment = [passing_round(index) for index in (1, 2, 3)]
        missing_deployment[2].pop("DEPLOYMENT_FINGERPRINT")
        missing_deployment[2]["DEPLOYMENT_PROVENANCE_STATUS"] = (
            "DEPLOYMENT_PROVENANCE_UNAVAILABLE"
        )
        blocked = evaluation.assess_final_seal_batch(missing_deployment)
        self.assertEqual(blocked["CATEGORY_V4_FINAL_SEAL"], "BLOCKED")
        self.assertEqual(
            blocked["BLOCKER"],
            "DEPLOYMENT_PROVENANCE_IS_NOT_OBSERVED_AND_FROZEN",
        )

    def test_deployment_snapshot_validates_and_fingerprints_observed_contract(self):
        snapshot = _deployment_snapshot()
        snapshot["skills_tools"]["selected"] = ["structured-output", "json-schema"]
        first = evaluation._deployment_provenance_record(snapshot)
        reordered = deepcopy(snapshot)
        reordered["skills_tools"]["selected"].reverse()
        reordered["unavailable_platform_facts"].reverse()
        reordered["platform"] = dict(reversed(list(reordered["platform"].items())))
        second = evaluation._deployment_provenance_record(reordered)
        self.assertEqual(first, second)
        self.assertEqual(first["DEPLOYMENT_PROVENANCE_STATUS"], "OBSERVED_AND_FROZEN")
        self.assertEqual(
            first["DEPLOYMENT_SNAPSHOT_CONTRACT_VERSION"],
            evaluation.DEPLOYMENT_SNAPSHOT_CONTRACT_VERSION,
        )
        self.assertEqual(len(first["DEPLOYMENT_FINGERPRINT"]), 64)

    def test_deployment_snapshot_requires_observed_identity_content(self):
        required_cases = (
            ("role_instruction", "content"),
            ("structured_output", "schema"),
            ("platform", "chatbot_instance_id"),
            ("platform", "model_identifier"),
        )
        for parent, child in required_cases:
            with self.subTest(parent=parent, child=child):
                snapshot = _deployment_snapshot()
                snapshot[parent].pop(child)
                with self.assertRaises(ValueError):
                    evaluation._deployment_provenance_record(snapshot)

        snapshot = _deployment_snapshot()
        snapshot["structured_output"]["schema"] = {"schema_version": "category-proposal-v4"}
        with self.assertRaises(ValueError):
            evaluation._deployment_provenance_record(
                {key: value for key, value in snapshot.items() if key != "structured_output"}
            )

    def test_deployment_snapshot_allows_optional_metadata_and_unavailable_facts(self):
        snapshot = _deployment_snapshot()
        snapshot["optional_platform_metadata"] = {}
        record = evaluation._deployment_provenance_record(snapshot)
        self.assertEqual(record["DEPLOYMENT_PROVENANCE_STATUS"], "OBSERVED_AND_FROZEN")

        unavailable_snapshot = _deployment_snapshot()
        unavailable_snapshot.pop("answer_mode")
        unavailable_snapshot["unavailable_platform_facts"].append("answer_mode")
        self.assertEqual(
            evaluation._deployment_provenance_record(unavailable_snapshot)[
                "DEPLOYMENT_PROVENANCE_STATUS"
            ],
            "OBSERVED_AND_FROZEN",
        )

        snapshot["optional_platform_metadata"] = {
            "chatbot_configuration_revision": "revision-7",
            "schema_identity": "platform-schema-7",
            "schema_version": "platform-v4",
        }
        self.assertEqual(
            evaluation._deployment_provenance_record(snapshot)["DEPLOYMENT_PROVENANCE_STATUS"],
            "OBSERVED_AND_FROZEN",
        )

        snapshot["optional_platform_metadata"]["chatbot_configuration_revision"] = (
            snapshot["platform"]["chatbot_instance_id"]
        )
        with self.assertRaises(ValueError):
            evaluation._deployment_provenance_record(snapshot)

    def test_deployment_snapshot_rejects_placeholders_and_never_backfills(self):
        for path in (
            ("platform", "model_identifier"),
            ("platform", "chatbot_instance_id"),
            ("role_instruction", "content"),
        ):
            with self.subTest(path=path):
                snapshot = _deployment_snapshot()
                snapshot[path[0]][path[1]] = "UNAVAILABLE"
                with self.assertRaises(ValueError):
                    evaluation._deployment_provenance_record(snapshot)

        snapshot = _deployment_snapshot()
        snapshot["unavailable_platform_facts"] = ["platform_schema_version"]
        self.assertEqual(
            evaluation._deployment_provenance_record(snapshot)["DEPLOYMENT_PROVENANCE_STATUS"],
            "OBSERVED_AND_FROZEN",
        )

    def test_deployment_snapshot_fingerprint_changes_for_observable_behavior_inputs(self):
        base = evaluation._deployment_provenance_record(_deployment_snapshot())[
            "DEPLOYMENT_FINGERPRINT"
        ]
        changes = (
            (("role_instruction", "content"), "changed role"),
            (("platform", "model_identifier"), "GPT-5.6 Sol (OpenAI)"),
            (("generation_settings", "model_max_output_tokens"), 64000),
            (("context_memory_settings", "conversation_memory"), "disabled"),
            (("structured_output", "schema"), {"type": "object"}),
            (("answer_mode",), "normal"),
            (("knowledge_base", "state"), "attached"),
        )
        for path, value in changes:
            with self.subTest(path=path):
                snapshot = _deployment_snapshot()
                target = snapshot
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                changed = evaluation._deployment_provenance_record(snapshot)[
                    "DEPLOYMENT_FINGERPRINT"
                ]
                self.assertNotEqual(base, changed)

    def test_deployment_snapshot_audit_metadata_does_not_change_fingerprint(self):
        snapshot = _deployment_snapshot()
        first = evaluation._deployment_provenance_record(snapshot)
        snapshot["audit_metadata"] = {
            "captured_at": "2099-01-01T00:00:00Z",
            "screenshot_filename": "capture-a.png",
            "operator_note": "first read-back",
        }
        second = evaluation._deployment_provenance_record(snapshot)
        self.assertEqual(
            first["DEPLOYMENT_FINGERPRINT"], second["DEPLOYMENT_FINGERPRINT"]
        )

    def test_malformed_snapshot_blocks_before_transport(self):
        config = MaiAgentCategorySemanticProviderConfig(
            api_base="https://maiagent.invalid",
            api_key="test-only",
            chatbot_id="category-test-only",
        )

        def forbidden_transport(*args, **kwargs):
            raise AssertionError("transport must not be called for malformed snapshot")

        with self.assertRaises(ValueError):
            evaluation.run_evaluation(
                config=config,
                transport=forbidden_transport,
                deployment_provenance={"snapshot_contract_version": "wrong"},
            )

        self.assertEqual(
            evaluation._deployment_provenance_record(None),
            {"DEPLOYMENT_PROVENANCE_STATUS": "DEPLOYMENT_PROVENANCE_UNAVAILABLE"},
        )

    def test_final_seal_contract_locks_predeclared_no_replacement_batch(self):
        contract = (evaluation.ROOT / "docs" / "ARCHITECTURE_CONTRACT.md").read_text(
            encoding="utf-8"
        )
        for expected in (
            "FINAL_SEAL_ROUNDS = 3",
            "GROUPS_PER_ROUND = 53",
            "TOTAL_PLANNED_LIVE_CALLS = 159",
            "EXACT_CATEGORY_MATCH_COUNT = 53",
            "不得平均、majority vote、挑選最佳 round",
            "不得為了取得 PASS 追加 round",
        ):
            self.assertIn(expected, contract)


if __name__ == "__main__":
    unittest.main()
