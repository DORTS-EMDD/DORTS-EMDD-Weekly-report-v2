"""Deterministic owner tests for the V2 Evidence boundary."""

from __future__ import annotations

import copy
import unittest

from src.weekly_report.contracts import (
    CanonicalCandidate,
    EvidenceState,
    FetchedSource,
    RejectReason,
)
from src.weekly_report.evidence_service import EvidenceService


def _candidate(**overrides) -> CanonicalCandidate:
    values = {
        "candidate_id": "C1",
        "title": "Metro operator commissions moving-block train control on Line 4",
        "url": "https://source.test/article/line-4-control",
        "publisher": "Fixture Publisher",
        "published_at": "2026-09-15T10:00:00Z",
        "discovery_intent": "technology",
        "search_snippet": "The metro commissioned a new train-control system.",
    }
    values.update(overrides)
    return CanonicalCandidate(**values)


class _FixtureFetcher:
    def __init__(self, source_or_error):
        self.source_or_error = source_or_error
        self.calls = []

    def __call__(self, url: str):
        self.calls.append(url)
        if isinstance(self.source_or_error, BaseException):
            raise self.source_or_error
        return self.source_or_error


def _service(html: str, *, url: str | None = None, content_type: str = "text/html"):
    source = FetchedSource(
        url=url or "https://source.test/article/line-4-control",
        content=html,
        content_type=content_type,
    )
    return EvidenceService(_FixtureFetcher(source))


class EvidenceContractTests(unittest.TestCase):
    def test_g01_title_only_is_rejected_without_downstream_fields(self):
        service = _service("<html><head><title>Metro operator commissions Line 4</title></head><body></body></html>")

        result = service.evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.TITLE_ONLY)
        self.assertEqual(result.substantive_content, "")

    def test_meta_description_only_is_not_substantive(self):
        service = _service(
            "<html><head><meta name='description' content='Metro operator commissions Line 4'></head>"
            "<body><nav>Home News Contact</nav></body></html>"
        )

        result = service.evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.INSUFFICIENT_SUBSTANCE)

    def test_search_snippet_only_cannot_be_promoted(self):
        service = _service("<html><head></head><body><nav>Search results</nav></body></html>")

        result = service.evaluate(_candidate(search_snippet="Metro operator commissions Line 4"))

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.TITLE_ONLY)

    def test_g02_homepage_is_wrong_landing_page(self):
        service = _service(
            "<html><body><nav>Home News Projects Contact</nav><main>Welcome to the operator.</main></body></html>",
            url="https://source.test/",
        )

        result = service.evaluate(_candidate(url="https://source.test/"))

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.SOURCE_PAGE_MISMATCH)

    def test_g18_search_navigation_shell_is_rejected(self):
        service = _service(
            "<html><body><nav>Home Search Results Categories Contact</nav></body></html>",
            url="https://source.test/search?q=line4",
        )

        result = service.evaluate(_candidate(url="https://source.test/search?q=line4"))

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.SOURCE_PAGE_MISMATCH)

    def test_unavailable_content_is_rejected(self):
        service = EvidenceService(_FixtureFetcher(RuntimeError("connection failed")))

        result = service.evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.CONTENT_UNAVAILABLE)

    def test_g03_article_body_is_ready_and_uses_canonical_url(self):
        html = (
            "<html><head><link rel='canonical' href='/article/line-4-control'></head>"
            "<body><article><p>Metro operator commissioned a moving-block train control system "
            "on Line 4 after integration testing was completed in September 2026.</p></article></body></html>"
        )
        service = _service(html)

        result = service.evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertIsNone(result.reject_reason)
        self.assertEqual(result.canonical_source_url, "https://source.test/article/line-4-control")
        self.assertIn("moving-block train control", result.substantive_content)
        self.assertTrue(result.provenance["source_to_candidate_match"])
        self.assertTrue(result.provenance["factual_substance"])

    def test_g10_structured_procurement_notice_is_ready(self):
        html = (
            "<html><body><main><p>The metro authority awarded a signalling replacement contract "
            "to Transit Systems for Line 2. The procurement notice lists the contractor, delivery "
            "milestones, and award date in September 2026.</p></main></body></html>"
        )
        service = _service(html, url="https://source.test/notices/line-2-award")

        result = service.evaluate(
            _candidate(
                title="Metro authority awards signalling replacement contract for Line 2",
                url="https://source.test/notices/line-2-award",
                discovery_intent="procurement",
                source_type="official_notice",
            )
        )

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(result.source_type, "official_notice")

    def test_g06_major_technical_incident_body_is_ready(self):
        html = (
            "<html><body><article><p>A metro traction-power fault caused smoke at Central Station "
            "and suspended Line 2 during the morning peak. The operator isolated the substation "
            "and restored service after inspection in September 2026.</p></article></body></html>"
        )
        service = _service(html, url="https://source.test/incidents/traction-power-fault")

        result = service.evaluate(
            _candidate(
                title="Metro traction-power fault suspends Line 2",
                url="https://source.test/incidents/traction-power-fault",
                discovery_intent="major incident",
            )
        )

        self.assertEqual(result.state, EvidenceState.READY)

    def test_g11_innovative_procurement_notice_is_ready(self):
        html = (
            "<html><body><main><p>The metro issued a procurement for a pilot wayside energy-storage "
            "system to recover braking energy. The notice describes the storage chemistry, test site, "
            "trial objectives, and measurement plan for September 2026.</p></main></body></html>"
        )
        service = _service(html, url="https://source.test/notices/energy-storage-pilot")

        result = service.evaluate(
            _candidate(
                title="Metro procures pilot wayside energy-storage system",
                url="https://source.test/notices/energy-storage-pilot",
                discovery_intent="procurement",
                source_type="official_notice",
            )
        )

        self.assertEqual(result.state, EvidenceState.READY)

    def test_high_title_overlap_with_broken_provenance_is_rejected(self):
        html = (
            "<html><body><h1>Metro operator commissions moving-block train control on Line 4</h1>"
            "<article><p>Metro operator commissioned a moving-block train control system on Line 4 "
            "after integration testing was completed in September 2026.</p></article></body></html>"
        )
        service = _service(html, url="https://source.test/article/unrelated")

        result = service.evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.SOURCE_PAGE_MISMATCH)
        self.assertFalse(result.provenance["source_provenance"])

    def test_valid_provenance_with_unrelated_event_identity_is_rejected(self):
        html = (
            "<html><body><h1>Metro operator commissions moving-block train control on Line 5</h1>"
            "<article><p>Metro operator commissioned the moving-block train control system on Line 5 "
            "after integration testing was completed in September 2026.</p></article></body></html>"
        )
        service = _service(html)

        result = service.evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.SOURCE_PAGE_MISMATCH)
        self.assertTrue(result.provenance["source_provenance"])
        self.assertFalse(result.provenance["page_event_identity"])

    def test_generic_urban_rail_overlap_does_not_establish_identity(self):
        html = (
            "<html><body><article><p>The metro operator completed a project at a station on the line. "
            "The system entered service after testing in 2026.</p></article></body></html>"
        )
        service = _service(html)

        result = service.evaluate(
            _candidate(title="Metro line station system project")
        )

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.SOURCE_PAGE_MISMATCH)
        self.assertFalse(result.provenance["page_event_identity"])

    def test_resolved_article_with_provenance_and_event_identity_is_ready(self):
        candidate_url = "https://source.test/news/line-4-control?tracking=1"
        resolved_url = "https://source.test/article/line-4-control"
        html = (
            "<html><head><link rel='canonical' href='/article/line-4-control'></head>"
            "<body><h1>Metro operator commissions moving-block train control on Line 4</h1>"
            "<article><p>Metro operator commissioned a moving-block train control system on Line 4 "
            "after integration testing was completed in September 2026.</p></article></body></html>"
        )
        source = FetchedSource(
            url=resolved_url,
            content=html,
            redirect_chain=(candidate_url, resolved_url),
        )
        service = EvidenceService(_FixtureFetcher(source))

        result = service.evaluate(_candidate(url=candidate_url))

        self.assertEqual(result.state, EvidenceState.READY)
        self.assertEqual(result.canonical_source_url, resolved_url)
        self.assertTrue(result.provenance["source_provenance"])
        self.assertTrue(result.provenance["page_event_identity"])

    def test_source_to_candidate_mismatch_is_rejected(self):
        html = (
            "<html><body><article><p>The airport authority opened a new bus terminal "
            "after construction finished in 2026. The project serves regional passengers.</p></article></body></html>"
        )
        service = _service(html, url="https://source.test/article/unrelated")

        result = service.evaluate(_candidate(url="https://source.test/article/unrelated"))

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.SOURCE_PAGE_MISMATCH)
        self.assertFalse(result.provenance["source_to_candidate_match"])

    def test_candidate_is_not_mutated_and_snippet_is_not_runtime_evidence(self):
        candidate = _candidate()
        before = copy.deepcopy(candidate)
        service = _service(
            "<html><body><article><p>Metro operator commissioned a moving-block train control system "
            "on Line 4 after testing in September 2026.</p></article></body></html>"
        )

        result = service.evaluate(candidate)

        self.assertEqual(candidate, before)
        self.assertNotIn(candidate.search_snippet, result.substantive_content)

    def test_non_textual_content_is_unavailable(self):
        service = _service("binary payload", content_type="application/pdf")

        result = service.evaluate(_candidate())

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.CONTENT_UNAVAILABLE)

    def test_invalid_candidate_url_is_unresolved_without_fetch(self):
        fetcher = _FixtureFetcher(FetchedSource(url="", content=""))
        service = EvidenceService(fetcher)

        result = service.evaluate(_candidate(url="not-a-url"))

        self.assertEqual(result.state, EvidenceState.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.URL_UNRESOLVED)
        self.assertEqual(fetcher.calls, [])


if __name__ == "__main__":
    unittest.main()
