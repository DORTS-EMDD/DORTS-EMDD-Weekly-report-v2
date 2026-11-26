"""RC-86 (section A.67): a page's canonical declarations fit when any one is related.

Fixtures copy the structure of three Amedia pages seen in recall Run 45558738725
and source probe Run 45618703238 (synthetic text and hosts; the repository is
public):

* a local paper declares ``og:url`` with the short article address first and
  ``link rel=canonical`` with the long slug address of the same article;
* a second local paper does the same;
* a national site republishes the first paper's article and declares the first
  paper's long address as its ``link rel=canonical``.

Before RC-86 only the first declaration (the short ``og:url``) was compared
with the resolved long address, so both local papers were rejected at
``SOURCE_PROVENANCE``.
"""

from __future__ import annotations

import unittest

from src.weekly_report.contracts import EvidenceState
from src.weekly_report.evidence_service import EvidenceService, FetchedSource, _declared_canonical, _site_host
from tests.test_evidence_contract import _candidate, _FixtureFetcher, _SameEventJudge

SHORT = "https://www.local-oslo.test/30-128-26544"
LONG = "https://www.local-oslo.test/full-stans-bil-hindret-trikken/s/30-128-26544"
NAB_SHORT = "https://www.local-nordre.test/80-143-38894"
NAB_LONG = "https://www.local-nordre.test/full-stans-i-trikketrafikken/s/80-143-38894"
REPUBLISHED = "https://www.national-site.test/80-95-257456"
ORIGINAL_ELSEWHERE = "https://www.local-oslo.test/trikk-sporet-av/s/80-128-81602"

BODY = (
    "<p>A tram derailed at a junction in the city on Tuesday afternoon, and tram traffic on two lines "
    "was stopped for several hours.</p>"
    "<p>The operator sent replacement buses while crews lifted the tram back onto the rails and "
    "inspected the track.</p>"
)


def _page(*, og_url: str | None, link_canonical: str | None) -> str:
    head = ["<meta charset='utf-8'>", "<title>Tram derailed at junction</title>"]
    if og_url:
        head.append(f"<meta property='og:url' content='{og_url}'>")
    if link_canonical:
        head.append(f"<link rel='canonical' href='{link_canonical}'>")
    return (
        f"<html><head>{''.join(head)}</head><body><main><article>"
        f"<h1>Tram derailed at junction</h1>{BODY}</article></main></body></html>"
    )


def _evaluate(resolved: str, html: str, chain: tuple[str, ...] | None = None):
    source = FetchedSource(url=resolved, content=html, content_type="text/html", redirect_chain=chain or ())
    return EvidenceService(_FixtureFetcher(source), semantic_judge=_SameEventJudge()).evaluate(
        _candidate(url=resolved, title="Tram derailed at junction", search_snippet="A tram derailed.")
    )


class DeclaredCanonicalTests(unittest.TestCase):
    def test_short_og_url_and_long_link_canonical_fit_the_long_address(self):
        result = _evaluate(LONG, _page(og_url=SHORT, link_canonical=LONG))
        self.assertIs(result.state, EvidenceState.READY)
        self.assertEqual(result.canonical_source_url, LONG)

    def test_they_also_fit_the_short_address(self):
        result = _evaluate(SHORT, _page(og_url=SHORT, link_canonical=LONG))
        self.assertIs(result.state, EvidenceState.READY)
        self.assertEqual(result.canonical_source_url, SHORT)

    def test_second_local_paper(self):
        result = _evaluate(NAB_LONG, _page(og_url=NAB_SHORT, link_canonical=NAB_LONG))
        self.assertIs(result.state, EvidenceState.READY)
        self.assertEqual(result.canonical_source_url, NAB_LONG)

    def test_a_republication_whose_canonical_names_another_site_is_rejected(self):
        # RC-89: a page whose first declaration is itself fits as before RC-86
        # (tests/test_evidence_canonical_rc89.py); here the first declaration
        # names the other site's article.
        for og_url in (ORIGINAL_ELSEWHERE, None):
            with self.subTest(og_url=og_url):
                result = _evaluate(REPUBLISHED, _page(og_url=og_url, link_canonical=ORIGINAL_ELSEWHERE))
                self.assertIs(result.state, EvidenceState.REJECTED)
                self.assertEqual(result.provenance["evidence_rejection_gate"], "SOURCE_PROVENANCE")
                self.assertEqual(result.provenance["source_provenance_mismatch_reason"], "CANONICAL_OTHER_SITE")

    def test_unrelated_same_site_declarations_stay_a_resource_mismatch(self):
        result = _evaluate(LONG, _page(og_url=NAB_SHORT.replace("local-nordre", "local-oslo"), link_canonical=None))
        self.assertIs(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.provenance["source_provenance_mismatch_reason"], "CANONICAL_RESOURCE_MISMATCH")

    def test_a_canonical_reached_through_the_redirect_chain_is_related(self):
        # Unchanged: a declaration that was a step of the acquisition redirect
        # chain is the same resource, also on another host.
        amp = "https://amp.local-oslo.test/30-128-26544"
        self.assertEqual(_declared_canonical((LONG,), amp, (LONG, amp)), (LONG, ""))

    def test_rule(self):
        self.assertEqual(_declared_canonical((), LONG, ()), ("", ""))
        self.assertEqual(_declared_canonical((SHORT, LONG), LONG, ()), (LONG, ""))
        self.assertEqual(_declared_canonical(("/30-128-26544", LONG), SHORT, ()), (SHORT, ""))
        self.assertEqual(
            _declared_canonical((ORIGINAL_ELSEWHERE, REPUBLISHED), REPUBLISHED, ()),
            (ORIGINAL_ELSEWHERE, "CANONICAL_OTHER_SITE"),
        )



class SameSitePrefixTests(unittest.TestCase):
    """RC-87: www., m., mobile. and amp. are the same site; nothing else is."""

    def test_site_host(self):
        for host in ("www.local-oslo.test", "m.local-oslo.test", "mobile.local-oslo.test", "amp.local-oslo.test",
                     "local-oslo.test", "www.m.local-oslo.test"):
            with self.subTest(host=host):
                self.assertEqual(_site_host(f"https://{host}/a"), "local-oslo.test")
        for host in ("news.local-oslo.test", "mbiz.local-oslo.test", "local-oslo.example", "m2.local-oslo.test"):
            with self.subTest(host=host):
                self.assertNotEqual(_site_host(f"https://{host}/a"), "local-oslo.test")

    def test_a_mobile_or_amp_declaration_beside_a_related_one_fits(self):
        for prefix in ("m.", "mobile.", "amp."):
            with self.subTest(prefix=prefix):
                other = f"https://{prefix}local-oslo.test/30-128-26544"
                self.assertEqual(_declared_canonical((other, LONG), LONG, ()), (LONG, ""))
                result = _evaluate(LONG, _page(og_url=other, link_canonical=LONG))
                self.assertIs(result.state, EvidenceState.READY)
                self.assertEqual(result.canonical_source_url, LONG)

    def test_a_mobile_declaration_alone_is_a_same_site_resource_mismatch(self):
        # Same site, but not the same resource and not in the redirect chain:
        # unchanged, as d5bfbaa (CANONICAL_RESOURCE_MISMATCH, not another site).
        other = "https://m.local-oslo.test/30-128-26544"
        self.assertEqual(_declared_canonical((other,), LONG, ()), (other, "CANONICAL_RESOURCE_MISMATCH"))

    def test_other_subdomains_are_still_another_site(self):
        other = "https://news.local-oslo.test/30-128-26544"
        self.assertEqual(_declared_canonical((other, LONG), LONG, ()), (other, "CANONICAL_OTHER_SITE"))


if __name__ == "__main__":
    unittest.main()
