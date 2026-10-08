"""Provider-agnostic, source-span grounded metadata extraction seam."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from .semantic_judge import BodySpan, PrincipalBodySegment


MetadataFieldName = Literal["country", "transit_system_name", "location"]
_GOVERNED_FIELDS = frozenset({"country", "transit_system_name", "location"})
_OBSERVATION_FIELDS = frozenset({"field_name", "value", "segment_id"})


@dataclass(frozen=True, slots=True)
class EvidenceMetadataRequest:
    """The only input available to a subordinate metadata extractor."""

    candidate_id: str
    principal_body_segments: tuple[PrincipalBodySegment, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.candidate_id, str):
            raise TypeError("candidate_id must be a string")
        segments = tuple(self.principal_body_segments)
        if any(not isinstance(segment, PrincipalBodySegment) for segment in segments):
            raise TypeError("principal_body_segments must contain PrincipalBodySegment values")
        ids = [segment.segment_id for segment in segments]
        if any(
            not isinstance(segment.segment_id, str) or not isinstance(segment.text, str)
            for segment in segments
        ):
            raise TypeError("principal body segment IDs and text must be strings")
        if len(ids) != len(set(ids)):
            raise ValueError("principal_body_segments must have unique segment IDs")
        object.__setattr__(self, "principal_body_segments", segments)


@dataclass(frozen=True, slots=True)
class MetadataFieldObservation:
    field_name: MetadataFieldName
    value: str
    support_spans: tuple[BodySpan, ...]


@dataclass(frozen=True, slots=True)
class EvidenceMetadataExtraction:
    observations: tuple[MetadataFieldObservation, ...]


class EvidenceMetadataExtractor(Protocol):
    def __call__(self, request: EvidenceMetadataRequest) -> object:
        """Return raw proposed observations without deciding Evidence state."""


class InvalidEvidenceMetadataResponse(ValueError):
    """The subordinate metadata response failed its strict schema."""

    def __init__(self, detail: str = "schema_invalid") -> None:
        super().__init__(detail)
        self.detail = detail


def validate_evidence_metadata_response(
    raw_response: object,
    request: EvidenceMetadataRequest,
) -> EvidenceMetadataExtraction:
    """Validate proposals and derive canonical spans from exact source text.

    The subordinate model chooses a governed field, its exact source-surface
    value, and the segment that contains it.  Python owns character-coordinate
    derivation: a proposal is accepted only when that value occurs exactly once
    in the named segment.  ``str.find`` is advanced by one code point so
    overlapping occurrences are counted as ambiguous too.
    """

    if not isinstance(raw_response, Mapping) or set(raw_response) != {"observations"}:
        raise InvalidEvidenceMetadataResponse("schema_invalid")
    raw_observations = raw_response["observations"]
    if not _is_array(raw_observations):
        raise InvalidEvidenceMetadataResponse("schema_invalid")

    segments = {segment.segment_id: segment.text for segment in request.principal_body_segments}
    ordered: list[MetadataFieldObservation] = []
    by_field: dict[str, MetadataFieldObservation] = {}
    for raw_observation in raw_observations:
        if not isinstance(raw_observation, Mapping) or set(raw_observation) != _OBSERVATION_FIELDS:
            raise InvalidEvidenceMetadataResponse("schema_invalid")
        field_name = raw_observation["field_name"]
        value = raw_observation["value"]
        segment_id = raw_observation["segment_id"]
        if not isinstance(field_name, str) or field_name not in _GOVERNED_FIELDS:
            raise InvalidEvidenceMetadataResponse("schema_invalid")
        if not isinstance(value, str) or not value.strip():
            raise InvalidEvidenceMetadataResponse("schema_invalid")
        if not isinstance(segment_id, str) or segment_id not in segments:
            raise InvalidEvidenceMetadataResponse("schema_invalid")

        occurrence_offsets = _exact_occurrence_offsets(segments[segment_id], value)
        if len(occurrence_offsets) != 1:
            raise InvalidEvidenceMetadataResponse("schema_invalid")
        start = occurrence_offsets[0]
        end = start + len(value)
        if segments[segment_id][start:end] != value:
            raise InvalidEvidenceMetadataResponse("schema_invalid")
        spans = [BodySpan(segment_id, start, end)]

        prior = by_field.get(field_name)
        if prior is None:
            observation = MetadataFieldObservation(field_name, value, tuple(spans))
            by_field[field_name] = observation
            ordered.append(observation)
            continue
        if prior.value != value:
            raise InvalidEvidenceMetadataResponse("same_source_distinct_values")
        combined = list(prior.support_spans)
        seen = set(combined)
        for span in spans:
            if span not in seen:
                seen.add(span)
                combined.append(span)
        replacement = MetadataFieldObservation(field_name, prior.value, tuple(combined))
        by_field[field_name] = replacement
        ordered[ordered.index(prior)] = replacement

    return EvidenceMetadataExtraction(tuple(ordered))


def _exact_occurrence_offsets(source: str, value: str) -> tuple[int, ...]:
    """Return every exact occurrence, including overlapping occurrences."""

    offsets: list[int] = []
    cursor = source.find(value)
    while cursor >= 0:
        offsets.append(cursor)
        cursor = source.find(value, cursor + 1)
    return tuple(offsets)


def _is_array(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray, Mapping)
    )
