"""Mechanical Google News RSS discovery adapter for Phase 2B.

The adapter consumes only a frozen :class:`SearchPlanItem`.  It owns no
market, capability, query, evidence, or domain decisions.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from datetime import timedelta, timezone
from email.utils import parsedate_to_datetime
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


class GoogleNewsRssDiagnosticReason(StrEnum):
    """Finite, mechanical reasons retained for provider failure forensics."""

    HTTP_OTHER_NON_200 = "HTTP_OTHER_NON_200"
    REDIRECT_OR_FINAL_URL_MISMATCH = "REDIRECT_OR_FINAL_URL_MISMATCH"
    RSS_PARSE_OR_SCHEMA_FAILURE = "RSS_PARSE_OR_SCHEMA_FAILURE"
    NETWORK = "NETWORK"
    TIMEOUT = "TIMEOUT"
    RATE_LIMIT = "RATE_LIMIT"
    AUTHENTICATION = "AUTHENTICATION"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class GoogleNewsRssDiagnostic:
    """Secret-free provider observation; it has no Search authority."""

    plan_item_id: str
    reason_code: GoogleNewsRssDiagnosticReason | str
    http_status: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.plan_item_id, str) or not self.plan_item_id.strip():
            raise ValueError("GoogleNewsRssDiagnostic requires plan_item_id")
        try:
            reason = GoogleNewsRssDiagnosticReason(self.reason_code)
        except (TypeError, ValueError) as exc:
            raise ValueError("GoogleNewsRssDiagnostic requires a finite reason code") from exc
        object.__setattr__(self, "reason_code", reason)
        if self.http_status is not None and (
            isinstance(self.http_status, bool)
            or not isinstance(self.http_status, int)
            or not 100 <= self.http_status <= 599
        ):
            raise ValueError("GoogleNewsRssDiagnostic http_status must be a valid HTTP status")


GoogleNewsRssDiagnosticSink = Callable[[GoogleNewsRssDiagnostic], object]


class _TransportResponseValidationError(ValueError):
    """A local transport-shape failure, distinct from malformed RSS content."""


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


def _emit_diagnostic(
    sink: GoogleNewsRssDiagnosticSink | None,
    diagnostic: GoogleNewsRssDiagnostic,
) -> None:
    if sink is None:
        return
    try:
        sink(diagnostic)
    except Exception:
        # Observability is passive and must never alter Search behavior.
        return


def _failure(
    item: SearchPlanItem,
    failure_class: SearchTechnicalFailureClass,
    *,
    diagnostic_sink: GoogleNewsRssDiagnosticSink | None,
    reason_code: GoogleNewsRssDiagnosticReason,
    http_status: int | None = None,
) -> SearchAttemptResult:
    result = SearchAttemptResult(
        item.plan_item_id,
        SearchTerminalStatus.TECHNICAL_FAILURE,
        technical_failure_class=failure_class,
    )
    _emit_diagnostic(
        diagnostic_sink,
        GoogleNewsRssDiagnostic(item.plan_item_id, reason_code, _safe_http_status(http_status)),
    )
    return result


def _safe_http_status(value: object) -> int | None:
    if (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 100 <= value <= 599
    ):
        return value
    return None


def _failure_class_for_status(status_code: int) -> SearchTechnicalFailureClass:
    if status_code in {401, 403}:
        return SearchTechnicalFailureClass.AUTHENTICATION
    if status_code == 429:
        return SearchTechnicalFailureClass.RATE_LIMIT
    return SearchTechnicalFailureClass.INVALID_RESPONSE


def _diagnostic_reason_for_status(status_code: int) -> GoogleNewsRssDiagnosticReason:
    if status_code in {401, 403}:
        return GoogleNewsRssDiagnosticReason.AUTHENTICATION
    if status_code == 429:
        return GoogleNewsRssDiagnosticReason.RATE_LIMIT
    return GoogleNewsRssDiagnosticReason.HTTP_OTHER_NON_200


def _response_parts(value: RssTransportResponse, request_url: str) -> tuple[bytes, int, str, Mapping[str, str]]:
    """Consume only the explicit transport contract; reject other shapes."""

    if not isinstance(value, RssTransportResponse):
        raise _TransportResponseValidationError("RSS transport requires RssTransportResponse")
    body = value.body
    status = value.status_code
    final_url = request_url if value.final_url == "" else value.final_url
    headers = {} if value.headers is None else value.headers

    if not isinstance(body, (bytes, str)) or not isinstance(status, int) or isinstance(status, bool):
        raise _TransportResponseValidationError("invalid RSS transport response")
    if not isinstance(final_url, str) or not final_url:
        raise _TransportResponseValidationError("invalid RSS response URL")
    if not isinstance(headers, Mapping):
        raise _TransportResponseValidationError("invalid RSS response headers")
    return (body.encode("utf-8") if isinstance(body, str) else body), status, final_url, headers


# One day of slack on each side absorbs time-zone differences between the
# provider's UTC timestamps and the report period.
WINDOW_SLACK = timedelta(days=1)


def published_within(published_at: str, window) -> bool:
    """Whether a result's own publication time can fall inside the window.

    RC-12: this only scopes discovery to the requested period, the same way
    the provider's date operators do; a missing or unparseable timestamp is
    kept, and Temporal remains the sole owner of date validity.
    """

    try:
        published = parsedate_to_datetime(published_at).astimezone(timezone.utc).date()
    except (TypeError, ValueError, IndexError):
        return True
    return window.start - WINDOW_SLACK <= published <= window.end + WINDOW_SLACK


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
        sources = [child for child in list(item) if _local_name(child.tag) == "source"]
        publisher_url = str(sources[0].attrib.get("url", "")).strip() if len(sources) == 1 else ""
        results.append(DiscoveryResult(title, url, publisher, published_at, snippet, publisher_url))
    return tuple(results)


class GoogleNewsRssProvider(SearchProvider):
    """One-request Google News RSS provider with no redirect or retry."""

    def __init__(
        self,
        transport: RssTransport | None = None,
        *,
        timeout_seconds: float = 10.0,
        diagnostic_sink: GoogleNewsRssDiagnosticSink | None = None,
    ) -> None:
        if isinstance(timeout_seconds, bool) or float(timeout_seconds) <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._timeout_seconds = float(timeout_seconds)
        self._transport = transport or _default_transport
        if diagnostic_sink is not None and not callable(diagnostic_sink):
            raise TypeError("diagnostic_sink must be callable or None")
        self._diagnostic_sink = diagnostic_sink

    @staticmethod
    def request_url(item: SearchPlanItem) -> str:
        if not isinstance(item, SearchPlanItem):
            raise TypeError("GoogleNewsRssProvider requires a SearchPlanItem")
        if item.provider_target is not SearchProviderId.GOOGLE_NEWS_RSS:
            raise ValueError("GoogleNewsRssProvider requires google_news_rss")
        encoding = item.provider_encoding
        q = item.query
        if item.search_window is not None:
            # Google News date operators; "before" is exclusive.
            q = f"{q} after:{item.search_window.start.isoformat()} before:{(item.search_window.end + timedelta(days=1)).isoformat()}"
        query = urlencode(
            (
                ("q", q),
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
                return _failure(
                    request,
                    _failure_class_for_status(status),
                    diagnostic_sink=self._diagnostic_sink,
                    reason_code=_diagnostic_reason_for_status(status),
                    http_status=status,
                )
            if final_url != url or any(
                str(key).casefold() == "location" for key in headers
            ):
                return _failure(
                    request,
                    SearchTechnicalFailureClass.INVALID_RESPONSE,
                    diagnostic_sink=self._diagnostic_sink,
                    reason_code=GoogleNewsRssDiagnosticReason.REDIRECT_OR_FINAL_URL_MISMATCH,
                    http_status=status,
                )
            results = _parse_rss(body)
            if request.search_window is not None:
                results = tuple(result for result in results if published_within(result.published_at, request.search_window))
            if not results:
                return SearchAttemptResult(request.plan_item_id, SearchTerminalStatus.SUCCESS_ZERO_RESULTS)
            return SearchAttemptResult(
                request.plan_item_id,
                SearchTerminalStatus.SUCCESS_WITH_RESULTS,
                results,
            )
        except HTTPError as exc:
            return _failure(
                request,
                _failure_class_for_status(exc.code),
                diagnostic_sink=self._diagnostic_sink,
                reason_code=_diagnostic_reason_for_status(exc.code),
                http_status=exc.code,
            )
        except TimeoutError:
            return _failure(
                request,
                SearchTechnicalFailureClass.TIMEOUT,
                diagnostic_sink=self._diagnostic_sink,
                reason_code=GoogleNewsRssDiagnosticReason.TIMEOUT,
            )
        except URLError as exc:
            reason = getattr(exc, "reason", None)
            if isinstance(reason, TimeoutError):
                failure_class = SearchTechnicalFailureClass.TIMEOUT
                diagnostic_reason = GoogleNewsRssDiagnosticReason.TIMEOUT
            else:
                failure_class = SearchTechnicalFailureClass.NETWORK
                diagnostic_reason = GoogleNewsRssDiagnosticReason.NETWORK
            return _failure(
                request,
                failure_class,
                diagnostic_sink=self._diagnostic_sink,
                reason_code=diagnostic_reason,
            )
        except _TransportResponseValidationError:
            return _failure(
                request,
                SearchTechnicalFailureClass.INVALID_RESPONSE,
                diagnostic_sink=self._diagnostic_sink,
                reason_code=GoogleNewsRssDiagnosticReason.RSS_PARSE_OR_SCHEMA_FAILURE,
            )
        except (ElementTree.ParseError, ValueError, TypeError, UnicodeError):
            return _failure(
                request,
                SearchTechnicalFailureClass.INVALID_RESPONSE,
                diagnostic_sink=self._diagnostic_sink,
                reason_code=GoogleNewsRssDiagnosticReason.RSS_PARSE_OR_SCHEMA_FAILURE,
            )
        except OSError:
            return _failure(
                request,
                SearchTechnicalFailureClass.NETWORK,
                diagnostic_sink=self._diagnostic_sink,
                reason_code=GoogleNewsRssDiagnosticReason.NETWORK,
            )
        except Exception:
            return _failure(
                request,
                SearchTechnicalFailureClass.UNKNOWN,
                diagnostic_sink=self._diagnostic_sink,
                reason_code=GoogleNewsRssDiagnosticReason.UNKNOWN,
            )


__all__ = [
    "GOOGLE_NEWS_RSS_ENDPOINT",
    "GoogleNewsRssProvider",
    "GoogleNewsRssDiagnostic",
    "GoogleNewsRssDiagnosticReason",
    "GoogleNewsRssDiagnosticSink",
    "RssTransportResponse",
]
