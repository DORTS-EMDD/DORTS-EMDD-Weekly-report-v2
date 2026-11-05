"""RC-60 (contract section A.44): official standards catalogue records.

The catalogue is a second Search discovery provider, used only in the monthly
monitored-standards check. It produces Candidates and decides nothing:
EvidenceService accepts an official record as Evidence, and Scope, Temporal and
Reportability judge it like any other Candidate. Fixtures below are minimal
pages with the real record structure (no copied page text).
"""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path
from urllib.error import HTTPError

import pytest

from src.weekly_report.contracts import (
    CanonicalCandidate,
    DiscoveryIntent,
    EvidenceState,
    FetchedSource,
    MonitoredCheckMonth,
    RegionMode,
    RegionResolutionBasis,
    RejectReason,
    ScopeState,
    SearchPlanItem,
    SearchProviderId,
    SearchTechnicalFailureClass,
    SearchTerminalStatus,
    SearchWindow,
    SourceDateKind,
)
from src.weekly_report.evidence_service import EvidenceService
from src.weekly_report.monitored_standards import load_monitored_standards_data, monitored_standards
from src.weekly_report.region_registry import RegionRegistry
from src.weekly_report.scope_classifier import MonitoredStandardScopeRequest, ScopeClassifier
from src.weekly_report.search_planner import SearchPlanner
from src.weekly_report.standards_catalogue import (
    CatalogueRecordError,
    CatalogueSource,
    parse_record,
    record_source,
    request_url,
)
from src.weekly_report.standards_catalogue_provider import CatalogueResponse, StandardsCatalogueProvider, _SameSourceRedirects
from src.weekly_report.temporal_rule import TemporalRule

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "weekly_report"
JULY = MonitoredCheckMonth(date(2026, 7, 1), date(2026, 7, 31))

_LIFECYCLES = {
    "v3": {"main": {"reference": "IEC 61373:2026", "publication_date": "2026-07-17", "edition": "3.0", "id": "68999", "status": "PUBLISHED"}, "versions": []},
    "v2": {"main": {"reference": "IEC 61373:2010/COR1:2011", "publication_date": "2011-10-12", "edition": "2.0", "id": "5396", "status": "REVISED"},
           "versions": [{"reference": "IEC 61373:2010", "publication_date": "2010-05-31", "edition": "2.0", "id": "5395", "status": "REVISED"}]},
    "v1": {"main": {"reference": "IEC 61373:1999", "publication_date": "1999-01-07", "edition": "1.0", "id": "19719", "status": "REVISED"}, "versions": []},
}


def _iec_page(reference: str, publication_date: str, edition: str, *, lifecycles=_LIFECYCLES) -> str:
    return f"""<html><head><title>{reference} | IEC</title></head><body>
<div class="reference-number"><span>{reference}</span></div>
<div class="publication-title"><span>Railway applications - Rolling stock equipment - Shock and vibration tests</span></div>
<div id="product-description"><div>Fixture description. This third edition cancels and replaces the second edition.</div></div>
<table class="iec-table"><tr><td><strong>Publication date</strong></td><td>{publication_date}</td></tr>
<tr><td><strong>Edition</strong></td><td>{edition}</td></tr></table>
<script> function initProductLifecycleTab_1() {{ return {{
        underDevelopmentProduct: [],
        lifecycles: {json.dumps(lifecycles)},
        statusMapping: {{ 'PUBLISHED': 'Published' }} }} }}</script></body></html>"""


def _ieee_page(designation: str, status: str, published: str, *, superseded_by: tuple[str, str] | None = None) -> str:
    successor = ""
    if superseded_by:
        successor = f'Superseded by <a href="https://standards.ieee.org/ieee/1474.1/{superseded_by[1]}">{superseded_by[0]}</a>'
    return f"""<html><head><title>IEEE SA - IEEE {designation}</title></head><body>
<h1>IEEE {designation}</h1><h2 id="stnd-title">IEEE Standard for Communications-Based Train Control (CBTC) Performance and Functional Requirements</h2>
<div>Status {status} {successor} Board Approval 2025-03-27 History Published: {published} Working Group Details</div></body></html>"""


IEC_URL = "https://webstore.iec.ch/en/publication/68999"
IEC_OLD_URL = "https://webstore.iec.ch/en/publication/5396"


# --- Pure record parsing --------------------------------------------------------------------


def test_an_iec_record_states_the_whole_family_lifecycle():
    record = parse_record("iec_webstore", _iec_page("IEC 61373:2026", "2026-07-17", "3.0"), IEC_URL)
    assert (record.reference, record.publication_date, record.edition, record.status) == (
        "IEC 61373:2026", date(2026, 7, 17), "3.0", "Published")
    assert [entry.reference for entry in record.family] == [
        "IEC 61373:2026", "IEC 61373:2010/COR1:2011", "IEC 61373:2010", "IEC 61373:1999"]
    text = record.as_evidence_text()
    assert "Publication date: 2026-07-17. Edition: 3.0. Status: Published." in text
    assert "cancels and replaces" in text


def test_an_older_iec_record_already_names_the_newer_edition():
    record = parse_record("iec_webstore", _iec_page("IEC 61373:2010/COR1:2011", "2011-10-12", "2.0"), IEC_OLD_URL)
    assert any(entry.reference == "IEC 61373:2026" and entry.publication_date == date(2026, 7, 17)
               for entry in record.family)


def test_an_ieee_record_states_status_date_and_successor():
    active = parse_record("ieee_sa", _ieee_page("1474.1-2025", "Active Standard", "2025-06-13"),
                          "https://standards.ieee.org/ieee/1474.1/6959/")
    assert (active.reference, active.publication_date) == ("IEEE 1474.1-2025", date(2025, 6, 13))
    assert "Published: 2025-06-13." in active.as_evidence_text()
    old = parse_record("ieee_sa", _ieee_page("1474.1-2004", "Superseded Standard", "2004-12-01",
                                              superseded_by=("1474.1-2025", "6959")),
                       "https://standards.ieee.org/ieee/1474.1/3552/")
    assert [(entry.reference, entry.status) for entry in old.family][-1] == ("IEEE 1474.1-2025", "Superseding")


@pytest.mark.parametrize("page", ["", "<html><body>no record</body></html>"])
def test_an_unreadable_record_fails_closed(page):
    with pytest.raises(CatalogueRecordError):
        parse_record("iec_webstore", page, IEC_URL)


def test_record_urls_are_recognised_only_for_supported_sources():
    assert record_source(IEC_URL) is CatalogueSource.IEC_WEBSTORE
    assert record_source("https://standards.ieee.org/ieee/1474.1/6959/") is CatalogueSource.IEEE_SA
    for url in ("https://www.astm.org/Standards/E119.htm", "https://webstore.iec.ch/en/search?q=1",
                "https://news.example.test/iec-61373", "http://webstore.iec.ch/en/publication/68999"):
        assert record_source(url) is None
    with pytest.raises(ValueError):
        request_url("iec_webstore", "68999/../1")
    with pytest.raises(ValueError):
        request_url("astm_store", "E119")


# --- The list: the 27 stay the only scope; 10 records are configured -----------------------


def test_every_listed_standard_is_configured_or_explained_and_the_list_is_unchanged():
    data = load_monitored_standards_data()
    standards = monitored_standards()
    configured = [record.identifier for record in standards.catalogue_records]
    explained = list(data["catalogue_records"]["not_configured"])
    assert len(standards.identifiers) == 27 and len(configured) == 10 and len(explained) == 17
    assert sorted(configured + explained) == sorted(standards.identifiers)
    assert {record.source for record in standards.catalogue_records} == {"iec_webstore", "ieee_sa"}
    for kept in ("NFPA 258", "EN 50128", "UIC 860-0", "IEC 60076", "IEC 60332-1", "ASTM E119"):
        assert kept in standards.identifiers and kept in explained
    assert "EN 50716" not in json.dumps(data["groups"])


# --- Search: the provider produces Candidates only, in the check month ----------------------


def _item(query: str, window: SearchWindow) -> SearchPlanItem:
    return SearchPlanItem("item-1", "standards_catalogue", RegionMode.SELECTED, DiscoveryIntent.MONITORED_STANDARDS,
                          "catalogue", "monitored_standard_catalogue", SearchProviderId.STANDARDS_CATALOGUE, query, None,
                          locale="und", search_window=window)


def _transport(pages: dict[str, tuple[int, str, str]]):
    def transport(url, timeout, source):
        if url not in pages:
            raise HTTPError(url, 403, "Forbidden", {}, None)
        status, final_url, body = pages[url]
        return CatalogueResponse(status, final_url, body)
    return transport


def test_the_provider_returns_only_entries_dated_in_the_check_month():
    pages = {IEC_URL: (200, IEC_URL, _iec_page("IEC 61373:2026", "2026-07-17", "3.0"))}
    provider = StandardsCatalogueProvider(_transport(pages))
    july = provider.execute(_item("iec_webstore:68999", SearchWindow(JULY.start, JULY.end)))
    assert july.status is SearchTerminalStatus.SUCCESS_WITH_RESULTS
    assert [(r.url, r.title.split(":")[0] + ":" + r.title.split(":")[1]) for r in july.results] == [(IEC_URL, "IEC 61373:2026")]
    august = provider.execute(_item("iec_webstore:68999", SearchWindow(date(2026, 8, 1), date(2026, 8, 31))))
    assert august.status is SearchTerminalStatus.SUCCESS_ZERO_RESULTS


def test_an_ieee_successor_is_discovered_undated_and_left_to_temporal():
    url = "https://standards.ieee.org/ieee/1474.1/3552/"
    pages = {url: (200, url, _ieee_page("1474.1-2004", "Superseded Standard", "2004-12-01", superseded_by=("1474.1-2025", "6959")))}
    result = StandardsCatalogueProvider(_transport(pages)).execute(_item("ieee_sa:1474.1/3552", SearchWindow(JULY.start, JULY.end)))
    assert [(r.url, r.published_at) for r in result.results] == [("https://standards.ieee.org/ieee/1474.1/6959/", "")]


@pytest.mark.parametrize(
    ("pages", "failure"),
    [
        ({}, SearchTechnicalFailureClass.AUTHENTICATION),  # the site refuses the production client (403)
        ({IEC_URL: (200, "https://webstore.iec.ch/en/", "<html></html>")}, SearchTechnicalFailureClass.INVALID_RESPONSE),
        ({IEC_URL: (200, IEC_URL, "<html><body>changed layout</body></html>")}, SearchTechnicalFailureClass.INVALID_RESPONSE),
    ],
)
def test_catalogue_failures_are_disclosed_technical_failures_never_results(pages, failure):
    result = StandardsCatalogueProvider(_transport(pages)).execute(_item("iec_webstore:68999", SearchWindow(JULY.start, JULY.end)))
    assert (result.status, result.technical_failure_class) == (SearchTerminalStatus.TECHNICAL_FAILURE, failure)


def test_redirects_are_followed_only_within_the_source_hosts():
    handler = _SameSourceRedirects(CatalogueSource.IEC_WEBSTORE)
    assert handler.redirect_request(None, None, 302, "", {}, "https://example.test/elsewhere") is None


def test_catalogue_items_exist_only_in_the_monthly_check_and_cover_the_month():
    registry = RegionRegistry.from_file()
    weekly = SearchPlanner(registry).plan("selected", window=SearchWindow(date(2026, 7, 13), date(2026, 7, 19)))
    assert not [i for i in weekly.items if i.provider_target is SearchProviderId.STANDARDS_CATALOGUE]
    monthly = SearchPlanner(registry).plan("selected", window=SearchWindow(date(2026, 7, 27), date(2026, 8, 2)),
                                           monitored_check=JULY)
    catalogue = [i for i in monthly.items if i.provider_target is SearchProviderId.STANDARDS_CATALOGUE]
    assert len(catalogue) == 10 and {i.search_window for i in catalogue} == {SearchWindow(JULY.start, JULY.end)}
    assert all(i.intent is DiscoveryIntent.MONITORED_STANDARDS and i.provider_encoding is None for i in catalogue)
    assert len([i for i in monthly.items if i.provider_target is SearchProviderId.GOOGLE_NEWS_RSS]) == 140 + 63


# --- Evidence: an official record is Authoritative Evidence from its own fields -------------


def _evidence(fetched: FetchedSource, url: str = IEC_URL):
    return EvidenceService(fetcher=lambda _url: fetched).evaluate(CanonicalCandidate("C1", "IEC 61373:2026", url))


def test_an_official_record_becomes_evidence_from_its_own_fields():
    result = _evidence(FetchedSource(IEC_URL, _iec_page("IEC 61373:2026", "2026-07-17", "3.0"), 200, "text/html", (IEC_URL,)))
    assert result.state is EvidenceState.READY and result.source_type == "official_standards_catalogue"
    assert result.canonical_source_url == IEC_URL
    assert result.substantive_content.startswith("IEC 61373:2026: Railway applications")
    (fact,) = result.source_date_facts
    assert (fact.raw_date_value, fact.date_kind) == ("2026-07-17", SourceDateKind.ORIGINAL_PUBLICATION)
    assert result.identity_facts.region_resolution.basis is RegionResolutionBasis.NOT_STATED


@pytest.mark.parametrize(
    ("fetched", "reason", "gate"),
    [
        (FetchedSource("https://webstore.iec.ch/en/publication/1", "<html></html>", 200, "text/html", ()),
         RejectReason.SOURCE_PAGE_MISMATCH, "SOURCE_PROVENANCE"),
        (FetchedSource(IEC_URL, "<html><body>changed</body></html>", 200, "text/html", ()),
         RejectReason.INSUFFICIENT_SUBSTANCE, "CATALOGUE_RECORD"),
        (FetchedSource(IEC_URL, "", 404, "text/html", ()), RejectReason.CONTENT_UNAVAILABLE, "HTTP_STATUS"),
    ],
)
def test_a_record_that_cannot_be_established_is_rejected(fetched, reason, gate):
    result = _evidence(fetched)
    assert (result.state, result.reject_reason, result.provenance.get("evidence_rejection_gate")) == (
        EvidenceState.REJECTED, reason, gate)


# --- The record still passes the ordinary owners: Scope then Temporal ------------------------


def test_the_record_reaches_scope_and_temporal_through_their_own_rules():
    evidence = _evidence(FetchedSource(IEC_URL, _iec_page("IEC 61373:2026", "2026-07-17", "3.0"), 200, "text/html", (IEC_URL,)))

    def helper(request):
        assert isinstance(request, MonitoredStandardScopeRequest) and request.monitored_identifiers == ("IEC 61373",)
        return {"candidate_id": "C1", "changed_standard": "IEC 61373", "lifecycle_action": "NEW_EDITION_OR_REVISION",
                "sentence_ids": ["S1", "S2"], "rationale": "scripted"}

    scope = ScopeClassifier(helper).classify(evidence, monitored_check=JULY)
    assert scope.state is ScopeState.IN_SCOPE and scope.monitored_standard.identifier == "IEC 61373"
    temporal = TemporalRule().evaluate("C1", evidence.source_date_facts, date(2026, 7, 27), date(2026, 8, 2),
                                       source_type=evidence.source_type, scope_result=scope)
    assert temporal.date_valid and temporal.controlling_calendar_date == date(2026, 7, 17)


# --- Architecture: the catalogue decides nothing -------------------------------------------


def test_the_catalogue_modules_hold_no_downstream_decision():
    for name in ("standards_catalogue.py", "standards_catalogue_provider.py"):
        imports = [line for line in (SRC / name).read_text(encoding="utf-8").splitlines()
                   if line.startswith(("from ", "import ")) or line.startswith("    ") and " import " in line]
        for owner in ("scope_classifier", "temporal_rule", "reportability", "classifier", "report_service", "delivery",
                      "monitored_standards", "maiagent", "evidence_service"):
            assert not any(owner in line for line in imports), (name, owner)
    readers = sorted(path.name for path in SRC.glob("*.py") if "standards_catalogue import" in path.read_text(encoding="utf-8")
                     or "from .standards_catalogue " in path.read_text(encoding="utf-8"))
    assert readers == ["evidence_service.py", "monitored_standards.py", "standards_catalogue_provider.py"]
