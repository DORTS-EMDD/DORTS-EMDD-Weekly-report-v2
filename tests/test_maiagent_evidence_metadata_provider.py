from __future__ import annotations

import json
import socket
import unittest
from types import ModuleType
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from src.weekly_report.contracts import CanonicalCandidate, FetchedSource, EvidenceState
from src.weekly_report.evidence_metadata import EvidenceMetadataRequest
from src.weekly_report.evidence_service import EvidenceService
from src.weekly_report.maiagent_evidence_metadata_provider import (
    EVIDENCE_METADATA_HELPER_VERSION,
    EVIDENCE_METADATA_INSTRUCTIONS,
    EVIDENCE_METADATA_PROMPT_VERSION,
    EVIDENCE_METADATA_SCHEMA_VERSION,
    MAIAGENT_EVIDENCE_METADATA_RESPONSE_SCHEMA,
    MaiAgentEvidenceMetadataExtractor,
    MaiAgentEvidenceMetadataProviderConfig,
    build_maiagent_evidence_metadata_model_input,
)
from src.weekly_report.maiagent_transport import (
    MaiAgentHttpResponse,
    UrllibMaiAgentJsonTransport,
    load_shared_maiagent_values,
)
import src.weekly_report.maiagent_transport as maiagent_transport_module
from src.weekly_report.semantic_judge import PrincipalBodySegment


def _request() -> EvidenceMetadataRequest:
    return EvidenceMetadataRequest(
        "candidate-1",
        (
            PrincipalBodySegment("body-0001", "臺灣 Metro opened at Taipei."),
            PrincipalBodySegment("body-0002", "Unicode stays exact: 東京."),
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


def _config() -> MaiAgentEvidenceMetadataProviderConfig:
    return MaiAgentEvidenceMetadataProviderConfig(
        "https://maiagent.example/",
        "synthetic-secret",
        "helper-id",
    )


class MaiAgentEvidenceMetadataProviderTests(unittest.TestCase):
    def test_shared_configuration_uses_one_helper_key_and_no_fallback(self):
        values = {
            "MAIAGENT_API_BASE": "https://dotenv.example",
            "MAIAGENT_API_KEY": "dotenv-secret",
            "MAIAGENT_STRUCTURED_HELPER_CHATBOT_ID": "helper-from-dotenv",
            "CATEGORY_MAIAGENT_CHATBOT_ID": "old-category-id",
            "EVIDENCE_METADATA_MAIAGENT_CHATBOT_ID": "old-metadata-id",
            "MAIAGENT_CHATBOT_ID": "writer-id",
        }
        dotenv = ModuleType("dotenv")
        dotenv.dotenv_values = lambda path: values
        with patch.dict("sys.modules", {"dotenv": dotenv}):
            config = MaiAgentEvidenceMetadataProviderConfig.from_environment(
                {"MAIAGENT_API_KEY": "process-secret"}, dotenv_path="repo/.env"
            )
        self.assertIsNotNone(config)
        self.assertEqual(config.chatbot_id, "helper-from-dotenv")
        self.assertEqual(config.api_key, "process-secret")
        self.assertNotIn("CATEGORY_MAIAGENT_CHATBOT_ID", config.__dict__ if hasattr(config, "__dict__") else {})

        with patch.dict("sys.modules", {"dotenv": dotenv}):
            blocked = MaiAgentEvidenceMetadataProviderConfig.from_environment(
                {"MAIAGENT_STRUCTURED_HELPER_CHATBOT_ID": ""}, dotenv_path="repo/.env"
            )
        self.assertIsNone(blocked)

        old_only = {
            "MAIAGENT_API_BASE": "https://dotenv.example",
            "MAIAGENT_API_KEY": "dotenv-secret",
            "CATEGORY_MAIAGENT_CHATBOT_ID": "old-category-id",
            "EVIDENCE_METADATA_MAIAGENT_CHATBOT_ID": "old-metadata-id",
        }
        old_dotenv = ModuleType("dotenv")
        old_dotenv.dotenv_values = lambda path: old_only
        with patch.dict("sys.modules", {"dotenv": old_dotenv}):
            self.assertIsNone(
                MaiAgentEvidenceMetadataProviderConfig.from_environment({}, dotenv_path="repo/.env")
            )

    def test_shared_loader_reads_only_canonical_names_and_preserves_process_precedence(self):
        dotenv = ModuleType("dotenv")
        dotenv.dotenv_values = lambda path: {
            "MAIAGENT_API_BASE": "https://dotenv.example",
            "MAIAGENT_API_KEY": "dotenv-secret",
            "MAIAGENT_STRUCTURED_HELPER_CHATBOT_ID": "dotenv-helper",
            "MAIAGENT_CHATBOT_ID": "writer-id",
        }
        with patch.dict("sys.modules", {"dotenv": dotenv}):
            values = load_shared_maiagent_values(
                {"MAIAGENT_API_BASE": "https://process.example"}, dotenv_path="repo/.env"
            )
        self.assertEqual(values["MAIAGENT_API_BASE"], "https://process.example")
        self.assertEqual(values["MAIAGENT_STRUCTURED_HELPER_CHATBOT_ID"], "dotenv-helper")
        self.assertNotIn("MAIAGENT_CHATBOT_ID", values)

    def test_request_contract_and_single_call_preserve_unicode_and_boundaries(self):
        request = _request()
        model_input = build_maiagent_evidence_metadata_model_input(request)
        self.assertEqual(model_input["evidence_metadata_request"]["candidate_id"], "candidate-1")
        self.assertEqual(
            model_input["evidence_metadata_request"]["principal_body_segments"][1]["text"],
            "Unicode stays exact: 東京.",
        )
        self.assertEqual(model_input["prompt_version"], EVIDENCE_METADATA_PROMPT_VERSION)
        self.assertEqual(model_input["schema_version"], EVIDENCE_METADATA_SCHEMA_VERSION)
        self.assertEqual(model_input["helper_version"], EVIDENCE_METADATA_HELPER_VERSION)
        self.assertEqual(tuple(model_input["instructions"]), EVIDENCE_METADATA_INSTRUCTIONS)
        self.assertEqual(
            set(model_input["evidence_metadata_request"]),
            {"candidate_id", "principal_body_segments"},
        )
        self.assertNotIn("title", json.dumps(model_input))
        self.assertNotIn("publisher", json.dumps(model_input))

        raw = {"observations": []}
        transport = _RecordedTransport(MaiAgentHttpResponse(200, _envelope(raw)))
        result = MaiAgentEvidenceMetadataExtractor(_config(), transport=transport)(request)
        self.assertEqual(result, raw)
        self.assertEqual(len(transport.calls), 1)
        endpoint, headers, body, timeout = transport.calls[0]
        self.assertEqual(endpoint, "https://maiagent.example/api/v1/chatbots/helper-id/completions/")
        self.assertEqual(headers["Authorization"], "Api-Key synthetic-secret")
        outer = json.loads(body)
        self.assertIsNone(outer["conversation"])
        self.assertEqual(outer["attachments"], [])
        self.assertFalse(outer["is_streaming"])
        self.assertEqual(outer["message"]["role"], "user")
        self.assertEqual(timeout, 45.0)

        sent_content = outer["message"]["content"]
        sent_input = json.loads(sent_content)
        self.assertEqual(sent_input["task_identity"], "evidence_metadata_extraction")
        self.assertEqual(sent_input["prompt_version"], EVIDENCE_METADATA_PROMPT_VERSION)
        self.assertEqual(sent_input["schema_version"], EVIDENCE_METADATA_SCHEMA_VERSION)
        self.assertEqual(sent_input["helper_version"], EVIDENCE_METADATA_HELPER_VERSION)
        self.assertEqual(sent_input["instructions"], list(EVIDENCE_METADATA_INSTRUCTIONS))
        self.assertEqual(
            sent_input["authoritative_response_contract"]["schema_version"],
            EVIDENCE_METADATA_SCHEMA_VERSION,
        )
        self.assertEqual(
            sent_input["authoritative_response_contract"]["json_schema"],
            MAIAGENT_EVIDENCE_METADATA_RESPONSE_SCHEMA,
        )
        sent_request = sent_input["evidence_metadata_request"]
        self.assertEqual(set(sent_request), {"candidate_id", "principal_body_segments"})
        expected_segments = [
            {"segment_id": segment.segment_id, "text": segment.text}
            for segment in request.principal_body_segments
        ]
        self.assertEqual(sent_request["candidate_id"], request.candidate_id)
        self.assertEqual(sent_request["principal_body_segments"], expected_segments)
        for forbidden in (
            "title",
            "publisher",
            "url",
            "search_snippet",
            "category",
            "taxonomy",
            "reportability",
        ):
            self.assertNotIn(forbidden, sent_content.lower())

    def test_response_parser_rejects_malformed_or_non_object_content_without_repair(self):
        request = _request()
        for body in (
            b"not-json",
            json.dumps({"answer": "{}"}).encode(),
            json.dumps({"content": "```json\n{}\n```"}).encode(),
            json.dumps({"content": "[]"}).encode(),
            json.dumps({"content": "not-json"}).encode(),
        ):
            with self.subTest(body=body):
                transport = _RecordedTransport(MaiAgentHttpResponse(200, body))
                result = MaiAgentEvidenceMetadataExtractor(_config(), transport=transport)(request)
                self.assertIsNone(result)
                self.assertEqual(len(transport.calls), 1)

    def test_raw_json_schema_is_not_validated_or_repaired_by_adapter(self):
        raw = {"observations": [{"wrong": "domain-shape"}]}
        transport = _RecordedTransport(MaiAgentHttpResponse(200, _envelope(raw)))
        result = MaiAgentEvidenceMetadataExtractor(_config(), transport=transport)(_request())
        self.assertEqual(result, raw)
        self.assertEqual(MAIAGENT_EVIDENCE_METADATA_RESPONSE_SCHEMA["required"], ["observations"])

    def test_timeout_status_error_and_http_failure_have_no_retry(self):
        request = _request()
        for error, expected in ((TimeoutError(), TimeoutError), (RuntimeError("secret"), RuntimeError)):
            transport = _RecordedTransport(error=error)
            with self.subTest(expected=expected), self.assertRaises(expected):
                MaiAgentEvidenceMetadataExtractor(_config(), transport=transport)(request)
            self.assertEqual(len(transport.calls), 1)

        transport = _RecordedTransport(MaiAgentHttpResponse(503, b"secret body"))
        with self.assertRaises(RuntimeError):
            MaiAgentEvidenceMetadataExtractor(_config(), transport=transport)(request)
        self.assertEqual(len(transport.calls), 1)

    def test_transport_preserves_timeout_and_sanitizes_failures(self):
        class _Opener:
            def __init__(self, error):
                self.error = error
                self.calls = 0

            def open(self, request, timeout):
                self.calls += 1
                raise self.error

        for error, expected in (
            (TimeoutError("secret"), TimeoutError),
            (URLError(socket.timeout("secret")), TimeoutError),
            (URLError("secret-url"), RuntimeError),
            (OSError("secret-os"), RuntimeError),
        ):
            opener = _Opener(error)
            with patch("src.weekly_report.maiagent_transport.build_opener", return_value=opener):
                with self.subTest(expected=expected), self.assertRaises(expected) as raised:
                    UrllibMaiAgentJsonTransport()("https://maiagent.example", headers={}, body=b"{}", timeout_seconds=1)
            self.assertEqual(opener.calls, 1)
            self.assertNotIn("secret", str(raised.exception))

        opener = _Opener(HTTPError("https://maiagent.example", 429, "denied", {}, None))
        with patch("src.weekly_report.maiagent_transport.build_opener", return_value=opener):
            response = UrllibMaiAgentJsonTransport()("https://maiagent.example", headers={}, body=b"{}", timeout_seconds=1)
        self.assertEqual(response, MaiAgentHttpResponse(429, b""))

    def test_transport_uses_one_post_without_redirect_handler(self):
        class _Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b"{}"

        class _Opener:
            def __init__(self):
                self.request = None
                self.timeout = None

            def open(self, request, timeout):
                self.request = request
                self.timeout = timeout
                return _Response()

        opener = _Opener()
        captured_handlers = []
        with patch(
            "src.weekly_report.maiagent_transport.build_opener",
            side_effect=lambda *handlers: (captured_handlers.extend(handlers) or opener),
        ):
            response = UrllibMaiAgentJsonTransport()("https://maiagent.example", headers={"X": "Y"}, body=b"{}", timeout_seconds=3)
        self.assertEqual(response, MaiAgentHttpResponse(200, b"{}"))
        self.assertEqual(opener.request.get_method(), "POST")
        self.assertEqual(opener.request.data, b"{}")
        self.assertEqual(opener.timeout, 3)
        self.assertEqual(len(captured_handlers), 1)
        self.assertEqual(captured_handlers[0].__name__, "_NoRedirect")

    def test_redirect_behavior_returns_no_follow_up_request(self):
        handler = maiagent_transport_module._NoRedirect()
        original = maiagent_transport_module.Request(
            "https://maiagent.example/completions",
            data=b"{}",
            method="POST",
        )
        redirected = handler.redirect_request(
            original,
            None,
            307,
            "temporary redirect",
            {},
            "https://redirect.example/completions",
        )
        self.assertIsNone(redirected)

        requests = [original]
        if redirected is not None:
            requests.append(redirected)
        self.assertEqual(len(requests), 1)

    def test_existing_evidence_service_accepts_adapter_proposal_and_keeps_ready(self):
        text = "Taiwan Metro opened at Taipei Central."
        raw = {
            "observations": [
                {"field_name": "country", "value": "Taiwan", "support_spans": [{"segment_id": "body-0001", "start": 0, "end": 6}]},
                {"field_name": "transit_system_name", "value": "Metro", "support_spans": [{"segment_id": "body-0001", "start": 7, "end": 12}]},
            ]
        }
        transport = _RecordedTransport(MaiAgentHttpResponse(200, _envelope(raw)))

        def judge(request):
            return {
                "relation": "SAME_EVENT",
                "support_spans": [{"segment_id": segment.segment_id, "start": 0, "end": len(segment.text)} for segment in request.principal_body_segments],
                "conflict_spans": [],
                "explanation": "grounded",
            }

        service = EvidenceService(
            lambda _url: FetchedSource("https://source.test/article", "<html><body><article><p>" + text + "</p></article></body></html>"),
            semantic_judge=judge,
            metadata_extractor=MaiAgentEvidenceMetadataExtractor(_config(), transport=transport),
        )
        result = service.evaluate(CanonicalCandidate("candidate-1", "Discovery title", "https://source.test/article"))
        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(result.provenance["metadata_extraction_status"], "valid_metadata")
        self.assertEqual(result.identity_facts.country, "Taiwan")
        self.assertEqual(result.identity_facts.transit_system_name, "Metro")
        self.assertEqual(len(transport.calls), 1)

    def test_existing_evidence_service_maps_adapter_failures_without_retry_or_salvage(self):
        text = "Taiwan Metro opened at Taipei Central."

        def judge(request):
            return {
                "relation": "SAME_EVENT",
                "support_spans": [{"segment_id": segment.segment_id, "start": 0, "end": len(segment.text)} for segment in request.principal_body_segments],
                "conflict_spans": [],
                "explanation": "grounded",
            }

        for raw, error, expected_status in (
            ({"observations": []}, None, "valid_zero_metadata"),
            ({"observations": [{"bad": 1}]}, None, "invalid_response"),
            ({"observations": [{"field_name": "country", "value": "Taiwan", "support_spans": [{"segment_id": "body-0001", "start": 0, "end": 99}]}]}, None, "invalid_response"),
            (None, TimeoutError(), "timeout"),
            (None, RuntimeError("secret-provider-error"), "transport_error"),
        ):
            with self.subTest(expected_status=expected_status):
                response = _envelope(raw) if raw is not None else b""
                transport = _RecordedTransport(
                    MaiAgentHttpResponse(200, response) if error is None else None,
                    error=error,
                )
                service = EvidenceService(
                    lambda _url: FetchedSource("https://source.test/article", "<html><body><article><p>" + text + "</p></article></body></html>"),
                    semantic_judge=judge,
                    metadata_extractor=MaiAgentEvidenceMetadataExtractor(_config(), transport=transport),
                )
                result = service.evaluate(CanonicalCandidate("candidate-1", "Title", "https://source.test/article"))
                self.assertEqual(result.state, EvidenceState.READY)
                self.assertEqual(result.provenance["metadata_extraction_status"], expected_status)
                self.assertEqual(len(transport.calls), 1)
                self.assertIsNone(result.identity_facts)


if __name__ == "__main__":
    unittest.main()
