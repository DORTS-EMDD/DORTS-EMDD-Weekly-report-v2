"""RC-60 Search provider: official standards catalogue records (monthly check only).

One plan item is one monitored standard's configured record. The provider makes
one request for it (following redirects only within that source's own hosts),
reads the record's lifecycle entries with ``standards_catalogue`` and returns
as discovery results the entries dated inside the item's search window, plus
an undated superseding edition the record names. It decides nothing: Evidence,
Scope, Temporal, Category and Reportability judge each result like any other
Candidate. It is a second discovery provider beside Google News, not a fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
from email.utils import format_datetime
from datetime import datetime, timezone
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .contracts import (
    DiscoveryResult,
    SearchAttemptResult,
    SearchPlanItem,
    SearchProviderId,
    SearchTechnicalFailureClass,
    SearchTerminalStatus,
)
from .standards_catalogue import (
    CatalogueRecordError,
    CatalogueSource,
    parse_record,
    record_source,
    request_url,
    same_source_host,
)

STANDARDS_CATALOGUE_USER_AGENT = "Weekly-report-v2-Search/1.0"
_MAX_REDIRECTS = 3


@dataclass(frozen=True, slots=True)
class CatalogueResponse:
    status_code: int
    final_url: str
    body: str


CatalogueTransport = Callable[[str, float, CatalogueSource], CatalogueResponse]


class _SameSourceRedirects(HTTPRedirectHandler):
    def __init__(self, source: CatalogueSource) -> None:
        self._source = source
        self._hops = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self._hops += 1
        if self._hops > _MAX_REDIRECTS or not same_source_host(self._source, newurl):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _default_transport(url: str, timeout_seconds: float, source: CatalogueSource) -> CatalogueResponse:
    request = Request(url, headers={"User-Agent": STANDARDS_CATALOGUE_USER_AGENT, "Accept": "text/html"}, method="GET")
    with build_opener(_SameSourceRedirects(source)).open(request, timeout=timeout_seconds) as response:
        body = response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")
        return CatalogueResponse(response.status, response.geturl(), body)


def _rfc2822(day) -> str:
    return format_datetime(datetime(day.year, day.month, day.day, tzinfo=timezone.utc), usegmt=True)


class StandardsCatalogueProvider:
    """Execute catalogue plan items; one request per item, no retry."""

    def __init__(self, transport: CatalogueTransport | None = None, *, timeout_seconds: float = 20.0) -> None:
        self._transport = transport or _default_transport
        self._timeout_seconds = float(timeout_seconds)

    def execute(self, request: SearchPlanItem) -> SearchAttemptResult:
        if not isinstance(request, SearchPlanItem) or request.provider_target is not SearchProviderId.STANDARDS_CATALOGUE:
            raise TypeError("StandardsCatalogueProvider requires a standards_catalogue plan item")

        def failure(failure_class: SearchTechnicalFailureClass) -> SearchAttemptResult:
            return SearchAttemptResult(request.plan_item_id, SearchTerminalStatus.TECHNICAL_FAILURE,
                                       technical_failure_class=failure_class)

        try:
            source_name, locator = request.query.split(":", 1)
            source = CatalogueSource(source_name)
            url = request_url(source, locator)
        except ValueError:
            return failure(SearchTechnicalFailureClass.INVALID_RESPONSE)
        try:
            response = self._transport(url, self._timeout_seconds, source)
        except HTTPError as exc:
            return failure(SearchTechnicalFailureClass.AUTHENTICATION if exc.code in {401, 403}
                           else SearchTechnicalFailureClass.RATE_LIMIT if exc.code == 429
                           else SearchTechnicalFailureClass.INVALID_RESPONSE)
        except TimeoutError:
            return failure(SearchTechnicalFailureClass.TIMEOUT)
        except (URLError, OSError):
            return failure(SearchTechnicalFailureClass.NETWORK)
        if response.status_code != 200 or record_source(response.final_url) is not source:
            return failure(SearchTechnicalFailureClass.INVALID_RESPONSE)
        try:
            record = parse_record(source, response.body, response.final_url)
        except CatalogueRecordError:
            return failure(SearchTechnicalFailureClass.INVALID_RESPONSE)

        window = request.search_window
        results = []
        for entry in record.family:
            if entry.publication_date is None:
                # A superseding edition the record names but does not date:
                # discovery only; its own record supplies the date to Temporal.
                keep = entry.status == "Superseding"
            else:
                keep = window is None or window.start <= entry.publication_date <= window.end
            if keep:
                results.append(DiscoveryResult(
                    title=f"{entry.reference}: {record.title}" if record.title else entry.reference,
                    url=entry.url,
                    publisher=source.value,
                    published_at=_rfc2822(entry.publication_date) if entry.publication_date else "",
                    snippet=f"{entry.reference} {entry.status}".strip(),
                    publisher_url=entry.url,
                ))
        if not results:
            return SearchAttemptResult(request.plan_item_id, SearchTerminalStatus.SUCCESS_ZERO_RESULTS)
        return SearchAttemptResult(request.plan_item_id, SearchTerminalStatus.SUCCESS_WITH_RESULTS, tuple(results))


__all__ = ["CatalogueResponse", "STANDARDS_CATALOGUE_USER_AGENT", "StandardsCatalogueProvider"]
