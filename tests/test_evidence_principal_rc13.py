"""RC-13: principal-document detection on real news page shapes."""

from __future__ import annotations

import unittest

from src.weekly_report.contracts import CanonicalCandidate, FetchedSource
from src.weekly_report.evidence_document import PrincipalDocumentStatus, assess_document
from src.weekly_report.evidence_service import EvidenceService, _amp_canonical_url

BODY = "<p>The operator commissioned new platform screen doors on Line 2 after a six-month trial at three stations.</p>"


def _page(main: str) -> str:
    return f"<html><head><title>t</title></head><body>{main}</body></html>"


class PrincipalDocumentTests(unittest.TestCase):
    def assess(self, html: str):
        return assess_document(html, "text/html", resource_url="https://news.example/articleView.html?idxno=1")

    def test_declared_article_body_resolves_sibling_fragment_units(self):
        html = _page(
            "<article class='item'><ul><li>Reporter A</li><li>2026.10.21</li></ul></article>"
            "<article class='item'><div><button><span>Copy link</span></button></div></article>"
            "<article><header><h1>Doors commissioned</h1></header>"
            f"<article itemprop='articleBody'>{BODY}</article></article>"
        )
        result = self.assess(html)
        self.assertIs(result.principal_document_status, PrincipalDocumentStatus.PRINCIPAL_DOCUMENT_ESTABLISHED)
        self.assertIn("platform screen doors", result.body_text)

    def test_duplicated_article_body_declarations_stay_ambiguous(self):
        html = _page(
            f"<article><h1>A</h1><div itemprop='articleBody'>{BODY}</div></article>"
            f"<article><h1>B</h1><div itemprop='articleBody'>{BODY}</div></article>"
        )
        self.assertIs(self.assess(html).principal_document_status, PrincipalDocumentStatus.PRINCIPAL_DOCUMENT_AMBIGUOUS)

    def test_two_real_articles_without_declaration_stay_ambiguous(self):
        html = _page(f"<article><h1>A</h1>{BODY}</article><article><h1>B</h1>{BODY}</article>")
        self.assertIs(self.assess(html).principal_document_status, PrincipalDocumentStatus.PRINCIPAL_DOCUMENT_AMBIGUOUS)

    def test_style_text_never_makes_a_link_widget_a_document(self):
        html = _page(
            f"<article><h1>Doors commissioned</h1>{BODY}</article>"
            "<article><style>#skin-9 > .item {margin-top:12px}</style>"
            "<a href='https://news.example/other-1'>Other story one</a> <a href='https://news.example/other-2'>Other story two</a></article>"
        )
        result = self.assess(html)
        self.assertIs(result.principal_document_status, PrincipalDocumentStatus.PRINCIPAL_DOCUMENT_ESTABLISHED)
        self.assertNotIn("Other story", result.body_text)

    def test_header_only_block_is_the_documents_own_header(self):
        html = _page(
            "<article><div><header><h1>Line 2 speed revised</h1><p>2026-10-20 16:59</p></header></div>"
            f"<div><h2>Simulation result</h2>{BODY}</div></article>"
        )
        result = self.assess(html)
        self.assertIs(result.principal_document_status, PrincipalDocumentStatus.PRINCIPAL_DOCUMENT_ESTABLISHED)
        self.assertIn("platform screen doors", result.body_text)

    def test_two_generic_story_blocks_remain_ambiguous(self):
        html = _page(f"<article><div><h2>A</h2>{BODY}</div><div><h2>B</h2>{BODY}</div></article>")
        self.assertIs(self.assess(html).principal_document_status, PrincipalDocumentStatus.PRINCIPAL_DOCUMENT_AMBIGUOUS)

    def test_related_links_inside_the_article_are_excluded_but_inline_links_kept(self):
        html = _page(
            "<article><h1>Doors commissioned</h1>"
            "<p>The operator commissioned new platform screen doors on <a href='https://news.example/line2'>Line 2</a> after a trial.</p>"
            "<div><a href='https://news.example/related-1'>Related: tram revival</a></div>"
            "<div><a href='https://facebook.example/share'>Facebook</a> <a href='https://x.example/share'>X</a></div></article>"
        )
        result = self.assess(html)
        self.assertIn("Line 2", result.body_text)
        self.assertNotIn("Related: tram revival", result.body_text)
        self.assertNotIn("Facebook", result.body_text)


class AmpCanonicalTests(unittest.TestCase):
    AMP = (
        '<!doctype html><html ⚡ lang="ko"><head><link rel="canonical" href="https://www.yna.co.kr/view/AKR1">'
        "</head><body><article><h1>t</h1><p>short</p></article></body></html>"
    )

    def test_amp_page_declares_its_same_host_canonical(self):
        self.assertEqual(_amp_canonical_url(self.AMP, "https://www.yna.co.kr/amp/view/AKR1"), "https://www.yna.co.kr/view/AKR1")
        self.assertEqual(_amp_canonical_url(self.AMP.replace("⚡", "amp"), "https://www.yna.co.kr/amp/view/AKR1"), "https://www.yna.co.kr/view/AKR1")

    def test_non_amp_or_cross_host_canonical_is_ignored(self):
        self.assertEqual(_amp_canonical_url(self.AMP.replace("⚡ ", ""), "https://www.yna.co.kr/amp/view/AKR1"), "")
        other = self.AMP.replace("https://www.yna.co.kr/view/AKR1", "https://elsewhere.example/view/AKR1")
        self.assertEqual(_amp_canonical_url(other, "https://www.yna.co.kr/amp/view/AKR1"), "")

    def test_evidence_assesses_the_canonical_article_instead_of_the_amp_page(self):
        canonical_page = _page(f"<article><h1>Line 2 speed revised</h1>{BODY}</article>")
        fetched = []

        def fetcher(url):
            fetched.append(url)
            content = self.AMP if "/amp/" in url else canonical_page
            return FetchedSource(url=url, content=content, status_code=200, content_type="text/html", redirect_chain=(url,))

        result = EvidenceService(fetcher).evaluate(
            CanonicalCandidate("C1", "Line 2 speed revised", "https://www.yna.co.kr/amp/view/AKR1")
        )
        self.assertEqual(fetched, ["https://www.yna.co.kr/amp/view/AKR1", "https://www.yna.co.kr/view/AKR1"])
        self.assertEqual(result.provenance["amp_url"], "https://www.yna.co.kr/amp/view/AKR1")
        self.assertEqual(result.canonical_source_url, "https://www.yna.co.kr/view/AKR1")


if __name__ == "__main__":
    unittest.main()
