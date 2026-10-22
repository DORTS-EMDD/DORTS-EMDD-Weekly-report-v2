"""Focused contract tests for the MaiAgent Reportability proposal adapter."""

from __future__ import annotations

import json
import math
import sys
import unittest
from types import ModuleType
from unittest.mock import patch

from src.weekly_report.contracts import (
    CanonicalCandidate,
    CategoryId,
    CategoryResult,
    CategoryState,
    EvidenceResult,
    EvidenceState,
    EventDecisionRecord,
    EventGroup,
    EventIdentityRecord,
    ReportabilitySemanticMember,
    ReportabilitySemanticRequest,
    ReportabilityStageFailure,
    ReportabilityState,
    ScopeResult,
    ScopeState,
    TaxonomyResult,
    TaxonomyState,
    TemporalResult,
)
from src.weekly_report.maiagent_reportability_provider import (
    HELPER_VERSION,
    MAIAGENT_REPORTABILITY_RESPONSE_SCHEMA,
    MaiAgentReportabilityProposalProvider,
    MaiAgentReportabilityProviderConfig,
    MaiAgentReportabilityProviderFailure,
    PROMPT_VERSION,
    REPORTABILITY_INSTRUCTIONS,
    SCHEMA_VERSION,
    TASK_IDENTITY,
    build_maiagent_reportability_model_input,
)
from src.weekly_report.contracts import SemanticProviderTechnicalFailure
from src.weekly_report.maiagent_transport import MaiAgentHttpResponse
from src.weekly_report.reportability import Reportability


def _request() -> ReportabilitySemanticRequest:
    return ReportabilitySemanticRequest(
        "事件-東京",
        (
            ReportabilitySemanticMember("A", "東京 Metro 東京車站完成號誌測試。"),
            ReportabilitySemanticMember("B", "Unicode stays exact: 臺灣、東京 and 🚇."),
        ),
    )


def _envelope(value: object) -> bytes:
    return json.dumps(
        {"content": json.dumps(value, ensure_ascii=False)},
        ensure_ascii=False,
    ).encode("utf-8")


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


def _config(timeout_seconds: float = 45.0) -> MaiAgentReportabilityProviderConfig:
    return MaiAgentReportabilityProviderConfig(
        "https://maiagent.example/",
        "synthetic-secret",
        "helper-id",
        timeout_seconds=timeout_seconds,
    )


def _proposal(
    request: ReportabilitySemanticRequest,
    *,
    state: str = "REPORTABLE",
    support: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    return {
        "event_id": request.event_id,
        "proposed_state": state,
        "examined_source_refs": list(request.source_refs),
        "support_citations": support or [],
        "rationale": "The supplied authoritative evidence supports this event.",
    }


def _record(candidate_id: str, body: str) -> EventIdentityRecord:
    evidence = EvidenceResult(
        candidate_id=candidate_id,
        state=EvidenceState.READY,
        canonical_source_url=f"https://example.test/{candidate_id}",
        source_type="authoritative",
        substantive_content=body,
    )
    return EventIdentityRecord(
        CanonicalCandidate(candidate_id, f"Title {candidate_id}", evidence.canonical_source_url),
        evidence,
        ScopeResult(candidate_id, ScopeState.IN_SCOPE),
        TemporalResult(candidate_id, True),
    )


def _decision(body: str = "The metro operator commissioned a new train control system.") -> EventDecisionRecord:
    group = EventGroup("E1", ("A",), "A", identity_basis=())
    category = CategoryResult(
        category_state=CategoryState.CATEGORY_ASSIGNED,
        event_id="E1",
        primary_category_id=CategoryId.TECHNICAL_DEVELOPMENT,
        primary_category=CategoryId.TECHNICAL_DEVELOPMENT.display_label,
        classification_reason="PRINCIPAL_ACTION_TECHNICAL_DEVELOPMENT",
    )
    taxonomy = TaxonomyResult(
        taxonomy_state=TaxonomyState.TAXONOMY_EVALUATED,
        event_id="E1",
    )
    return EventDecisionRecord(group, (_record("A", body),), category, taxonomy)


class MaiAgentReportabilityProviderTests(unittest.TestCase):
    def test_config_uses_only_shared_keys_and_rejects_legacy_fallback(self):
        values = {
            "MAIAGENT_API_BASE": "https://dotenv.example",
            "MAIAGENT_API_KEY": "dotenv-secret",
            "MAIAGENT_STRUCTURED_HELPER_CHATBOT_ID": "dotenv-helper",
            "REPORTABILITY_MAIAGENT_CHATBOT_ID": "legacy-reportability",
            "MAIAGENT_CHATBOT_ID": "writer-id",
        }
        dotenv = ModuleType("dotenv")
        dotenv.dotenv_values = lambda _path: values
        with patch.dict(sys.modules, {"dotenv": dotenv}):
            config = MaiAgentReportabilityProviderConfig.from_environment({}, dotenv_path="repo/.env")
        self.assertIsNotNone(config)
        self.assertEqual(config.api_base, "https://dotenv.example")
        self.assertEqual(config.chatbot_id, "dotenv-helper")

        old_only = {
            "MAIAGENT_API_BASE": "https://dotenv.example",
            "MAIAGENT_API_KEY": "secret",
            "REPORTABILITY_MAIAGENT_CHATBOT_ID": "legacy",
        }
        old_dotenv = ModuleType("dotenv")
        old_dotenv.dotenv_values = lambda _path: old_only
        with patch.dict(sys.modules, {"dotenv": old_dotenv}):
            self.assertIsNone(
                MaiAgentReportabilityProviderConfig.from_environment({}, dotenv_path="repo/.env")
            )

    def test_config_is_strict_and_redacts_credentials(self):
        self.assertNotIn("synthetic-secret", repr(_config()))
        self.assertNotIn("helper-id", repr(_config()))
        for base in (
            "http://maiagent.example",
            "https://maiagent.example/path",
            "https://maiagent.example?x=1",
            "maiagent.example",
        ):
            with self.subTest(base=base), self.assertRaises(ValueError):
                MaiAgentReportabilityProviderConfig(base, "secret", "helper")
        for kwargs in (
            {"api_key": ""},
            {"chatbot_id": ""},
            {"api_key": "a\nb"},
            {"chatbot_id": "a\rb"},
            {"timeout_seconds": 0},
            {"timeout_seconds": -1},
            {"timeout_seconds": math.inf},
            {"timeout_seconds": math.nan},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                values = {"api_key": "secret", "chatbot_id": "helper", "timeout_seconds": 45.0}
                values.update(kwargs)
                MaiAgentReportabilityProviderConfig("https://maiagent.example", **values)

    def test_builder_is_bounded_and_has_exact_task_contract(self):
        request = _request()
        model_input = build_maiagent_reportability_model_input(request)
        self.assertEqual(model_input["task_identity"], TASK_IDENTITY)
        self.assertEqual(model_input["prompt_version"], PROMPT_VERSION)
        self.assertEqual(model_input["schema_version"], SCHEMA_VERSION)
        self.assertEqual(model_input["helper_version"], HELPER_VERSION)
        self.assertEqual(tuple(model_input["instructions"]), REPORTABILITY_INSTRUCTIONS)
        self.assertEqual(model_input["reportability_request"], request.as_payload())
        self.assertEqual(
            set(model_input["reportability_request"]),
            {"event_id", "members"},
        )
        serialized = json.dumps(model_input["reportability_request"], ensure_ascii=False)
        for forbidden in (
            "categoryresult",
            "taxonomyresult",
            "publisher",
            "search_snippet",
            "golden",
            "writer",
            "ordering",
            "start",
            "end",
            "support_spans",
        ):
            self.assertNotIn(forbidden, serialized.lower())

    def test_response_schema_has_only_locked_fields_and_no_offsets(self):
        self.assertEqual(
            set(MAIAGENT_REPORTABILITY_RESPONSE_SCHEMA["properties"]),
            {"event_id", "proposed_state", "examined_source_refs", "support_citations", "rationale"},
        )
        self.assertEqual(
            MAIAGENT_REPORTABILITY_RESPONSE_SCHEMA["properties"]["proposed_state"]["enum"],
            ["REPORTABLE", "NOT_REPORTABLE"],
        )
        citation = MAIAGENT_REPORTABILITY_RESPONSE_SCHEMA["properties"]["support_citations"]["items"]
        self.assertEqual(set(citation["properties"]), {"source_ref", "sentence_ids"})
        self.assertNotIn("start", json.dumps(MAIAGENT_REPORTABILITY_RESPONSE_SCHEMA))
        self.assertNotIn("end", json.dumps(MAIAGENT_REPORTABILITY_RESPONSE_SCHEMA))

    def test_actual_envelope_is_stateless_and_preserves_unicode(self):
        request = _request()
        raw = _proposal(request, support=[{"source_ref": "M1", "sentence_ids": ["S1"]}])
        transport = _RecordedTransport(MaiAgentHttpResponse(200, _envelope(raw)))
        result = MaiAgentReportabilityProposalProvider(_config(), transport=transport)(request)
        self.assertEqual(result, raw)
        self.assertEqual(len(transport.calls), 1)
        endpoint, headers, body, timeout = transport.calls[0]
        self.assertEqual(endpoint, "https://maiagent.example/api/v1/chatbots/helper-id/completions/")
        self.assertEqual(headers["Authorization"], "Api-Key synthetic-secret")
        self.assertEqual(timeout, 45.0)
        outer = json.loads(body)
        self.assertIsNone(outer["conversation"])
        self.assertEqual(outer["attachments"], [])
        self.assertFalse(outer["is_streaming"])
        sent = json.loads(outer["message"]["content"])
        self.assertEqual(sent["task_identity"], TASK_IDENTITY)
        self.assertEqual(sent["reportability_request"], request.as_payload())
        self.assertNotIn("model", sent)

    def test_failure_paths_are_safe_and_retried_only_when_transient(self):
        # RC-6: transient failures get one identical retry; another non-200
        # status (402) is non-transient and not retried.  Nothing is repaired.
        request = _request()
        for error in (TimeoutError("secret-timeout"), RuntimeError("secret-provider")):
            transport = _RecordedTransport(error=error)
            with self.subTest(error=type(error)), self.assertRaises(SemanticProviderTechnicalFailure) as raised:
                MaiAgentReportabilityProposalProvider(_config(), transport=transport)(request)
            self.assertNotIn("secret", str(raised.exception))
            self.assertEqual(len(transport.calls), 2)
        for response, calls in (
            (MaiAgentHttpResponse(402, b"secret body"), 1),
            (MaiAgentHttpResponse(200, b"not-json"), 2),
            (MaiAgentHttpResponse(200, json.dumps({"answer": "{}"}).encode()), 2),
        ):
            transport = _RecordedTransport(response)
            with self.subTest(response=response), self.assertRaises(SemanticProviderTechnicalFailure) as raised:
                MaiAgentReportabilityProposalProvider(_config(), transport=transport)(request)
            self.assertNotIn("secret", str(raised.exception))
            self.assertEqual(len(transport.calls), calls)

    def test_construction_and_builder_make_no_network_calls(self):
        transport = _RecordedTransport()
        provider = MaiAgentReportabilityProposalProvider(_config(), transport=transport)
        self.assertIsNotNone(provider)
        build_maiagent_reportability_model_input(_request())
        self.assertEqual(transport.calls, [])

    def test_existing_reportability_owner_accepts_valid_adapter_proposal(self):
        decision = _decision()
        request = ReportabilitySemanticRequest(
            "E1",
            (ReportabilitySemanticMember("A", decision.member_records[0].evidence.substantive_content),),
        )
        raw = _proposal(
            request,
            support=[{"source_ref": "M1", "sentence_ids": ["S1"]}],
        )
        transport = _RecordedTransport(MaiAgentHttpResponse(200, _envelope(raw)))
        result = Reportability(MaiAgentReportabilityProposalProvider(_config(), transport=transport)).evaluate(decision)
        self.assertEqual(result.reportability_state, ReportabilityState.REPORTABLE)
        self.assertIsNone(result.reportability_reason)
        # RC-16: the span is the cited sentence.
        content = decision.member_records[0].evidence.substantive_content
        span = result.provenance.support_spans[0]
        self.assertEqual(span.start, 0)
        self.assertTrue(content[span.start:span.end].startswith("The metro operator commissioned"))
        self.assertEqual(len(transport.calls), 1)

    def test_existing_reportability_owner_accepts_not_reportable_adapter_proposal(self):
        decision = _decision("The source describes only an unrelated administrative notice.")
        request = ReportabilitySemanticRequest(
            "E1",
            (ReportabilitySemanticMember("A", decision.member_records[0].evidence.substantive_content),),
        )
        raw = _proposal(request, state="NOT_REPORTABLE")
        transport = _RecordedTransport(MaiAgentHttpResponse(200, _envelope(raw)))
        result = Reportability(MaiAgentReportabilityProposalProvider(_config(), transport=transport)).evaluate(decision)
        self.assertEqual(result.reportability_state, ReportabilityState.NOT_REPORTABLE)
        self.assertEqual(result.reportability_reason.value, "LOW_REPORTABILITY_VALUE")
        self.assertEqual(len(transport.calls), 1)

    def test_owner_rejects_invalid_quote_and_provider_failure_without_rescue(self):
        decision = _decision()
        request = ReportabilitySemanticRequest(
            "E1",
            (ReportabilitySemanticMember("A", decision.member_records[0].evidence.substantive_content),),
        )
        invalid = _proposal(request, support=[{"source_ref": "M1", "sentence_ids": ["S9"]}])
        transport = _RecordedTransport(MaiAgentHttpResponse(200, _envelope(invalid)))
        with self.assertRaises(ReportabilityStageFailure):
            Reportability(MaiAgentReportabilityProposalProvider(_config(), transport=transport)).evaluate(decision)
        self.assertEqual(len(transport.calls), 1)


class ReportabilityCriteriaTests(unittest.TestCase):
    """RC-10: the contract's accepted value paths reach the helper."""

    def test_instructions_carry_the_contract_value_paths_and_incident_boundary(self):
        from src.weekly_report.maiagent_reportability_provider import PROMPT_VERSION, REPORTABILITY_INSTRUCTIONS

        instructions = " ".join(REPORTABILITY_INSTRUCTIONS)
        self.assertEqual(PROMPT_VERSION, "reportability-principal-body-v4")
        self.assertIn("Accepted value paths", instructions)
        self.assertIn("substantive technical research, testing, pilots or deployments", instructions)
        self.assertIn("procurement, demonstration or trial activity", instructions)
        self.assertIn("An ordinary crime, assault, medical or personal incident", instructions)
        self.assertIn("Relevance to Taipei alone never makes an event REPORTABLE", instructions)
        self.assertIn("No path requires novelty", instructions)


if __name__ == "__main__":
    unittest.main()


def test_instructions_name_the_general_low_value_classes():
    from src.weekly_report.maiagent_reportability_provider import REPORTABILITY_INSTRUCTIONS

    text = " ".join(REPORTABILITY_INSTRUCTIONS)
    assert "Awards, rankings, media praise" in text
    assert "statements by officials are NOT_REPORTABLE unless" in text
    assert "minor collision with only a brief local disruption is NOT_REPORTABLE" in text
