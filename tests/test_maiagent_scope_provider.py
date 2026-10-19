from __future__ import annotations

import json

import pytest

from src.weekly_report.contracts import ScopeDiagnostic
from src.weekly_report.maiagent_scope_provider import (
    MAIAGENT_SCOPE_RESPONSE_SCHEMA,
    MaiAgentScopeProviderConfig,
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
    assert payload["schema_version"] == SCOPE_PROPOSAL_SCHEMA_VERSION
    assert payload["scope_request"]["candidate_id"] == "C1"
    assert payload["authoritative_response_contract"]["json_schema"] is MAIAGENT_SCOPE_RESPONSE_SCHEMA


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


def test_scope_provider_config_rejects_non_https():
    with pytest.raises(ValueError):
        MaiAgentScopeProviderConfig("http://maiagent.invalid", "key", "helper")


def test_scope_provider_returns_shared_config_none_without_all_keys():
    assert build_maiagent_scope_provider(
        environ={"MAIAGENT_API_BASE": "", "MAIAGENT_API_KEY": "", "MAIAGENT_STRUCTURED_HELPER_CHATBOT_ID": ""},
        dotenv_path="C:/does/not/exist/.env",
    ) is None
