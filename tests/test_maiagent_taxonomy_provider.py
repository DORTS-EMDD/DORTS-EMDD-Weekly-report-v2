"""Recorded-transport tests for the MaiAgent Taxonomy proposal adapter."""

from __future__ import annotations

import json
import math
import unittest

from src.weekly_report.contracts import (
    CanonicalCandidate,
    CategoryId,
    CategoryResult,
    CategoryState,
    EvidenceResult,
    EvidenceState,
    EventGroup,
    EventIdentityRecord,
    ScopeResult,
    ScopeState,
    TemporalDiagnostic,
    TemporalResult,
    TaxonomyState,
)
from src.weekly_report.maiagent_taxonomy_provider import (
    HELPER_VERSION,
    MAIAGENT_TAXONOMY_RESPONSE_SCHEMA,
    MaiAgentTaxonomyProposalProvider,
    MaiAgentTaxonomyProviderConfig,
    MaiAgentTaxonomyProviderFailure,
    PROMPT_VERSION,
    SCHEMA_VERSION,
    TASK_IDENTITY,
    TAXONOMY_INSTRUCTIONS,
    build_maiagent_taxonomy_model_input,
)
from src.weekly_report.maiagent_transport import MaiAgentHttpResponse
from src.weekly_report.taxonomy import Taxonomy, TaxonomySemanticMember, TaxonomySemanticRequest, TaxonomyStageFailure


def _request() -> TaxonomySemanticRequest:
    return TaxonomySemanticRequest(
        "事件-東京",
        (
            TaxonomySemanticMember("A", "東京 Metro 東京車站的號誌系統完成測試。"),
            TaxonomySemanticMember("B", "Unicode stays exact: 臺灣、東京 and 🚇."),
        ),
    )


def _envelope(value: object) -> bytes:
    return json.dumps({"content": json.dumps(value, ensure_ascii=False)}).encode("utf-8")


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


def _config(timeout_seconds: float = 45.0) -> MaiAgentTaxonomyProviderConfig:
    return MaiAgentTaxonomyProviderConfig(
        "https://maiagent.example/",
        "synthetic-secret",
        "helper-id",
        timeout_seconds=timeout_seconds,
    )


def _proposal(
    request: TaxonomySemanticRequest,
    *,
    state: str = "TAXONOMY_EVALUATED",
    systems: list[str] | None = None,
    reason: str | None = None,
    support: list[dict[str, str]] | None = None,
    conflict: list[dict[str, str]] | None = None,
    insufficient: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "event_id": request.event_id,
        "taxonomy_state": state,
        "systems": systems or [],
        "taxonomy_resolution_reason": reason,
        "support_citations": support or [],
        "conflict_citations": conflict or [],
        "insufficient_provenance": insufficient,
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
        TemporalResult(candidate_id, True, diagnostic=TemporalDiagnostic.NONE),
    )


def _group(*ids: str) -> EventGroup:
    ordered = tuple(sorted(ids))
    return EventGroup("E1", ordered, ordered[0], identity_basis=())


def _assigned(group: EventGroup) -> CategoryResult:
    return CategoryResult(
        category_state=CategoryState.CATEGORY_ASSIGNED,
        event_id=group.event_id,
        primary_category_id=CategoryId.TECHNICAL_DEVELOPMENT,
        primary_category=CategoryId.TECHNICAL_DEVELOPMENT.display_label,
        classification_reason="PRINCIPAL_ACTION_TECHNICAL_DEVELOPMENT",
    )


class MaiAgentTaxonomyProviderTests(unittest.TestCase):
    def test_config_uses_only_shared_helper_keys_and_process_precedence(self):
        values = {
            "MAIAGENT_API_BASE": "https://dotenv.example",
            "MAIAGENT_API_KEY": "dotenv-secret",
            "MAIAGENT_STRUCTURED_HELPER_CHATBOT_ID": "dotenv-helper",
            "CATEGORY_MAIAGENT_CHATBOT_ID": "old-category-id",
            "TAXONOMY_MAIAGENT_CHATBOT_ID": "old-taxonomy-id",
            "MAIAGENT_CHATBOT_ID": "writer-id",
        }
        import sys
        from types import ModuleType
        from unittest.mock import patch

        dotenv = ModuleType("dotenv")
        dotenv.dotenv_values = lambda path: values
        with patch.dict(sys.modules, {"dotenv": dotenv}):
            config = MaiAgentTaxonomyProviderConfig.from_environment(
                {"MAIAGENT_API_KEY": "process-secret"}, dotenv_path="repo/.env"
            )
        self.assertIsNotNone(config)
        self.assertEqual(config.api_key, "process-secret")
        self.assertEqual(config.chatbot_id, "dotenv-helper")

        with patch.dict(sys.modules, {"dotenv": dotenv}):
            self.assertIsNone(
                MaiAgentTaxonomyProviderConfig.from_environment(
                    {"MAIAGENT_STRUCTURED_HELPER_CHATBOT_ID": ""}, dotenv_path="repo/.env"
                )
            )

        old_only = {"MAIAGENT_API_BASE": "https://dotenv.example", "MAIAGENT_API_KEY": "secret", "TAXONOMY_MAIAGENT_CHATBOT_ID": "old"}
        old_dotenv = ModuleType("dotenv")
        old_dotenv.dotenv_values = lambda path: old_only
        with patch.dict(sys.modules, {"dotenv": old_dotenv}):
            self.assertIsNone(MaiAgentTaxonomyProviderConfig.from_environment({}, dotenv_path="repo/.env"))

        empty_dotenv = ModuleType("dotenv")
        empty_dotenv.dotenv_values = lambda path: {}
        forbidden_keys = (
            "MAIAGENT_CHATBOT_ID",
            "CATEGORY_MAIAGENT_CHATBOT_ID",
            "TAXONOMY_MAIAGENT_CHATBOT_ID",
            "REPORTABILITY_MAIAGENT_CHATBOT_ID",
            "EVIDENCE_METADATA_MAIAGENT_CHATBOT_ID",
        )
        with patch.dict(sys.modules, {"dotenv": empty_dotenv}):
            for forbidden_key in forbidden_keys:
                with self.subTest(missing_canonical_key=forbidden_key):
                    process_values = {
                        "MAIAGENT_API_BASE": "https://process.example",
                        "MAIAGENT_API_KEY": "process-secret",
                        forbidden_key: "legacy-helper-id",
                    }
                    self.assertIsNone(
                        MaiAgentTaxonomyProviderConfig.from_environment(
                            process_values,
                            dotenv_path="repo/.env",
                        )
                    )

            process_values = {
                "MAIAGENT_API_BASE": "https://process.example",
                "MAIAGENT_API_KEY": "process-secret",
                "MAIAGENT_STRUCTURED_HELPER_CHATBOT_ID": "",
                "MAIAGENT_CHATBOT_ID": "writer-id",
                "CATEGORY_MAIAGENT_CHATBOT_ID": "category-id",
                "TAXONOMY_MAIAGENT_CHATBOT_ID": "taxonomy-id",
                "REPORTABILITY_MAIAGENT_CHATBOT_ID": "reportability-id",
                "EVIDENCE_METADATA_MAIAGENT_CHATBOT_ID": "metadata-id",
            }
            self.assertIsNone(
                MaiAgentTaxonomyProviderConfig.from_environment(
                    process_values,
                    dotenv_path="repo/.env",
                )
            )

    def test_config_validation_is_strict_and_repr_redacts_credentials(self):
        self.assertNotIn("synthetic-secret", repr(_config()))
        self.assertNotIn("helper-id", repr(_config()))
        for base in ("http://maiagent.example", "https://maiagent.example/path", "https://maiagent.example?x=1", "maiagent.example"):
            with self.subTest(base=base), self.assertRaises(ValueError):
                MaiAgentTaxonomyProviderConfig(base, "secret", "helper")
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
                MaiAgentTaxonomyProviderConfig("https://maiagent.example", **values)

    def test_builder_uses_exact_bounded_request_and_schema(self):
        request = _request()
        model_input = build_maiagent_taxonomy_model_input(request)
        self.assertEqual(model_input["task_identity"], TASK_IDENTITY)
        self.assertEqual(model_input["prompt_version"], PROMPT_VERSION)
        self.assertEqual(model_input["schema_version"], SCHEMA_VERSION)
        self.assertEqual(model_input["helper_version"], HELPER_VERSION)
        self.assertEqual(tuple(model_input["instructions"]), TAXONOMY_INSTRUCTIONS)
        self.assertEqual(model_input["taxonomy_request"], request.as_payload())
        self.assertEqual(model_input["authoritative_response_contract"]["json_schema"], MAIAGENT_TAXONOMY_RESPONSE_SCHEMA)
        self.assertEqual(
            set(model_input["taxonomy_request"]),
            {"event_id", "members"},
        )
        self.assertEqual(
            [member["candidate_id"] for member in model_input["taxonomy_request"]["members"]],
            ["A", "B"],
        )
        self.assertIn("東京", model_input["taxonomy_request"]["members"][0]["substantive_content"])
        serialized = json.dumps(model_input, ensure_ascii=False)
        for forbidden in ("publisher", "url", "search_snippet", "reportability", "writer", "golden"):
            self.assertNotIn(forbidden, serialized.lower())
        self.assertEqual(set(MAIAGENT_TAXONOMY_RESPONSE_SCHEMA["properties"]), {
            "event_id", "taxonomy_state", "systems", "taxonomy_resolution_reason",
            "support_citations", "conflict_citations", "insufficient_provenance",
        })

    def test_actual_sent_payload_and_stateless_envelope_are_exact(self):
        raw = _proposal(_request())
        transport = _RecordedTransport(MaiAgentHttpResponse(200, _envelope(raw)))
        result = MaiAgentTaxonomyProposalProvider(_config(), transport=transport)(_request())
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
        self.assertEqual(sent["task_identity"], TASK_IDENTITY)
        self.assertEqual(sent["prompt_version"], PROMPT_VERSION)
        self.assertEqual(sent["schema_version"], SCHEMA_VERSION)
        self.assertEqual(sent["helper_version"], HELPER_VERSION)
        self.assertEqual(sent["instructions"], list(TAXONOMY_INSTRUCTIONS))
        self.assertEqual(sent["taxonomy_request"], _request().as_payload())
        self.assertEqual(
            sent["authoritative_response_contract"]["schema_version"],
            SCHEMA_VERSION,
        )
        self.assertEqual(sent["authoritative_response_contract"]["json_schema"], MAIAGENT_TAXONOMY_RESPONSE_SCHEMA)

    def test_all_legal_raw_proposal_shapes_are_returned_without_semantic_repair(self):
        request = _request()
        proposals = (
            _proposal(request, systems=["SIGNALLING"], support=[{"system_id": "SIGNALLING", "candidate_id": "A", "exact_quote": "號誌系統完成測試"}]),
            _proposal(request, systems=["ROLLING_STOCK", "SIGNALLING"]),
            _proposal(request, systems=[]),
            _proposal(request, state="TAXONOMY_UNRESOLVED", reason="INSUFFICIENT_SYSTEM_EVIDENCE", insufficient={"member_candidate_ids": ["A", "B"], "diagnostic": "not enough"}),
            _proposal(request, state="TAXONOMY_UNRESOLVED", reason="CONFLICTING_SYSTEM_EVIDENCE", conflict=[{"system_id": "SIGNALLING", "candidate_id": "A", "exact_quote": "號誌"}, {"system_id": "POWER_SUPPLY", "candidate_id": "B", "exact_quote": "供電"}]),
        )
        for proposal in proposals:
            with self.subTest(proposal=proposal):
                transport = _RecordedTransport(MaiAgentHttpResponse(200, _envelope(proposal)))
                self.assertEqual(MaiAgentTaxonomyProposalProvider(_config(), transport=transport)(request), proposal)
                self.assertEqual(len(transport.calls), 1)

    def test_failures_are_safe_and_never_retried(self):
        request = _request()
        for error in (TimeoutError("secret-timeout"), RuntimeError("secret-provider")):
            transport = _RecordedTransport(error=error)
            with self.subTest(error=type(error)), self.assertRaises((TimeoutError, MaiAgentTaxonomyProviderFailure)) as raised:
                MaiAgentTaxonomyProposalProvider(_config(), transport=transport)(request)
            self.assertNotIn("secret", str(raised.exception))
            self.assertEqual(len(transport.calls), 1)

        for response in (
            MaiAgentHttpResponse(503, b"secret body"),
            MaiAgentHttpResponse(200, b"not-json"),
            MaiAgentHttpResponse(200, json.dumps({"answer": "{}"}).encode()),
            MaiAgentHttpResponse(200, json.dumps({"content": "```json\n{}\n```"}).encode()),
            MaiAgentHttpResponse(200, json.dumps({"content": "[]"}).encode()),
        ):
            transport = _RecordedTransport(response)
            with self.subTest(response=response), self.assertRaises(MaiAgentTaxonomyProviderFailure):
                MaiAgentTaxonomyProposalProvider(_config(), transport=transport)(request)
            self.assertEqual(len(transport.calls), 1)

    def test_owner_accepts_valid_adapter_proposal_and_rejects_invalid_support(self):
        group = _group("A")
        record = _record("A", "Traction substation breakers were replaced.")
        valid = _proposal(
            TaxonomySemanticRequest("E1", (TaxonomySemanticMember("A", record.evidence.substantive_content),)),
            systems=["POWER_SUPPLY"],
            support=[{"system_id": "POWER_SUPPLY", "candidate_id": "A", "exact_quote": "Traction substation"}],
        )
        transport = _RecordedTransport(MaiAgentHttpResponse(200, _envelope(valid)))
        result = Taxonomy(MaiAgentTaxonomyProposalProvider(_config(), transport=transport)).evaluate(group, (record,), _assigned(group))
        self.assertEqual(result.taxonomy_state, TaxonomyState.TAXONOMY_EVALUATED)
        self.assertEqual(result.systems[0].value, "POWER_SUPPLY")
        self.assertEqual(len(transport.calls), 1)

        invalid = dict(valid)
        invalid["support_citations"] = [{"system_id": "POWER_SUPPLY", "candidate_id": "A", "exact_quote": "not in source"}]
        transport = _RecordedTransport(MaiAgentHttpResponse(200, _envelope(invalid)))
        with self.assertRaises(TaxonomyStageFailure):
            Taxonomy(MaiAgentTaxonomyProposalProvider(_config(), transport=transport)).evaluate(group, (record,), _assigned(group))
        self.assertEqual(len(transport.calls), 1)

    def test_owner_accepts_all_legal_domain_paths_through_real_adapter(self):
        group = _group("A", "B")
        records = (_record("A", "號誌系統完成測試。"), _record("B", "供電設備完成檢查。"))
        request = TaxonomySemanticRequest(
            group.event_id,
            tuple(
                TaxonomySemanticMember(record.candidate.candidate_id, record.evidence.substantive_content)
                for record in records
            ),
        )
        cases = (
            _proposal(
                request,
                systems=["SIGNALLING"],
                support=[{"system_id": "SIGNALLING", "candidate_id": "A", "exact_quote": "號誌系統完成測試"}],
            ),
            _proposal(request, systems=[]),
            _proposal(
                request,
                state="TAXONOMY_UNRESOLVED",
                reason="INSUFFICIENT_SYSTEM_EVIDENCE",
                insufficient={"member_candidate_ids": ["A", "B"], "diagnostic": "insufficient"},
            ),
            _proposal(
                request,
                state="TAXONOMY_UNRESOLVED",
                reason="CONFLICTING_SYSTEM_EVIDENCE",
                conflict=[
                    {"system_id": "SIGNALLING", "candidate_id": "A", "exact_quote": "號誌"},
                    {"system_id": "POWER_SUPPLY", "candidate_id": "B", "exact_quote": "供電"},
                ],
            ),
        )
        expected_states = (
            TaxonomyState.TAXONOMY_EVALUATED,
            TaxonomyState.TAXONOMY_EVALUATED,
            TaxonomyState.TAXONOMY_UNRESOLVED,
            TaxonomyState.TAXONOMY_UNRESOLVED,
        )
        for proposal, expected_state in zip(cases, expected_states):
            with self.subTest(expected_state=expected_state):
                transport = _RecordedTransport(MaiAgentHttpResponse(200, _envelope(proposal)))
                result = Taxonomy(MaiAgentTaxonomyProposalProvider(_config(), transport=transport)).evaluate(
                    group, records, _assigned(group)
                )
                self.assertEqual(result.taxonomy_state, expected_state)
                self.assertEqual(len(transport.calls), 1)

    def test_owner_rejects_mismatched_member_provenance_through_real_adapter(self):
        group = _group("A", "B")
        records = (_record("A", "A body"), _record("B", "B body"))
        request = TaxonomySemanticRequest(
            group.event_id,
            tuple(
                TaxonomySemanticMember(record.candidate.candidate_id, record.evidence.substantive_content)
                for record in records
            ),
        )
        proposal = _proposal(
            request,
            state="TAXONOMY_UNRESOLVED",
            reason="INSUFFICIENT_SYSTEM_EVIDENCE",
            insufficient={"member_candidate_ids": ["A"], "diagnostic": "incomplete"},
        )
        transport = _RecordedTransport(MaiAgentHttpResponse(200, _envelope(proposal)))
        with self.assertRaises(TaxonomyStageFailure):
            Taxonomy(MaiAgentTaxonomyProposalProvider(_config(), transport=transport)).evaluate(
                group, records, _assigned(group)
            )
        self.assertEqual(len(transport.calls), 1)

    def test_owner_maps_provider_failure_to_technical_stage_failure_not_unresolved(self):
        group = _group("A")
        record = _record("A", "Body")
        for transport in (
            _RecordedTransport(error=TimeoutError("secret")),
            _RecordedTransport(MaiAgentHttpResponse(200, b"not-json")),
        ):
            with self.subTest(transport_error=transport.error is not None), self.assertRaises(TaxonomyStageFailure) as raised:
                Taxonomy(MaiAgentTaxonomyProposalProvider(_config(), transport=transport)).evaluate(
                    group, (record,), _assigned(group)
                )
            self.assertNotEqual(raised.exception.reason, "TAXONOMY_UNRESOLVED")
            self.assertEqual(len(transport.calls), 1)

    def test_construction_and_model_input_make_no_network_calls(self):
        transport = _RecordedTransport()
        provider = MaiAgentTaxonomyProposalProvider(_config(), transport=transport)
        self.assertIsNotNone(provider)
        build_maiagent_taxonomy_model_input(_request())
        self.assertEqual(transport.calls, [])


if __name__ == "__main__":
    unittest.main()
