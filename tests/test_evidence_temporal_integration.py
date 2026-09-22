from __future__ import annotations

import unittest
from datetime import date

from src.weekly_report.contracts import (
    CanonicalCandidate,
    EvidenceState,
    FetchedSource,
    SourceDateKind,
    TemporalDiagnostic,
)
from src.weekly_report.evidence_service import EvidenceService
from src.weekly_report.semantic_judge import JudgeMetadata
from src.weekly_report.temporal_rule import TemporalRule


class _FixtureFetcher:
    def __init__(self, source: FetchedSource) -> None:
        self.source = source

    def __call__(self, _url: str) -> FetchedSource:
        return self.source


class _SameEventJudge:
    metadata = JudgeMetadata(
        model_identifier="integration-test-model",
        prompt_version="integration-test-prompt-v1",
        schema_version="integration-test-schema-v1",
    )

    def __call__(self, request):
        body = request.principal_body_segments[0].text
        return {
            "relation": "SAME_EVENT",
            "support_spans": [
                {"segment_id": "body-0001", "start": 0, "end": len(body)}
            ],
            "conflict_spans": [],
            "explanation": "The fixture body describes the Candidate event.",
        }


def _candidate(**overrides) -> CanonicalCandidate:
    values = {
        "candidate_id": "C1",
        "title": "Metro operator commissions moving-block train control on Line 4",
        "url": "https://source.test/article/line-4-control",
        "publisher": "Fixture Publisher",
        "published_at": "2026-09-15T12:00:00Z",
        "source_type": "web_source",
    }
    values.update(overrides)
    return CanonicalCandidate(**values)


def _evidence(html: str, *, content_type: str = "text/html", **candidate_overrides):
    candidate = _candidate(**candidate_overrides)
    source = FetchedSource(
        url=candidate.url,
        content=html,
        content_type=content_type,
    )
    service = EvidenceService(
        _FixtureFetcher(source),
        semantic_judge=_SameEventJudge(),
    )
    return candidate, service.evaluate(candidate)


def _article_html(head: str = "", body: str = "The operator commissioned Line 4 after final testing.") -> str:
    return (
        f"<html><head>{head}</head><body><article>"
        "<h1>Metro operator commissions moving-block train control on Line 4</h1>"
        f"<p>{body}</p></article></body></html>"
    )


def _temporal(result, *, start: str = "2026-09-12", end: str = "2026-09-18"):
    return TemporalRule().evaluate(
        result.candidate_id,
        result.source_date_facts,
        start,
        end,
        source_type=result.source_type,
    )


class EvidenceTemporalIntegrationTests(unittest.TestCase):
    def test_unrelated_jsonld_date_is_not_promoted_or_used_by_temporal(self):
        html = _article_html(
            "<script type='application/ld+json'>"
            '{"@type":"NewsArticle","datePublished":"2020-01-01"}'
            "</script>"
        )
        _, evidence = _evidence(html)

        temporal = _temporal(evidence)

        self.assertEqual(evidence.state, EvidenceState.READY)
        self.assertEqual(evidence.source_date_facts, ())
        self.assertFalse(temporal.date_valid)
        self.assertEqual(temporal.diagnostic, TemporalDiagnostic.DATE_MISSING)

    def test_explicitly_associated_jsonld_date_is_emitted(self):
        html = _article_html(
            "<script type='application/ld+json'>"
            '{"@id":"https://source.test/article/line-4-control",'
            '"@type":"NewsArticle","datePublished":"2026-09-15"}'
            "</script>"
        )
        _, evidence = _evidence(html)

        self.assertEqual(evidence.state, EvidenceState.READY)
        self.assertEqual(len(evidence.source_date_facts), 1)
        self.assertEqual(
            evidence.source_date_facts[0].date_kind,
            SourceDateKind.ORIGINAL_PUBLICATION,
        )
        self.assertEqual(evidence.source_date_facts[0].raw_date_value, "2026-09-15")

    def test_conflicting_jsonld_id_and_url_are_not_principal_owned(self):
        html = _article_html(
            "<script type='application/ld+json'>"
            '{"@id":"https://source.test/article/line-4-control",'
            '"url":"https://source.test/article/other-story",'
            '"@type":"NewsArticle","datePublished":"2026-09-15"}'
            "</script>"
        )
        _, evidence = _evidence(html)

        self.assertEqual(evidence.state, EvidenceState.READY)
        self.assertEqual(evidence.source_date_facts, ())

    def test_conflicting_jsonld_url_array_is_not_principal_owned(self):
        html = _article_html(
            "<script type='application/ld+json'>"
            '{"@id":"https://source.test/article/line-4-control",'
            '"url":["https://source.test/article/other-story"],'
            '"@type":"NewsArticle","datePublished":"2026-09-15"}'
            "</script>"
        )
        _, evidence = _evidence(html)

        temporal = _temporal(evidence)

        self.assertEqual(evidence.state, EvidenceState.READY)
        self.assertEqual(evidence.source_date_facts, ())
        self.assertEqual(temporal.diagnostic, TemporalDiagnostic.DATE_MISSING)

    def test_conflicting_jsonld_main_entity_array_is_not_principal_owned(self):
        html = _article_html(
            "<script type='application/ld+json'>"
            '{"@id":"https://source.test/article/line-4-control",'
            '"mainEntityOfPage":[{"@id":"https://source.test/article/other-story"}],'
            '"@type":"NewsArticle","datePublished":"2026-09-15"}'
            "</script>"
        )
        _, evidence = _evidence(html)

        self.assertEqual(evidence.state, EvidenceState.READY)
        self.assertEqual(evidence.source_date_facts, ())

    def test_jsonld_array_only_identity_is_conservatively_unsupported(self):
        html = _article_html(
            "<script type='application/ld+json'>"
            '{"url":["https://source.test/article/line-4-control"],'
            '"@type":"NewsArticle","datePublished":"2026-09-15"}'
            "</script>"
        )
        _, evidence = _evidence(html)

        self.assertEqual(evidence.state, EvidenceState.READY)
        self.assertEqual(evidence.source_date_facts, ())

    def test_consistent_redundant_jsonld_identities_remain_principal_owned(self):
        html = _article_html(
            "<script type='application/ld+json'>"
            '{"@id":"https://source.test/article/line-4-control",'
            '"url":"https://source.test/article/line-4-control",'
            '"mainEntityOfPage":{"@id":"https://source.test/article/line-4-control"},'
            '"@type":"NewsArticle","headline":"Metro control project",'
            '"datePublished":"2026-09-15"}'
            "</script>"
        )
        _, evidence = _evidence(html)

        self.assertEqual(evidence.state, EvidenceState.READY)
        self.assertEqual(len(evidence.source_date_facts), 1)
        self.assertEqual(evidence.source_date_facts[0].raw_date_value, "2026-09-15")

    def test_matching_jsonld_id_with_conflicting_main_entity_is_not_owned(self):
        html = _article_html(
            "<script type='application/ld+json'>"
            '{"@id":"https://source.test/article/line-4-control",'
            '"mainEntityOfPage":{"@id":"https://source.test/article/other-story"},'
            '"@type":"NewsArticle","datePublished":"2026-09-15"}'
            "</script>"
        )
        _, evidence = _evidence(html)

        self.assertEqual(evidence.state, EvidenceState.READY)
        self.assertEqual(evidence.source_date_facts, ())

    def test_realistic_associated_newsarticle_ignores_descriptive_fields(self):
        html = _article_html(
            "<script type='application/ld+json'>"
            '{"@id":"https://source.test/article/line-4-control",'
            '"@type":"NewsArticle","headline":"Metro control project",'
            '"author":{"@type":"Organization","name":"Metro Authority"},'
            '"publisher":{"@type":"Organization","name":"Metro Authority"},'
            '"datePublished":"2026-09-15"}'
            "</script>"
        )
        _, evidence = _evidence(html)

        self.assertEqual(evidence.state, EvidenceState.READY)
        self.assertEqual(len(evidence.source_date_facts), 1)
        self.assertEqual(evidence.source_date_facts[0].raw_date_value, "2026-09-15")

    def test_rich_main_entity_of_page_jsonld_emits_publication_and_modified(self):
        html = _article_html(
            "<script type='application/ld+json'>"
            '{"@type":"NewsArticle",'
            '"mainEntityOfPage":{"@id":"https://source.test/article/line-4-control"},'
            '"headline":"Metro control project",'
            '"author":{"@type":"Organization","name":"Metro Authority"},'
            '"datePublished":"2026-09-15","dateModified":"2026-09-17"}'
            "</script>"
        )
        _, evidence = _evidence(html)

        self.assertEqual(evidence.state, EvidenceState.READY)
        self.assertEqual(
            {fact.date_kind for fact in evidence.source_date_facts},
            {SourceDateKind.ORIGINAL_PUBLICATION, SourceDateKind.MODIFIED},
        )

    def test_explicitly_unrelated_jsonld_date_is_not_emitted(self):
        html = _article_html(
            "<script type='application/ld+json'>"
            '{"@id":"https://source.test/article/other-story",'
            '"@type":"NewsArticle","datePublished":"2020-01-01"}'
            "</script>"
        )
        _, evidence = _evidence(html)

        temporal = _temporal(evidence)

        self.assertEqual(evidence.state, EvidenceState.READY)
        self.assertEqual(evidence.source_date_facts, ())
        self.assertEqual(temporal.diagnostic, TemporalDiagnostic.DATE_MISSING)

    def test_unrelated_rich_jsonld_is_rejected_by_resource_identity(self):
        html = _article_html(
            "<script type='application/ld+json'>"
            '{"@id":"https://source.test/article/other-story",'
            '"@type":"NewsArticle","headline":"Other story",'
            '"author":{"@type":"Organization","name":"Metro Authority"},'
            '"publisher":{"@type":"Organization","name":"Metro Authority"},'
            '"datePublished":"2020-01-01"}'
            "</script>"
        )
        _, evidence = _evidence(html)

        self.assertEqual(evidence.state, EvidenceState.READY)
        self.assertEqual(evidence.source_date_facts, ())

    def test_nested_foreign_jsonld_date_is_not_crawled(self):
        html = _article_html(
            "<script type='application/ld+json'>"
            '{"@id":"https://source.test/article/line-4-control",'
            '"@type":"NewsArticle",'
            '"author":{"@type":"Person","datePublished":"2020-01-01"},'
            '"datePublished":"2026-09-15"}'
            "</script>"
        )
        _, evidence = _evidence(html)

        self.assertEqual(evidence.state, EvidenceState.READY)
        self.assertEqual(len(evidence.source_date_facts), 1)
        self.assertEqual(evidence.source_date_facts[0].raw_date_value, "2026-09-15")

    def test_associated_plus_unrelated_jsonld_graph_keeps_only_associated_date(self):
        html = _article_html(
            "<script type='application/ld+json'>"
            '{"@graph":[{"@id":"https://source.test/article/line-4-control",'
            '"@type":"NewsArticle","headline":"Metro control project",'
            '"datePublished":"2026-09-15"},'
            '{"@id":"https://source.test/article/other-story",'
            '"@type":"NewsArticle","headline":"Other story",'
            '"datePublished":"2020-01-01"}]}'
            "</script>"
        )
        _, evidence = _evidence(html)

        self.assertEqual(evidence.state, EvidenceState.READY)
        self.assertEqual(len(evidence.source_date_facts), 1)
        self.assertEqual(evidence.source_date_facts[0].raw_date_value, "2026-09-15")

    def test_multi_entity_jsonld_does_not_create_false_temporal_conflict(self):
        html = _article_html(
            "<script type='application/ld+json'>"
            '{"@graph":[{"@type":"NewsArticle","datePublished":"2026-09-15"},'
            '{"@type":"NewsArticle","datePublished":"2020-01-01"}]}'
            "</script>"
        )
        _, evidence = _evidence(html)

        temporal = _temporal(evidence)

        self.assertEqual(evidence.state, EvidenceState.READY)
        self.assertEqual(evidence.source_date_facts, ())
        self.assertFalse(temporal.date_valid)
        self.assertEqual(temporal.diagnostic, TemporalDiagnostic.DATE_MISSING)

    def test_valid_publication_flows_directly_with_timezone_preserved(self):
        raw_value = "2026-09-15T09:30:00+09:00"
        _, evidence = _evidence(
            _article_html(
                f"<meta property='article:published_time' content='{raw_value}'>"
            )
        )

        temporal = _temporal(evidence)

        self.assertEqual(evidence.state, EvidenceState.READY)
        self.assertEqual(len(evidence.source_date_facts), 1)
        self.assertEqual(
            evidence.source_date_facts[0].date_kind,
            SourceDateKind.ORIGINAL_PUBLICATION,
        )
        self.assertEqual(evidence.source_date_facts[0].raw_date_value, raw_value)
        self.assertEqual(evidence.source_date_facts[0].explicit_timezone_or_offset, "+09:00")
        self.assertTrue(temporal.date_valid)
        self.assertEqual(temporal.diagnostic, TemporalDiagnostic.NONE)
        self.assertEqual(temporal.controlling_calendar_date, date(2026, 9, 15))

    def test_out_of_range_publication_is_not_rescued(self):
        _, evidence = _evidence(
            _article_html(
                "<meta property='article:published_time' content='2026-09-01'>"
            )
        )

        temporal = _temporal(evidence)

        self.assertEqual(evidence.state, EvidenceState.READY)
        self.assertFalse(temporal.date_valid)
        self.assertEqual(temporal.diagnostic, TemporalDiagnostic.OUT_OF_RANGE)
        self.assertEqual(temporal.controlling_calendar_date, date(2026, 9, 1))

    def test_publication_and_modified_use_temporal_publication_precedence(self):
        _, evidence = _evidence(
            _article_html(
                "<meta property='article:published_time' content='2026-09-01'>"
                "<meta property='article:modified_time' content='2026-09-15'>"
            )
        )

        temporal = _temporal(evidence)

        self.assertEqual(evidence.state, EvidenceState.READY)
        self.assertEqual(
            {fact.date_kind for fact in evidence.source_date_facts},
            {SourceDateKind.ORIGINAL_PUBLICATION, SourceDateKind.MODIFIED},
        )
        self.assertFalse(temporal.date_valid)
        self.assertEqual(temporal.diagnostic, TemporalDiagnostic.OUT_OF_RANGE)
        self.assertEqual(temporal.controlling_date_kind, SourceDateKind.ORIGINAL_PUBLICATION)
        self.assertEqual(temporal.controlling_calendar_date, date(2026, 9, 1))

    def test_missing_source_date_does_not_use_candidate_published_at(self):
        candidate, evidence = _evidence(_article_html(), published_at="2026-09-15T12:00:00Z")

        temporal = _temporal(evidence)

        self.assertEqual(candidate.published_at, "2026-09-15T12:00:00Z")
        self.assertEqual(evidence.state, EvidenceState.READY)
        self.assertEqual(evidence.source_date_facts, ())
        self.assertFalse(temporal.date_valid)
        self.assertEqual(temporal.diagnostic, TemporalDiagnostic.DATE_MISSING)

    def test_unparseable_structured_date_reaches_temporal_unchanged(self):
        raw_value = "September ?? 2026"
        _, evidence = _evidence(
            _article_html(
                "<script type='application/ld+json'>"
                f'{{"@id":"https://source.test/article/line-4-control",'
                f'"@type":"NewsArticle","datePublished":"{raw_value}"}}'
                "</script>"
            )
        )

        temporal = _temporal(evidence)

        self.assertEqual(evidence.state, EvidenceState.READY)
        self.assertEqual(evidence.source_date_facts[0].raw_date_value, raw_value)
        self.assertFalse(temporal.date_valid)
        self.assertEqual(temporal.diagnostic, TemporalDiagnostic.DATE_UNPARSEABLE)

    def test_rejected_evidence_stops_before_temporal_semantics(self):
        _, evidence = _evidence(
            "<html><head><meta property='article:published_time' content='2026-09-15'>"
            "</head><body></body></html>"
        )

        self.assertEqual(evidence.state, EvidenceState.REJECTED)
        self.assertEqual(evidence.source_date_facts, ())

    def test_excluded_template_date_cannot_make_temporal_valid(self):
        html = _article_html(
            "<template><meta property='article:published_time' "
            "content='2026-09-15'></template>"
        )
        _, evidence = _evidence(html)

        temporal = _temporal(evidence)

        self.assertEqual(evidence.state, EvidenceState.READY)
        self.assertEqual(evidence.source_date_facts, ())
        self.assertFalse(temporal.date_valid)
        self.assertEqual(temporal.diagnostic, TemporalDiagnostic.DATE_MISSING)

    def test_subordinate_only_date_cannot_make_temporal_valid(self):
        html = (
            "<notice><article><p>Metro operator commissioned Line 4 after "
            "final testing.</p><article><head><meta "
            "property='article:published_time' content='2026-09-15' />"
            "</head><p>Subordinate event body.</p></article></article>"
            "</notice>"
        )
        _, evidence = _evidence(html, content_type="application/xml")

        temporal = _temporal(evidence)

        self.assertEqual(evidence.state, EvidenceState.READY)
        self.assertEqual(evidence.source_date_facts, ())
        self.assertFalse(temporal.date_valid)
        self.assertEqual(temporal.diagnostic, TemporalDiagnostic.DATE_MISSING)

    def test_principal_date_survives_subordinate_conflicting_date(self):
        html = (
            "<notice><head><meta property='article:published_time' "
            "content='2026-09-15' /></head><article><p>Metro operator "
            "commissioned Line 4 after final testing.</p><article><head>"
            "<meta property='article:published_time' content='2020-01-01' />"
            "</head><p>Subordinate event body.</p></article></article>"
            "</notice>"
        )
        _, evidence = _evidence(html, content_type="application/xml")

        temporal = _temporal(evidence)

        self.assertEqual(evidence.state, EvidenceState.READY)
        self.assertEqual(
            [(fact.raw_date_value, fact.date_kind) for fact in evidence.source_date_facts],
            [("2026-09-15", SourceDateKind.ORIGINAL_PUBLICATION)],
        )
        self.assertTrue(temporal.date_valid)
        self.assertEqual(temporal.diagnostic, TemporalDiagnostic.NONE)
        self.assertEqual(temporal.controlling_calendar_date, date(2026, 9, 15))

    def test_exact_principal_head_subordinate_date_is_missing(self):
        html = (
            "<notice><article><head><article><meta "
            "property='article:published_time' content='2026-09-15' />"
            "</article></head><p>Metro operator commissioned Line 4 after "
            "final testing.</p></article></notice>"
        )
        _, evidence = _evidence(html, content_type="application/xml")

        temporal = _temporal(evidence)

        self.assertEqual(evidence.state, EvidenceState.READY)
        self.assertEqual(evidence.source_date_facts, ())
        self.assertFalse(temporal.date_valid)
        self.assertEqual(temporal.diagnostic, TemporalDiagnostic.DATE_MISSING)

    def test_exact_principal_date_survives_subordinate_conflicting_date(self):
        html = (
            "<notice><article><head><meta "
            "property='article:published_time' content='2026-09-15' />"
            "<article><meta property='article:published_time' "
            "content='2020-01-01' /></article></head><p>Metro operator "
            "commissioned Line 4 after final testing.</p></article></notice>"
        )
        _, evidence = _evidence(html, content_type="application/xml")

        temporal = _temporal(evidence)

        self.assertEqual(evidence.state, EvidenceState.READY)
        self.assertEqual(
            [(fact.raw_date_value, fact.date_kind) for fact in evidence.source_date_facts],
            [("2026-09-15", SourceDateKind.ORIGINAL_PUBLICATION)],
        )
        self.assertTrue(temporal.date_valid)
        self.assertEqual(temporal.diagnostic, TemporalDiagnostic.NONE)
        self.assertEqual(temporal.controlling_calendar_date, date(2026, 9, 15))

    def test_p01_detached_meta_is_missing_for_temporal(self):
        html = (
            "<notice><section><head><meta property='article:published_time' "
            "content='2026-09-15' /></head></section><article><p>Principal "
            "metro event body.</p></article></notice>"
        )
        _, evidence = _evidence(html, content_type="application/xml")

        temporal = _temporal(evidence)

        self.assertEqual(evidence.state, EvidenceState.READY)
        self.assertEqual(evidence.source_date_facts, ())
        self.assertFalse(temporal.date_valid)
        self.assertEqual(temporal.diagnostic, TemporalDiagnostic.DATE_MISSING)

    def test_p01_detached_jsonld_is_missing_for_temporal(self):
        html = (
            "<notice><section><head><script type='application/ld+json'>"
            "{&quot;@id&quot;:&quot;https://source.test/article/line-4-control&quot;,"
            "&quot;datePublished&quot;:&quot;2026-09-15&quot;}</script>"
            "</head></section><article><p>Principal metro event body."
            "</p></article></notice>"
        )
        _, evidence = _evidence(html, content_type="application/xml")

        temporal = _temporal(evidence)

        self.assertEqual(evidence.state, EvidenceState.READY)
        self.assertEqual(evidence.source_date_facts, ())
        self.assertFalse(temporal.date_valid)
        self.assertEqual(temporal.diagnostic, TemporalDiagnostic.DATE_MISSING)

    def test_p01_principal_date_survives_detached_conflicting_meta(self):
        html = (
            "<notice><head><meta property='article:published_time' "
            "content='2026-09-15' /></head><section><head><meta "
            "property='article:published_time' content='2020-01-01' />"
            "</head></section><article><p>Principal metro event body."
            "</p></article></notice>"
        )
        _, evidence = _evidence(html, content_type="application/xml")

        temporal = _temporal(evidence)

        self.assertEqual(evidence.state, EvidenceState.READY)
        self.assertEqual(
            [(fact.raw_date_value, fact.date_kind) for fact in evidence.source_date_facts],
            [("2026-09-15", SourceDateKind.ORIGINAL_PUBLICATION)],
        )
        self.assertTrue(temporal.date_valid)
        self.assertEqual(temporal.diagnostic, TemporalDiagnostic.NONE)
        self.assertEqual(temporal.controlling_calendar_date, date(2026, 9, 15))

    def test_p01_principal_date_survives_detached_conflicting_jsonld(self):
        html = (
            "<notice><head><script type='application/ld+json'>"
            "{&quot;@id&quot;:&quot;https://source.test/article/line-4-control&quot;,"
            "&quot;datePublished&quot;:&quot;2026-09-15&quot;}</script></head>"
            "<section><head><script type='application/ld+json'>"
            "{&quot;@id&quot;:&quot;https://source.test/article/line-4-control&quot;,"
            "&quot;datePublished&quot;:&quot;2020-01-01&quot;}</script></head>"
            "</section><article><p>Principal metro event body.</p></article>"
            "</notice>"
        )
        _, evidence = _evidence(html, content_type="application/xml")

        temporal = _temporal(evidence)

        self.assertEqual(evidence.state, EvidenceState.READY)
        self.assertEqual(
            [(fact.raw_date_value, fact.date_kind) for fact in evidence.source_date_facts],
            [("2026-09-15", SourceDateKind.ORIGINAL_PUBLICATION)],
        )
        self.assertTrue(temporal.date_valid)
        self.assertEqual(temporal.diagnostic, TemporalDiagnostic.NONE)
        self.assertEqual(temporal.controlling_calendar_date, date(2026, 9, 15))


if __name__ == "__main__":
    unittest.main()
