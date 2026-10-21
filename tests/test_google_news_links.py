"""RC-11: Google News discovery links resolve to publisher articles in Evidence."""

from __future__ import annotations

import base64
import json
import unittest

from src.weekly_report.contracts import CanonicalCandidate, EvidenceState, FetchedSource
from src.weekly_report.evidence_service import EvidenceService
from src.weekly_report.google_news_links import (
    GoogleNewsLinkResolver,
    LinkResolutionError,
    LinkResolutionFailure,
    decode_legacy_article_id,
    google_news_article_id,
    same_publisher,
)
from src.weekly_report.google_news_rss_provider import _parse_rss

PUBLISHER = "https://www.railwaygazette.com/india/2026/10/13/chennai-yellow-line/"
LINK = "https://news.google.com/rss/articles/CBMiAU_yqLexample?oc=5"


def _batch_response(url: str) -> str:
    inner = json.dumps(["garturlres", url, 1])
    return ")]}'\n\n" + json.dumps([["wrb.fr", "Fbv4je", inner, None, None, None, "generic"]])


class _Transport:
    def __init__(self, *, page_status=200, page='<div jscontroller="x" data-n-a-sg="SIG" data-n-a-ts="1700000000">', batch_status=200, batch=None):
        self.page_status, self.page, self.batch_status = page_status, page, batch_status
        self.batch = _batch_response(PUBLISHER) if batch is None else batch
        self.calls = []

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append((method, url, body))
        if method == "GET":
            return self.page_status, self.page
        return self.batch_status, self.batch


class GoogleNewsLinkTests(unittest.TestCase):
    def test_article_id_only_for_google_news_article_links(self):
        self.assertEqual(google_news_article_id(LINK), "CBMiAU_yqLexample")
        self.assertIsNone(google_news_article_id("https://www.railwaygazette.com/a"))
        self.assertIsNone(google_news_article_id("https://news.google.com/rss/search?q=metro"))

    def test_legacy_ids_decode_offline(self):
        raw = b"\x08\x13\x22" + bytes([len(PUBLISHER)]) + PUBLISHER.encode() + b"\xd2\x01\x00"
        article_id = base64.urlsafe_b64encode(raw).decode().rstrip("=")
        self.assertEqual(decode_legacy_article_id(article_id), PUBLISHER)
        transport = _Transport()
        resolution = GoogleNewsLinkResolver(transport).resolve(f"https://news.google.com/rss/articles/{article_id}")
        self.assertEqual((resolution.publisher_url, resolution.method, resolution.requests), (PUBLISHER, "LEGACY_ID_DECODE", 0))
        self.assertEqual(transport.calls, [])

    def test_current_ids_resolve_with_two_requests(self):
        transport = _Transport()
        resolution = GoogleNewsLinkResolver(transport).resolve(LINK)
        self.assertEqual(resolution.publisher_url, PUBLISHER)
        self.assertEqual(resolution.requests, 2)
        self.assertEqual([call[0] for call in transport.calls], ["GET", "POST"])
        self.assertIn(b"Fbv4je", transport.calls[1][2])

    def test_failures_are_typed(self):
        cases = (
            (_Transport(page_status=429), LinkResolutionFailure.TRANSPORT),
            (_Transport(page="<html>consent</html>"), LinkResolutionFailure.UNRESOLVABLE),
            (_Transport(batch_status=503), LinkResolutionFailure.TRANSPORT),
            (_Transport(batch=_batch_response("https://news.google.com/x")), LinkResolutionFailure.UNRESOLVABLE),
            (_Transport(batch="garbage"), LinkResolutionFailure.UNRESOLVABLE),
        )
        for transport, failure in cases:
            with self.subTest(failure=failure), self.assertRaises(LinkResolutionError) as context:
                GoogleNewsLinkResolver(transport).resolve(LINK)
            self.assertIs(context.exception.failure, failure)

    def test_publisher_origin_comparison(self):
        self.assertTrue(same_publisher("https://www.railwaygazette.com", PUBLISHER))
        self.assertTrue(same_publisher("https://cnn.com", "https://edition.cnn.com/a"))
        self.assertFalse(same_publisher("https://www.railwaygazette.com", "https://example.com/a"))
        self.assertIsNone(same_publisher("", PUBLISHER))

    def test_rss_keeps_the_declared_publisher_origin(self):
        body = (
            '<rss><channel><item><title>t</title><link>' + LINK.replace("&", "&amp;") + '</link>'
            '<source url="https://www.railwaygazette.com">Railway Gazette</source></item></channel></rss>'
        ).encode()
        (result,) = _parse_rss(body)
        self.assertEqual((result.publisher, result.publisher_url), ("Railway Gazette", "https://www.railwaygazette.com"))


class PublicationWindowTests(unittest.TestCase):
    """RC-12: discovery keeps only results the provider dates inside the period."""

    def test_window_uses_provider_timestamps_with_one_day_slack(self):
        from datetime import date

        from src.weekly_report.contracts import SearchWindow
        from src.weekly_report.google_news_rss_provider import published_within

        window = SearchWindow(date(2026, 10, 14), date(2026, 10, 20))
        self.assertTrue(published_within("Wed, 15 Oct 2026 08:00:00 GMT", window))
        self.assertTrue(published_within("Mon, 13 Oct 2026 22:00:00 GMT", window))
        self.assertFalse(published_within("Sat, 11 Oct 2026 08:00:00 GMT", window))
        self.assertFalse(published_within("Fri, 03 Apr 2026 08:00:00 GMT", window))
        self.assertTrue(published_within("", window))
        self.assertTrue(published_within("not a date", window))

    def test_provider_drops_results_dated_outside_the_window(self):
        from datetime import date

        from src.weekly_report.contracts import (
            DiscoveryIntent,
            GoogleNewsRssEncoding,
            RegionMode,
            SearchPlanItem,
            SearchProviderId,
            SearchTerminalStatus,
            SearchWindow,
        )
        from src.weekly_report.google_news_rss_provider import GoogleNewsRssProvider, RssTransportResponse

        body = (
            "<rss><channel>"
            "<item><title>in</title><link>https://a.test/1</link><pubDate>Wed, 15 Oct 2026 08:00:00 GMT</pubDate></item>"
            "<item><title>old</title><link>https://a.test/2</link><pubDate>Fri, 03 Apr 2026 08:00:00 GMT</pubDate></item>"
            "</channel></rss>"
        ).encode()
        item = SearchPlanItem(
            "p1", "united_kingdom", RegionMode.SELECTED, DiscoveryIntent.TECHNOLOGY, "en", "family",
            SearchProviderId.GOOGLE_NEWS_RSS, "metro", GoogleNewsRssEncoding("en-GB", "GB", "GB:en"), "en-GB",
            search_window=SearchWindow(date(2026, 10, 14), date(2026, 10, 20)),
        )
        result = GoogleNewsRssProvider(lambda url, timeout: RssTransportResponse(body)).execute(item)
        self.assertEqual(result.status, SearchTerminalStatus.SUCCESS_WITH_RESULTS)
        self.assertEqual([entry.title for entry in result.results], ["in"])


class EvidenceLinkResolutionTests(unittest.TestCase):
    def _candidate(self, publisher_url="https://www.railwaygazette.com"):
        return CanonicalCandidate("C1", "Chennai Metro opens Yellow Line", LINK, "Railway Gazette", publisher_url=publisher_url)

    def test_evidence_fetches_the_publisher_article_not_the_google_page(self):
        fetched = []

        def fetcher(url):
            fetched.append(url)
            return FetchedSource(url=url, content="<html><body><p>short</p></body></html>", status_code=200, content_type="text/html", redirect_chain=(url,))

        result = EvidenceService(fetcher, link_resolver=GoogleNewsLinkResolver(_Transport())).evaluate(self._candidate())
        self.assertEqual(fetched, [PUBLISHER])
        self.assertEqual(result.provenance["discovery_url"], LINK)
        self.assertEqual(result.provenance["link_resolution"], "GOOGLE_NEWS_ARTICLE_ENDPOINT")
        self.assertEqual(result.provenance["publisher_origin_check"], "MATCH")
        self.assertNotIn("news.google.com", result.canonical_source_url)

    def test_publisher_origin_mismatch_is_rejected_without_fetching(self):
        fetched = []
        service = EvidenceService(lambda url: fetched.append(url), link_resolver=GoogleNewsLinkResolver(_Transport()))
        result = service.evaluate(self._candidate("https://www.another-publisher.com"))
        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.provenance["evidence_rejection_gate"], "SOURCE_PROVENANCE")
        self.assertEqual(result.provenance["source_provenance_mismatch_reason"], "PUBLISHER_ORIGIN_MISMATCH")
        self.assertEqual(fetched, [])

    def test_unresolved_link_is_never_fetched_or_used_as_evidence(self):
        fetched = []
        for service in (
            EvidenceService(lambda url: fetched.append(url)),
            EvidenceService(lambda url: fetched.append(url), link_resolver=GoogleNewsLinkResolver(_Transport(page_status=429))),
        ):
            result = service.evaluate(self._candidate())
            self.assertEqual(result.state, EvidenceState.REJECTED)
            self.assertEqual(result.provenance["evidence_rejection_gate"], "LINK_RESOLUTION")
        self.assertEqual(fetched, [])


if __name__ == "__main__":
    unittest.main()
