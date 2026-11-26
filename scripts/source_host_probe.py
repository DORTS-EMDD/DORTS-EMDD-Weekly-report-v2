"""Observation-only probe of specialist rail media hosts (no MaiAgent calls).

For each URL it fetches the page with EvidenceService's own fetcher, runs the
production structural assessment, and prints the outcome. With --dump it also
prints the page as gzip+base64 between markers, so an offline reviewer without
network access to the host can reproduce the assessment exactly. It never
participates in any production decision.
"""

from __future__ import annotations

import argparse
import base64
import gzip
import json
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.weekly_report import evidence_service
from src.weekly_report.evidence_document import assess_document
from src.weekly_report.temporal_rule import TemporalRule

DEFAULT_URLS = (
    # Railway-News (PRINCIPAL_DOCUMENT in Run 44429652572)
    "https://railway-news.com/austin-light-rail-vehicle-programme-moves-into-preliminary-design/",
    "https://railway-news.com/news/",
    # Mass Transit, Urban Transport Magazine (PRINCIPAL_DOCUMENT)
    "https://www.masstransitmag.com/rail/infrastructure/news/55398395/trinity-metro-fort-worth-transportation-authority-trinity-metro-breaks-ground-on-tre-double-track-project",
    "https://www.urban-transport-magazine.com/en/guatemala-the-metroriel-light-rail-more-electric-buses-and-a-new-cableway-system/",
    # Railway PRO, Railway Gazette, IRJ (FETCH_TRANSPORT)
    "https://www.railwaypro.com/",
    "https://www.railwaygazette.com/",
    "https://www.railjournal.com/",
    # Global Railway Review (DATE_PROVENANCE_INVALID)
    "https://www.globalrailwayreview.com/tracsis-completes-computer-aided-dispatch-deployment-across-watco-railroads-ahead-of-schedule-in-north-america/2137019.article",
    # The three pages that ended at DATE_PROVENANCE_INVALID in that run.
    "https://www.globalrailwayreview.com/thessaloniki-metro-kalamaria-extension-opens-with-hitachi-rail-driverless-signalling-technology/2136343.article",
    "https://www.globalrailwayreview.com/alstom-launches-first-next-generation-g-class-tram-into-passenger-service-in-melbourne/2136277.article",
    "https://www.globalrailwayreview.com/alstom-cbtc-signalling-enters-revenue-service-on-bengaluru-metro-pink-line-reach-6-priority-section/2136996.article",
    # Query-list hosts with no candidate in that run. railtech.com and
    # intelligenttransport.com redirect to other publishers (the probe prints
    # the final url); railway-technology.com is given one article.
    "https://www.railtech.com/",
    "https://www.intelligenttransport.com/",
    "https://www.railway-technology.com/news/alstom-urbalis-flo-cbtc-melbourne-metro-tunnel-project/",
    # Hosts with the most DATE_PROVENANCE_INVALID in that run (one page each).
    "https://tw.news.yahoo.com/%E5%9F%BA%E9%9A%86%E6%8D%B7%E9%81%8B%E6%AD%A3%E5%BC%8F%E9%96%8B%E5%B7%A5-%E4%BE%AF%E5%8F%8B%E5%AE%9C%E5%8A%9B%E6%8B%9A2033%E5%B9%B4%E5%AE%8C%E5%B7%A5%E9%80%9A%E8%BB%8A-101553376.html",
    "https://www.kyeonggi.com/article/20261102580350",
    "https://j.people.com.cn/n3/2026/1030/c94638-20514129.html",
    "https://jp.news.cn/20261031/12cfe1ffe30d4b188d9b18a4fc0e4863/c.html",
    # Hosts with the most PRINCIPAL_DOCUMENT failures in that run (one page each).
    "https://www.yna.co.kr/view/AKR20261019059100057",
    "https://www.infobae.com/colombia/2026/09/07/metro-de-bogota-arranco-segundo-intento-de-licitacion-de-la-linea-2-ya-habilito-la-entrega-de-documentos-para-empresas-interesadas/",
    "https://www.yonhapnewstv.co.kr/news/AKR20260922210611qDJ",
    "https://www.newspim.com/news/view/20260922001267",
    "https://imnews.imbc.com/news/2026/society/article/6850242_36918.html",
    # Run 44462316932 (2026-11-09..15): Rail Technology Magazine pages that ended at
    # PRINCIPAL_DOCUMENT_AMBIGUOUS (six) or DATE_PROVENANCE_INVALID (the Vossloh page).
    "https://www.railtechnologymagazine.com/articles/gbr-anglia-plans-100000-miles-track-treatment-boost-rail-resilience-autumn-and-winter",
    "https://www.railtechnologymagazine.com/articles/northern-and-caf-partnership-delivers-major-reliability-boost-class-331-fleet",
    "https://www.railtechnologymagazine.com/articles/podcast-episode-82-inclusion-and-diversity-tracks",
    "https://www.railtechnologymagazine.com/articles/alstoms-next-generation-tgv-m-enters-passenger-service-france",
    "https://www.railtechnologymagazine.com/articles/network-rail-forecasts-ps149bn-station-spending-boom-wellness-and-leisure-transform",
    "https://www.railtechnologymagazine.com/articles/stadler-lands-first-finnish-tram-contract-helsinki-order-worth-183-vehicles",
    "https://www.railtechnologymagazine.com/articles/vossloh-wins-contract-supply-booted-sleepers-sydney-metro-west",
    # Mass Transit page whose two ORIGINAL_PUBLICATION facts ended at DATE_UNPARSEABLE.
    "https://www.masstransitmag.com/rail/infrastructure/news/55418425/the-austin-transit-partnership-austin-transit-partnership-advances-planning-for-future-extension-of-austin-light-rail-to-austin-bergstrom-international-airport",
    # 2026-11-16..22 recall review (Runs 44919705575 and 45103217994):
    # 철도경제신문 pages that ended at INSUFFICIENT_SUBSTANCE|PRINCIPAL_DOCUMENT.
    "https://www.redaily.co.kr/news/articleView.html?idxno=18220",
    "https://www.redaily.co.kr/news/articleView.html?idxno=18269",
    "https://www.redaily.co.kr/news/articleView.html?idxno=18261",
    # One page of each host with the most SOURCE_PAGE_MISMATCH|PRINCIPAL_DOCUMENT.
    "https://www.vietnam.vn/ja/doanh-nghiep-muon-ro-tieu-chuan-goi-thau-de-tham-gia-metro",
    "https://www.onet.pl/informacje/przez-wieki-2/atak-w-tokijskim-metrze-zamach-ktora-wstrzasnal-japonia/vstz7tr,0666d3f1",
    "https://www.rynekinfrastruktury.pl/wiadomosci/miasto/warszawa-matro-ma-byc-przedluzone-z-brodna-na-marymont-107510.html",
    "https://transinfo.pl/infotram/warszawa-tramwaje-nie-pojada-targowa-zmiany-dla-pieciu-linii/",
    "https://warszawa.wyborcza.pl/warszawa/7,54420,33141462,rewolucyjna-zapowiedz-dla-warszawy-druga-linia-metra-pojedzie.htm",
    "https://tvn24.pl/krakow/krakow-wysiada-z-metra-minister-obrony-narodowej-deklaruje-wsparcie-st9345911",
    "https://www.bankier.pl/wiadomosc/Warszawa-przedluzy-druga-linie-metra-Powstana-cztery-nowe-stacje-9231876.html",
    "https://www.newspim.com/news/view/20261117000559",
    "https://olomoucky.denik.cz/zpravy-region/olomouc-dpmo-vanocni-tramvaje-spanila-mikulaska-jizda/",
    "https://polskieradio24.pl/polska/nie-bedzie-metra-beda-tramwaje-krakow-stawia-na-kolej-naziemna-chce-siedmiu-linii",
    "https://www.wnp.pl/budownictwo/zwrot-w-sprawie-metra-w-krakowie-nowe-wladze-mowia-co-dalej,1120510.html",
    # Recall targets: Scope (Stadler Helsinki), Category (Fortress), Evidence
    # SOURCE_PROVENANCE (two Oslo derailment reports).
    "https://www.urban-transport-magazine.com/en/now-confirmed-and-signed-stadler-secures-contract-for-up-to-183-tango-trams-for-helsinki/",
    "https://www.masstransitmag.com/rail/railroad-signals-ptc-control-systems-and-products/article/55420233/fortress-solutions-providing-wireless-network-integration-for-new-york-city-transits-fulton-liberty-line",
    "https://www.nettavisen.no/80-95-257456",
    "https://www.nab.no/80-143-38894",
    # RC-89 (observation only): pages rejected as CANONICAL_OTHER_SITE under
    # RC-86/87 (recall Runs 45558738725, 45641734970); which declaration kind
    # (link rel=canonical, og:url, twitter:url) names the other host.
    "https://mbiz.heraldcorp.com/article/10943384",
    "https://mbiz.heraldcorp.com/article/10943388",
    "https://biz.sbs.co.kr/article/20000347750",
    "https://www.cp24.com/local/toronto/2026/11/19/female-pedestrian-dead-after-being-struck-by-eglinton-lrt-vehicle/",
)

FEEDS = (
    "https://railway-news.com/feed/",
    "https://www.railwaypro.com/feed/",
    "https://www.railwaygazette.com/rss",
    "https://www.railjournal.com/feed/",
    "https://www.masstransitmag.com/rss",
    "https://www.urban-transport-magazine.com/en/feed/",
)


def _probe_page(url: str, dump: bool) -> None:
    print(f"\n=== PAGE {url}")
    try:
        fetched = evidence_service._default_fetcher(url, 20.0)
    except Exception as exc:  # observation only
        print(f"FETCH_ERROR {type(exc).__name__} {getattr(exc, 'status_code', '')} {exc}")
        return
    print(f"status={fetched.status_code} content_type={fetched.content_type} bytes={len(fetched.content)} url={fetched.url}")
    # The same call EvidenceService makes, including the resource-identity
    # checker that JSON-LD date facts require (RC-71: the earlier probe omitted
    # it and so always showed no date facts).
    assessment = assess_document(
        fetched.content,
        fetched.content_type,
        resource_url=fetched.url,
        candidate_id="probe",
        resource_identity_checker=lambda value: evidence_service._canonical_is_related(
            value, fetched.url, fetched.redirect_chain
        ),
    )
    provenance = assessment.as_provenance()
    print("principal_document_status=", assessment.principal_document_status.value)
    print("structural_diagnostics=", json.dumps(
        {k: v for k, v in assessment.diagnostics.items() if k != "parse_diagnostics"}, ensure_ascii=False, default=str))
    temporal = TemporalRule().evaluate(
        "probe", assessment.source_date_facts, "2000-01-01", "2100-12-31", source_type="news"
    )
    print("temporal=", temporal.date_valid, getattr(temporal.diagnostic, "value", temporal.diagnostic),
          temporal.controlling_calendar_date)
    print("reject_reason=", assessment.reject_reason)
    print("body_chars=", len(assessment.body_text))
    print("headlines=", list(assessment.document_level_headlines)[:3])
    print("date_facts=", json.dumps(list(assessment.source_date_facts)[:5], ensure_ascii=False, default=str))
    print("provenance=", json.dumps(provenance, ensure_ascii=False, default=str)[:3000])
    print("jsonld_types=", re.findall(r'"@type"\s*:\s*"([^"]+)"', fetched.content)[:12])
    print("date_markup=", json.dumps(_date_markup(fetched.content), ensure_ascii=False))
    if dump:
        blob = base64.b64encode(gzip.compress(fetched.content.encode("utf-8"))).decode("ascii")
        print(f"<<<HTML_GZ_B64 {url}")
        for i in range(0, len(blob), 4000):
            print(blob[i : i + 4000])
        print("HTML_GZ_B64>>>")


def _date_markup(content: str) -> dict[str, object]:
    """Raw date-bearing markup of a page, to explain an empty date_facts."""

    return {
        "meta_dates": re.findall(
            r"""<meta[^>]+(?:property|name|itemprop)=["']([^"']*(?:date|time|pub)[^"']*)["'][^>]*content=["']([^"']*)""",
            content,
            flags=re.I,
        )[:8],
        "jsonld_identity_and_dates": re.findall(
            r'"(@id|url|mainEntityOfPage|datePublished|dateModified|dateCreated)"\s*:\s*(?:"([^"]*)"|\{[^}]*\})',
            content,
        )[:12],
        "time_elements": re.findall(r"<time[^>]*>", content)[:5],
    }


def _probe_status(url: str, user_agent: str) -> str:
    request = Request(url, headers={"User-Agent": user_agent, "Accept": "*/*"})
    try:
        with urlopen(request, timeout=20) as response:
            body = response.read()
            text = body.decode("utf-8", "replace")
            items = len(re.findall(r"<item[\s>]|<entry[\s>]", text))
            full = len(re.findall(r"<content:encoded>", text))
            return f"{response.status} bytes={len(body)} items={items} content_encoded={full}"
    except HTTPError as exc:
        return f"HTTP {exc.code} server={exc.headers.get('Server', '')} cf={'cf-ray' in {k.lower() for k in exc.headers.keys()}}"
    except URLError as exc:
        return f"URLError {exc.reason}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dump", action="store_true")
    parser.add_argument("urls", nargs="*")
    args = parser.parse_args(argv)
    for url in args.urls or DEFAULT_URLS:
        _probe_page(url, args.dump)
    print("\n=== STATUS BY USER-AGENT (diagnosis of FETCH_TRANSPORT only)")
    agents = {
        "evidence": "Weekly-report-v2-EvidenceService/1.0",
        "browser_like": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    }
    for url in (*DEFAULT_URLS[4:7], *FEEDS):
        for name, agent in agents.items():
            print(f"{name:12} {url} -> {_probe_status(url, agent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
