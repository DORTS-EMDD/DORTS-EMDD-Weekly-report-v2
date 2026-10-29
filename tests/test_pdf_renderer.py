"""Mechanical PDF rendering of the assembled formal report."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from src.weekly_report import pdf_renderer
from src.weekly_report.pdf_renderer import PdfFontUnavailable, pdf_filename, render_report_pdf
from src.weekly_report.report_service import (
    FinalReportArtifact,
    FinalReportBlock,
    FinalReportSection,
    FormalReportMetadata,
    ReportDisclosure,
    ReportService,
)

SOURCE_URL = "https://www.example.com/a/very/long/path?id=1&x=2"


def _block():
    metadata = FormalReportMetadata(
        event_id="evt_1",
        display_date="2026-10-19",
        country="韓國",
        transit_system_name="양산 도시철도",
        location="양산",
        category="營運動態",
        em_system_labels=("電聯車",),
        source_display="www.example.com",
        source_url=SOURCE_URL,
    )
    return FinalReportBlock(metadata, "蔚山城市鐵道1號線車輛基地規劃遷址", "蔚山市宣布擬將車輛基地改設於其他基地。", "可同步查明地下管線。")


def _artifact(events=None, disclosure=ReportDisclosure(validation_failed_count=1, event_identity_gap_count=1)):
    events = (_block(),) if events is None else events
    sections = (FinalReportSection("營運動態", events),) if events else ()
    period = (date(2026, 10, 14), date(2026, 10, 20))
    content = ReportService._render_final_content(events, sections, disclosure, period)
    return FinalReportArtifact(
        "weekly-report-0123456789abcdef", "artifact-1", "v1", events, sections, content,
        disclosure, period_start=period[0], period_end=period[1],
    )


def _text_and_links(data):
    fitz = pytest.importorskip("fitz")
    document = fitz.open(stream=data, filetype="pdf")
    text = "".join(page.get_text() for page in document)
    links = [link.get("uri") for page in document for link in page.get_links()]
    return text, links


def test_report_renders_with_embedded_fonts_and_keeps_text():
    data = render_report_pdf(_artifact())
    assert data.startswith(b"%PDF")
    text, _ = _text_and_links(data)
    for expected in ("捷運技術週報", "報告期間：2026-10-14～2026-10-20", "蔚山城市鐵道1號線", "양산", "可同步查明地下管線"):
        assert expected in text
    assert pdf_filename(_artifact()) == "weekly-report-0123456789abcdef.pdf"


def test_pdf_shows_the_source_as_one_link_and_omits_system_line_and_notes():
    # RC-31: presentation only; the Markdown artifact keeps all three.
    artifact = _artifact()
    text, links = _text_and_links(render_report_pdf(artifact))
    assert "來源：www.example.com" in text.replace("\n", "")
    assert links == [SOURCE_URL]
    for absent in ("運輸系統", "양산 도시철도", "來源網址", "執行說明", "未通過內容驗證", "可能含重複"):
        assert absent not in text
    for kept in ("運輸系統：양산 도시철도", f"來源：[www.example.com]({SOURCE_URL})", "執行說明：", "可能含重複報導"):
        assert kept in artifact.content
    assert "來源網址" not in artifact.content


def test_zero_event_artifact_renders_its_statement_without_notes():
    artifact = _artifact(events=(), disclosure=ReportDisclosure(technical_gap_count=2))
    text, _ = _text_and_links(render_report_pdf(artifact))
    assert "本期正式報告無事件。" in text
    assert "執行說明" not in text
    clean = _artifact(events=(), disclosure=ReportDisclosure())
    assert "本期無符合正式報導條件之事件。" in _text_and_links(render_report_pdf(clean))[0]


def test_missing_font_fails_closed():
    with patch.dict(pdf_renderer._FONT_CANDIDATES, {"ko": ("PDF_FONT_KO_UNSET", ("/no/such/font.ttf",))}):
        with pytest.raises(PdfFontUnavailable):
            render_report_pdf(_artifact())
