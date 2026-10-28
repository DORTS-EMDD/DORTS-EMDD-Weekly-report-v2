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


def test_headline_label_prefixes_and_pictographs_are_found():
    # RC-24: Python assembles sections; a headline carries no label or emoji.
    from src.weekly_report.validator import _headline_decorations

    assert _headline_decorations("🔹 [營運政策] 廈門地鐵兩條新線啟動") == ["🔹", "[營運政策]"]
    assert _headline_decorations("🔹營運爭議｜蔚山車輛基地變更") == ["🔹", "營運爭議｜"]
    assert _headline_decorations("【營運政策】那不勒斯地鐵6號線調整服務") == ["【營運政策】"]
    for clean in (
        "日內瓦跨境電車17號線延伸至法國阿訥馬斯",
        "雪梨 M1 線最後一段本週末不通車，政府尚未公布啟用日期",
        "慕尼黑U-Bahn A型車將於2026年底退役",
        "溫度達40℃時列車降速",
    ):
        assert _headline_decorations(clean) == []


def test_decorated_headline_fails_without_a_helper_call_and_gets_one_correction():
    result = _workflow_result()
    metadata = ReportService().project_formal_metadata((result,))
    calls = []

    def provider(request):
        calls.append(request)
        return _semantic_provider(request)

    def correct(_result, block, feedback):
        assert any("重大事故｜" in item for item in feedback)
        return WriterReportBlock(block.event_id, "臺北捷運號誌測試完成", block.factual_summary, block.taipei_insight)

    validator = Validator(correction_provider=correct, semantic_provider=provider)
    outcome = validator.validate(
        (result,),
        metadata,
        (WriterReportBlock("E1", "🔹 重大事故｜臺北捷運號誌測試完成", "事件摘要 Taiwan Metro", "可供臺北捷運評估規劃方向"),),
    )
    assert len(outcome.passed) == 1
    assert outcome.passed[0].block.headline == "臺北捷運號誌測試完成"
    assert len(calls) == 1


def test_writer_instructions_forbid_headline_labels_and_request_references():
    from src.weekly_report.writer import WRITER_INSTRUCTIONS

    text = " ".join(WRITER_INSTRUCTIONS)
    assert "label prefix" in text and "【營運政策】" in text
    assert "候選資料" in text


def test_writer_insight_must_be_specific_and_not_assert_taipei_status():
    from src.weekly_report.writer import WRITER_INSTRUCTIONS

    text = " ".join(WRITER_INSTRUCTIONS)
    assert "avoid generic advice that would fit any event" in text
    assert "rail system in Taiwan" in text
