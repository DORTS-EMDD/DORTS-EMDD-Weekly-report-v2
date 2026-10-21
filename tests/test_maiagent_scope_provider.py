from __future__ import annotations

import json

import pytest

from src.weekly_report.contracts import ScopeDiagnostic, SemanticProviderTechnicalFailure
from src.weekly_report.maiagent_scope_provider import (
    MAIAGENT_SCOPE_RESPONSE_SCHEMA,
    MaiAgentScopeProviderConfig,
    MaiAgentScopeProviderFailure,
    PROMPT_VERSION,
    SCOPE_SEMANTIC_INSTRUCTIONS,
    build_maiagent_scope_model_input,
    build_maiagent_scope_provider,
)
from src.weekly_report.maiagent_transport import MaiAgentHttpResponse
from src.weekly_report.scope_classifier import ScopeSemanticRequest, SCOPE_PROPOSAL_SCHEMA_VERSION


def _request() -> ScopeSemanticRequest:
    return ScopeSemanticRequest("C1", "Metro signalling", "The Metro system renewed signalling equipment.", {"source": "fixture"})


def test_scope_model_input_is_versioned_and_task_specific():
    payload = build_maiagent_scope_model_input(_request())
    assert payload["task_identity"] == "scope_semantic_proposal"
    assert payload["prompt_version"] == PROMPT_VERSION
    assert payload["schema_version"] == SCOPE_PROPOSAL_SCHEMA_VERSION
    assert payload["scope_request"]["candidate_id"] == "C1"
    assert payload["authoritative_response_contract"]["json_schema"] is MAIAGENT_SCOPE_RESPONSE_SCHEMA


def test_prompt_and_schema_express_conditional_quote_obligations():
    payload = build_maiagent_scope_model_input(_request())
    instructions = " ".join(payload["instructions"])
    schema = MAIAGENT_SCOPE_RESPONSE_SCHEMA["properties"]
    # RC-8: v5 anchors endpoint labels inside relation quotations; endpoints
    # carry no quotations of their own.
    assert PROMPT_VERSION == "scope-event-target-system-v7"
    assert SCOPE_PROPOSAL_SCHEMA_VERSION == "scope-semantic-proposal-v3"
    assert "records every occurrence" in MAIAGENT_SCOPE_RESPONSE_SCHEMA["description"]
    assert "occur exactly once" not in instructions
    assert "Every nonempty quotation" in instructions
    assert "LOCATED_AT, OWNED_BY, and OPERATED_BY never establish target-to-system eligibility" in instructions
    for endpoint in ("action", "target", "system"):
        assert set(schema[endpoint]["properties"]) == {"label"}
    assert "UNRESOLVED" in schema["event_focus"]["properties"]["quote"]["description"]
    assert "ESTABLISHED or CONFLICTING" in schema["action_target"]["properties"]["quote"]["description"]
    assert "action and target labels" in schema["action_target"]["properties"]["quote"]["description"]
    assert "target_reference and the system label" in schema["target_system"]["properties"]["quote"]["description"]
    assert "same-event reference" in schema["target_system"]["properties"]["target_reference"]["description"]
    assert "target_reference" not in MAIAGENT_SCOPE_RESPONSE_SCHEMA["properties"]["target_system"]["required"]
    assert "NONE or UNRESOLVED" in schema["ambiguity"]["properties"]["quote"]["description"]
    assert "focus action's own target or system" in schema["noneligible_relation"]["properties"]["quote"]["description"]


def test_scope_prompt_v6_states_relation_anchored_labels_and_boundary_rules():
    instructions = " ".join(SCOPE_SEMANTIC_INSTRUCTIONS)
    # SC-1: labels anchored in relation quotations; target may equal system.
    assert "Endpoints are labels, not quotations" in instructions
    assert "do not translate, paraphrase, normalize" in instructions
    assert "must contain both the action label and the target label" in instructions
    assert "must contain the target label and the system label" in instructions
    assert "put that exact reference in target_system.target_reference" in instructions
    assert "Uncertainty about details that leave the system unchanged" in instructions
    assert "Never invent a quotation that repeats the target label" in instructions
    assert "that phrase already states membership" in instructions
    assert "is PART_OF that system" in instructions
    assert "not the contract document itself" in instructions
    assert "never become urban rail through the operator" in instructions
    assert "may be the same text when the action affects the system itself" in instructions
    assert "must not borrow support from a separate event" in instructions
    # SC-2: noneligible relation only for the focus action.
    assert "noneligible_relation concerns only the Candidate focus action's own target or system" in instructions
    assert "When status is ABSENT, noneligible_kind must be NONE" in instructions
    assert "mode must be NON_ELIGIBLE" in instructions
    # D1: events on or in a facility of the system; proximity is not LOCATED_AT.
    assert "Proximity, nearby or adjacent locations are never LOCATED_AT" in instructions
    # D2: commuter/suburban/S-Bahn labels neither include nor exclude.
    assert "neither include nor exclude a system by name" in instructions
    assert "never URBAN_RAIL" in instructions
    assert "NON_ELIGIBLE and UNKNOWN are valid" in instructions
    assert "anaphora, demonstratives, possessives, component relationships, and cross-sentence" in instructions
    assert "A location, operator identity alone, ownership identity, generic equipment word, or nearby station is not target-to-system membership" in instructions
    assert "action_target ESTABLISHED even if target_system is UNESTABLISHED" in instructions
    assert "Do not force a positive proposal" in instructions


def test_scope_provider_uses_shared_configuration_and_stateless_call():
    calls = []

    def transport(endpoint, *, headers, body, timeout_seconds):
        calls.append((endpoint, headers, json.loads(body), timeout_seconds))
        return MaiAgentHttpResponse(200, b'{"content":"{\\"invalid\\":true}"}')

    provider = build_maiagent_scope_provider(
        transport=transport,
        environ={"MAIAGENT_API_BASE": "https://maiagent.invalid", "MAIAGENT_API_KEY": "key", "MAIAGENT_STRUCTURED_HELPER_CHATBOT_ID": "helper"},
    )
    assert provider is not None
    provider(_request())
    assert len(calls) == 1
    body = calls[0][2]
    assert body["conversation"] is None
    assert body["attachments"] == []
    assert body["is_streaming"] is False
    request = json.loads(body["message"]["content"])
    assert request["task_identity"] == "scope_semantic_proposal"
    assert request["prompt_version"] == PROMPT_VERSION


def test_scope_provider_config_rejects_non_https():
    with pytest.raises(ValueError):
        MaiAgentScopeProviderConfig("http://maiagent.invalid", "key", "helper")


def test_scope_provider_returns_shared_config_none_without_all_keys():
    assert build_maiagent_scope_provider(
        environ={"MAIAGENT_API_BASE": "", "MAIAGENT_API_KEY": "", "MAIAGENT_STRUCTURED_HELPER_CHATBOT_ID": ""},
        dotenv_path="C:/does/not/exist/.env",
    ) is None


@pytest.mark.parametrize(
    ("transport_result", "expected_class"),
    [
        (MaiAgentHttpResponse(503, b"credential-like body is discarded"), "HTTP_503"),
        (MaiAgentHttpResponse(200, b"not-json"), "UNPARSEABLE_RESPONSE"),
    ],
)
def test_scope_provider_failure_categories_are_safe_and_distinct(transport_result, expected_class):
    # RC-6: transient failures are typed technical failures after one retry.
    calls = []

    def transport(*_args, **_kwargs):
        calls.append(1)
        return transport_result

    provider = build_maiagent_scope_provider(
        transport=transport,
        environ={"MAIAGENT_API_BASE": "https://maiagent.invalid", "MAIAGENT_API_KEY": "key", "MAIAGENT_STRUCTURED_HELPER_CHATBOT_ID": "helper"},
    )
    assert provider is not None
    with pytest.raises(SemanticProviderTechnicalFailure) as caught:
        provider(_request())
    assert caught.value.failure_class == expected_class
    assert len(calls) == 2
    assert "credential-like" not in str(caught.value)


def test_scope_provider_transport_failure_category_is_safe():
    def failed_transport(*_args, **_kwargs):
        raise RuntimeError("provider supplied details are not retained")

    provider = build_maiagent_scope_provider(
        transport=failed_transport,
        environ={"MAIAGENT_API_BASE": "https://maiagent.invalid", "MAIAGENT_API_KEY": "key", "MAIAGENT_STRUCTURED_HELPER_CHATBOT_ID": "helper"},
    )
    assert provider is not None
    with pytest.raises(SemanticProviderTechnicalFailure) as caught:
        provider(_request())
    assert caught.value.failure_class == "CONNECTION"
    assert "provider supplied details" not in str(caught.value)
