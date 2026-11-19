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
