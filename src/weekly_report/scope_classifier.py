"""Candidate-stage Scope owner.

ScopeClassifier consumes only an already-established EvidenceResult and
same-document facts supplied by that Evidence boundary.  It never searches,
fetches, or promotes discovery metadata into Scope proof.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
import re
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


# These expressions describe the finite transport families and boundary
# language in SCOPE_CONTRACT.  They are deliberately used only as part of an
# event-level statement recognizer below: an isolated family word never
# establishes Scope.
_ELIGIBLE_MODE_PATTERN = (
    r"metro|mrt|subway|light\s+rail|tram|streetcar|urban[- ]rail|agt|"
    r"automated\s+guideway\s+transit|monorail|people[- ]mover"
)
_ELIGIBLE_MODE = re.compile(
    rf"(?<![\w-])(?:{_ELIGIBLE_MODE_PATTERN})(?![\w-])",
    re.IGNORECASE,
)
_JAPANESE_SUBWAY = re.compile(r"地下鉄")
_EXCLUDED_MODE = re.compile(
    r"\b(?:funicular|cable\s+rail(?:way)?|cable-hauled|"
    r"conventional\s+(?:mainline\s+)?airport\s+express|"
    r"mainline\s+airport\s+express)\b",
    re.IGNORECASE,
)
_NON_URBAN_MODE = re.compile(
    r"\b(?:commuter|suburban|regional|intercity|high[- ]speed|"
    r"conventional|mainline|bus|aviation|aircraft)\b",
    re.IGNORECASE,
)
_GENERIC_RAIL = re.compile(r"\b(?:railway|railroad|rail\s+service)\b", re.IGNORECASE)
_ACTION = re.compile(
    r"\b(?:install(?:ed|s|ation)?|commission(?:ed|s)?|upgrade(?:d|s)?|"
    r"open(?:ed|s|ing)?|deploy(?:ed|s|ment)?|pilot(?:ed|s|ing)?|"
    r"replace(?:d|s|ment)?|add(?:ed|s|ing)?|introduc(?:e|ed|es|ing)|"
    r"implement(?:ed|s|ation)?|construct(?:ed|s|ion)?|"
    r"launch(?:ed|es|ing)?|complete(?:d|s|ion)?|test(?:ed|s|ing)?|"
    r"renew(?:ed|s|al)?|retrofit(?:ted|s|ting)?|receive(?:d|s)?|"
    r"announce(?:d|s)?|deliver(?:ed|s)?|award(?:ed|s)?|"
    r"action|event|activity|works?)\b",
    re.IGNORECASE,
)
_JAPANESE_ACTION = re.compile(r"(?:導入|設置|更新|改修|運用開始|発表|試験|建設|交換)")
_MODE_ASSERTION = re.compile(
    r"\b(?:is|are|was|were|be|classified|identified|described|"
    r"operating|operates|known)\b.{0,80}\b(?:as|a|an|the)?\s*"
    rf"(?:{_ELIGIBLE_MODE_PATTERN})\b"
    rf"|\b(?:{_ELIGIBLE_MODE_PATTERN})\b"
    r"\s+(?:system|network|line|station|service|connector|route|segment|portion)\b",
    re.IGNORECASE,
)
_RELATION_PREPOSITION = re.compile(
    r"\b(?:at|on|for|to|within|along|between|of|from)\b",
    re.IGNORECASE,
)
_IDENTITY_ONLY = re.compile(
    r"\b(?:publisher|operator|company|agency|authority|division)\b"
    r".{0,55}\b(?:operates|runs|owns|manages|serves)\b",
    re.IGNORECASE,
)
_UNRESOLVED = re.compile(
    r"(?:does\s+not\s+identify\s+whether|does\s+not\s+identify\s+which|"
    r"does\s+not\s+establish\s+(?:which|whether)|cannot\s+identify|"
    r"cannot\s+be\s+resolved|"
    r"cannot\s+be\s+reliably\s+isolated|does\s+not\s+say\s+whether|"
    r"does\s+not\s+(?:tie|link|associate|attribute)\b|"
    r"shared\s+(?:corridor|control)|unclear\s+whether)",
    re.IGNORECASE,
)
_ONLY_NON_URBAN = re.compile(
    r"(?:\b(?:event|action|activity)\b.{0,45}\bconcerns?\s+only\b|"
    r"\b(?:only|solely)\s+(?:the\s+)?(?:intercity|mainline|conventional|"
    r"commuter|regional|suburban)\b)",
    re.IGNORECASE,
)
def _content_sentences(content: str) -> tuple[tuple[int, int, str], ...]:
    """Return bounded sentence-like spans without changing source offsets."""

    result: list[tuple[int, int, str]] = []
    for match in re.finditer(r"[^.!?。！？;；\n]+(?:[.!?。！？;；\n]|$)", content):
        start, end = match.span()
        text = content[start:end].strip()
        if not text:
            continue
        leading = len(content[start:end]) - len(content[start:end].lstrip())
        trailing = len(content[start:end].rstrip())
        result.append((start + leading, start + trailing, text))
    return tuple(result)


def _has_mode_negation(sentence: str, mode_start: int) -> bool:
    """Recognize an explicit negation attached to one mode mention."""

    left = sentence[max(0, mode_start - 160) : mode_start]
    return bool(
        re.search(
            r"(?:\bno\s+(?:eligible\s+)?(?:mode|system|service|metro|mrt|"
            r"subway|tram|streetcar|urban[- ]rail|agt|monorail|people[- ]mover)\b|"
            r"\bwithout\s+(?:an?\s+)?eligible\b|\bnot\s+(?:an?\s+)?|"
            r"\bdoes\s+not\s+(?:establish|identify)\b|"
            r"\bdoesn't\s+(?:establish|identify)\b)",
            left,
            re.IGNORECASE,
        )
    )


def _has_direct_event_relation(sentence: str, mode_start: int, mode_end: int) -> bool:
    """Require a local event predicate and an attributable mode relation."""

    action_matches = tuple(_ACTION.finditer(sentence))
    if not action_matches and not _JAPANESE_ACTION.search(sentence):
        return False
    if _JAPANESE_SUBWAY.search(sentence) and _JAPANESE_ACTION.search(sentence):
        return True

    before = sentence[:mode_start]
    # A mode assertion such as ``the service is the Metro system`` can bind
    # the later action in the same sentence, including conjunctions.
    if _MODE_ASSERTION.search(sentence):
        return True

    # The action must either name the eligible system as its object or use it
    # as the event subject.  This prevents ``Metro operator installed a bus``
    # from being promoted by the word Metro alone.
    for action_match in action_matches:
        if action_match.start() < mode_end:
            continue
        if _RELATION_PREPOSITION.search(sentence[mode_end : action_match.start()]):
            return True
    if any(match.end() <= mode_start for match in action_matches) and _RELATION_PREPOSITION.search(
        before[-90:]
    ):
        return True
    if any(
        mode_end <= match.start() <= mode_end + 55
        and not _NON_URBAN_MODE.search(sentence[match.end() :])
        for match in action_matches
    ):
        return True
    return False


def _interpret_authoritative_content(
    content: str,
) -> tuple[ScopeSemanticSupport, ScopeDiagnostic, tuple[ScopeSupportSpan, ...]]:
    """Interpret only explicit event-to-mode statements in principal content.

    This is intentionally a small, fail-closed statement recognizer.  It does
    not inspect Candidate titles, provenance, search fields, publisher names,
    or arbitrary mode vocabulary.  A positive result requires an action
    predicate and a local, attributable relation to a listed eligible family.
    """

    sentences = _content_sentences(content)
    positive_spans: list[ScopeSupportSpan] = []
    has_nonurban_event = False
    has_excluded_event = False
    has_mixed_modes = False
    has_identity_only_nonurban_event = False
    for start, end, sentence in sentences:
        eligible_matches = tuple(_ELIGIBLE_MODE.finditer(sentence))
        active_eligible_matches = tuple(
            match
            for match in eligible_matches
            if not _has_mode_negation(sentence, match.start())
        )
        has_japanese_mode = bool(_JAPANESE_SUBWAY.search(sentence))
        nonurban = bool(_NON_URBAN_MODE.search(sentence) or _GENERIC_RAIL.search(sentence))
        excluded = bool(_EXCLUDED_MODE.search(sentence))
        has_nonurban_event |= bool(_ACTION.search(sentence)) and nonurban
        has_excluded_event |= bool(_ACTION.search(sentence)) and excluded
        has_identity_only_nonurban_event |= bool(_IDENTITY_ONLY.search(sentence)) and nonurban
        if active_eligible_matches and nonurban:
            has_mixed_modes = True
        for match in eligible_matches:
            if _has_mode_negation(sentence, match.start()):
                continue
            if _has_direct_event_relation(sentence, match.start(), match.end()):
                # Identity-only sentences are usable only when their event
                # clause independently binds the action to the mode.
                action_matches = tuple(_ACTION.finditer(sentence))
                has_forward_binding = bool(
                    _RELATION_PREPOSITION.search(sentence[match.end() :])
                )
                has_reverse_binding = any(
                    action_match.end() <= match.start()
                    and _RELATION_PREPOSITION.search(sentence[action_match.end() : match.start()])
                    for action_match in action_matches
                )
                if _IDENTITY_ONLY.search(sentence) and not (
                    has_forward_binding or has_reverse_binding
                ):
                    continue
                positive_spans.append(ScopeSupportSpan(start, end))
                break
        if has_japanese_mode and _JAPANESE_ACTION.search(sentence):
            positive_spans.append(ScopeSupportSpan(start, end))

    if positive_spans and not _UNRESOLVED.search(content) and not _ONLY_NON_URBAN.search(content):
        return ScopeSemanticSupport.IN_SCOPE_SUPPORT, ScopeDiagnostic.NONE, tuple(positive_spans)
    if has_excluded_event:
        return ScopeSemanticSupport.OUT_OF_SCOPE_SUPPORT, ScopeDiagnostic.EXCLUDED_TRANSPORT_MODE, ()
    if _ONLY_NON_URBAN.search(content):
        return ScopeSemanticSupport.OUT_OF_SCOPE_SUPPORT, ScopeDiagnostic.NON_URBAN_RAIL, ()
    if has_identity_only_nonurban_event:
        return ScopeSemanticSupport.OUT_OF_SCOPE_SUPPORT, ScopeDiagnostic.NON_URBAN_RAIL, ()
    if _UNRESOLVED.search(content) or (has_mixed_modes and not positive_spans):
        return ScopeSemanticSupport.OUT_OF_SCOPE_SUPPORT, ScopeDiagnostic.SCOPE_NOT_ESTABLISHED, ()
    if has_nonurban_event:
        return ScopeSemanticSupport.OUT_OF_SCOPE_SUPPORT, ScopeDiagnostic.NON_URBAN_RAIL, ()
    return ScopeSemanticSupport.UNCERTAIN, ScopeDiagnostic.SCOPE_NOT_ESTABLISHED, ()


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
            support, diagnostic, spans = _interpret_authoritative_content(
                evidence.substantive_content
            )
            if support is ScopeSemanticSupport.IN_SCOPE_SUPPORT and spans:
                return ScopeResult(
                    candidate_id=evidence.candidate_id,
                    state=ScopeState.IN_SCOPE,
                    provenance={
                        "decision_basis": "authoritative_event_mode_relation",
                        "validated_support_spans": [
                            {"start": span.start, "end": span.end} for span in spans
                        ],
                    },
                )
            return self._out_of_scope(
                evidence.candidate_id,
                diagnostic,
                {"decision_basis": "authoritative_event_mode_relation"},
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
