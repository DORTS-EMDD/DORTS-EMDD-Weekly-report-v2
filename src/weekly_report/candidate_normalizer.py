"""Mechanical Candidate normalization for successful discovery acquisitions."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from .contracts import (
    AcquisitionOrigin,
    AcquisitionRecord,
    CandidateNormalizationFailure,
    CandidateNormalizationFailureClass,
    CandidateNormalizationResult,
    CanonicalCandidate,
    NormalizedCandidate,
    candidate_id_for_url,
    acquisition_id_for,
)


class CandidateNormalizationError(ValueError):
    """Stable, payload-free failure at the normalizer boundary."""

    def __init__(self, failure: CandidateNormalizationFailure) -> None:
        if not isinstance(failure, CandidateNormalizationFailure):
            raise TypeError("CandidateNormalizationError requires a typed failure")
        self.failure = failure
        super().__init__(failure.failure_class.value)

    @property
    def failure_class(self) -> CandidateNormalizationFailureClass:
        return self.failure.failure_class


def _raise_failure(failure_class: CandidateNormalizationFailureClass) -> None:
    failure = CandidateNormalizationFailure(failure_class)
    raise CandidateNormalizationError(failure)


def _valid_exact_http_url(value: str) -> bool:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or any(char.isspace() for char in value)
        or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value)
    ):
        return False
    try:
        parsed = urlsplit(value)
        if parsed.scheme.casefold() not in {"http", "https"} or not parsed.netloc or not parsed.hostname:
            return False
        if "\\" in parsed.netloc or re.search(r"%(?![0-9A-Fa-f]{2})", value):
            return False
        parsed.port
    except (TypeError, ValueError):
        return False
    return True


class CandidateNormalizer:
    """The sole owner of exact-URL candidate and acquisition projection."""

    def normalize(self, acquisitions: tuple[AcquisitionRecord, ...]) -> CandidateNormalizationResult:
        if not isinstance(acquisitions, tuple):
            raise TypeError("CandidateNormalizer requires a tuple of AcquisitionRecord values")
        occurrence_records: dict[tuple[str, str, int], AcquisitionRecord] = {}
        for record in acquisitions:
            if not isinstance(record, AcquisitionRecord):
                _raise_failure(CandidateNormalizationFailureClass.INVALID_ACQUISITION)
            key = (
                record.plan_id,
                record.plan_item.plan_item_id,
                record.provider_result_ordinal,
            )
            prior = occurrence_records.get(key)
            if prior is not None:
                if prior.raw_result != record.raw_result:
                    _raise_failure(CandidateNormalizationFailureClass.INVALID_ACQUISITION)
                continue
            if not _valid_exact_http_url(record.raw_result.url):
                _raise_failure(CandidateNormalizationFailureClass.INVALID_URL)
            occurrence_records[key] = record

        by_url: dict[str, list[AcquisitionRecord]] = {}
        for record in occurrence_records.values():
            by_url.setdefault(record.raw_result.url, []).append(record)

        normalized: list[NormalizedCandidate] = []
        for url, records in by_url.items():
            internal_failure = False
            try:
                selected = min(
                    records,
                    key=lambda item: (
                        item.raw_result.title,
                        item.raw_result.publisher,
                        item.raw_result.published_at,
                        item.raw_result.snippet,
                        item.raw_result.url,
                    ),
                )
                candidate_id = candidate_id_for_url(url)
                candidate = CanonicalCandidate(
                    candidate_id=candidate_id,
                    title=selected.raw_result.title,
                    url=url,
                    publisher=selected.raw_result.publisher,
                    published_at=selected.raw_result.published_at,
                    discovery_intent=min(item.plan_item.intent.value for item in records),
                    search_snippet=selected.raw_result.snippet,
                    source_type="web_source",
                )
                origins = tuple(
                    AcquisitionOrigin(acquisition_id_for(item), item)
                    for item in records
                )
                normalized.append(NormalizedCandidate(candidate, origins))
            except CandidateNormalizationError:
                raise
            except (TypeError, ValueError):
                internal_failure = True
            if internal_failure:
                _raise_failure(CandidateNormalizationFailureClass.INTERNAL_FAILURE)

        internal_failure = False
        try:
            result = CandidateNormalizationResult(tuple(normalized))
        except (TypeError, ValueError):
            internal_failure = True
            result = None
        if internal_failure or result is None:
            _raise_failure(CandidateNormalizationFailureClass.INTERNAL_FAILURE)
        return result

    __call__ = normalize


def normalize_candidates(acquisitions: tuple[AcquisitionRecord, ...]) -> CandidateNormalizationResult:
    """Convenience wrapper preserving the normalizer's single owner."""

    return CandidateNormalizer().normalize(acquisitions)


__all__ = [
    "CandidateNormalizationError",
    "CandidateNormalizer",
    "normalize_candidates",
]
