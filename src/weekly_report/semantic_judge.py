"""Provider-agnostic Semantic Judge boundary for EvidenceService.

This module validates comparison data and judge responses. It never decides
EVIDENCE_READY or EVIDENCE_REJECTED.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from typing import Any, Protocol


class SemanticRelation(StrEnum):
    SAME_EVENT = "SAME_EVENT"
    DIFFERENT_EVENT = "DIFFERENT_EVENT"
    UNCERTAIN = "UNCERTAIN"


@dataclass(frozen=True, slots=True)
class PrincipalBodySegment:
    segment_id: str
    text: str


@dataclass(frozen=True, slots=True)
class SemanticJudgeInput:
    candidate_id: str
    candidate_title: str
    document_level_headlines: tuple[str, ...]
    principal_body_segments: tuple[PrincipalBodySegment, ...]

    def as_payload(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "candidate_title": self.candidate_title,
            "document_level_headlines": list(self.document_level_headlines),
            "principal_body_segments": [
                {"segment_id": segment.segment_id, "text": segment.text}
                for segment in self.principal_body_segments
            ],
        }


@dataclass(frozen=True, slots=True)
class JudgeMetadata:
    model_identifier: str = ""
    prompt_version: str = ""
    schema_version: str = ""


@dataclass(frozen=True, slots=True)
class BodySpan:
    segment_id: str
    start: int
    end: int

    def as_mapping(self) -> dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "start": self.start,
            "end": self.end,
        }


@dataclass(frozen=True, slots=True)
class ValidatedSemanticJudgeResponse:
    relation: SemanticRelation
    support_spans: tuple[BodySpan, ...]
    conflict_spans: tuple[BodySpan, ...]
    explanation: str


class SemanticJudge(Protocol):
    def __call__(self, request: SemanticJudgeInput) -> object:
        """Return the provider response without deciding Evidence state."""


class InvalidSemanticJudgeResponse(ValueError):
    """The provider response failed the locked response contract."""


_RESPONSE_FIELDS = frozenset(
    {"relation", "support_spans", "conflict_spans", "explanation"}
)
_SPAN_FIELDS = frozenset({"segment_id", "start", "end"})


def semantic_judge_input_hash(request: SemanticJudgeInput) -> str:
    """Hash the exact canonical input supplied to the Semantic Judge."""

    serialized = json.dumps(
        request.as_payload(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def validate_semantic_judge_response(
    raw_response: object,
    request: SemanticJudgeInput,
) -> ValidatedSemanticJudgeResponse:
    """Parse and strictly validate one provider response against exact input."""

    response = _parse_response_object(raw_response)
    if frozenset(response) != _RESPONSE_FIELDS:
        raise InvalidSemanticJudgeResponse("response fields do not match schema")

    relation = response["relation"]
    if not isinstance(relation, str) or relation not in {
        item.value for item in SemanticRelation
    }:
        raise InvalidSemanticJudgeResponse("relation is not a valid enum value")
    explanation = response["explanation"]
    if not isinstance(explanation, str):
        raise InvalidSemanticJudgeResponse("explanation must be a string")

    segments = {
        segment.segment_id: segment.text
        for segment in request.principal_body_segments
    }
    support_spans = _validate_spans(response["support_spans"], segments)
    conflict_spans = _validate_spans(response["conflict_spans"], segments)
    if relation == SemanticRelation.SAME_EVENT and not support_spans:
        raise InvalidSemanticJudgeResponse(
            "SAME_EVENT requires at least one support span"
        )

    return ValidatedSemanticJudgeResponse(
        relation=SemanticRelation(relation),
        support_spans=support_spans,
        conflict_spans=conflict_spans,
        explanation=explanation,
    )


def _parse_response_object(raw_response: object) -> Mapping[str, Any]:
    response: object = raw_response
    if isinstance(raw_response, (str, bytes, bytearray)):
        try:
            response = json.loads(raw_response)
        except (TypeError, ValueError) as exc:
            raise InvalidSemanticJudgeResponse("response is not valid JSON") from exc
    if not isinstance(response, Mapping):
        raise InvalidSemanticJudgeResponse("response must be an object")
    return response


def _validate_spans(
    raw_spans: object,
    segments: Mapping[str, str],
) -> tuple[BodySpan, ...]:
    if not isinstance(raw_spans, Sequence) or isinstance(
        raw_spans, (str, bytes, bytearray)
    ):
        raise InvalidSemanticJudgeResponse("spans must be an array")

    validated: list[BodySpan] = []
    for raw_span in raw_spans:
        if not isinstance(raw_span, Mapping):
            raise InvalidSemanticJudgeResponse("span must be an object")
        if frozenset(raw_span) != _SPAN_FIELDS:
            raise InvalidSemanticJudgeResponse("span fields do not match schema")
        segment_id = raw_span["segment_id"]
        start = raw_span["start"]
        end = raw_span["end"]
        if not isinstance(segment_id, str) or segment_id not in segments:
            raise InvalidSemanticJudgeResponse("span references an unknown segment")
        if (
            isinstance(start, bool)
            or not isinstance(start, int)
            or isinstance(end, bool)
            or not isinstance(end, int)
        ):
            raise InvalidSemanticJudgeResponse("span offsets must be integers")
        if start < 0 or start >= end or end > len(segments[segment_id]):
            raise InvalidSemanticJudgeResponse("span offsets are out of range")
        validated.append(BodySpan(segment_id, start, end))
    return tuple(validated)
