"""RC-89: a page whose first canonical declaration is itself fits, as before RC-86.

Synthetic fixtures with the declaration structure of the pages that RC-86/87
rejected as CANONICAL_OTHER_SITE (probe Run 45729522763; synthetic text and
hosts, the repository is public), and of the two republications that must stay
rejected:

* Herald (two pages): ``og:url`` is the resolved mobile page, ``link
  rel=canonical`` the same article on a sibling host (``mbiz.`` / ``biz.``).
* SBS Biz: ``link rel=canonical``, ``og:url`` and a first ``twitter:url`` are the
  page; a second ``twitter:url`` is a feed API host.
* cp24: ``og:url`` is the page, ``link rel=canonical`` the article on another
  news brand's site. Structurally identical to Herald: it fits too (as before
  RC-86); telling the two apart needs a registrable-domain comparison, which the
  user excluded.
* AOL (syndicated BBC article, recall Run 45641734970): the page's canonical
  declarations name the original publisher's article. Rejected.
* Nettavisen (republished Avisa Oslo article): its first declaration names the
  original publisher's article. Rejected.
"""

from __future__ import annotations

import unittest

from src.weekly_report.contracts import EvidenceState
from src.weekly_report.evidence_service import _declared_canonical
from tests.test_evidence_canonical_rc86 import LONG, SHORT, _evaluate

BODY = (
    "<p>A subway branch line stopped running on Thursday morning after a train passed a stop signal and "
    "damaged a track switch.</p><p>Service resumed in the afternoon after the switch was repaired.</p>"
)


def _page(*declarations: tuple[str, str]) -> str:
    tags = []
    for kind, url in declarations:
        if kind == "link":
            tags.append(f'<link rel="canonical" href="{url}" />')
        elif kind == "og":
            tags.append(f'<meta property="og:url" content="{url}" />')
        else:
            tags.append(f'<meta name="twitter:url" content="{url}" />')
    return (
        f"<html><head><title>Branch line stopped</title>{''.join(tags)}</head><body><main><article>"
        f"<h1>Branch line stopped</h1>{BODY}</article></main></body></html>"
    )


HERALD_M = "https://mbiz.daily-herald.test/article/10943384"
HERALD = "https://biz.daily-herald.test/article/10943384"
SBS = "https://biz.broadcast-biz.test/article/20000347750"
SBS_FEED = "https://feedapi.cloud.broadcast-biz.test/feed-api/article_hub/20000347750"
CITY = "https://www.city-news.test/local/2026/11/19/pedestrian-struck-by-lrt-vehicle/"
NATIONAL = "https://www.national-news.test/city/article/pedestrian-struck-by-lrt-vehicle/"
PORTAL = "https://www.portal-news.test/news/tram-boss-to-step-down-120000.html"
BROADCASTER = "https://www.broadcaster.test/news/articles/ck4gnmzre0ndo?xtor=AL-72-partner-portal"
NATIONAL_SITE = "https://www.national-site.test/80-95-257456"


class FirstDeclarationTests(unittest.TestCase):
    def test_herald_pages_fit(self):
        result = _evaluate(HERALD_M, _page(("og", HERALD_M), ("link", HERALD)))
        self.assertIs(result.state, EvidenceState.READY)
        self.assertEqual(result.canonical_source_url, HERALD_M)

    def test_sbs_page_fits(self):
        result = _evaluate(SBS, _page(("link", SBS), ("og", SBS), ("twitter", SBS), ("twitter", SBS_FEED)))
        self.assertIs(result.state, EvidenceState.READY)
        self.assertEqual(result.canonical_source_url, SBS)

    def test_a_self_first_page_naming_another_brand_fits_as_before_rc86(self):
        # Known limit (section A.70): the cp24 structure is the Herald structure.
        result = _evaluate(CITY, _page(("og", CITY), ("link", NATIONAL)))
        self.assertIs(result.state, EvidenceState.READY)

    def test_the_syndicated_copy_is_rejected(self):
        for declarations in ((("link", BROADCASTER),), (("link", BROADCASTER), ("og", BROADCASTER))):
            with self.subTest(declarations=declarations):
                result = _evaluate(PORTAL, _page(*declarations))
                self.assertIs(result.state, EvidenceState.REJECTED)
                self.assertEqual(result.provenance["source_provenance_mismatch_reason"], "CANONICAL_OTHER_SITE")

    def test_a_republication_whose_first_declaration_names_the_original_is_rejected(self):
        result = _evaluate(NATIONAL_SITE, _page(("link", LONG), ("og", NATIONAL_SITE)))
        self.assertIs(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.provenance["source_provenance_mismatch_reason"], "CANONICAL_OTHER_SITE")

    def test_amedia_still_fits(self):
        # RC-86: the short og:url first, unrelated to the resolved long address.
        result = _evaluate(LONG, _page(("og", SHORT), ("link", LONG)))
        self.assertIs(result.state, EvidenceState.READY)
        self.assertEqual(result.canonical_source_url, LONG)

    def test_rule(self):
        self.assertEqual(_declared_canonical((HERALD_M, HERALD), HERALD_M, ()), (HERALD_M, ""))
        self.assertEqual(_declared_canonical((HERALD, HERALD_M), HERALD_M, ()), (HERALD, "CANONICAL_OTHER_SITE"))
        self.assertEqual(_declared_canonical((BROADCASTER,), PORTAL, ()), (BROADCASTER, "CANONICAL_OTHER_SITE"))


if __name__ == "__main__":
    unittest.main()
