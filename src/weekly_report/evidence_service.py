"""The first V2 production boundary: Canonical Candidate to Evidence result.

EvidenceService is the only module in this phase that decides whether a
source is EVIDENCE_READY. Transport and parsing helpers below return facts or
signals only; they do not create a second Evidence owner.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import codecs
import ipaddress
import re
import socket
from time import perf_counter
from typing import Any
from urllib.error import HTTPError
from urllib.parse import unquote_plus, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .contracts import (
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


Fetcher = Callable[[str], FetchedSource | Mapping[str, Any] | object]

_TRACKING_QUERY_NAMES = {"fbclid", "gclid"}


class _UnsafeDestinationError(RuntimeError):
    """The default transport refused a non-public network destination."""


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
        raise RuntimeError(f"HTTP {exc.code}") from exc


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
    ) -> None:
        self._timeout_seconds = float(timeout_seconds)
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
        canonical_url = self._canonical_url(list(assessment.canonical_values), resolved_url)
        source_url = canonical_url or resolved_url
        if not _normalise_url(source_url):
            return self._rejected(item, RejectReason.URL_UNRESOLVED, {})

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

        structural_provenance = assessment.as_provenance()
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
                    **structural_provenance,
                },
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
                    **structural_provenance,
                },
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
                    **provenance_signals,
                    **structural_provenance,
                },
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
                    **provenance_signals,
                    **structural_provenance,
                    **semantic_signals,
                    "EvidenceService_final_decision": EvidenceState.REJECTED.value,
                },
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
        if not extraction.observations:
            return None, self._metadata_signals("valid_zero_metadata")
        return facts, self._metadata_signals("valid_metadata")

    @staticmethod
    def _metadata_signals(status: str, detail: str = "") -> dict[str, Any]:
        return {
            "metadata_extraction_status": status,
            "metadata_extraction_detail": detail,
        }

    @staticmethod
    def _translate_metadata(
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
        for observation in extraction.observations:
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
        return EventIdentityFacts(
            country=values["country"],
            transit_system_name=values["transit_system_name"],
            location=str(values["location"] or ""),
            metadata_support=tuple(supports),
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
