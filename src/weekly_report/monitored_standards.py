"""The monitored standards list (RC-58) and a mechanical identifier locator.

``monitored_standards.json`` is the only source of truth for which standards
the standards-update monitoring covers. It is the V1 list, approved by the user
as the product scope. This module loads it and locates identifier mentions in
text, and ``monitored_check_month`` is the only owner of the monthly cadence
(RC-59). Neither decides an event: SearchPlanner uses the identifiers as
discovery terms in the monthly check, and ScopeClassifier alone decides whether
a Candidate is a proven formal lifecycle change of a monitored standard.

Locating is mechanical. The text is NFKC-normalized first, so full-width
digits match. A publication token is a body prefix followed by its number.
Between them an optional "Std" (IEEE usage) and optional whitespace or a
hyphen are allowed.

Locator grammar (how a token's full publication number is read; it decides no
coverage):
* For the IEC, EN and UIC prefixes, every following "-<digits>" segment
  belongs to the number ("IEC 60076-11", "EN 50126-1", "UIC 860-0").
* For every other prefix, a following hyphen starts an edition or year
  ("ASTM E119-24", "IEEE 1474.1-2025").
* An edition, year, amendment or corrigendum after the full number does not
  change it ("EN 50122-2:2010/A1").
* A longer number, a letter or a decimal is another publication
  ("EN 501260", "NFPA 70E", "IEEE 1474.10").

Basis: the official catalogue records in the RC-60 fixtures write the year
after a colon for IEC ("IEC 61373:2010/COR1:2011") and after a hyphen for IEEE
("IEEE 1474.1-2025"). For EN, UIC, ASTM and NFPA the grammar is assumed, not
evidenced in this repository.

Hyphen year (user decision, contract section A.46): a final "-YYYY" (four
digits) may be the edition year. The full number is tried first, so an
explicitly configured publication keeps its own number. Only when the full
number has no owner is the final "-YYYY" read as a year ("IEC 61373-2010" is
IEC 61373, "IEC 60076-11-2018" is IEC 60076-11). Removing it never creates
coverage: a part before it still needs its own owner. For prefixes without
hyphenated parts the hyphen already starts an edition or year, so the rule
only affects IEC, EN and UIC.

Series packs (contract section A.46): a designation followed by IEC's
designator "SER" names a Series, which IEC defines as a package containing all
the official publications and value-added products of a standard (all of its
parts). It owns nothing, so it is never a monitored lifecycle change ("IEC
60076:2026 SER"). A part the text names itself is still located as usual.
Designators of one publication (CSV, CMV, RLV) keep its owner. No other
designator is treated as a package.

Configuration consistency (fail closed): every listed identifier and every
configured family part must read back as itself through this grammar.

RC-62 (contract section A.46, user Domain Rule): ownership is exact.
* A listed identifier owns the publication with exactly its own number.
* A parent owns a further numbered part only when the configuration's
  ``family_coverage`` lists that part for it.
* An explicitly listed child (for example IEC 60076-11 or EN 50122-2) always
  owns itself, and no parent may list it.
* Numbering alone never makes a part monitored.

``identifiers_in`` returns the owners of the publications that a text names.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import unicodedata
from typing import Any, Mapping

from .contracts import MonitoredCheckMonth


REFERENCE_PATH = Path(__file__).with_name("monitored_standards.json")
_IDENTIFIER = re.compile(r"^([A-Z]{2,5}) ([A-Z]?)(\d+(?:\.\d+)?(?:-\d+)*)$")
# Locator grammar only (see the module docstring): prefixes whose hyphenated
# digit segments belong to the publication number. It decides no coverage.
_HYPHEN_PART_BODIES = frozenset({"IEC", "EN", "UIC"})
# User decision (section A.46): a final -YYYY may be the edition year.
_HYPHEN_YEAR = re.compile(r"-\d{4}$")
# Section A.46: an IEC Series pack ("IEC 60076:2026 SER") is a package of other
# publications, not a publication of the identifier.
_SERIES_DESIGNATOR = re.compile(r"\s*(?::\d{4})?\s*SER(?![A-Za-z0-9])")


@dataclass(frozen=True, slots=True)
class MonitoredStandard:
    identifier: str
    group: str


class MonitoredStandards:
    """Immutable, validated list of one reference version."""

    def __init__(self, data: Mapping[str, Any]) -> None:
        version = data.get("reference_version")
        if not isinstance(version, str) or not version.strip():
            raise ValueError("monitored standards require reference_version")
        groups = data.get("groups")
        if not isinstance(groups, list) or not groups:
            raise ValueError("monitored standards require groups")
        standards: list[MonitoredStandard] = []
        for group in groups:
            label = group.get("label") if isinstance(group, Mapping) else None
            members = group.get("standards") if isinstance(group, Mapping) else None
            if not isinstance(label, str) or not label.strip() or not isinstance(members, list) or not members:
                raise ValueError("each monitored standards group needs a label and standards")
            for identifier in members:
                if not isinstance(identifier, str) or _IDENTIFIER.fullmatch(identifier) is None:
                    raise ValueError(f"monitored standard identifier is malformed: {identifier!r}")
                standards.append(MonitoredStandard(identifier, label))
        identifiers = [standard.identifier for standard in standards]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("monitored standard identifiers must be unique")
        self.version = version
        self.standards = tuple(standards)
        self.identifiers = tuple(identifiers)
        self.family_coverage = _family_coverage(data.get("family_coverage"), self.identifiers)
        owners = {_publication_key(identifier): identifier for identifier in identifiers}
        for parent, members in self.family_coverage.items():
            for member in members:
                owners[_publication_key(member)] = parent
        self._owners = owners
        self._order = {identifier: index for index, identifier in enumerate(identifiers)}
        self._token_patterns = tuple(
            (prefix, _token_pattern(prefix)) for prefix in dict.fromkeys(key[0] for key in owners)
        )
        for owned, owner in ((identifier, identifier) for identifier in identifiers):
            self._require_read_back(owned, owner)
        for parent, members in self.family_coverage.items():
            for member in members:
                self._require_read_back(member, parent)
        self.catalogue_records = _catalogue_records(data.get("catalogue_records"), self.identifiers)

    def identifiers_in(self, text: str) -> tuple[str, ...]:
        """Owners of the publications ``text`` names, in list order (RC-62: exact ownership)."""

        if not isinstance(text, str):
            raise TypeError("text must be a string")
        normalized = unicodedata.normalize("NFKC", text)
        found: set[str] = set()
        for prefix, pattern in self._token_patterns:
            for match in pattern.finditer(normalized):
                if _SERIES_DESIGNATOR.match(normalized, match.end()):
                    continue
                letter, number = match.group("letter") or "", match.group("number")
                owner = self._owners.get((prefix, letter, number))
                if owner is None and _HYPHEN_YEAR.search(number):
                    owner = self._owners.get((prefix, letter, _HYPHEN_YEAR.sub("", number)))
                if owner is not None:
                    found.add(owner)
        return tuple(sorted(found, key=self._order.__getitem__))

    def _require_read_back(self, publication: str, owner: str) -> None:
        """A configured publication must be locatable as itself, or the configuration fails closed."""

        prefix, letter, number = _publication_key(publication)
        pattern = dict(self._token_patterns)[prefix]
        match = pattern.fullmatch(unicodedata.normalize("NFKC", publication))
        if match is None or (match.group("letter") or "", match.group("number")) != (letter, number):
            raise ValueError(f"{publication!r} cannot be located as itself, so {owner!r} could never own it")

    def source_literal_sha256(self, data: Mapping[str, Any]) -> str:
        """Digest of the V1 literal shape ``{group label: [identifiers]}``."""

        literal = {group["label"]: list(group["standards"]) for group in data["groups"]}
        return hashlib.sha256(json.dumps(literal, ensure_ascii=False).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class CatalogueRecordRef:
    """RC-60: where the monthly check reads one monitored standard's official record."""

    identifier: str
    source: str
    locator: str


def _catalogue_records(value: Any, identifiers: tuple[str, ...]) -> tuple[CatalogueRecordRef, ...]:
    """Validate the record table: each listed standard is configured or explained, once."""

    if value is None:
        return ()
    from .standards_catalogue import CatalogueSource, request_url

    if not isinstance(value, Mapping) or not isinstance(value.get("records"), list):
        raise ValueError("catalogue_records requires a records list")
    explained = value.get("not_configured", {})
    if not isinstance(explained, Mapping) or any(not isinstance(text, str) or not text.strip() for text in explained.values()):
        raise ValueError("catalogue_records.not_configured must give a reason per standard")
    records: list[CatalogueRecordRef] = []
    for item in value["records"]:
        if not isinstance(item, Mapping) or set(item) != {"identifier", "source", "locator"}:
            raise ValueError("each catalogue record has exactly identifier, source and locator")
        source = CatalogueSource(item["source"]).value
        request_url(source, item["locator"])  # validates the locator format
        records.append(CatalogueRecordRef(item["identifier"], source, item["locator"]))
    configured = [record.identifier for record in records]
    covered = configured + list(explained)
    if len(covered) != len(set(covered)) or set(covered) != set(identifiers):
        raise ValueError("every monitored standard must be configured or explained exactly once, and nothing else")
    order = {identifier: index for index, identifier in enumerate(identifiers)}
    return tuple(sorted(records, key=lambda record: order[record.identifier]))


def _publication_key(identifier: str) -> tuple[str, str, str]:
    prefix, letter, number = _IDENTIFIER.fullmatch(identifier).groups()
    return prefix, letter, number


def _token_pattern(prefix: str) -> re.Pattern[str]:
    """One body's publication tokens; the captured number is the full publication number."""

    parts = r"(?:-\d+)*" if prefix in _HYPHEN_PART_BODIES else ""
    return re.compile(
        r"(?<![A-Za-z0-9])" + re.escape(prefix) + r"(?:\s*Std\.?)?[\s-]*"
        + r"(?:(?P<letter>[A-Z])\s?)?(?P<number>\d+(?:\.\d+)?" + parts + r")"
        + r"(?![0-9A-Za-z])(?!\.[0-9])"
    )


def _family_coverage(value: Any, identifiers: tuple[str, ...]) -> dict[str, tuple[str, ...]]:
    """RC-62: the parts each listed parent owns, defined only by the configuration."""

    if value is None:
        return {}
    if not isinstance(value, Mapping) or not isinstance(value.get("families"), Mapping):
        raise ValueError("family_coverage requires a families mapping")
    listed = set(identifiers)
    owned: set[str] = set()
    families: dict[str, tuple[str, ...]] = {}
    for parent, members in value["families"].items():
        if parent not in listed:
            raise ValueError(f"family_coverage parent {parent!r} is not a monitored identifier")
        if not isinstance(members, list):
            raise ValueError(f"family_coverage for {parent!r} must be a list of parts")
        for member in members:
            if not isinstance(member, str) or _IDENTIFIER.fullmatch(member) is None:
                raise ValueError(f"family part is malformed: {member!r}")
            if member in listed:
                raise ValueError(f"{member!r} is listed itself; an explicit child owns itself")
            if member in owned:
                raise ValueError(f"{member!r} is owned by more than one family")
            owned.add(member)
        families[parent] = tuple(members)
    return families


def monitored_check_month(period_start: date, period_end: date) -> MonitoredCheckMonth | None:
    """RC-59: the calendar month whose monthly check belongs to this report period.

    The monitored standards are checked once per calendar month, in the weekly
    report whose period contains that month's last day; the check covers the
    whole month. A week can contain at most one month end, and every month end
    lies in exactly one Monday-to-Sunday week, so each month is checked by
    exactly one report period. The answer depends only on the period: a
    delayed or repeated run for the same period gives the same answer.
    """

    if type(period_start) is not date or type(period_end) is not date or period_end < period_start:
        raise ValueError("monitored_check_month requires a valid report period")
    day = period_start
    while day <= period_end:
        following = day + timedelta(days=1)
        if following.month != day.month:
            return MonitoredCheckMonth(day.replace(day=1), day)
        day = following
    return None


def load_monitored_standards_data(path: str | Path = REFERENCE_PATH) -> Mapping[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, Mapping):
        raise ValueError("monitored standards must be a JSON object")
    return value


@lru_cache(maxsize=1)
def monitored_standards() -> MonitoredStandards:
    return MonitoredStandards(load_monitored_standards_data())


__all__ = [
    "CatalogueRecordRef",
    "MonitoredStandard",
    "MonitoredStandards",
    "REFERENCE_PATH",
    "load_monitored_standards_data",
    "monitored_check_month",
    "monitored_standards",
]
