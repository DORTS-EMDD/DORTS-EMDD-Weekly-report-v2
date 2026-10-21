"""Versioned geographic reference data for EvidenceService region resolution.

This module only loads and looks up declarative data.  It decides nothing:
EvidenceService remains the sole owner of formal country/region metadata and
uses this reference only on source-supported exact metadata values.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
from pathlib import Path
from typing import Any, Mapping


REFERENCE_PATH = Path(__file__).with_name("geographic_reference.json")


class GeographicMatchKind(StrEnum):
    REGION = "REGION"
    CITY = "CITY"
    SYSTEM = "SYSTEM"
    AMBIGUOUS = "AMBIGUOUS"


@dataclass(frozen=True, slots=True)
class GeographicMatch:
    kind: GeographicMatchKind
    region_id: str | None = None
    display_name: str | None = None


def _key(value: str) -> str:
    """The reference matching key: case folding and whitespace collapsing only."""

    return " ".join(str(value).split()).casefold()


class GeographicReference:
    """Immutable, validated lookup over one reference version."""

    def __init__(self, data: Mapping[str, Any]) -> None:
        version = data.get("reference_version")
        if not isinstance(version, str) or not version.strip():
            raise ValueError("geographic reference requires reference_version")
        self.version = version
        regions = data.get("regions")
        places = data.get("places")
        if not isinstance(regions, list) or not isinstance(places, list):
            raise ValueError("geographic reference requires regions and places")
        display_names: dict[str, str] = {}
        targets: dict[str, set[tuple[GeographicMatchKind, str]]] = {}

        def add(name: object, kind: GeographicMatchKind, region_id: str) -> None:
            if not isinstance(name, str) or not name.strip():
                raise ValueError("geographic reference names must be non-empty strings")
            targets.setdefault(_key(name), set()).add((kind, region_id))

        for region in regions:
            region_id = region.get("region_id")
            display_name = region.get("display_name")
            if not isinstance(region_id, str) or not region_id.strip() or region_id in display_names:
                raise ValueError("geographic reference region IDs must be unique non-empty strings")
            if not isinstance(display_name, str) or not display_name.strip():
                raise ValueError("geographic reference regions require display_name")
            display_names[region_id] = display_name
            for name in region.get("names", ()):
                add(name, GeographicMatchKind.REGION, region_id)
        for place in places:
            region_id = place.get("region_id")
            if region_id not in display_names:
                raise ValueError("geographic reference place refers to an unknown region")
            for name in place.get("cities", ()):
                add(name, GeographicMatchKind.CITY, region_id)
            for name in place.get("systems", ()):
                add(name, GeographicMatchKind.SYSTEM, region_id)
        ambiguous = {_key(name) for name in data.get("ambiguous_names", ())}
        self._display_names = display_names
        self._matches: dict[str, GeographicMatch] = {}
        for key, entries in targets.items():
            region_ids = {region_id for _, region_id in entries}
            if key in ambiguous or len(region_ids) != 1:
                self._matches[key] = GeographicMatch(GeographicMatchKind.AMBIGUOUS)
                continue
            region_id = next(iter(region_ids))
            kinds = {kind for kind, _ in entries}
            kind = next(
                candidate
                for candidate in (
                    GeographicMatchKind.REGION,
                    GeographicMatchKind.CITY,
                    GeographicMatchKind.SYSTEM,
                )
                if candidate in kinds
            )
            self._matches[key] = GeographicMatch(kind, region_id, display_names[region_id])
        for key in ambiguous:
            self._matches.setdefault(key, GeographicMatch(GeographicMatchKind.AMBIGUOUS))
        self._generic_terms = frozenset(_key(term) for term in data.get("generic_transit_terms", ()))

    @classmethod
    def from_file(cls, path: str | Path | None = None) -> "GeographicReference":
        with open(path or REFERENCE_PATH, encoding="utf-8") as handle:
            return cls(json.load(handle))

    def lookup(self, value: str) -> GeographicMatch | None:
        """Return the whole-value match, an ambiguity marker, or None."""

        if not isinstance(value, str) or not value.strip():
            return None
        return self._matches.get(_key(value))

    def is_generic_transit_term(self, value: str) -> bool:
        return isinstance(value, str) and _key(value) in self._generic_terms

    def is_region_or_city_name(self, value: str) -> bool:
        """Whether a value is a region or city name, never a transit-system name."""

        match = self.lookup(value)
        return match is not None and match.kind in {
            GeographicMatchKind.REGION,
            GeographicMatchKind.CITY,
        }


_DEFAULT: GeographicReference | None = None


def default_geographic_reference() -> GeographicReference:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = GeographicReference.from_file()
    return _DEFAULT


__all__ = [
    "GeographicMatch",
    "GeographicMatchKind",
    "GeographicReference",
    "REFERENCE_PATH",
    "default_geographic_reference",
]
