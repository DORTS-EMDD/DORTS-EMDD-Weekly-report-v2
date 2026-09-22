"""Contract tests for the deterministic Candidate-stage Temporal owner."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.weekly_report.contracts import (
    ScopeResult,
    ScopeState,
    SourceDateFact,
    SourceDateKind,
    TemporalDiagnostic,
)
from src.weekly_report.temporal_rule import TemporalRule


ROOT = Path(__file__).resolve().parents[1]


def _fact(
    raw: str,
    kind: SourceDateKind | str,
    *,
    candidate_id: str = "C1",
    provenance: str = "source_content.publication_date",
    offset: str | None = "Z",
) -> SourceDateFact:
    return SourceDateFact(
        raw_date_value=raw,
        date_kind=kind,
        principal_document_association=candidate_id,
        source_node_or_field_provenance=provenance,
        explicit_timezone_or_offset=offset,
    )


class TemporalRuleTests(unittest.TestCase):
    def setUp(self):
        self.rule = TemporalRule()

    def test_inclusive_boundaries_and_source_calendar_date(self):
        start = self.rule.evaluate(
            "C1",
            [_fact("2026-09-12", SourceDateKind.ORIGINAL_PUBLICATION)],
            "2026-09-12",
            "2026-09-18",
        )
        end = self.rule.evaluate(
            "C1",
            [_fact("2026-09-18", SourceDateKind.NOTICE_PUBLISHED)],
            "2026-09-12",
            "2026-09-18",
        )
        offset = self.rule.evaluate(
            "C1",
            [_fact("2026-09-11T23:30:00-05:00", SourceDateKind.ORIGINAL_PUBLICATION, offset="-05:00")],
            "2026-09-12",
            "2026-09-18",
        )
        self.assertTrue(start.date_valid)
        self.assertTrue(end.date_valid)
        self.assertEqual(offset.controlling_calendar_date.isoformat(), "2026-09-11")
        self.assertEqual(offset.diagnostic, TemporalDiagnostic.OUT_OF_RANGE)

    def test_precedence_does_not_rescue_old_publication(self):
        for kind, raw in (
            (SourceDateKind.MODIFIED, "2026-09-17"),
            (SourceDateKind.EVENT_DATE, "2026-09-17"),
            (SourceDateKind.DEADLINE, "2026-09-18"),
        ):
            result = self.rule.evaluate(
                "C1",
                [
                    _fact("2026-09-01", SourceDateKind.ORIGINAL_PUBLICATION),
                    _fact(raw, kind),
                ],
                "2026-09-12",
                "2026-09-18",
            )
            self.assertFalse(result.date_valid)
            self.assertEqual(result.diagnostic, TemporalDiagnostic.OUT_OF_RANGE)
            self.assertEqual(result.controlling_date_kind, SourceDateKind.ORIGINAL_PUBLICATION)

    def test_notice_publication_precedes_notice_issued(self):
        result = self.rule.evaluate(
            "C1",
            [
                _fact("2026-09-01", SourceDateKind.NOTICE_ISSUED),
                _fact("2026-09-15", SourceDateKind.NOTICE_PUBLISHED),
            ],
            "2026-09-12",
            "2026-09-18",
            source_type="government_notice",
        )
        self.assertTrue(result.date_valid)
        self.assertEqual(result.controlling_date_kind, SourceDateKind.NOTICE_PUBLISHED)

    def test_news_publication_beats_notice_like_fact(self):
        result = self.rule.evaluate(
            "C1",
            [
                _fact("2026-09-15", SourceDateKind.ORIGINAL_PUBLICATION),
                _fact("2026-09-01", SourceDateKind.NOTICE_PUBLISHED),
            ],
            "2026-09-12",
            "2026-09-18",
            source_type="news/article",
        )
        self.assertTrue(result.date_valid)
        self.assertEqual(result.controlling_calendar_date.isoformat(), "2026-09-15")
        self.assertEqual(result.controlling_date_kind, SourceDateKind.ORIGINAL_PUBLICATION)

    def test_notice_without_publication_uses_issued_date(self):
        result = self.rule.evaluate(
            "C1",
            [_fact("2026-09-15", SourceDateKind.NOTICE_ISSUED)],
            "2026-09-12",
            "2026-09-18",
            source_type="procurement_notice",
        )
        self.assertTrue(result.date_valid)
        self.assertEqual(result.controlling_date_kind, SourceDateKind.NOTICE_ISSUED)

    def test_missing_discovery_only_and_invalid_provenance_are_distinct(self):
        missing = self.rule.evaluate("C1", [], "2026-09-12", "2026-09-18")
        discovery_only = self.rule.evaluate(
            "C1", [], "2026-09-12", "2026-09-18", discovery_published_at="2026-09-15T12:00:00Z"
        )
        invalid = self.rule.evaluate(
            "C1",
            [_fact("2026-09-15", SourceDateKind.MODIFIED)],
            "2026-09-12",
            "2026-09-18",
        )
        self.assertEqual(missing.diagnostic, TemporalDiagnostic.DATE_MISSING)
        self.assertEqual(discovery_only.diagnostic, TemporalDiagnostic.DATE_PROVENANCE_INVALID)
        self.assertEqual(invalid.diagnostic, TemporalDiagnostic.DATE_PROVENANCE_INVALID)

    def test_unparseable_and_same_kind_conflict_are_conservative(self):
        unparseable = self.rule.evaluate(
            "C1",
            [_fact("not-a-date", SourceDateKind.ORIGINAL_PUBLICATION)],
            "2026-09-12",
            "2026-09-18",
        )
        conflict = self.rule.evaluate(
            "C1",
            [
                _fact("2026-09-15", SourceDateKind.ORIGINAL_PUBLICATION),
                _fact("2026-09-16", SourceDateKind.ORIGINAL_PUBLICATION),
            ],
            "2026-09-12",
            "2026-09-18",
        )
        self.assertEqual(unparseable.diagnostic, TemporalDiagnostic.DATE_UNPARSEABLE)
        self.assertEqual(conflict.diagnostic, TemporalDiagnostic.DATE_CONFLICT)

    def test_wrong_scope_cannot_invoke_temporal(self):
        with self.assertRaises(ValueError):
            self.rule.evaluate(
                "C1",
                [_fact("2026-09-15", SourceDateKind.ORIGINAL_PUBLICATION)],
                "2026-09-12",
                "2026-09-18",
                scope_result=ScopeResult("C1", ScopeState.OUT_OF_SCOPE),
            )

    def test_golden_temporal_cases(self):
        manifest = json.loads((ROOT / "golden/manifest.json").read_text(encoding="utf-8"))
        for entry in manifest["cases"]:
            number = int(entry["case_id"][1:])
            if not 36 <= number <= 48:
                continue
            fixture = json.loads((ROOT / "golden" / entry["file"]).read_text(encoding="utf-8"))
            candidate = fixture["candidates"][0]
            result = self.rule.evaluate(
                candidate["candidate_id"],
                candidate.get("source_date_facts", []),
                fixture["run_context"]["period_start"],
                fixture["run_context"]["period_end"],
                source_type=candidate.get("source_type", ""),
                discovery_published_at=candidate.get("published_at", ""),
                scope_result=ScopeResult(candidate["candidate_id"], ScopeState.IN_SCOPE),
            )
            expected = fixture["expected"]
            self.assertEqual(result.date_valid, expected["date_valid"], entry["case_id"])
            self.assertEqual(result.diagnostic.value, expected["temporal_diagnostic"], entry["case_id"])

    def test_existing_temporal_fixtures_use_source_facts_not_discovery_dates(self):
        manifest = json.loads((ROOT / "golden/manifest.json").read_text(encoding="utf-8"))
        existing_ids = set(
            [*(f"G{i:02d}" for i in range(3, 14)), *(f"G{i:02d}" for i in range(15, 18)), *(f"G{i:02d}" for i in range(19, 22))]
        )
        for entry in manifest["cases"]:
            if entry["case_id"] not in existing_ids:
                continue
            fixture = json.loads((ROOT / "golden" / entry["file"]).read_text(encoding="utf-8"))
            for candidate in fixture["candidates"]:
                result = self.rule.evaluate(
                    candidate["candidate_id"],
                    candidate["source_date_facts"],
                    fixture["run_context"]["period_start"],
                    fixture["run_context"]["period_end"],
                    discovery_published_at=candidate.get("published_at", ""),
                    scope_result=ScopeResult(candidate["candidate_id"], ScopeState.IN_SCOPE),
                )
                self.assertEqual(result.date_valid, fixture["expected"]["date_valid"], entry["case_id"])


if __name__ == "__main__":
    unittest.main()
