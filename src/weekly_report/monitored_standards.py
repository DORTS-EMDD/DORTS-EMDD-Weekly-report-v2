"""The monitored standards list (RC-58) and a mechanical identifier matcher.

``monitored_standards.json`` is the only source of truth for which standards
the standards-update monitoring covers. It is the V1 list, approved by the user
as the product scope. This module loads it and locates identifier mentions in
text. It decides nothing: SearchPlanner uses the identifiers as discovery
terms (through the materialized Search configuration), and Reportability
alone decides whether an event is a formal change of a monitored standard.

Matching is mechanical. An entry matches when the text contains its body
prefix and number as one token; an optional "Std" (IEEE usage) and optional
whitespace or hyphen between the prefix and the number are allowed. A part,
edition or year may follow ("EN 50126-1:2017", "IEC 60076-11"). A longer
number, letter or decimal does not match ("EN 501260", "NFPA 70E",
"IEEE 1474.10"). A series entry ("EN 50122") also matches its parts. Text is
NFKC-normalized first, so full-width digits match.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import unicodedata
from typing import Any, Mapping


REFERENCE_PATH = Path(__file__).with_name("monitored_standards.json")
_IDENTIFIER = re.compile(r"^([A-Z]{2,5}) ([A-Z]?)(\d+(?:\.\d+)?(?:-\d+)*)$")


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
        self._patterns = tuple((identifier, _pattern(identifier)) for identifier in identifiers)

    def identifiers_in(self, text: str) -> tuple[str, ...]:
        """Monitored identifiers mentioned in ``text``, in list order."""

        if not isinstance(text, str):
            raise TypeError("text must be a string")
        normalized = unicodedata.normalize("NFKC", text)
        return tuple(identifier for identifier, pattern in self._patterns if pattern.search(normalized))

    def source_literal_sha256(self, data: Mapping[str, Any]) -> str:
        """Digest of the V1 literal shape ``{group label: [identifiers]}``."""

        literal = {group["label"]: list(group["standards"]) for group in data["groups"]}
        return hashlib.sha256(json.dumps(literal, ensure_ascii=False).encode("utf-8")).hexdigest()


def _pattern(identifier: str) -> re.Pattern[str]:
    prefix, letter, number = _IDENTIFIER.fullmatch(identifier).groups()
    number_pattern = re.escape(letter) + r"\s?" + re.escape(number) if letter else re.escape(number)
    return re.compile(
        r"(?<![A-Za-z0-9])" + re.escape(prefix) + r"(?:\s*Std\.?)?[\s-]*" + number_pattern
        + r"(?![0-9A-Za-z])(?!\.[0-9])"
    )


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
    "MonitoredStandard",
    "MonitoredStandards",
    "REFERENCE_PATH",
    "load_monitored_standards_data",
    "monitored_standards",
]
