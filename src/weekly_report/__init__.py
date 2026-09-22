"""Minimal V2 production boundary exports."""

from .contracts import (
    CanonicalCandidate,
    EvidenceResult,
    EvidenceState,
    FetchedSource,
    RejectReason,
    ScopeDiagnostic,
    ScopeResult,
    ScopeState,
    SourceDateFact,
    SourceDateKind,
    TemporalDiagnostic,
    TemporalResult,
)
from .evidence_service import EvidenceService
from .scope_classifier import (
    ScopeClassifier,
    ScopeSemanticRequest,
    ScopeSemanticResponse,
    ScopeSemanticSupport,
    ScopeSupportSpan,
)
from .temporal_rule import TemporalRule

__all__ = [
    "CanonicalCandidate",
    "EvidenceResult",
    "EvidenceService",
    "EvidenceState",
    "FetchedSource",
    "RejectReason",
    "ScopeClassifier",
    "ScopeDiagnostic",
    "ScopeResult",
    "ScopeSemanticRequest",
    "ScopeSemanticResponse",
    "ScopeSemanticSupport",
    "ScopeState",
    "ScopeSupportSpan",
    "SourceDateFact",
    "SourceDateKind",
    "TemporalDiagnostic",
    "TemporalResult",
    "TemporalRule",
]
