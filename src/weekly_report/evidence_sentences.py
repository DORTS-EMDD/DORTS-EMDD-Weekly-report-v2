"""Deterministic sentence segmentation of authoritative Evidence text (RC-9).

Structured helpers cite Evidence by sentence ID instead of re-typing source
text, so a citation can never be a mis-copied or invented quotation.  This
module is purely mechanical: it decides nothing about meaning, and every
non-whitespace character of the content belongs to exactly one sentence.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

_CJK_TERMINATORS = frozenset("。！？；")
_ASCII_TERMINATORS = frozenset(".!?")
_CLOSERS = frozenset("」』）〕】》〉”’\"')]")
# Short tokens that end with a period without ending a sentence.
_ABBREVIATIONS = frozenset(
    {"st", "no", "nos", "mr", "mrs", "ms", "dr", "prof", "co", "corp", "inc", "ltd", "jr", "sr", "vs", "etc",
     "fig", "approx", "dept", "gov", "rep", "sen", "gen", "lt", "col", "capt", "mt", "ft", "e.g", "i.e", "u.s", "u.k"}
)


@dataclass(frozen=True, slots=True)
class EvidenceSentence:
    sentence_id: str
    start: int
    end: int
    text: str

    def as_mapping(self) -> dict[str, str]:
        return {"sentence_id": self.sentence_id, "text": self.text}


def _ascii_sentence_end(content: str, index: int) -> bool:
    """A period/!/? ends a sentence before whitespace and a non-lowercase start."""

    following = index + 1
    while following < len(content) and content[following] in _CLOSERS:
        following += 1
    if following >= len(content):
        return True
    if not content[following].isspace():
        return False
    nxt = following
    while nxt < len(content) and content[nxt].isspace():
        nxt += 1
    if nxt >= len(content):
        return True
    upcoming = content[nxt]
    if upcoming.isdigit() or (upcoming.isascii() and upcoming.islower()):
        return False
    if content[index] == ".":
        token_start = index
        while token_start > 0 and not content[token_start - 1].isspace():
            token_start -= 1
        token = content[token_start:index].strip("\"'(“‘").casefold()
        if token in _ABBREVIATIONS or (len(token) == 1 and token.isalpha()):
            return False
    return True


def segment_evidence_sentences(content: str) -> tuple[EvidenceSentence, ...]:
    """Split Evidence text into ordered sentences with IDs ``S1``, ``S2``, …"""

    if not isinstance(content, str):
        raise TypeError("Evidence sentence segmentation requires text")
    boundaries: list[int] = []
    length = len(content)
    index = 0
    while index < length:
        character = content[index]
        end = None
        if character == "\n":
            end = index + 1
        elif character in _CJK_TERMINATORS:
            end = index + 1
            while end < length and (content[end] in _CJK_TERMINATORS or content[end] in _CLOSERS):
                end += 1
        elif character in _ASCII_TERMINATORS and _ascii_sentence_end(content, index):
            end = index + 1
            while end < length and (content[end] in _ASCII_TERMINATORS or content[end] in _CLOSERS):
                end += 1
        if end is not None:
            boundaries.append(end)
            index = end
            continue
        index += 1
    boundaries.append(length)

    sentences: list[EvidenceSentence] = []
    start = 0
    for boundary in boundaries:
        segment = content[start:boundary]
        stripped = segment.strip()
        if stripped:
            offset = start + (len(segment) - len(segment.lstrip()))
            sentences.append(
                EvidenceSentence(f"S{len(sentences) + 1}", offset, offset + len(stripped), stripped)
            )
        start = boundary
    return tuple(sentences)


def resolve_sentence_ids(
    sentences: tuple[EvidenceSentence, ...],
    sentence_ids: Iterable[object],
) -> tuple[EvidenceSentence, ...] | None:
    """Return the cited sentences in document order, or None when invalid.

    A citation is invalid when it is empty, repeats an ID, or names an ID that
    the segmentation did not produce.
    """

    by_id = {sentence.sentence_id: sentence for sentence in sentences}
    ids = list(sentence_ids)
    if not ids or len(set(map(str, ids))) != len(ids):
        return None
    if any(not isinstance(value, str) or value not in by_id for value in ids):
        return None
    return tuple(sorted((by_id[value] for value in ids), key=lambda sentence: sentence.start))


def event_focus_sentences(content: str, focus_spans: object) -> tuple[EvidenceSentence, ...]:
    """The Candidate's event-focus sentences recorded by Scope (RC-20), in order.

    ``focus_spans`` is the Scope provenance ``candidate_event_focus`` list of
    ``{"start", "end"}`` sentence spans. Returns the matching sentences of
    ``content``; an absent or unusable record yields no sentences.
    """

    if not isinstance(focus_spans, (list, tuple)):
        return ()
    wanted = {
        (span.get("start"), span.get("end"))
        for span in focus_spans
        if isinstance(span, dict)
    }
    return tuple(
        sentence for sentence in segment_evidence_sentences(content) if (sentence.start, sentence.end) in wanted
    )


def cited_text(sentences: tuple[EvidenceSentence, ...]) -> str:
    return " ".join(sentence.text for sentence in sentences)


__all__ = ["EvidenceSentence", "segment_evidence_sentences", "resolve_sentence_ids", "event_focus_sentences", "cited_text"]
