from __future__ import annotations

from unittest import TestCase

from src.weekly_report.report_service import ReportService
from src.weekly_report.validator import ValidationPopulationError, Validator
from src.weekly_report.writer import WriterReportBlock

from test_report_service import _workflow_result


def _metadata(result):
    return ReportService().project_formal_metadata((result,))[0]


def _block(event_id: str, *, summary: str = "Taiwan Metro") -> WriterReportBlock:
    return WriterReportBlock(
        event_id,
        "事件標題",
        f"事件摘要 {summary}",
        "可供臺北捷運評估相關規劃方向",
    )


class ValidatorTests(TestCase):
    def test_valid_event_passes_and_preserves_reference(self) -> None:
        result = _workflow_result("E1")
        validation = Validator().validate((result,), (_metadata(result),), (_block("E1"),))
        self.assertEqual(validation.pass_count, 1)
        self.assertIs(validation.passed[0].result, result)

    def test_population_mismatch_is_whole_boundary_failure(self) -> None:
        result = _workflow_result("E1")
        with self.assertRaises(ValidationPopulationError):
            Validator().validate((result,), (_metadata(result),), ())

    def test_unsupported_taipei_assertion_excludes_only_one_event(self) -> None:
        first = _workflow_result("E1")
        second = _workflow_result("E2")
        blocks = (
            WriterReportBlock("E1", "事件標題", "事件摘要 Taiwan Metro", "臺北捷運已安裝同型設備"),
            _block("E2"),
        )
        validation = Validator().validate(
            (first, second), (_metadata(first), _metadata(second)), blocks
        )
        self.assertEqual(tuple(item.event_id for item in validation.passed), ("E2",))
        self.assertEqual(validation.failed_event_ids, ("E1",))

    def test_one_correction_is_allowed_per_failed_event(self) -> None:
        result = _workflow_result("E1")
        calls = []

        def correction(upstream, block, reasons):
            calls.append((upstream.event_group.event_id, reasons))
            return _block("E1")

        invalid = WriterReportBlock("E1", "English", "Unsupported", "Taipei Metro installed")
        validation = Validator(correction_provider=correction).validate(
            (result,), (_metadata(result),), (invalid,)
        )
        self.assertEqual(validation.pass_count, 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(validation.correction_calls, 1)


if __name__ == "__main__":
    import unittest

    unittest.main()
