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


RESOURCE = "https://news.example/articles/doors"


def _jsonld(identity: str) -> str:
    return (
        '<script type="application/ld+json">'
        '{"@type":"Article","datePublished":"2026-08-28","dateModified":"2026-08-29",'
        f'"mainEntityOfPage":{{"@type":"WebPage","@id":"{identity}"}}}}'
        "</script>"
    )


def _dated(body_tail: str, head_tail: str = "") -> object:
    html = (
        f"<html><head><title>t</title>{head_tail}</head><body><main><article><h1>Doors commissioned</h1>{BODY}</article></main>"
        f"{body_tail}</body></html>"
    )
    return assess_document(
        html,
        "text/html",
        resource_url=RESOURCE,
        candidate_id="c1",
        resource_identity_checker=lambda value: value == RESOURCE,
    )


class JsonLdOutsideTheHeadTests(unittest.TestCase):
    def test_a_body_level_block_that_names_this_resource_gives_date_facts(self):
        result = _dated(_jsonld(RESOURCE))
        kinds = {fact["date_kind"]: fact["raw_date_value"] for fact in result.source_date_facts}
        self.assertEqual(kinds, {"ORIGINAL_PUBLICATION": "2026-08-28", "MODIFIED": "2026-08-29"})

    def test_a_block_that_names_another_resource_gives_none(self):
        self.assertEqual(_dated(_jsonld("https://news.example/articles/other")).source_date_facts, ())

    def test_a_block_inside_an_excluded_region_gives_none(self):
        self.assertEqual(_dated(f"<aside>{_jsonld(RESOURCE)}</aside>").source_date_facts, ())
        self.assertEqual(_dated(f"<footer>{_jsonld(RESOURCE)}</footer>").source_date_facts, ())

    def test_a_head_block_is_still_read_once(self):
        result = _dated("", _jsonld(RESOURCE))
        self.assertEqual(len(result.source_date_facts), 2)


HEADLINE = "Doors commissioned on Line 2"


def _declared_page(
    *,
    entities: tuple[str, ...] | None = None,
    headline: str = f" {HEADLINE} ",
    identity: str = RESOURCE,
    h1s: tuple[str, ...] = (HEADLINE, "Related", "You may also like"),
    types: str = '"NewsArticle"',
    outside: str = "",
) -> str:
    entity = (
        f'{{"@type":{types},"headline":"{headline}",'
        f'"mainEntityOfPage":{{"@type":"WebPage","@id":"{identity}"}}}}'
    )
    blocks = "".join(
        f'<script type="application/ld+json">{item}</script>' for item in (entities if entities is not None else (entity,))
    )
    widgets = "".join(
        f"<div><h1>{text}</h1><div><a href='https://news.example/o{index}'>Other story</a></div></div>"
        for index, text in enumerate(h1s[1:])
    )
    return (
        f"<html><head><title>t</title>{blocks}</head><body>{outside}<main>"
        f"<div><h1>{h1s[0]}</h1>{BODY}</div>{widgets}</main></body></html>"
    )


def _assess_declared(html: str, *, checker: bool = True):
    return assess_document(
        html,
        "text/html",
        resource_url=RESOURCE,
        candidate_id="c1",
        resource_identity_checker=(lambda value: value == RESOURCE) if checker else None,
    )


class DeclaredDocumentHeadlineTests(unittest.TestCase):
    def test_the_declared_h1_wins_and_the_widget_headings_do_not_compete(self):
        result = _assess_declared(_declared_page())
        self.assertIs(result.principal_document_status, ESTABLISHED)
        self.assertEqual([item for item in result.document_level_headlines if item == HEADLINE], [HEADLINE])
        self.assertNotIn("Related", result.document_level_headlines)

    def test_a_type_list_that_includes_article_counts(self):
        result = _assess_declared(_declared_page(types='["WebPage","Article"]'))
        self.assertIs(result.principal_document_status, ESTABLISHED)

    def test_without_the_structured_data_it_stays_ambiguous(self):
        self.assertIs(_assess_declared(_declared_page(entities=())).principal_document_status, AMBIGUOUS)

    def test_without_an_identity_checker_it_stays_ambiguous(self):
        self.assertIs(_assess_declared(_declared_page(), checker=False).principal_document_status, AMBIGUOUS)

    def test_an_entity_that_names_another_resource_resolves_nothing(self):
        html = _declared_page(identity="https://news.example/articles/other")
        self.assertIs(_assess_declared(html).principal_document_status, AMBIGUOUS)

    def test_two_article_entities_resolve_nothing(self):
        entity = (
            f'{{"@type":"Article","headline":"{HEADLINE}",'
            f'"mainEntityOfPage":{{"@type":"WebPage","@id":"{RESOURCE}"}}}}'
        )
        other = '{"@type":"NewsArticle","headline":"Other","mainEntityOfPage":"https://news.example/other"}'
        html = _declared_page(entities=(entity, other))
        self.assertIs(_assess_declared(html).principal_document_status, AMBIGUOUS)

    def test_a_headline_that_differs_in_any_character_resolves_nothing(self):
        for headline in (HEADLINE.lower(), HEADLINE + ".", "Doors commissioned on Line 2 today"):
            html = _declared_page(headline=headline)
            self.assertIs(_assess_declared(html).principal_document_status, AMBIGUOUS, headline)

    def test_two_h1_with_the_declared_text_resolve_nothing(self):
        html = _declared_page(h1s=(HEADLINE, HEADLINE, "Related"))
        self.assertIs(_assess_declared(html).principal_document_status, AMBIGUOUS)

    def test_a_declared_h1_outside_the_principal_region_resolves_nothing(self):
        html = _declared_page(outside=f"<header><h1>{HEADLINE}</h1></header>", h1s=("Another", "Related", "More"))
        self.assertIs(_assess_declared(html).principal_document_status, AMBIGUOUS)

    def test_structured_data_in_an_excluded_region_is_ignored(self):
        entity = (
            f'{{"@type":"NewsArticle","headline":"{HEADLINE}",'
            f'"mainEntityOfPage":{{"@type":"WebPage","@id":"{RESOURCE}"}}}}'
        )
        html = _declared_page(entities=(), outside=f'<aside><script type="application/ld+json">{entity}</script></aside>')
        self.assertIs(_assess_declared(html).principal_document_status, AMBIGUOUS)

    def test_a_listing_with_declared_data_is_still_a_listing(self):
        html = (
            "<html><head><title>t</title><script type=\"application/ld+json\">"
            f'{{"@type":"NewsArticle","headline":"{HEADLINE}","mainEntityOfPage":"{RESOURCE}"}}'
            f"</script></head><body><main><h1>{HEADLINE}</h1>{_cards(4)}</main></body></html>"
        )
        self.assertIs(_assess_declared(html).principal_document_status, AMBIGUOUS)
