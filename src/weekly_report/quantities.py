"""Mechanical quantity reading for the Validator's numeric grounding check (RC-29).

Reads the quantities a text states (number, magnitude word, measurement unit or
currency) so the Validator can compare Writer prose with the authoritative
Evidence. It decides nothing; ``Validator`` owns the check.

Evidence numbers are read in the source's own notation. ``5,000`` is a
thousand-grouped 5000 in English and a decimal 5 in German, so a token with
one separator followed by three digits is resolved only by notation the text
itself establishes: CJK notation next to it, the decimal mark its unambiguous
numbers use, or a tail ending in 0 (a decimal fraction is not written with
trailing zeros). An unresolved token grounds nothing; it is never read both
ways.
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
# Magnitude words only English uses, always with a dot decimal mark ("91.766 billion").
# "million(s)" is left out: French writes "1,5 million".
_ENGLISH_MAGNITUDE_RE = re.compile(r"lakh\s+crores?|crores?|cr\.?|lakhs?|lacs?|trillions?|tn|billions?|bn|bln|mn|mln", re.IGNORECASE)
# Directly after a currency-signed number, "m", "b" and "k" are magnitudes ("$5m", "€1.2b").
_SIGN_MAGNITUDE_RE = re.compile(r"(m|b|k)(?![A-Za-z])")
_SIGN_MAGNITUDES = {"m": 10**6, "b": 10**9, "k": 10**3}
# A space joins digits only as thousands grouping ("20 000"), never two numbers ("20 2026").
_NUMBER = r"\d+(?:[.,]\d+|[   ]\d{3}(?!\d))*"
_NUMBER_RE = re.compile(_NUMBER)
_RANGE_SEPARATOR = re.compile(r"\s*(?:-|–|—|~|～|〜|至|到)\s*|\s+(?:to|bis|à|a|al|e|y|und|and|et)\s+", re.IGNORECASE)

# Currencies. A sign shared by several currencies reads as all of them; two
# currencies match when their sets intersect, so "$" grounds 美元 or 澳元 but
# 日圓 never grounds 美元.
_DOLLARS = frozenset({"USD", "AUD", "CAD", "NZD", "SGD", "HKD", "TWD"})
# 元 alone names no currency: every yuan- or dollar-named one (美元, 澳元, 新臺幣元 ...).
_YUAN = _DOLLARS | {"CNY"}
_RUPEES = frozenset({"INR", "PKR", "LKR", "NPR"})
_KRONOR = frozenset({"SEK", "NOK", "DKK"})
_ISO_CODES = ("USD", "EUR", "GBP", "JPY", "KRW", "CNY", "TWD", "HKD", "SGD", "AUD", "CAD", "NZD", "INR", "CHF", "SEK", "NOK", "DKK", "THB", "VND")
_PREFIX_CURRENCIES = (
    (r"U\.?S\.?\$|美金", {"USD"}),
    (r"A\$|AU\$", {"AUD"}),
    (r"C\$|CA\$", {"CAD"}),
    (r"NZ\$", {"NZD"}),
    (r"S\$|SG\$", {"SGD"}),
    (r"HK\$|港幣", {"HKD"}),
    (r"NT\$|NTD|新臺幣|新台幣|臺幣|台幣", {"TWD"}),
    (r"RMB|人民幣", {"CNY"}),
    (r"R\$", {"BRL"}),
    (r"\$", _DOLLARS),
    (r"€", {"EUR"}),
    (r"£", {"GBP"}),
    (r"¥|￥", {"JPY", "CNY"}),
    (r"₩", {"KRW"}),
    (r"₹", {"INR"}),
    (r"Rs\.?", _RUPEES),
    *((code, {code}) for code in _ISO_CODES),
)
_SUFFIX_CURRENCIES = (
    (r"US\s?dollars?|U\.S\.\s?dollars?|美元|美金|米ドル|USD", {"USD"}),
    (r"Australian\s+dollars?|澳元|澳幣|豪ドル|AUD", {"AUD"}),
    (r"Canadian\s+dollars?|加元|加幣|カナダドル|CAD", {"CAD"}),
    (r"Singapore\s+dollars?|新加坡元|新加坡幣|星元|シンガポールドル|SGD", {"SGD"}),
    (r"Hong\s+Kong\s+dollars?|港元|港幣|香港ドル|HKD", {"HKD"}),
    (r"(?:New\s+)?Taiwan\s+dollars?|新臺幣|新台幣|臺幣|台幣|台湾ドル|TWD|NTD", {"TWD"}),
    (r"NZ\s+dollars?|紐元|NZD", {"NZD"}),
    (r"dollars?|dólares|dollari|ドル|달러", _DOLLARS),
    (r"euros?|歐元|欧元|ユーロ|유로|EUR", {"EUR"}),
    (r"pounds?(?:\s+sterling)?|sterling|英鎊|ポンド|파운드|GBP", {"GBP"}),
    (r"yen|日圓|日元|日幣|円|엔|JPY", {"JPY"}),
    (r"yuan|renminbi|人民幣|人民元|위안|CNY|RMB", {"CNY"}),
    (r"won|韓元|韓圜|ウォン|원|KRW", {"KRW"}),
    (r"Indian\s+rupees?|印度盧比|インドルピー|INR", {"INR"}),
    (r"rupees?|盧比|ルピー|루피", _RUPEES),
    (r"Swiss\s+francs?|francs?|Franken|瑞士法郎|法郎|スイスフラン|CHF", {"CHF"}),
    (r"Swedish\s+kronor|kronor|瑞典克朗|SEK", {"SEK"}),
    (r"Norwegian\s+kroner|挪威克朗|NOK", {"NOK"}),
    (r"Danish\s+kroner|丹麥克朗|DKK", {"DKK"}),
    (r"kroner|kronen|克朗|크로나", _KRONOR),
    (r"baht|泰銖|バーツ|THB", {"THB"}),
    (r"越南盾|VND", {"VND"}),
    (r"元", _YUAN),
)
# Measurement units: (pattern, dimension, factor to the dimension's base unit).
# Metric units of one dimension convert exactly; miles stay their own unit,
# because a mile-to-kilometre figure is an approximation the source never states.
_MEASURES = (
    (r"平方公里|平方キロ(?:メートル)?|제곱킬로미터|㎢|km²|km2|sq\.?\s?km|square\s+kilomet(?:re|er)s?|Quadratkilometer[n]?", "area", 1e6),
    (r"平方公尺|平方米|平方メートル|제곱미터|㎡|m²|m2|sq\.?\s?m|square\s+met(?:re|er)s?|Quadratmeter[n]?|metros?\s+cuadrados|mètres?\s+carrés|metri\s+quadrati", "area", 1.0),
    (r"公頃|ヘクタール|헥타르|hectares?|Hektar|ettari|hectáreas|ha", "area", 1e4),
    (r"立方公尺|立方米|立方メートル|세제곱미터|㎥|m³|m3|cubic\s+met(?:re|er)s?|Kubikmeter[n]?", "volume", 1.0),
    (r"公里|千米|キロメートル|キロ|킬로미터|㎞|km|kilomet(?:re|er)s?|kilomètres?|Kilometer[n]?|chilometri|kil[oó]metros|quil[oó]metros", "length", 1000.0),
    (r"英里|マイル|마일|miles?|Meilen|millas|miglia|mi", "mile", 1.0),
    (r"公分|センチ(?:メートル)?|센티미터|cm|centimet(?:re|er)s?|Zentimeter[n]?", "length", 0.01),
    (r"公釐|毫米|ミリ(?:メートル)?|밀리미터|mm|millimet(?:re|er)s?|Millimeter[n]?", "length", 0.001),
    (r"公尺|メートル|미터|met(?:re|er)s?|mètres?|Meter[n]?|metri|metros|m|米(?!ドル|国|國)", "length", 1.0),
    (r"公噸|噸|吨|トン|톤|tonnes?|tons?|Tonnen|toneladas|tonnellate|t", "mass", 1.0),
    (r"%p|％p|퍼센트\s?포인트|パーセントポイント|(?:個)?百分點|percentage\s+points?|Prozentpunkte[n]?|puntos\s+porcentuales|points?\s+de\s+pourcentage", "percentage_point", 1.0),
    (r"%|％|percent|per\s?cent|pct|pc|Prozent|por\s+ciento|per\s+cento|pour\s+cent|procent|prosent|パーセント|퍼센트", "percent", 1.0),
)
_LATIN_END = r"(?![A-Za-zÀ-ÿ])"


def _alternation(table) -> str:
    return "|".join(f"({pattern})" for pattern, *_ in table)


_PREFIX_RE = re.compile(r"(?<![A-Za-z])(?:" + _alternation(_PREFIX_CURRENCIES) + r")\s?$")
_SUFFIX_RE = re.compile(r"(?:\s*(?:de|d['’]|di|of))?\s*(?:" + _alternation(_SUFFIX_CURRENCIES) + ")" + _LATIN_END, re.IGNORECASE)
# Between the bounds of a range; the upper bound may repeat the currency sign
# ("₹5,000 crore to ₹10,000 crore").
_RANGE_GAP = re.compile(
    "(?:" + _RANGE_SEPARATOR.pattern + ")(?:" + "|".join(pattern for pattern, _ in _PREFIX_CURRENCIES) + r")?\s?",
    re.IGNORECASE,
)
_MEASURE_RE = re.compile(r"(?:\s*|-)(?:" + _alternation(_MEASURES) + ")" + _LATIN_END, re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class StatedQuantity:
    text: str
    values: frozenset[float]
    # Dimension ("length", "percent", ...) or the possible currency codes;
    # empty when the text states no unit with the number.
    unit: frozenset[str] = frozenset()
    # The value of the last digit as written, in the unit's base: a written
    # number stands for every value that rounds to it.
    place: float = 0.0


@dataclass(slots=True)
class _Reading:
    start: int
    end: int
    values: set[float]
    place: float
    magnitude: float | None = None
    currency: frozenset[str] = frozenset()
    measure: str | None = None
    measure_factor: float = 1.0


# Notation of a token: _STRICT is Traditional Chinese report style (Writer
# prose); "." or "," is the decimal mark the source establishes; None is unknown.
_STRICT = "strict"
_CJK_CHARACTER = re.compile(r"[\u3040-\u30ff\u3300-\u33ff\u3400-\u9fff\uac00-\ud7af]")


def _grouped(groups: list[str], mark: str) -> bool:
    """Valid thousands grouping, or Indian lakh grouping (1,25,000) with commas."""

    if groups and 1 <= len(groups[0]) <= 3 and all(len(group) == 3 for group in groups[1:]):
        return True
    return mark == "," and len(groups) > 2 and 1 <= len(groups[0]) <= 2 and len(groups[-1]) == 3 and all(
        len(group) == 2 for group in groups[1:-1]
    )


def _decimal_mark_of(token: str) -> str | None:
    """The decimal mark a token establishes by itself, if any."""

    marks = re.findall(r"[.,]", token)
    if len(set(marks)) == 2:
        return marks[-1]
    if len(marks) >= 2:
        # A repeated mark groups thousands, so the other one is the decimal mark.
        return {".": ",", ",": "."}[marks[0]] if _grouped(re.split(r"[.,\s]", token), marks[0]) else None
    if len(marks) == 1:
        before, after = re.sub(r"\s", "", token).split(marks[0])
        if len(after) != 3 or before == "0" or len(before) > 3:
            return marks[0]
    return None


def _readings(token: str, notation: str | None = _STRICT) -> set[float]:
    """The numeric value of a digit token in the given notation (empty when unresolved)."""

    token = token.replace("\u00a0", " ").replace("\u202f", " ")
    if notation == _STRICT:
        try:
            return {float(token.replace(",", "").replace(" ", ""))}
        except ValueError:
            return {float(re.split(r"[.,\s]", token)[0])}
    marks = re.findall(r"[.,]", token)
    if not marks:
        groups = token.split()
        return {float("".join(groups))} if len(groups) == 1 or _grouped(groups, " ") else set()
    decimal = _decimal_mark_of(token)
    if decimal is None and len(marks) == 1:
        # One separator before three digits: only the source's notation decides.
        if notation in {".", ","}:
            decimal = notation
        elif token.endswith("0"):
            decimal = "," if marks[0] == "." else "."
        else:
            return set()
    if decimal is None:
        return set()
    whole, _, fraction = token.rpartition(decimal) if decimal in marks else (token, "", "")
    groups = re.split(r"[.,\s]", whole)
    if len(groups) > 1 and not _grouped(groups, "." if decimal == "," else ","):
        return set()
    return {float("".join(groups) + ("." + fraction if fraction else ""))}


def _cjk_adjacent(text: str, start: int, end: int) -> bool:
    """CJK notation (comma groups, dot is decimal) holds for a number written next to CJK text."""

    return bool(
        (start and _CJK_CHARACTER.match(text, start - 1))
        or _CJK_CHARACTER.match(text, end)
        or (end < len(text) and text[end] == " " and _CJK_CHARACTER.match(text, end + 1))
    )


def _document_decimal_mark(text: str) -> str | None:
    """The one decimal mark the text's unambiguous numbers use; None if none or conflicting."""

    marks = set()
    for number in _NUMBER_RE.finditer(text):
        if not _cjk_adjacent(text, number.start(), number.end()):
            mark = _decimal_mark_of(number.group().replace("\u00a0", " ").replace("\u202f", " "))
            if mark is not None:
                marks.add(mark)
    return marks.pop() if len(marks) == 1 else None


def _place(token: str) -> float:
    """The value of the last written digit under the report-style reading."""

    decimals = token.rsplit(".", 1)[1] if "." in token else ""
    return 10.0 ** -len(decimals) if decimals.isdigit() else 1.0


def _cjk_value(text: str, start: int, notation: str | None) -> tuple[set[float], int, float, float] | None:
    """Read a composed CJK amount such as ``1兆9000億``, ``1조 9000억`` or ``5,000億``.

    Returns the values, the end, the place of the last digit and the magnitude
    of the leading part (which a range's lower bound shares).
    """

    position = start
    totals: set[float] = {0.0}
    place = 1.0
    leading: float | None = None
    while True:
        resume = position
        while leading is not None and resume < len(text) and text[resume] == " ":
            resume += 1
        number = _NUMBER_RE.match(text, resume)
        if not number:
            break
        after = number.end()
        while after < len(text) and text[after] == " ":
            after += 1
        unit = text[after] if after < len(text) else ""
        # A number written with a CJK magnitude is in CJK notation.
        readings = _readings(number.group(), notation if notation == _STRICT else ".")
        if unit not in _CJK_MAGNITUDES:
            if leading is None:
                return None
            totals = {total + reading for total in totals for reading in readings}
            place = _place(number.group())
            position = number.end()
            break
        totals = {total + reading * _CJK_MAGNITUDES[unit] for total in totals for reading in readings}
        place = _place(number.group()) * _CJK_MAGNITUDES[unit]
        leading = leading or _CJK_MAGNITUDES[unit]
        position = after + 1
    return (totals, position, place, leading) if leading is not None else None


def _matched(table, match: re.Match[str]):
    return table[match.lastindex - 1] if match.lastindex else None


def _read(text: str, number: re.Match[str], notation: str | None) -> _Reading:
    start = number.start()
    prefix = _PREFIX_RE.search(text, max(0, start - 12), start)
    currency = frozenset(_matched(_PREFIX_CURRENCIES, prefix)[1]) if prefix else frozenset()
    cjk = _cjk_value(text, start, notation)
    if cjk is not None:
        values, end, place, magnitude = cjk
        reading = _Reading(start, end, values, place, magnitude, currency)
    else:
        word = _WORD_RE.match(text, number.end())
        if notation != _STRICT and _cjk_adjacent(text, start, number.end()):
            notation = "."
        elif notation is None and word and _ENGLISH_MAGNITUDE_RE.fullmatch(word.group(1)):
            notation = "."
        reading = _Reading(start, number.end(), _readings(number.group(), notation), _place(number.group()), None, currency)
        sign = _SIGN_MAGNITUDE_RE.match(text, reading.end) if currency else None
        if word:
            factor = next(value for pattern, value in _WORD_MAGNITUDES if re.fullmatch(pattern, word.group(1), re.IGNORECASE))
            reading.end = word.end()
        elif sign:
            factor = _SIGN_MAGNITUDES[sign.group(1).casefold()]
            reading.end = sign.end()
        else:
            factor = None
        if factor:
            reading.values = {value * factor for value in reading.values}
            reading.place *= factor
            reading.magnitude = factor
    measure = _MEASURE_RE.match(text, reading.end)
    suffix = None if measure else _SUFFIX_RE.match(text, reading.end)
    if measure:
        _, dimension, factor = _matched(_MEASURES, measure)
        reading.values = {value * factor for value in reading.values}
        reading.place *= factor
        reading.measure = dimension
        reading.measure_factor = factor
        reading.end = measure.end()
    elif suffix:
        codes = frozenset(_matched(_SUFFIX_CURRENCIES, suffix)[1])
        # "NT$5億元": the more specific of the two names the currency.
        reading.currency = (reading.currency & codes) or reading.currency or codes
        reading.end = suffix.end()
    return reading


def _share_upper_bound(lower: _Reading, upper: _Reading) -> None:
    """A range states its magnitude and unit once: "5,000～10,000億円", "5-10%"."""

    if lower.magnitude is None and lower.measure is None and upper.magnitude:
        lower.values = {value * upper.magnitude for value in lower.values}
        lower.place *= upper.magnitude
        lower.magnitude = upper.magnitude
    if lower.measure is None and not lower.currency:
        if upper.measure is not None:
            lower.values = {value * upper.measure_factor for value in lower.values}
            lower.place *= upper.measure_factor
            lower.measure = upper.measure
            lower.measure_factor = upper.measure_factor
        else:
            lower.currency = upper.currency


def stated_quantities(text: str, *, strict: bool = False) -> tuple[StatedQuantity, ...]:
    """Quantities stated in ``text``: magnitudes, ranges, measures and amounts."""

    notation = _STRICT if strict else _document_decimal_mark(text)
    readings: list[_Reading] = []
    position = 0
    while True:
        number = _NUMBER_RE.search(text, position)
        if not number:
            break
        readings.append(_read(text, number, notation))
        position = readings[-1].end
    for lower, upper in zip(readings, readings[1:]):
        if _RANGE_GAP.fullmatch(text, lower.end, upper.start):
            _share_upper_bound(lower, upper)
    return tuple(
        StatedQuantity(
            text[reading.start:reading.end],
            frozenset(reading.values),
            frozenset({reading.measure}) if reading.measure else reading.currency,
            reading.place,
        )
        for reading in readings
    )


def checked_quantities(text: str) -> tuple[StatedQuantity, ...]:
    """The Writer quantities that must be grounded: amounts, measures and large magnitudes."""

    return tuple(
        quantity
        for quantity in stated_quantities(text, strict=True)
        if quantity.unit or max(quantity.values, default=0) >= 10_000
    )


def is_grounded(quantity: StatedQuantity, evidence: tuple[StatedQuantity, ...]) -> bool:
    """True when an Evidence quantity in a compatible unit rounds to the written value.

    A written unit needs the same unit in the Evidence, and a written currency
    one the Evidence names at least as specifically (``5億元`` does not ground
    ``新臺幣5億元``, ``$`` does not ground 美元); a written number stands for
    the values that round to it at its last written digit.
    """

    tolerance = quantity.place / 2
    for stated in evidence:
        if quantity.unit and not (stated.unit and stated.unit <= quantity.unit):
            continue
        for written in quantity.values:
            for value in stated.values:
                if abs(value - written) <= tolerance + 1e-9 * max(abs(value), 1.0):
                    return True
    return False


__all__ = ["StatedQuantity", "checked_quantities", "is_grounded", "stated_quantities"]
