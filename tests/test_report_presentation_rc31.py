"""RC-31 presentation: one-line linked source and the email index (no Domain change)."""

from __future__ import annotations

from datetime import date

from src.weekly_report.gmail_smtp import index_for_artifact, subject_for_artifact
from src.weekly_report.report_service import (
    FinalReportArtifact,
    FinalReportBlock,
    FinalReportSection,
    FormalReportMetadata,
    ReportDisclosure,
    ReportService,
)

URL = "https://www.watch.impress.co.jp/docs/news/2151594.html"


def _block(event_id, category, headline, url):
    metadata = FormalReportMetadata(
        event_id=event_id, display_date="2026-10-27", country="日本", transit_system_name="東京メトロ",
        location=None, category=category, em_system_labels=("號誌",), source_display="www.watch.impress.co.jp", source_url=url,
    )
    return FinalReportBlock(metadata, headline, f"{headline}的事件摘要。", f"{headline}的臺北捷運局啟示。")


def _artifact(blocks, disclosure=ReportDisclosure()):
    sections = []
    for block in blocks:
        if sections and sections[-1].category == block.category:
            sections[-1] = FinalReportSection(block.category, sections[-1].events + (block,))
        else:
            sections.append(FinalReportSection(block.category, (block,)))
    period = (date(2026, 10, 21), date(2026, 10, 27))
    content = ReportService._render_final_content(tuple(blocks), tuple(sections), disclosure, period)
    return FinalReportArtifact(
        "weekly-report-0123456789abcdef", "artifact-1", "v1", tuple(blocks), tuple(sections), content,
        disclosure, period_start=period[0], period_end=period[1],
    )


def test_the_email_body_indexes_linked_headlines_by_section_in_assembled_order():
    blocks = [
        _block("e1", "技術新知", "東京地下鐵導入作業車輛AI輔助", URL),
        _block("e2", "技術新知", "另一則技術新知", "https://b.example/2"),
        _block("e3", "事故事件", "車站月臺起火", "https://c.example/3?a=1&b=2"),
    ]
    artifact = _artifact(blocks, ReportDisclosure(event_identity_gap_count=1))
    text, html = index_for_artifact(artifact)
    assert text.splitlines() == [
        "捷運技術週報", "報告期間：2026-10-21～2026-10-27", "",
        "【技術新知】", "- 東京地下鐵導入作業車輛AI輔助", f"  {URL}", "- 另一則技術新知", "  https://b.example/2", "",
        "【事故事件】", "- 車站月臺起火", "  https://c.example/3?a=1&b=2", "",
        "詳細內容及臺北捷運局啟示請參閱附件 PDF。",
    ]
    assert f'<a href="{URL}">東京地下鐵導入作業車輛AI輔助</a>' in html
    assert '<a href="https://c.example/3?a=1&amp;b=2">車站月臺起火</a>' in html
    for absent in ("事件摘要", "臺北捷運局啟示。", "日期：", "國家／地區", "執行說明", "可能含重複"):
        assert absent not in text and absent not in html
    assert subject_for_artifact(artifact) == "捷運技術週報｜2026-10-21～2026-10-27｜3 則"


def test_a_zero_event_email_states_the_artifact_outcome():
    text, _ = index_for_artifact(_artifact([], ReportDisclosure(technical_gap_count=1)))
    assert "本期正式報告無事件。" in text
    assert "本期無符合正式報導條件之事件" not in text
    text, _ = index_for_artifact(_artifact([]))
    assert "本期無符合正式報導條件之事件。" in text


def test_markdown_keeps_system_name_and_disclosure_and_links_the_source_once():
    artifact = _artifact([_block("e1", "技術新知", "標題", URL)], ReportDisclosure(event_identity_gap_count=1))
    assert f"來源：[www.watch.impress.co.jp]({URL})" in artifact.content
    assert "來源網址" not in artifact.content
    assert "運輸系統：東京メトロ" in artifact.content
    assert "執行說明：" in artifact.content
