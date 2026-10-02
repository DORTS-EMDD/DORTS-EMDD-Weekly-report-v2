from __future__ import annotations

from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from unittest import TestCase
from unittest.mock import Mock

from src.weekly_report.contracts import (
    DiscoveryIntent,
    GoogleNewsRssEncoding,
    RegionMode,
    SearchPlanItem,
    SearchProvider,
    SearchTechnicalFailureClass,
    SearchTerminalStatus,
)
from src.weekly_report.google_news_rss_provider import (
    GoogleNewsRssProvider,
    RssTransportResponse,
)


def _item() -> SearchPlanItem:
    return SearchPlanItem(
        "item-1",
        "market",
        RegionMode.SELECTED,
        DiscoveryIntent.TECHNOLOGY,
        "zh",
        "family",
        "google_news_rss",
        "  exact rail query  ",
        GoogleNewsRssEncoding("zh-TW", "TW", "TW:zh-Hant"),
        "zh-TW",
    )


VALID_RSS = b"""<?xml version='1.0'?><rss version='2.0'><channel><title>feed</title>
<item><title>Story</title><link>https://news.example/story</link><source>Publisher</source>
<pubDate>2026-01-01</pubDate><description>Snippet</description></item></channel></rss>"""
EMPTY_RSS = b"<rss version='2.0'><channel><title>feed</title></channel></rss>"


class GoogleNewsRssProviderTests(TestCase):
    def test_protocol_and_exact_request_encoding(self) -> None:
        calls: list[str] = []

        def transport(url: str, timeout: float):
            calls.append(url)
            return RssTransportResponse(EMPTY_RSS)

        provider = GoogleNewsRssProvider(transport)
        self.assertIsInstance(provider, SearchProvider)
        result = provider.execute(_item())
        self.assertEqual(result.status, SearchTerminalStatus.SUCCESS_ZERO_RESULTS)
        self.assertEqual(len(calls), 1)
        parsed = parse_qs(urlsplit(calls[0]).query, keep_blank_values=True)
        self.assertEqual(parsed["q"], ["  exact rail query  "])
        self.assertEqual(parsed["hl"], ["zh-TW"])
        self.assertEqual(parsed["gl"], ["TW"])
        self.assertEqual(parsed["ceid"], ["TW:zh-Hant"])

    def test_valid_rss_is_parsed_mechanically(self) -> None:
        result = GoogleNewsRssProvider(lambda url, timeout: RssTransportResponse(VALID_RSS)).execute(_item())
        self.assertEqual(result.status, SearchTerminalStatus.SUCCESS_WITH_RESULTS)
        self.assertEqual(len(result.results), 1)
        self.assertEqual(result.results[0].title, "Story")
        self.assertEqual(result.results[0].url, "https://news.example/story")
        self.assertEqual(result.results[0].publisher, "Publisher")

    def test_empty_rss_is_legal_zero_result(self) -> None:
        result = GoogleNewsRssProvider(lambda url, timeout: RssTransportResponse(EMPTY_RSS)).execute(_item())
        self.assertEqual(result.status, SearchTerminalStatus.SUCCESS_ZERO_RESULTS)
        self.assertEqual(result.results, ())

    def test_malformed_xml_and_malformed_row_are_whole_item_failures(self) -> None:
        malformed = GoogleNewsRssProvider(lambda url, timeout: RssTransportResponse(b"<rss>")).execute(_item())
        self.assertEqual(malformed.technical_failure_class, SearchTechnicalFailureClass.INVALID_RESPONSE)
        bad_row = b"<rss><channel><item><title>ok</title></item></channel></rss>"
        result = GoogleNewsRssProvider(lambda url, timeout: RssTransportResponse(bad_row)).execute(_item())
        self.assertEqual(result.status, SearchTerminalStatus.TECHNICAL_FAILURE)
        self.assertEqual(result.results, ())
        self.assertEqual(result.technical_failure_class, SearchTechnicalFailureClass.INVALID_RESPONSE)

    def test_redirect_is_rejected_without_following(self) -> None:
        calls: list[str] = []

        def transport(url: str, timeout: float):
            calls.append(url)
            return RssTransportResponse(VALID_RSS, status_code=302, final_url="https://other.example")

        result = GoogleNewsRssProvider(transport).execute(_item())
        self.assertEqual(result.technical_failure_class, SearchTechnicalFailureClass.INVALID_RESPONSE)
        self.assertEqual(len(calls), 1)

    def test_transport_failures_are_finite_and_safe(self) -> None:
        for error, expected in (
            (TimeoutError("secret"), SearchTechnicalFailureClass.TIMEOUT),
            (OSError("secret"), SearchTechnicalFailureClass.NETWORK),
            (RuntimeError("secret"), SearchTechnicalFailureClass.UNKNOWN),
        ):
            result = GoogleNewsRssProvider(lambda url, timeout, error=error: (_ for _ in ()).throw(error)).execute(_item())
            self.assertEqual(result.technical_failure_class, expected)

    def test_provider_does_not_retry(self) -> None:
        calls = 0

        def transport(url: str, timeout: float):
            nonlocal calls
            calls += 1
            raise OSError("network")

        result = GoogleNewsRssProvider(transport).execute(_item())
        self.assertEqual(result.status, SearchTerminalStatus.TECHNICAL_FAILURE)
        self.assertEqual(calls, 1)

    def test_http_status_classification_is_transport_representation_parity(self) -> None:
        expected = {
            401: SearchTechnicalFailureClass.AUTHENTICATION,
            403: SearchTechnicalFailureClass.AUTHENTICATION,
            429: SearchTechnicalFailureClass.RATE_LIMIT,
            302: SearchTechnicalFailureClass.INVALID_RESPONSE,
            500: SearchTechnicalFailureClass.INVALID_RESPONSE,
        }
        for status, failure_class in expected.items():
            with self.subTest(status=status):
                ordinary = GoogleNewsRssProvider(
                    lambda url, timeout, status=status: RssTransportResponse(b"", status_code=status)
                ).execute(_item())

                def raise_http_error(url, timeout, status=status):
                    raise HTTPError(url, status, "synthetic status", {}, None)

                exceptional = GoogleNewsRssProvider(raise_http_error).execute(_item())
                self.assertEqual(ordinary.technical_failure_class, failure_class)
                self.assertEqual(exceptional.technical_failure_class, failure_class)

    def test_speculative_transport_shapes_are_rejected_without_inspection(self) -> None:
        arbitrary = Mock(body=EMPTY_RSS, status_code=200, final_url="", headers={})
        for value in (EMPTY_RSS, EMPTY_RSS.decode(), {"body": EMPTY_RSS}, arbitrary):
            with self.subTest(value_type=type(value).__name__):
                calls = []

                def transport(url, timeout):
                    calls.append(url)
                    return value

                result = GoogleNewsRssProvider(transport).execute(_item())
                self.assertEqual(result.technical_failure_class, SearchTechnicalFailureClass.INVALID_RESPONSE)
                self.assertEqual(len(calls), 1)
                self.assertEqual(result.results, ())
        arbitrary.read.assert_not_called()
        arbitrary.geturl.assert_not_called()

    def test_raw_url_and_metadata_are_preserved_without_trimming(self) -> None:
        body = b"""<rss><channel><item><title> Story </title>
<link> https://news.example/story </link><source> Publisher </source>
<pubDate> 2026-01-01 </pubDate><description> Snippet </description>
</item></channel></rss>"""
        result = GoogleNewsRssProvider(lambda url, timeout: RssTransportResponse(body)).execute(_item())
        self.assertEqual(result.status, SearchTerminalStatus.SUCCESS_WITH_RESULTS)
        self.assertEqual(result.results[0].url, " https://news.example/story ")
        self.assertEqual(result.results[0].title, " Story ")
        self.assertEqual(result.results[0].publisher, " Publisher ")
        self.assertEqual(result.results[0].published_at, " 2026-01-01 ")
        self.assertEqual(result.results[0].snippet, " Snippet ")
