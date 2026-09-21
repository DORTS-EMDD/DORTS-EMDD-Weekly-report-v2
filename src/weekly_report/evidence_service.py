"""The first V2 production boundary: Canonical Candidate to Evidence result.

EvidenceService is the only module in this phase that decides whether a
source is EVIDENCE_READY. Transport and parsing helpers below return facts or
signals only; they do not create a second Evidence owner.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from html.parser import HTMLParser
import re
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .contracts import (
    CanonicalCandidate,
    EvidenceResult,
    EvidenceState,
    FetchedSource,
    RejectReason,
)


Fetcher = Callable[[str], FetchedSource | Mapping[str, Any] | object]


_STOPWORDS = {
    "a",
    "an",
    "and",
    "for",
    "from",
    "in",
    "is",
    "of",
    "on",
    "the",
    "to",
    "with",
}

_ACTION_TERMS = {
    "announced",
    "approved",
    "awarded",
    "awards",
    "began",
    "caused",
    "causes",
    "commissioned",
    "commissions",
    "completed",
    "deployed",
    "failed",
    "introduced",
    "installed",
    "issued",
    "launched",
    "opened",
    "procured",
    "procure",
    "procures",
    "procurement",
    "replaced",
    "restored",
    "signed",
    "started",
    "suspended",
    "suspends",
    "suspension",
    "tested",
    "trialled",
    "trialed",
    "事故",
    "公告",
    "啟用",
    "完成",
    "採購",
    "故障",
    "恢復",
    "發生",
    "簽約",
    "部署",
    "試驗",
    "通車",
}

_GENERIC_IDENTITY_TERMS = {
    "authority",
    "equipment",
    "line",
    "metro",
    "mrt",
    "operator",
    "project",
    "rail",
    "route",
    "service",
    "station",
    "subway",
    "system",
    "train",
    "transit",
    "urban",
    "network",
    "platform",
    "technology",
    "transport",
    "地鐵",
    "捷運",
    "列車",
    "車站",
    "路線",
    "系統",
    "服務",
    "工程",
    "專案",
}

_EVENT_CONTEXT_TERMS = {
    "authority",
    "contract",
    "equipment",
    "fault",
    "line",
    "metro",
    "operator",
    "package",
    "power",
    "project",
    "rail",
    "service",
    "signalling",
    "signal",
    "station",
    "subway",
    "system",
    "tender",
    "train",
    "urban",
    "變電站",
    "公告",
    "列車",
    "地鐵",
    "契約",
    "工程",
    "捷運",
    "系統",
    "線",
    "車站",
    "設備",
    "軌道",
    "營運商",
}

_DETAIL_TERMS = {
    "after",
    "during",
    "because",
    "between",
    "contractor",
    "date",
    "for",
    "from",
    "method",
    "notice",
    "pilot",
    "result",
    "testing",
    "until",
    "award",
    "amount",
    "期間",
    "原因",
    "測試",
    "試點",
    "金額",
    "日期",
}

_PAGE_SHELL_SEGMENTS = {
    "a-z",
    "archive",
    "archives",
    "category",
    "categories",
    "home",
    "index",
    "navigation",
    "results",
    "search",
    "search-results",
    "tag",
    "tags",
    "topic",
    "topics",
}

_SEARCH_SHELL_MARKERS = {
    "search results",
    "related searches",
    "filters:",
    "no event body",
    "no page-specific event details",
}

_SKIPPED_TAGS = {
    "aside",
    "footer",
    "head",
    "header",
    "link",
    "meta",
    "nav",
    "noscript",
    "script",
    "style",
    "svg",
    "template",
    "title",
}

_VOID_TAGS = {"br", "hr", "img", "input", "link", "meta"}


class _DocumentParser(HTMLParser):
    """Extract visible body text and canonical metadata without deciding readiness."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.canonical_values: list[str] = []
        self.headline_values: list[str] = []
        self.saw_title = False
        self.saw_meta = False
        self._skip_depth = 0
        self._skip_tags: list[str] = []
        self._headline_depth = 0
        self._headline_parts: list[str] = []
        self._title_depth = 0
        self._title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        attributes = {key.casefold(): value or "" for key, value in attrs}
        if tag == "title":
            self.saw_title = True
            self._title_depth += 1
            self._title_parts = []
        if tag in {"h1", "h2"} and self._skip_depth == 0:
            self._headline_depth += 1
            self._headline_parts = []
        if tag == "meta":
            self.saw_meta = True
        if tag == "link" and "canonical" in attributes.get("rel", "").casefold():
            if attributes.get("href"):
                self.canonical_values.append(attributes["href"])
        if tag == "meta":
            property_name = (
                attributes.get("property", "") or attributes.get("name", "")
            ).casefold()
            if property_name in {"og:url", "twitter:url"} and attributes.get("content"):
                self.canonical_values.append(attributes["content"])
            if property_name in {"og:title", "twitter:title"} and attributes.get("content"):
                self.headline_values.append(attributes["content"])
        if tag in _SKIPPED_TAGS and tag not in _VOID_TAGS:
            self._skip_depth += 1
            self._skip_tags.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.casefold() in _SKIPPED_TAGS and tag.casefold() not in _VOID_TAGS and self._skip_depth:
            self._skip_depth -= 1
            self._skip_tags.pop()

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag == "title" and self._title_depth:
            headline = " ".join(" ".join(self._title_parts).split())
            if headline:
                self.headline_values.append(headline)
            self._title_depth = 0
            self._title_parts = []
        if tag in {"h1", "h2"} and self._headline_depth:
            headline = " ".join(" ".join(self._headline_parts).split())
            if headline:
                self.headline_values.append(headline)
            self._headline_depth = 0
            self._headline_parts = []
        if tag in _SKIPPED_TAGS and self._skip_depth:
            self._skip_depth -= 1
            if self._skip_tags:
                self._skip_tags.pop()

    def handle_data(self, data: str) -> None:
        if self._title_depth:
            self._title_parts.append(data)
        if self._headline_depth:
            self._headline_parts.append(data)
        if self._skip_depth == 0 and self._headline_depth == 0 and data.strip():
            self.parts.append(data)


def _candidate(value: CanonicalCandidate | Mapping[str, Any]) -> CanonicalCandidate:
    if isinstance(value, CanonicalCandidate):
        return value
    if isinstance(value, Mapping):
        return CanonicalCandidate.from_mapping(value)
    raise TypeError("candidate must be CanonicalCandidate or mapping")


def _normalise_url(value: str) -> str:
    raw = str(value or "").strip()
    parsed = urlsplit(raw)
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.netloc:
        return ""
    return raw


def _is_shell_url(value: str) -> bool:
    parsed = urlsplit(value)
    host = parsed.netloc.casefold().removeprefix("www.")
    if host == "news.google.com":
        return True
    path_segments = {
        segment.casefold()
        for segment in parsed.path.split("/")
        if segment
    }
    if not parsed.path or parsed.path == "/":
        return True
    if path_segments & _PAGE_SHELL_SEGMENTS:
        return True
    return parsed.query.casefold().startswith(("q=", "query=")) and "search" in parsed.path.casefold()


def _tokenise(value: str) -> set[str]:
    tokens = re.findall(r"[A-Za-z0-9]+|[\u3400-\u9fff]+", str(value or "").casefold())
    return {
        token
        for token in tokens
        if token not in _STOPWORDS and (len(token) >= 3 or any("\u3400" <= char <= "\u9fff" for char in token))
    }


def _identity_tokens(title: str) -> set[str]:
    return _tokenise(title) - _GENERIC_IDENTITY_TERMS - _ACTION_TERMS


def _event_anchor_values(value: str) -> set[str]:
    anchors = set(re.findall(r"\b\d+\b", str(value or "").casefold()))
    for compound in re.findall(r"\b[A-Za-z0-9]+(?:[-/][A-Za-z0-9]+)+\b", str(value or "").casefold()):
        anchors.add(re.sub(r"[-/]", "", compound))
    return anchors


def _normalise_headline(value: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9]+|[\u3400-\u9fff]+", str(value or "").casefold())
    return " ".join(tokens)


def _page_event_identity(
    title: str,
    content: str,
    headlines: list[str],
) -> tuple[bool, dict[str, Any]]:
    """Return deterministic page/event identity signals, not a final decision."""

    identity_tokens = _identity_tokens(title)
    content_tokens = _tokenise(content)
    headline_match = (
        len(identity_tokens) >= 2
        and any(_normalise_headline(title) == _normalise_headline(value) for value in headlines)
    )
    candidate_anchors = _event_anchor_values(title)
    content_anchors = _event_anchor_values(content)
    anchor_bundle_match = (
        len(identity_tokens) >= 3
        and identity_tokens.issubset(content_tokens)
        and (
            bool(candidate_anchors)
            and candidate_anchors.issubset(content_anchors)
            or not candidate_anchors
        )
    )
    return headline_match or anchor_bundle_match, {
        "headline_exact": headline_match,
        "event_anchor_bundle": anchor_bundle_match,
        "identity_token_count": len(identity_tokens),
        "event_anchor_count": len(candidate_anchors),
    }


def _is_search_navigation_content(content: str) -> bool:
    lowered = str(content or "").casefold()
    return sum(marker in lowered for marker in _SEARCH_SHELL_MARKERS) >= 2


def _has_factual_substance(content: str) -> bool:
    lowered = content.casefold()
    tokens = _tokenise(content)
    has_action = bool(tokens & _ACTION_TERMS)
    has_context = bool(tokens & _EVENT_CONTEXT_TERMS)
    has_detail = bool(tokens & _DETAIL_TERMS) or bool(re.search(r"\d", content))
    return has_action and has_context and has_detail


def _resource_key(value: str) -> tuple[str, str] | None:
    normalised = _normalise_url(value)
    if not normalised:
        return None
    parsed = urlsplit(normalised)
    host = parsed.netloc.casefold().removeprefix("www.")
    path = parsed.path.rstrip("/") or "/"
    return host, path.casefold()


def _normalise_redirect_chain(values: tuple[str, ...]) -> list[str] | None:
    normalised: list[str] = []
    for value in values:
        item = _normalise_url(value)
        if not item:
            return None
        normalised.append(item)
    return normalised


def _source_provenance(
    candidate_url: str,
    resolved_url: str,
    redirect_chain: tuple[str, ...],
) -> tuple[bool, dict[str, Any]]:
    """Check acquisition provenance without deciding page/event identity."""

    candidate_key = _resource_key(candidate_url)
    resolved_key = _resource_key(resolved_url)
    chain = _normalise_redirect_chain(redirect_chain)
    signals: dict[str, Any] = {
        "provenance_path": chain or [],
        "provenance_mode": "direct" if candidate_key == resolved_key else "redirect_chain",
    }
    if candidate_key is None or resolved_key is None or chain is None:
        return False, signals
    if candidate_key == resolved_key:
        if chain and (_resource_key(chain[0]) != candidate_key or _resource_key(chain[-1]) != resolved_key):
            return False, signals
        return True, signals
    if not chain:
        return False, signals
    return _resource_key(chain[0]) == candidate_key and _resource_key(chain[-1]) == resolved_key, signals


def _canonical_is_related(
    canonical_url: str,
    resolved_url: str,
    redirect_chain: tuple[str, ...],
) -> bool:
    canonical_key = _resource_key(canonical_url)
    resolved_key = _resource_key(resolved_url)
    if canonical_key is None or resolved_key is None:
        return False
    if canonical_key == resolved_key:
        return True
    chain = _normalise_redirect_chain(redirect_chain) or []
    if any(_resource_key(item) == canonical_key for item in chain):
        return True
    return canonical_key[0] == resolved_key[0] and not _is_shell_url(canonical_url)


def _extract_body(content: str) -> tuple[str, list[str], list[str], bool, bool]:
    """Return body text and parser signals; no readiness decision is made."""

    if "<" not in content or ">" not in content:
        return " ".join(content.split()), [], [], False, False
    parser = _DocumentParser()
    try:
        parser.feed(content)
        parser.close()
    except Exception:
        return "", [], [], parser.saw_title, parser.saw_meta
    visible = " ".join(" ".join(parser.parts).split())
    return visible, parser.canonical_values, parser.headline_values, parser.saw_title, parser.saw_meta


def _coerce_source(value: FetchedSource | Mapping[str, Any] | object, request_url: str) -> FetchedSource:
    if isinstance(value, FetchedSource):
        return value
    if isinstance(value, Mapping):
        headers = value.get("headers")
        content_type = value.get("content_type", "")
        if not content_type and isinstance(headers, Mapping):
            content_type = headers.get("Content-Type", headers.get("content-type", ""))
        redirect_chain = value.get("redirect_chain", ())
        if isinstance(redirect_chain, str):
            redirect_chain = (redirect_chain,)
        return FetchedSource(
            url=str(value.get("url", "") or request_url),
            content=str(value.get("content", value.get("text", "")) or ""),
            status_code=int(value.get("status_code", 200) or 200),
            content_type=str(content_type or "text/html"),
            redirect_chain=tuple(str(item) for item in redirect_chain or ()),
        )
    headers = getattr(value, "headers", {}) or {}
    content_type = getattr(value, "content_type", "") or (
        headers.get("Content-Type", headers.get("content-type", ""))
        if hasattr(headers, "get")
        else ""
    )
    body = getattr(value, "text", getattr(value, "content", ""))
    if isinstance(body, bytes):
        body = body.decode("utf-8", errors="replace")
    return FetchedSource(
        url=str(getattr(value, "url", "") or request_url),
        content=str(body or ""),
        status_code=int(getattr(value, "status_code", 200) or 200),
        content_type=str(content_type or "text/html"),
        redirect_chain=tuple(str(item) for item in getattr(value, "redirect_chain", ()) or ()),
    )


class _RecordingRedirectHandler(HTTPRedirectHandler):
    def __init__(self) -> None:
        super().__init__()
        self.redirect_urls: list[str] = []

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.redirect_urls.append(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _default_fetcher(url: str, timeout_seconds: float) -> FetchedSource:
    request = Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml,text/plain,*/*",
            "User-Agent": "Weekly-report-v2-EvidenceService/1.0",
        },
    )
    redirect_handler = _RecordingRedirectHandler()
    try:
        with build_opener(redirect_handler).open(request, timeout=timeout_seconds) as response:
            body = response.read()
            headers = getattr(response, "headers", {})
            content_type = headers.get("Content-Type", "") if hasattr(headers, "get") else ""
            resolved_url = str(response.geturl() or url)
            redirect_chain = [url, *redirect_handler.redirect_urls]
            if not redirect_chain or redirect_chain[-1] != resolved_url:
                redirect_chain.append(resolved_url)
            return FetchedSource(
                url=resolved_url,
                content=body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body),
                status_code=int(getattr(response, "status", 200) or 200),
                content_type=str(content_type or "text/html"),
                redirect_chain=tuple(redirect_chain),
            )
    except HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}") from exc


class EvidenceService:
    """The sole authoritative owner of EVIDENCE_READY / EVIDENCE_REJECTED."""

    def __init__(self, fetcher: Fetcher | None = None, *, timeout_seconds: float = 10.0) -> None:
        self._timeout_seconds = float(timeout_seconds)
        self._fetcher = fetcher or (
            lambda url: _default_fetcher(url, self._timeout_seconds)
        )

    def evaluate(self, candidate: CanonicalCandidate | Mapping[str, Any]) -> EvidenceResult:
        """Acquire and assess one Candidate without mutating the input."""

        item = _candidate(candidate)
        input_url = _normalise_url(item.url)
        if not input_url:
            return self._rejected(item, RejectReason.URL_UNRESOLVED, {})

        try:
            fetched = _coerce_source(self._fetcher(input_url), input_url)
        except Exception as exc:
            return self._rejected(
                item,
                RejectReason.CONTENT_UNAVAILABLE,
                {"transport_error": type(exc).__name__},
            )

        resolved_url = _normalise_url(fetched.url) or input_url
        if fetched.status_code >= 400:
            return self._rejected(
                item,
                RejectReason.CONTENT_UNAVAILABLE,
                {"resolved_url": resolved_url, "status_code": fetched.status_code},
                canonical_source_url=resolved_url,
            )
        if fetched.content_type and not self._textual_content_type(fetched.content_type):
            return self._rejected(
                item,
                RejectReason.CONTENT_UNAVAILABLE,
                {"resolved_url": resolved_url, "content_type": fetched.content_type},
                canonical_source_url=resolved_url,
            )

        body, canonical_values, headlines, saw_title, saw_meta = _extract_body(fetched.content)
        canonical_url = self._canonical_url(canonical_values, resolved_url)
        source_url = canonical_url or resolved_url
        if not _normalise_url(source_url):
            return self._rejected(item, RejectReason.URL_UNRESOLVED, {})
        if _is_shell_url(resolved_url) or _is_shell_url(source_url):
            return self._rejected(
                item,
                RejectReason.SOURCE_PAGE_MISMATCH,
                {"resolved_url": source_url, "page_kind": "shell"},
                canonical_source_url=source_url,
            )

        source_provenance, provenance_signals = _source_provenance(
            input_url,
            resolved_url,
            fetched.redirect_chain,
        )
        if canonical_url and not _canonical_is_related(canonical_url, resolved_url, fetched.redirect_chain):
            source_provenance = False
            provenance_signals["canonical_related"] = False
        else:
            provenance_signals["canonical_related"] = True
        if not source_provenance:
            return self._rejected(
                item,
                RejectReason.SOURCE_PAGE_MISMATCH,
                {
                    "resolved_url": source_url,
                    "source_provenance": False,
                    "source_to_candidate_match": False,
                    **provenance_signals,
                },
                canonical_source_url=source_url,
            )

        if not body:
            reason = (
                RejectReason.INSUFFICIENT_SUBSTANCE
                if saw_meta
                else RejectReason.TITLE_ONLY
                if saw_title or item.title or item.search_snippet
                else RejectReason.CONTENT_UNAVAILABLE
            )
            return self._rejected(
                item,
                reason,
                {"resolved_url": source_url, "body_text_available": False},
                canonical_source_url=source_url,
            )

        matched, identity_signals = _page_event_identity(item.title, body, headlines)
        if not matched:
            reject_reason = (
                RejectReason.INSUFFICIENT_SUBSTANCE
                if _is_search_navigation_content(body)
                else RejectReason.SOURCE_PAGE_MISMATCH
            )
            return self._rejected(
                item,
                reject_reason,
                {
                    "resolved_url": source_url,
                    "source_provenance": True,
                    "page_event_identity": False,
                    "source_to_candidate_match": False,
                    **provenance_signals,
                    **identity_signals,
                },
                canonical_source_url=source_url,
            )

        factual = _has_factual_substance(body)
        if not factual:
            return self._rejected(
                item,
                RejectReason.INSUFFICIENT_SUBSTANCE,
                {
                    "resolved_url": source_url,
                    "source_provenance": True,
                    "page_event_identity": True,
                    "factual_substance": False,
                    **provenance_signals,
                    **identity_signals,
                },
                canonical_source_url=source_url,
            )

        return EvidenceResult(
            candidate_id=item.candidate_id,
            state=EvidenceState.READY,
            canonical_source_url=source_url,
            source_type=item.source_type or "web_source",
            substantive_content=body,
            provenance={
                "candidate_url": input_url,
                "resolved_url": source_url,
                "content_type": fetched.content_type,
                "content_kind": "body_text",
                "source_provenance": True,
                "page_event_identity": True,
                "source_to_candidate_match": True,
                "factual_substance": True,
                **provenance_signals,
                **identity_signals,
            },
        )

    @staticmethod
    def _textual_content_type(content_type: str) -> bool:
        lowered = content_type.casefold()
        return any(kind in lowered for kind in ("html", "text", "xml"))

    @staticmethod
    def _canonical_url(values: list[str], base_url: str) -> str:
        for value in values:
            candidate = _normalise_url(urljoin(base_url, value.strip()))
            if candidate and not _is_shell_url(candidate):
                return candidate
        return ""

    @staticmethod
    def _rejected(
        candidate: CanonicalCandidate,
        reason: RejectReason,
        provenance: Mapping[str, Any],
        *,
        canonical_source_url: str = "",
    ) -> EvidenceResult:
        return EvidenceResult(
            candidate_id=candidate.candidate_id,
            state=EvidenceState.REJECTED,
            canonical_source_url=canonical_source_url,
            source_type=candidate.source_type or "web_source",
            substantive_content="",
            provenance=dict(provenance),
            reject_reason=reason,
        )
