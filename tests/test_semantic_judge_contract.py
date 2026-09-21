from __future__ import annotations

import unittest

from src.weekly_report.contracts import (
    CanonicalCandidate,
    EvidenceState,
    FetchedSource,
    RejectReason,
)
from src.weekly_report.evidence_service import EvidenceService
from src.weekly_report.semantic_judge import JudgeMetadata


def _candidate(**overrides) -> CanonicalCandidate:
    values = {
        "candidate_id": "C1",
        "title": "Metro launches predictive maintenance platform",
        "url": "https://source.test/article/predictive-maintenance",
        "publisher": "Fixture Publisher",
        "published_at": "2026-09-15T10:00:00Z",
        "discovery_intent": "technology",
        "search_snippet": "The operator launched a predictive platform.",
    }
    values.update(overrides)
    return CanonicalCandidate(**values)


class _FixtureFetcher:
    def __init__(self, source):
        self.source = source

    def __call__(self, _url):
        return self.source


class _RecordingJudge:
    metadata = JudgeMetadata(
        model_identifier="test-model",
        prompt_version="test-prompt-v1",
        schema_version="test-schema-v1",
    )

    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = 0
        self.requests = []

    def __call__(self, request):
        self.calls += 1
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.response(request) if callable(self.response) else self.response


def _same_event_response(request):
    body = request.principal_body_segments[0].text
    return {
        "relation": "SAME_EVENT",
        "support_spans": [
            {"segment_id": "body-0001", "start": 0, "end": len(body)}
        ],
        "conflict_spans": [],
        "explanation": "The principal body describes the Candidate event.",
    }


def _different_event_response(_request):
    return {
        "relation": "DIFFERENT_EVENT",
        "support_spans": [],
        "conflict_spans": [
            {"segment_id": "body-0001", "start": 0, "end": 1}
        ],
        "explanation": "The principal body describes a different event.",
    }


def _service(body, judge, *, title=None, url=None):
    candidate = _candidate(
        title=title or _candidate().title,
        url=url or _candidate().url,
    )
    html = f"<html><body><h1>{candidate.title}</h1><article><p>{body}</p></article></body></html>"
    source = FetchedSource(
        url=candidate.url,
        content=html,
        content_type="text/html",
    )
    return EvidenceService(
        _FixtureFetcher(source),
        semantic_judge=judge,
    ), candidate


class SemanticJudgeContractTests(unittest.TestCase):
    def test_same_event_with_valid_body_support_is_ready(self):
        judge = _RecordingJudge(response=_same_event_response)
        service, candidate = _service(
            "The operator introduced the platform after trials and will deploy it across the network.",
            judge,
        )

        result = service.evaluate(candidate)

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(judge.calls, 1)
        self.assertEqual(result.provenance["raw_relation"], "SAME_EVENT")
        self.assertEqual(result.provenance["response_validation_result"], "valid")
        self.assertEqual(
            result.provenance["EvidenceService_final_decision"],
            EvidenceState.READY.value,
        )

    def test_judge_input_excludes_search_metadata(self):
        judge = _RecordingJudge(response=_same_event_response)
        service, candidate = _service("The operator introduced the platform after trials.", judge)

        service.evaluate(candidate)

        payload = judge.requests[0].as_payload()
        self.assertEqual(set(payload), {
            "candidate_id",
            "candidate_title",
            "document_level_headlines",
            "principal_body_segments",
        })
        self.assertNotIn(candidate.search_snippet, str(payload))
        self.assertNotIn(candidate.publisher, str(payload))
        self.assertNotIn(candidate.url, str(payload))

    def test_judge_input_excludes_secondary_headlines(self):
        candidate = _candidate()
        judge = _RecordingJudge(response=_same_event_response)
        html = (
            f"<html><body><h1>{candidate.title}</h1><main>"
            "<h2>Related section card</h2>"
            "<p>The operator introduced the platform after trials and will deploy it across the network.</p>"
            "</main></body></html>"
        )
        source = FetchedSource(
            url=candidate.url,
            content=html,
            content_type="text/html",
        )
        EvidenceService(
            _FixtureFetcher(source),
            semantic_judge=judge,
        ).evaluate(candidate)

        self.assertEqual(judge.calls, 1)
        self.assertEqual(judge.requests[0].document_level_headlines, (candidate.title,))

    def test_same_event_without_support_span_is_rejected(self):
        judge = _RecordingJudge(
            response=lambda _request: {
                "relation": "SAME_EVENT",
                "support_spans": [],
                "conflict_spans": [],
                "explanation": "No grounded span.",
            }
        )
        service, candidate = _service("The operator introduced the platform after trials.", judge)

        result = service.evaluate(candidate)

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.SOURCE_PAGE_MISMATCH)
        self.assertEqual(judge.calls, 1)
        self.assertEqual(result.provenance["response_validation_result"], "invalid")

    def test_same_event_with_unknown_segment_is_rejected(self):
        judge = _RecordingJudge(
            response=lambda _request: {
                "relation": "SAME_EVENT",
                "support_spans": [{"segment_id": "missing", "start": 0, "end": 1}],
                "conflict_spans": [],
                "explanation": "Invalid segment.",
            }
        )
        service, candidate = _service("The operator introduced the platform after trials.", judge)

        result = service.evaluate(candidate)

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(judge.calls, 1)

    def test_same_event_with_out_of_range_span_is_rejected(self):
        judge = _RecordingJudge(
            response=lambda _request: {
                "relation": "SAME_EVENT",
                "support_spans": [{"segment_id": "body-0001", "start": 0, "end": 99999}],
                "conflict_spans": [],
                "explanation": "Invalid boundary.",
            }
        )
        service, candidate = _service("The operator introduced the platform after trials.", judge)

        result = service.evaluate(candidate)

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(judge.calls, 1)

    def test_different_event_is_rejected_with_conflict_diagnostics(self):
        judge = _RecordingJudge(response=_different_event_response)
        service, candidate = _service(
            "The operator reported annual ridership increased after fare policy changes.",
            judge,
        )

        result = service.evaluate(candidate)

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.SOURCE_PAGE_MISMATCH)
        self.assertEqual(judge.calls, 1)
        self.assertEqual(len(result.provenance["validated_conflict_spans"]), 1)

    def test_uncertain_is_rejected_without_retry(self):
        judge = _RecordingJudge(
            response={
                "relation": "UNCERTAIN",
                "support_spans": [],
                "conflict_spans": [],
                "explanation": "Insufficient semantic certainty.",
            }
        )
        service, candidate = _service("The operator introduced the platform after trials.", judge)

        result = service.evaluate(candidate)

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(judge.calls, 1)

    def test_timeout_is_rejected_without_retry(self):
        judge = _RecordingJudge(error=TimeoutError("judge timed out"))
        service, candidate = _service("The operator introduced the platform after trials.", judge)

        result = service.evaluate(candidate)

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(judge.calls, 1)
        self.assertEqual(result.provenance["response_validation_result"], "timeout")

    def test_provider_exception_is_rejected_without_retry(self):
        judge = _RecordingJudge(error=RuntimeError("provider unavailable"))
        service, candidate = _service("The operator introduced the platform after trials.", judge)

        result = service.evaluate(candidate)

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(judge.calls, 1)
        self.assertEqual(result.provenance["response_validation_result"], "transport_error")

    def test_malformed_response_is_rejected_without_repair_or_retry(self):
        judge = _RecordingJudge(
            response={
                "relation": "SAME_EVENT",
                "support_spans": [],
                "conflict_spans": [],
                "explanation": "Missing required support.",
                "unexpected": True,
            }
        )
        service, candidate = _service("The operator introduced the platform after trials.", judge)

        result = service.evaluate(candidate)

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(judge.calls, 1)
        self.assertEqual(result.provenance["response_validation_result"], "invalid")

    def test_unconfigured_judge_rejects_without_deterministic_fallback(self):
        service, candidate = _service("The operator introduced the platform after trials.", None)

        result = service.evaluate(candidate)

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.SOURCE_PAGE_MISMATCH)
        self.assertEqual(result.provenance["response_validation_result"], "not_configured")

    def test_exact_h1_cannot_bypass_unconfigured_judge(self):
        service, candidate = _service(
            "The operator introduced the platform after trials.",
            None,
            title="Metro launches predictive maintenance platform",
        )

        result = service.evaluate(candidate)

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.provenance["error_type"], "SemanticJudgeNotConfigured")

    def test_cross_language_same_event_uses_only_judge_result(self):
        title = "Le métro lance une plateforme de maintenance prédictive"
        judge = _RecordingJudge(response=_same_event_response)
        service, candidate = _service(
            "L'opérateur a introduit la plateforme après des essais et la déploiera sur le réseau.",
            judge,
            title=title,
        )

        result = service.evaluate(candidate)

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(judge.calls, 1)

    def test_wrong_body_with_exact_h1_follows_judge(self):
        judge = _RecordingJudge(response=_different_event_response)
        service, candidate = _service(
            "The operator reported annual ridership increased after fare policy changes.",
            judge,
        )

        result = service.evaluate(candidate)

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.SOURCE_PAGE_MISMATCH)
        self.assertEqual(judge.calls, 1)

    def test_unicode_offsets_are_code_point_offsets(self):
        judge = _RecordingJudge(response=_same_event_response)
        service, candidate = _service(
            "東京メトロは平台を導入した。",
            judge,
            title="東京メトロ、新型保守平台を導入",
        )

        result = service.evaluate(candidate)

        self.assertEqual(result.state, EvidenceState.READY)
        span = result.provenance["validated_support_spans"][0]
        self.assertEqual(span["end"], len(result.substantive_content))

    def test_title_only_rejects_before_judge(self):
        judge = _RecordingJudge(response=_same_event_response)
        candidate = _candidate()
        source = FetchedSource(
            url=candidate.url,
            content=f"<html><head><title>{candidate.title}</title></head><body></body></html>",
            content_type="text/html",
        )
        result = EvidenceService(
            _FixtureFetcher(source),
            semantic_judge=judge,
        ).evaluate(candidate)

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.TITLE_ONLY)
        self.assertEqual(judge.calls, 0)

    def test_feed_rejects_before_judge(self):
        judge = _RecordingJudge(response=_same_event_response)
        candidate = _candidate(url="https://source.test/news")
        source = FetchedSource(
            url=candidate.url,
            content="<rss><channel><item><title>Story</title></item></channel></rss>",
            content_type="application/rss+xml",
        )
        result = EvidenceService(
            _FixtureFetcher(source),
            semantic_judge=judge,
        ).evaluate(candidate)

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.SOURCE_PAGE_MISMATCH)
        self.assertEqual(judge.calls, 0)

    def test_invalid_provenance_rejects_before_judge(self):
        judge = _RecordingJudge(response=_same_event_response)
        candidate = _candidate()
        source = FetchedSource(
            url="https://other.test/article",
            content="<html><body><article>Substantive content.</article></body></html>",
            content_type="text/html",
        )
        result = EvidenceService(
            _FixtureFetcher(source),
            semantic_judge=judge,
        ).evaluate(candidate)

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.SOURCE_PAGE_MISMATCH)
        self.assertEqual(judge.calls, 0)


if __name__ == "__main__":
    unittest.main()
