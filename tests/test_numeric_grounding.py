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


def _grounded(evidence_text, writer_text):
    evidence = stated_quantities(evidence_text)
    return [is_grounded(quantity, evidence) for quantity in checked_quantities(writer_text)]


def test_magnitude_words_ranges_and_composed_cjk_amounts_are_read():
    assert _values("₹5,000 crore to ₹10,000 crore") == [[5e10], [1e11]]
    assert _values("1조 9000억 원") == [[1.9e12]]
    assert _values("3万4000人") == [[34000.0]]
    assert _values("16,4 millones de euros") == [[pytest.approx(16.4e6)]]
    assert _values("$1.93 billion") == [[1.93e9]]
    assert _values("€800 millions") == [[8e8]]
    # A range states its magnitude and unit once, on the upper bound.
    assert _values("5,000～10,000億円") == [[5e11], [1e12]]
    # Writer prose is read strictly: comma groups thousands.
    assert _values("5,000億至1兆", strict=True) == [[5e11], [1e12]]


@pytest.mark.parametrize(
    ("text", "values"),
    [
        # The source's own unambiguous numbers establish its decimal mark.
        ("The line is 1,234 km long and costs $1.5 billion.", [[1.234e6], [1.5e9]]),
        ("Die Strecke ist 1,234 km lang und kostet 1,5 Mrd. Euro.", [[1234.0], [1.5e9]]),
        ("Le projet de 1.234 km coûtera 2,5 milliards d'euros.", [[1.234e6], [2.5e9]]),
        # Unresolved: one separator before three digits, nothing else to go by.
        ("The line is 1,234 km long.", [[]]),
        # A magnitude word only English uses fixes the dot decimal mark.
        ("A contract of 91.766 billion KRW", [[9.1766e10]]),
        ("Kosten von 1.250 Millionen Euro", [[1.25e9]]),
        ("Kosten von 1.234 Millionen Euro", [[]]),
        # A decimal fraction is not written with trailing zeros.
        ("Orders of ₹2,500 crore", [[2.5e10]]),
        # Notation fixed by the token itself (km are read in metres) or by CJK text next to it.
        ("₹1,25,000 crore", [[1.25e12]]),
        ("1.234.567 passengers", [[1234567.0]]),
        ("1,234,567.5 passengers", [[1234567.5]]),
        ("1.234.567,5 passengers", [[1234567.5]]),
        ("0,500 km", [[500.0]]),
        ("16,4 km", [[16400.0]]),
        ("運賃は1,234円", [[1234.0]]),
    ],
)
def test_a_separator_is_read_in_the_notation_the_source_establishes(text, values):
    assert _values(text) == values


def test_units_and_currencies_are_read_with_the_number():
    units = {q.text: sorted(q.unit) for q in stated_quantities("a 31-km line, 42 miles, 2.3 percentage points, up 37%, €16.4m, 300억 원")}
    assert units == {
        "31-km": ["length"], "42 miles": ["mile"], "2.3 percentage points": ["percentage_point"],
        "37%": ["percent"], "16.4m": ["EUR"], "300억 원": ["KRW"],
    }


def test_amounts_measures_and_large_magnitudes_are_checked_but_dates_and_counts_are_not():
    checked = [q.text for q in checked_quantities("2026年10月27日，共19站、全長31公里，增加37%，經費1,640萬歐元，34列")]
    assert checked == ["31公里", "37%", "1,640萬歐元"]


def test_a_tenfold_magnitude_error_is_not_grounded_and_the_exact_conversion_is():
    assert _grounded(CRORE_EVIDENCE, "金額級距為5,000億至1兆印度盧比") == [False, False]
    assert _grounded(CRORE_EVIDENCE, "金額級距為500億至1,000億印度盧比") == [True, True]
    assert all(_grounded(CRORE_EVIDENCE, "金額級距為₹5,000～10,000 crore"))


@pytest.mark.parametrize(
    ("evidence", "writer"),
    [
        # Same number, different unit or currency.
        ("The upgrade covers 42 miles of track.", "涵蓋42公里軌道"),
        ("全長30公里", "運量增加30%"),
        ("事業費は500億円", "經費500億美元"),
        ("Ridership rose 2.3 percentage points.", "運量增加2.3%"),
        ("A 4,000 m² depot", "長4,000公尺"),
        ("The contract is worth €800 million.", "合約金額8億英鎊"),
        ("The contract is worth $500 million.", "合約金額5億歐元"),
        # An ambiguous Evidence number never grounds its other reading.
        ("Orders of ₹5,000 crore", "訂單5,000萬印度盧比"),
        ("The line is 1,234 km long.", "全長1,234公里"),
        ("The line is 1,234 km long.", "全長1.234公里"),
        # A currency the Evidence does not name is not grounded by a shared sign or word.
        ("總經費5億元", "總經費新臺幣5億元"),
        ("The order is worth $1.93 billion.", "訂單金額19.3億美元"),
        ("¥500 billion", "5,000億日圓"),
        ("Rs 5,000 crore", "500億印度盧比"),
        # A different value that a relative tolerance would have accepted.
        ("事業費は1,040億円", "經費1,000億日圓"),
        ("Ridership grew 20%.", "運量增加21%"),
        ("A 31 km line", "全長31.5公里"),
    ],
)
def test_a_number_is_not_grounded_by_the_same_digits_in_another_unit_or_value(evidence, writer):
    assert _grounded(evidence, writer) == [False]


@pytest.mark.parametrize(
    ("evidence", "writer"),
    [
        ("The order is worth $1.93 billion.", "訂單金額19.3億元"),
        ("The order is worth $1.93 billion.", "訂單金額$19.3億"),
        ("A$2.5bn upgrade", "25億澳元的升級"),
        ("A €16.4m contract", "1,640萬歐元合約"),
        ("The order is worth US$1.93 billion.", "訂單金額19.3億美元"),
        ("16,4 millones de euros", "1,640萬歐元"),
        ("총사업비 1조 9000억 원", "總經費1兆9,000億韓元"),
        ("사업비 300억 원", "經費300億韓元"),
        ("¥500 billion", "¥5,000億"),
        ("事業費は5,000～10,000億円", "經費5,000億至1兆日圓"),
        ("NT$5億元", "新臺幣5億元"),
        ("總經費5億元", "總經費5億元"),
        ("新台幣5億元", "新臺幣5億元"),
        ("Rs 5,000 crore", "500億盧比"),
        ("Orders of ₹2,500 crore", "訂單250億印度盧比"),
        ("Die Strecke ist 1,234 km lang und kostet 1,5 Mrd. Euro.", "全長1.234公里"),
        ("The line is 1,234 km long and costs $1.5 billion.", "全長1,234公里"),
        ("a 31-km line", "全長31公里"),
        ("全長31.5キロ", "全長31.5公里"),
        ("a 500 metres viaduct", "0.5公里高架"),
        ("Ridership rose 2.3 percentage points.", "運量增加2.3個百分點"),
        ("승객이 3.5%p 늘었다", "增加3.5個百分點"),
        ("Ridership grew 20.4%.", "運量增加20%"),
        ("1,500 tonnes of steel", "1,500公噸鋼材"),
        ("연간 1160t이 필요하다", "年用量1,160噸"),
        # The Writer states no currency: the number alone must match.
        ("₹10,000 crore", "約1,000億"),
    ],
)
def test_a_grounded_amount_or_measure_in_any_source_language_passes(evidence, writer):
    grounded = _grounded(evidence, writer)
    assert grounded and all(grounded)


def test_an_added_unit_conversion_is_not_grounded():
    assert _grounded("The upgrade covers 42 miles of track.", "涵蓋42英里（約68公里）軌道") == [True, False]


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
    assert any("'5,000億'" in item for item in feedback_seen) and any("'1兆印度盧比'" in item for item in feedback_seen)
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
