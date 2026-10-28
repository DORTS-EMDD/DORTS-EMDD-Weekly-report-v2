from __future__ import annotations

import json
import math
import unittest

from src.weekly_report.contracts import SemanticProviderTechnicalFailure
from src.weekly_report.maiagent_transport import MaiAgentHttpResponse
from src.weekly_report.maiagent_validation_provider import (
    HELPER_VERSION,
    MAIAGENT_VALIDATION_RESPONSE_SCHEMA,
    PROMPT_VERSION,
    SCHEMA_VERSION,
    TASK_IDENTITY,
    VALIDATION_INSTRUCTIONS,
    MaiAgentValidationProposalProvider,
    MaiAgentValidationProviderConfig,
    MaiAgentValidationProviderFailure,
    build_maiagent_validation_model_input,
)
from src.weekly_report.validator import (
    ValidationEvidenceSource,
    ValidationSemanticRequest,
    ValidationWriterProse,
)


def _request() -> ValidationSemanticRequest:
    return ValidationSemanticRequest(
        "E1",
        (ValidationEvidenceSource("C1", "Metro Taipei completed signalling testing."),),
        ValidationWriterProse("Metro", "Taipei Metro signalling testing", "Taipei"),
    )


def _envelope(value: object) -> bytes:
    return json.dumps(
        {"content": json.dumps(value, ensure_ascii=False)}, ensure_ascii=False
    ).encode("utf-8")


class _Transport:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def __call__(self, endpoint, *, headers, body, timeout_seconds):
        self.calls.append((endpoint, dict(headers), body, timeout_seconds))
        if self.error is not None:
            raise self.error
        return self.response


def _config(**kwargs):
    values = {
        "api_base": "https://maiagent.example",
        "api_key": "test-key",
        "chatbot_id": "helper",
        "timeout_seconds": 45.0,
    }
    values.update(kwargs)
    return MaiAgentValidationProviderConfig(**values)


class MaiAgentValidationProviderTests(unittest.TestCase):
    def test_model_input_has_exact_task_and_request_boundary(self):
        request = _request()
        model_input = build_maiagent_validation_model_input(request)
        self.assertEqual(model_input["task_identity"], TASK_IDENTITY)
        self.assertEqual(model_input["prompt_version"], PROMPT_VERSION)
        self.assertEqual(model_input["schema_version"], SCHEMA_VERSION)
        self.assertEqual(model_input["helper_version"], HELPER_VERSION)
        self.assertEqual(tuple(model_input["instructions"]), VALIDATION_INSTRUCTIONS)
        self.assertEqual(model_input["validation_request"], request.as_payload())
        self.assertEqual(set(model_input["validation_request"]), {"event_id", "evidence_sources", "writer_fields"})
        units = [
            unit for field in model_input["validation_request"]["writer_fields"] for unit in field["units"]
        ]
        self.assertEqual(
            [unit["unit_id"] for unit in units], ["headline-1", "factual_summary-1", "taipei_insight-1"]
        )
        self.assertNotIn("MAIAGENT_CHATBOT_ID", json.dumps(model_input))

    def test_response_schema_has_no_extra_fields_or_offsets(self):
        self.assertEqual(set(MAIAGENT_VALIDATION_RESPONSE_SCHEMA["properties"]), {"event_id", "field_assessments"})
        field = MAIAGENT_VALIDATION_RESPONSE_SCHEMA["properties"]["field_assessments"]["items"]
        self.assertEqual(set(field["properties"]), {"field_name", "language_assessment", "unit_assessments"})
        unit = field["properties"]["unit_assessments"]["items"]
        # RC-7: the helper references Validator unit IDs and never re-types Writer text.
        self.assertEqual(set(unit["properties"]), {"unit_id", "assessment", "evidence_citations"})
        self.assertNotIn("writer_quote", json.dumps(MAIAGENT_VALIDATION_RESPONSE_SCHEMA))
        # RC-9: Evidence citations name Python sentence IDs, never copied text.
        citation = unit["properties"]["evidence_citations"]["items"]
        self.assertEqual(set(citation["properties"]), {"source_ref", "sentence_ids"})
        self.assertNotIn("exact_quote", json.dumps(MAIAGENT_VALIDATION_RESPONSE_SCHEMA))
        self.assertEqual((PROMPT_VERSION, SCHEMA_VERSION), (
            "validation-evidence-writer-v5", "validation-semantic-check-proposal-v4"
        ))
        source = build_maiagent_validation_model_input(_request())["validation_request"]["evidence_sources"][0]
        self.assertEqual(source["sentences"], [{"sentence_id": "S1", "text": "Metro Taipei completed signalling testing."}])
        self.assertNotIn("offset", json.dumps(MAIAGENT_VALIDATION_RESPONSE_SCHEMA))
        self.assertEqual(source["source_ref"], "M1")
        instructions = " ".join(build_maiagent_validation_model_input(_request())["instructions"])
        self.assertIn("Every SUPPORTED or ANALYSIS unit must cite at least one Evidence sentence", instructions)
        # RC-27: a pure recommendation is ANALYSIS citing the event, not UNSUPPORTED.
        self.assertIn("only recommends, suggests or draws a professional implication", instructions)
        self.assertNotIn("A unit whose premise you cannot cite is UNSUPPORTED", instructions)

    def test_provider_makes_one_stateless_call_with_shared_helper(self):
        request = _request()
        response = {"event_id": "E1", "field_assessments": []}
        transport = _Transport(MaiAgentHttpResponse(200, _envelope(response)))
        provider = MaiAgentValidationProposalProvider(_config(), transport=transport)
        self.assertEqual(provider(request), response)
        self.assertEqual(provider.call_count, 1)
        endpoint, headers, body, timeout = transport.calls[0]
        self.assertEqual(endpoint, "https://maiagent.example/api/v1/chatbots/helper/completions/")
        self.assertEqual(timeout, 45.0)
        self.assertTrue(headers["Authorization"].startswith("Api-Key "))
        envelope = json.loads(body)
        self.assertIsNone(envelope["conversation"])
        self.assertEqual(envelope["attachments"], [])
        self.assertFalse(envelope["is_streaming"])

    def test_transport_failure_is_safe_and_retried_once(self):
        # RC-6: a timeout gets exactly one identical retry, then a typed
        # technical failure that is never a semantic FAIL.
        transport = _Transport(error=TimeoutError())
        provider = MaiAgentValidationProposalProvider(_config(), transport=transport)
        with self.assertRaises(SemanticProviderTechnicalFailure) as context:
            provider(_request())
        self.assertNotIn("test-key", str(context.exception))
        self.assertEqual(context.exception.failure_class, "TIMEOUT")
        self.assertEqual(len(transport.calls), 2)

    def test_config_rejects_invalid_values_and_redacts_credentials(self):
        self.assertNotIn("test-key", repr(_config()))
        for kwargs in (
            {"api_key": ""},
            {"chatbot_id": ""},
            {"timeout_seconds": 0},
            {"timeout_seconds": math.inf},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                values = {"api_key": "test-key", "chatbot_id": "helper", "timeout_seconds": 45.0}
                values.update(kwargs)
                MaiAgentValidationProviderConfig("https://maiagent.example", **values)


if __name__ == "__main__":
    unittest.main()
