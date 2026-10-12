from __future__ import annotations

from unittest import TestCase

from src.weekly_report.report_service import ReportService
from src.weekly_report.validator import (
    ValidationStageFailure,
    ValidationStageFailureReason,
    Validator,
)
from src.weekly_report.writer import WriterReportBlock

from test_report_service import _workflow_result


def _metadata(result):
    return ReportService().project_formal_metadata((result,))[0]


def _block(event_id: str = "E1", *, headline: str = "Taiwan", summary: str = "Metro", insight: str = "Taipei") -> WriterReportBlock:
    return WriterReportBlock(event_id, headline, summary, insight)


def _proposal(request, *, assessment_overrides=None, language_overrides=None):
    assessment_overrides = assessment_overrides or {}
    language_overrides = language_overrides or {}
    source = request.evidence_sources[0]
    fields = []
    for field_name, value in request.writer_prose.as_mapping().items():
        fields.append(
            {
                "field_name": field_name,
                "language_assessment": language_overrides.get(field_name, "TRADITIONAL_CHINESE"),
                "units": [
                    {
                        "writer_quote": value,
                        "assessment": assessment_overrides.get(field_name, "ANALYSIS" if field_name == "taipei_insight" else "SUPPORTED"),
                        "evidence_citations": [
                            {"candidate_id": source.candidate_id, "exact_quote": source.substantive_content}
                        ],
                    }
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
            proposal["field_assessments"][0]["units"][0]["evidence_citations"][0]["exact_quote"] = "missing"
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
            proposal["field_assessments"][0]["units"][0]["evidence_citations"] = []
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


if __name__ == "__main__":
    import unittest

    unittest.main()
