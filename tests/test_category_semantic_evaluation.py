"""Offline checks for Category Event Group oracle reconciliation and harness gates."""

from __future__ import annotations

import hashlib
import json
import unittest
from copy import deepcopy
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

import scripts.category_formal_v7_seal as formal_seal
import scripts.category_narrow_v7_revaluation as historical_candidate
import scripts.category_semantic_evaluation as evaluation
from src.weekly_report import category_semantic_provider as category_provider_module
from src.weekly_report import classifier as classifier_module
from src.weekly_report.category_semantic_provider import (
    MaiAgentCategorySemanticProviderConfig,
)
from src.weekly_report.contracts import CategoryState


class _AssignedProcurementStub:
    def __init__(self):
        self.call_count = 0
        self.payloads: list[dict] = []

    def __call__(self, request):
        self.call_count += 1
        self.payloads.append(request.as_payload())
        return {
            "actions": [{
                "action_id": "A1",
                "action_kind": "PROCUREMENT_AWARD",
                "subject_kind": "PROCUREMENT_ACTION",
                "lifecycle_relation": "PROCUREMENT_LIFECYCLE",
                "adoption_status": "COMPLETED",
                "citations": [{"source_ref": "M1", "sentence_ids": ["S1"]}],
            }],
            "principal_action_id": "A1",
            "subtype": None,
            "examined_citations": [{"source_ref": "M1", "sentence_ids": ["S1"]}],
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


def _bound_deployment_record(snapshot: dict, identity: str = "category-instance-123") -> dict:
    return evaluation._deployment_provenance_record(
        snapshot,
        runtime_helper_identity=identity,
    )


class CategorySemanticEvaluationHarnessTests(unittest.TestCase):
    def setUp(self):
        self.manifest, self.fixtures = evaluation._load_population()

    def test_phase_a_reconciles_fixture_oracles_to_all_53_event_groups(self):
        _specs, oracle_by_group, counts = evaluation._phase_a_reconcile(self.fixtures)

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
        provider = _AssignedProcurementStub()

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
            # RC-16: sentence citations cannot cut inside a word.
            self.assertFalse(row["semantic_citation_concerns"])
            self.assertEqual(row["citations"][0]["source_ref"], "M1")
            self.assertEqual(row["citations"][0]["sentence_ids"], ["S1"])
            self.assertTrue(row["citations"][0]["resolved_substring"])
            self.assertIsInstance(row["citations"][0]["resolved_start"], int)
            self.assertIsInstance(row["citations"][0]["resolved_end"], int)
            self.assertEqual(row["earliest_failure_type"], None)

    def test_old_g82_conflict_citation_message_is_not_string_classified(self):
        class InvalidResult:
            provenance: ClassVar = {
                "validation_error": "conflict citations require a conflict reason"
            }
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

        with patch.object(evaluation, "CATEGORY_SEMANTIC_PROMPT_VERSION", "category-principal-action-test"):
            changed_version = evaluation._configuration_fingerprint(specs, oracle)
        self.assertNotEqual(first, changed_version)

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

    def test_formal_configuration_binding_passes_for_checked_in_production(self):
        production, specs, oracle, _ = evaluation._resolve_checked_in_production_configuration(
            category_config=MaiAgentCategorySemanticProviderConfig(
                api_base="https://maiagent.invalid",
                api_key="test-only",
                chatbot_id="category-test-only",
            )
        )
        target = evaluation._target_configuration_identity(specs, oracle)
        binding = evaluation.enforce_category_configuration_binding(
            production=production,
            target=target,
            mode=evaluation.FORMAL_CURRENT_CONFIGURATION_SEAL,
        )
        self.assertEqual(binding["status"], "PASS")
        self.assertEqual(binding["mismatches"], {})

    def test_formal_binding_rejects_each_identity_mismatch_before_provider_call(self):
        production, specs, oracle, _ = evaluation._resolve_checked_in_production_configuration(
            category_config=MaiAgentCategorySemanticProviderConfig(
                api_base="https://maiagent.invalid",
                api_key="test-only",
                chatbot_id="category-test-only",
            )
        )
        target = evaluation._target_configuration_identity(specs, oracle)
        for field in (
            "guidance_digest",
            "prompt_identity",
            "response_contract_identity",
            "schema_identity",
            "configuration_fingerprint",
        ):
            with self.subTest(field=field):
                changed = dict(target.as_mapping())
                changed[field] = "changed-" + field
                changed_target = evaluation.CategoryAcceptanceConfigurationIdentity(
                    **changed
                )
                provider_calls = []
                with self.assertRaises(evaluation.CategoryConfigurationBindingError) as raised:
                    evaluation.enforce_category_configuration_binding(
                        production=production,
                        target=changed_target,
                        mode=evaluation.FORMAL_CURRENT_CONFIGURATION_SEAL,
                    )
                self.assertEqual(raised.exception.reason_code, evaluation.FORMAL_SEAL_PRODUCTION_CONFIGURATION_MISMATCH)
                self.assertEqual(provider_calls, [])

    def test_candidate_mode_allows_explicit_historical_guidance_but_formal_mode_rejects(self):
        production, specs, oracle, _ = evaluation._resolve_checked_in_production_configuration(
            category_config=MaiAgentCategorySemanticProviderConfig(
                api_base="https://maiagent.invalid",
                api_key="test-only",
                chatbot_id="category-test-only",
            )
        )
        historical_guidance = historical_candidate._recover_exact_v7_guidance()
        candidate = evaluation.CategoryAcceptanceConfigurationIdentity(
            guidance_digest=evaluation._guidance_digest(historical_guidance),
            prompt_identity=historical_candidate.V7_PROMPT_IDENTITY,
            response_contract_identity=category_provider_module.MAIAGENT_CATEGORY_MESSAGE_VERSION,
            schema_identity=category_provider_module.CATEGORY_SEMANTIC_SCHEMA_VERSION,
            configuration_fingerprint=evaluation._configuration_fingerprint_for(
                specs,
                oracle,
                guidance=historical_guidance,
                prompt_identity=historical_candidate.V7_PROMPT_IDENTITY,
                response_contract_identity=category_provider_module.MAIAGENT_CATEGORY_MESSAGE_VERSION,
                schema_identity=category_provider_module.CATEGORY_SEMANTIC_SCHEMA_VERSION,
                authoritative_response_schema=category_provider_module._CATEGORY_RESPONSE_SCHEMA,
                provider_schema_projection=category_provider_module._MAIAGENT_CATEGORY_RESPONSE_SCHEMA,
                provider_identifier=category_provider_module.MAIAGENT_CATEGORY_PROVIDER_IDENTIFIER,
                helper_version=category_provider_module.MAIAGENT_CATEGORY_SEMANTIC_HELPER_VERSION,
            ),
        )
        allowed = evaluation.enforce_category_configuration_binding(
            production=production,
            target=candidate,
            mode=evaluation.CANDIDATE_EXPERIMENT,
        )
        self.assertEqual(allowed["status"], "CANDIDATE_EXPERIMENT_ALLOWED")
        self.assertTrue(allowed["mismatches"])
        with self.assertRaises(evaluation.CategoryConfigurationBindingError):
            evaluation.enforce_category_configuration_binding(
                production=production,
                target=candidate,
                mode=evaluation.FORMAL_CURRENT_CONFIGURATION_SEAL,
            )

    def test_production_identity_tracks_the_single_checked_in_guidance_owner(self):
        baseline, _, _, _ = evaluation._resolve_checked_in_production_configuration(
            category_config=MaiAgentCategorySemanticProviderConfig(
                api_base="https://maiagent.invalid",
                api_key="test-only",
                chatbot_id="category-test-only",
            )
        )
        changed_guidance = classifier_module._CATEGORY_GUIDANCE + (
            "A generic audit-only guidance probe.",
        )
        with patch.object(classifier_module, "_CATEGORY_GUIDANCE", changed_guidance):
            changed, _, _, _ = evaluation._resolve_checked_in_production_configuration(
                category_config=MaiAgentCategorySemanticProviderConfig(
                    api_base="https://maiagent.invalid",
                    api_key="test-only",
                    chatbot_id="category-test-only",
                )
            )
        self.assertNotEqual(baseline.guidance_digest, changed.guidance_digest)
        self.assertNotEqual(
            baseline.configuration_fingerprint,
            changed.configuration_fingerprint,
        )

    def test_formal_runner_rejects_target_mismatch_before_any_provider_request(self):
        config = MaiAgentCategorySemanticProviderConfig(
            api_base="https://maiagent.invalid",
            api_key="test-only",
            chatbot_id="category-test-only",
        )
        with (
            patch.object(
                evaluation,
                "_CATEGORY_GUIDANCE",
                evaluation._CATEGORY_GUIDANCE + ("candidate-only guidance",),
            ),
            self.assertRaises(evaluation.CategoryConfigurationBindingError) as raised,
        ):
            formal_seal._prepare_configuration(config)
        self.assertEqual(
            raised.exception.reason_code,
            evaluation.FORMAL_SEAL_PRODUCTION_CONFIGURATION_MISMATCH,
        )

    def test_formal_runner_has_no_historical_in_memory_override_seam(self):
        source = formal_seal.__file__
        assert source is not None
        contents = Path(source).read_text(encoding="utf-8")
        self.assertNotIn("_apply_recovered_v7_guidance", contents)
        self.assertNotIn("category_narrow_v7_revaluation", contents)

    def test_final_seal_requires_all_three_complete_zero_error_rounds(self):
        fingerprint = "a" * 64

        def passing_round(index):
            return {
                "CATEGORY_53_GROUP_LIVE_ACCEPTANCE": "PASS",
                "ACCEPTANCE_VERSION": evaluation.ACCEPTANCE_VERSION,
                "ACCEPTANCE_EVIDENCE_VERSION": evaluation.ACCEPTANCE_EVIDENCE_VERSION,
                "CONFIGURATION_FINGERPRINT": fingerprint,
                "DEPLOYMENT_PROVENANCE_STATUS": "OBSERVED_AND_FROZEN",
                "DEPLOYMENT_SNAPSHOT_CONTRACT_VERSION": evaluation.DEPLOYMENT_SNAPSHOT_CONTRACT_VERSION,
                "DEPLOYMENT_FINGERPRINT": "b" * 64,
                "SAME_RUNTIME_HELPER_BINDING": "PROVEN",
                "ACCEPTANCE_EVIDENCE_CHAIN_STATUS": "COMPLETE",
                "ACCEPTANCE_EVIDENCE_COMPLETE_COUNT": 53,
                "RESULTS": [
                    {
                        "acceptance_evidence": {
                            "request_payload_sha256": "c" * 64,
                            "provider_request_body_sha256": "d" * 64,
                            "provider_response_body_sha256": "1" * 64,
                            "proposal_sha256": "e" * 64,
                            "validated_result_sha256": "f" * 64,
                            "chain_sha256": "0" * 64,
                            "transport_attempts": [
                                {
                                    "request_body_sha256": "d" * 64,
                                    "status_code": 200,
                                    "response_parse_status": "PARSEABLE_RESPONSE",
                                    "retry_authorized": False,
                                    "retry_reason": None,
                                }
                            ],
                            "transport_accounting": {
                                "status": "PASS",
                                "attempt_count": 1,
                                "retry_count": 0,
                                "retry_reasons": [],
                                "request_body_consistent": True,
                                "final_response_parse_status": "PARSEABLE_RESPONSE",
                                "unauthorized_retry": False,
                                "failure": None,
                            },
                        }
                    }
                    for _ in range(53)
                ],
                "ROUND_INDEX": index,
                "LIVE_CALL_COUNT": 53,
                "HTTP_200_COUNT": 53,
                "LOGICAL_CALL_COUNT": 53,
                "TRANSPORT_ATTEMPT_COUNT": 53,
                "FINAL_HTTP_200_COUNT": 53,
                "HTTP_200_ATTEMPT_COUNT": 53,
                "AUTHORIZED_TRANSPORT_RETRY_COUNT": 0,
                "UNAUTHORIZED_TRANSPORT_RETRY_COUNT": 0,
                "TRANSPORT_ACCOUNTING_STATUS": "PASS",
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

        historical_reports = [dict(report) for report in reports]
        for report in historical_reports:
            report.pop("ACCEPTANCE_EVIDENCE_VERSION")
            report.pop("SAME_RUNTIME_HELPER_BINDING")
            report.pop("ACCEPTANCE_EVIDENCE_CHAIN_STATUS")
            report.pop("ACCEPTANCE_EVIDENCE_COMPLETE_COUNT")
            report.pop("RESULTS")
        current_blocked = evaluation.assess_final_seal_batch(historical_reports)
        self.assertEqual(
            current_blocked["BLOCKER"],
            "CURRENT_ACCEPTANCE_EVIDENCE_VERSION_REQUIRED",
        )
        historical = evaluation.assess_historical_final_seal_batch(historical_reports)
        self.assertEqual(historical["CATEGORY_V4_FINAL_SEAL"], "PASS")
        self.assertEqual(historical["ACCEPTANCE_SCOPE"], "HISTORICAL_ONLY")
        self.assertEqual(historical["CURRENT_LIVE_SCOREABILITY"], "NO")

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

    def test_transport_retry_accounting_accepts_authorized_rc6_retry(self):
        request_hash = "a" * 64
        accounting = evaluation._transport_attempt_accounting(
            [
                {
                    "request_body_sha256": request_hash,
                    "status_code": 200,
                    "response_parse_status": "UNPARSEABLE_RESPONSE",
                    "retry_authorized": True,
                    "retry_reason": "UNPARSEABLE_RESPONSE",
                },
                {
                    "request_body_sha256": request_hash,
                    "status_code": 200,
                    "response_parse_status": "PARSEABLE_RESPONSE",
                    "retry_authorized": False,
                    "retry_reason": None,
                },
            ]
        )
        self.assertEqual(accounting["status"], "PASS")
        self.assertEqual(accounting["retry_count"], 1)
        self.assertEqual(accounting["retry_reasons"], ["UNPARSEABLE_RESPONSE"])

    def test_transport_retry_accounting_rejects_parseable_result_retry(self):
        request_hash = "b" * 64
        accounting = evaluation._transport_attempt_accounting(
            [
                {
                    "request_body_sha256": request_hash,
                    "status_code": 200,
                    "response_parse_status": "PARSEABLE_RESPONSE",
                    "retry_authorized": False,
                    "retry_reason": None,
                },
                {
                    "request_body_sha256": request_hash,
                    "status_code": 200,
                    "response_parse_status": "PARSEABLE_RESPONSE",
                    "retry_authorized": False,
                    "retry_reason": None,
                },
            ]
        )
        self.assertEqual(accounting["status"], "FINDINGS")
        self.assertTrue(accounting["unauthorized_retry"])
        self.assertEqual(accounting["failure"], "UNAUTHORIZED_TRANSPORT_RETRY")

    def test_deployment_snapshot_validates_and_fingerprints_observed_contract(self):
        snapshot = _deployment_snapshot()
        snapshot["skills_tools"]["selected"] = ["structured-output", "json-schema"]
        first = _bound_deployment_record(snapshot)
        reordered = deepcopy(snapshot)
        reordered["skills_tools"]["selected"].reverse()
        reordered["unavailable_platform_facts"].reverse()
        reordered["platform"] = dict(reversed(list(reordered["platform"].items())))
        second = _bound_deployment_record(reordered)
        self.assertEqual(first, second)
        self.assertEqual(first["DEPLOYMENT_PROVENANCE_STATUS"], "OBSERVED_AND_FROZEN")
        self.assertEqual(first["DEPLOYMENT_BINDING_STATUS"], "SAME_RUNTIME_HELPER_PROVEN")
        self.assertEqual(first["SAME_RUNTIME_HELPER_BINDING"], "PROVEN")
        self.assertEqual(
            first["RUNTIME_HELPER_IDENTITY_FINGERPRINT"],
            first["DEPLOYMENT_SNAPSHOT_IDENTITY_FINGERPRINT"],
        )
        self.assertEqual(
            first["DEPLOYMENT_SNAPSHOT_CONTRACT_VERSION"],
            evaluation.DEPLOYMENT_SNAPSHOT_CONTRACT_VERSION,
        )
        self.assertEqual(len(first["DEPLOYMENT_FINGERPRINT"]), 64)

    def test_different_runtime_helper_snapshot_fails_closed(self):
        with self.assertRaises(ValueError):
            _bound_deployment_record(
                _deployment_snapshot(),
                identity="different-category-instance",
            )

    def test_missing_runtime_helper_binding_is_not_frozen(self):
        record = evaluation._deployment_provenance_record(_deployment_snapshot())
        self.assertEqual(
            record["DEPLOYMENT_PROVENANCE_STATUS"],
            "DEPLOYMENT_PROVENANCE_UNAVAILABLE",
        )
        self.assertEqual(
            record["DEPLOYMENT_BINDING_STATUS"],
            "RUNTIME_HELPER_IDENTITY_UNAVAILABLE",
        )
        self.assertNotIn("DEPLOYMENT_FINGERPRINT", record)

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
                    _bound_deployment_record(snapshot)

        snapshot = _deployment_snapshot()
        snapshot["structured_output"]["schema"] = {"schema_version": "category-proposal-v4"}
        with self.assertRaises(ValueError):
            _bound_deployment_record(
                {key: value for key, value in snapshot.items() if key != "structured_output"}
            )

    def test_deployment_snapshot_allows_optional_metadata_and_unavailable_facts(self):
        snapshot = _deployment_snapshot()
        snapshot["optional_platform_metadata"] = {}
        record = _bound_deployment_record(snapshot)
        self.assertEqual(record["DEPLOYMENT_PROVENANCE_STATUS"], "OBSERVED_AND_FROZEN")

        unavailable_snapshot = _deployment_snapshot()
        unavailable_snapshot.pop("answer_mode")
        unavailable_snapshot["unavailable_platform_facts"].append("answer_mode")
        self.assertEqual(
            _bound_deployment_record(unavailable_snapshot)[
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
            _bound_deployment_record(snapshot)["DEPLOYMENT_PROVENANCE_STATUS"],
            "OBSERVED_AND_FROZEN",
        )

        snapshot["optional_platform_metadata"]["chatbot_configuration_revision"] = (
            snapshot["platform"]["chatbot_instance_id"]
        )
        with self.assertRaises(ValueError):
            _bound_deployment_record(snapshot)

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
                    _bound_deployment_record(snapshot)

        snapshot = _deployment_snapshot()
        snapshot["unavailable_platform_facts"] = ["platform_schema_version"]
        self.assertEqual(
            _bound_deployment_record(snapshot)["DEPLOYMENT_PROVENANCE_STATUS"],
            "OBSERVED_AND_FROZEN",
        )

    def test_deployment_snapshot_fingerprint_changes_for_observable_behavior_inputs(self):
        base = _bound_deployment_record(_deployment_snapshot())[
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
                changed = _bound_deployment_record(snapshot)[
                    "DEPLOYMENT_FINGERPRINT"
                ]
                self.assertNotEqual(base, changed)

    def test_deployment_snapshot_audit_metadata_does_not_change_fingerprint(self):
        snapshot = _deployment_snapshot()
        first = _bound_deployment_record(snapshot)
        snapshot["audit_metadata"] = {
            "captured_at": "2099-01-01T00:00:00Z",
            "screenshot_filename": "capture-a.png",
            "operator_note": "first read-back",
        }
        second = _bound_deployment_record(snapshot)
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
            {
                "DEPLOYMENT_PROVENANCE_STATUS": "DEPLOYMENT_PROVENANCE_UNAVAILABLE",
                "DEPLOYMENT_BINDING_STATUS": "DEPLOYMENT_SNAPSHOT_UNAVAILABLE",
            },
        )

    def test_offline_acceptance_retains_bound_request_response_chain(self):
        provider = _AssignedProcurementStub()
        report = evaluation.run_evaluation(provider=provider)

        self.assertEqual(report["ACCEPTANCE_EVIDENCE_VERSION"], evaluation.ACCEPTANCE_EVIDENCE_VERSION)
        self.assertEqual(report["CONFIGURATION_FINGERPRINT"], evaluation._configuration_fingerprint(
            evaluation._phase_a_reconcile(self.fixtures)[0],
            evaluation._phase_a_reconcile(self.fixtures)[1],
        ))
        row = report["RESULTS"][0]
        evidence = row["acceptance_evidence"]
        serialized_request = json.dumps(
            provider.payloads[0], ensure_ascii=False, separators=(",", ":")
        )
        self.assertEqual(
            evidence["request_payload_sha256"],
            hashlib.sha256(serialized_request.encode("utf-8")).hexdigest(),
        )
        self.assertEqual(evidence["proposal_evidence_status"], "PARSED_PROPOSAL_RETAINED")
        self.assertEqual(evidence["validation_status"], "CLASSIFIER_ACCEPTED")
        self.assertEqual(len(evidence["proposal_sha256"]), 64)
        self.assertEqual(len(evidence["validated_result_sha256"]), 64)
        self.assertEqual(len(evidence["chain_sha256"]), 64)
        self.assertEqual(
            evidence["configuration_fingerprint"],
            report["CONFIGURATION_FINGERPRINT"],
        )
        self.assertEqual(report["RESPONSES_ADAPTER_USED"], "NO")
        self.assertIsNone(evidence["provider_request_body_sha256"])
        self.assertNotIn("api_key", json.dumps(evidence, ensure_ascii=False).lower())

    def test_runtime_binding_blocks_transport_before_live_call(self):
        config = MaiAgentCategorySemanticProviderConfig(
            api_base="https://maiagent.invalid",
            api_key="test-only",
            chatbot_id="runtime-helper-instance",
        )
        calls = []

        def forbidden_transport(*args, **kwargs):
            calls.append((args, kwargs))
            raise AssertionError("transport must not run for a mismatched Helper instance")

        with self.assertRaises(ValueError):
            evaluation.run_evaluation(
                config=config,
                transport=forbidden_transport,
                deployment_provenance=_deployment_snapshot(),
            )
        self.assertEqual(calls, [])

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
