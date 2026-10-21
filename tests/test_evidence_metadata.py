from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace
from unittest.mock import patch

from src.weekly_report.contracts import (
    CanonicalCandidate,
    EvidenceResult,
    EvidenceState,
    EventIdentityFacts,
    EventIdentityRecord,
    FetchedSource,
    IdentityMetadataSupport,
    RejectReason,
    ScopeResult,
    ScopeState,
    TemporalResult,
)
from src.weekly_report.evidence_metadata import (
    EvidenceMetadataRequest,
    InvalidEvidenceMetadataResponse,
    validate_evidence_metadata_response,
)
from src.weekly_report.evidence_service import EvidenceService
from src.weekly_report.evidence_document import (
    DocumentSegment,
    PrincipalDocumentStatus,
    StructuralAssessment,
)
from src.weekly_report.event_identity import EventIdentity
from src.weekly_report.semantic_judge import PrincipalBodySegment


def _request(*segments: tuple[str, str]) -> EvidenceMetadataRequest:
    return EvidenceMetadataRequest(
        "C1", tuple(PrincipalBodySegment(segment_id, text) for segment_id, text in segments)
    )


def _proposal(field_name: str, value: str, segment_id: str) -> dict[str, object]:
    return {"field_name": field_name, "value": value, "segment_id": segment_id}


class MetadataContractTests(unittest.TestCase):
    def test_support_is_frozen_and_validates_offsets(self):
        support = IdentityMetadataSupport("country", 2, 5)
        self.assertEqual((support.field_name, support.start, support.end), ("country", 2, 5))
        with self.assertRaises(FrozenInstanceError):
            support.start = 3  # type: ignore[misc]
        with self.assertRaises((TypeError, ValueError)):
            IdentityMetadataSupport("city", 0, 1)  # type: ignore[arg-type]
        with self.assertRaises((TypeError, ValueError)):
            IdentityMetadataSupport("country", True, 1)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            IdentityMetadataSupport("country", 4, 4)

    def test_identity_facts_mapping_deserializes_typed_support(self):
        facts = EventIdentityFacts.from_mapping(
            {
                "country": "Taiwan",
                "transit_system_name": "Metro",
                "location": "Taipei",
                "metadata_support": [
                    {"field_name": "country", "start": 0, "end": 6},
                    {"field_name": "transit_system_name", "start": 7, "end": 12},
                    {"field_name": "location", "start": 13, "end": 19},
                ],
            }
        )
        self.assertIsInstance(facts.metadata_support[0], IdentityMetadataSupport)
        with self.assertRaises((TypeError, ValueError)):
            EventIdentityFacts.from_mapping(
                {"metadata_support": [{"field_name": "country", "start": 0}]}
            )

    def test_ready_parent_requires_exact_support_and_rejected_cannot_expose_it(self):
        with self.assertRaises(ValueError):
            EvidenceResult(
                "C1",
                EvidenceState.READY,
                substantive_content="A source from Taiwan.",
                identity_facts=EventIdentityFacts(country="Taiwan"),
            )
        ready = EvidenceResult(
            "C1",
            EvidenceState.READY,
            substantive_content="A source from Taiwan at Taipei.",
            identity_facts=EventIdentityFacts(
                country="Taiwan",
                location="Taipei",
                metadata_support=(
                    IdentityMetadataSupport("country", 14, 20),
                    IdentityMetadataSupport("location", 24, 30),
                ),
            ),
        )
        self.assertEqual(ready.identity_facts.country, "Taiwan")
        with self.assertRaises(ValueError):
            EvidenceResult(
                "C1",
                EvidenceState.REJECTED,
                reject_reason=RejectReason.CONTENT_UNAVAILABLE,
                identity_facts=EventIdentityFacts(country="Taiwan"),
            )
        with self.assertRaises(ValueError):
            EvidenceResult(
                "C1",
                EvidenceState.REJECTED,
                reject_reason=RejectReason.CONTENT_UNAVAILABLE,
                identity_facts=EventIdentityFacts(transit_system_name="Taipei Metro"),
            )
        with self.assertRaises(ValueError):
            EvidenceResult(
                "C1",
                EvidenceState.REJECTED,
                reject_reason=RejectReason.CONTENT_UNAVAILABLE,
                identity_facts=EventIdentityFacts(
                    metadata_support=(IdentityMetadataSupport("location", 0, 1),)
                ),
            )
        legacy = EvidenceResult(
            "C1",
            EvidenceState.REJECTED,
            reject_reason=RejectReason.CONTENT_UNAVAILABLE,
            identity_facts=EventIdentityFacts(action="incident", location="Taipei"),
        )
        self.assertEqual(legacy.identity_facts.location, "Taipei")

    def test_validator_derives_unique_canonical_span_and_consolidates_duplicates(self):
        request = _request(("s1", "Taiwan Metro opened in Taipei."))
        empty = validate_evidence_metadata_response({"observations": []}, request)
        self.assertEqual(empty.observations, ())
        raw = {"observations": [_proposal("country", "Taiwan", "s1"), _proposal("country", "Taiwan", "s1")]}
        extraction = validate_evidence_metadata_response(raw, request)
        self.assertEqual(len(extraction.observations), 1)
        self.assertEqual(extraction.observations[0].support_spans[0].as_mapping(), {"segment_id": "s1", "start": 0, "end": 6})

    def test_validator_rejects_provider_offsets_and_strict_schema_errors(self):
        # Malformed response or observation shapes still invalidate the whole
        # proposal; provider offsets are never accepted.
        request = _request(("s1", "Taiwan Metro opened in Taipei."))
        cases = [
            {},
            {"observations": "bad"},
            {"observations": [{"field_name": "country", "value": "Taiwan", "support_spans": []}]},
            {"observations": [{"field_name": "country", "value": "Taiwan", "segment_id": "s1", "start": 0}]},
            {"observations": [{"field_name": "country", "value": "Taiwan", "segment_id": "s1", "end": 6}]},
            {"observations": [{"field_name": "city", "value": "Taiwan", "segment_id": "s1"}]},
        ]
        for raw in cases:
            with self.subTest(raw=raw), self.assertRaises(InvalidEvidenceMetadataResponse):
                validate_evidence_metadata_response(raw, request)

    def test_value_failures_invalidate_only_their_field(self):
        # RC-3: field-level validation; other valid fields are retained.
        request = _request(("s1", "Taiwan Metro opened in Taipei."))
        for proposal, reason in (
            (_proposal("country", "Taiwan", "unknown"), "UNKNOWN_SEGMENT"),
            (_proposal("country", "   ", "s1"), "VALUE_INVALID"),
            (_proposal("country", "Korea", "s1"), "VALUE_NOT_IN_SEGMENT"),
        ):
            with self.subTest(reason=reason):
                extraction = validate_evidence_metadata_response(
                    {"observations": [proposal, _proposal("location", "Taipei", "s1")]},
                    request,
                )
                self.assertEqual([item.field_name for item in extraction.observations], ["location"])
                self.assertEqual(
                    [(item.field_name, item.reason) for item in extraction.field_diagnostics],
                    [("country", reason)],
                )
        with self.assertRaises(ValueError):
            EvidenceMetadataRequest("C1", (PrincipalBodySegment("dup", "Taiwan"), PrincipalBodySegment("dup", "Taiwan")))

    def test_validator_records_every_exact_occurrence_without_selecting_one(self):
        # RC-3 (EXACT_TEXT_ALL_OCCURRENCES): repeated identical values are
        # valid and every occurrence, including overlaps, is recorded.
        for name, value, text, expected in (
            ("duplicate", "Japan", "Japan Japan", [(0, 5), (6, 11)]),
            ("overlap", "aa", "aaaa", [(0, 2), (1, 3), (2, 4)]),
        ):
            with self.subTest(case=name):
                extraction = validate_evidence_metadata_response(
                    {"observations": [_proposal("country", value, "s1")]},
                    _request(("s1", text)),
                )
                self.assertEqual(
                    [(span.start, span.end) for span in extraction.observations[0].support_spans],
                    expected,
                )

    def test_validator_rejects_normalization_or_fuzzy_matching(self):
        cases = (
            ("zero", "Korea", "Taiwan Metro"),
            ("whitespace", " Japan", "Japan"),
            ("case", "japan", "Japan"),
            ("fuzzy", "Jpn", "Japan"),
        )
        for name, value, text in cases:
            with self.subTest(case=name):
                extraction = validate_evidence_metadata_response(
                    {"observations": [_proposal("country", value, "s1")]},
                    _request(("s1", text)),
                )
                self.assertEqual(extraction.observations, ())
                self.assertEqual(
                    [(item.field_name, item.reason) for item in extraction.field_diagnostics],
                    [("country", "VALUE_NOT_IN_SEGMENT")],
                )

    def test_validator_records_distinct_values_as_field_conflict_without_choosing(self):
        request = _request(("s1", "Taiwan and Japan in Taipei"))
        extraction = validate_evidence_metadata_response(
            {
                "observations": [
                    _proposal("country", "Taiwan", "s1"),
                    _proposal("country", "Japan", "s1"),
                    _proposal("location", "Taipei", "s1"),
                ]
            },
            request,
        )
        self.assertEqual([item.field_name for item in extraction.observations], ["location"])
        self.assertEqual(
            [(item.field_name, item.reason, item.proposed_values) for item in extraction.field_diagnostics],
            [("country", "SAME_SOURCE_DISTINCT_VALUES", ("Taiwan", "Japan"))],
        )

    def test_validator_preserves_segment_specific_support_and_does_not_accept_ambiguous_segment(self):
        request = _request(("s1", "Taiwan Metro"), ("s2", "Japan Metro"))
        extraction = validate_evidence_metadata_response(
            {"observations": [_proposal("country", "Taiwan", "s1"), _proposal("location", "Japan", "s2")]},
            request,
        )
        self.assertEqual(
            tuple(span.as_mapping() for span in extraction.observations[0].support_spans),
            ({"segment_id": "s1", "start": 0, "end": 6},),
        )
        unknown = validate_evidence_metadata_response(
            {"observations": [_proposal("country", "Taiwan", "unknown")]},
            request,
        )
        self.assertEqual(unknown.observations, ())
        self.assertEqual(
            [(item.field_name, item.reason) for item in unknown.field_diagnostics],
            [("country", "UNKNOWN_SEGMENT")],
        )

    def test_validator_derives_diagnostic_sentence_offsets_in_python(self):
        text = "Country: Japan. Transit system: Sakura Metro. Location: Sakura City."
        request = _request(("META-DIAG-SEG-001", text))
        extraction = validate_evidence_metadata_response(
            {
                "observations": [
                    _proposal("country", "Japan", "META-DIAG-SEG-001"),
                    _proposal("transit_system_name", "Sakura Metro", "META-DIAG-SEG-001"),
                    _proposal("location", "Sakura City", "META-DIAG-SEG-001"),
                ]
            },
            request,
        )
        self.assertEqual(
            [
                (observation.field_name, observation.support_spans[0].start, observation.support_spans[0].end)
                for observation in extraction.observations
            ],
            [("country", 9, 14), ("transit_system_name", 32, 44), ("location", 56, 67)],
        )


class _SameEventJudge:
    def __call__(self, request):
        return {
            "relation": "SAME_EVENT",
            "support_evidence": [
                {"segment_id": segment.segment_id, "exact_quote": segment.text}
                for segment in request.principal_body_segments
            ],
            "conflict_evidence": [],
            "explanation": "grounded",
        }


class _MetadataExtractor:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        if self.error:
            raise self.error
        text = request.principal_body_segments[0].text
        return self.response(text)


class _RequestMetadataExtractor:
    def __init__(self, response):
        self.response = response
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        return self.response(request)


def _service(extractor=None, html=None):
    body = html or (
        "<html><head><title>Principal headline</title></head>"
        "<body><article><h1>Actual source headline</h1>"
        "<p>Taiwan Metro opened at Taipei Central.</p></article></body></html>"
    )
    source = FetchedSource("https://source.test/article", body)
    return EvidenceService(
        lambda _url: source,
        semantic_judge=_SameEventJudge(),
        metadata_extractor=extractor,
    )


class EvidenceMetadataServiceTests(unittest.TestCase):
    def test_valid_metadata_is_authoritative_and_request_excludes_candidate_context(self):
        def response(text):
            return {
                "observations": [
                    _proposal("country", "Taiwan", "body-0001"),
                    _proposal("transit_system_name", "Taiwan Metro", "body-0001"),
                    _proposal("location", "Taipei Central", "body-0001"),
                ]
            }

        extractor = _MetadataExtractor(response=response)
        result = _service(extractor).evaluate(
            CanonicalCandidate("C1", "Discovery title says Japan", "https://source.test/article", publisher="Discovery")
        )
        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(result.identity_facts.country, "Taiwan")
        self.assertEqual(result.identity_facts.transit_system_name, "Taiwan Metro")
        self.assertEqual(result.identity_facts.location, "Taipei Central")
        resolution = result.identity_facts.region_resolution
        self.assertEqual(
            (resolution.basis.value, resolution.region_id, resolution.source_field, resolution.source_value),
            ("SOURCE_STATED", "TW", "country", "Taiwan"),
        )
        self.assertEqual(result.provenance["metadata_extraction_status"], "valid_metadata")
        self.assertEqual(
            result.provenance["principal_source_headlines"],
            ["Principal headline", "Actual source headline"],
        )
        request = extractor.requests[0]
        self.assertEqual(request.candidate_id, "C1")
        self.assertEqual([segment.segment_id for segment in request.principal_body_segments], ["body-0001"])
        self.assertEqual(len(extractor.requests), 1)
        self.assertFalse(hasattr(request, "title"))
        self.assertFalse(hasattr(request, "publisher"))

    def test_not_configured_zero_timeout_transport_and_malformed_keep_ready(self):
        for extractor, expected in (
            (None, "not_configured"),
            (_MetadataExtractor(error=TimeoutError()), "timeout"),
            (_MetadataExtractor(error=RuntimeError("secret")), "transport_error"),
            (_MetadataExtractor(response=lambda _text: {"observations": [{"bad": 1}]}), "invalid_response"),
        ):
            with self.subTest(expected=expected):
                result = _service(extractor).evaluate(
                    CanonicalCandidate("C1", "Title", "https://source.test/article")
                )
                self.assertEqual(result.state, EvidenceState.READY)
                self.assertEqual(result.provenance["metadata_extraction_status"], expected)
                self.assertIsNone(result.identity_facts)
                self.assertNotIn("secret", str(result.provenance))

    def test_valid_zero_metadata_is_recorded_as_not_stated(self):
        # RC-4: a valid empty proposal means the source states no geography;
        # it is recorded as NOT_STATED, never as an established country.
        result = _service(_MetadataExtractor(response=lambda _text: {"observations": []})).evaluate(
            CanonicalCandidate("C1", "Title", "https://source.test/article")
        )
        self.assertEqual(result.provenance["metadata_extraction_status"], "valid_zero_metadata")
        self.assertIsNone(result.identity_facts.country)
        self.assertEqual(result.identity_facts.region_resolution.basis.value, "NOT_STATED")

    def test_generic_mode_word_is_not_a_transit_system_name(self):
        # RC-4: a mode word ("Metro") or a city is never stored as a system name.
        def response(_text):
            return {
                "observations": [
                    _proposal("transit_system_name", "Metro", "body-0001"),
                    _proposal("location", "Taipei Central", "body-0001"),
                ]
            }

        result = _service(_MetadataExtractor(response=response)).evaluate(
            CanonicalCandidate("C1", "Title", "https://source.test/article")
        )
        self.assertIsNone(result.identity_facts.transit_system_name)
        self.assertEqual(result.identity_facts.unresolved_metadata_fields, ("transit_system_name",))
        self.assertEqual(result.provenance["metadata_extraction_status"], "partial_metadata")

    def test_metadata_diagnostics_are_flat_and_provider_errors_are_safe(self):
        extractor = _MetadataExtractor(error=RuntimeError("secret-provider-message"))
        result = _service(extractor).evaluate(
            CanonicalCandidate("C1", "Title", "https://source.test/article")
        )
        self.assertEqual(
            {key for key in result.provenance if key.startswith("metadata_extraction")},
            {"metadata_extraction_status", "metadata_extraction_detail"},
        )
        self.assertNotIn("secret-provider-message", str(result.provenance))
        self.assertEqual(len(extractor.requests), 1)

    def test_service_failure_matrix_is_single_call_and_fail_closed(self):
        text = "Taiwan Metro opened at Taipei Central."

        def distinct(_text):
            return {
                "observations": [
                    _proposal("country", "Taiwan", "body-0001"),
                    _proposal("country", "Taipei", "body-0001"),
                ]
            }

        def mixed(_text):
            return {
                "observations": [
                    _proposal("country", "Taiwan", "body-0001"),
                    _proposal("city", "Taipei", "body-0001"),
                ]
            }

        for extractor, status, detail in (
            (_MetadataExtractor(error=TimeoutError()), "timeout", ""),
            (_MetadataExtractor(error=RuntimeError("secret-provider-message")), "transport_error", ""),
            (_MetadataExtractor(response=lambda _text: {"bad": True}), "invalid_response", "schema_invalid"),
            (_MetadataExtractor(response=mixed), "invalid_response", "schema_invalid"),
        ):
            with self.subTest(status=status, detail=detail):
                result = _service(extractor).evaluate(
                    CanonicalCandidate("C1", "Title", "https://source.test/article")
                )
                self.assertEqual(result.state, EvidenceState.READY)
                self.assertIsNone(result.identity_facts)
                self.assertEqual(result.provenance["metadata_extraction_status"], status)
                self.assertEqual(result.provenance["metadata_extraction_detail"], detail)
                self.assertEqual(len(extractor.requests), 1)
                self.assertNotIn("secret-provider-message", str(result.provenance))

        # RC-3: same-source distinct values are a recorded field conflict; the
        # other fields stay usable and no value is chosen.
        extractor = _MetadataExtractor(response=distinct)
        result = _service(extractor).evaluate(CanonicalCandidate("C1", "Title", "https://source.test/article"))
        self.assertEqual(result.provenance["metadata_extraction_status"], "partial_metadata")
        self.assertEqual(result.provenance["metadata_extraction_detail"], "country:UNRESOLVED")
        self.assertIsNone(result.identity_facts.country)
        self.assertEqual(result.identity_facts.region_resolution.basis.value, "UNRESOLVED")
        self.assertEqual(len(extractor.requests), 1)

    def test_service_level_multi_segment_mapping_uses_ordered_segments(self):
        assessment = StructuralAssessment(
            format="html",
            parse_status="ok",
            principal_document_status=PrincipalDocumentStatus.PRINCIPAL_DOCUMENT_ESTABLISHED,
            principal_document_identifier="article-1",
            principal_segment_ids=("body-0001", "body-0002"),
            principal_body_segments=(
                DocumentSegment("body-0001", "  Taiwan Metro"),
                DocumentSegment("body-0002", "opened at Taipei  ."),
            ),
            document_level_headlines=(),
            secondary_headlines=(),
            canonical_values=(),
        )

        def response(request):
            first, second = request.principal_body_segments
            return {
                "observations": [
                    _proposal("country", "Taiwan", first.segment_id),
                    _proposal("location", "Taipei", second.segment_id),
                ]
            }

        extractor = _RequestMetadataExtractor(response)
        with patch("src.weekly_report.evidence_service.assess_document", return_value=assessment):
            result = _service(extractor).evaluate(
                CanonicalCandidate("C1", "Discovery title", "https://source.test/article")
            )
        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual([segment.segment_id for segment in extractor.requests[0].principal_body_segments], ["body-0001", "body-0002"])
        self.assertEqual(result.identity_facts.country, "Taiwan")
        self.assertEqual(result.identity_facts.location, "Taipei")
        body = result.substantive_content
        expected_values = {"country": "Taiwan", "location": "Taipei"}
        for support in result.identity_facts.metadata_support:
            self.assertEqual(body[support.start:support.end], expected_values[support.field_name])
        self.assertEqual(body, "Taiwan Metro opened at Taipei  .")

    def test_service_level_span_mapping_failure_publishes_no_partial_metadata(self):
        assessment = SimpleNamespace(
            body_text="Taiwan Metro opened at Taipei  .",
            document_level_headlines=(),
            canonical_values=(),
            principal_document_status=PrincipalDocumentStatus.PRINCIPAL_DOCUMENT_ESTABLISHED,
            principal_body_segments=(DocumentSegment("body-0001", "Taiwan Metro opened at Taipei."),),
            source_date_facts=(),
            structural_conflict=False,
            reject_reason="",
            diagnostics={},
            as_provenance=lambda: {},
        )

        def response(request):
            segment = request.principal_body_segments[0]
            return {
                "observations": [
                    _proposal("country", "Taiwan", segment.segment_id),
                ]
            }

        extractor = _RequestMetadataExtractor(response)
        with patch("src.weekly_report.evidence_service.assess_document", return_value=assessment):
            result = _service(extractor).evaluate(
                CanonicalCandidate("C1", "Title", "https://source.test/article")
            )
        self.assertEqual(result.state, EvidenceState.READY)
        self.assertIsNone(result.identity_facts)
        self.assertEqual(result.provenance["metadata_extraction_status"], "invalid_response")
        self.assertEqual(result.provenance["metadata_extraction_detail"], "span_mapping_invalid")
        self.assertEqual(len(extractor.requests), 1)

    def test_discovery_title_and_publisher_are_not_metadata_authority(self):
        extractor = _MetadataExtractor(response=lambda _text: {"observations": []})
        result = _service(extractor).evaluate(
            CanonicalCandidate(
                "C1",
                "Japan Metro opens in Tokyo",
                "https://source.test/article",
                publisher="Japan Rail Authority",
                search_snippet="Japan system context",
            )
        )
        request = extractor.requests[0]
        # RC-4: discovery title "Japan" never becomes country; zero source
        # metadata is NOT_STATED.
        self.assertIsNone(result.identity_facts.country)
        self.assertEqual(result.identity_facts.region_resolution.basis.value, "NOT_STATED")
        self.assertFalse(hasattr(request, "title"))
        self.assertFalse(hasattr(request, "publisher"))
        self.assertFalse(hasattr(request, "search_snippet"))

    def test_empty_structural_headline_does_not_fallback_to_candidate_title(self):
        result = _service(
            _MetadataExtractor(response=lambda _text: {"observations": []}),
            html="<html><body><article><p>Authoritative factual body content.</p></article></body></html>",
        ).evaluate(CanonicalCandidate("C1", "Discovery title", "https://source.test/article"))
        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(result.provenance["principal_source_headlines"], [])

    def test_multiple_segments_use_exact_join_offset_translation(self):
        request = _request(("body-0001", "  Taiwan Metro"), ("body-0002", "opened at Taipei  ."))
        raw = {
            "observations": [
                _proposal("country", "Taiwan", "body-0001"),
                _proposal("location", "Taipei", "body-0002"),
            ]
        }
        extraction = validate_evidence_metadata_response(raw, request)
        from src.weekly_report.evidence_service import EvidenceService
        body = "  Taiwan Metro opened at Taipei  .".strip()
        facts = EvidenceService(lambda _url: None)._translate_metadata(extraction, request, body)
        self.assertEqual(body[facts.metadata_support[0].start:facts.metadata_support[0].end], "Taiwan")
        self.assertEqual(body[facts.metadata_support[1].start:facts.metadata_support[1].end], "Taipei")

    def test_rejected_candidate_never_invokes_metadata_extractor(self):
        extractor = _MetadataExtractor(response=lambda _text: {"observations": []})
        result = _service(extractor, html="<html><body></body></html>").evaluate(
            CanonicalCandidate("C1", "Title", "https://source.test/article")
        )
        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(extractor.requests, [])

    def test_event_identity_advisor_gets_ephemeral_pre_extension_projection(self):
        body = "The commissioning occurred in Taiwan for Metro at Taipei."
        support = (
            IdentityMetadataSupport("country", body.index("Taiwan"), body.index("Taiwan") + 6),
            IdentityMetadataSupport("transit_system_name", body.index("Metro"), body.index("Metro") + 5),
            IdentityMetadataSupport("location", body.index("Taipei"), body.index("Taipei") + 6),
        )
        authoritative = EventIdentityFacts(
            event_key="event-1",
            action="commissioning",
            lifecycle_step="service_entry",
            subject="line-4",
            asset="train-set-4",
            project="metro-modernisation",
            package="signalling-package",
            occurrence_context="approved commissioning",
            occurrence_date="2026-09-15",
            location="Taipei",
            non_identity_claims={"duration": "42 minutes"},
            evidence_references=("body:0-10",),
            country="Taiwan",
            transit_system_name="Metro",
            metadata_support=support,
        )
        left = EvidenceResult("L", EvidenceState.READY, substantive_content=body, identity_facts=authoritative)
        right_facts = replace(authoritative, action="entered_service")
        right = EvidenceResult("R", EvidenceState.READY, substantive_content=body, identity_facts=right_facts)
        records = [
            EventIdentityRecord(CanonicalCandidate("L", "L", "https://source.test/l"), left, ScopeResult("L", ScopeState.IN_SCOPE), TemporalResult("L", True)),
            EventIdentityRecord(CanonicalCandidate("R", "R", "https://source.test/r"), right, ScopeResult("R", ScopeState.IN_SCOPE), TemporalResult("R", True)),
        ]

        captured = []

        def advisor(request):
            captured.append(request)
            spans = [
                {"candidate_id": candidate_id, "role": role, "start": 0, "end": len(source_body)}
                for candidate_id, source_body in ((request.left_candidate_id, request.left_body), (request.right_candidate_id, request.right_body))
                for role in ("occurrence", "subject", "lifecycle")
            ]
            return {"relation": "SAME_EVENT", "support_spans": spans, "contradictions": [], "missing_support": []}

        result = EventIdentity(advisor).evaluate(records)
        self.assertEqual(len(result.groups), 1)
        for projected in (captured[0].left_identity_facts, captured[0].right_identity_facts):
            self.assertEqual(projected.event_key, "event-1")
            self.assertEqual(projected.action, "commissioning" if projected is captured[0].left_identity_facts else "entered_service")
            self.assertEqual(projected.lifecycle_step, "service_entry")
            self.assertEqual(projected.subject, "line-4")
            self.assertEqual(projected.asset, "train-set-4")
            self.assertEqual(projected.project, "metro-modernisation")
            self.assertEqual(projected.package, "signalling-package")
            self.assertEqual(projected.location, "Taipei")
            self.assertEqual(projected.occurrence_context, "approved commissioning")
            self.assertEqual(projected.occurrence_date, "2026-09-15")
            self.assertEqual(dict(projected.non_identity_claims), {"duration": "42 minutes"})
            self.assertEqual(projected.evidence_references, ("body:0-10",))
            self.assertIsNone(projected.country)
            self.assertIsNone(projected.transit_system_name)
            self.assertEqual(projected.metadata_support, ())
        self.assertEqual(records[0].evidence.identity_facts.country, "Taiwan")
        self.assertEqual(records[0].evidence.identity_facts.transit_system_name, "Metro")
        self.assertEqual(records[0].evidence.identity_facts.metadata_support, support)
        self.assertEqual(records[1].evidence.identity_facts.country, "Taiwan")
        self.assertEqual(records[1].evidence.identity_facts.transit_system_name, "Metro")
        self.assertEqual(records[1].evidence.identity_facts.metadata_support, support)


if __name__ == "__main__":
    unittest.main()
