"""Python candidate pairs for Event Identity confirmation (RC-79, section A.60).

Part of the Event Identity owner. It only nominates pairs: every pair still
goes through the helper confirmation of RC-23/RC-52 and becomes SAME_EVENT only
when at least two of the three procedures confirm it. It never merges,
separates or decides anything by itself.

Two eligible records form a candidate pair when all of these hold:

* their EvidenceService regions are not established and different (a record
  without an established region may pair with any record);
* their discovery publication times are both known and at most 72 hours apart;
* their title (without the publisher suffix) or their Scope event-focus
  sentences share a *feature term*: a term that appears in at least two and at
  most ``FEATURE_MAX_RECORDS`` records of this run.

Terms are read mechanically, with no name list: Latin-script words of at least
four characters; katakana runs of at least three characters; three-character
windows of Han and Hangul runs; and any quoted span (「」『』“”"" and similar)
of at least three characters. Generic urban-rail words (every profile's
governed mode words and the geographic reference's generic transit terms), the
words of those phrases, and a short multilingual stop-word list are not
feature terms. No system, operator or publisher name is written here.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from functools import lru_cache
from itertools import combinations
import json
from pathlib import Path
import re
import unicodedata

FEATURE_MAX_RECORDS = 3
PUBLICATION_WINDOW = timedelta(hours=72)
LATIN_MIN = 4
CJK_MIN = 3

_HERE = Path(__file__).resolve().parent
_QUOTED = re.compile(r"[「『“\"‘«„]([^」』”\"’»“]{%d,60})[」』”\"’»“]" % CJK_MIN)
_KATAKANA = re.compile(r"[ァ-ヺーㇰ-ㇿ]{%d,}" % CJK_MIN)
_HAN = re.compile(r"[㐀-䶿一-鿿豈-﫿]{%d,}" % CJK_MIN)
_HANGUL = re.compile(r"[가-힣]{%d,}" % CJK_MIN)
_WORD = re.compile(r"[^\W_]+(?:['’][^\W_]+)?")

# Common function and reporting words of the profile languages (four letters
# or more), and month and weekday names (a date is not an identity feature,
# RC-38); not names. Feature terms must also be rare in the run, so this
# list only spares obvious noise in very small runs.
_STOP_WORDS = frozenset(
    """
    about after also been before being between could during each from have into more most news only other over
    report reports said says since some such than that their them then there these they this those through under
    until were what when where which while will with would year years week today first last next
    nach nicht noch oder sich sind über unter wird wurde einen einer eines dass auch beim
    avec dans pour plus sont leur être cette mais après selon entre
    para como pero desde sobre entre tras este esta según
    della delle sono anche dopo nella degli alle come
    pela pelo como mais entre após sobre
    door voor naar zijn heeft werd deze over niet
    från till efter inte eller under över
    efter ikke eller over under
    etter ikke eller over under
    event events update article story video photo photos
    january february march april june july august september october november december
    monday tuesday wednesday thursday friday saturday sunday
    januar februar märz juni juli oktober dezember montag dienstag mittwoch donnerstag freitag samstag sonntag
    janvier février mars avril juin juillet août septembre octobre novembre décembre
    lundi mardi mercredi jeudi vendredi samedi dimanche
    enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre
    lunes martes miércoles jueves viernes sábado domingo
    gennaio febbraio aprile maggio giugno luglio settembre ottobre dicembre
    lunedì martedì mercoledì giovedì venerdì sabato domenica
    janeiro fevereiro março maio junho julho setembro outubro novembro dezembro
    segunda terça quarta quinta sexta sábado
    januari februari maart augustus mei juni juli oktober maandag dinsdag woensdag donderdag vrijdag zaterdag zondag
    augusti måndag tisdag onsdag torsdag fredag lördag söndag mandag tirsdag onsdag torsdag fredag lørdag søndag
    tammikuu helmikuu maaliskuu huhtikuu toukokuu kesäkuu heinäkuu elokuu syyskuu lokakuu marraskuu joulukuu
    leden únor březen duben květen červen červenec srpen září říjen listopad prosinec
    styczeń luty marzec kwiecień maj czerwiec lipiec sierpień wrzesień październik listopad grudzień
    """.split()
)


def _norm(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "").casefold()


@lru_cache(maxsize=1)
def generic_terms() -> frozenset[str]:
    """Governed generic urban-rail words: profile mode words and generic transit terms."""

    terms: set[str] = set()
    configuration = json.loads((_HERE / "search_configuration.json").read_text(encoding="utf-8"))
    for profile in configuration.get("profiles", ()):
        for vocabulary in profile.get("intent_vocabulary", {}).values():
            terms.update(vocabulary.get("urban_rail_terms", ()))
    reference = json.loads((_HERE / "geographic_reference.json").read_text(encoding="utf-8"))
    terms.update(reference.get("generic_transit_terms", ()))
    normalised = {_norm(term) for term in terms}
    # The words of a generic phrase ("metro line" -> metro, line) are generic too.
    normalised |= {word for term in normalised for word in term.split()}
    return frozenset(term for term in normalised if term)


def _is_generic(term: str, generic: frozenset[str]) -> bool:
    if term in generic or term in _STOP_WORDS:
        return True
    # A CJK window inside a generic word ("城市軌" in "城市軌道") is generic.
    return not term.isascii() and any(term in item for item in generic if not item.isascii())


def _cjk_windows(run: str) -> Iterable[str]:
    for start in range(0, len(run) - CJK_MIN + 1):
        yield run[start : start + CJK_MIN]


def feature_terms(text: str, generic: frozenset[str] | None = None) -> frozenset[str]:
    """The candidate feature terms of one text (before the run's rarity filter)."""

    generic = generic_terms() if generic is None else generic
    value = _norm(text)
    found: set[str] = set()
    for match in _QUOTED.finditer(value):
        found.add(" ".join(match.group(1).split()))
    found.update(_KATAKANA.findall(value))
    for pattern in (_HAN, _HANGUL):
        for run in pattern.findall(value):
            found.update(_cjk_windows(run))
    for word in _WORD.findall(value):
        if len(word) >= LATIN_MIN and all(ord(char) < 0x0250 for char in word) and not word.isdigit():
            found.add(word)
    return frozenset(term for term in found if len(term) >= CJK_MIN and not _is_generic(term, generic))


def _title_without_publisher(title: str, publisher: str) -> str:
    title = title or ""
    publisher = (publisher or "").strip()
    if publisher and title.rstrip().endswith(publisher):
        stripped = title.rstrip()[: -len(publisher)].rstrip()
        if stripped.endswith(("-", "–", "|", "｜")):
            return stripped[:-1].rstrip()
    return title


def _instant(raw: str) -> datetime | None:
    raw = str(raw or "").strip()
    if not raw:
        return None
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError):
        try:
            parsed = datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith(("Z", "z")) else raw)
        except ValueError:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def candidate_pairs(
    records: Sequence[object],
    *,
    focus_text: Mapping[str, str],
    different_regions,
    generic: frozenset[str] | None = None,
) -> dict[tuple[str, str], int]:
    """Pairs of candidate IDs and how many feature terms each pair shares.

    ``records`` are Event Identity records; ``focus_text`` maps a candidate ID
    to its Scope event-focus text; ``different_regions(left, right)`` is the
    owner's established-region conflict test (RC-22).
    """

    generic = generic_terms() if generic is None else generic
    terms: dict[str, frozenset[str]] = {}
    instants: dict[str, datetime | None] = {}
    by_id = {}
    for record in records:
        candidate = record.candidate  # type: ignore[attr-defined]
        candidate_id = candidate.candidate_id
        by_id[candidate_id] = record
        text = _title_without_publisher(candidate.title, candidate.publisher) + "\n" + focus_text.get(candidate_id, "")
        terms[candidate_id] = feature_terms(text, generic)
        instants[candidate_id] = _instant(candidate.published_at)
    holders: dict[str, list[str]] = {}
    for candidate_id, found in terms.items():
        for term in found:
            holders.setdefault(term, []).append(candidate_id)
    shared: dict[tuple[str, str], int] = {}
    for term, ids in holders.items():
        if not 2 <= len(ids) <= FEATURE_MAX_RECORDS:
            continue
        for left, right in combinations(sorted(ids), 2):
            shared[(left, right)] = shared.get((left, right), 0) + 1
    pairs: dict[tuple[str, str], int] = {}
    for (left, right), count in sorted(shared.items()):
        left_time, right_time = instants[left], instants[right]
        if left_time is None or right_time is None or abs(left_time - right_time) > PUBLICATION_WINDOW:
            continue
        if different_regions(by_id[left], by_id[right]):
            continue
        pairs[(left, right)] = count
    return pairs


__all__ = [
    "FEATURE_MAX_RECORDS",
    "PUBLICATION_WINDOW",
    "candidate_pairs",
    "feature_terms",
    "generic_terms",
]
