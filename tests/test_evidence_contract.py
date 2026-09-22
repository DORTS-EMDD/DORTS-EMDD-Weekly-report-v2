"""Deterministic owner tests for the V2 Evidence boundary."""

from __future__ import annotations

import copy
import socket
import unittest
from unittest.mock import patch

from src.weekly_report.contracts import (
    CanonicalCandidate,
    EvidenceState,
    FetchedSource,
    RejectReason,
    SourceDateKind,
)
from src.weekly_report.evidence_service import (
    EvidenceService,
    _RecordingRedirectHandler,
    _UnsafeDestinationError,
)
from src.weekly_report.evidence_document import (
    PrincipalDocumentStatus,
    assess_document,
)
from src.weekly_report.semantic_judge import JudgeMetadata


def _candidate(**overrides) -> CanonicalCandidate:
    values = {
        "candidate_id": "C1",
        "title": "Metro operator commissions moving-block train control on Line 4",
        "url": "https://source.test/article/line-4-control",
        "publisher": "Fixture Publisher",
        "published_at": "2026-09-15T10:00:00Z",
        "discovery_intent": "technology",
        "search_snippet": "The metro commissioned a new train-control system.",
    }
    values.update(overrides)
    return CanonicalCandidate(**values)


class _FixtureFetcher:
    def __init__(self, source_or_error):
        self.source_or_error = source_or_error
        self.calls = []

    def __call__(self, url: str):
        self.calls.append(url)
        if isinstance(self.source_or_error, BaseException):
            raise self.source_or_error
        return self.source_or_error


class _MockHTTPResponse:
    def __init__(self, body: bytes, *, url: str, content_type: str):
        self._body = body
        self._url = url
        self.status = 200
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return self._body

    def geturl(self):
        return self._url


class _MockHTTPOpener:
    def __init__(self, response):
        self.response = response

    def open(self, request, timeout):
        return self.response


class _SameEventJudge:
    metadata = JudgeMetadata(
        model_identifier="test-model",
        prompt_version="test-prompt-v1",
        schema_version="test-schema-v1",
    )

    def __init__(self):
        self.calls = 0
        self.requests = []

    def __call__(self, request):
        self.calls += 1
        self.requests.append(request)
        body = request.principal_body_segments[0].text
        return {
            "relation": "SAME_EVENT",
            "support_spans": [
                {"segment_id": "body-0001", "start": 0, "end": len(body)}
            ],
            "conflict_spans": [],
            "explanation": "test support",
        }


class _DifferentEventJudge:
    metadata = _SameEventJudge.metadata

    def __init__(self):
        self.calls = 0

    def __call__(self, request):
        self.calls += 1
        body = request.principal_body_segments[0].text
        return {
            "relation": "DIFFERENT_EVENT",
            "support_spans": [],
            "conflict_spans": [
                {"segment_id": "body-0001", "start": 0, "end": len(body)}
            ],
            "explanation": "test mismatch",
        }


_AUTO_SAME_EVENT_JUDGE = object()


def _service(
    html: str,
    *,
    url: str | None = None,
    content_type: str = "text/html",
    judge=_AUTO_SAME_EVENT_JUDGE,
):
    source = FetchedSource(
        url=url or "https://source.test/article/line-4-control",
        content=html,
        content_type=content_type,
    )
    configured_judge = (
        _SameEventJudge() if judge is _AUTO_SAME_EVENT_JUDGE else judge
    )
    return EvidenceService(
        _FixtureFetcher(source),
        semantic_judge=configured_judge,
    )


class EvidenceContractTests(unittest.TestCase):
    def test_g01_title_only_is_rejected_without_downstream_fields(self):
        service = _service("<html><head><title>Metro operator commissions Line 4</title></head><body></body></html>")

        result = service.evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.TITLE_ONLY)
        self.assertEqual(result.substantive_content, "")

    def test_meta_description_only_is_not_substantive(self):
        service = _service(
            "<html><head><meta name='description' content='Metro operator commissions Line 4'></head>"
            "<body><nav>Home News Contact</nav></body></html>"
        )

        result = service.evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.INSUFFICIENT_SUBSTANCE)

    def test_search_snippet_only_cannot_be_promoted(self):
        service = _service("<html><head></head><body><nav>Search results</nav></body></html>")

        result = service.evaluate(_candidate(search_snippet="Metro operator commissions Line 4"))

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.TITLE_ONLY)

    def test_g02_homepage_is_wrong_landing_page(self):
        service = _service(
            "<html><body><nav>Home News Projects Contact</nav><main>Welcome to the operator.</main></body></html>",
            url="https://source.test/",
        )

        result = service.evaluate(_candidate(url="https://source.test/"))

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.SOURCE_PAGE_MISMATCH)

    def test_g18_search_navigation_shell_is_rejected(self):
        service = _service(
            "<html><body><nav>Home Search Results Categories Contact</nav></body></html>",
            url="https://source.test/search?q=line4",
        )

        result = service.evaluate(_candidate(url="https://source.test/search?q=line4"))

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.SOURCE_PAGE_MISMATCH)

    def test_unavailable_content_is_rejected(self):
        service = EvidenceService(_FixtureFetcher(RuntimeError("connection failed")))

        result = service.evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.CONTENT_UNAVAILABLE)

    def test_g03_article_body_is_ready_and_uses_canonical_url(self):
        html = (
            "<html><head><link rel='canonical' href='/article/line-4-control'></head>"
            "<body><article><p>Metro operator commissioned a moving-block train control system "
            "on Line 4 after integration testing was completed in September 2026.</p></article></body></html>"
        )
        service = _service(html)

        result = service.evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertIsNone(result.reject_reason)
        self.assertEqual(result.canonical_source_url, "https://source.test/article/line-4-control")
        self.assertIn("moving-block train control", result.substantive_content)
        self.assertTrue(result.provenance["source_to_candidate_match"])
        self.assertTrue(result.provenance["factual_substance"])

    def test_g10_structured_procurement_notice_is_ready(self):
        html = (
            "<html><body><main><p>The metro authority awarded a signalling replacement contract "
            "to Transit Systems for Line 2. The procurement notice lists the contractor, delivery "
            "milestones, and award date in September 2026.</p></main></body></html>"
        )
        service = _service(html, url="https://source.test/notices/line-2-award")

        result = service.evaluate(
            _candidate(
                title="Metro authority awards signalling replacement contract for Line 2",
                url="https://source.test/notices/line-2-award",
                discovery_intent="procurement",
                source_type="official_notice",
            )
        )

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(result.source_type, "official_notice")

    def test_g06_major_technical_incident_body_is_ready(self):
        html = (
            "<html><body><article><p>A metro traction-power fault caused smoke at Central Station "
            "and suspended Line 2 during the morning peak. The operator isolated the substation "
            "and restored service after inspection in September 2026.</p></article></body></html>"
        )
        service = _service(html, url="https://source.test/incidents/traction-power-fault")

        result = service.evaluate(
            _candidate(
                title="Metro traction-power fault suspends Line 2",
                url="https://source.test/incidents/traction-power-fault",
                discovery_intent="major incident",
            )
        )

        self.assertEqual(result.state, EvidenceState.READY)

    def test_g11_innovative_procurement_notice_is_ready(self):
        html = (
            "<html><body><main><p>The metro issued a procurement for a pilot wayside energy-storage "
            "system to recover braking energy. The notice describes the storage chemistry, test site, "
            "trial objectives, and measurement plan for September 2026.</p></main></body></html>"
        )
        service = _service(html, url="https://source.test/notices/energy-storage-pilot")

        result = service.evaluate(
            _candidate(
                title="Metro procures pilot wayside energy-storage system",
                url="https://source.test/notices/energy-storage-pilot",
                discovery_intent="procurement",
                source_type="official_notice",
            )
        )

        self.assertEqual(result.state, EvidenceState.READY)

    def test_french_substantive_article_is_ready_without_english_lexicon(self):
        title = "Le métro de Lyon déploie un système de signalisation innovant"
        html = (
            f"<html><body><h1>{title}</h1><article><p>Le réseau lyonnais a déployé ce système "
            "après une campagne d'essais sur la ligne concernée. La mise en service et les résultats "
            "du test sont décrits dans l'avis publié en septembre 2026.</p></article></body></html>"
        )

        result = _service(html).evaluate(_candidate(title=title))

        self.assertEqual(result.state, EvidenceState.READY)

    def test_japanese_substantive_article_is_ready_with_unicode_identity(self):
        title = "東京メトロ、新型信号システムを導入"
        html = (
            f"<html><body><h1>{title}</h1><article><p>東京メトロは新型信号システムを導入した。"
            "試験運用は2026年9月に開始され、運行への影響と検証結果が公表された。</p>"
            "</article></body></html>"
        )

        result = _service(html).evaluate(_candidate(title=title))

        self.assertEqual(result.state, EvidenceState.READY)

    def test_korean_substantive_article_is_ready_with_unicode_identity(self):
        title = "서울 지하철, 새 신호 시스템 도입"
        html = (
            f"<html><body><h1>{title}</h1><article><p>서울 지하철 운영기관은 새 신호 시스템을 도입했다."
            "2026년 9월 시험 운행에서 처리 결과와 서비스 영향이 확인되었다.</p>"
            "</article></body></html>"
        )

        result = _service(html).evaluate(_candidate(title=title))

        self.assertEqual(result.state, EvidenceState.READY)

    def test_accented_european_identity_is_ready(self):
        title = "München eröffnet Zürichs lärmarme Station"
        html = (
            f"<html><body><h1>{title}</h1><article><p>Die Betreiberin eröffnete die Station nach einer "
            "Messkampagne und veröffentlichte die Ergebnisse der Lärmpruefung für den Betrieb im Jahr 2026."
            "</p></article></body></html>"
        )

        result = _service(html).evaluate(_candidate(title=title))

        self.assertEqual(result.state, EvidenceState.READY)

    def test_headline_repetition_only_is_rejected_as_insufficient_substance(self):
        title = "東京メトロ、新型信号システムを導入"
        html = f"<html><body><h1>{title}</h1><article><p>{title}</p></article></body></html>"

        result = _service(html).evaluate(_candidate(title=title))

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.INSUFFICIENT_SUBSTANCE)

    def test_high_title_overlap_with_broken_provenance_is_rejected(self):
        html = (
            "<html><body><h1>Metro operator commissions moving-block train control on Line 4</h1>"
            "<article><p>Metro operator commissioned a moving-block train control system on Line 4 "
            "after integration testing was completed in September 2026.</p></article></body></html>"
        )
        service = _service(html, url="https://source.test/article/unrelated")

        result = service.evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.SOURCE_PAGE_MISMATCH)
        self.assertFalse(result.provenance["source_provenance"])

    def test_valid_provenance_with_unrelated_event_identity_is_rejected(self):
        html = (
            "<html><body><h1>Metro operator commissions moving-block train control on Line 5</h1>"
            "<article><p>Metro operator commissioned the moving-block train control system on Line 5 "
            "after integration testing was completed in September 2026.</p></article></body></html>"
        )
        service = _service(html, judge=_DifferentEventJudge())

        result = service.evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.SOURCE_PAGE_MISMATCH)
        self.assertTrue(result.provenance["source_provenance"])
        self.assertFalse(result.provenance["page_event_identity"])

    def test_generic_urban_rail_overlap_does_not_establish_identity(self):
        html = (
            "<html><body><article><p>The metro operator completed a project at a station on the line. "
            "The system entered service after testing in 2026.</p></article></body></html>"
        )
        service = _service(html, judge=_DifferentEventJudge())

        result = service.evaluate(
            _candidate(title="Metro line station system project")
        )

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.SOURCE_PAGE_MISMATCH)
        self.assertFalse(result.provenance["page_event_identity"])

    def test_resolved_article_with_provenance_and_event_identity_is_ready(self):
        candidate_url = "https://source.test/news/line-4-control?tracking=1"
        resolved_url = "https://source.test/article/line-4-control"
        html = (
            "<html><head><link rel='canonical' href='/article/line-4-control'></head>"
            "<body><h1>Metro operator commissions moving-block train control on Line 4</h1>"
            "<article><p>Metro operator commissioned a moving-block train control system on Line 4 "
            "after integration testing was completed in September 2026.</p></article></body></html>"
        )
        source = FetchedSource(
            url=resolved_url,
            content=html,
            redirect_chain=(candidate_url, resolved_url),
        )
        service = EvidenceService(
            _FixtureFetcher(source),
            semantic_judge=_SameEventJudge(),
        )

        result = service.evaluate(_candidate(url=candidate_url))

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(result.canonical_source_url, resolved_url)
        self.assertTrue(result.provenance["source_provenance"])
        self.assertTrue(result.provenance["page_event_identity"])

    def test_source_to_candidate_mismatch_is_rejected(self):
        html = (
            "<html><body><article><p>The airport authority opened a new bus terminal "
            "after construction finished in 2026. The project serves regional passengers.</p></article></body></html>"
        )
        service = _service(
            html,
            url="https://source.test/article/unrelated",
            judge=_DifferentEventJudge(),
        )

        result = service.evaluate(_candidate(url="https://source.test/article/unrelated"))

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.SOURCE_PAGE_MISMATCH)
        self.assertFalse(result.provenance["source_to_candidate_match"])

    def test_candidate_is_not_mutated_and_snippet_is_not_runtime_evidence(self):
        candidate = _candidate()
        before = copy.deepcopy(candidate)
        service = _service(
            "<html><body><article><p>Metro operator commissioned a moving-block train control system "
            "on Line 4 after testing in September 2026.</p></article></body></html>"
        )

        result = service.evaluate(candidate)

        self.assertEqual(candidate, before)
        self.assertNotIn(candidate.search_snippet, result.substantive_content)

    def test_non_textual_content_is_unavailable(self):
        service = _service("binary payload", content_type="application/pdf")

        result = service.evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.CONTENT_UNAVAILABLE)

    def test_invalid_candidate_url_is_unresolved_without_fetch(self):
        fetcher = _FixtureFetcher(FetchedSource(url="", content=""))
        service = EvidenceService(fetcher)

        result = service.evaluate(_candidate(url="not-a-url"))

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.URL_UNRESOLVED)
        self.assertEqual(fetcher.calls, [])

    def test_query_parameter_difference_is_not_same_resource(self):
        html = (
            "<html><body><h1>Metro operator commissions moving-block train control on Line 4</h1>"
            "<article><p>Metro operator commissioned a moving-block train control system on Line 4 "
            "after integration testing was completed in September 2026.</p></article></body></html>"
        )
        service = _service(html, url="https://source.test/article?id=999")

        result = service.evaluate(_candidate(url="https://source.test/article?id=123"))

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.SOURCE_PAGE_MISMATCH)

    def test_path_case_difference_is_not_same_resource(self):
        html = (
            "<html><body><h1>Metro operator commissions moving-block train control on Line 4</h1>"
            "<article><p>Metro operator commissioned a moving-block train control system on Line 4 "
            "after integration testing was completed in September 2026.</p></article></body></html>"
        )
        service = _service(html, url="https://source.test/article/a")

        result = service.evaluate(_candidate(url="https://source.test/Article/A"))

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.SOURCE_PAGE_MISMATCH)

    def test_tracking_only_query_difference_is_safe_resource_normalisation(self):
        html = (
            "<html><body><h1>Metro operator commissions moving-block train control on Line 4</h1>"
            "<article><p>Metro operator commissioned a moving-block train control system on Line 4 "
            "after integration testing was completed in September 2026.</p></article></body></html>"
        )
        service = _service(html, url="https://source.test/article?id=123")

        result = service.evaluate(
            _candidate(url="https://source.test/article?id=123&utm_source=newsletter#section")
        )

        self.assertEqual(result.state, EvidenceState.READY)

    def test_same_host_unrelated_canonical_is_rejected(self):
        html = (
            "<html><head><link rel='canonical' href='/article/completely-different-story'></head>"
            "<body><h1>Metro operator commissions moving-block train control on Line 4</h1>"
            "<article><p>Metro operator commissioned a moving-block train control system on Line 4 "
            "after integration testing was completed in September 2026.</p></article></body></html>"
        )
        service = _service(html)

        result = service.evaluate(_candidate(url="https://source.test/article/line-4"))

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.SOURCE_PAGE_MISMATCH)
        self.assertFalse(result.provenance["source_provenance"])

    def test_default_transport_respects_declared_non_utf8_charset(self):
        url = "http://charset.test/article"
        html = (
            "<html><body><h1>Metro operator commissions moving-block train control on Line 4</h1>"
            "<article><p>Métro completed é and à validation for Line 4 in September 2026.</p>"
            "</article></body></html>"
        ).encode("iso-8859-1")
        response = _MockHTTPResponse(
            html,
            url=url,
            content_type="text/html; charset=iso-8859-1",
        )
        opener = _MockHTTPOpener(response)
        public_dns = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))]

        with (
            patch("src.weekly_report.evidence_service.socket.getaddrinfo", return_value=public_dns),
            patch("src.weekly_report.evidence_service.build_opener", return_value=opener),
        ):
            result = EvidenceService(semantic_judge=_SameEventJudge()).evaluate(
                _candidate(url=url)
            )

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertIn("Métro", result.substantive_content)
        self.assertIn("é", result.substantive_content)
        self.assertIn("à", result.substantive_content)
        self.assertNotIn("�", result.substantive_content)

    def test_default_transport_blocks_loopback_before_open(self):
        opener = patch("src.weekly_report.evidence_service.build_opener")
        with opener as build_opener:
            result = EvidenceService().evaluate(_candidate(url="http://127.0.0.1/article"))

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.CONTENT_UNAVAILABLE)
        build_opener.assert_not_called()

    def test_default_transport_blocks_ipv6_loopback_before_open(self):
        opener = patch("src.weekly_report.evidence_service.build_opener")
        with opener as build_opener:
            result = EvidenceService().evaluate(_candidate(url="http://[::1]/article"))

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.CONTENT_UNAVAILABLE)
        build_opener.assert_not_called()

    def test_redirect_handler_blocks_private_target_before_follow(self):
        handler = _RecordingRedirectHandler()

        with patch("src.weekly_report.evidence_service.HTTPRedirectHandler.redirect_request") as parent:
            with self.assertRaises(_UnsafeDestinationError):
                handler.redirect_request(
                    None,
                    None,
                    302,
                    "Found",
                    {},
                    "http://127.0.0.1/internal",
                )

        parent.assert_not_called()
        self.assertEqual(handler.redirect_urls, [])

    def test_default_transport_blocks_dns_private_result_before_open(self):
        private_dns = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.10.10.10", 80))]
        opener = patch("src.weekly_report.evidence_service.build_opener")
        with (
            patch("src.weekly_report.evidence_service.socket.getaddrinfo", return_value=private_dns) as resolver,
            opener as build_opener,
        ):
            result = EvidenceService().evaluate(_candidate(url="http://private.test/article"))

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.CONTENT_UNAVAILABLE)
        resolver.assert_called_once()
        build_opener.assert_not_called()

    def test_structural_collection_candidate_h2_is_not_primary_identity(self):
        title = "Line 4 opens"
        html = (
            "<html><body><main role='list'>"
            f"<div role='listitem'><h2>{title}</h2><p>The operator opened Line 4 after final testing.</p></div>"
            "<div role='listitem'><h2>Metro awards signalling contract</h2>"
            "<p>The award covers Line 2.</p></div>"
            "</main></body></html>"
        )
        result = _service(html, url="https://source.test/news").evaluate(
            _candidate(title=title, url="https://source.test/news")
        )

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.SOURCE_PAGE_MISMATCH)

    def test_news_ancestor_is_allowed_for_article_resource(self):
        title = "Line 4 opens"
        html = (
            f"<html><body><h1>{title}</h1><article><p>The operator opened Line 4 "
            "after final testing and safety approval.</p></article></body></html>"
        )
        judge = _SameEventJudge()
        result = _service(
            html,
            url="https://source.test/news/line-4-opens",
            judge=judge,
        ).evaluate(_candidate(title=title, url="https://source.test/news/line-4-opens"))

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(judge.calls, 1)

    def test_nested_news_ancestor_is_allowed_for_article_resource(self):
        title = "Line 4 opens"
        html = (
            f"<html><body><h1>{title}</h1><article><p>The operator opened Line 4 "
            "after final testing and safety approval.</p></article></body></html>"
        )
        judge = _SameEventJudge()
        result = _service(
            html,
            url="https://source.test/press/news/line-4-opens",
            judge=judge,
        ).evaluate(
            _candidate(title=title, url="https://source.test/press/news/line-4-opens")
        )

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(judge.calls, 1)

    def test_latest_ancestor_is_allowed_for_article_resource(self):
        title = "Line 4 opens"
        html = (
            f"<html><body><h1>{title}</h1><article><p>The operator opened Line 4 "
            "after final testing and safety approval.</p></article></body></html>"
        )
        judge = _SameEventJudge()
        result = _service(
            html,
            url="https://source.test/latest/line-4-opens",
            judge=judge,
        ).evaluate(_candidate(title=title, url="https://source.test/latest/line-4-opens"))

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(judge.calls, 1)

    def test_news_root_path_is_not_authoritative_when_principal_is_established(self):
        title = "Line 4 opens"
        html = (
            f"<html><body><h1>{title}</h1><main><p>The operator opened Line 4 "
            "after final testing and safety approval.</p></main></body></html>"
        )
        judge = _SameEventJudge()
        result = _service(html, url="https://source.test/news", judge=judge).evaluate(
            _candidate(title=title, url="https://source.test/news")
        )

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertIsNone(result.reject_reason)
        self.assertEqual(judge.calls, 1)

    def test_latest_root_path_is_not_authoritative_when_principal_is_established(self):
        title = "Line 4 opens"
        html = (
            f"<html><body><h1>{title}</h1><main><p>The operator opened Line 4 "
            "after final testing and safety approval.</p></main></body></html>"
        )
        judge = _SameEventJudge()
        result = _service(html, url="https://source.test/latest", judge=judge).evaluate(
            _candidate(title=title, url="https://source.test/latest")
        )

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertIsNone(result.reject_reason)
        self.assertEqual(judge.calls, 1)

    def test_category_path_is_not_authoritative_when_principal_is_established(self):
        title = "Line 4 opens"
        html = (
            f"<html><body><h1>{title}</h1><main><p>The operator opened Line 4 "
            "after final testing and safety approval.</p></main></body></html>"
        )
        judge = _SameEventJudge()
        result = _service(
            html,
            url="https://source.test/category/metro",
            judge=judge,
        ).evaluate(_candidate(title=title, url="https://source.test/category/metro"))

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(judge.calls, 1)

    def test_locale_tag_path_is_not_authoritative_when_principal_is_established(self):
        title = "Line 4 opens"
        html = (
            f"<html><body><h1>{title}</h1><main><p>The operator opened Line 4 "
            "after final testing and safety approval.</p></main></body></html>"
        )
        judge = _SameEventJudge()
        result = _service(
            html,
            url="https://source.test/fr/tag/signalisation",
            judge=judge,
        ).evaluate(_candidate(title=title, url="https://source.test/fr/tag/signalisation"))

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(judge.calls, 1)

    def test_archive_path_is_not_authoritative_when_principal_is_established(self):
        title = "Line 4 opens"
        html = (
            f"<html><body><h1>{title}</h1><main><p>The operator opened Line 4 "
            "after final testing and safety approval.</p></main></body></html>"
        )
        judge = _SameEventJudge()
        result = _service(
            html,
            url="https://source.test/archive/2026",
            judge=judge,
        ).evaluate(_candidate(title=title, url="https://source.test/archive/2026"))

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(judge.calls, 1)

    def test_listing_page_substantial_card_summary_is_not_authoritative(self):
        title = "Line 4 opens"
        html = (
            "<html><body><main role='list'>"
            f"<div role='listitem'><h2>{title}</h2><p>The operator opened Line 4 on 15 September 2026 "
            "after commissioning, safety checks, and trial operations.</p></div>"
            "<div role='listitem'><h2>Another event</h2><p>A separate event summary.</p></div>"
            "</main></body></html>"
        )
        result = _service(html, url="https://source.test/latest").evaluate(
            _candidate(title=title, url="https://source.test/latest")
        )

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.SOURCE_PAGE_MISMATCH)

    def test_short_exact_primary_headline_with_body_is_ready(self):
        title = "Line 4 opens"
        html = (
            f"<html><body><h1>{title}</h1><main><p>The operator opened Line 4 on 15 September 2026 "
            "after final safety checks and a successful trial operation.</p></main></body></html>"
        )
        result = _service(html, url="https://source.test/article/line-4-opens").evaluate(
            _candidate(title=title, url="https://source.test/article/line-4-opens")
        )

        self.assertEqual(result.state, EvidenceState.READY)

    def test_short_exact_primary_headline_without_new_body_is_rejected(self):
        title = "Line 4 opens"
        html = f"<html><body><h1>{title}</h1><main><p>{title}</p></main></body></html>"
        result = _service(html, url="https://source.test/article/line-4-opens").evaluate(
            _candidate(title=title, url="https://source.test/article/line-4-opens")
        )

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.INSUFFICIENT_SUBSTANCE)

    def test_exact_candidate_in_arbitrary_h2_cannot_establish_identity(self):
        title = "Line 4 opens"
        html = (
            "<html><body><h1>Latest News</h1><main>"
            f"<article><h2>{title}</h2><p>The operator opened Line 4 after testing and approval.</p></article>"
            "<article><h2>Metro awards signalling contract</h2><p>The award covers Line 2.</p></article>"
            "</main></body></html>"
        )
        judge = _SameEventJudge()
        result = _service(
            html,
            url="https://source.test/updates",
            judge=judge,
        ).evaluate(
            _candidate(title=title, url="https://source.test/updates")
        )

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.SOURCE_PAGE_MISMATCH)
        self.assertEqual(judge.calls, 0)

    def test_long_form_multi_section_article_is_not_listing_shell(self):
        title = "Metro launches predictive maintenance platform"
        html = (
            f"<html><body><h1>{title}</h1><main>"
            "<section><h2>Background</h2><p>The operator introduced the platform after extensive trials.</p></section>"
            "<section><h2>Technical details</h2><p>It predicts equipment failures and supports maintenance teams.</p></section>"
            "</main></body></html>"
        )
        judge = _SameEventJudge()
        result = _service(
            html,
            url="https://source.test/article/predictive-maintenance",
            judge=judge,
        ).evaluate(
            _candidate(
                title=title,
                url="https://source.test/article/predictive-maintenance",
            )
        )

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(judge.calls, 1)

    def test_official_notice_without_article_is_ready(self):
        title = "Line 4 opens"
        html = (
            f"<html><body><h1>{title}</h1><main><div>The operator opened Line 4 on 15 September 2026 "
            "after safety approval, final testing, and trial operations were completed.</div></main></body></html>"
        )
        result = _service(
            html,
            url="https://source.test/notices/line-4-open",
        ).evaluate(
            _candidate(
                title=title,
                url="https://source.test/notices/line-4-open",
                source_type="official_notice",
            )
        )

        self.assertEqual(result.state, EvidenceState.READY)

    def test_structured_og_title_can_establish_primary_identity(self):
        title = "Line 4 opens"
        html = (
            f"<html><head><meta property='og:title' content='{title}'></head><body>"
            "<main><div>The operator opened Line 4 on 15 September 2026 after safety approval "
            "and final trial operations were completed.</div></main></body></html>"
        )
        result = _service(html, url="https://source.test/releases/line-4-open").evaluate(
            _candidate(title=title, url="https://source.test/releases/line-4-open")
        )

        self.assertEqual(result.state, EvidenceState.READY)

    def test_read_more_only_body_is_not_factual_substance(self):
        title = "Line 4 opens"
        html = f"<html><body><h1>{title}</h1><main><a href='/more'>Read more.</a></main></body></html>"
        result = _service(html, url="https://source.test/article/line-4-opens").evaluate(
            _candidate(title=title, url="https://source.test/article/line-4-opens")
        )

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.TITLE_ONLY)

    def test_inline_anchor_text_is_preserved_for_semantic_judge(self):
        title = "Metro awards signalling contract on Line 4"
        html = (
            f"<html><body><h1>{title}</h1><main><p>The operator awarded a "
            "<a href='/contract'>signalling contract</a> for <a href='/line-4'>Line 4</a> "
            "to <a href='/supplier'>Siemens Mobility</a> after procurement review.</p>"
            "</main></body></html>"
        )
        judge = _SameEventJudge()
        result = _service(
            html,
            url="https://source.test/article/line-4-contract",
            judge=judge,
        ).evaluate(
            _candidate(
                title=title,
                url="https://source.test/article/line-4-contract",
            )
        )

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(judge.calls, 1)
        body = judge.requests[0].principal_body_segments[0].text
        self.assertIn("signalling contract", body)
        self.assertIn("Line 4", body)
        self.assertIn("Siemens Mobility", body)

    def test_interactive_only_principal_content_is_rejected_before_judge(self):
        title = "Line 4 opens"
        html = (
            f"<html><body><h1>{title}</h1><main><a href='/more'>Read more</a>"
            "<button>Contact</button></main></body></html>"
        )
        judge = _SameEventJudge()
        result = _service(
            html,
            url="https://source.test/article/line-4-opens",
            judge=judge,
        ).evaluate(_candidate(title=title, url="https://source.test/article/line-4-opens"))

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.TITLE_ONLY)
        self.assertEqual(judge.calls, 0)

    def test_s1_main_article_and_related_article_are_separable(self):
        judge = _SameEventJudge()
        html = (
            "<html><body><main><article><header><h1>Line 4 opens</h1></header>"
            "<p>The operator opened Line 4 after final testing and safety approval.</p>"
            "</article><aside><article><h2>Related project</h2>"
            "<p>A separate project summary.</p></article></aside></main></body></html>"
        )
        result = _service(
            html, url="https://source.test/category/metro", judge=judge
        ).evaluate(_candidate(title="Line 4 opens", url="https://source.test/category/metro"))

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(judge.calls, 1)
        self.assertNotIn("separate project summary", judge.requests[0].principal_body_segments[0].text)

    def test_s2_nested_comment_article_is_excluded_from_principal_body(self):
        judge = _SameEventJudge()
        html = (
            "<html><body><article><header><h1>Line 4 opens</h1></header>"
            "<p>The operator opened Line 4 after final testing.</p>"
            "<article role='comment'><h2>Comment</h2><p>Unrelated reply text.</p></article>"
            "</article></body></html>"
        )
        result = _service(html, judge=judge).evaluate(_candidate(title="Line 4 opens"))

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(judge.calls, 1)
        self.assertNotIn("Unrelated reply text", judge.requests[0].principal_body_segments[0].text)

    def test_comment_and_reply_articles_cannot_become_principal_documents(self):
        for attribute, relation in (
            ("role='comment'", "comment"),
            ("role='reply'", "reply"),
            ("itemprop='comment'", "comment"),
            ("aria-label='reply'", "reply"),
        ):
            with self.subTest(attribute=attribute):
                html = (
                    f"<html><body><article {attribute}><h1>{relation.title()} title</h1>"
                    f"<p>{relation.title()}-only body.</p></article></body></html>"
                )
                assessment = assess_document(
                    html,
                    "text/html",
                    resource_url="https://source.test/article/line-4-control",
                    candidate_id="C1",
                )
                result = _service(html).evaluate(_candidate())

                self.assertNotEqual(
                    assessment.principal_document_status,
                    PrincipalDocumentStatus.PRINCIPAL_DOCUMENT_ESTABLISHED,
                )
                self.assertEqual(result.state, EvidenceState.REJECTED)
                self.assertEqual(result.substantive_content, "")

    def test_article_nested_inside_comment_cannot_become_principal_document(self):
        html = (
            "<html><body><p>Principal page text.</p>"
            "<div role='comment'><article><h1>Comment article title</h1>"
            "<p>Comment article body.</p></article></div></body></html>"
        )
        assessment = assess_document(
            html,
            "text/html",
            resource_url="https://source.test/article/line-4-control",
            candidate_id="C1",
        )

        self.assertEqual(
            assessment.principal_document_status,
            PrincipalDocumentStatus.PRINCIPAL_DOCUMENT_ESTABLISHED,
        )
        self.assertEqual(assessment.body_text, "Principal page text.")
        self.assertNotIn("Comment article title", assessment.document_level_headlines)

    def test_comment_headings_do_not_create_conflict_or_secondary_headlines(self):
        html = (
            "<article><h1>Main title</h1><p>Main authoritative body.</p>"
            "<div role='comment'><h1>Comment title</h1><h2>Comment section</h2>"
            "<p>Comment body.</p></div></article>"
        )
        assessment = assess_document(
            html,
            "text/html",
            resource_url="https://source.test/article/line-4-control",
            candidate_id="C1",
        )
        judge = _SameEventJudge()
        result = _service(html, judge=judge).evaluate(_candidate())

        self.assertEqual(
            assessment.principal_document_status,
            PrincipalDocumentStatus.PRINCIPAL_DOCUMENT_ESTABLISHED,
        )
        self.assertEqual(assessment.document_level_headlines, ("Main title",))
        self.assertEqual(assessment.secondary_headlines, ())
        self.assertNotIn("headline_conflict", result.provenance)
        self.assertEqual(judge.requests[0].document_level_headlines, ("Main title",))

    def test_generic_units_do_not_obtain_body_from_comment_subtrees(self):
        html = (
            "<article><h1>Main</h1><p>Main body.</p>"
            "<div><h2>Section A</h2><div role='comment'><p>comment body A</p>"
            "</div></div><div><h2>Section B</h2><div role='comment'>"
            "<p>comment body B</p></div></div></article>"
        )
        assessment = assess_document(
            html,
            "text/html",
            resource_url="https://source.test/article/line-4-control",
            candidate_id="C1",
        )

        self.assertEqual(
            assessment.principal_document_status,
            PrincipalDocumentStatus.PRINCIPAL_DOCUMENT_ESTABLISHED,
        )
        self.assertNotIn("unresolved_generic_sibling_units", assessment.diagnostics)
        self.assertEqual(assessment.body_text, "Main body.")

    def test_collection_units_do_not_obtain_body_from_comment_subtrees(self):
        html = (
            "<main role='list'><div role='listitem'><h2>Item A</h2>"
            "<div role='comment'><p>comment A</p></div></div>"
            "<div role='listitem'><h2>Item B</h2><div role='comment'>"
            "<p>comment B</p></div></div></main>"
        )
        assessment = assess_document(
            html,
            "text/html",
            resource_url="https://source.test/article/line-4-control",
            candidate_id="C1",
        )

        self.assertNotEqual(
            assessment.principal_document_status,
            PrincipalDocumentStatus.PRINCIPAL_DOCUMENT_AMBIGUOUS,
        )
        self.assertNotIn("collection", assessment.diagnostics)

    def test_generic_unit_comment_headline_does_not_qualify_unit_shape(self):
        html = (
            "<main><div><div role='comment'><h2>Comment headline</h2>"
            "</div><p>Normal parent text.</p></div></main>"
        )
        assessment = assess_document(
            html,
            "text/html",
            resource_url="https://source.test/article/line-4-control",
            candidate_id="C1",
        )

        self.assertEqual(
            assessment.principal_document_status,
            PrincipalDocumentStatus.PRINCIPAL_DOCUMENT_ESTABLISHED,
        )
        self.assertEqual(assessment.body_text, "Normal parent text.")
        self.assertNotIn("unresolved_generic_sibling_units", assessment.diagnostics)

    def test_collection_item_comment_headline_does_not_qualify_unit_shape(self):
        html = (
            "<main role='list'><div role='listitem'><div role='comment'>"
            "<h2>Comment headline</h2></div><p>Normal item text.</p></div></main>"
        )
        assessment = assess_document(
            html,
            "text/html",
            resource_url="https://source.test/article/line-4-control",
            candidate_id="C1",
        )

        self.assertNotEqual(
            assessment.principal_document_status,
            PrincipalDocumentStatus.PRINCIPAL_DOCUMENT_AMBIGUOUS,
        )
        self.assertNotIn("collection", assessment.diagnostics)

    def test_owned_generic_headline_and_body_still_qualify_unit_shape(self):
        html = (
            "<main><div><h2>Technical section</h2>"
            "<p>Owned technical body.</p></div></main>"
        )
        assessment = assess_document(
            html,
            "text/html",
            resource_url="https://source.test/article/line-4-control",
            candidate_id="C1",
        )

        self.assertEqual(
            assessment.principal_document_status,
            PrincipalDocumentStatus.PRINCIPAL_DOCUMENT_ESTABLISHED,
        )
        self.assertIn("Owned technical body.", assessment.body_text)

    def test_owned_collection_units_remain_a_collection(self):
        html = (
            "<main role='list'><div role='listitem'><h2>Item A</h2>"
            "<p>Owned body A.</p></div><div role='listitem'><h2>Item B</h2>"
            "<p>Owned body B.</p></div></main>"
        )
        assessment = assess_document(
            html,
            "text/html",
            resource_url="https://source.test/article/line-4-control",
            candidate_id="C1",
        )

        self.assertEqual(
            assessment.principal_document_status,
            PrincipalDocumentStatus.PRINCIPAL_DOCUMENT_AMBIGUOUS,
        )
        self.assertTrue(assessment.diagnostics["collection"])

    def test_generic_sibling_headline_tails_remain_ambiguous(self):
        html = (
            "<main><div><h2>Event A</h2>Body A</div>"
            "<div><h2>Event B</h2>Body B</div></main>"
        )
        assessment = assess_document(
            html,
            "text/html",
            resource_url="https://source.test/article/line-4-control",
            candidate_id="C1",
        )

        self.assertEqual(
            assessment.principal_document_status,
            PrincipalDocumentStatus.PRINCIPAL_DOCUMENT_AMBIGUOUS,
        )
        self.assertTrue(assessment.diagnostics["unresolved_generic_sibling_units"])

    def test_collection_headline_tails_remain_ambiguous(self):
        html = (
            "<main role='list'><div role='listitem'><h2>Item A</h2>Body A</div>"
            "<div role='listitem'><h2>Item B</h2>Body B</div></main>"
        )
        assessment = assess_document(
            html,
            "text/html",
            resource_url="https://source.test/article/line-4-control",
            candidate_id="C1",
        )

        self.assertEqual(
            assessment.principal_document_status,
            PrincipalDocumentStatus.PRINCIPAL_DOCUMENT_AMBIGUOUS,
        )
        self.assertTrue(assessment.diagnostics["collection"])

    def test_generic_sibling_direct_text_remains_ambiguous(self):
        html = (
            "<main><div>Body A<h2>Event A</h2></div>"
            "<div>Body B<h2>Event B</h2></div></main>"
        )
        assessment = assess_document(
            html,
            "text/html",
            resource_url="https://source.test/article/line-4-control",
            candidate_id="C1",
        )

        self.assertEqual(
            assessment.principal_document_status,
            PrincipalDocumentStatus.PRINCIPAL_DOCUMENT_AMBIGUOUS,
        )
        self.assertTrue(assessment.diagnostics["unresolved_generic_sibling_units"])

    def test_collection_direct_text_remains_ambiguous(self):
        html = (
            "<main role='list'><div role='listitem'>Body A<h2>Item A</h2></div>"
            "<div role='listitem'>Body B<h2>Item B</h2></div></main>"
        )
        assessment = assess_document(
            html,
            "text/html",
            resource_url="https://source.test/article/line-4-control",
            candidate_id="C1",
        )

        self.assertEqual(
            assessment.principal_document_status,
            PrincipalDocumentStatus.PRINCIPAL_DOCUMENT_AMBIGUOUS,
        )
        self.assertTrue(assessment.diagnostics["collection"])

    def test_excluded_child_preserves_parent_owned_tail_body(self):
        html = (
            "<main><div><h2>Event A</h2><div role='comment'>Excluded comment."
            "</div>Parent-owned body A.</div><div><h2>Event B</h2>"
            "<div role='comment'>Excluded comment.</div>Parent-owned body B.</div>"
            "</main>"
        )
        assessment = assess_document(
            html,
            "text/html",
            resource_url="https://source.test/article/line-4-control",
            candidate_id="C1",
        )

        self.assertEqual(
            assessment.principal_document_status,
            PrincipalDocumentStatus.PRINCIPAL_DOCUMENT_AMBIGUOUS,
        )
        self.assertTrue(assessment.diagnostics["unresolved_generic_sibling_units"])

    def test_comment_internal_tail_does_not_qualify_parent_unit(self):
        html = (
            "<main><div><h2>Section</h2><div role='comment'><span>Comment "
            "fragment</span>Comment continuation</div></div></main>"
        )
        assessment = assess_document(
            html,
            "text/html",
            resource_url="https://source.test/article/line-4-control",
            candidate_id="C1",
        )

        self.assertNotEqual(
            assessment.principal_document_status,
            PrincipalDocumentStatus.PRINCIPAL_DOCUMENT_ESTABLISHED,
        )
        self.assertNotIn("Comment continuation", assessment.body_text)

    def test_nested_collection_headlines_do_not_qualify_generic_units(self):
        html = (
            "<main><div>Outer body A<ul><li><h2>Nested A</h2>"
            "<p>Nested body A</p></li></ul></div><div>Outer body B"
            "<ul><li><h2>Nested B</h2><p>Nested body B</p></li></ul>"
            "</div></main>"
        )
        assessment = assess_document(
            html,
            "text/html",
            resource_url="https://source.test/article/line-4-control",
            candidate_id="C1",
        )

        self.assertNotEqual(
            assessment.principal_document_status,
            PrincipalDocumentStatus.PRINCIPAL_DOCUMENT_AMBIGUOUS,
        )
        self.assertNotIn("unresolved_generic_sibling_units", assessment.diagnostics)

    def test_nested_collection_headlines_do_not_qualify_list_items(self):
        html = (
            "<main role='list'><div role='listitem'>Outer body A<ul><li>"
            "<h2>Nested A</h2><p>Nested body</p></li></ul></div>"
            "<div role='listitem'>Outer body B<ul><li><h2>Nested B</h2>"
            "<p>Nested body</p></li></ul></div></main>"
        )
        assessment = assess_document(
            html,
            "text/html",
            resource_url="https://source.test/article/line-4-control",
            candidate_id="C1",
        )

        self.assertNotEqual(
            assessment.principal_document_status,
            PrincipalDocumentStatus.PRINCIPAL_DOCUMENT_AMBIGUOUS,
        )
        self.assertNotIn("collection", assessment.diagnostics)

    def test_owned_direct_headlines_still_qualify_generic_units(self):
        html = (
            "<main><div><h2>Outer A</h2><p>Body A</p></div>"
            "<div><h2>Outer B</h2><p>Body B</p></div></main>"
        )
        assessment = assess_document(
            html,
            "text/html",
            resource_url="https://source.test/article/line-4-control",
            candidate_id="C1",
        )

        self.assertEqual(
            assessment.principal_document_status,
            PrincipalDocumentStatus.PRINCIPAL_DOCUMENT_AMBIGUOUS,
        )
        self.assertTrue(assessment.diagnostics["unresolved_generic_sibling_units"])

    def test_s3_multiple_independent_sibling_documents_reject_before_judge(self):
        judge = _SameEventJudge()
        html = (
            "<html><body><main><article><h1>Line 4 opens</h1><p>Event one.</p></article>"
            "<article><h1>Line 2 closes</h1><p>Event two.</p></article></main></body></html>"
        )
        result = _service(html, judge=judge).evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.SOURCE_PAGE_MISMATCH)
        self.assertEqual(judge.calls, 0)
        self.assertEqual(result.provenance["principal_document_status"], "PRINCIPAL_DOCUMENT_AMBIGUOUS")

    def test_s4_div_collection_uses_relationships_not_class_vocabulary(self):
        judge = _SameEventJudge()
        html = (
            "<html><body><main role='list'>"
            "<div role='listitem'><h2>Line 4 opens</h2><p>Event one.</p></div>"
            "<div role='listitem'><h2>Line 2 closes</h2><p>Event two.</p></div>"
            "</main></body></html>"
        )
        result = _service(html, url="https://source.test/article/line-4-opens", judge=judge).evaluate(
            _candidate(title="Line 4 opens", url="https://source.test/article/line-4-opens")
        )

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(judge.calls, 0)

    def test_s5_related_section_is_not_in_principal_segments(self):
        judge = _SameEventJudge()
        html = (
            "<html><body><main><article><h1>Line 4 opens</h1>"
            "<p>The operator opened Line 4 after final testing.</p></article>"
            "<aside><section><h2>Recommended</h2><p>Related content must be excluded.</p>"
            "</section></aside></main></body></html>"
        )
        result = _service(html, judge=judge).evaluate(_candidate(title="Line 4 opens"))

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertNotIn("Related content must be excluded", judge.requests[0].principal_body_segments[0].text)

    def test_s6_competing_main_regions_are_ambiguous(self):
        judge = _SameEventJudge()
        html = (
            "<html><body><main><h1>First document</h1><p>First body.</p></main>"
            "<main><h1>Second document</h1><p>Second body.</p></main></body></html>"
        )
        result = _service(html, judge=judge).evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.provenance["principal_document_status"], "PRINCIPAL_DOCUMENT_AMBIGUOUS")
        self.assertEqual(judge.calls, 0)

    def test_s7_aria_navigation_does_not_contaminate_body(self):
        judge = _SameEventJudge()
        html = (
            "<html><body><main><div role='navigation'>Navigation menu text.</div>"
            "<h1>Line 4 opens</h1><p>The operator opened Line 4 after final testing.</p>"
            "</main></body></html>"
        )
        result = _service(html, judge=judge).evaluate(_candidate(title="Line 4 opens"))

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertNotIn("Navigation menu text", judge.requests[0].principal_body_segments[0].text)

    def test_s8_article_owned_header_is_preserved(self):
        judge = _SameEventJudge()
        html = (
            "<html><body><article><header><h1>Line 4 opens</h1>"
            "<p>Lead: the operator completed final safety approval.</p></header>"
            "<p>The line entered service after testing.</p></article></body></html>"
        )
        result = _service(html, judge=judge).evaluate(_candidate(title="Line 4 opens"))

        self.assertEqual(result.state, EvidenceState.READY)
        request = judge.requests[0]
        self.assertEqual(request.document_level_headlines, ("Line 4 opens",))
        self.assertIn("final safety approval", request.principal_body_segments[0].text)

    def test_s9_locale_and_collection_paths_do_not_override_document_structure(self):
        for url in (
            "https://source.test/category/metro",
            "https://source.test/en/category/metro",
            "https://source.test/fr/tag/signalisation",
        ):
            with self.subTest(url=url):
                judge = _SameEventJudge()
                html = (
                    "<html><body><main><article><h1>Line 4 opens</h1>"
                    "<p>The operator opened Line 4 after final testing.</p>"
                    "</article></main></body></html>"
                )
                result = _service(html, url=url, judge=judge).evaluate(_candidate(title="Line 4 opens", url=url))
                self.assertEqual(result.state, EvidenceState.READY)
                self.assertEqual(judge.calls, 1)

    def test_s10_article_looking_path_cannot_promote_collection(self):
        judge = _SameEventJudge()
        html = (
            "<html><body><main role='list'><div role='listitem'><h2>Line 4 opens</h2>"
            "<p>Event one.</p></div><div role='listitem'><h2>Line 2 closes</h2>"
            "<p>Event two.</p></div></main></body></html>"
        )
        result = _service(html, url="https://source.test/article/line-4-opens", judge=judge).evaluate(
            _candidate(title="Line 4 opens", url="https://source.test/article/line-4-opens")
        )
        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(judge.calls, 0)

    def test_s11_inline_anchor_text_is_retained(self):
        self.test_inline_anchor_text_is_preserved_for_semantic_judge()

    def test_s12_interactive_only_content_rejects_before_judge(self):
        self.test_interactive_only_principal_content_is_rejected_before_judge()

    def test_s13_h2_to_h6_are_not_document_level_headlines(self):
        judge = _SameEventJudge()
        html = (
            "<html><body><main><h2>Line 4 opens</h2><h3>Related section</h3>"
            "<p>The operator opened Line 4 after final testing.</p></main></body></html>"
        )
        result = _service(html, judge=judge).evaluate(_candidate(title="Line 4 opens"))

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(judge.requests[0].document_level_headlines, ())

    def test_s14_rss_atom_and_rdf_feeds_reject_before_judge(self):
        for content_type, content in (
            ("application/rss+xml", "<rss><channel><item><title>Line 4 opens</title></item></channel></rss>"),
            ("application/atom+xml", "<feed><entry><title>Line 4 opens</title></entry></feed>"),
            ("application/rdf+xml", "<rdf:RDF xmlns:rdf='x'><channel/><item/></rdf:RDF>"),
        ):
            with self.subTest(content_type=content_type):
                judge = _SameEventJudge()
                result = _service(content, content_type=content_type, judge=judge).evaluate(_candidate())
                self.assertEqual(result.state, EvidenceState.REJECTED)
                self.assertEqual(judge.calls, 0)

    def test_s15_non_feed_xml_and_rdf_notice_use_format_specific_structure(self):
        for content_type, content in (
            (
                "application/xml",
                "<notice xmlns='urn:notice'><div role='main' data-resource='notice'>"
                "<h1>Line 4 opens</h1><p>The operator opened Line 4 after testing.</p>"
                "</div></notice>",
            ),
            (
                "application/rdf+xml",
                "<rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#' "
                "xmlns:notice='urn:notice'><notice:notice><notice:div role='main' "
                "data-resource='notice'><notice:h1>Line 4 opens</notice:h1>"
                "<notice:p>The operator opened Line 4 after testing.</notice:p>"
                "</notice:div></notice:notice></rdf:RDF>",
            ),
        ):
            with self.subTest(content_type=content_type):
                judge = _SameEventJudge()
                result = _service(content, content_type=content_type, judge=judge).evaluate(_candidate())
                self.assertEqual(result.state, EvidenceState.READY)
                self.assertEqual(judge.calls, 1)
                self.assertTrue(result.provenance["xml_namespaces"])
                self.assertTrue(
                    any(
                        facts["attributes"].get("role") == "main"
                        for facts in result.provenance["xml_nodes"]
                    )
                )

    def test_t1_native_ul_li_multi_document_list_rejects_before_judge(self):
        judge = _SameEventJudge()
        html = (
            "<main><ul><li><h2>Line 4 opens</h2><p>Event one.</p></li>"
            "<li><h2>Line 2 closes</h2><p>Event two.</p></li></ul></main>"
        )

        result = _service(html, judge=judge).evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(judge.calls, 0)
        self.assertEqual(
            result.provenance["principal_document_status"],
            "PRINCIPAL_DOCUMENT_AMBIGUOUS",
        )

    def test_t2_nested_non_comment_article_is_excluded_from_body(self):
        judge = _SameEventJudge()
        html = (
            "<article><h1>Line 4 opens</h1><p>Main event body.</p>"
            "<article><h2>Related project</h2><p>Completely separate event.</p>"
            "</article></article>"
        )

        result = _service(html, judge=judge).evaluate(_candidate(title="Line 4 opens"))

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(judge.calls, 1)
        self.assertNotIn(
            "Completely separate event",
            judge.requests[0].principal_body_segments[0].text,
        )

    def test_t3_body_h1_p_document_does_not_require_main_or_article(self):
        judge = _SameEventJudge()
        html = (
            "<html><head><title>Line 4 opens</title></head><body>"
            "<h1>Line 4 opens</h1><p>The operator opened Line 4 after testing "
            "and safety approval.</p></body></html>"
        )

        result = _service(html, judge=judge).evaluate(_candidate(title="Line 4 opens"))

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(judge.calls, 1)
        self.assertEqual(
            result.provenance["principal_document_status"],
            "PRINCIPAL_DOCUMENT_ESTABLISHED",
        )

    def test_t4_headline_text_variation_does_not_create_structural_conflict(self):
        judge = _SameEventJudge()
        html = (
            "<html><head><title>Line 4 opens | Metro Authority</title>"
            "<meta property='og:title' content='Line 4 opens'></head><body>"
            "<article><h1>Line 4 opens — operator notice</h1>"
            "<p>The operator opened Line 4 after testing.</p>"
            "</article></body></html>"
        )

        result = _service(html, judge=judge).evaluate(_candidate(title="Line 4 opens"))

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(judge.calls, 1)
        self.assertNotIn("headline_conflict", result.provenance)

    def test_t5_xml_attributes_are_preserved_in_structural_facts(self):
        judge = _SameEventJudge()
        xml = (
            "<notice><div role='main' data-resource='operator-notice'>"
            "<h1>Line 4 opens</h1><p>The operator opened Line 4 after testing.</p>"
            "</div></notice>"
        )

        result = _service(xml, content_type="application/xml", judge=judge).evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.READY)
        main_nodes = [facts for facts in result.provenance["xml_nodes"] if facts["attributes"].get("role") == "main"]
        self.assertEqual(len(main_nodes), 1)
        self.assertEqual(main_nodes[0]["attributes"]["data-resource"], "operator-notice")

    def test_t6_xml_namespace_is_preserved_in_structural_facts(self):
        judge = _SameEventJudge()
        xml = (
            "<notice xmlns='urn:notice'><div role='main'><h1>Line 4 opens</h1>"
            "<p>The operator opened Line 4 after testing.</p></div></notice>"
        )

        result = _service(xml, content_type="application/xml", judge=judge).evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertIn("urn:notice", result.provenance["xml_namespaces"])
        self.assertTrue(
            any(node["namespace"] == "urn:notice" for node in result.provenance["xml_nodes"])
        )

    def test_t7_unsupported_rdf_graph_rejects_conservatively(self):
        judge = _SameEventJudge()
        rdf = (
            "<rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>"
            "<rdf:Description rdf:about='https://source.test/notice'>"
            "<headline>Line 4 opens</headline>"
            "<body rdf:resource='https://source.test/body'/></rdf:Description>"
            "</rdf:RDF>"
        )

        result = _service(rdf, content_type="application/rdf+xml", judge=judge).evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(judge.calls, 0)
        self.assertTrue(result.provenance["unsupported_structure"])
        self.assertEqual(result.provenance["unsupported_structure_reason"], "rdf_graph")

    def test_t8_interactive_only_principal_never_reports_established_without_segments(self):
        judge = _SameEventJudge()
        html = (
            "<html><body><main><h1>Line 4 opens</h1><a href='/more'>Read more</a>"
            "<button>Contact</button></main></body></html>"
        )

        result = _service(html, judge=judge).evaluate(_candidate(title="Line 4 opens"))

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(judge.calls, 0)
        self.assertNotEqual(
            result.provenance["principal_document_status"],
            "PRINCIPAL_DOCUMENT_ESTABLISHED",
        )
        self.assertEqual(result.provenance["principal_segment_ids"], [])

    def test_f1a_generic_main_div_sections_are_ambiguous(self):
        judge = _SameEventJudge()
        html = (
            "<main><h1>Line 4 opens</h1>"
            "<div><h2>Background</h2><p>The operator completed testing.</p></div>"
            "<div><h2>Commissioning</h2><p>The line opened after approval.</p></div>"
            "</main>"
        )

        result = _service(html, judge=judge).evaluate(_candidate(title="Line 4 opens"))

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(judge.calls, 0)
        self.assertEqual(
            result.provenance["principal_document_status"],
            "PRINCIPAL_DOCUMENT_AMBIGUOUS",
        )

    def test_f1b_article_with_explicit_sections_remains_one_document(self):
        judge = _SameEventJudge()
        html = (
            "<article><header><h1>Line 4 opens</h1></header>"
            "<section><h2>Background</h2><p>The operator completed testing.</p></section>"
            "<section><h2>Commissioning</h2><p>The line opened after approval.</p></section>"
            "</article>"
        )

        result = _service(html, judge=judge).evaluate(_candidate(title="Line 4 opens"))

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(judge.calls, 1)
        self.assertIn("The operator completed testing", judge.requests[0].principal_body_segments[0].text)
        self.assertIn("The line opened after approval", judge.requests[0].principal_body_segments[0].text)

    def test_f2_title_site_name_suffix_with_matching_h1_is_eligible(self):
        judge = _SameEventJudge()
        html = (
            "<html><head><title>Line 4 opens | Metro Authority</title></head><body>"
            "<article><h1>Line 4 opens</h1><p>The operator opened Line 4 after testing.</p>"
            "</article></body></html>"
        )

        result = _service(html, judge=judge).evaluate(_candidate(title="Line 4 opens"))

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(judge.calls, 1)

    def test_f3_title_og_h1_presentation_variation_is_not_automatic_conflict(self):
        judge = _SameEventJudge()
        html = (
            "<html><head><title>Line 4 opens | Metro Authority</title>"
            "<meta property='og:title' content='Line 4 opens'></head><body>"
            "<article><h1>Line 4 opens — operator notice</h1>"
            "<p>The operator opened Line 4 after testing.</p></article>"
            "</body></html>"
        )

        result = _service(html, judge=judge).evaluate(_candidate(title="Line 4 opens"))

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(judge.calls, 1)

    def test_f4_multiple_principal_h1_ownership_rejects_conservatively(self):
        judge = _SameEventJudge()
        html = (
            "<main><h1>Line 4 opens</h1><h1>Line 2 closes</h1>"
            "<p>The operator published two competing principal headlines.</p></main>"
        )

        result = _service(html, judge=judge).evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.SOURCE_PAGE_MISMATCH)
        self.assertEqual(judge.calls, 0)
        self.assertEqual(result.provenance["headline_conflict_reasons"], ["multiple_principal_h1"])

    def test_f5_omitted_li_end_tags_keep_independent_units_separate(self):
        judge = _SameEventJudge()
        html = (
            "<main><ul><li><h2>Event one</h2><p>First event.</p>"
            "<li><h2>Event two</h2><p>Second event.</p></ul></main>"
        )

        result = _service(html, judge=judge).evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(judge.calls, 0)
        self.assertEqual(result.provenance["principal_document_status"], "PRINCIPAL_DOCUMENT_AMBIGUOUS")

    def test_f6_repairable_malformed_multi_document_html_never_reaches_judge(self):
        judge = _SameEventJudge()
        html = (
            "<main><ul><li><h2>Event one</h2><p>First event."
            "<li><h2>Event two</h2><p>Second event.</ul>"
            "<div>Unclosed trailing shell"
        )

        result = _service(html, judge=judge).evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(judge.calls, 0)
        self.assertEqual(result.provenance["principal_document_status"], "PRINCIPAL_DOCUMENT_AMBIGUOUS")

    def test_g1_generic_main_sibling_blocks_are_ambiguous(self):
        judge = _SameEventJudge()
        html = (
            "<main><h1>Line 4 opens</h1>"
            "<div><h2>Background</h2><p>The operator completed testing.</p></div>"
            "<div><h2>Commissioning</h2><p>The line opened after approval.</p></div>"
            "</main>"
        )

        result = _service(html, judge=judge).evaluate(_candidate(title="Line 4 opens"))

        self.assertEqual(result.provenance["principal_document_status"], "PRINCIPAL_DOCUMENT_AMBIGUOUS")
        self.assertEqual(judge.calls, 0)

    def test_g2_news_card_words_do_not_resolve_generic_structure(self):
        judge = _SameEventJudge()
        html = (
            "<main><h1>Latest News</h1>"
            "<div><h2>Line 4 opens</h2><p>The operator opened Line 4 after testing.</p></div>"
            "<div><h2>Line 2 closes</h2><p>A separate event closed Line 2 after a fault.</p></div>"
            "</main>"
        )

        result = _service(html, judge=judge).evaluate(_candidate(title="Line 4 opens"))

        self.assertEqual(result.provenance["principal_document_status"], "PRINCIPAL_DOCUMENT_AMBIGUOUS")
        self.assertEqual(judge.calls, 0)

    def test_g3_both_generic_fixtures_stop_before_semantic_judge(self):
        fixtures = (
            "<main><h1>Line 4 opens</h1>"
            "<div><h2>Background</h2><p>The operator completed testing.</p></div>"
            "<div><h2>Commissioning</h2><p>The line opened after approval.</p></div></main>",
            "<main><h1>Latest News</h1>"
            "<div><h2>Line 4 opens</h2><p>The operator opened Line 4 after testing.</p></div>"
            "<div><h2>Line 2 closes</h2><p>A separate event closed Line 2 after a fault.</p></div></main>",
        )

        for html in fixtures:
            judge = _SameEventJudge()
            result = _service(html, judge=judge).evaluate(_candidate())
            self.assertEqual(result.state, EvidenceState.REJECTED)
            self.assertEqual(judge.calls, 0)

    def test_g4_article_with_normal_sections_is_established(self):
        judge = _SameEventJudge()
        html = (
            "<main><article><header><h1>Line 4 opens</h1></header>"
            "<section><h2>Background</h2><p>The operator completed testing.</p></section>"
            "<section><h2>Commissioning</h2><p>The line opened after approval.</p></section>"
            "</article></main>"
        )

        result = _service(html, judge=judge).evaluate(_candidate(title="Line 4 opens"))

        self.assertEqual(result.provenance["principal_document_status"], "PRINCIPAL_DOCUMENT_ESTABLISHED")
        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(judge.calls, 1)

    def test_g5_article_with_unresolved_generic_competitors_is_ambiguous(self):
        judge = _SameEventJudge()
        html = (
            "<main><article><header><h1>Line 4 opens</h1></header>"
            "<div><h2>Background</h2><p>The operator completed testing.</p></div>"
            "<div><h2>Separate notice</h2><p>A different notice concerns Line 2.</p></div>"
            "</article></main>"
        )

        result = _service(html, judge=judge).evaluate(_candidate(title="Line 4 opens"))

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.provenance["principal_document_status"], "PRINCIPAL_DOCUMENT_AMBIGUOUS")
        self.assertEqual(judge.calls, 0)

    def test_g6_previous_f1_to_f6_regressions_remain_correct(self):
        for regression in (
            self.test_f1a_generic_main_div_sections_are_ambiguous,
            self.test_f1b_article_with_explicit_sections_remains_one_document,
            self.test_f2_title_site_name_suffix_with_matching_h1_is_eligible,
            self.test_f3_title_og_h1_presentation_variation_is_not_automatic_conflict,
            self.test_f4_multiple_principal_h1_ownership_rejects_conservatively,
            self.test_f5_omitted_li_end_tags_keep_independent_units_separate,
            self.test_f6_repairable_malformed_multi_document_html_never_reaches_judge,
        ):
            regression()

    def test_boilerplate_share_contact_privacy_body_is_not_factual_substance(self):
        title = "Line 4 opens"
        html = (
            f"<html><body><h1>{title}</h1><footer>Share this article. Contact us. "
            "Privacy policy and cookie settings.</footer></body></html>"
        )
        result = _service(html, url="https://source.test/article/line-4-opens").evaluate(
            _candidate(title=title, url="https://source.test/article/line-4-opens")
        )

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.TITLE_ONLY)

    def test_genuine_event_body_is_factual_substance(self):
        title = "Line 4 opens"
        html = (
            f"<html><body><h1>{title}</h1><main><p>The operator opened Line 4 on 15 September 2026 "
            "after safety approval and final trial operations were completed.</p></main></body></html>"
        )
        result = _service(html, url="https://source.test/article/line-4-opens").evaluate(
            _candidate(title=title, url="https://source.test/article/line-4-opens")
        )

        self.assertEqual(result.state, EvidenceState.READY)

    def test_rss_feed_is_not_authoritative_evidence(self):
        feed = (
            "<rss><channel><title>Metro News Feed</title><item>"
            "<title>Line 4 opens</title><description>The operator opened Line 4 after testing.</description>"
            "</item></channel></rss>"
        )
        result = _service(
            feed,
            url="https://source.test/feed",
            content_type="application/rss+xml",
        ).evaluate(_candidate(title="Line 4 opens", url="https://source.test/feed"))

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.SOURCE_PAGE_MISMATCH)

    def test_atom_feed_is_not_authoritative_evidence(self):
        feed = (
            "<feed xmlns='http://www.w3.org/2005/Atom'><title>Metro News Feed</title><entry>"
            "<title>Line 4 opens</title><summary>The operator opened Line 4 after testing.</summary>"
            "</entry></feed>"
        )
        result = _service(
            feed,
            url="https://source.test/atom.xml",
            content_type="application/atom+xml",
        ).evaluate(_candidate(title="Line 4 opens", url="https://source.test/atom.xml"))

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.SOURCE_PAGE_MISMATCH)

    def test_no_headline_numeric_anchor_and_split_identity_is_rejected(self):
        body = (
            "<html><body><main><p>Line 4 maintenance continues. "
            "The operator said another station opens next month.</p></main></body></html>"
        )
        result = _service(
            body,
            url="https://source.test/plain",
            judge=_DifferentEventJudge(),
        ).evaluate(
            _candidate(title="Line 4 opens", url="https://source.test/plain")
        )

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.SOURCE_PAGE_MISMATCH)

    def test_no_headline_complete_event_identity_is_ready(self):
        body = (
            "<html><body><main><p>Metro operator commissions moving-block train control on Line 4 "
            "after integration testing was completed in September 2026. The bulletin describes "
            "onboard equipment, wayside interfaces, and the service date.</p></main></body></html>"
        )
        result = _service(body, url="https://source.test/plain").evaluate(
            _candidate(
                title="Metro operator commissions moving-block train control on Line 4",
                url="https://source.test/plain",
            )
        )

        self.assertEqual(result.state, EvidenceState.READY)

    def test_non_feed_xml_is_not_blindly_blocked(self):
        notice = (
            "<notice><h1>Line 4 opens</h1><main><div>The operator opened Line 4 on 15 September 2026 "
            "after safety approval and final testing were completed.</div></main></notice>"
        )
        result = _service(
            notice,
            url="https://source.test/notice.xml",
            content_type="application/xml",
        ).evaluate(_candidate(title="Line 4 opens", url="https://source.test/notice.xml"))

        self.assertEqual(result.state, EvidenceState.READY)

    def test_boilerplate_with_year_is_not_factual_substance(self):
        title = "Line 4 opens"
        html = (
            f"<html><body><h1>{title}</h1><footer><p>Copyright 2026 Metro Authority.</p>"
            "<p>All rights reserved worldwide for website visitors.</p></footer></body></html>"
        )
        result = _service(html, url="https://source.test/article/line-4-opens").evaluate(
            _candidate(title=title, url="https://source.test/article/line-4-opens")
        )

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.TITLE_ONLY)

    def test_wrong_event_body_is_not_accepted_by_primary_headline(self):
        title = "Line 4 opens"
        html = (
            f"<html><body><h1>{title}</h1><main><p>The operator reported annual ridership reached "
            "25 million passengers in 2026 after fare changes.</p></main></body></html>"
        )
        result = _service(
            html,
            url="https://source.test/article/line-4-opens",
            judge=_DifferentEventJudge(),
        ).evaluate(
            _candidate(title=title, url="https://source.test/article/line-4-opens")
        )

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.SOURCE_PAGE_MISMATCH)

    def test_paraphrased_primary_body_without_number_is_ready(self):
        title = "Metro launches predictive maintenance platform"
        html = (
            f"<html><body><h1>{title}</h1><main><p>The operator introduced the platform after "
            "extensive trials and will deploy it across the network to support maintenance teams."
            "</p></main></body></html>"
        )
        result = _service(html, url="https://source.test/article/predictive-maintenance").evaluate(
            _candidate(title=title, url="https://source.test/article/predictive-maintenance")
        )

        self.assertEqual(result.state, EvidenceState.READY)

    def test_no_headline_fuzzy_control_contract_match_is_rejected(self):
        body = (
            "<html><body><main><p>The metro awarded a train contract on Line 4 after procurement "
            "evaluation and supplier review.</p></main></body></html>"
        )
        result = _service(
            body,
            url="https://source.test/plain",
            judge=_DifferentEventJudge(),
        ).evaluate(
            _candidate(
                title="Metro train control on Line 4",
                url="https://source.test/plain",
            )
        )

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.SOURCE_PAGE_MISMATCH)

    def test_rss1_rdf_feed_is_not_authoritative_evidence(self):
        feed = (
            "<rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#' "
            "xmlns='http://purl.org/rss/1.0/'><channel><title>Metro News</title></channel>"
            "<item><title>Line 4 opens</title><description>The operator opened Line 4.</description>"
            "</item></rdf:RDF>"
        )
        result = _service(
            feed,
            url="https://source.test/feed.rdf",
            content_type="application/rdf+xml",
        ).evaluate(_candidate(title="Line 4 opens", url="https://source.test/feed.rdf"))

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.SOURCE_PAGE_MISMATCH)

    def test_non_feed_rdf_notice_is_not_blindly_blocked(self):
        notice = (
            "<rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>"
            "<notice><h1>Line 4 opens</h1><main><div>The operator opened Line 4 after "
            "safety approval and final testing were completed.</div></main></notice></rdf:RDF>"
        )
        result = _service(
            notice,
            url="https://source.test/notice.rdf",
            content_type="application/rdf+xml",
        ).evaluate(_candidate(title="Line 4 opens", url="https://source.test/notice.rdf"))

        self.assertEqual(result.state, EvidenceState.READY)

    def test_structured_original_publication_date_is_exposed_as_a_fact(self):
        raw_value = "2026-09-15T10:00:00Z"
        html = (
            "<html><head><meta property='article:published_time' "
            f"content='{raw_value}'></head><body><article><p>Metro operator "
            "commissioned a control system after testing.</p></article></body></html>"
        )

        result = _service(html).evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(len(result.source_date_facts), 1)
        fact = result.source_date_facts[0]
        self.assertEqual(fact.date_kind, SourceDateKind.ORIGINAL_PUBLICATION)
        self.assertEqual(fact.raw_date_value, raw_value)
        self.assertEqual(fact.principal_document_association, "C1")
        self.assertIn("meta[", fact.source_node_or_field_provenance)

    def test_jsonld_publication_and_modified_dates_remain_distinct_facts(self):
        html = (
            "<html><head><script type='application/ld+json'>"
            '{"@id":"https://source.test/article/line-4-control",'
            '"@type":"NewsArticle","datePublished":"2026-09-15",'
            '"dateModified":"2026-09-17"}'
            "</script></head><body><article><p>Metro operator commissioned "
            "a control system after testing.</p></article></body></html>"
        )

        result = _service(html).evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.READY)
        facts = {fact.date_kind: fact.raw_date_value for fact in result.source_date_facts}
        self.assertEqual(facts[SourceDateKind.ORIGINAL_PUBLICATION], "2026-09-15")
        self.assertEqual(facts[SourceDateKind.MODIFIED], "2026-09-17")

    def test_candidate_published_at_does_not_populate_source_date_facts(self):
        html = (
            "<html><body><article><p>Metro operator commissioned a control system "
            "after testing.</p></article></body></html>"
        )

        result = _service(html).evaluate(_candidate(published_at="2026-09-15T10:00:00Z"))

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(result.source_date_facts, ())

    def test_detached_date_metadata_is_not_principal_document_fact(self):
        html = (
            "<html><body><main><article><p>Metro operator commissioned a control "
            "system after testing.</p></article><aside><meta "
            "property='article:published_time' content='2026-09-15'></aside>"
            "</main></body></html>"
        )

        result = _service(html).evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(result.source_date_facts, ())

    def test_excluded_template_metadata_does_not_provide_source_date(self):
        html = (
            "<html><head><template><meta property='article:published_time' "
            "content='2026-09-15'></template></head><body><article><p>Metro "
            "operator commissioned a control system after testing.</p>"
            "</article></body></html>"
        )

        result = _service(html).evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(result.source_date_facts, ())

    def test_direct_head_jsonld_remains_a_source_date_carrier(self):
        html = (
            "<html><head><script type='application/ld+json'>"
            '{"@id":"https://source.test/article/line-4-control",'
            '"@type":"NewsArticle","datePublished":"2026-09-15"}'
            "</script></head><body><article><p>Metro operator commissioned "
            "a control system after testing.</p></article></body></html>"
        )

        result = _service(html).evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(len(result.source_date_facts), 1)
        self.assertEqual(
            result.source_date_facts[0].date_kind,
            SourceDateKind.ORIGINAL_PUBLICATION,
        )

    def test_excluded_template_jsonld_does_not_provide_source_date(self):
        html = (
            "<html><head><template><script type='application/ld+json'>"
            '{"@id":"https://source.test/article/line-4-control",'
            '"@type":"NewsArticle","datePublished":"2026-09-15"}'
            "</script></template></head><body><article><p>Metro operator "
            "commissioned a control system after testing.</p></article>"
            "</body></html>"
        )

        result = _service(html).evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(result.source_date_facts, ())

    def test_excluded_xml_comment_head_does_not_provide_source_date(self):
        xml = (
            "<notice><div role='comment'><head><meta "
            "property='article:published_time' content='2026-09-15' />"
            "</head></div><main><p>Metro operator commissioned a control "
            "system after testing.</p></main></notice>"
        )
        source = FetchedSource(
            url="https://source.test/article/line-4-control",
            content=xml,
            content_type="application/xml",
        )
        result = EvidenceService(
            lambda _url: source,
            semantic_judge=_SameEventJudge(),
        ).evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(result.source_date_facts, ())

    def test_excluded_xml_comment_jsonld_does_not_provide_source_date(self):
        xml = (
            "<notice><div role='comment'><head><script "
            "type='application/ld+json'>{&quot;@id&quot;:"
            "&quot;https://source.test/article/line-4-control&quot;,"
            "&quot;datePublished&quot;:&quot;2026-09-15&quot;}</script>"
            "</head></div><main><p>Metro operator commissioned a control "
            "system after testing.</p></main></notice>"
        )
        source = FetchedSource(
            url="https://source.test/article/line-4-control",
            content=xml,
            content_type="application/xml",
        )
        result = EvidenceService(
            lambda _url: source,
            semantic_judge=_SameEventJudge(),
        ).evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(result.source_date_facts, ())

    def test_subordinate_xml_head_meta_does_not_provide_source_date(self):
        xml = (
            "<notice><article><p>Metro operator commissioned Line 4 after "
            "final testing.</p><article><head><meta "
            "property='article:published_time' content='2026-09-15' />"
            "</head><p>Subordinate event body.</p></article></article>"
            "</notice>"
        )
        source = FetchedSource(
            url="https://source.test/article/line-4-control",
            content=xml,
            content_type="application/xml",
        )
        result = EvidenceService(
            lambda _url: source,
            semantic_judge=_SameEventJudge(),
        ).evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertIn("Metro operator commissioned Line 4", result.substantive_content)
        self.assertNotIn("Subordinate event body", result.substantive_content)
        self.assertEqual(result.source_date_facts, ())

    def test_subordinate_xml_head_jsonld_does_not_provide_source_date(self):
        xml = (
            "<notice><article><p>Metro operator commissioned Line 4 after "
            "final testing.</p><article><head><script "
            "type='application/ld+json'>{&quot;@id&quot;:"
            "&quot;https://source.test/article/line-4-control&quot;,"
            "&quot;datePublished&quot;:&quot;2026-09-15&quot;}</script>"
            "</head><p>Subordinate event body.</p></article></article>"
            "</notice>"
        )
        source = FetchedSource(
            url="https://source.test/article/line-4-control",
            content=xml,
            content_type="application/xml",
        )
        result = EvidenceService(
            lambda _url: source,
            semantic_judge=_SameEventJudge(),
        ).evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(result.source_date_facts, ())

    def test_exact_principal_head_subordinate_meta_does_not_provide_source_date(self):
        xml = (
            "<notice><article><head><article><p>Subordinate content.</p><meta "
            "property='article:published_time' content='2026-09-15' />"
            "</article></head><p>Metro operator commissioned Line 4 after "
            "final testing.</p></article></notice>"
        )
        source = FetchedSource(
            url="https://source.test/article/line-4-control",
            content=xml,
            content_type="application/xml",
        )
        result = EvidenceService(
            lambda _url: source,
            semantic_judge=_SameEventJudge(),
        ).evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertIn("Metro operator commissioned Line 4", result.substantive_content)
        self.assertEqual(result.source_date_facts, ())

    def test_exact_principal_head_subordinate_jsonld_does_not_provide_source_date(self):
        xml = (
            "<notice><article><head><article><script "
            "type='application/ld+json'>{&quot;@id&quot;:"
            "&quot;https://source.test/article/line-4-control&quot;,"
            "&quot;datePublished&quot;:&quot;2026-09-15&quot;}</script>"
            "</article></head><p>Metro operator commissioned Line 4 after "
            "final testing.</p></article></notice>"
        )
        source = FetchedSource(
            url="https://source.test/article/line-4-control",
            content=xml,
            content_type="application/xml",
        )
        result = EvidenceService(
            lambda _url: source,
            semantic_judge=_SameEventJudge(),
        ).evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(result.source_date_facts, ())

    def test_exact_principal_and_subordinate_head_meta_keep_only_principal_date(self):
        xml = (
            "<notice><article><head><meta property='article:published_time' "
            "content='2026-09-15' /><article><meta "
            "property='article:published_time' content='2020-01-01' />"
            "</article></head><p>Metro operator commissioned Line 4 after "
            "final testing.</p></article></notice>"
        )
        source = FetchedSource(
            url="https://source.test/article/line-4-control",
            content=xml,
            content_type="application/xml",
        )
        result = EvidenceService(
            lambda _url: source,
            semantic_judge=_SameEventJudge(),
        ).evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(
            [(fact.raw_date_value, fact.date_kind) for fact in result.source_date_facts],
            [("2026-09-15", SourceDateKind.ORIGINAL_PUBLICATION)],
        )

    def test_exact_principal_and_subordinate_head_jsonld_keep_only_principal_date(self):
        xml = (
            "<notice><article><head><script type='application/ld+json'>"
            "{&quot;@id&quot;:&quot;https://source.test/article/line-4-control&quot;,"
            "&quot;datePublished&quot;:&quot;2026-09-15&quot;}</script><article>"
            "<script type='application/ld+json'>{&quot;@id&quot;:"
            "&quot;https://source.test/article/line-4-control&quot;,"
            "&quot;datePublished&quot;:&quot;2020-01-01&quot;}</script>"
            "</article></head><p>Metro operator commissioned Line 4 after "
            "final testing.</p></article></notice>"
        )
        source = FetchedSource(
            url="https://source.test/article/line-4-control",
            content=xml,
            content_type="application/xml",
        )
        result = EvidenceService(
            lambda _url: source,
            semantic_judge=_SameEventJudge(),
        ).evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(
            [(fact.raw_date_value, fact.date_kind) for fact in result.source_date_facts],
            [("2026-09-15", SourceDateKind.ORIGINAL_PUBLICATION)],
        )

    def test_principal_and_subordinate_xml_meta_keep_only_principal_date(self):
        xml = (
            "<notice><head><meta property='article:published_time' "
            "content='2026-09-15' /></head><article><p>Metro operator "
            "commissioned Line 4 after final testing.</p><article><head>"
            "<meta property='article:published_time' content='2020-01-01' />"
            "</head><p>Subordinate event body.</p></article></article>"
            "</notice>"
        )
        source = FetchedSource(
            url="https://source.test/article/line-4-control",
            content=xml,
            content_type="application/xml",
        )
        result = EvidenceService(
            lambda _url: source,
            semantic_judge=_SameEventJudge(),
        ).evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(
            [(fact.raw_date_value, fact.date_kind) for fact in result.source_date_facts],
            [("2026-09-15", SourceDateKind.ORIGINAL_PUBLICATION)],
        )

    def test_principal_owned_xml_head_remains_a_source_date_carrier(self):
        xml = (
            "<notice><article><head><meta property='article:published_time' "
            "content='2026-09-15' /></head><p>Metro operator commissioned "
            "Line 4 after final testing.</p></article></notice>"
        )
        source = FetchedSource(
            url="https://source.test/article/line-4-control",
            content=xml,
            content_type="application/xml",
        )
        result = EvidenceService(
            lambda _url: source,
            semantic_judge=_SameEventJudge(),
        ).evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(len(result.source_date_facts), 1)
        self.assertEqual(
            result.source_date_facts[0].raw_date_value,
            "2026-09-15",
        )

    def test_subordinate_xml_time_does_not_provide_source_date(self):
        xml = (
            "<notice><article><p>Metro operator commissioned Line 4 after "
            "final testing.</p><article><time itemprop='datePublished' "
            "datetime='2020-01-01' /><p>Subordinate event body.</p>"
            "</article></article></notice>"
        )
        source = FetchedSource(
            url="https://source.test/article/line-4-control",
            content=xml,
            content_type="application/xml",
        )
        result = EvidenceService(
            lambda _url: source,
            semantic_judge=_SameEventJudge(),
        ).evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(result.source_date_facts, ())

    def test_source_timezone_offset_is_preserved_without_conversion(self):
        raw_value = "2026-09-11T23:30:00-05:00"
        html = (
            "<html><head><meta property='article:published_time' "
            f"content='{raw_value}'></head><body><article><p>Metro operator "
            "issued a technical bulletin after testing.</p></article></body></html>"
        )

        result = _service(html).evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.READY)
        fact = result.source_date_facts[0]
        self.assertEqual(fact.raw_date_value, raw_value)
        self.assertEqual(fact.explicit_timezone_or_offset, "-05:00")

    def test_compact_source_timezone_offset_is_preserved_without_conversion(self):
        raw_value = "2026-09-15T10:00:00+0900"
        html = (
            "<html><head><meta property='article:published_time' "
            f"content='{raw_value}'></head><body><article><p>Metro operator "
            "issued a technical bulletin after testing.</p></article></body></html>"
        )

        result = _service(html).evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(result.source_date_facts[0].raw_date_value, raw_value)
        self.assertEqual(result.source_date_facts[0].explicit_timezone_or_offset, "+0900")

    def test_hour_only_source_timezone_offset_is_preserved_without_conversion(self):
        raw_value = "2026-09-15T10:00:00+09"
        html = (
            "<html><head><meta property='article:published_time' "
            f"content='{raw_value}'></head><body><article><p>Metro operator "
            "issued a technical bulletin after testing.</p></article></body></html>"
        )

        result = _service(html).evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(result.source_date_facts[0].raw_date_value, raw_value)
        self.assertEqual(result.source_date_facts[0].explicit_timezone_or_offset, "+09")

    def test_unparseable_structured_date_is_preserved_for_temporal(self):
        raw_value = "September ?? 2026"
        html = (
            "<html><head><meta property='article:published_time' "
            f"content='{raw_value}'></head><body><article><p>Metro operator "
            "issued a technical bulletin after testing.</p></article></body></html>"
        )

        result = _service(html).evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(result.source_date_facts[0].raw_date_value, raw_value)
        self.assertEqual(
            result.source_date_facts[0].date_kind,
            SourceDateKind.ORIGINAL_PUBLICATION,
        )

    def test_comment_time_is_not_principal_source_date(self):
        html = (
            "<html><body><article><p>Metro operator commissioned a control system "
            "after testing.</p><div role='comment'><time itemprop='datePublished' "
            "datetime='2020-01-01'>January 1, 2020</time></div></article></body></html>"
        )

        result = _service(html).evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(result.source_date_facts, ())

    def test_comment_and_reply_subtrees_are_excluded_from_principal_body(self):
        for relation in ("comment", "reply"):
            with self.subTest(relation=relation):
                html = (
                    "<html><body><article><h1>Line 4 opens</h1>"
                    "<p>The operator opened Line 4 after final testing.</p>"
                    f"<div role='{relation}'><p>Another unrelated event occurred "
                    "on Line 2.</p></div></article></body></html>"
                )

                result = _service(html).evaluate(_candidate())

                self.assertEqual(result.state, EvidenceState.READY)
                self.assertIn("Line 4 after final testing", result.substantive_content)
                self.assertNotIn("Another unrelated event occurred on Line 2", result.substantive_content)

    def test_normal_principal_div_remains_in_evidence_body(self):
        html = (
            "<html><body><article><p>Metro operator commissioned a control system "
            "after testing.</p><div><p>Principal technical details remain "
            "available.</p></div></article></body></html>"
        )

        result = _service(html).evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertIn("Principal technical details remain available", result.substantive_content)

    def test_principal_owned_time_is_exposed_as_original_publication(self):
        raw_value = "2026-09-15"
        html = (
            "<html><body><article><time itemprop='datePublished' "
            f"datetime='{raw_value}'>September 15, 2026</time><p>Metro operator "
            "commissioned a control system after testing.</p></article></body></html>"
        )

        result = _service(html).evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(len(result.source_date_facts), 1)
        self.assertEqual(
            result.source_date_facts[0].date_kind,
            SourceDateKind.ORIGINAL_PUBLICATION,
        )
        self.assertEqual(result.source_date_facts[0].raw_date_value, raw_value)

    def test_rejected_evidence_does_not_expose_source_date_facts(self):
        html = (
            "<html><head><meta property='article:published_time' "
            "content='2026-09-15'></head><body></body></html>"
        )

        result = _service(html).evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.source_date_facts, ())

    def test_p01_detached_xml_head_meta_does_not_provide_source_date(self):
        xml = (
            "<notice><section><head><meta property='article:published_time' "
            "content='2026-09-15' /></head></section><article><p>Principal "
            "metro event body.</p></article></notice>"
        )
        result = _service(xml, content_type="application/xml").evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(result.source_date_facts, ())

    def test_p01_detached_xml_head_jsonld_does_not_provide_source_date(self):
        xml = (
            "<notice><section><head><script type='application/ld+json'>"
            "{&quot;@id&quot;:&quot;https://source.test/article/line-4-control&quot;,"
            "&quot;datePublished&quot;:&quot;2026-09-15&quot;}</script>"
            "</head></section><article><p>Principal metro event body."
            "</p></article></notice>"
        )
        result = _service(xml, content_type="application/xml").evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(result.source_date_facts, ())

    def test_p02_excluded_canonical_does_not_replace_resource_identity(self):
        for excluded_region in ("aside", "template"):
            with self.subTest(excluded_region=excluded_region):
                html = (
                    f"<html><body><{excluded_region}><link rel='canonical' "
                    "href='https://source.test/unrelated' /></"
                    f"{excluded_region}><article><h1>Principal event</h1>"
                    "<p>Principal substantive metro event body.</p></article>"
                    "</body></html>"
                )
                result = _service(html).evaluate(_candidate())

                self.assertEqual(result.state, EvidenceState.READY)
                self.assertEqual(
                    result.canonical_source_url,
                    "https://source.test/article/line-4-control",
                )

    def test_p03_subordinate_og_title_is_not_principal_headline_metadata(self):
        xml = (
            "<notice><article><head><meta property='og:title' "
            "content='Line 4 opens' /><article><meta property='og:title' "
            "content='Other event' /></article></head><p>Principal metro "
            "event body.</p></article></notice>"
        )
        judge = _SameEventJudge()
        result = _service(
            xml,
            content_type="application/xml",
            judge=judge,
        ).evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(judge.requests[0].document_level_headlines, ("Line 4 opens",))

    def test_p03_subordinate_only_og_title_has_no_principal_authority(self):
        xml = (
            "<notice><article><head><article><meta property='og:title' "
            "content='Other event' /></article></head><p>Principal metro "
            "event body.</p></article></notice>"
        )
        judge = _SameEventJudge()
        result = _service(
            xml,
            content_type="application/xml",
            judge=judge,
        ).evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(judge.requests[0].document_level_headlines, ())

    def test_p04_outer_wrappers_do_not_borrow_subordinate_units(self):
        html = (
            "<html><body><article><h1>Principal event</h1><p>Principal "
            "metro event body.</p><div><article><h2>Other event A</h2>"
            "<p>Other event body A.</p></article></div><div><article>"
            "<h2>Other event B</h2><p>Other event body B.</p></article>"
            "</div></article></body></html>"
        )
        result = _service(html).evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertIn("Principal metro event body.", result.substantive_content)
        self.assertNotIn("Other event body A.", result.substantive_content)
        self.assertNotIn("Other event body B.", result.substantive_content)

    def test_p05_xml_tail_text_preserves_source_order_for_semantic_judge(self):
        fixtures = (
            (
                "<notice><article><p>First event fact.</p> Middle event "
                "fact. <p>Last event fact.</p></article></notice>",
                "First event fact. Middle event fact. Last event fact.",
            ),
            (
                "<notice><article><p>First event fact.</p> Middle event "
                "fact. <p>Second event fact.</p> Tail event fact. "
                "<p>Last event fact.</p></article></notice>",
                "First event fact. Middle event fact. Second event fact. "
                "Tail event fact. Last event fact.",
            ),
        )
        for xml, expected_body in fixtures:
            with self.subTest(expected_body=expected_body):
                judge = _SameEventJudge()
                result = _service(
                    xml,
                    content_type="application/xml",
                    judge=judge,
                ).evaluate(_candidate())

                self.assertEqual(result.state, EvidenceState.READY)
                self.assertEqual(result.substantive_content, expected_body)
                self.assertEqual(
                    judge.requests[0].principal_body_segments[0].text,
                    expected_body,
                )

    def test_p06_excluded_headline_descendants_do_not_enter_headline_text(self):
        fixtures = (
            (
                "text/html",
                "<html><body><article><h1>Principal headline "
                "<span role='comment'>Excluded words</span></h1><p>"
                "Principal metro event body.</p></article></body></html>",
            ),
            (
                "application/xml",
                "<notice><article><h1>Principal headline <span "
                "role='comment'>Excluded words</span></h1><p>Principal "
                "metro event body.</p></article></notice>",
            ),
        )
        for content_type, source in fixtures:
            with self.subTest(content_type=content_type):
                judge = _SameEventJudge()
                result = _service(
                    source,
                    content_type=content_type,
                    judge=judge,
                ).evaluate(_candidate())

                self.assertEqual(result.state, EvidenceState.READY)
                self.assertEqual(
                    judge.requests[0].document_level_headlines,
                    ("Principal headline",),
                )

    def test_p06_inline_headline_descendant_text_remains_owned(self):
        judge = _SameEventJudge()
        html = (
            "<html><body><article><h1>Metro <span>opens Line 4</span>"
            "</h1><p>Principal metro event body.</p></article></body></html>"
        )
        result = _service(html, judge=judge).evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(
            judge.requests[0].document_level_headlines,
            ("Metro opens Line 4",),
        )

    def test_headless_principal_og_title_is_owned_only_inside_principal(self):
        html = (
            "<html><body><main><meta property='og:title' "
            "content='Line 4 opens'><p>Principal metro event body.</p>"
            "</main></body></html>"
        )
        judge = _SameEventJudge()
        result = _service(
            html,
            judge=judge,
        ).evaluate(_candidate(title="Line 4 opens"))

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(
            judge.requests[0].document_level_headlines,
            ("Line 4 opens",),
        )

    def test_detached_headless_og_title_has_no_principal_authority(self):
        html = (
            "<html><body><section><meta property='og:title' "
            "content='Detached title'></section><main><p>Principal metro "
            "event body.</p></main></body></html>"
        )
        judge = _SameEventJudge()
        result = _service(html, judge=judge).evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(judge.requests[0].document_level_headlines, ())

    def test_xml_canonical_values_remain_empty(self):
        xml = (
            "<notice><head><link rel='canonical' "
            "href='https://source.test/other' /></head><article><p>"
            "Principal metro event body.</p></article></notice>"
        )
        assessment = assess_document(
            xml,
            "application/xml",
            resource_url="https://source.test/article/line-4-control",
        )

        self.assertEqual(
            assessment.principal_document_status,
            PrincipalDocumentStatus.PRINCIPAL_DOCUMENT_ESTABLISHED,
        )
        self.assertEqual(assessment.canonical_values, ())

    def test_self_comment_head_og_title_has_no_principal_authority(self):
        html = (
            "<html><head><meta property='og:title' content='Comment title' "
            "role='comment'></head><body><article><p>Principal metro event "
            "body.</p></article></body></html>"
        )
        judge = _SameEventJudge()
        result = _service(html, judge=judge).evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(judge.requests[0].document_level_headlines, ())

    def test_self_reply_headless_og_title_has_no_principal_authority(self):
        html = (
            "<html><body><main><meta property='og:title' "
            "content='Reply title' role='reply'><p>Principal metro event "
            "body.</p></main></body></html>"
        )
        judge = _SameEventJudge()
        result = _service(html, judge=judge).evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(judge.requests[0].document_level_headlines, ())

    def test_self_comment_canonical_has_no_authority(self):
        html = (
            "<html><head><link rel='canonical' "
            "href='https://source.test/unrelated' role='comment'></head>"
            "<body><article><p>Principal metro event body.</p></article>"
            "</body></html>"
        )
        result = _service(html).evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(
            result.canonical_source_url,
            "https://source.test/article/line-4-control",
        )

    def test_self_comment_jsonld_has_no_source_date(self):
        html = (
            "<html><head><script type='application/ld+json' role='comment'>"
            '{"@id":"https://source.test/article/line-4-control",'
            '"datePublished":"2026-09-15"}'
            "</script></head><body><article><p>Principal metro event "
            "body.</p></article></body></html>"
        )
        result = _service(html).evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(result.source_date_facts, ())


if __name__ == "__main__":
    unittest.main()
