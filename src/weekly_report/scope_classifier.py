"""Candidate-stage Scope owner.

ScopeClassifier consumes only an already-established EvidenceResult and
same-document facts supplied by that Evidence boundary.  It never searches,
fetches, or promotes discovery metadata into Scope proof.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from .contracts import (
    EvidenceResult,
    EvidenceState,
    ScopeDiagnostic,
    ScopeResult,
    ScopeState,
)


class ScopeSemanticSupport(StrEnum):
    """Non-authoritative relation returned by an optional Scope helper."""

    IN_SCOPE_SUPPORT = "IN_SCOPE_SUPPORT"
    OUT_OF_SCOPE_SUPPORT = "OUT_OF_SCOPE_SUPPORT"
    UNCERTAIN = "UNCERTAIN"


@dataclass(frozen=True, slots=True)
class ScopeSupportSpan:
    """A helper citation into the supplied principal content."""

    start: int
    end: int


@dataclass(frozen=True, slots=True)
class ScopeSemanticRequest:
    """The complete bounded input available to a Scope semantic helper."""

    candidate_id: str
    candidate_title: str
    principal_content: str
    source_metadata: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ScopeSemanticResponse:
    """Validated-shape response supplied by a constrained helper."""

    support: ScopeSemanticSupport | str
    support_spans: tuple[ScopeSupportSpan, ...] = ()
    diagnostic: ScopeDiagnostic = ScopeDiagnostic.SCOPE_NOT_ESTABLISHED


class ScopeSemanticHelper(Protocol):
    """A non-authoritative, no-I/O semantic interpretation helper."""

    def __call__(
        self, request: ScopeSemanticRequest
    ) -> ScopeSemanticResponse | Mapping[str, Any] | object:
        ...


def _span_from_mapping(value: object) -> ScopeSupportSpan | None:
    if isinstance(value, ScopeSupportSpan):
        return value
    if not isinstance(value, Mapping):
        return None
    try:
        return ScopeSupportSpan(int(value["start"]), int(value["end"]))
    except (KeyError, TypeError, ValueError):
        return None


def _coerce_response(value: object) -> ScopeSemanticResponse | None:
    if isinstance(value, ScopeSemanticResponse):
        return value
    if not isinstance(value, Mapping):
        return None
    support = value.get("support", value.get("relation", ""))
    spans = value.get("support_spans", value.get("spans", ()))
    if isinstance(spans, Mapping):
        spans = (spans,)
    if isinstance(spans, (str, bytes)) or not isinstance(spans, Sequence):
        return None
    parsed_spans = tuple(
        span for item in spans if (span := _span_from_mapping(item)) is not None
    )
    diagnostic = value.get("diagnostic", ScopeDiagnostic.SCOPE_NOT_ESTABLISHED)
    try:
        diagnostic = ScopeDiagnostic(diagnostic)
    except ValueError:
        diagnostic = ScopeDiagnostic.SCOPE_NOT_ESTABLISHED
    return ScopeSemanticResponse(
        support=support,
        support_spans=parsed_spans,
        diagnostic=diagnostic,
    )


def _valid_spans(
    spans: tuple[ScopeSupportSpan, ...], content: str
) -> tuple[ScopeSupportSpan, ...]:
    return tuple(
        span
        for span in spans
        if 0 <= span.start < span.end <= len(content)
    )


class ScopeClassifier:
    """The sole authoritative owner of IN_SCOPE / OUT_OF_SCOPE."""

    def __init__(self, semantic_helper: ScopeSemanticHelper | None = None) -> None:
        self._semantic_helper = semantic_helper

    def classify(
        self,
        evidence: EvidenceResult,
        *,
        candidate_title: str = "",
    ) -> ScopeResult:
        """Classify one EVIDENCE_READY Candidate without external I/O."""

        if evidence.state is not EvidenceState.READY:
            raise ValueError("ScopeClassifier requires EVIDENCE_READY evidence")

        if self._semantic_helper is None:
            return self._out_of_scope(
                evidence.candidate_id,
                ScopeDiagnostic.SCOPE_NOT_ESTABLISHED,
                {"reason": "mode_support_not_established"},
            )

        request = ScopeSemanticRequest(
            candidate_id=evidence.candidate_id,
            candidate_title=candidate_title,
            principal_content=evidence.substantive_content,
            source_metadata=dict(evidence.provenance),
        )
        try:
            response = _coerce_response(self._semantic_helper(request))
        except Exception as exc:
            return self._out_of_scope(
                evidence.candidate_id,
                ScopeDiagnostic.SCOPE_NOT_ESTABLISHED,
                {"helper_error": type(exc).__name__},
            )
        if response is None:
            return self._out_of_scope(
                evidence.candidate_id,
                ScopeDiagnostic.SCOPE_NOT_ESTABLISHED,
                {"helper_response": "invalid"},
            )

        try:
            support = ScopeSemanticSupport(response.support)
        except ValueError:
            support = ScopeSemanticSupport.UNCERTAIN
        spans = _valid_spans(response.support_spans, evidence.substantive_content)
        if support is ScopeSemanticSupport.IN_SCOPE_SUPPORT and spans:
            return ScopeResult(
                candidate_id=evidence.candidate_id,
                state=ScopeState.IN_SCOPE,
                provenance={
                    "decision_basis": "constrained_scope_helper",
                    "validated_support_spans": [
                        {"start": span.start, "end": span.end} for span in spans
                    ],
                },
            )
        if support is ScopeSemanticSupport.OUT_OF_SCOPE_SUPPORT and spans:
            diagnostic = response.diagnostic
            if diagnostic is ScopeDiagnostic.NONE:
                diagnostic = ScopeDiagnostic.SCOPE_NOT_ESTABLISHED
            return self._out_of_scope(
                evidence.candidate_id,
                diagnostic,
                {
                    "decision_basis": "constrained_scope_helper",
                    "validated_support_spans": [
                        {"start": span.start, "end": span.end} for span in spans
                    ],
                },
            )
        return self._out_of_scope(
            evidence.candidate_id,
            ScopeDiagnostic.SCOPE_NOT_ESTABLISHED,
            {"decision_basis": "constrained_scope_helper", "support": support.value},
        )

    evaluate = classify

    @staticmethod
    def _out_of_scope(
        candidate_id: str,
        diagnostic: ScopeDiagnostic,
        provenance: Mapping[str, Any],
    ) -> ScopeResult:
        return ScopeResult(
            candidate_id=candidate_id,
            state=ScopeState.OUT_OF_SCOPE,
            diagnostic=diagnostic,
            provenance=dict(provenance),
        )


__all__ = [
    "ScopeClassifier",
    "ScopeSemanticHelper",
    "ScopeSemanticRequest",
    "ScopeSemanticResponse",
    "ScopeSemanticSupport",
    "ScopeSupportSpan",
]
