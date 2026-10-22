"""Python-assigned source references for event-level helpers (RC-16).

Category, Taxonomy and Reportability helpers see each EventGroup member as a
short reference (``M1``, ``M2``, ...) with its Evidence segmented into RC-9
sentences, and cite ``source_ref`` plus ``sentence_ids``. They never copy a
candidate ID or source text, so a citation cannot be mis-typed into an
invalid one. This module is mechanical and decides nothing.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .evidence_sentences import resolve_sentence_ids, segment_evidence_sentences


def source_refs(candidate_ids: Sequence[str]) -> dict[str, str]:
    """Map ``M1..Mn`` to candidate IDs in the owner's member order."""

    return {f"M{index}": candidate_id for index, candidate_id in enumerate(candidate_ids, start=1)}


def source_payload(source_ref: str, content: str) -> dict[str, Any]:
    return {
        "source_ref": source_ref,
        "sentences": [sentence.as_mapping() for sentence in segment_evidence_sentences(content)],
    }


def cited_spans(content: str, sentence_ids: object) -> tuple[tuple[int, int], ...] | None:
    """Return one ``[start, end)`` span per cited sentence, or None when invalid."""

    if not isinstance(sentence_ids, (list, tuple)):
        return None
    sentences = resolve_sentence_ids(segment_evidence_sentences(content), sentence_ids)
    if sentences is None:
        return None
    return tuple((sentence.start, sentence.end) for sentence in sentences)


__all__ = ["cited_spans", "source_payload", "source_refs"]
