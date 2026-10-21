from __future__ import annotations

from unittest import TestCase

from src.weekly_report.report_service import ReportService
from src.weekly_report.contracts import TechnicalGapKind
from src.weekly_report.validator import (
    ValidationEvidenceSource,
    ValidationSemanticRequest,
    ValidationStageFailure,
    ValidationStageFailureReason,
    ValidationWriterProse,
    Validator,
    segment_writer_field,
)
from src.weekly_report.writer import WriterReportBlock

from test_report_service import _workflow_result


def _metadata(result):
    return ReportService().project_formal_metadata((result,))[0]


def _block(event_id: str = "E1", *, headline: str = "Taiwan", summary: str = "Metro", insight: str = "Taipei") -> WriterReportBlock:
    return WriterReportBlock(event_id, headline, summary, insight)


def _proposal(request, *, assessment_overrides=None, language_overrides=None):
    """Assess every Validator-supplied unit; overrides key on field or unit_id."""

    assessment_overrides = assessment_overrides or {}
    language_overrides = language_overrides or {}
    source = request.evidence_sources[0]
    fields = []
    for field_name, unit_ids in request.unit_ids_by_field().items():
        name = field_name.value
        default = "ANALYSIS" if name == "taipei_insight" else "SUPPORTED"
        fields.append(
            {
                "field_name": name,
                "language_assessment": language_overrides.get(name, "TRADITIONAL_CHINESE"),
                "unit_assessments": [
                    {
                        "unit_id": unit_id,
                        "assessment": assessment_overrides.get(
                            unit_id, assessment_overrides.get(name, default)
                        ),
                        "evidence_citations": [
                            {"candidate_id": source.candidate_id, "exact_quote": source.substantive_content}
                        ],
                    }
                    for unit_id in unit_ids
                ],
            }
        )
    return {"event_id": request.event_id, "field_assessments": fields}


class ValidatorTests(TestCase):
    def test_valid_event_passes_and_preserves_reference(self) -> None:
        result = _workflow_result("E1")
        validation = Validator(semantic_provider=_proposal).validate(
            (result,), (_metadata(result),), (_block(),)
        )
        self.assertEqual(validation.pass_count, 1)
        self.assertIs(validation.passed[0].result, result)

    def test_nonzero_event_without_semantic_provider_is_whole_run_failure(self) -> None:
        result = _workflow_result("E1")
        with self.assertRaises(ValidationStageFailure) as context:
            Validator().validate((result,), (_metadata(result),), (_block(),))
        self.assertEqual(context.exception.reason, ValidationStageFailureReason.MISSING_SEMANTIC_PROVIDER)

    def test_population_mismatch_is_whole_boundary_failure(self) -> None:
        result = _workflow_result("E1")
        with self.assertRaises(ValidationStageFailure) as context:
            Validator(semantic_provider=_proposal).validate((result,), (_metadata(result),), ())
        self.assertEqual(context.exception.reason, ValidationStageFailureReason.EVENT_POPULATION_FAILURE)

    def test_generic_overlap_does_not_prove_grounding(self) -> None:
        result = _workflow_result("E1")
        invalid = _block(summary="Metro 已全面部署 AI 自動駕駛系統，並完成全線無人化營運。")
        provider = lambda request: _proposal(request, assessment_overrides={"factual_summary": "UNSUPPORTED"})
        validation = Validator(semantic_provider=provider).validate(
            (result,), (_metadata(result),), (invalid,)
        )
        self.assertEqual(validation.pass_count, 0)
        self.assertEqual(validation.failed_event_ids, ("E1",))

    def test_language_assessment_rejects_japanese_simplified_and_mixed(self) -> None:
        result = _workflow_result("E1")
        for headline in ("大阪メトロ新型車両を導入", "该地铁已完成信号系统升级", "Metro 新型車両 upgrade completed"):
            with self.subTest(headline=headline):
                provider = lambda request: _proposal(
                    request, language_overrides={"headline": "NOT_TRADITIONAL_CHINESE"}
                )
                validation = Validator(semantic_provider=provider).validate(
                    (result,), (_metadata(result),), (_block(headline=headline),)
                )
                self.assertEqual(validation.pass_count, 0)

    def test_invalid_response_is_technical_failure(self) -> None:
        result = _workflow_result("E1")
        with self.assertRaises(ValidationStageFailure) as context:
            Validator(semantic_provider=lambda request: {"event_id": request.event_id}).validate(
                (result,), (_metadata(result),), (_block(),)
            )
        self.assertEqual(context.exception.reason, ValidationStageFailureReason.INVALID_RESPONSE)

    def test_invalid_citation_is_technical_failure(self) -> None:
        result = _workflow_result("E1")

        def provider(request):
            proposal = _proposal(request)
            proposal["field_assessments"][0]["unit_assessments"][0]["evidence_citations"][0]["exact_quote"] = "missing"
            return proposal

        with self.assertRaises(ValidationStageFailure) as context:
            Validator(semantic_provider=provider).validate(
                (result,), (_metadata(result),), (_block(),)
            )
        self.assertEqual(context.exception.reason, ValidationStageFailureReason.INVALID_CITATION)

    def test_supported_unit_without_citation_is_technical_failure(self) -> None:
        result = _workflow_result("E1")

        def provider(request):
            proposal = _proposal(request)
            proposal["field_assessments"][0]["unit_assessments"][0]["evidence_citations"] = []
            return proposal

        with self.assertRaises(ValidationStageFailure) as context:
            Validator(semantic_provider=provider).validate(
                (result,), (_metadata(result),), (_block(),)
            )
        self.assertEqual(context.exception.reason, ValidationStageFailureReason.INVALID_CITATION)

    def test_one_semantic_correction_gets_one_fresh_check(self) -> None:
        result = _workflow_result("E1")
        calls = []

        def provider(request):
            calls.append(request.writer_prose.headline)
            if len(calls) == 1:
                return _proposal(request, assessment_overrides={"factual_summary": "UNSUPPORTED"})
            return _proposal(request)

        def correction(upstream, block, reasons):
            return _block("E1")

        validation = Validator(correction_provider=correction, semantic_provider=provider).validate(
            (result,), (_metadata(result),), (_block(summary="unsupported"),)
        )
        self.assertEqual(validation.pass_count, 1)
        self.assertEqual(validation.correction_calls, 1)
        self.assertEqual(len(calls), 2)

    def test_technical_provider_failure_does_not_trigger_correction(self) -> None:
        result = _workflow_result("E1")
        corrections = []

        def correction(*args):
            corrections.append(args)
            return _block()

        with self.assertRaises(ValidationStageFailure) as context:
            Validator(
                correction_provider=correction,
                semantic_provider=lambda request: (_ for _ in ()).throw(RuntimeError("provider")),
            ).validate((result,), (_metadata(result),), (_block(),))
        self.assertEqual(context.exception.reason, ValidationStageFailureReason.PROVIDER_FAILURE)
        self.assertEqual(corrections, [])


class WriterSegmentationTests(TestCase):
    """RC-7: the Validator owns deterministic Writer-unit segmentation."""

    def _texts(self, text):
        units = segment_writer_field("factual_summary", text)
        self.assertEqual("".join(unit.text for unit in units), text)
        self.assertEqual(
            [unit.unit_id for unit in units],
            [f"factual_summary-{index}" for index in range(1, len(units) + 1)],
        )
        return [unit.text for unit in units]

    def test_headline_without_terminator_is_one_unit(self) -> None:
        self.assertEqual(self._texts("埃及開羅地鐵三號線第四期啟用"), ["埃及開羅地鐵三號線第四期啟用"])

    def test_full_width_terminators_split_and_keep_closers_and_whitespace(self) -> None:
        self.assertEqual(
            self._texts("第一句。第二句！「引述內容。」接著說明；最後一句？  "),
            ["第一句。", "第二句！", "「引述內容。」", "接著說明；", "最後一句？  "],
        )

    def test_ascii_periods_commas_and_decimals_do_not_split(self) -> None:
        self.assertEqual(
            self._texts("St. Louis 延伸 3.5 公里，預計 2026 年完工。後續"),
            ["St. Louis 延伸 3.5 公里，預計 2026 年完工。", "後續"],
        )

    def test_line_breaks_split_and_punctuation_only_units_merge(self) -> None:
        self.assertEqual(self._texts("甲段\n\n乙段。"), ["甲段\n\n", "乙段。"])
        self.assertEqual(self._texts("。開頭"), ["。開頭"])
        self.assertEqual(self._texts("結尾。\n」"), ["結尾。\n」"])

    def test_segmentation_is_deterministic(self) -> None:
        text = "第一句。第二句。"
        self.assertEqual(
            segment_writer_field("factual_summary", text), segment_writer_field("factual_summary", text)
        )

    def test_request_payload_carries_units_not_free_prose(self) -> None:
        request = ValidationSemanticRequest(
            "E1",
            (ValidationEvidenceSource("C1", "Evidence."),),
            ValidationWriterProse("標題", "第一句。第二句。", "啟示。"),
        )
        payload = request.as_payload()
        self.assertEqual(set(payload), {"event_id", "evidence_sources", "writer_fields"})
        self.assertEqual(
            payload["writer_fields"],
            [
                {"field_name": "headline", "units": [{"unit_id": "headline-1", "text": "標題"}]},
                {
                    "field_name": "factual_summary",
                    "units": [
                        {"unit_id": "factual_summary-1", "text": "第一句。"},
                        {"unit_id": "factual_summary-2", "text": "第二句。"},
                    ],
                },
                {"field_name": "taipei_insight", "units": [{"unit_id": "taipei_insight-1", "text": "啟示。"}]},
            ],
        )


class UnitCoverageTests(TestCase):
    """RC-7: the proposal must assess every supplied unit exactly once."""

    _SUMMARY = "Metro 完成測試。Metro 將於明年通車。"

    def _validate(self, provider, *, hook=None):
        result = _workflow_result("E1")
        return Validator(semantic_provider=provider).validate(
            (result,), (_metadata(result),), (_block(summary=self._SUMMARY),),
            on_event_technical_gap=hook,
        )

    def _summary_units(self, proposal):
        return next(
            field for field in proposal["field_assessments"] if field["field_name"] == "factual_summary"
        )["unit_assessments"]

    def test_multi_unit_summary_passes_when_every_unit_is_supported(self) -> None:
        seen = []

        def provider(request):
            seen.append(request.unit_ids_by_field())
            return _proposal(request)

        self.assertEqual(self._validate(provider).pass_count, 1)
        self.assertEqual(
            [ids for name, ids in seen[0].items() if name.value == "factual_summary"],
            [("factual_summary-1", "factual_summary-2")],
        )

    def test_one_unsupported_unit_is_a_semantic_fail(self) -> None:
        provider = lambda request: _proposal(request, assessment_overrides={"factual_summary-2": "UNSUPPORTED"})
        validation = self._validate(provider)
        self.assertEqual(validation.pass_count, 0)
        self.assertEqual(validation.failed[0].reasons, ("semantic_factual_summary_unsupported",))

    def test_reordered_unit_assessments_are_mapped_by_unit_id(self) -> None:
        def provider(request):
            proposal = _proposal(request)
            self._summary_units(proposal).reverse()
            return proposal

        self.assertEqual(self._validate(provider).pass_count, 1)

    def test_missing_duplicate_or_foreign_unit_is_coverage_violation(self) -> None:
        def missing(units):
            del units[1]

        def duplicate(units):
            units[1] = dict(units[0])

        def foreign(units):
            units[1] = dict(units[1], unit_id="headline-1")

        for mutate in (missing, duplicate, foreign):
            with self.subTest(mutation=mutate.__name__):
                def provider(request, mutate=mutate):
                    proposal = _proposal(request)
                    mutate(self._summary_units(proposal))
                    return proposal

                with self.assertRaises(ValidationStageFailure) as context:
                    self._validate(provider)
                self.assertEqual(context.exception.reason, ValidationStageFailureReason.TEXT_COVERAGE_INVALID)

    def test_legacy_writer_quote_shape_is_invalid_response(self) -> None:
        def provider(request):
            proposal = _proposal(request)
            for field in proposal["field_assessments"]:
                field["units"] = [
                    {"writer_quote": "x", "assessment": unit["assessment"], "evidence_citations": unit["evidence_citations"]}
                    for unit in field.pop("unit_assessments")
                ]
            return proposal

        with self.assertRaises(ValidationStageFailure) as context:
            self._validate(provider)
        self.assertEqual(context.exception.reason, ValidationStageFailureReason.INVALID_RESPONSE)

    def test_coverage_violation_in_formal_run_is_event_technical_gap(self) -> None:
        gaps = []

        def provider(request):
            proposal = _proposal(request)
            del self._summary_units(proposal)[0]
            return proposal

        validation = self._validate(provider, hook=gaps.append)
        self.assertEqual((validation.pass_count, len(validation.failed)), (0, 0))
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].kind, TechnicalGapKind.PROPOSAL_CONTRACT_VIOLATION)
        self.assertEqual(gaps[0].failure_class, "TEXT_COVERAGE_INVALID")


if __name__ == "__main__":
    import unittest

    unittest.main()
