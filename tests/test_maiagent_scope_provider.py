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


def test_prompt_and_schema_express_conditional_citation_obligations():
    payload = build_maiagent_scope_model_input(_request())
    instructions = " ".join(payload["instructions"])
    schema = MAIAGENT_SCOPE_RESPONSE_SCHEMA["properties"]
    # RC-9: citations are Python sentence IDs; no field carries copied text.
    assert PROMPT_VERSION == "scope-event-target-system-v12"
    assert SCOPE_PROPOSAL_SCHEMA_VERSION == "scope-semantic-proposal-v4"
    assert payload["scope_request"]["principal_sentences"][0]["sentence_id"] == "S1"
    assert "principal_content" not in payload["scope_request"]
    assert "quote" not in json.dumps(MAIAGENT_SCOPE_RESPONSE_SCHEMA["required"])
    for record in ("event_focus", "action_target", "target_system", "ambiguity", "noneligible_relation"):
        assert "sentence_ids" in schema[record]["required"]
        assert "quote" not in schema[record]["properties"]
    for endpoint in ("action", "target", "system"):
        assert set(schema[endpoint]["properties"]) == {"label"}
    assert "target_reference" not in schema["target_system"]["required"]
    assert "Cite Evidence only by sentence_id" in instructions
    assert "Never copy, retype" in instructions
    assert "LOCATED_AT, OWNED_BY, and OPERATED_BY never establish target-to-system eligibility" in instructions


def test_scope_prompt_v8_states_relation_anchored_labels_and_boundary_rules():
    instructions = " ".join(SCOPE_SEMANTIC_INSTRUCTIONS)
    # SC-1: labels anchored in the cited relation sentences; target may equal system.
    assert "Endpoints are labels" in instructions
    assert "do not translate, paraphrase, normalize" in instructions
    assert "must contain both the action label and the target label" in instructions
    assert "the exact referring words in target_system.target_reference" in instructions
    assert "may be the same text when the action affects the system itself" in instructions
    assert "Do not borrow support from a separate event" in instructions
    assert "that phrase already states membership" in instructions
    assert "is PART_OF that system" in instructions
    assert "not the contract document itself" in instructions
    assert "never become urban rail through the operator" in instructions
    # SC-2: noneligible relation only for the focus action.
    assert "noneligible_relation concerns only the Candidate focus action's own target or system" in instructions
    assert "When status is ABSENT, noneligible_kind must be NONE" in instructions
    # D1: events on or in a facility of the system; proximity is not LOCATED_AT.
    assert "Proximity, nearby or adjacent locations are never LOCATED_AT" in instructions
    # D2: commuter/suburban/S-Bahn labels neither include nor exclude.
    assert "neither include nor exclude a system by name" in instructions
    assert "never URBAN_RAIL" in instructions
    assert "Uncertainty about details that leave the system unchanged" in instructions
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


def test_mode_words_in_other_languages_name_the_family():
    # RC-27: 捷運 is Taiwan's word for MRT; conventional railways stay out.
    from src.weekly_report.maiagent_scope_provider import SCOPE_SEMANTIC_INSTRUCTIONS as SCOPE_INSTRUCTIONS

    text = " ".join(SCOPE_INSTRUCTIONS)
    assert "捷運 (Taiwan's word for MRT" in text
    assert "台鐵/臺鐵, 高鐵 and JR intercity lines are not urban rail" in text


def test_installed_equipment_takes_its_facilitys_membership_and_negation_is_explicit():
    # RC-43 (section A.31): run 40999869397 lost three reports of AI driver
    # assistance fitted to track-maintenance vehicles when the helper took the
    # installed system, not the vehicles, as the target and left its
    # membership unresolved; a "no works tonight" notice was marked ASSERTED.
    instructions = build_maiagent_scope_model_input(_request())["instructions"]
    equipment = [line for line in instructions if line.startswith("Equipment, devices or systems installed on")]
    assert len(equipment) == 1
    assert "take that facility's membership" in equipment[0]
    assert "track-maintenance vehicles" in equipment[0]
    # The operator-asset exclusion stays, beside the existing operator-identity rule.
    assert "buses, ferries or real estate, remain outside it" in equipment[0]
    assert any("an operator's buses, ferries or real estate never become urban rail" in line for line in instructions)
    negation = [line for line in instructions if line.startswith("Record noneligible, ambiguous")]
    assert len(negation) == 1 and "event_status is NEGATED" in negation[0] and "never an ASSERTED event" in negation[0]


def test_the_candidate_event_is_the_documents_own_news_not_recalled_background():
    # Section A.33: run 41018554355 took a background sentence of a
    # parliamentary-audit report (a service launched two days earlier) as its
    # event focus, and Event Identity, comparing focus excerpts, merged the
    # statement into the launch.
    instructions = build_maiagent_scope_model_input(_request())["instructions"]
    line = [item for item in instructions if item.startswith("The Candidate event is the occurrence the document reports as its own news")]
    assert len(line) == 1
    assert "not an earlier occurrence the document recalls as background" in line[0]
    assert "that statement is the Candidate event" in line[0]
    assert "the occurrence is the Candidate event" in line[0]
    assert instructions.index(line[0]) < next(i for i, item in enumerate(instructions) if item.startswith("event_focus cites"))
