"""Contract tests for the advisory MaiAgent Category provider."""

from __future__ import annotations

import json
from types import ModuleType
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator

import src.weekly_report.category_semantic_provider as provider_module
from src.weekly_report.category_semantic_provider import (
    CATEGORY_SEMANTIC_PROMPT_VERSION,
    CATEGORY_SEMANTIC_SCHEMA_VERSION,
    MAIAGENT_CATEGORY_MESSAGE_VERSION,
    MAIAGENT_CATEGORY_PROVIDER_IDENTIFIER,
    MAIAGENT_CATEGORY_SEMANTIC_HELPER_VERSION,
    MaiAgentCategorySemanticProvider,
    MaiAgentCategorySemanticProviderConfig,
    MaiAgentHttpResponse,
    _CATEGORY_RESPONSE_SCHEMA,
    _MAIAGENT_CATEGORY_RESPONSE_SCHEMA,
    build_maiagent_category_classifier,
    build_maiagent_category_model_input,
    build_maiagent_category_schema,
)
from src.weekly_report.classifier import CategorySemanticRequest, CategorySourceEvidence
from src.weekly_report.contracts import (
    CanonicalCandidate,
    CategoryId,
    CategoryResolutionReason,
    CategoryState,
    EvidenceResult,
    EvidenceState,
    EventGroup,
    EventIdentityRecord,
    ScopeResult,
    ScopeState,
    TemporalResult,
    SemanticProviderTechnicalFailure,
)


class _RecordedTransport:
    def __init__(self, response=None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.calls: list[tuple[str, dict[str, str], bytes, float]] = []

    def __call__(self, endpoint, *, headers, body, timeout_seconds):
        self.calls.append((endpoint, dict(headers), body, timeout_seconds))
        if self.error:
            raise self.error
        return self.response


def _request(body: str = "The operator completed deployment of a radio system.") -> CategorySemanticRequest:
    return CategorySemanticRequest((CategorySourceEvidence("source-1", body, {}),))


def _action(
    kind: str = "DEPLOYMENT",
    *,
    subject: str = "TECHNOLOGY_METHOD_MATERIAL",
    lifecycle: str = "TECHNOLOGY_ITSELF",
    adoption: str = "COMPLETED",
) -> dict[str, object]:
    return {
        "action_id": "A1",
        "action_kind": kind,
        "subject_kind": subject,
        "lifecycle_relation": lifecycle,
        "adoption_status": adoption,
        "citations": [{"source_ref": "M1", "sentence_ids": ["S1"]}],
    }


def _proposal(action: dict[str, object] | None = None, *, subtype: str | None = "pilot") -> dict[str, object]:
    return {
        "actions": [action or _action()],
        "principal_action_id": "A1",
        "subtype": subtype,
        "examined_citations": [{"source_ref": "M1", "sentence_ids": ["S1"]}],
        "relationships": [],
    }


def _response_body(proposal: dict[str, object]) -> bytes:
    return json.dumps({"content": json.dumps(proposal)}).encode("utf-8")


def _config() -> MaiAgentCategorySemanticProviderConfig:
    return MaiAgentCategorySemanticProviderConfig(
        api_base="https://api.maiagent.ai/",
        api_key="synthetic-test-api-key",
        chatbot_id="synthetic-category-chatbot-id",
    )


def _record(body: str = "The operator completed deployment of a radio system.") -> EventIdentityRecord:
    candidate = CanonicalCandidate(
        candidate_id="source-1",
        title="PRIVATE_TITLE",
        url="https://private.invalid/source",
        publisher="PRIVATE_PUBLISHER",
        published_at="PRIVATE_DATE",
        discovery_intent="PRIVATE_INTENT",
        search_snippet="PRIVATE_SNIPPET",
    )
    return EventIdentityRecord(
        candidate,
        EvidenceResult(
            candidate_id="source-1",
            state=EvidenceState.READY,
            canonical_source_url="https://private.invalid/source",
            substantive_content=body,
        ),
        ScopeResult(candidate_id="source-1", state=ScopeState.IN_SCOPE),
        TemporalResult(candidate_id="source-1", date_valid=True),
    )


def _group(record: EventIdentityRecord) -> EventGroup:
    return EventGroup(
        event_id="private-event-id",
        member_candidate_ids=(record.candidate.candidate_id,),
        canonical_candidate_id=record.candidate.candidate_id,
        identity_basis=(),
    )


class CategorySemanticProviderTests(unittest.TestCase):
    def test_versioned_schema_contains_only_advisory_action_contract(self):
        self.assertEqual(CATEGORY_SEMANTIC_PROMPT_VERSION, "category-principal-action-relationship-v8")
        self.assertEqual(CATEGORY_SEMANTIC_SCHEMA_VERSION, "category-action-lifecycle-relationship-proposal-v1")
        self.assertEqual(MAIAGENT_CATEGORY_MESSAGE_VERSION, "category-action-lifecycle-relationship-response-contract-v1")
        Draft202012Validator.check_schema(_CATEGORY_RESPONSE_SCHEMA)
        fields = {"actions", "principal_action_id", "subtype", "examined_citations", "relationships"}
        self.assertEqual(set(_CATEGORY_RESPONSE_SCHEMA["properties"]), fields)
        self.assertEqual(set(_CATEGORY_RESPONSE_SCHEMA["required"]), fields)
        self.assertFalse(_CATEGORY_RESPONSE_SCHEMA["additionalProperties"])
        self.assertNotIn("category_state", _CATEGORY_RESPONSE_SCHEMA["properties"])
        self.assertNotIn("primary_category_id", _CATEGORY_RESPONSE_SCHEMA["properties"])
        self.assertTrue(Draft202012Validator(_CATEGORY_RESPONSE_SCHEMA).is_valid(_proposal()))

    def test_schema_projection_is_derived_and_drops_unsupported_keywords(self):
        projected = build_maiagent_category_schema(_CATEGORY_RESPONSE_SCHEMA)
        self.assertEqual(projected, _MAIAGENT_CATEGORY_RESPONSE_SCHEMA)

        def walk(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    self.assertNotIn(key, {"oneOf", "allOf", "minItems", "minLength", "pattern"})
                    yield from walk(child)
            elif isinstance(value, list):
                for child in value:
                    yield from walk(child)

        list(walk(projected))
        action_fields = set(projected["properties"]["actions"]["items"]["properties"])
        self.assertEqual(
            action_fields,
            {"action_id", "action_kind", "subject_kind", "lifecycle_relation", "adoption_status", "citations"},
        )
        relationship_fields = set(projected["properties"]["relationships"]["items"]["properties"])
        self.assertEqual(
            relationship_fields,
            {
                "relationship_type",
                "member_action_ids",
                "principal_action_id",
                "dependent_action_id",
                "dependence_kind",
                "citations",
            },
        )

    def test_model_input_is_request_bound_and_versioned(self):
        request = _request()
        model_input = build_maiagent_category_model_input(request)
        self.assertEqual(model_input["category_request"], request.as_payload())
        self.assertEqual(
            model_input["authoritative_response_contract"],
            {"schema_version": CATEGORY_SEMANTIC_SCHEMA_VERSION, "json_schema": _CATEGORY_RESPONSE_SCHEMA},
        )

    def test_provider_uses_confirmed_envelope_and_classifier_maps_action(self):
        record = _record("The agency awarded a contract to Example Rail Ltd.")
        proposal = _proposal(
            _action(
                "PROCUREMENT_AWARD",
                subject="PROCUREMENT_ACTION",
                lifecycle="PROCUREMENT_LIFECYCLE",
                adoption="COMPLETED",
            ),
            subtype=None,
        )
        transport = _RecordedTransport(MaiAgentHttpResponse(200, _response_body(proposal)))
        result = build_maiagent_category_classifier(_config(), transport=transport).classify(
            _group(record), (record,)
        )
        self.assertEqual(result.category_state, CategoryState.CATEGORY_ASSIGNED)
        self.assertEqual(result.primary_category_id, CategoryId.PROCUREMENT)
        self.assertEqual(result.provenance["decision_basis"], "classifier_authoritative_domain_mechanism")
        self.assertEqual(result.provenance["provider_identifier"], MAIAGENT_CATEGORY_PROVIDER_IDENTIFIER)
        self.assertEqual(result.provenance["schema_version"], CATEGORY_SEMANTIC_SCHEMA_VERSION)
        self.assertEqual(result.provenance["prompt_version"], CATEGORY_SEMANTIC_PROMPT_VERSION)
        self.assertEqual(result.provenance["helper_version"], MAIAGENT_CATEGORY_SEMANTIC_HELPER_VERSION)
        self.assertEqual(len(result.provenance["validated_action_spans"]["A1"]), 1)
        self.assertEqual(len(transport.calls), 1)
        body = json.loads(transport.calls[0][2])
        self.assertEqual(body["message"]["role"], "user")
        self.assertIsNone(body["conversation"])
        self.assertEqual(body["attachments"], [])
        self.assertFalse(body["is_streaming"])
        model_input = json.loads(body["message"]["content"])
        self.assertEqual(model_input, build_maiagent_category_model_input(_request(record.evidence.substantive_content)))

    def test_invalid_envelope_is_technical_failure_with_bounded_retry(self):
        transport = _RecordedTransport(MaiAgentHttpResponse(200, json.dumps({"answer": "no"}).encode()))
        with self.assertRaises(SemanticProviderTechnicalFailure) as raised:
            MaiAgentCategorySemanticProvider(_config(), transport=transport)(_request())
        self.assertEqual(raised.exception.failure_class, "UNPARSEABLE_RESPONSE")
        self.assertEqual(len(transport.calls), 2)

    def test_provider_never_uses_alternate_envelope_or_backfills(self):
        transport = _RecordedTransport(MaiAgentHttpResponse(200, json.dumps({"data": _proposal()}).encode()))
        with self.assertRaises(SemanticProviderTechnicalFailure):
            MaiAgentCategorySemanticProvider(_config(), transport=transport)(_request())
        self.assertEqual(len(transport.calls), 2)

    def test_provenance_omits_credentials_and_chatbot_id(self):
        transport = _RecordedTransport(MaiAgentHttpResponse(200, _response_body(_proposal())))
        result = MaiAgentCategorySemanticProvider(_config(), transport=transport)(_request())
        text = json.dumps(dict(result.provenance))
        self.assertNotIn(_config().api_key, text)
        self.assertNotIn(_config().chatbot_id, text)

    def test_missing_category_configuration_fails_closed_without_writer_fallback(self):
        module = ModuleType("dotenv")
        module.dotenv_values = lambda path: {}
        transport = _RecordedTransport(MaiAgentHttpResponse(200, _response_body(_proposal())))
        with patch.dict("sys.modules", {"dotenv": module}):
            classifier = build_maiagent_category_classifier(
                transport=transport,
                environ={"MAIAGENT_CHATBOT_ID": "writer-only-id"},
                dotenv_path="repo/.env",
            )
        record = _record()
        result = classifier.classify(_group(record), (record,))
        self.assertEqual(result.category_resolution_reason, CategoryResolutionReason.SEMANTIC_HELPER_UNAVAILABLE)
        self.assertEqual(transport.calls, [])

    def test_configuration_process_environment_overrides_dotenv(self):
        module = ModuleType("dotenv")
        module.dotenv_values = lambda path: {
            "MAIAGENT_API_BASE": "https://dotenv.example",
            "MAIAGENT_API_KEY": "dotenv-key",
            "MAIAGENT_STRUCTURED_HELPER_CHATBOT_ID": "dotenv-helper-id",
            "MAIAGENT_CHATBOT_ID": "writer-only-id",
        }
        with patch.dict("sys.modules", {"dotenv": module}):
            config = MaiAgentCategorySemanticProviderConfig.from_environment(
                {"MAIAGENT_API_KEY": "process-key"}, dotenv_path="repo/.env"
            )
        self.assertIsNotNone(config)
        self.assertEqual(config.api_base, "https://dotenv.example")
        self.assertEqual(config.api_key, "process-key")
        self.assertEqual(config.chatbot_id, "dotenv-helper-id")


if __name__ == "__main__":
    unittest.main()
