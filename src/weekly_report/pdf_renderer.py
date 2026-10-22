"""Mechanical PDF rendering of the assembled formal report (contract section R).

The PDF presents ``FinalReportArtifact.content`` line by line, in the
assembled order, so the PDF says exactly what the validated report says. It
decides nothing and changes no text. TrueType fonts are embedded (subset) per
script run (Traditional Chinese, Korean, Japanese kana), so the PDF renders the
same in every viewer, including source-language metadata such as a Korean
system name. Without a usable font, rendering fails; a broken PDF is never sent.
"""

from __future__ import annotations

from html import escape
from io import BytesIO
import os
from pathlib import Path
import re

from .report_service import FinalReportArtifact

PDF_RENDERER_VERSION = "formal-report-pdf-v1"

# Per script: an environment override, the Ubuntu runner font (apt package
# fonts-wqy-zenhei covers Chinese, Korean and kana), then Windows fonts.
_WQY = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"
_FONT_CANDIDATES = {
    "zh": ("PDF_FONT_ZH", (_WQY, "C:/Windows/Fonts/msjh.ttc")),
    "ko": ("PDF_FONT_KO", (_WQY, "C:/Windows/Fonts/malgun.ttf")),
    "ja": ("PDF_FONT_JA", (_WQY, "C:/Windows/Fonts/msgothic.ttc")),
}


class PdfFontUnavailable(RuntimeError):
    """No embeddable font is available for a script the report needs."""
_SCRIPT_RUNS = re.compile(
    r"(?P<ko>[가-힣ᄀ-ᇿ㄰-㆏]+)|(?P<ja>[぀-ヿㇰ-ㇿｦ-ﾝ]+)"
)
_LINK_LABEL = "來源網址："


def _registered_fonts() -> dict[str, str]:
    """Register one embeddable TrueType font per script; return script -> name."""

    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    names: dict[str, str] = {}
    by_path: dict[str, str] = {}
    for script, (variable, defaults) in _FONT_CANDIDATES.items():
        override = os.environ.get(variable, "").strip()
        path = next((candidate for candidate in ((override,) if override else defaults) if Path(candidate).is_file()), None)
        if path is None:
            raise PdfFontUnavailable(f"no embeddable font for script {script}")
        if path not in by_path:
            name = f"weekly-report-{len(by_path) + 1}"
            if name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(name, path, subfontIndex=0))
            by_path[path] = name
        names[script] = by_path[path]
    return names


def _markup(text: str, fonts: dict[str, str]) -> str:
    """Escape text and wrap Korean and kana runs in their CID fonts."""

    parts: list[str] = []
    position = 0
    for match in _SCRIPT_RUNS.finditer(text):
        parts.append(escape(text[position:match.start()]))
        parts.append(f'<font name="{fonts[match.lastgroup]}">{escape(match.group())}</font>')
        position = match.end()
    parts.append(escape(text[position:]))
    return "".join(parts)


def _link(url: str) -> str:
    # CJK word wrapping lets a long URL break inside the page width.
    return f'<link href="{escape(url, quote=True)}" color="#1f4e8c">{escape(url)}</link>'


def render_report_pdf(artifact: FinalReportArtifact) -> bytes:
    """Render the artifact's content as an A4 PDF; raises on any failure."""

    if not isinstance(artifact, FinalReportArtifact):
        raise TypeError("PDF rendering requires a FinalReportArtifact")
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    fonts = _registered_fonts()
    font = fonts["zh"]
    body = ParagraphStyle("body", fontName=font, fontSize=10.2, leading=15.5, alignment=TA_LEFT, wordWrap="CJK")
    styles = {
        "title": ParagraphStyle("title", parent=body, fontSize=16, leading=22, spaceAfter=6),
        "section": ParagraphStyle("section", parent=body, fontSize=13, leading=18, spaceBefore=10, spaceAfter=4, textColor="#1f4e8c"),
        "headline": ParagraphStyle("headline", parent=body, fontSize=12, leading=17, spaceBefore=6, spaceAfter=2, textColor="#111111"),
        "body": body,
        "meta": ParagraphStyle("meta", parent=body, fontSize=9.3, leading=13.5, textColor="#444444"),
    }

    lines = artifact.content.rstrip("\n").split("\n")
    story = []
    for index, line in enumerate(lines):
        if not line.strip():
            story.append(Spacer(1, 3 * mm))
            continue
        next_line = lines[index + 1] if index + 1 < len(lines) else ""
        if index == 0:
            style = "title"
        elif line.startswith("【") and line.endswith("】") or line == "執行說明：":
            style = "section"
        elif next_line.startswith("日期："):
            style = "headline"
        elif line.startswith(("報告期間：", "日期：", "國家／地區：", "運輸系統：", "地點：", "相關系統：", "來源：", _LINK_LABEL)):
            style = "meta"
        else:
            style = "body"
        if line.startswith(_LINK_LABEL):
            text = escape(_LINK_LABEL) + _link(line[len(_LINK_LABEL):])
        else:
            text = _markup(line, fonts)
        story.append(Paragraph(text, styles[style]))

    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title="捷運技術週報",
        subject=f"{artifact.report_id} {artifact.artifact_id}",
        creator=PDF_RENDERER_VERSION,
    )
    document.build(story)
    data = buffer.getvalue()
    if not data.startswith(b"%PDF"):
        raise RuntimeError("PDF rendering produced no document")
    return data


def pdf_filename(artifact: FinalReportArtifact) -> str:
    return f"{artifact.report_id}.pdf"


__all__ = ["PDF_RENDERER_VERSION", "PdfFontUnavailable", "pdf_filename", "render_report_pdf"]
