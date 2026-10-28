"""RC-29: deterministic numeric grounding of Writer prose (Validator-owned)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from src.weekly_report.quantities import checked_quantities, is_grounded, stated_quantities
from src.weekly_report.report_service import ReportService
from src.weekly_report.validator import Validator
from src.weekly_report.writer import WriterReportBlock
from tests.test_report_service import _record, _semantic_provider, _workflow_result

# Modelled on run 40623936647: the source states an order-size range in crore.
CRORE_EVIDENCE = (
    "Under the order classification, a major order falls in the range of "
    "₹5,000 crore to ₹10,000 crore. The line will span about 31 km with 19 stations."
)


def _values(text, **kwargs):
    return [sorted(q.values) for q in stated_quantities(text, **kwargs)]


def test_magnitude_words_ranges_and_composed_cjk_amounts_are_read():
    assert _values("₹5,000 crore to ₹10,000 crore") == [[5e7, 5e10], [1e8, 1e11]]
    assert _values("1조 9000억 원") == [[1.9e12]]
    assert _values("3万4000人") == [[34000.0]]
    assert _values("16,4 millones de euros") == [[pytest.approx(16.4e6)]]
    assert _values("$1.93 billion") == [[1.93e9]]
    assert _values("€800 millions") == [[8e8]]
    # Writer prose is read strictly: comma groups thousands.
    assert _values("5,000億至1兆", strict=True) == [[5e11], [1e12]]


def test_only_large_amounts_and_measured_numbers_are_checked():
    checked = [q.text for q in checked_quantities("2026年10月27日，共19站、全長31公里，增加37%，經費1,640萬歐元，34列")]
    assert checked == ["31", "37", "1,640萬"]


def test_a_tenfold_magnitude_error_is_not_grounded_and_the_exact_conversion_is():
    evidence = stated_quantities(CRORE_EVIDENCE)
    wrong = checked_quantities("金額級距為5,000億至1兆印度盧比")
    right = checked_quantities("金額級距為500億至1,000億印度盧比")
    kept = checked_quantities("金額級距為₹5,000～10,000 crore")
    assert [is_grounded(q, evidence) for q in wrong] == [False, False]
    assert [is_grounded(q, evidence) for q in right] == [True, True]
    assert all(is_grounded(q, evidence) for q in kept)


def test_an_added_unit_conversion_is_not_grounded():
    evidence = stated_quantities("The upgrade covers 42 miles of track.")
    assert [is_grounded(q, evidence) for q in checked_quantities("涵蓋42英里（約68公里）軌道")] == [True, False]


def _crore_result():
    result = _workflow_result()
    record = result.member_records[0]
    evidence = replace(record.evidence, substantive_content=f"{record.evidence.substantive_content} {CRORE_EVIDENCE}")
    return replace(result, decision=replace(result.decision, member_records=(replace(record, evidence=evidence),)))


def test_validator_rejects_an_ungrounded_amount_without_a_helper_call_and_corrects_it_once():
    result = _crore_result()
    metadata = ReportService().project_formal_metadata((result,))
    calls, feedback_seen = [], []

    def provider(request):
        calls.append(request)
        return _semantic_provider(request)

    def correct(_result, block, feedback):
        feedback_seen.extend(feedback)
        return WriterReportBlock(block.event_id, block.headline, "L&T取得訂單，金額級距為500億至1,000億印度盧比。", block.taipei_insight)

    outcome = Validator(correction_provider=correct, semantic_provider=provider).validate(
        (result,), metadata,
        (WriterReportBlock("E1", "L&T取得達卡捷運訂單", "L&T取得訂單，金額級距為5,000億至1兆印度盧比。", "可供臺北捷運參考採購分類"),),
    )
    assert len(outcome.passed) == 1
    assert "500億至1,000億" in outcome.passed[0].block.factual_summary
    assert any("'5,000億'" in item for item in feedback_seen) and any("'1兆'" in item for item in feedback_seen)
    assert len(calls) == 1  # only the corrected block reached the helper


def test_validator_fails_the_event_when_the_correction_keeps_the_wrong_amount():
    result = _crore_result()
    metadata = ReportService().project_formal_metadata((result,))
    block = WriterReportBlock("E1", "L&T取得達卡捷運訂單", "金額級距為5,000億至1兆印度盧比。", "可供臺北捷運參考採購分類")
    outcome = Validator(correction_provider=lambda _r, b, _f: b, semantic_provider=_semantic_provider).validate(
        (result,), metadata, (block,)
    )
    assert outcome.passed == ()
    assert "factual_factual_summary_quantity_ungrounded" in outcome.failed[0].reasons


def test_grounded_amounts_pass_unchanged():
    result = _crore_result()
    metadata = ReportService().project_formal_metadata((result,))
    block = WriterReportBlock("E1", "L&T取得達卡捷運訂單", "金額級距為500億至1,000億印度盧比，全長31公里。", "可供臺北捷運參考採購分類")
    outcome = Validator(semantic_provider=_semantic_provider).validate((result,), metadata, (block,))
    assert len(outcome.passed) == 1 and outcome.failed == ()
