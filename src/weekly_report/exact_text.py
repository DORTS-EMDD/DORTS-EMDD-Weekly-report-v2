"""The single mechanical exact-text locator (EXACT_TEXT_ALL_OCCURRENCES).

Semantic helpers propose exact source text; Python derives coordinates.  A
proposed text is located at every exact occurrence, including overlapping
occurrences.  No occurrence is selected, so first/last/nearest/longest choice
cannot arise.  Locating text never proves a semantic relation: each owner keeps
its own relation and context checks.
"""

from __future__ import annotations


EXACT_TEXT_ALL_OCCURRENCES = "EXACT_TEXT_ALL_OCCURRENCES"
EXACT_TEXT_RESOLUTION = EXACT_TEXT_ALL_OCCURRENCES


def exact_occurrence_offsets(source: str, value: str) -> tuple[int, ...]:
    """Return every exact occurrence of ``value`` in ``source`` in ascending order."""

    if not isinstance(source, str) or not isinstance(value, str) or not value:
        return ()
    offsets: list[int] = []
    cursor = source.find(value)
    while cursor >= 0:
        offsets.append(cursor)
        cursor = source.find(value, cursor + 1)
    return tuple(offsets)


__all__ = ["EXACT_TEXT_ALL_OCCURRENCES", "EXACT_TEXT_RESOLUTION", "exact_occurrence_offsets"]
