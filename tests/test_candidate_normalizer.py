from __future__ import annotations

from unittest import TestCase

from src.weekly_report.candidate_normalizer import CandidateNormalizationError, CandidateNormalizer
from src.weekly_report.contracts import (
    AcquisitionRecord,
    DiscoveryIntent,
    DiscoveryResult,
    GoogleNewsRssEncoding,
    RegionMode,
    SearchPlan,
    SearchPlanItem,
)


def _plan() -> SearchPlan:
    items = tuple(
        SearchPlanItem(
            f"item-{index}", "market", RegionMode.SELECTED, intent,
            "en", "family", "google_news_rss", f"query-{index}",
            GoogleNewsRssEncoding("en-US", "US", "US:en"), "en-US",
        )
        for index, intent in enumerate((DiscoveryIntent.PROCUREMENT, DiscoveryIntent.TECHNOLOGY))
    )
    return SearchPlan("search-discovery-v3", RegionMode.SELECTED, items, "plan-1")


def _record(ordinal: int = 0, *, item_index: int = 0, result: DiscoveryResult | None = None) -> AcquisitionRecord:
    plan = _plan()
    return AcquisitionRecord(
        plan.plan_id,
        plan.items[item_index],
        ordinal,
        result or DiscoveryResult("Title", "https://example.test/story", "Publisher", "2026", "Snippet"),
    )


class CandidateNormalizerTests(TestCase):
    def setUp(self) -> None:
        self.normalizer = CandidateNormalizer()

    def test_valid_acquisition_and_zero_acquisitions(self) -> None:
        result = self.normalizer.normalize((_record(),))
        self.assertEqual(len(result.normalized_candidates), 1)
        self.assertEqual(self.normalizer.normalize(()).normalized_candidates, ())

    def test_exact_duplicate_url_preserves_all_distinct_origins(self) -> None:
        first = _record(0)
        second = _record(1)
        result = self.normalizer.normalize((first, second))
        candidate = result.normalized_candidates[0]
        self.assertEqual(len(candidate.acquisition_origins), 2)
        self.assertEqual(candidate.candidate.url, first.raw_result.url)

    def test_metadata_conflict_uses_one_complete_lexicographic_tuple(self) -> None:
        first = _record(result=DiscoveryResult("z-title", "https://example.test/story", "a", "1", "a"))
        second = _record(1, result=DiscoveryResult("a-title", "https://example.test/story", "z", "2", "z"))
        candidate = self.normalizer.normalize((first, second)).normalized_candidates[0].candidate
        self.assertEqual((candidate.title, candidate.publisher, candidate.published_at, candidate.search_snippet), ("a-title", "z", "2", "z"))

    def test_multi_intent_url_is_one_candidate_with_lexicographic_intent_projection(self) -> None:
        first = _record(item_index=0)
        second = _record(item_index=1)
        candidate = self.normalizer.normalize((first, second)).normalized_candidates[0].candidate
        self.assertEqual(candidate.discovery_intent, "procurement")

    def test_same_occurrence_conflict_fails_closed(self) -> None:
        first = _record(0, result=DiscoveryResult("one", "https://example.test/one"))
        second = _record(0, result=DiscoveryResult("two", "https://example.test/two"))
        with self.assertRaises(CandidateNormalizationError) as context:
            self.normalizer.normalize((first, second))
        self.assertEqual(context.exception.failure_class.value, "INVALID_ACQUISITION")

    def test_distinct_ordinals_are_distinct_origins(self) -> None:
        first = _record(0)
        second = _record(1, result=first.raw_result)
        candidate = self.normalizer.normalize((first, second)).normalized_candidates[0]
        self.assertEqual(len(candidate.acquisition_origins), 2)

    def test_invalid_url_and_malformed_input_are_finite(self) -> None:
        for value, expected in (
            (DiscoveryResult("bad", "relative/path"), "INVALID_URL"),
            (DiscoveryResult("bad", " https://example.test "), "INVALID_URL"),
        ):
            with self.assertRaises(CandidateNormalizationError) as context:
                self.normalizer.normalize((_record(result=value),))
            self.assertEqual(context.exception.failure_class.value, expected)
        with self.assertRaises(CandidateNormalizationError) as context:
            self.normalizer.normalize(("bad",))
        self.assertEqual(context.exception.failure_class.value, "INVALID_ACQUISITION")

    def test_candidate_and_origin_order_are_deterministic_and_google_url_is_opaque(self) -> None:
        first = _record(result=DiscoveryResult("first", "https://news.google.com/rss/articles/a?b=2&a=1#x"))
        second = _record(1, result=DiscoveryResult("second", "https://example.test/other"))
        result = self.normalizer.normalize((second, first))
        ids = tuple(item.candidate.candidate_id for item in result.normalized_candidates)
        self.assertEqual(ids, tuple(sorted(ids)))
        self.assertIn(first.raw_result.url, tuple(item.candidate.url for item in result.normalized_candidates))
