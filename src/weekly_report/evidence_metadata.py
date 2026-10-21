"""Provider-agnostic, source-span grounded metadata extraction seam."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from .exact_text import exact_occurrence_offsets
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
class MetadataFieldDiagnostic:
    """Why one governed field was invalidated; other fields are unaffected."""

    field_name: MetadataFieldName
    reason: str
    proposed_values: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EvidenceMetadataExtraction:
    observations: tuple[MetadataFieldObservation, ...]
    field_diagnostics: tuple[MetadataFieldDiagnostic, ...] = ()


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
    derivation under EXACT_TEXT_ALL_OCCURRENCES: every exact occurrence of the
    unchanged value in the named segment is recorded and none is selected.

    A malformed response or observation shape invalidates the whole proposal.
    A value that is blank, names an unknown segment, or does not occur in it
    invalidates only its field; same-source distinct values for one field are
    a recorded conflict and that field is invalidated without choosing a value.
    """

    if not isinstance(raw_response, Mapping) or set(raw_response) != {"observations"}:
        raise InvalidEvidenceMetadataResponse("schema_invalid")
    raw_observations = raw_response["observations"]
    if not _is_array(raw_observations):
        raise InvalidEvidenceMetadataResponse("schema_invalid")

    segments = {segment.segment_id: segment.text for segment in request.principal_body_segments}
    field_order: list[str] = []
    values_by_field: dict[str, list[str]] = {}
    spans_by_field: dict[str, list[BodySpan]] = {}
    failures_by_field: dict[str, str] = {}
    for raw_observation in raw_observations:
        if not isinstance(raw_observation, Mapping) or set(raw_observation) != _OBSERVATION_FIELDS:
            raise InvalidEvidenceMetadataResponse("schema_invalid")
        field_name = raw_observation["field_name"]
        value = raw_observation["value"]
        segment_id = raw_observation["segment_id"]
        if not isinstance(field_name, str) or field_name not in _GOVERNED_FIELDS:
            raise InvalidEvidenceMetadataResponse("schema_invalid")
        if field_name not in field_order:
            field_order.append(field_name)
            values_by_field[field_name] = []
            spans_by_field[field_name] = []

        if not isinstance(value, str) or not value.strip():
            failures_by_field.setdefault(field_name, "VALUE_INVALID")
            continue
        if value not in values_by_field[field_name]:
            values_by_field[field_name].append(value)
        if not isinstance(segment_id, str) or segment_id not in segments:
            failures_by_field.setdefault(field_name, "UNKNOWN_SEGMENT")
            continue
        occurrences = exact_occurrence_offsets(segments[segment_id], value)
        if not occurrences:
            failures_by_field.setdefault(field_name, "VALUE_NOT_IN_SEGMENT")
            continue
        for start in occurrences:
            end = start + len(value)
            if segments[segment_id][start:end] != value:
                raise InvalidEvidenceMetadataResponse("schema_invalid")
            span = BodySpan(segment_id, start, end)
            if span not in spans_by_field[field_name]:
                spans_by_field[field_name].append(span)

    observations: list[MetadataFieldObservation] = []
    diagnostics: list[MetadataFieldDiagnostic] = []
    for field_name in field_order:
        values = tuple(values_by_field[field_name])
        if field_name in failures_by_field:
            diagnostics.append(MetadataFieldDiagnostic(field_name, failures_by_field[field_name], values))
        elif len(values) > 1:
            diagnostics.append(MetadataFieldDiagnostic(field_name, "SAME_SOURCE_DISTINCT_VALUES", values))
        else:
            observations.append(
                MetadataFieldObservation(field_name, values[0], tuple(spans_by_field[field_name]))
            )
    return EvidenceMetadataExtraction(tuple(observations), tuple(diagnostics))


def _is_array(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray, Mapping)
    )
