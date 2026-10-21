"""The first V2 production boundary: Canonical Candidate to Evidence result.

EvidenceService is the only module in this phase that decides whether a
source is EVIDENCE_READY. Transport and parsing helpers below return facts or
signals only; they do not create a second Evidence owner.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import codecs
from dataclasses import replace
import ipaddress
import re
import socket
from time import perf_counter
from typing import Any
from urllib.error import HTTPError
from urllib.parse import unquote_plus, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .contracts import (
    RegionResolution,
    RegionResolutionBasis,
    SemanticProviderConfigurationFailure,
    SemanticProviderTechnicalFailure,
    CanonicalCandidate,
    EvidenceResult,
    EvidenceState,
    EventIdentityFacts,
    FetchedSource,
    IdentityMetadataSupport,
    RejectReason,
)
from .evidence_metadata import (
    EvidenceMetadataExtraction,
    EvidenceMetadataExtractor,
    EvidenceMetadataRequest,
    InvalidEvidenceMetadataResponse,
    validate_evidence_metadata_response,
)
from .semantic_judge import (
    JudgeMetadata,
    InvalidSemanticJudgeResponse,
    PrincipalBodySegment,
    SemanticJudge,
    SemanticJudgeInput,
    SemanticRelation,
    ValidatedSemanticJudgeResponse,
    semantic_judge_input_hash,
    validate_semantic_judge_response,
)
from .evidence_document import DocumentSegment, PrincipalDocumentStatus, assess_document
from .geographic_reference import GeographicMatchKind, GeographicReference, default_geographic_reference
from .google_news_links import (
    GoogleNewsLinkResolver,
    LinkResolutionError,
    LinkResolutionFailure,
    is_google_news_article_url,
    same_publisher,
)


Fetcher = Callable[[str], FetchedSource | Mapping[str, Any] | object]

_TRACKING_QUERY_NAMES = {"fbclid", "gclid"}


class _UnsafeDestinationError(RuntimeError):
    """The default transport refused a non-public network destination."""


class _EvidenceFetchError(RuntimeError):
    """Safe transport failure retaining bounded transport observations."""

    def __init__(
        self,
        status_code: int | None = None,
        *,
        request_url: str = "",
        failing_url: str = "",
        redirect_hop_count: int | None = None,
    ) -> None:
        super().__init__("evidence fetch failed")
        self.status_code = status_code
        self.request_hostname = _safe_hostname(request_url) or None
        self.failing_endpoint_hostname = _safe_hostname(failing_url) or None
        self.redirect_hop_count = (
            redirect_hop_count
            if isinstance(redirect_hop_count, int) and not isinstance(redirect_hop_count, bool)
            and redirect_hop_count >= 0
            else None
        )


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
    try:
        parsed.port
    except ValueError:
        return ""
    query = _normalise_query(parsed.query)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, ""))


def _safe_hostname(value: object) -> str:
    try:
        hostname = urlsplit(str(value or "")).hostname or ""
    except ValueError:
        return ""
    return hostname.casefold()


def _normalise_query(value: str) -> str:
    if not value:
        return ""
    kept: list[str] = []
    for component in value.split("&"):
        raw_key = component.split("=", 1)[0]
        key = unquote_plus(raw_key).casefold()
        if key.startswith("utm_") or key in _TRACKING_QUERY_NAMES:
            continue
        kept.append(component)
    return "&".join(kept)


def _is_repeated_headline_only(content: str, references: list[str]) -> bool:
    body_text = " ".join(str(content or "").split()).casefold()
    if not body_text:
        return True
    for reference in references:
        reference_text = " ".join(str(reference or "").split()).casefold()
        if reference_text and body_text == reference_text:
            return True
    return False


def _raw_relation(raw_response: object) -> str:
    if isinstance(raw_response, Mapping):
        value = raw_response.get("relation", "")
        return value if isinstance(value, str) else ""
    return ""


def _has_factual_substance(content: str, title: str, headlines: list[str]) -> bool:
    """Check structural body availability without deciding event identity."""

    if not content.strip():
        return False
    if _is_repeated_headline_only(content, [title, *headlines]):
        return False
    return True


def _resource_key(value: str) -> tuple[str, str, int | None, str, str] | None:
    normalised = _normalise_url(value)
    if not normalised:
        return None
    parsed = urlsplit(normalised)
    try:
        port = parsed.port
    except ValueError:
        return None
    host = (parsed.hostname or "").casefold().removeprefix("www.")
    if not host:
        return None
    default_port = 80 if parsed.scheme.casefold() == "http" else 443
    effective_port = None if port in {None, default_port} else port
    path = parsed.path or "/"
    return parsed.scheme.casefold(), host, effective_port, path, _normalise_query(parsed.query)


def _normalise_redirect_chain(values: tuple[str, ...]) -> list[str] | None:
    normalised: list[str] = []
    for value in values:
        item = _normalise_url(value)
        if not item:
            return None
        normalised.append(item)
    return normalised


def _acquisition_observation(
    input_url: str,
    elapsed_ms: int,
    *,
    fetched: FetchedSource | None = None,
    error: BaseException | None = None,
) -> dict[str, Any]:
    """Return bounded transport facts without making an Evidence decision."""

    initial_hostname = _safe_hostname(input_url) or "UNKNOWN"
    observation: dict[str, Any] = {
        "acquisition_elapsed_ms": max(0, int(elapsed_ms)),
        "acquisition_initial_hostname": initial_hostname,
        "acquisition_redirect_hop_count": "UNKNOWN",
        "acquisition_path": "UNKNOWN",
        "acquisition_final_endpoint": "UNKNOWN",
        "acquisition_redirect_consistency": "UNKNOWN",
        "acquisition_failing_endpoint_hostname": "UNKNOWN",
    }
    if fetched is not None:
        chain = tuple(fetched.redirect_chain or ())
        resolved_url = _normalise_url(fetched.url)
        has_redirect = len(chain) >= 2
        chain_starts_at_input = (
            not chain or _normalise_url(chain[0]) == input_url
        )
        hop_count = (
            max(0, len(chain) - 1)
            if has_redirect or chain_starts_at_input
            else "UNKNOWN"
        )
        direct = (
            not has_redirect
            and chain_starts_at_input
            and resolved_url == input_url
        )
        observation.update(
            {
                "acquisition_redirect_hop_count": (
                    hop_count if direct or has_redirect else "UNKNOWN"
                ),
                "acquisition_path": (
                    "REDIRECTED" if has_redirect else "DIRECT" if direct else "UNKNOWN"
                ),
                "acquisition_final_endpoint": (
                    "OBSERVED" if resolved_url else "UNKNOWN"
                ),
                "acquisition_failing_endpoint_hostname": "NOT_APPLICABLE",
            }
        )
        return observation

    if isinstance(error, _EvidenceFetchError):
        if error.redirect_hop_count is not None:
            observation["acquisition_redirect_hop_count"] = error.redirect_hop_count
            observation["acquisition_path"] = (
                "REDIRECTED" if error.redirect_hop_count else "DIRECT"
            )
        if error.failing_endpoint_hostname:
            observation["acquisition_failing_endpoint_hostname"] = (
                error.failing_endpoint_hostname
            )
        return observation

    if isinstance(error, HTTPError):
        failing_hostname = _safe_hostname(getattr(error, "url", ""))
        if failing_hostname:
            observation["acquisition_failing_endpoint_hostname"] = failing_hostname
        return observation

    return observation


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
    if candidate_key is None:
        signals["source_provenance_mismatch_reason"] = "INVALID_CANDIDATE_RESOURCE_KEY"
        return False, signals
    if resolved_key is None:
        signals["source_provenance_mismatch_reason"] = "INVALID_RESOLVED_RESOURCE_KEY"
        return False, signals
    if chain is None:
        signals["source_provenance_mismatch_reason"] = "INVALID_REDIRECT_CHAIN"
        return False, signals
    if candidate_key == resolved_key:
        if chain and _resource_key(chain[0]) != candidate_key:
            signals["source_provenance_mismatch_reason"] = "FIRST_REDIRECT_ENDPOINT_MISMATCH"
            return False, signals
        if chain and _resource_key(chain[-1]) != resolved_key:
            signals["source_provenance_mismatch_reason"] = "FINAL_REDIRECT_ENDPOINT_MISMATCH"
            return False, signals
        signals["acquisition_redirect_consistency"] = (
            "CONSISTENT" if len(chain) >= 2 else "NOT_APPLICABLE"
        )
        signals["redirect_hop_count"] = max(0, len(chain) - 1)
        return True, signals
    if not chain:
        signals["source_provenance_mismatch_reason"] = "MISSING_REDIRECT_CHAIN"
        return False, signals
    if _resource_key(chain[0]) != candidate_key:
        signals["source_provenance_mismatch_reason"] = "FIRST_REDIRECT_ENDPOINT_MISMATCH"
        return False, signals
    if _resource_key(chain[-1]) != resolved_key:
        signals["source_provenance_mismatch_reason"] = "FINAL_REDIRECT_ENDPOINT_MISMATCH"
        return False, signals
    signals["acquisition_redirect_consistency"] = "CONSISTENT"
    signals["redirect_hop_count"] = max(0, len(chain) - 1)
    return True, signals


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
    return False


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


def _codec_name(value: str) -> str | None:
    try:
        return codecs.lookup(value.strip().strip("'\"")).name
    except (LookupError, AttributeError):
        return None


def _declared_charset(content_type: str) -> str | None:
    match = re.search(
        r"(?:^|;)\s*charset\s*=\s*['\"]?([^;\s'\"]+)",
        str(content_type or ""),
        flags=re.IGNORECASE,
    )
    return _codec_name(match.group(1)) if match else None


def _html_meta_charset(body: bytes) -> str | None:
    # Inspect only the initial HTML declaration area; this is a deterministic
    # transport decoding fallback, not language detection or content parsing.
    sample = body[:8192].decode("ascii", errors="ignore")
    patterns = (
        r"<meta\b[^>]*\bcharset\s*=\s*['\"]?\s*([A-Za-z0-9._:-]+)",
        r"<meta\b[^>]*\bcontent\s*=\s*['\"][^'\"]*?charset\s*=\s*([A-Za-z0-9._:-]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, sample, flags=re.IGNORECASE)
        if match:
            codec = _codec_name(match.group(1))
            if codec:
                return codec
    return None


def _decode_response_body(body: bytes, content_type: str) -> str:
    """Decode HTTP bytes using declared charset, then HTML meta, then UTF-8."""

    charset = _declared_charset(content_type) or _html_meta_charset(body) or "utf-8"
    return body.decode(charset, errors="replace")


def _is_public_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    if address.version == 6 and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return bool(
        address.is_global
        and not address.is_private
        and not address.is_loopback
        and not address.is_link_local
        and not address.is_unspecified
        and not address.is_multicast
        and not address.is_reserved
    )


def _assert_safe_destination(url: str) -> None:
    normalised = _normalise_url(url)
    parsed = urlsplit(normalised)
    host = parsed.hostname
    if not host:
        raise _UnsafeDestinationError("destination host is missing")
    try:
        port = parsed.port or (443 if parsed.scheme.casefold() == "https" else 80)
    except ValueError as exc:
        raise _UnsafeDestinationError("destination port is invalid") from exc

    try:
        ipaddress.ip_address(host)
    except ValueError:
        try:
            addresses = {
                info[4][0]
                for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
                if info[4]
            }
        except OSError as exc:
            raise _UnsafeDestinationError("destination DNS resolution failed") from exc
    else:
        addresses = {host}

    if not addresses or any(not _is_public_ip(address) for address in addresses):
        raise _UnsafeDestinationError("destination is not public")


class _RecordingRedirectHandler(HTTPRedirectHandler):
    def __init__(self) -> None:
        super().__init__()
        self.redirect_urls: list[str] = []

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _assert_safe_destination(newurl)
        self.redirect_urls.append(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _default_fetcher(url: str, timeout_seconds: float) -> FetchedSource:
    _assert_safe_destination(url)
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
            _assert_safe_destination(resolved_url)
            redirect_chain = [url, *redirect_handler.redirect_urls]
            if not redirect_chain or redirect_chain[-1] != resolved_url:
                redirect_chain.append(resolved_url)
            return FetchedSource(
                url=resolved_url,
                content=(
                    _decode_response_body(body, str(content_type))
                    if isinstance(body, bytes)
                    else str(body)
                ),
                status_code=int(getattr(response, "status", 200) or 200),
                content_type=str(content_type or "text/html"),
                redirect_chain=tuple(redirect_chain),
            )
    except HTTPError as exc:
        raise _EvidenceFetchError(
            exc.code,
            request_url=url,
            failing_url=getattr(exc, "url", ""),
            redirect_hop_count=len(redirect_handler.redirect_urls),
        ) from exc


_AMP_HTML_TAG = re.compile(r"<html\b[^>]*?(?:\s(?:⚡|amp))(?:[\s=>/])", re.IGNORECASE)
_CANONICAL_LINK = re.compile(r"<link\b[^>]*\brel\s*=\s*[\"']?canonical[\"']?[^>]*>", re.IGNORECASE)
_HREF = re.compile(r"\bhref\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE)


def _amp_canonical_url(content: str, resolved_url: str) -> str:
    """Return the same-host canonical article declared by an AMP page, if any."""

    head = str(content or "")[:20000]
    if not _AMP_HTML_TAG.search(head):
        return ""
    links = _CANONICAL_LINK.findall(head)
    if len(links) != 1:
        return ""
    match = _HREF.search(links[0])
    if not match:
        return ""
    canonical = _normalise_url(urljoin(resolved_url, match.group(1).strip()))

    def host(value: str) -> str:
        name = _safe_hostname(value).casefold()
        return name[4:] if name.startswith("www.") else name

    if not canonical or canonical == _normalise_url(resolved_url) or host(canonical) != host(resolved_url):
        return ""
    return canonical


class EvidenceService:
    """The sole authoritative owner of EVIDENCE_READY / EVIDENCE_REJECTED."""

    def __init__(
        self,
        fetcher: Fetcher | None = None,
        *,
        timeout_seconds: float = 10.0,
        semantic_judge: SemanticJudge | None = None,
        judge_metadata: JudgeMetadata | None = None,
        metadata_extractor: EvidenceMetadataExtractor | None = None,
        geographic_reference: GeographicReference | None = None,
        link_resolver: GoogleNewsLinkResolver | None = None,
    ) -> None:
        self._timeout_seconds = float(timeout_seconds)
        self._link_resolver = link_resolver
        self._geographic_reference = geographic_reference or default_geographic_reference()
        self._fetcher = fetcher or (
            lambda url: _default_fetcher(url, self._timeout_seconds)
        )
        self._semantic_judge = semantic_judge
        self._judge_metadata = judge_metadata
        self._metadata_extractor = metadata_extractor

    def evaluate(self, candidate: CanonicalCandidate | Mapping[str, Any]) -> EvidenceResult:
        """Acquire and assess one Candidate without mutating the input."""

        item = _candidate(candidate)
        input_url = _normalise_url(item.url)
        if not input_url:
            return self._rejected(
                item,
                RejectReason.URL_UNRESOLVED,
                {},
                evidence_rejection_gate="URL_VALIDATION",
            )
        if not is_google_news_article_url(input_url):
            return self._evaluate_source(item, input_url)

        # RC-11: a Google News discovery link is resolved to the publisher
        # article it points to; only the publisher page can become Evidence.
        link: dict[str, Any] = {"discovery_url": input_url}
        if self._link_resolver is None:
            link["link_resolution"] = "NOT_CONFIGURED"
            return self._rejected(item, RejectReason.URL_UNRESOLVED, link, evidence_rejection_gate="LINK_RESOLUTION")
        try:
            resolution = self._link_resolver.resolve(input_url)
        except LinkResolutionError as exc:
            link.update(link_resolution=exc.failure.value, link_resolution_detail=exc.detail)
            reason = (
                RejectReason.CONTENT_UNAVAILABLE
                if exc.failure is LinkResolutionFailure.TRANSPORT
                else RejectReason.URL_UNRESOLVED
            )
            return self._rejected(item, reason, link, evidence_rejection_gate="LINK_RESOLUTION")
        publisher_url = _normalise_url(resolution.publisher_url)
        link.update(
            link_resolution=resolution.method,
            link_resolution_requests=resolution.requests,
            link_resolved_url=publisher_url,
        )
        origin = same_publisher(item.publisher_url, publisher_url)
        link["publisher_origin_check"] = "NOT_DECLARED" if origin is None else ("MATCH" if origin else "MISMATCH")
        if not publisher_url:
            return self._rejected(item, RejectReason.URL_UNRESOLVED, link, evidence_rejection_gate="LINK_RESOLUTION")
        if origin is False:
            link["source_provenance_mismatch_reason"] = "PUBLISHER_ORIGIN_MISMATCH"
            return self._rejected(
                item,
                RejectReason.SOURCE_PAGE_MISMATCH,
                link,
                evidence_rejection_gate="SOURCE_PROVENANCE",
                canonical_source_url=publisher_url,
            )
        result = self._evaluate_source(item, publisher_url)
        return replace(result, provenance={**dict(result.provenance), **link})

    def _evaluate_source(self, item: CanonicalCandidate, input_url: str, *, amp_url: str = "") -> EvidenceResult:
        """Acquire and assess the source page at ``input_url``."""

        fetch_started = perf_counter()
        try:
            fetched = _coerce_source(self._fetcher(input_url), input_url)
        except _EvidenceFetchError as exc:
            provenance: dict[str, Any] = _acquisition_observation(
                input_url,
                int((perf_counter() - fetch_started) * 1000),
                error=exc,
            )
            provenance["transport_error"] = "HTTPError"
            if exc.status_code is not None:
                provenance["status_code"] = exc.status_code
            return self._rejected(
                item,
                RejectReason.CONTENT_UNAVAILABLE,
                provenance,
                evidence_rejection_gate="FETCH_TRANSPORT",
            )
        except HTTPError as exc:
            provenance = _acquisition_observation(
                input_url,
                int((perf_counter() - fetch_started) * 1000),
                error=exc,
            )
            provenance.update(
                {"transport_error": "HTTPError", "status_code": int(exc.code)}
            )
            return self._rejected(
                item,
                RejectReason.CONTENT_UNAVAILABLE,
                provenance,
                evidence_rejection_gate="FETCH_TRANSPORT",
            )
        except Exception as exc:
            provenance = _acquisition_observation(
                input_url,
                int((perf_counter() - fetch_started) * 1000),
                error=exc,
            )
            provenance["transport_error"] = type(exc).__name__
            return self._rejected(
                item,
                RejectReason.CONTENT_UNAVAILABLE,
                provenance,
                evidence_rejection_gate="FETCH_TRANSPORT",
            )

        fetch_observation = _acquisition_observation(
            input_url,
            int((perf_counter() - fetch_started) * 1000),
            fetched=fetched,
        )
        # RC-13: an AMP page is an alternate rendering of a canonical article.
        # When it declares a same-host canonical, that canonical article is
        # acquired once and assessed instead; nothing else is substituted.
        if not amp_url and fetched.status_code < 400:
            amp_canonical = _amp_canonical_url(fetched.content, _normalise_url(fetched.url) or input_url)
            if amp_canonical:
                result = self._evaluate_source(item, amp_canonical, amp_url=_normalise_url(fetched.url) or input_url)
                return replace(result, provenance={**dict(result.provenance), "amp_url": _normalise_url(fetched.url) or input_url})

        resolved_url = _normalise_url(fetched.url) or input_url
        if fetched.status_code >= 400:
            return self._rejected(
                item,
                RejectReason.CONTENT_UNAVAILABLE,
                {
                    **fetch_observation,
                    "resolved_url": resolved_url,
                    "status_code": fetched.status_code,
                    "content_type": fetched.content_type,
                },
                evidence_rejection_gate="HTTP_STATUS",
                canonical_source_url=resolved_url,
            )
        if fetched.content_type and not self._textual_content_type(fetched.content_type):
            return self._rejected(
                item,
                RejectReason.CONTENT_UNAVAILABLE,
                {
                    **fetch_observation,
                    "resolved_url": resolved_url,
                    "content_type": fetched.content_type,
                },
                evidence_rejection_gate="CONTENT_TYPE",
                canonical_source_url=resolved_url,
            )
        assessment = assess_document(
            fetched.content,
            fetched.content_type,
            resource_url=resolved_url,
            candidate_id=item.candidate_id,
            resource_identity_checker=lambda value: _canonical_is_related(
                value,
                resolved_url,
                fetched.redirect_chain,
            ),
        )
        body = assessment.body_text
        document_level_headlines = list(assessment.document_level_headlines)
        structural_provenance = assessment.as_provenance()
        structural_provenance["content_type"] = fetched.content_type
        structural_provenance["body_text_available"] = bool(body)
        canonical_url = self._canonical_url(list(assessment.canonical_values), resolved_url)
        source_url = canonical_url or resolved_url
        if not _normalise_url(source_url):
            return self._rejected(
                item,
                RejectReason.URL_UNRESOLVED,
                {},
                evidence_rejection_gate="URL_VALIDATION",
            )

        source_provenance, provenance_signals = _source_provenance(
            input_url,
            resolved_url,
            fetched.redirect_chain,
        )
        if canonical_url and not _canonical_is_related(canonical_url, resolved_url, fetched.redirect_chain):
            source_provenance = False
            provenance_signals["canonical_related"] = False
            provenance_signals["source_provenance_mismatch_reason"] = "CANONICAL_RESOURCE_MISMATCH"
        else:
            provenance_signals["canonical_related"] = True
            if source_provenance and "acquisition_redirect_consistency" not in provenance_signals:
                provenance_signals["acquisition_redirect_consistency"] = (
                    "CONSISTENT"
                    if len(tuple(fetched.redirect_chain or ())) >= 2
                    else "NOT_APPLICABLE"
                )
        if not source_provenance:
            return self._rejected(
                item,
                RejectReason.SOURCE_PAGE_MISMATCH,
                {
                    "resolved_url": source_url,
                    "source_provenance": False,
                    "source_to_candidate_match": False,
                    **fetch_observation,
                    **provenance_signals,
                    **structural_provenance,
                },
                evidence_rejection_gate="SOURCE_PROVENANCE",
                canonical_source_url=source_url,
            )

        if assessment.principal_document_status is not PrincipalDocumentStatus.PRINCIPAL_DOCUMENT_ESTABLISHED:
            if assessment.reject_reason == "TITLE_ONLY":
                reason = RejectReason.TITLE_ONLY
            elif assessment.reject_reason == "INSUFFICIENT_SUBSTANCE":
                reason = RejectReason.INSUFFICIENT_SUBSTANCE
            elif assessment.reject_reason == "CONTENT_UNAVAILABLE":
                reason = (
                    RejectReason.TITLE_ONLY
                    if item.title or item.search_snippet or assessment.document_level_headlines
                    else RejectReason.CONTENT_UNAVAILABLE
                )
            else:
                reason = RejectReason.SOURCE_PAGE_MISMATCH
            parse_diagnostics = assessment.diagnostics.get("parse_diagnostics", [])
            if (
                "metadata_present" in parse_diagnostics
                and not assessment.structural_conflict
                and assessment.diagnostics.get("page_kind") != "search_shell"
            ):
                reason = RejectReason.INSUFFICIENT_SUBSTANCE
            if assessment.diagnostics.get("page_kind") in {"landing_page", "search_shell"}:
                reason = RejectReason.SOURCE_PAGE_MISMATCH
            return self._rejected(
                item,
                reason,
                {
                    "resolved_url": source_url,
                    "source_provenance": True,
                    "source_to_candidate_match": False,
                    **fetch_observation,
                    **structural_provenance,
                },
                evidence_rejection_gate="PRINCIPAL_DOCUMENT",
                canonical_source_url=source_url,
            )

        if not body:
            reason = (
                RejectReason(assessment.reject_reason)
                if assessment.reject_reason in {item.value for item in RejectReason}
                else RejectReason.INSUFFICIENT_SUBSTANCE
            )
            return self._rejected(
                item,
                reason,
                {
                    "resolved_url": source_url,
                    "body_text_available": False,
                    **fetch_observation,
                    **structural_provenance,
                },
                evidence_rejection_gate="BODY_AVAILABILITY",
                canonical_source_url=source_url,
            )

        factual = _has_factual_substance(
            body,
            item.title,
            document_level_headlines,
        )
        if not factual:
            return self._rejected(
                item,
                RejectReason.INSUFFICIENT_SUBSTANCE,
                {
                    "resolved_url": source_url,
                    "source_provenance": True,
                    "page_event_identity": False,
                    "source_to_candidate_match": False,
                    "factual_substance": False,
                    **fetch_observation,
                    **provenance_signals,
                    **structural_provenance,
                },
                evidence_rejection_gate="FACTUAL_SUBSTANCE",
                canonical_source_url=source_url,
            )

        semantic_result, semantic_signals = self._semantic_match(
            item,
            body,
            document_level_headlines,
            assessment.principal_body_segments,
        )
        if semantic_result is None or semantic_result.relation is not SemanticRelation.SAME_EVENT:
            return self._rejected(
                item,
                RejectReason.SOURCE_PAGE_MISMATCH,
                {
                    "resolved_url": source_url,
                    "source_provenance": True,
                    "page_event_identity": False,
                    "source_to_candidate_match": False,
                    "factual_substance": True,
                    **fetch_observation,
                    **provenance_signals,
                    **structural_provenance,
                    **semantic_signals,
                    "EvidenceService_final_decision": EvidenceState.REJECTED.value,
                },
                evidence_rejection_gate="SEMANTIC_MATCH",
                canonical_source_url=source_url,
            )

        metadata_facts, metadata_signals = self._extract_metadata(
            item.candidate_id,
            assessment.principal_body_segments,
            body,
        )
        semantic_signals["EvidenceService_final_decision"] = EvidenceState.READY.value
        return EvidenceResult(
            candidate_id=item.candidate_id,
            state=EvidenceState.READY,
            canonical_source_url=source_url,
            source_type=item.source_type or "web_source",
            substantive_content=body,
            provenance={
                **fetch_observation,
                "candidate_url": input_url,
                "resolved_url": source_url,
                "content_type": fetched.content_type,
                "content_kind": "body_text",
                "source_provenance": True,
                "page_event_identity": True,
                "source_to_candidate_match": True,
                "factual_substance": True,
                "principal_source_headlines": list(document_level_headlines),
                **provenance_signals,
                **structural_provenance,
                **semantic_signals,
                **metadata_signals,
            },
            source_date_facts=assessment.source_date_facts,
            identity_facts=metadata_facts,
        )

    def _extract_metadata(
        self,
        candidate_id: str,
        document_segments: tuple[DocumentSegment, ...],
        substantive_content: str,
    ) -> tuple[EventIdentityFacts | None, dict[str, Any]]:
        segments = tuple(
            PrincipalBodySegment(segment_id=segment.segment_id, text=segment.text)
            for segment in document_segments
        )
        request = EvidenceMetadataRequest(candidate_id, segments)
        if self._metadata_extractor is None:
            return None, self._metadata_signals("not_configured")
        try:
            raw_response = self._metadata_extractor(request)
        except (SemanticProviderTechnicalFailure, SemanticProviderConfigurationFailure):
            # RC-6: a technical failure is not "metadata absent"; the
            # application records a technical gap for this Candidate.
            raise
        except TimeoutError:
            return None, self._metadata_signals("timeout")
        except Exception:
            return None, self._metadata_signals("transport_error")
        try:
            extraction = validate_evidence_metadata_response(raw_response, request)
        except InvalidEvidenceMetadataResponse as exc:
            return None, self._metadata_signals("invalid_response", exc.detail)
        except Exception:
            return None, self._metadata_signals("invalid_response", "schema_invalid")
        try:
            facts = self._translate_metadata(extraction, request, substantive_content)
        except ValueError:
            return None, self._metadata_signals("invalid_response", "span_mapping_invalid")
        detail = ",".join(
            f"{field}:UNRESOLVED" for field in facts.unresolved_metadata_fields
        )
        resolution = facts.region_resolution
        region_signal = {
            "metadata_region_basis": resolution.basis.value if resolution else "",
            "metadata_region_diagnostic": resolution.diagnostic if resolution else "",
        }
        if facts.unresolved_metadata_fields:
            return facts, {**self._metadata_signals("partial_metadata", detail), **region_signal}
        if not extraction.observations:
            return facts, {**self._metadata_signals("valid_zero_metadata"), **region_signal}
        return facts, {**self._metadata_signals("valid_metadata"), **region_signal}

    @staticmethod
    def _metadata_signals(status: str, detail: str = "") -> dict[str, Any]:
        return {
            "metadata_extraction_status": status,
            "metadata_extraction_detail": detail,
        }

    def _resolve_region(
        self,
        values: Mapping[str, str | None],
        unresolved_fields: tuple[str, ...],
    ) -> RegionResolution:
        """Deterministically resolve one country/region from source values.

        Only validated exact source values are looked up in the versioned
        geographic reference.  Agreeing matches establish the region; any
        disagreement, ambiguity, or unrecognized value leaves it unresolved.
        Search market, query, publisher, URL, and model knowledge are never used.
        """

        reference = self._geographic_reference
        matches = []
        ambiguous = False
        present = False
        for field_name in ("country", "transit_system_name", "location"):
            value = values.get(field_name)
            if not value:
                continue
            present = True
            match = reference.lookup(value)
            if match is None:
                continue
            if match.kind is GeographicMatchKind.AMBIGUOUS:
                ambiguous = True
                continue
            matches.append((field_name, value, match))
        regions = {match.region_id for _, _, match in matches}
        if len(regions) > 1:
            return RegionResolution(RegionResolutionBasis.UNRESOLVED, diagnostic="CONFLICTING_REGIONS")
        if len(regions) == 1:
            stated = [item for item in matches if item[2].kind is GeographicMatchKind.REGION]
            field_name, value, match = (stated or matches)[0]
            return RegionResolution(
                RegionResolutionBasis.SOURCE_STATED if stated else RegionResolutionBasis.REFERENCE_MAPPED,
                region_id=match.region_id,
                display_name=match.display_name,
                source_field=field_name,
                source_value=value,
                reference_version=reference.version,
            )
        if ambiguous:
            return RegionResolution(RegionResolutionBasis.UNRESOLVED, diagnostic="AMBIGUOUS_NAME")
        if present:
            return RegionResolution(RegionResolutionBasis.UNRESOLVED, diagnostic="UNRECOGNIZED_VALUE")
        if unresolved_fields:
            return RegionResolution(RegionResolutionBasis.UNRESOLVED, diagnostic="INVALID_FIELD")
        return RegionResolution(RegionResolutionBasis.NOT_STATED)

    def _translate_metadata(
        self,
        extraction: EvidenceMetadataExtraction,
        request: EvidenceMetadataRequest,
        substantive_content: str,
    ) -> EventIdentityFacts:
        joined = " ".join(segment.text for segment in request.principal_body_segments)
        if joined.strip() != substantive_content:
            raise ValueError("principal body does not match substantive content")
        leading_trim = len(joined) - len(joined.lstrip())
        trailing_end = len(joined.rstrip())
        positions: dict[str, int] = {}
        running = 0
        for index, segment in enumerate(request.principal_body_segments):
            positions[segment.segment_id] = running + index
            running += len(segment.text)

        values: dict[str, str | None] = {
            "country": None,
            "transit_system_name": None,
            "location": "",
        }
        supports: list[IdentityMetadataSupport] = []
        unresolved = [diagnostic.field_name for diagnostic in extraction.field_diagnostics]
        reference = self._geographic_reference
        for observation in extraction.observations:
            if observation.field_name == "transit_system_name" and (
                reference.is_generic_transit_term(observation.value)
                or reference.is_region_or_city_name(observation.value)
                or reference.is_non_specific_system_name(observation.value)
            ):
                # A mode word, city, country, or a list of them is not a
                # specific system name.
                unresolved.append("transit_system_name")
                continue
            values[observation.field_name] = observation.value
            for span in observation.support_spans:
                segment = next(
                    item
                    for item in request.principal_body_segments
                    if item.segment_id == span.segment_id
                )
                joined_start = positions[span.segment_id] + span.start
                joined_end = positions[span.segment_id] + span.end
                if not (
                    leading_trim <= joined_start < joined_end <= trailing_end
                ):
                    raise ValueError("metadata span is outside substantive content")
                translated_start = joined_start - leading_trim
                translated_end = joined_end - leading_trim
                if (
                    segment.text[span.start : span.end]
                    != substantive_content[translated_start:translated_end]
                ):
                    raise ValueError("metadata span text cannot be translated exactly")
                supports.append(
                    IdentityMetadataSupport(
                        field_name=observation.field_name,
                        start=translated_start,
                        end=translated_end,
                    )
                )
        unresolved_fields = tuple(dict.fromkeys(unresolved))
        return EventIdentityFacts(
            country=values["country"],
            transit_system_name=values["transit_system_name"],
            location=str(values["location"] or ""),
            metadata_support=tuple(supports),
            region_resolution=self._resolve_region(values, unresolved_fields),
            unresolved_metadata_fields=unresolved_fields,
        )

    def _semantic_match(
        self,
        candidate: CanonicalCandidate,
        body: str,
        headlines: list[str],
        document_segments: tuple[DocumentSegment, ...] = (),
    ) -> tuple[ValidatedSemanticJudgeResponse | None, dict[str, Any]]:
        segments = tuple(
            PrincipalBodySegment(segment_id=segment.segment_id, text=segment.text)
            for segment in document_segments
        ) or (PrincipalBodySegment(segment_id="body-0001", text=body),)
        request = SemanticJudgeInput(
            candidate_id=candidate.candidate_id,
            candidate_title=candidate.title,
            document_level_headlines=tuple(headlines),
            principal_body_segments=segments,
        )
        signals = self._semantic_signals(request)
        if self._semantic_judge is None:
            signals.update(
                {
                    "response_validation_result": "not_configured",
                    "error_type": "SemanticJudgeNotConfigured",
                }
            )
            return None, signals

        started = perf_counter()
        try:
            raw_response = self._semantic_judge(request)
        except (SemanticProviderTechnicalFailure, SemanticProviderConfigurationFailure):
            # RC-6: never converted into SOURCE_PAGE_MISMATCH.
            raise
        except TimeoutError:
            signals.update(
                {
                    "response_validation_result": "timeout",
                    "error_type": "TimeoutError",
                    "latency": perf_counter() - started,
                }
            )
            return None, signals
        except Exception as exc:
            signals.update(
                {
                    "response_validation_result": "transport_error",
                    "error_type": type(exc).__name__,
                    "latency": perf_counter() - started,
                }
            )
            return None, signals

        signals["raw_relation"] = _raw_relation(raw_response)
        try:
            validated = validate_semantic_judge_response(raw_response, request)
        except InvalidSemanticJudgeResponse as exc:
            signals.update(
                {
                    "response_validation_result": "invalid",
                    "error_type": type(exc).__name__,
                    "latency": perf_counter() - started,
                }
            )
            return None, signals

        signals.update(
            {
                "raw_relation": validated.relation.value,
                "validated_support_spans": [
                    span.as_mapping() for span in validated.support_spans
                ],
                "validated_conflict_spans": [
                    span.as_mapping() for span in validated.conflict_spans
                ],
                "response_validation_result": "valid",
                "latency": perf_counter() - started,
            }
        )
        return validated, signals

    def _semantic_signals(self, request: SemanticJudgeInput) -> dict[str, Any]:
        metadata = self._judge_metadata
        if metadata is None and self._semantic_judge is not None:
            candidate_metadata = getattr(self._semantic_judge, "metadata", None)
            if isinstance(candidate_metadata, JudgeMetadata):
                metadata = candidate_metadata
        metadata = metadata or JudgeMetadata()
        return {
            "judge_input_hash": semantic_judge_input_hash(request),
            "model_identifier": metadata.model_identifier,
            "prompt_version": metadata.prompt_version,
            "schema_version": metadata.schema_version,
            "raw_relation": "",
            "validated_support_spans": [],
            "validated_conflict_spans": [],
            "response_validation_result": "not_attempted",
            "latency": 0.0,
            "error_type": "",
            "EvidenceService_final_decision": "",
        }

    @staticmethod
    def _textual_content_type(content_type: str) -> bool:
        lowered = content_type.casefold()
        return any(kind in lowered for kind in ("html", "text", "xml"))

    @staticmethod
    def _canonical_url(values: list[str], base_url: str) -> str:
        for value in values:
            candidate = _normalise_url(urljoin(base_url, value.strip()))
            if candidate:
                return candidate
        return ""

    @staticmethod
    def _rejected(
        candidate: CanonicalCandidate,
        reason: RejectReason,
        provenance: Mapping[str, Any],
        *,
        evidence_rejection_gate: str,
        canonical_source_url: str = "",
    ) -> EvidenceResult:
        allowed_gates = {
            "URL_VALIDATION",
            "LINK_RESOLUTION",
            "FETCH_TRANSPORT",
            "HTTP_STATUS",
            "CONTENT_TYPE",
            "SOURCE_PROVENANCE",
            "PRINCIPAL_DOCUMENT",
            "BODY_AVAILABILITY",
            "FACTUAL_SUBSTANCE",
            "SEMANTIC_MATCH",
        }
        if evidence_rejection_gate not in allowed_gates:
            raise ValueError("unknown Evidence rejection gate")
        diagnostic = dict(provenance)
        diagnostic["evidence_rejection_gate"] = evidence_rejection_gate
        candidate_host = _safe_hostname(candidate.url)
        resolved_value = canonical_source_url or diagnostic.get("resolved_url", "")
        resolved_host = _safe_hostname(resolved_value)
        if candidate_host:
            diagnostic["candidate_hostname"] = candidate_host
        if resolved_host:
            diagnostic["resolved_hostname"] = resolved_host
        path = diagnostic.get("provenance_path")
        if isinstance(path, (list, tuple)):
            diagnostic["redirect_hop_count"] = max(0, len(path) - 1)
        return EvidenceResult(
            candidate_id=candidate.candidate_id,
            state=EvidenceState.REJECTED,
            canonical_source_url=canonical_source_url,
            source_type=candidate.source_type or "web_source",
            substantive_content="",
            provenance=diagnostic,
            reject_reason=reason,
        )
