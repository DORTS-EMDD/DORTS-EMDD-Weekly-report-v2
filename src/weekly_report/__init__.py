"""Minimal V2 production boundary exports."""

from .contracts import (
    CanonicalCandidate,
    EvidenceResult,
    EvidenceState,
    FetchedSource,
    RejectReason,
)
from .evidence_service import EvidenceService

__all__ = [
    "CanonicalCandidate",
    "EvidenceResult",
    "EvidenceService",
    "EvidenceState",
    "FetchedSource",
    "RejectReason",
]
