"""Official standards catalogue records (RC-60): URLs and mechanical parsers.

The monthly monitored-standards check reads, for each monitored standard with a
configured catalogue record, that standard's record in its issuing body's
public catalogue. This module only builds the record URL and reads the record's
own structured fields. It decides nothing:

* the Search provider (``standards_catalogue_provider``) turns entries dated
  in the check month into discovery results;
* EvidenceService turns a fetched record into Authoritative Evidence;
* ScopeClassifier, TemporalRule and Reportability decide as for any Candidate.

Supported sources and what each record states:

* ``iec_webstore``: every webstore publication page embeds the whole family's
  lifecycle (each edition, amendment and corrigendum with its reference,
  edition, publication date and status).
* ``ieee_sa``: an edition page states its status, publication date and, once
  superseded, the superseding edition.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
import html as html_lib
import json
import re
from urllib.parse import urlsplit

from lxml import html as lxml_html


class CatalogueSource(StrEnum):
    IEC_WEBSTORE = "iec_webstore"
    IEEE_SA = "ieee_sa"


_LOCATOR = {
    CatalogueSource.IEC_WEBSTORE: re.compile(r"^\d{1,7}$"),
    CatalogueSource.IEEE_SA: re.compile(r"^\d+(?:\.\d+)*/\d{1,7}$"),
}
_RECORD_URL = {
    CatalogueSource.IEC_WEBSTORE: re.compile(r"^https://webstore\.iec\.ch/(?:en/)?publication/(\d{1,7})/?$"),
    CatalogueSource.IEEE_SA: re.compile(r"^https://standards\.ieee\.org/ieee/\d+(?:\.\d+)*/\d{1,7}/?$"),
}
# The hosts a record request may pass through.
RECORD_HOSTS = {
    CatalogueSource.IEC_WEBSTORE: frozenset({"webstore.iec.ch"}),
    CatalogueSource.IEEE_SA: frozenset({"standards.ieee.org"}),
}


class CatalogueRecordError(ValueError):
    """The page is not a readable record of its declared source."""


@dataclass(frozen=True, slots=True)
class CatalogueEntry:
    """One lifecycle entry of a standard family, as the catalogue states it."""

    reference: str
    url: str
    publication_date: date | None
    edition: str
    status: str


@dataclass(frozen=True, slots=True)
class CatalogueRecord:
    """The structured fields of one record page, used as Evidence text."""

    source: CatalogueSource
    url: str
    reference: str
    title: str
    publication_date: date
    edition: str
    status: str
    description: str
    family: tuple[CatalogueEntry, ...]
    # The page's own label for ``publication_date`` (IEC "Publication date",
    # IEEE "Published"), so the text says what the page says.
    date_label: str = "Publication date"
    other_facts: tuple[str, ...] = ()

    def as_evidence_text(self) -> str:
        """The record's own fields, one statement per line, in page order."""

        lines = [f"{self.reference}: {self.title}." if self.title else f"{self.reference}."]
        facts = [f"{self.date_label}: {self.publication_date.isoformat()}."]
        if self.edition:
            facts.append(f"Edition: {self.edition}.")
        if self.status:
            facts.append(f"Status: {self.status}.")
        facts.extend(self.other_facts)
        lines.append(" ".join(facts))
        if self.description:
            lines.append(self.description)
        others = [entry for entry in self.family if entry.reference != self.reference]
        for entry in others:
            when = f"published {entry.publication_date.isoformat()}, " if entry.publication_date else ""
            edition = f"edition {entry.edition}, " if entry.edition else ""
            lines.append(f"Lifecycle entry: {entry.reference} ({when}{edition}status {entry.status}).")
        return "\n".join(lines)


def request_url(source: CatalogueSource | str, locator: str) -> str:
    source = CatalogueSource(source)
    if not isinstance(locator, str) or _LOCATOR[source].fullmatch(locator) is None:
        raise ValueError(f"invalid {source.value} locator: {locator!r}")
    if source is CatalogueSource.IEC_WEBSTORE:
        return f"https://webstore.iec.ch/en/publication/{locator}"
    return f"https://standards.ieee.org/ieee/{locator}/"


def record_source(url: str) -> CatalogueSource | None:
    """The catalogue source whose record page ``url`` is, or None."""

    if not isinstance(url, str):
        return None
    for source, pattern in _RECORD_URL.items():
        if pattern.fullmatch(url.strip()):
            return source
    return None


def _text(node) -> str:
    return re.sub(r"\s+", " ", node.text_content()).strip() if node is not None else ""


def _first(tree, xpath: str):
    found = tree.xpath(xpath)
    return found[0] if found else None


def _document(page: str):
    if not isinstance(page, str) or not page.strip():
        raise CatalogueRecordError("empty record page")
    return lxml_html.fromstring(page)


# --- IEC webstore ------------------------------------------------------------------------

_IEC_LIFECYCLES = re.compile(r"lifecycles:\s*(\{.*?\}),\s*\n\s*statusMapping", re.S)
_IEC_STATUS = {"PUBLISHED": "Published", "REVISED": "Revised", "REPLACED": "Replaced", "WITHDRAWN": "Withdrawn"}


def _iec_family(page: str) -> tuple[CatalogueEntry, ...]:
    match = _IEC_LIFECYCLES.search(page)
    if match is None:
        raise CatalogueRecordError("IEC record has no lifecycle data")
    try:
        lifecycles = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise CatalogueRecordError("IEC lifecycle data is not JSON") from exc
    entries: list[CatalogueEntry] = []
    for edition in lifecycles.values():
        for item in [edition.get("main"), *edition.get("versions", [])]:
            if not isinstance(item, dict):
                continue
            reference, identifier = item.get("reference"), str(item.get("id", ""))
            if not isinstance(reference, str) or not reference.strip() or not identifier.isdigit():
                raise CatalogueRecordError("IEC lifecycle entry lacks reference or id")
            raw_date = item.get("publication_date")
            try:
                published = date.fromisoformat(raw_date) if raw_date else None
            except (TypeError, ValueError) as exc:
                raise CatalogueRecordError("IEC lifecycle date is not ISO") from exc
            entries.append(CatalogueEntry(
                reference.strip(), request_url(CatalogueSource.IEC_WEBSTORE, identifier), published,
                str(item.get("edition") or ""), _IEC_STATUS.get(str(item.get("status")), str(item.get("status") or "")),
            ))
    if not entries:
        raise CatalogueRecordError("IEC lifecycle data is empty")
    return tuple(entries)


def _iec_record(page: str, url: str) -> CatalogueRecord:
    tree = _document(page)
    family = _iec_family(page)
    identifier = _RECORD_URL[CatalogueSource.IEC_WEBSTORE].fullmatch(url).group(1)
    own = [entry for entry in family if entry.url == request_url(CatalogueSource.IEC_WEBSTORE, identifier)]
    reference = _text(_first(tree, '//div[contains(@class,"reference-number")]'))
    if len(own) != 1 or own[0].publication_date is None or own[0].reference != reference:
        raise CatalogueRecordError("IEC record does not state its own lifecycle entry")
    return CatalogueRecord(
        CatalogueSource.IEC_WEBSTORE, url, reference,
        _text(_first(tree, '//div[contains(@class,"publication-title")]')),
        own[0].publication_date, own[0].edition, own[0].status,
        _text(_first(tree, '//div[@id="product-description"]')), family,
    )


# --- IEEE SA -----------------------------------------------------------------------------

_IEEE_FIELD = re.compile(r"\b(Status|Board Approval|Published:)\s+([^\n]+?)(?=\s+(?:Status|Superseding|Superseded by|Board Approval|History|PAR Approval|ANSI Approved:|Published:|Working Group)\b|$)")


def _ieee_record(page: str, url: str) -> CatalogueRecord:
    tree = _document(page)
    text = re.sub(r"\s+", " ", html_lib.unescape(_text(tree.body if tree.body is not None else tree)))
    fields = {name.rstrip(":"): value.strip() for name, value in _IEEE_FIELD.findall(text)}
    try:
        published = date.fromisoformat(fields.get("Published", "")[:10])
    except ValueError as exc:
        raise CatalogueRecordError("IEEE record has no published date") from exc
    designation = re.search(r"\b(\d+(?:\.\d+)*-\d{4})\b", _text(_first(tree, "//h1"))) or re.search(
        r"\b(\d+(?:\.\d+)*-\d{4})\b", _text(_first(tree, "//title")))
    title = _text(_first(tree, '//*[@id="stnd-title"]'))
    if designation is None:
        raise CatalogueRecordError("IEEE record has no designation")
    reference = f"IEEE {designation.group(1)}"
    family: list[CatalogueEntry] = [CatalogueEntry(reference, url, published, "", fields.get("Status", ""))]
    successor = re.search(r"Superseded by (\d+(?:\.\d+)*-\d{4})", text)
    if successor is not None:
        number = successor.group(1).rsplit("-", 1)[0]
        for link in tree.xpath('//a[@href]'):
            href = link.get("href", "")
            if re.fullmatch(rf"https://standards\.ieee\.org/ieee/{re.escape(number)}/\d+/?", href) and _text(link) == successor.group(1):
                family.append(CatalogueEntry(f"IEEE {successor.group(1)}", href.rstrip("/") + "/", None, "", "Superseding"))
                break
    approval = fields.get("Board Approval", "")[:10]
    other = [f"Board approval: {approval}."] if re.fullmatch(r"\d{4}-\d{2}-\d{2}", approval) else []
    if successor is not None:
        other.append(f"Superseded by: IEEE {successor.group(1)}.")
    return CatalogueRecord(CatalogueSource.IEEE_SA, url, reference, title, published, "", fields.get("Status", ""),
                           "", tuple(family), date_label="Published", other_facts=tuple(other))


_RECORD_PARSERS = {
    CatalogueSource.IEC_WEBSTORE: _iec_record,
    CatalogueSource.IEEE_SA: _ieee_record,
}


def parse_record(source: CatalogueSource | str, page: str, url: str) -> CatalogueRecord:
    """The record ``page`` fetched from ``url`` (the final record URL)."""

    source = CatalogueSource(source)
    if record_source(url) is not source:
        raise CatalogueRecordError("URL is not a record page of the declared source")
    return _RECORD_PARSERS[source](page, url)


def same_source_host(source: CatalogueSource | str, url: str) -> bool:
    return (urlsplit(url).hostname or "") in RECORD_HOSTS[CatalogueSource(source)]


__all__ = [
    "CatalogueEntry",
    "CatalogueRecord",
    "CatalogueRecordError",
    "CatalogueSource",
    "RECORD_HOSTS",
    "parse_record",
    "record_source",
    "request_url",
    "same_source_host",
]
