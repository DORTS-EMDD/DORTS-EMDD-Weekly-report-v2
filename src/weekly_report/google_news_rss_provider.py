"""Mechanical Google News RSS discovery adapter for Phase 2B.

The adapter consumes only a frozen :class:`SearchPlanItem`.  It owns no
market, capability, query, evidence, or domain decisions.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener
from xml.etree import ElementTree

from .contracts import (
    DiscoveryResult,
    SearchAttemptResult,
    SearchPlanItem,
    SearchProvider,
    SearchProviderId,
    SearchTechnicalFailureClass,
    SearchTerminalStatus,
)


GOOGLE_NEWS_RSS_ENDPOINT = "https://news.google.com/rss/search"
GOOGLE_NEWS_RSS_USER_AGENT = "Weekly-report-v2-Search/1.0"


@dataclass(frozen=True, slots=True)
class RssTransportResponse:
    """The explicit response contract for the injectable RSS transport."""

    body: bytes | str
    status_code: int = 200
    final_url: str = ""
    headers: Mapping[str, str] | None = None


RssTransport = Callable[[str, float], RssTransportResponse]


class _NoRedirectHandler(HTTPRedirectHandler):
    """Make redirect responses terminal instead of following them."""

    def redirect_request(self, request, fp, code, msg, headers, newurl):  # noqa: D401
        return None


def _default_transport(url: str, timeout_seconds: float) -> RssTransportResponse:
    request = Request(
        url,
        headers={
            "Accept": "application/rss+xml, application/xml, text/xml",
            "User-Agent": GOOGLE_NEWS_RSS_USER_AGENT,
        },
        method="GET",
    )
    opener = build_opener(_NoRedirectHandler())
    with opener.open(request, timeout=timeout_seconds) as response:
        body = response.read()
        return RssTransportResponse(
            body=body,
            status_code=response.status,
            final_url=response.geturl(),
            headers=dict(response.headers.items()),
        )


def _failure(item: SearchPlanItem, failure_class: SearchTechnicalFailureClass) -> SearchAttemptResult:
    return SearchAttemptResult(
        item.plan_item_id,
        SearchTerminalStatus.TECHNICAL_FAILURE,
        technical_failure_class=failure_class,
    )


def _failure_class_for_status(status_code: int) -> SearchTechnicalFailureClass:
    if status_code in {401, 403}:
        return SearchTechnicalFailureClass.AUTHENTICATION
    if status_code == 429:
        return SearchTechnicalFailureClass.RATE_LIMIT
    return SearchTechnicalFailureClass.INVALID_RESPONSE


def _response_parts(value: RssTransportResponse, request_url: str) -> tuple[bytes, int, str, Mapping[str, str]]:
    """Consume only the explicit transport contract; reject other shapes."""

    if not isinstance(value, RssTransportResponse):
        raise TypeError("RSS transport requires RssTransportResponse")
    body = value.body
    status = value.status_code
    final_url = request_url if value.final_url == "" else value.final_url
    headers = {} if value.headers is None else value.headers

    if not isinstance(body, (bytes, str)) or not isinstance(status, int) or isinstance(status, bool):
        raise ValueError("invalid RSS transport response")
    if not isinstance(final_url, str) or not final_url:
        raise ValueError("invalid RSS response URL")
    if not isinstance(headers, Mapping):
        raise ValueError("invalid RSS response headers")
    return (body.encode("utf-8") if isinstance(body, str) else body), status, final_url, headers


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _single_text(parent: ElementTree.Element, name: str, *, required: bool) -> str:
    values = [child.text for child in list(parent) if _local_name(child.tag) == name]
    if len(values) > 1:
        raise ValueError("duplicate RSS field")
    if not values:
        if required:
            raise ValueError("missing RSS field")
        return ""
    value = values[0]
    if not isinstance(value, str) or not value.strip():
        if required:
            raise ValueError("empty RSS field")
        return ""
    return value


def _parse_rss(body: bytes) -> tuple[DiscoveryResult, ...]:
    root = ElementTree.fromstring(body)
    if _local_name(root.tag) != "rss":
        raise ValueError("unexpected RSS root")
    channels = [child for child in list(root) if _local_name(child.tag) == "channel"]
    if len(channels) != 1:
        raise ValueError("RSS channel is missing or ambiguous")
    results: list[DiscoveryResult] = []
    for item in list(channels[0]):
        if _local_name(item.tag) != "item":
            continue
        title = _single_text(item, "title", required=True)
        url = _single_text(item, "link", required=True)
        publisher = _single_text(item, "source", required=False)
        published_at = _single_text(item, "pubdate", required=False)
        snippet = _single_text(item, "description", required=False)
        results.append(DiscoveryResult(title, url, publisher, published_at, snippet))
    return tuple(results)


class GoogleNewsRssProvider(SearchProvider):
    """One-request Google News RSS provider with no redirect or retry."""

    def __init__(
        self,
        transport: RssTransport | None = None,
        *,
        timeout_seconds: float = 10.0,
    ) -> None:
        if isinstance(timeout_seconds, bool) or float(timeout_seconds) <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._timeout_seconds = float(timeout_seconds)
        self._transport = transport or _default_transport

    @staticmethod
    def request_url(item: SearchPlanItem) -> str:
        if not isinstance(item, SearchPlanItem):
            raise TypeError("GoogleNewsRssProvider requires a SearchPlanItem")
        if item.provider_target is not SearchProviderId.GOOGLE_NEWS_RSS:
            raise ValueError("GoogleNewsRssProvider requires google_news_rss")
        encoding = item.provider_encoding
        query = urlencode(
            (
                ("q", item.query),
                ("hl", encoding.hl),
                ("gl", encoding.gl),
                ("ceid", encoding.ceid),
            )
        )
        return f"{GOOGLE_NEWS_RSS_ENDPOINT}?{query}"

    def execute(self, request: SearchPlanItem) -> SearchAttemptResult:
        if not isinstance(request, SearchPlanItem):
            raise TypeError("GoogleNewsRssProvider requires a SearchPlanItem")
        url = self.request_url(request)
        try:
            response = self._transport(url, self._timeout_seconds)
            body, status, final_url, headers = _response_parts(response, url)
            if status != 200:
                return _failure(request, _failure_class_for_status(status))
            if final_url != url or any(
                str(key).casefold() == "location" for key in headers
            ):
                return _failure(request, SearchTechnicalFailureClass.INVALID_RESPONSE)
            results = _parse_rss(body)
            if not results:
                return SearchAttemptResult(request.plan_item_id, SearchTerminalStatus.SUCCESS_ZERO_RESULTS)
            return SearchAttemptResult(
                request.plan_item_id,
                SearchTerminalStatus.SUCCESS_WITH_RESULTS,
                results,
            )
        except HTTPError as exc:
            return _failure(request, _failure_class_for_status(exc.code))
        except TimeoutError:
            return _failure(request, SearchTechnicalFailureClass.TIMEOUT)
        except URLError as exc:
            reason = getattr(exc, "reason", None)
            if isinstance(reason, TimeoutError):
                failure_class = SearchTechnicalFailureClass.TIMEOUT
            else:
                failure_class = SearchTechnicalFailureClass.NETWORK
            return _failure(request, failure_class)
        except (ElementTree.ParseError, ValueError, TypeError, UnicodeError):
            return _failure(request, SearchTechnicalFailureClass.INVALID_RESPONSE)
        except OSError:
            return _failure(request, SearchTechnicalFailureClass.NETWORK)
        except Exception:
            return _failure(request, SearchTechnicalFailureClass.UNKNOWN)


__all__ = [
    "GOOGLE_NEWS_RSS_ENDPOINT",
    "GoogleNewsRssProvider",
    "RssTransportResponse",
]
