from __future__ import annotations

from unittest import TestCase

from src.weekly_report.report_service import ReportService
from src.weekly_report.writer import (
    ReportWriter,
    WriterPopulationError,
    WriterReportBlock,
    build_maiagent_writer_model_input,
)

from test_report_service import _workflow_result


class ReportWriterTests(TestCase):
    def test_zero_input_makes_no_provider_call(self) -> None:
        calls = []
        writer = ReportWriter(provider=lambda request: calls.append(request))
        self.assertEqual(writer.write(()), ())
        self.assertEqual(calls, [])

    def test_one_and_n_preserve_event_ids_and_order(self) -> None:
        calls = []

        def provider(request):
            calls.append(request)
            event_id = request["writer_request"]["event_id"]
            return {
                "event_id": event_id,
                "headline": "事件標題",
                "factual_summary": "來源說明事件內容",
                "taipei_insight": "可據此評估臺北捷運相關規劃方向",
            }

        ordered = (_workflow_result("E2"), _workflow_result("E1"))
        blocks = ReportWriter(provider=provider).write(ordered)
        self.assertEqual(tuple(block.event_id for block in blocks), ("E2", "E1"))
        self.assertEqual(len(calls), 2)

    def test_request_contains_only_event_and_authoritative_content(self) -> None:
        result = _workflow_result("E1")
        request = build_maiagent_writer_model_input(result)
        self.assertEqual(request["writer_request"]["event_id"], "E1")
        self.assertIn("substantive_content", request["writer_request"]["authoritative_evidence"])
        self.assertNotIn("country", request["writer_request"])
        self.assertNotIn("category", request["writer_request"])

    def test_extra_fields_and_foreign_headline_fail_whole_run(self) -> None:
        results = (_workflow_result("E1"), _workflow_result("E2"))
        calls = []

        def provider(request):
            calls.append(request)
            return {
                "event_id": request["writer_request"]["event_id"],
                "headline": "English headline",
                "factual_summary": "事件說明",
                "taipei_insight": "臺北捷運可評估規劃方向",
                "country": "forbidden",
            }

        with self.assertRaises(WriterPopulationError):
            ReportWriter(provider=provider).write(results)
        self.assertEqual(len(calls), 2)

    def test_japanese_and_simplified_structural_prose_cross_writer_boundary(self) -> None:
        result = _workflow_result("E1")
        for headline in ("大阪メトロ新型車両を導入", "该地铁已完成信号系统升级"):
            with self.subTest(headline=headline):
                def provider(request, headline=headline):
                    return {
                        "event_id": request["writer_request"]["event_id"],
                        "headline": headline,
                        "factual_summary": "事件摘要 Taiwan Metro",
                        "taipei_insight": "可供臺北捷運評估相關規劃方向",
                    }
                blocks = ReportWriter(provider=provider).write((result,))
                self.assertEqual(blocks[0].headline, headline)

    def test_writer_block_has_exact_fields(self) -> None:
        block = WriterReportBlock("E1", "標題", "摘要", "啟示")
        self.assertEqual(set(block.__dataclass_fields__), {"event_id", "headline", "factual_summary", "taipei_insight"})


if __name__ == "__main__":
    import unittest

    unittest.main()
