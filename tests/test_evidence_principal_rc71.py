"""RC-71: three structural facts that kept real trade-press articles ambiguous.

Each case is a generic document shape (no publisher selector, class name or
phrase): a related-document collection outside the single principal article,
the same title stated twice, and interactive widgets inside the article.
Listings and genuinely competing units must stay ambiguous.
"""

from __future__ import annotations

import unittest

from src.weekly_report.evidence_document import PrincipalDocumentStatus, assess_document

BODY = "<p>The operator commissioned new platform screen doors on Line 2 after a six-month trial at three stations.</p>"
ESTABLISHED = PrincipalDocumentStatus.PRINCIPAL_DOCUMENT_ESTABLISHED
AMBIGUOUS = PrincipalDocumentStatus.PRINCIPAL_DOCUMENT_AMBIGUOUS


def _cards(count: int) -> str:
    return "<ul>" + "".join(
        f"<li><h3>Other story {index}</h3><p>Summary of other story {index} from the same publisher.</p></li>"
        for index in range(count)
    ) + "</ul>"


def _assess(html: str):
    return assess_document(html, "text/html", resource_url="https://news.example/articles/doors")


class RelatedCollectionOutsideThePrincipalArticleTests(unittest.TestCase):
    def test_related_cards_beside_the_single_article_do_not_make_it_ambiguous(self):
        html = (
            "<html><head><title>t</title></head><body><main>"
            f"<article><h1>Doors commissioned</h1>{BODY}</article>"
            f"<section>{_cards(3)}</section>"
            "</main></body></html>"
        )
        result = _assess(html)
        self.assertIs(result.principal_document_status, ESTABLISHED)
        self.assertIn("platform screen doors", result.body_text)
        self.assertNotIn("Other story", result.body_text)

    def test_a_collection_without_an_article_is_still_a_listing(self):
        html = f"<html><body><main><section>{_cards(4)}</section></main></body></html>"
        self.assertIs(_assess(html).principal_document_status, AMBIGUOUS)

    def test_a_collection_inside_the_article_still_counts(self):
        html = (
            "<html><body><main><article><h1>Doors commissioned</h1>"
            f"{BODY}{_cards(3)}</article></main></body></html>"
        )
        self.assertIs(_assess(html).principal_document_status, AMBIGUOUS)

    def test_a_collection_that_contains_the_article_still_counts(self):
        html = (
            "<html><body><main><ul>"
            f"<li><h2>First unit</h2><p>Summary text.</p><article><h1>Doors commissioned</h1>{BODY}</article></li>"
            "<li><h3>Other story</h3><p>Summary of another story from the same publisher.</p></li>"
            "</ul></main></body></html>"
        )
        self.assertIs(_assess(html).principal_document_status, AMBIGUOUS)


class RepeatedHeadlineMetadataTests(unittest.TestCase):
    def _page(self, first: str, second: str, tag: str = "title") -> str:
        if tag == "title":
            head = f"<title>{first}</title><title>{second}</title>"
        else:
            head = (
                f"<meta property='og:title' content='{first}'>"
                f"<meta property='og:title' content='{second}'>"
            )
        return f"<html><head>{head}</head><body><main><article><h1>Doors commissioned</h1>{BODY}</article></main></body></html>"

    def test_the_same_title_stated_twice_is_not_a_conflict(self):
        for tag in ("title", "meta"):
            result = _assess(self._page("Doors commissioned", "Doors commissioned", tag))
            self.assertIs(result.principal_document_status, ESTABLISHED, tag)

    def test_differing_titles_remain_a_conflict(self):
        for tag in ("title", "meta"):
            result = _assess(self._page("Doors commissioned", "Another document", tag))
            self.assertIs(result.principal_document_status, AMBIGUOUS, tag)


class InteractiveWidgetsInsideTheArticleTests(unittest.TestCase):
    WIDGETS = (
        "<div><form><h3>Newsletter</h3><label>Email</label><input type='text'>"
        "<button>Subscribe</button></form></div>"
        "<div><h3>Share</h3><div><a href='https://social.example/a'>Network</a>"
        "<a href='https://news.example/copy'>Copy</a></div></div>"
    )

    def test_a_form_and_a_share_block_are_not_competing_document_units(self):
        html = (
            "<html><head><title>t</title></head><body><main><article>"
            f"<h1>Doors commissioned</h1>{BODY}{self.WIDGETS}</article></main></body></html>"
        )
        result = _assess(html)
        self.assertIs(result.principal_document_status, ESTABLISHED)
        self.assertIn("platform screen doors", result.body_text)

    def test_two_blocks_with_prose_remain_competing_units(self):
        html = f"<html><body><main><article><div><h2>A</h2>{BODY}</div><div><h2>B</h2>{BODY}</div></article></main></body></html>"
        self.assertIs(_assess(html).principal_document_status, AMBIGUOUS)

    def test_a_block_whose_prose_follows_a_link_still_counts(self):
        unit = "<div><h2>A</h2><a href='https://social.example/a'>Link</a> and then prose of its own about doors.</div>"
        html = f"<html><body><main><article>{unit}{unit}</article></main></body></html>"
        self.assertIs(_assess(html).principal_document_status, AMBIGUOUS)


if __name__ == "__main__":
    unittest.main()
