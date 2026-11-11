"""Recorded transport tests for the constrained Category semantic provider."""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
from types import ModuleType
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator

import src.weekly_report.category_semantic_provider as category_semantic_provider_module
from src.weekly_report.contracts import (
    SemanticProviderConfigurationFailure,
    SemanticProviderTechnicalFailure,
)
import src.weekly_report.classifier as classifier_module

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
    build_maiagent_category_schema,
    build_maiagent_category_model_input,
    build_maiagent_category_classifier,
)
from src.weekly_report.classifier import CategoryProposalViolation, CategorySemanticRequest, Classifier
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
)


class _RecordedMaiAgentTransport:
    def __init__(self, response=None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.calls = []

    def __call__(self, endpoint, *, headers, body, timeout_seconds):
        self.calls.append((endpoint, dict(headers), body, timeout_seconds))
        if self.error:
            raise self.error
        return self.response


def _record(candidate_id="source-1", body="The operator began a signalling pilot."):
    return EventIdentityRecord(
        CanonicalCandidate(
            candidate_id=candidate_id,
            title="PRIVATE_TITLE",
            url="https://private.invalid/?q=PRIVATE_QUERY",
            publisher="PRIVATE_PUBLISHER",
            published_at="PRIVATE_DATE",
            discovery_intent="PRIVATE_INTENT",
            search_snippet="PRIVATE_SNIPPET",
        ),
        EvidenceResult(
            candidate_id=candidate_id,
            state=EvidenceState.READY,
            canonical_source_url="https://private.invalid/source",
            substantive_content=body,
        ),
        ScopeResult(candidate_id=candidate_id, state=ScopeState.IN_SCOPE),
        TemporalResult(candidate_id=candidate_id, date_valid=True),
    )


def _group(record):
    candidate_id = record.candidate.candidate_id
    return EventGroup(
        event_id="private-event-id",
        member_candidate_ids=(candidate_id,),
        canonical_candidate_id=candidate_id,
        identity_basis=(),
    )


_VIOLATION = "PROPOSAL_VIOLATION"


def _classify(classifier, group, records):
    """Return the CategoryResult, or _VIOLATION for a disclosed gap (RC-16)."""

    try:
        return classifier.classify(group, records)
    except CategoryProposalViolation:
        return _VIOLATION


def _proposal(record, *, state=CategoryState.CATEGORY_ASSIGNED, category_id=CategoryId.TECHNICAL_DEVELOPMENT):
    if state is CategoryState.CATEGORY_ASSIGNED:
        return {
            "category_state": state.value,
            "primary_category_id": category_id.value,
            "subtype": "pilot",
            "category_resolution_reason": None,
            "citations": [{"source_ref": "M1", "sentence_ids": ["S1"]}],
        }
    return {
        "category_state": state.value,
        "primary_category_id": None,
        "subtype": None,
        "category_resolution_reason": CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION.value,
        "citations": [{"source_ref": "M1", "sentence_ids": ["S1"]}],
    }


def _top_level_assignment_count(module, name):
    source = Path(module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    count = 0
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = (node.target,)
        else:
            continue
        count += sum(
            isinstance(target, ast.Name) and target.id == name
            for target in targets
        )
    return count


class CategorySemanticProviderTests(unittest.TestCase):
    def test_authoritative_v6_schema_and_five_field_contract(self):
        self.assertEqual(CATEGORY_SEMANTIC_SCHEMA_VERSION, "category-proposal-v6")
        self.assertEqual(MAIAGENT_CATEGORY_MESSAGE_VERSION, "category-full-response-contract-v3")
        Draft202012Validator.check_schema(_CATEGORY_RESPONSE_SCHEMA)
        validator = Draft202012Validator(_CATEGORY_RESPONSE_SCHEMA)
        expected_fields = {
            "category_state",
            "primary_category_id",
            "subtype",
            "category_resolution_reason",
            "citations",
        }
        self.assertEqual(set(_CATEGORY_RESPONSE_SCHEMA["properties"]), expected_fields)
        self.assertEqual(set(_CATEGORY_RESPONSE_SCHEMA["required"]), expected_fields)
        self.assertFalse(_CATEGORY_RESPONSE_SCHEMA["additionalProperties"])

        record = _record()
        assigned = _proposal(record)
        assigned["subtype"] = None
        self.assertTrue(validator.is_valid(assigned))
        unresolved = _proposal(record, state=CategoryState.CATEGORY_UNRESOLVED)
        for reason in (
            CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION,
            CategoryResolutionReason.RECOMMENDATION_WITHOUT_ADOPTED_ACTION,
            CategoryResolutionReason.CONFLICTING_CATEGORY_DEFINING_CLAIMS,
            CategoryResolutionReason.NO_UNIQUE_PRINCIPAL_ACTION,
            CategoryResolutionReason.INSUFFICIENT_CATEGORY_EVIDENCE,
        ):
            with self.subTest(reason=reason):
                proposal = dict(unresolved, category_resolution_reason=reason.value)
                self.assertTrue(validator.is_valid(proposal))
                if reason is CategoryResolutionReason.NO_UNIQUE_PRINCIPAL_ACTION:
                    self.assertEqual(len(proposal["citations"]), 1)

    def test_assigned_subtype_schema_and_classifier_acceptance_are_identical(self):
        validator = Draft202012Validator(_CATEGORY_RESPONSE_SCHEMA)
        record = _record()
        valid_subtypes = (
            None,
            "a",
            "valid",
            "valid_name",
            "a1",
            "a" * 64,
            "valid\n",
            "valid\r",
            "valid\r\n",
            " valid",
            "valid ",
            "Invalid",
            "valid-name",
            "",
            "a" * 65,
        )
        invalid_subtypes = (
            5,
            True,
            [],
            {},
        )

        for subtype in valid_subtypes + invalid_subtypes:
            with self.subTest(subtype=repr(subtype)):
                proposal = _proposal(record)
                proposal["subtype"] = subtype
                schema_accepts = validator.is_valid(proposal)
                result = _classify(
                    Classifier(lambda _request: proposal), _group(record), (record,)
                )
                classifier_accepts = (
                    result is not _VIOLATION
                    and result.category_state is CategoryState.CATEGORY_ASSIGNED
                )

                self.assertEqual(schema_accepts, classifier_accepts)
                self.assertEqual(
                    schema_accepts,
                    subtype in valid_subtypes,
                )

    def test_v6_schema_rejects_legacy_fields_and_invalid_state_shapes(self):
        validator = Draft202012Validator(_CATEGORY_RESPONSE_SCHEMA)
        record = _record()
        assigned = _proposal(record)
        unresolved = _proposal(record, state=CategoryState.CATEGORY_UNRESOLVED)
        invalid = {
            "legacy-v3-fields": dict(
                assigned,
                support_spans=[],
                conflict_spans=[],
            ),
            "assigned-null-category": dict(assigned, primary_category_id=None),
            "assigned-with-reason": dict(
                assigned,
                category_resolution_reason=CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION.value,
            ),
            "invalid-subtype-type": dict(assigned, subtype=5),
            "unresolved-with-category": dict(
                unresolved,
                primary_category_id=CategoryId.PROCUREMENT.value,
            ),
            "unresolved-with-subtype": dict(unresolved, subtype="award"),
            "empty-citations": dict(assigned, citations=[]),
            "empty-source-ref": dict(
                assigned,
                citations=[{"source_ref": "", "sentence_ids": ["S1"]}],
            ),
            "empty-sentence-ids": dict(
                assigned,
                citations=[{"source_ref": "M1", "sentence_ids": []}],
            ),
            "extra-top-level-field": dict(assigned, unexpected="value"),
        }
        for name, proposal in invalid.items():
            with self.subTest(case=name):
                self.assertFalse(validator.is_valid(proposal))
                result = _classify(
                    Classifier(
                        MaiAgentCategorySemanticProvider(_maiagent_config(), transport=_maiagent_transport(proposal))
                    ),
                    _group(record),
                    (record,),
                )
                self.assertEqual(result, _VIOLATION)

    def test_projection_is_derived_and_contains_sentence_citations_without_offsets(self):
        full_schema_before = json.loads(json.dumps(_CATEGORY_RESPONSE_SCHEMA))
        projection = build_maiagent_category_schema(_CATEGORY_RESPONSE_SCHEMA)
        projection_validator = Draft202012Validator(projection)
        self.assertEqual(projection, _MAIAGENT_CATEGORY_RESPONSE_SCHEMA)
        self.assertEqual(_CATEGORY_RESPONSE_SCHEMA, full_schema_before)
        Draft202012Validator.check_schema(_CATEGORY_RESPONSE_SCHEMA)

        unsupported = {
            "oneOf", "allOf", "if", "then", "else", "const", "minItems",
            "maxItems", "minLength", "pattern", "minimum",
        }

        def schema_keywords(value):
            if isinstance(value, dict):
                found = set(value)
                for child in value.values():
                    found.update(schema_keywords(child))
                return found
            if isinstance(value, list):
                found = set()
                for child in value:
                    found.update(schema_keywords(child))
                return found
            return set()

        self.assertFalse(schema_keywords(projection) & unsupported)
        expected_fields = {
            "category_state", "primary_category_id", "subtype",
            "category_resolution_reason", "citations",
        }
        self.assertEqual(set(projection["properties"]), expected_fields)
        self.assertEqual(set(projection["required"]), expected_fields)
        self.assertFalse(projection["additionalProperties"])
        item = projection["properties"]["citations"]["items"]
        self.assertEqual(set(item["properties"]), {"source_ref", "sentence_ids"})
        self.assertEqual(set(item["required"]), {"source_ref", "sentence_ids"})
        self.assertFalse(item["additionalProperties"])
        self.assertEqual(item["properties"]["source_ref"]["type"], "string")
        self.assertEqual(item["properties"]["sentence_ids"]["type"], "array")

        record = _record()
        assigned = _proposal(record)
        self.assertTrue(projection_validator.is_valid(dict(assigned, citations=[])))
        # The capability projection omits minItems; the authoritative Classifier rejects it.
        result = _classify(
            Classifier(
                MaiAgentCategorySemanticProvider(_maiagent_config(), transport=_maiagent_transport(dict(assigned, citations=[])),
                )
            ),
            _group(record),
            (record,),
        )
        self.assertEqual(result, _VIOLATION)

        tree = ast.parse(Path(category_semantic_provider_module.__file__).read_text(encoding="utf-8"))
        assignments = [
            node for node in tree.body
            if isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and "SCHEMA" in node.target.id
            and isinstance(node.value, ast.Dict)
        ]
        self.assertEqual(
            [node.target.id for node in assignments],
            ["_CITATION_SCHEMA", "_CATEGORY_RESPONSE_SCHEMA"],
        )
        self.assertEqual(
            _top_level_assignment_count(category_semantic_provider_module, "_CATEGORY_RESPONSE_SCHEMA"),
            1,
        )

    def test_guidance_uses_sentence_citations_and_aligns_existing_g54_g68_rules(self):
        guidance = "\n".join(classifier_module._CATEGORY_GUIDANCE)
        self.assertIn("source_ref", guidance)
        self.assertIn("sentence_ids", guidance)
        self.assertNotIn("exact quote", guidance)
        self.assertIn("completed incident investigation", guidance)
        self.assertIn("OPERATIONAL_CHANGE", guidance)
        self.assertIn("ordinary passenger complaint", guidance)
        self.assertIn("NO_CATEGORY_DEFINING_ACTION", guidance)
        self.assertNotIn("support_spans", guidance)
        self.assertNotIn("conflict_spans", guidance)
        self.assertNotIn("start inclusive", guidance)
        self.assertNotIn("end exclusive", guidance)

    def test_guidance_maps_every_unresolved_reason_to_distinct_semantics(self):
        guidance = "\n".join(classifier_module._CATEGORY_GUIDANCE)
        for reason in (
            CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION,
            CategoryResolutionReason.RECOMMENDATION_WITHOUT_ADOPTED_ACTION,
            CategoryResolutionReason.CONFLICTING_CATEGORY_DEFINING_CLAIMS,
            CategoryResolutionReason.NO_UNIQUE_PRINCIPAL_ACTION,
            CategoryResolutionReason.INSUFFICIENT_CATEGORY_EVIDENCE,
        ):
            self.assertIn(reason.value, guidance)
        self.assertIn("positively establishes an unadopted recommendation", guidance)
        self.assertIn("sources need not contradict each other", guidance)
        self.assertIn("distinct from evidence affirmatively establishing", guidance)
        self.assertIn("Subtype is optional descriptive metadata", guidance)

    def test_authoritative_schema_and_guidance_each_have_one_source(self):
        self.assertEqual(
            _top_level_assignment_count(
                category_semantic_provider_module,
                "_CATEGORY_RESPONSE_SCHEMA",
            ),
            1,
        )
        self.assertEqual(
            _top_level_assignment_count(classifier_module, "_CATEGORY_GUIDANCE"),
            1,
        )

    def test_empty_citations_fail_closed_without_provider_backfill(self):
        record = _record()
        for state in (CategoryState.CATEGORY_ASSIGNED, CategoryState.CATEGORY_UNRESOLVED):
            with self.subTest(state=state):
                proposal = _proposal(record, state=state)
                proposal["citations"] = []
                result = _classify(
                    Classifier(MaiAgentCategorySemanticProvider(_maiagent_config(), transport=_maiagent_transport(proposal))),
                    _group(record),
                    (record,),
                )
                self.assertEqual(result, _VIOLATION)

    def test_unresolved_proposal_remains_terminal_in_classifier(self):
        record = _record(body="A system name appears without an announced action.")
        result = build_maiagent_category_classifier(
            _maiagent_config(),
            transport=_maiagent_transport(_proposal(record, state=CategoryState.CATEGORY_UNRESOLVED)),
        ).classify(_group(record), (record,))
        self.assertEqual(result.category_state, CategoryState.CATEGORY_UNRESOLVED)
        self.assertIsNone(result.primary_category_id)
        self.assertEqual(
            result.category_resolution_reason,
            CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION,
        )

    def test_request_carries_no_candidate_metadata(self):
        record = _record()
        transport = _maiagent_transport(_proposal(record))
        MaiAgentCategorySemanticProvider(_maiagent_config(), transport=transport)(_category_request(record))
        submitted = transport.calls[0][2].decode("utf-8")
        for forbidden in ("PRIVATE_TITLE", "PRIVATE_QUERY", "PRIVATE_INTENT", "PRIVATE_SNIPPET",
                          "PRIVATE_PUBLISHER", "PRIVATE_DATE", "expected_category", "GOLDEN_CASE"):
            self.assertNotIn(forbidden, submitted)
        self.assertIn("signalling pilot", submitted)

    def test_invalid_schema_unknown_category_and_bad_citation_fail_closed(self):
        record = _record()
        valid = _proposal(record)
        missing = dict(valid)
        missing.pop("subtype")
        mutations = [
            missing,
            dict(valid, primary_category_id="UNKNOWN_CATEGORY"),
            dict(valid, citations=[{"source_ref": "M9", "sentence_ids": ["S1"]}]),
        ]
        for proposal in mutations:
            with self.subTest(proposal=proposal):
                result = _classify(
                    Classifier(MaiAgentCategorySemanticProvider(_maiagent_config(), transport=_maiagent_transport(proposal))),
                    _group(record),
                    (record,),
                )
                self.assertEqual(result, _VIOLATION)


def _maiagent_config():
    return MaiAgentCategorySemanticProviderConfig(
        api_base="https://api.maiagent.ai/",
        api_key="synthetic-test-api-key",
        chatbot_id="synthetic-category-chatbot-id",
    )


def _category_request(record):
    class Capture:
        value = None

        def __call__(self, request):
            self.value = request
            return _proposal(record)

    capture = Capture()
    Classifier(capture).classify(_group(record), (record,))
    return capture.value


def _maiagent_body(proposal):
    return json.dumps({"content": json.dumps(proposal)}).encode("utf-8")


def _maiagent_transport(proposal):
    return _RecordedMaiAgentTransport(MaiAgentHttpResponse(200, _maiagent_body(proposal)))


def _dotenv_module(values):
    module = ModuleType("dotenv")
    module.dotenv_values = lambda path: values
    return module


class MaiAgentCategorySemanticProviderTests(unittest.TestCase):
    def test_request_uses_the_confirmed_completions_contract(self):
        record = _record(body="The agency awarded a contract to Example Rail Ltd.")
        request = _category_request(record)
        transport = _RecordedMaiAgentTransport(
            MaiAgentHttpResponse(200, _maiagent_body(_proposal(record)))
        )

        MaiAgentCategorySemanticProvider(_maiagent_config(), transport=transport)(request)

        self.assertEqual(len(transport.calls), 1)
        endpoint, headers, raw_body, _ = transport.calls[0]
        self.assertEqual(
            endpoint,
            "https://api.maiagent.ai/api/v1/chatbots/"
            "synthetic-category-chatbot-id/completions/",
        )
        self.assertEqual(headers["Authorization"], "Api-Key synthetic-test-api-key")
        body = json.loads(raw_body)
        self.assertIsInstance(body["message"]["content"], str)
        model_input = json.loads(body["message"]["content"])
        self.assertEqual(model_input["category_request"], request.as_payload())
        self.assertEqual(
            model_input["authoritative_response_contract"],
            {
                "schema_version": CATEGORY_SEMANTIC_SCHEMA_VERSION,
                "json_schema": _CATEGORY_RESPONSE_SCHEMA,
            },
        )
        self.assertEqual(model_input, build_maiagent_category_model_input(request))
        self.assertIsNone(body["conversation"])
        self.assertEqual(body["attachments"], [])
        self.assertIs(body["is_streaming"], False)
        self.assertEqual(body["message"]["role"], "user")
        self.assertNotIn("schema", body)

    def test_maiagent_full_contract_tracks_authoritative_schema_mechanically(self):
        record = _record()
        request = _category_request(record)
        changed_schema = json.loads(json.dumps(_CATEGORY_RESPONSE_SCHEMA))
        changed_schema["properties"]["subtype"]["description"] = "mechanical-test-change"
        transport = _RecordedMaiAgentTransport(
            MaiAgentHttpResponse(200, _maiagent_body(_proposal(record)))
        )

        with patch.object(
            category_semantic_provider_module,
            "_CATEGORY_RESPONSE_SCHEMA",
            changed_schema,
        ):
            MaiAgentCategorySemanticProvider(_maiagent_config(), transport=transport)(request)

        raw_body = transport.calls[0][2]
        model_input = json.loads(json.loads(raw_body)["message"]["content"])
        self.assertEqual(
            model_input["authoritative_response_contract"]["json_schema"],
            changed_schema,
        )
        self.assertEqual(
            _MAIAGENT_CATEGORY_RESPONSE_SCHEMA,
            build_maiagent_category_schema(_CATEGORY_RESPONSE_SCHEMA),
        )

    def test_exact_top_level_content_proposal_reaches_classifier_with_null_subtype(self):
        record = _record(body="The agency awarded a contract to Example Rail Ltd.")
        proposal = _proposal(record, category_id=CategoryId.PROCUREMENT)
        proposal["subtype"] = None
        transport = _RecordedMaiAgentTransport(MaiAgentHttpResponse(200, _maiagent_body(proposal)))

        result = Classifier(
            MaiAgentCategorySemanticProvider(_maiagent_config(), transport=transport)
        ).classify(_group(record), (record,))

        self.assertEqual(result.category_state, CategoryState.CATEGORY_ASSIGNED)
        self.assertEqual(result.primary_category_id, CategoryId.PROCUREMENT)
        self.assertIsNone(result.subtype)
        self.assertEqual(result.provenance["provider_identifier"], MAIAGENT_CATEGORY_PROVIDER_IDENTIFIER)
        self.assertEqual(result.provenance["schema_version"], "category-proposal-v6")
        self.assertEqual(result.provenance["prompt_version"], MAIAGENT_CATEGORY_MESSAGE_VERSION)
        self.assertEqual(
            result.provenance["helper_version"],
            MAIAGENT_CATEGORY_SEMANTIC_HELPER_VERSION,
        )
        self.assertEqual(len(result.provenance["validated_support_spans"]), 1)
        self.assertNotIn("validated_conflict_spans", result.provenance)
        self.assertEqual(len(transport.calls), 1)

    def test_missing_content_non_string_content_and_invalid_json_fail_closed(self):
        record = _record()
        proposal_json = json.dumps(_proposal(record))
        invalid_bodies = (
            json.dumps({"answer": proposal_json}).encode(),
            json.dumps({"content": {"proposal": _proposal(record)}}).encode(),
            json.dumps({"content": "not JSON"}).encode(),
        )
        # RC-6: an unparseable envelope is a technical failure (one identical
        # retry), never CATEGORY_UNRESOLVED; it is disclosed as a technical gap.
        for body in invalid_bodies:
            with self.subTest(body=body):
                transport = _RecordedMaiAgentTransport(MaiAgentHttpResponse(200, body))
                with self.assertRaises(SemanticProviderTechnicalFailure) as raised:
                    Classifier(
                        MaiAgentCategorySemanticProvider(_maiagent_config(), transport=transport)
                    ).classify(_group(record), (record,))
                self.assertEqual(raised.exception.failure_class, "UNPARSEABLE_RESPONSE")
                self.assertEqual(len(transport.calls), 2)

    def test_alternate_envelopes_are_not_searched_or_used_as_fallback(self):
        record = _record()
        proposal_json = json.dumps(_proposal(record))
        envelopes = (
            {"message": {"content": proposal_json}},
            {"data": {"content": proposal_json}},
            {"result": proposal_json},
            {"output": proposal_json},
            {"contentPayload": proposal_json},
        )
        for envelope in envelopes:
            with self.subTest(envelope=envelope):
                transport = _RecordedMaiAgentTransport(
                    MaiAgentHttpResponse(200, json.dumps(envelope).encode())
                )
                # Alternate envelopes are never searched; the response is
                # unparseable under the confirmed envelope contract (RC-6).
                with self.assertRaises(SemanticProviderTechnicalFailure):
                    Classifier(
                        MaiAgentCategorySemanticProvider(_maiagent_config(), transport=transport)
                    ).classify(_group(record), (record,))
                self.assertEqual(len(transport.calls), 2)

    def test_non_200_and_transport_errors_fail_closed_without_retry_or_secret_provenance(self):
        record = _record()
        secret = "synthetic-test-api-key"
        chatbot_id = "synthetic-category-chatbot-id"
        # RC-6: 401/403/404 are configuration failures (run stops, no retry);
        # another non-200 status is a non-transient technical failure (no
        # retry); a connection error is retried once.  None becomes a Category
        # decision and no secret is exposed.
        cases = (
            (_RecordedMaiAgentTransport(MaiAgentHttpResponse(403, b"permission denied")), SemanticProviderConfigurationFailure, 1),
            (_RecordedMaiAgentTransport(MaiAgentHttpResponse(201, _maiagent_body(_proposal(record)))), SemanticProviderTechnicalFailure, 1),
            (_RecordedMaiAgentTransport(error=RuntimeError(f"{secret} {chatbot_id}")), SemanticProviderTechnicalFailure, 2),
        )
        for transport, expected, calls in cases:
            with self.subTest(expected=expected.__name__, calls=calls):
                with self.assertRaises(expected) as raised:
                    Classifier(
                        MaiAgentCategorySemanticProvider(_maiagent_config(), transport=transport)
                    ).classify(_group(record), (record,))
                self.assertNotIn(secret, str(raised.exception))
                self.assertNotIn(chatbot_id, str(raised.exception))
                self.assertEqual(len(transport.calls), calls)

    def test_category_configuration_merges_dotenv_and_process_env_with_process_precedence(self):
        dotenv_values = {
            "MAIAGENT_API_BASE": "https://dotenv.example",
            "MAIAGENT_API_KEY": "dotenv-key",
            "MAIAGENT_STRUCTURED_HELPER_CHATBOT_ID": "dotenv-helper-id",
            "MAIAGENT_CHATBOT_ID": "writer-only-id",
        }
        with patch.dict("sys.modules", {"dotenv": _dotenv_module(dotenv_values)}):
            config = MaiAgentCategorySemanticProviderConfig.from_environment(
                {"MAIAGENT_API_KEY": "process-key"}, dotenv_path="repo/.env"
            )

        self.assertIsNotNone(config)
        self.assertEqual(config.api_base, "https://dotenv.example")
        self.assertEqual(config.api_key, "process-key")
        self.assertEqual(config.chatbot_id, "dotenv-helper-id")

    def test_writer_chatbot_variable_is_never_a_category_configuration_fallback(self):
        dotenv_values = {
            "MAIAGENT_API_BASE": "https://dotenv.example",
            "MAIAGENT_API_KEY": "dotenv-key",
            "MAIAGENT_CHATBOT_ID": "writer-only-id",
        }
        with patch.dict("sys.modules", {"dotenv": _dotenv_module(dotenv_values)}):
            config = MaiAgentCategorySemanticProviderConfig.from_environment(
                {}, dotenv_path="repo/.env"
            )
        self.assertIsNone(config)

    def test_missing_category_configuration_builds_fail_closed_classifier(self):
        transport = _RecordedMaiAgentTransport(
            MaiAgentHttpResponse(200, _maiagent_body(_proposal(_record())))
        )
        with patch.dict("sys.modules", {"dotenv": _dotenv_module({})}):
            classifier = build_maiagent_category_classifier(
                transport=transport,
                environ={"MAIAGENT_CHATBOT_ID": "writer-only-id"},
                dotenv_path="repo/.env",
            )
        record = _record()
        result = classifier.classify(_group(record), (record,))

        self.assertEqual(result.category_state, CategoryState.CATEGORY_UNRESOLVED)
        self.assertEqual(
            result.category_resolution_reason,
            CategoryResolutionReason.SEMANTIC_HELPER_UNAVAILABLE,
        )
        self.assertEqual(transport.calls, [])

    def test_provider_provenance_omits_credentials_and_chatbot_id(self):
        record = _record()
        transport = _RecordedMaiAgentTransport(
            MaiAgentHttpResponse(200, _maiagent_body(_proposal(record)))
        )
        result = build_maiagent_category_classifier(
            _maiagent_config(), transport=transport
        ).classify(_group(record), (record,))

        provenance_text = json.dumps(dict(result.provenance))
        self.assertNotIn(_maiagent_config().api_key, provenance_text)
        self.assertNotIn(_maiagent_config().chatbot_id, provenance_text)
        self.assertEqual(result.provenance["provider_identifier"], MAIAGENT_CATEGORY_PROVIDER_IDENTIFIER)
        self.assertEqual(result.provenance["schema_version"], CATEGORY_SEMANTIC_SCHEMA_VERSION)
        self.assertEqual(len(transport.calls), 1)

    def test_maiagent_schema_projection_is_derived_from_the_authoritative_schema(self):
        self.assertEqual(CATEGORY_SEMANTIC_SCHEMA_VERSION, "category-proposal-v6")
        self.assertEqual(
            _MAIAGENT_CATEGORY_RESPONSE_SCHEMA,
            build_maiagent_category_schema(_CATEGORY_RESPONSE_SCHEMA),
        )


class SingleCategoryProviderTests(unittest.TestCase):
    """F5: the MaiAgent Structured Helper is the only Category provider (AGENTS section 11)."""

    def test_no_second_category_provider_is_shipped(self):
        for name in ("CategorySemanticProvider", "CategorySemanticProviderConfig", "build_category_classifier",
                     "UrllibJsonTransport", "JsonHttpTransport"):
            self.assertFalse(hasattr(category_semantic_provider_module, name), name)
        source_root = Path(category_semantic_provider_module.__file__).parent
        for source in source_root.glob("*.py"):
            text = source.read_text(encoding="utf-8")
            self.assertNotIn("CATEGORY_SEMANTIC_API_URL", text, source.name)

    def test_production_composes_the_maiagent_category_classifier(self):
        runner = Path(category_semantic_provider_module.__file__).with_name("production_runner.py").read_text(encoding="utf-8")
        self.assertIn("build_maiagent_category_classifier(", runner)

if __name__ == "__main__":
    unittest.main()
