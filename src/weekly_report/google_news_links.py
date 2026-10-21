"""Resolve Google News discovery links to their publisher article URLs (RC-11).

Google News RSS items link to ``news.google.com`` redirect pages, not to the
publisher article. Resolution is part of EvidenceService's acquisition
responsibility: it only finds which publisher URL the discovery link points
to. The publisher page is then fetched and judged like any other source; no
Google page, title or snippet ever becomes Evidence.

Older article IDs embed the publisher URL and decode offline. Current IDs are
resolved through Google News' own article endpoint (one page request for the
signing parameters, one ``batchexecute`` request for the URL).
"""

from __future__ import annotations

import base64
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

GOOGLE_NEWS_HOST = "news.google.com"
_ARTICLE_PATH = re.compile(r"^/(?:rss/)?(?:articles|read)/([A-Za-z0-9_-]+)")
_SIGNATURE = re.compile(r'data-n-a-sg="([^"]+)"')
_TIMESTAMP = re.compile(r'data-n-a-ts="(\d+)"')
_BATCH_ENDPOINT = "https://news.google.com/_/DotsSplashUi/data/batchexecute"
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Weekly-report-v2-EvidenceService/1.0"

# (method, url, headers, body, timeout) -> (status, text)
LinkTransport = Callable[[str, str, dict[str, str], bytes | None, float], tuple[int, str]]


class LinkResolutionFailure(StrEnum):
    UNRESOLVABLE = "UNRESOLVABLE"
    TRANSPORT = "TRANSPORT"


class LinkResolutionError(RuntimeError):
    def __init__(self, failure: LinkResolutionFailure, detail: str) -> None:
        super().__init__(f"{failure.value}: {detail}")
        self.failure = failure
        self.detail = detail


@dataclass(frozen=True, slots=True)
class LinkResolution:
    discovery_url: str
    publisher_url: str
    method: str
    requests: int


def is_google_news_article_url(url: str) -> bool:
    return google_news_article_id(url) is not None


def google_news_article_id(url: str) -> str | None:
    try:
        parts = urlsplit(str(url or ""))
    except ValueError:
        return None
    if (parts.hostname or "").casefold() != GOOGLE_NEWS_HOST:
        return None
    match = _ARTICLE_PATH.match(parts.path)
    return match.group(1) if match else None


def _publisher_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parts = urlsplit(value.strip())
    except ValueError:
        return None
    host = (parts.hostname or "").casefold()
    if parts.scheme not in {"http", "https"} or not host or host == "google.com" or host.endswith(".google.com"):
        return None
    return value.strip()


def decode_legacy_article_id(article_id: str) -> str | None:
    """Decode an older article ID that embeds the publisher URL; else None."""

    try:
        raw = base64.urlsafe_b64decode(article_id + "=" * (-len(article_id) % 4))
    except (ValueError, TypeError):
        return None
    prefix = b"\x08\x13\x22"
    if not raw.startswith(prefix):
        return None
    rest = raw[len(prefix):]
    if not rest:
        return None
    length, offset = rest[0], 1
    if length & 0x80:
        if len(rest) < 2:
            return None
        length, offset = (length & 0x7F) | (rest[1] << 7), 2
    candidate = rest[offset:offset + length]
    if candidate.startswith(b"AU_yqL"):
        return None
    try:
        return _publisher_url(candidate.decode("utf-8"))
    except UnicodeDecodeError:
        return None


def _default_transport(method: str, url: str, headers: dict[str, str], body: bytes | None, timeout: float) -> tuple[int, str]:
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            return int(getattr(response, "status", 200) or 200), response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        return int(exc.code), ""


class GoogleNewsLinkResolver:
    """Find the publisher URL a Google News discovery link points to."""

    def __init__(self, transport: LinkTransport | None = None, *, timeout_seconds: float = 10.0) -> None:
        self._transport = transport or _default_transport
        self._timeout = float(timeout_seconds)

    def resolve(self, url: str) -> LinkResolution:
        article_id = google_news_article_id(url)
        if article_id is None:
            raise LinkResolutionError(LinkResolutionFailure.UNRESOLVABLE, "not a Google News article link")
        legacy = decode_legacy_article_id(article_id)
        if legacy is not None:
            return LinkResolution(url, legacy, "LEGACY_ID_DECODE", 0)
        requests = 0
        try:
            status, page = self._transport(
                "GET",
                f"https://{GOOGLE_NEWS_HOST}/rss/articles/{article_id}",
                {"User-Agent": _USER_AGENT, "Accept": "text/html"},
                None,
                self._timeout,
            )
            requests += 1
            if status != 200:
                raise LinkResolutionError(LinkResolutionFailure.TRANSPORT, f"article page HTTP {status}")
            signature, timestamp = _SIGNATURE.search(page), _TIMESTAMP.search(page)
            if not signature or not timestamp:
                raise LinkResolutionError(LinkResolutionFailure.UNRESOLVABLE, "article page has no signing parameters")
            inner = (
                '["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,null,null,null,null,null,0,1],'
                f'"X","X",1,[1,1,1],1,1,null,0,0,null,0],"{article_id}",{timestamp.group(1)},"{signature.group(1)}"]'
            )
            body = ("f.req=" + quote(json.dumps([[["Fbv4je", inner]]], separators=(",", ":")))).encode("utf-8")
            status, text = self._transport(
                "POST",
                _BATCH_ENDPOINT,
                {"User-Agent": _USER_AGENT, "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
                body,
                self._timeout,
            )
            requests += 1
        except LinkResolutionError:
            raise
        except (TimeoutError, URLError, OSError) as exc:
            raise LinkResolutionError(LinkResolutionFailure.TRANSPORT, type(exc).__name__) from None
        if status != 200:
            raise LinkResolutionError(LinkResolutionFailure.TRANSPORT, f"batchexecute HTTP {status}")
        publisher = _parse_batch_response(text)
        if publisher is None:
            raise LinkResolutionError(LinkResolutionFailure.UNRESOLVABLE, "batchexecute returned no publisher URL")
        return LinkResolution(url, publisher, "GOOGLE_NEWS_ARTICLE_ENDPOINT", requests)


def _parse_batch_response(text: str) -> str | None:
    try:
        payload = json.loads(text.split("\n\n", 1)[1])
        for row in payload:
            if isinstance(row, list) and len(row) > 2 and row[0] == "wrb.fr" and isinstance(row[2], str):
                decoded = json.loads(row[2])
                if isinstance(decoded, list) and len(decoded) > 1:
                    return _publisher_url(decoded[1])
    except (IndexError, ValueError, TypeError):
        return None
    return None


def same_publisher(publisher_url: str, resolved_url: str) -> bool | None:
    """Whether the resolved article belongs to the declared publisher origin.

    None when the discovery provider declared no origin.
    """

    def host(value: str) -> str:
        try:
            name = (urlsplit(value).hostname or "").casefold()
        except ValueError:
            return ""
        return name[4:] if name.startswith("www.") else name

    declared, resolved = host(publisher_url), host(resolved_url)
    if not declared:
        return None
    if not resolved:
        return False
    return declared == resolved or resolved.endswith("." + declared) or declared.endswith("." + resolved)


__all__ = [
    "GOOGLE_NEWS_HOST",
    "GoogleNewsLinkResolver",
    "LinkResolution",
    "LinkResolutionError",
    "LinkResolutionFailure",
    "decode_legacy_article_id",
    "google_news_article_id",
    "is_google_news_article_url",
    "same_publisher",
]
