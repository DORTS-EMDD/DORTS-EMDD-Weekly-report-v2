"""RC-85 (section A.66): two structural boundaries of the principal-document assessment.

1. Article elements on the path from the principal article to its single
   declared schema.org articleBody wrap the principal's own body (철도경제신문
   redaily.co.kr nests ``article.wrapper > article.grid > article[itemprop=articleBody]``;
   Runs 44919705575 and 45103217994 ended at INSUFFICIENT_SUBSTANCE with an empty body).
2. A main region without any text does not compete as the principal region.

The fixtures reproduce the probed tag structure with synthetic text; the public
repository holds no source article.
"""

from __future__ import annotations

from src.weekly_report.evidence_document import PrincipalDocumentStatus, assess_document

URL = "https://news.example.test/articleView.html?idxno=1"
BODY = (
    "<p>The research institute developed a vehicle-mounted rail image inspection device.</p>"
    "<p>A line-scan camera on a service train records the rail head continuously while it runs.</p>"
    "<p>Software detects corrugation and gives its position and wavelength automatically.</p>"
)


def _nested(body_attrs: str = 'itemprop="articleBody"', second_body: str = "") -> str:
    return f"""<html><head><title>Rail image inspection</title></head><body>
<header><nav><a href="/">Home</a></nav></header>
<article class="view-header"><h1>Rail image inspection for metro trains</h1></article>
<article class="byline"><p>Reporter Kim</p></article>
<article class="wrapper">
  <section class="article-view-content">
    <article class="grid body">
      <aside><a href="/other">Other news</a></aside>
      <section class="article-body">
        <h2>Small, light, always-on inspection</h2>
        <article id="article-view-content-div" {body_attrs}>{BODY}</article>
        {second_body}
      </section>
    </article>
  </section>
</article>
<footer><p>Copyright</p></footer>
</body></html>"""


def _assess(html: str):
    return assess_document(html, "text/html; charset=utf-8", resource_url=URL, candidate_id="C1")


def test_articles_on_the_path_to_the_single_article_body_are_not_subordinate():
    assessment = _assess(_nested())
    assert assessment.principal_document_status is PrincipalDocumentStatus.PRINCIPAL_DOCUMENT_ESTABLISHED
    assert "line-scan camera on a service train" in assessment.body_text
    assert "corrugation" in assessment.body_text


def test_without_a_unique_article_body_nested_articles_stay_subordinate():
    # Structure only: no declaration, or two of them, gives no path exception.
    for html in (_nested(body_attrs=""), _nested(second_body='<article itemprop="articleBody"><p>Second body.</p></article>')):
        assessment = _assess(html)
        assert "line-scan camera" not in assessment.body_text


def _two_mains(first: str) -> str:
    return f"""<html><body>
<main class="shell">{first}</main>
<main><article><h1>Tram line closes for works</h1>
<p>The operator closes the tram line between two stops this weekend.</p>
<p>Replacement buses serve the closed section.</p></article></main>
</body></html>"""


def test_an_empty_main_does_not_compete():
    assessment = _assess(_two_mains(""))
    assert assessment.principal_document_status is PrincipalDocumentStatus.PRINCIPAL_DOCUMENT_ESTABLISHED
    assert "Replacement buses" in assessment.body_text


def test_two_mains_with_text_stay_ambiguous():
    assessment = _assess(_two_mains("<p>Other text.</p>"))
    assert assessment.principal_document_status is PrincipalDocumentStatus.PRINCIPAL_DOCUMENT_AMBIGUOUS
