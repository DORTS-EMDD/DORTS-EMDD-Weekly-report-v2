"""Small immutable contracts for the V2 Evidence boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping


class EvidenceState(StrEnum):
    """The only terminal states owned by EvidenceService."""

    READY = "EVIDENCE_READY"
    REJECTED = "EVIDENCE_REJECTED"


class RejectReason(StrEnum):
    """Reject vocabulary locked by the Architecture Contract."""

    URL_UNRESOLVED = "URL_UNRESOLVED"
    CONTENT_UNAVAILABLE = "CONTENT_UNAVAILABLE"
    SOURCE_PAGE_MISMATCH = "SOURCE_PAGE_MISMATCH"
    TITLE_ONLY = "TITLE_ONLY"
    INSUFFICIENT_SUBSTANCE = "INSUFFICIENT_SUBSTANCE"
    UNTRUSTWORTHY_SOURCE = "UNTRUSTWORTHY_SOURCE"


@dataclass(frozen=True, slots=True)
class CanonicalCandidate:
    """The minimum candidate input required before Evidence acquisition."""

    candidate_id: str
    title: str
    url: str
    publisher: str = ""
    published_at: str = ""
    discovery_intent: str = ""
    search_snippet: str = ""
    source_type: str = "web_source"

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CanonicalCandidate":
        """Create a candidate without retaining unrelated upstream fields."""

        return cls(
            candidate_id=str(value.get("candidate_id", "")),
            title=str(value.get("title", "")),
            url=str(value.get("url", "")),
            publisher=str(value.get("publisher", "")),
            published_at=str(value.get("published_at", "")),
            discovery_intent=str(value.get("discovery_intent", "")),
            search_snippet=str(value.get("search_snippet", "")),
            source_type=str(value.get("source_type", "web_source")),
        )


@dataclass(frozen=True, slots=True)
class FetchedSource:
    """Transport output consumed by EvidenceService.

    Transport reports what it obtained. It does not decide whether the
    content is authoritative evidence.
    """

    url: str
    content: str
    status_code: int = 200
    content_type: str = "text/html"
    redirect_chain: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EvidenceResult:
    """Authoritative EvidenceService output."""

    candidate_id: str
    state: EvidenceState
    canonical_source_url: str = ""
    source_type: str = ""
    substantive_content: str = ""
    provenance: Mapping[str, Any] = field(default_factory=dict)
    reject_reason: RejectReason | None = None

    def __post_init__(self) -> None:
        if self.state is EvidenceState.READY and self.reject_reason is not None:
            raise ValueError("EVIDENCE_READY cannot carry a reject reason")
        if self.state is EvidenceState.REJECTED and self.reject_reason is None:
            raise ValueError("EVIDENCE_REJECTED requires a reject reason")
        if self.state is EvidenceState.READY and not self.substantive_content.strip():
            raise ValueError("EVIDENCE_READY requires substantive_content")
        if self.state is EvidenceState.REJECTED and self.substantive_content:
            raise ValueError("Rejected evidence cannot expose authoritative content")
