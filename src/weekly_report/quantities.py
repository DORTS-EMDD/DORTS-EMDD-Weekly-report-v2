"""Mechanical quantity reading for the Validator's numeric grounding check (RC-29).

Reads the quantities a text states (number, magnitude word, measurement unit)
so the Validator can compare Writer prose with the authoritative Evidence.
It decides nothing; ``Validator`` owns the check. Evidence numbers are read
with every plausible separator convention (``16,4`` and ``1.640`` are
ambiguous across languages), so the check never rejects a correct value
because of a separator; a magnitude error is still caught.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

# Magnitude words by language. CJK magnitude characters compose ("1兆9000億").
_CJK_MAGNITUDES = {"兆": 10**12, "億": 10**8, "亿": 10**8, "萬": 10**4, "万": 10**4, "조": 10**12, "억": 10**8, "만": 10**4}
_WORD_MAGNITUDES = (
    # Longest first so "lakh crore" wins over "crore".
    (r"lakh\s+crores?", 10**12),
    (r"mil\s+millones", 10**9),
    (r"mil\s+milh(?:ões|oes)", 10**9),
    (r"crores?|cr\.?", 10**7),
    (r"lakhs?|lacs?", 10**5),
    (r"trillions?|tn", 10**12),
    (r"billions?|bn|bln", 10**9),
    (r"millions?|mn|mln|mio\.?|millionen|millones|millón|millon|milioni|milione|miljoen|miljoner|millioner|milh(?:ões|oes|ão|ao)", 10**6),
    (r"milliards?|milliarden|mrd\.?|miliardi|miliardo|miljard(?:en)?|miljarder|milliarder", 10**9),
    (r"bilh(?:ões|oes|ão|ao)", 10**9),
    (r"thousands?|tsd\.?|mil", 10**3),
)
_WORD_RE = re.compile(r"\s*(" + "|".join(pattern for pattern, _ in _WORD_MAGNITUDES) + r")(?![a-zà-ÿ])", re.IGNORECASE)
_NUMBER = r"\d+(?:[.,   ]\d+)*"
_NUMBER_RE = re.compile(_NUMBER)
_RANGE_SEPARATOR = re.compile(r"\s*(?:-|–|—|~|～|〜|至|到|to|bis|à|a|al|e)\s*(?:[₹$€£¥₩]|rs\.?|us\$)?\s*", re.IGNORECASE)
# Measurement units whose numbers must also be stated by the Evidence.
_MEASURE_UNIT = re.compile(r"\s*(公里|公尺|英里|公分|公釐|公頃|平方公尺|立方公尺|公噸|噸|%|％|百分點)")


@dataclass(frozen=True, slots=True)
class StatedQuantity:
    text: str
    values: frozenset[float]
    measured: bool = False


def _readings(token: str, strict: bool = False) -> set[float]:
    """Every plausible numeric value of a digit token across separator conventions.

    ``strict`` reads Traditional Chinese report style only: commas group
    thousands and a dot is the decimal mark.
    """

    token = token.replace(" ", " ").replace(" ", " ")
    if strict:
        try:
            return {float(token.replace(",", "").replace(" ", ""))}
        except ValueError:
            return {float(re.split(r"[.,\s]", token)[0])}
    parts = re.split(r"([.,\s])", token)
    digits = parts[0::2]
    separators = parts[1::2]
    if not separators:
        return {float(token)}
    values: set[float] = set()
    whole = "".join(digits)
    # All separators group thousands.
    if all(len(group) == 3 for group in digits[1:]):
        values.add(float(whole))
    # The last separator is a decimal mark; the earlier ones group thousands.
    if separators[-1] in ".," and all(len(group) == 3 for group in digits[1:-1]):
        values.add(float("".join(digits[:-1]) + "." + digits[-1]))
    return values or {float(digits[0])}


def _cjk_value(text: str, start: int, strict: bool) -> tuple[set[float], int] | None:
    """Read a composed CJK amount such as ``1兆9000億``, ``1조 9000억`` or ``5,000億``."""

    position = start
    totals: set[float] = {0.0}
    found = False
    while True:
        resume = position
        while found and resume < len(text) and text[resume] == " ":
            resume += 1
        number = _NUMBER_RE.match(text, resume)
        if not number:
            break
        after = number.end()
        while after < len(text) and text[after] == " ":
            after += 1
        unit = text[after] if after < len(text) else ""
        if unit not in _CJK_MAGNITUDES:
            if not found:
                return None
            readings = _readings(number.group(), strict)
            totals = {total + reading for total in totals for reading in readings}
            position = number.end()
            break
        readings = _readings(number.group(), strict)
        totals = {total + reading * _CJK_MAGNITUDES[unit] for total in totals for reading in readings}
        position = after + 1
        found = True
    return (totals, position) if found else None


def stated_quantities(text: str, *, strict: bool = False) -> tuple[StatedQuantity, ...]:
    """Quantities stated in ``text``: magnitudes, ranges and measured numbers."""

    quantities: list[StatedQuantity] = []
    position = 0
    while True:
        number = _NUMBER_RE.search(text, position)
        if not number:
            break
        start = number.start()
        cjk = _cjk_value(text, start, strict)
        if cjk is not None:
            values, end = cjk
            quantities.append(StatedQuantity(text[start:end], frozenset(values)))
            position = end
            continue
        readings = _readings(number.group(), strict)
        end = number.end()
        word = _WORD_RE.match(text, end)
        if word:
            factor = next(value for pattern, value in _WORD_MAGNITUDES if re.fullmatch(pattern, word.group(1), re.IGNORECASE))
            quantities.append(StatedQuantity(text[start:word.end()], frozenset(r * factor for r in readings)))
            position = word.end()
            continue
        # A range shares the magnitude word of its upper end: "5,000 to 10,000 crore".
        separator = _RANGE_SEPARATOR.match(text, end)
        if separator:
            upper = _NUMBER_RE.match(text, separator.end())
            if upper:
                upper_word = _WORD_RE.match(text, upper.end())
                if upper_word:
                    factor = next(value for pattern, value in _WORD_MAGNITUDES if re.fullmatch(pattern, upper_word.group(1), re.IGNORECASE))
                    quantities.append(StatedQuantity(text[start:end], frozenset(r * factor for r in readings)))
                    quantities.append(StatedQuantity(text[upper.start():upper_word.end()], frozenset(r * factor for r in _readings(upper.group(), strict))))
                    position = upper_word.end()
                    continue
        measured = bool(_MEASURE_UNIT.match(text, end))
        quantities.append(StatedQuantity(text[start:end], frozenset(readings), measured))
        position = end
    return tuple(quantities)


def checked_quantities(text: str) -> tuple[StatedQuantity, ...]:
    """The Writer quantities that must be grounded: large magnitudes and measured numbers."""

    return tuple(
        quantity
        for quantity in stated_quantities(text, strict=True)
        if quantity.measured or max(quantity.values) >= 10_000
    )


def is_grounded(quantity: StatedQuantity, evidence: tuple[StatedQuantity, ...], tolerance: float = 0.05) -> bool:
    """True when some Evidence quantity has the same value, within rounding tolerance."""

    for stated in evidence:
        for written in quantity.values:
            for value in stated.values:
                if value == written or (value and abs(value - written) / abs(value) <= tolerance):
                    return True
    return False


__all__ = ["StatedQuantity", "checked_quantities", "is_grounded", "stated_quantities"]
