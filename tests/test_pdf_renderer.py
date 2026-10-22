"""Mechanical PDF rendering of the assembled formal report."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.weekly_report import pdf_renderer
from src.weekly_report.pdf_renderer import PdfFontUnavailable, pdf_filename, render_report_pdf
from src.weekly_report.report_service import FinalReportArtifact

CONTENT = (
    "捷運技術週報\n\n【營運動態】\n\n"
    "蔚山城市鐵道1號線車輛基地規劃遷址\n日期：2026-10-19\n國家／地區：韓國\n運輸系統：양산 도시철도\n"
    "相關系統：電聯車\n事件摘要：蔚山市宣布擬將車輛基地改設於其他基地。\n臺北捷運局啟示：可同步查明地下管線。\n"
    "來源：www.example.com\n來源網址：https://www.example.com/a/very/long/path?id=1&x=2\n\n"
    "執行說明：\n本期有 1 則事件未通過內容驗證，未列入本報告。\n"
)


def _artifact(content=CONTENT):
    return FinalReportArtifact("weekly-report-0123456789abcdef", "artifact-1", "v1", (), (), content)


def test_report_renders_with_embedded_fonts_and_keeps_text():
    fitz = pytest.importorskip("fitz")
    data = render_report_pdf(_artifact())
    assert data.startswith(b"%PDF")
    text = "".join(page.get_text() for page in fitz.open(stream=data, filetype="pdf"))
    for expected in ("捷運技術週報", "蔚山城市鐵道1號線", "양산 도시철도", "本期有 1 則事件未通過內容驗證"):
        assert expected in text
    assert pdf_filename(_artifact()) == "weekly-report-0123456789abcdef.pdf"


def test_zero_event_artifact_renders():
    assert render_report_pdf(_artifact("本期無符合正式報導條件之事件。")).startswith(b"%PDF")


def test_missing_font_fails_closed():
    with patch.dict(pdf_renderer._FONT_CANDIDATES, {"ko": ("PDF_FONT_KO_UNSET", ("/no/such/font.ttf",))}):
        with pytest.raises(PdfFontUnavailable):
            render_report_pdf(_artifact())
