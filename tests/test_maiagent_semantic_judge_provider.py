from __future__ import annotations

import json
import unittest
from types import ModuleType
from unittest.mock import patch

from src.weekly_report.contracts import CanonicalCandidate, EvidenceState, FetchedSource, RejectReason
from src.weekly_report.evidence_service import EvidenceService
from src.weekly_report.maiagent_semantic_judge_provider import (
    EVIDENCE_SEMANTIC_JUDGE_HELPER_VERSION,
    EVIDENCE_SEMANTIC_JUDGE_PROMPT_VERSION,
    EVIDENCE_SEMANTIC_JUDGE_SCHEMA_VERSION,
    EVIDENCE_SEMANTIC_JUDGE_TASK_IDENTITY,
    MAIAGENT_SEMANTIC_JUDGE_RESPONSE_SCHEMA,
    SEMANTIC_JUDGE_INSTRUCTIONS,
    MaiAgentSemanticJudgeConfig,
    MaiAgentSemanticJudgeProvider,
    MaiAgentSemanticJudgeProviderFailure,
    build_maiagent_semantic_judge,
    build_maiagent_semantic_judge_model_input,
)
from src.weekly_report.maiagent_transport import MaiAgentHttpResponse
from src.weekly_report.semantic_judge import JudgeMetadata, PrincipalBodySegment, SemanticJudgeInput


def _request() -> SemanticJudgeInput:
    return SemanticJudgeInput(
        candidate_id="candidate-1",
        candidate_title="東京メトロ launches a maintenance platform",
        document_level_headlines=("東京メトロ launches a maintenance platform", "Related headline"),
        principal_body_segments=(
            PrincipalBodySegment("body-0001", "東京メトロ launched the platform in 2026."),
            PrincipalBodySegment("body-0002", "The operator will deploy it after trials."),
        ),
    )


def _envelope(raw: object) -> bytes:
    return json.dumps({"content": json.dumps(raw, ensure_ascii=False)}).encode("utf-8")


class _RecordedTransport:
    def __init__(self, response: MaiAgentHttpResponse | None = None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.calls: list[tuple[str, dict[str, str], bytes, float]] = []

    def __call__(self, endpoint, *, headers, body, timeout_seconds):
        self.calls.append((endpoint, dict(headers), body, timeout_seconds))
        if self.error is not None:
            raise self.error
        return self.response


def _config(**overrides) -> MaiAgentSemanticJudgeConfig:
    values = {
        "api_base": "https://maiagent.example/",
        "api_key": "synthetic-secret",
        "chatbot_id": "helper-id",
        "model_identifier": "GPT-OSS-120B",
    }
    values.update(overrides)
    return MaiAgentSemanticJudgeConfig(**values)


def _candidate() -> CanonicalCandidate:
    return CanonicalCandidate(
        candidate_id="candidate-1",
        title="東京メトロ launches a maintenance platform",
        url="https://source.test/article",
        publisher="Fixture Publisher",
        published_at="2026-09-15T10:00:00Z",
        discovery_intent="technology",
        search_snippet="Discovery-only snippet.",
    )


def _same_event_response(request: SemanticJudgeInput) -> dict[str, object]:
    return {
        "relation": "SAME_EVENT",
        "support_spans": [
            {
                "segment_id": request.principal_body_segments[0].segment_id,
                "start": 0,
                "end": len(request.principal_body_segments[0].text),
            }
        ],
        "conflict_spans": [],
        "explanation": "The supplied principal body establishes the event.",
    }


class MaiAgentSemanticJudgeProviderTests(unittest.TestCase):
    def test_shared_config_uses_canonical_helper_key_only_and_explicit_model(self):
        dotenv_values = {
            "MAIAGENT_API_BASE": "https://dotenv.example",
            "MAIAGENT_API_KEY": "dotenv-secret",
            "MAIAGENT_STRUCTURED_HELPER_CHATBOT_ID": "helper-from-dotenv",
            "CATEGORY_MAIAGENT_CHATBOT_ID": "old-category-id",
            "EVIDENCE_METADATA_MAIAGENT_CHATBOT_ID": "old-metadata-id",
            "MAIAGENT_CHATBOT_ID": "writer-id",
        }
        dotenv = ModuleType("dotenv")
        dotenv.dotenv_values = lambda _path: dotenv_values
        with patch.dict("sys.modules", {"dotenv": dotenv}):
            config = MaiAgentSemanticJudgeConfig.from_environment(
                {"MAIAGENT_API_KEY": "process-secret"},
                model_identifier="operator-model",
                dotenv_path="repo/.env",
            )
        self.assertIsNotNone(config)
        self.assertEqual(config.api_key, "process-secret")
        self.assertEqual(config.chatbot_id, "helper-from-dotenv")
        self.assertEqual(config.model_identifier, "operator-model")

        with patch.dict("sys.modules", {"dotenv": dotenv}):
            blocked = MaiAgentSemanticJudgeConfig.from_environment(
                {"MAIAGENT_STRUCTURED_HELPER_CHATBOT_ID": ""},
                model_identifier="operator-model",
                dotenv_path="repo/.env",
            )
        self.assertIsNone(blocked)

        old_only = {
            "MAIAGENT_API_BASE": "https://dotenv.example",
            "MAIAGENT_API_KEY": "dotenv-secret",
            "CATEGORY_MAIAGENT_CHATBOT_ID": "old-category-id",
            "EVIDENCE_METADATA_MAIAGENT_CHATBOT_ID": "old-metadata-id",
        }
        old_dotenv = ModuleType("dotenv")
        old_dotenv.dotenv_values = lambda _path: old_only
        with patch.dict("sys.modules", {"dotenv": old_dotenv}):
            self.assertIsNone(
                MaiAgentSemanticJudgeConfig.from_environment(
                    {}, model_identifier="operator-model", dotenv_path="repo/.env"
                )
            )

    def test_config_requires_explicit_model_and_never_uses_chatbot_id_as_model(self):
        self.assertIsNone(
            MaiAgentSemanticJudgeConfig.from_environment(
                {
                    "MAIAGENT_API_BASE": "https://maiagent.example",
                    "MAIAGENT_API_KEY": "key",
                    "MAIAGENT_STRUCTURED_HELPER_CHATBOT_ID": "GPT-OSS-120B",
                }
            )
        )
        provider = MaiAgentSemanticJudgeProvider(_config(chatbot_id="chatbot-123"))
        self.assertEqual(provider.metadata.model_identifier, "GPT-OSS-120B")
        self.assertNotEqual(provider.metadata.model_identifier, "chatbot-123")

    def test_config_validation_and_construction_are_network_free(self):
        for overrides in (
            {"api_base": "http://maiagent.example"},
            {"api_base": "https://maiagent.example/path"},
            {"api_key": ""},
            {"chatbot_id": ""},
            {"model_identifier": ""},
            {"api_key": "bad\nsecret"},
            {"chatbot_id": "bad\nid"},
            {"model_identifier": "bad\nid"},
            {"timeout_seconds": 0},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                _config(**overrides)
        calls = []
        transport = _RecordedTransport(error=AssertionError("network during construction"))
        provider = build_maiagent_semantic_judge(_config(), transport=transport)
        self.assertIsInstance(provider, MaiAgentSemanticJudgeProvider)
        self.assertEqual(calls, [])
        self.assertEqual(transport.calls, [])
        self.assertNotIn("synthetic-secret", repr(provider._config))
        self.assertNotIn("helper-id", repr(provider._config))

    def test_request_builder_contains_full_bounded_contract(self):
        request = _request()
        model_input = build_maiagent_semantic_judge_model_input(request)
        self.assertEqual(model_input["task_identity"], EVIDENCE_SEMANTIC_JUDGE_TASK_IDENTITY)
        self.assertEqual(model_input["prompt_version"], EVIDENCE_SEMANTIC_JUDGE_PROMPT_VERSION)
        self.assertEqual(model_input["schema_version"], EVIDENCE_SEMANTIC_JUDGE_SCHEMA_VERSION)
        self.assertEqual(model_input["helper_version"], EVIDENCE_SEMANTIC_JUDGE_HELPER_VERSION)
        self.assertEqual(tuple(model_input["instructions"]), SEMANTIC_JUDGE_INSTRUCTIONS)
        self.assertEqual(model_input["semantic_judge_request"], request.as_payload())
        self.assertEqual(
            model_input["authoritative_response_contract"]["json_schema"],
            MAIAGENT_SEMANTIC_JUDGE_RESPONSE_SCHEMA,
        )
        self.assertEqual(
            set(model_input["semantic_judge_request"]),
            {"candidate_id", "candidate_title", "document_level_headlines", "principal_body_segments"},
        )
        serialized = json.dumps(model_input["semantic_judge_request"], ensure_ascii=False)
        for forbidden in ("publisher", "search_snippet", "url", "category", "taxonomy", "reportability"):
            self.assertNotIn(forbidden, serialized.lower())
        self.assertIn("東京メトロ", serialized)

    def test_actual_request_is_stateless_and_single_call(self):
        request = _request()
        raw = _same_event_response(request)
        transport = _RecordedTransport(MaiAgentHttpResponse(200, _envelope(raw)))
        provider = MaiAgentSemanticJudgeProvider(_config(), transport=transport)
        result = provider(request)
        self.assertEqual(result, raw)
        self.assertEqual(len(transport.calls), 1)
        endpoint, headers, body, timeout = transport.calls[0]
        self.assertEqual(endpoint, "https://maiagent.example/api/v1/chatbots/helper-id/completions/")
        self.assertEqual(headers["Authorization"], "Api-Key synthetic-secret")
        self.assertEqual(timeout, 45.0)
        outer = json.loads(body)
        self.assertEqual(outer["message"]["role"], "user")
        self.assertIsNone(outer["conversation"])
        self.assertEqual(outer["attachments"], [])
        self.assertFalse(outer["is_streaming"])
        sent = json.loads(outer["message"]["content"])
        self.assertEqual(sent["task_identity"], EVIDENCE_SEMANTIC_JUDGE_TASK_IDENTITY)
        self.assertEqual(sent["prompt_version"], EVIDENCE_SEMANTIC_JUDGE_PROMPT_VERSION)
        self.assertEqual(sent["schema_version"], EVIDENCE_SEMANTIC_JUDGE_SCHEMA_VERSION)
        self.assertEqual(sent["helper_version"], EVIDENCE_SEMANTIC_JUDGE_HELPER_VERSION)
        self.assertEqual(sent["instructions"], list(SEMANTIC_JUDGE_INSTRUCTIONS))
        response_contract = sent["authoritative_response_contract"]
        self.assertEqual(response_contract["schema_version"], EVIDENCE_SEMANTIC_JUDGE_SCHEMA_VERSION)
        self.assertEqual(response_contract["json_schema"], MAIAGENT_SEMANTIC_JUDGE_RESPONSE_SCHEMA)

        sent_request = sent["semantic_judge_request"]
        self.assertEqual(
            set(sent_request),
            {"candidate_id", "candidate_title", "document_level_headlines", "principal_body_segments"},
        )
        self.assertEqual(sent_request, request.as_payload())
        self.assertEqual(sent_request["candidate_id"], request.candidate_id)
        self.assertEqual(sent_request["candidate_title"], request.candidate_title)
        self.assertEqual(
            sent_request["document_level_headlines"],
            list(request.document_level_headlines),
        )
        self.assertEqual(
            [item["segment_id"] for item in sent_request["principal_body_segments"]],
            [segment.segment_id for segment in request.principal_body_segments],
        )
        self.assertEqual(
            [item["text"] for item in sent_request["principal_body_segments"]],
            [segment.text for segment in request.principal_body_segments],
        )
        for forbidden_key in (
            "publisher",
            "url",
            "search_snippet",
            "region",
            "category",
            "taxonomy",
            "reportability",
        ):
            self.assertNotIn(forbidden_key, sent_request)

    def test_valid_relations_are_returned_raw_and_schema_is_not_repaired(self):
        for relation in ("SAME_EVENT", "DIFFERENT_EVENT", "UNCERTAIN"):
            with self.subTest(relation=relation):
                raw = {
                    "relation": relation,
                    "support_spans": [],
                    "conflict_spans": [],
                    "explanation": "raw proposal",
                }
                transport = _RecordedTransport(MaiAgentHttpResponse(200, _envelope(raw)))
                self.assertEqual(MaiAgentSemanticJudgeProvider(_config(), transport=transport)(_request()), raw)
        wrong = {"relation": "SAME_EVENT", "support_spans": [], "conflict_spans": []}
        transport = _RecordedTransport(MaiAgentHttpResponse(200, _envelope(wrong)))
        self.assertEqual(MaiAgentSemanticJudgeProvider(_config(), transport=transport)(_request()), wrong)

    def test_malformed_response_is_invalid_raw_value_without_repair(self):
        for body in (
            b"not-json",
            json.dumps({"answer": "{}"}).encode(),
            json.dumps({"content": "```json\n{}\n```"}).encode(),
            json.dumps({"content": "[]"}).encode(),
            json.dumps({"content": "not-json"}).encode(),
        ):
            with self.subTest(body=body):
                transport = _RecordedTransport(MaiAgentHttpResponse(200, body))
                self.assertIsNone(MaiAgentSemanticJudgeProvider(_config(), transport=transport)(_request()))
                self.assertEqual(len(transport.calls), 1)

    def test_timeout_non_200_and_generic_failure_are_safe_and_not_retried(self):
        for error in (TimeoutError("secret-timeout"), RuntimeError("secret-provider")):
            transport = _RecordedTransport(error=error)
            provider = MaiAgentSemanticJudgeProvider(_config(), transport=transport)
            expected = TimeoutError if isinstance(error, TimeoutError) else MaiAgentSemanticJudgeProviderFailure
            with self.subTest(expected=expected), self.assertRaises(expected) as raised:
                provider(_request())
            self.assertNotIn("secret", str(raised.exception))
            self.assertEqual(len(transport.calls), 1)
        transport = _RecordedTransport(MaiAgentHttpResponse(503, b"secret body"))
        with self.assertRaises(MaiAgentSemanticJudgeProviderFailure) as raised:
            MaiAgentSemanticJudgeProvider(_config(), transport=transport)(_request())
        self.assertNotIn("secret", str(raised.exception))
        self.assertEqual(len(transport.calls), 1)

    def test_existing_evidence_service_keeps_authority_for_all_paths(self):
        text = "東京メトロ launched the platform after trials."
        candidate = _candidate()
        source = FetchedSource(
            url=candidate.url,
            content=f"<html><body><h1>{candidate.title}</h1><article><p>{text}</p></article></body></html>",
            content_type="text/html",
        )
        for relation, expected_state, expected_diagnostic in (
            ("SAME_EVENT", EvidenceState.READY, "valid"),
            ("DIFFERENT_EVENT", EvidenceState.REJECTED, "valid"),
            ("UNCERTAIN", EvidenceState.REJECTED, "valid"),
        ):
            with self.subTest(relation=relation):
                request = _request()
                raw = {
                    "relation": relation,
                    "support_spans": ([{"segment_id": "body-0001", "start": 0, "end": len(text)}] if relation == "SAME_EVENT" else []),
                    "conflict_spans": ([{"segment_id": "body-0001", "start": 0, "end": 1}] if relation == "DIFFERENT_EVENT" else []),
                    "explanation": "bounded",
                }
                transport = _RecordedTransport(MaiAgentHttpResponse(200, _envelope(raw)))
                provider = MaiAgentSemanticJudgeProvider(_config(), transport=transport)
                extractor_calls = []
                service = EvidenceService(
                    lambda _url, source=source: source,
                    semantic_judge=provider,
                    judge_metadata=provider.metadata,
                    metadata_extractor=lambda _request: extractor_calls.append(True),
                )
                result = service.evaluate(candidate)
                self.assertEqual(result.state, expected_state)
                self.assertEqual(result.provenance["response_validation_result"], expected_diagnostic)
                self.assertEqual(len(transport.calls), 1)
                if expected_state is EvidenceState.REJECTED:
                    self.assertEqual(extractor_calls, [])

    def test_invalid_body_span_reaches_existing_validator_and_rejects_without_retry(self):
        candidate = _candidate()
        text = "東京メトロ launched the platform after trials."
        source = FetchedSource(
            url=candidate.url,
            content=f"<html><body><h1>{candidate.title}</h1><article><p>{text}</p></article></body></html>",
            content_type="text/html",
        )
        raw = {
            "relation": "SAME_EVENT",
            "support_spans": [
                {"segment_id": "body-0001", "start": 0, "end": len(text) + 1}
            ],
            "conflict_spans": [],
            "explanation": "syntactically valid but out-of-range support",
        }
        transport = _RecordedTransport(MaiAgentHttpResponse(200, _envelope(raw)))
        provider = MaiAgentSemanticJudgeProvider(_config(), transport=transport)
        extractor_calls = []
        result = EvidenceService(
            lambda _url, source=source: source,
            semantic_judge=provider,
            judge_metadata=provider.metadata,
            metadata_extractor=lambda _request: extractor_calls.append(True),
        ).evaluate(candidate)

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.SOURCE_PAGE_MISMATCH)
        self.assertEqual(result.provenance["response_validation_result"], "invalid")
        self.assertEqual(extractor_calls, [])
        self.assertEqual(len(transport.calls), 1)

    def test_evidence_service_maps_timeout_transport_and_invalid_paths(self):
        candidate = _candidate()
        text = "東京メトロ launched the platform after trials."
        source = FetchedSource(
            url=candidate.url,
            content=f"<html><body><h1>{candidate.title}</h1><article><p>{text}</p></article></body></html>",
            content_type="text/html",
        )
        for body, error, expected in (
            (None, TimeoutError("secret"), "timeout"),
            (None, RuntimeError("secret"), "transport_error"),
            (b"not-json", None, "invalid"),
        ):
            with self.subTest(expected=expected):
                transport = _RecordedTransport(
                    None if error else MaiAgentHttpResponse(200, body), error=error
                )
                provider = MaiAgentSemanticJudgeProvider(_config(), transport=transport)
                result = EvidenceService(
                    lambda _url, source=source: source,
                    semantic_judge=provider,
                    judge_metadata=provider.metadata,
                ).evaluate(candidate)
                self.assertEqual(result.state, EvidenceState.REJECTED)
                self.assertEqual(result.reject_reason, RejectReason.SOURCE_PAGE_MISMATCH)
                self.assertEqual(result.provenance["response_validation_result"], expected)
                self.assertEqual(len(transport.calls), 1)


if __name__ == "__main__":
    unittest.main()
