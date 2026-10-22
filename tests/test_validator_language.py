"""RC-20: deterministic Traditional Chinese check for fused Korean/Chinese words."""

from __future__ import annotations

from src.weekly_report.report_service import ReportService
from src.weekly_report.validator import Validator, _mixed_script_words
from src.weekly_report.writer import WriterReportBlock
from tests.test_report_service import _semantic_provider, _workflow_result


def test_fused_words_are_found_and_clean_prose_is_not():
    assert _mixed_script_words("경남道長搭乘試運轉列車") == ["경남道長搭乘"]
    assert _mixed_script_words("울산市議會檢視電車政策") == ["울산市議會檢"]
    for clean in ("蔚山市議會檢視電車政策", "梁山 양산 도시철도", "東京メトロ日比谷線", "Metro de Santiago 9號線"):
        assert _mixed_script_words(clean) == []


def test_mixed_script_fails_without_a_helper_call_and_gets_one_correction():
    result = _workflow_result()
    metadata = ReportService().project_formal_metadata((result,))
    calls = []

    def provider(request):
        calls.append(request)
        return _semantic_provider(request)

    def correct(_result, block, feedback):
        assert any("경남道長" in item for item in feedback)
        return WriterReportBlock(block.event_id, "慶尚南道知事搭乘試運轉列車", block.factual_summary, block.taipei_insight)

    validator = Validator(correction_provider=correct, semantic_provider=provider)
    outcome = validator.validate(
        (result,),
        metadata,
        (WriterReportBlock("E1", "경남道長搭乘試運轉列車", "事件摘要 Taiwan Metro", "可供臺北捷運評估規劃方向"),),
    )
    assert len(outcome.passed) == 1
    assert outcome.passed[0].block.headline == "慶尚南道知事搭乘試運轉列車"
    assert len(calls) == 1  # only the corrected block reached the helper
