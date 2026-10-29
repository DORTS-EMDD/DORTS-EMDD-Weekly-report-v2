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


# --- source display label (RC-31, amended section R) -------------------------

from dataclasses import replace  # noqa: E402

import pytest  # noqa: E402

from src.weekly_report.contracts import CanonicalCandidate  # noqa: E402
from src.weekly_report.gmail_smtp import index_for_artifact as _index  # noqa: E402
from src.weekly_report.report_service import source_display_for  # noqa: E402
from src.weekly_report.validator import Validator, ValidationStageFailure, ValidationStageFailureReason  # noqa: E402
from src.weekly_report.writer import WriterReportBlock  # noqa: E402
from tests.test_report_service import _record, _semantic_provider, _workflow_result  # noqa: E402


def _published(
    *, publisher="Impress Watch", publisher_url="https://www.watch.impress.co.jp", origin_check="MATCH", url=URL
):
    record = _record("C1", source_url=url)
    candidate = CanonicalCandidate(
        "C1", "Candidate C1", "https://news.google.com/rss/articles/X", publisher=publisher, publisher_url=publisher_url
    )
    provenance = {} if origin_check is None else {"publisher_origin_check": origin_check}
    return replace(record, candidate=candidate, evidence=replace(record.evidence, provenance=provenance))


def test_a_validated_publisher_of_the_canonical_host_names_the_source():
    assert source_display_for(_published()) == "Impress Watch"
    # The declared origin may be the registrable parent of the canonical host.
    assert source_display_for(_published(publisher_url="https://impress.co.jp")) == "Impress Watch"
    assert source_display_for(_published(publisher="  Impress\n Watch ")) == "Impress Watch"


@pytest.mark.parametrize(
    "overrides",
    [
        {"origin_check": "MISMATCH"},  # EvidenceService found the article outside the declared origin
        {"origin_check": "NOT_DECLARED"},  # no declared origin to validate
        {"origin_check": None},  # direct source: no publisher provenance at all
        {"publisher_url": "https://other.example"},  # validated origin is not the canonical host
        {"url": "https://amp.mirror.example/docs/news/2151594.html"},  # canonical moved to another host
        {"publisher": "   "},
        {"publisher": "x" * 81},
    ],
)
def test_an_unvalidated_or_mismatched_publisher_falls_back_to_the_canonical_hostname(overrides):
    record = _published(**overrides)
    expected = "amp.mirror.example" if "url" in overrides else "www.watch.impress.co.jp"
    assert source_display_for(record) == expected


def test_an_unusable_canonical_url_has_no_label():
    assert source_display_for(_published(url="not a url")) is None


def test_every_renderer_consumes_the_one_projected_label_and_the_validator_checks_it():
    from src.weekly_report.pdf_renderer import render_report_pdf
    from src.weekly_report.report_service import ReportService

    fitz = pytest.importorskip("fitz")
    result = _workflow_result(records=(_published(),))
    service = ReportService()
    metadata = service.project_formal_metadata((result,))
    assert metadata[0].source_display == "Impress Watch"
    assert metadata[0].source_url == URL  # the link target is unchanged
    block = WriterReportBlock("E1", "事件標題", "事件摘要 Taiwan Metro", "可供臺北捷運評估規劃方向")
    artifact = service.assemble_final_report(Validator(semantic_provider=_semantic_provider).validate((result,), metadata, (block,)))
    assert f"來源：[Impress Watch]({URL})" in artifact.content
    document = fitz.open(stream=render_report_pdf(artifact), filetype="pdf")
    assert "來源：Impress Watch" in "".join(page.get_text() for page in document).replace("\n", "")
    assert [link.get("uri") for page in document for link in page.get_links()] == [URL]
    assert f'<a href="{URL}">事件標題</a>' in _index(artifact)[1]

    # A label that is not the owner's value fails metadata integrity.
    tampered = (replace(metadata[0], source_display="www.watch.impress.co.jp"),)
    with pytest.raises(ValidationStageFailure) as failure:
        Validator(semantic_provider=_semantic_provider).validate((result,), tampered, (block,))
    assert failure.value.reason is ValidationStageFailureReason.METADATA_INTEGRITY_FAILURE
