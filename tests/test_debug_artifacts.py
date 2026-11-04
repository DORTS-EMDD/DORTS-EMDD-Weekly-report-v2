"""F4 (contract section S, AGENTS.md section 14): Developer Debug and Engineering Summary.

Both files come from one run's already-produced result and the same RunTrace;
they are observations only. Nothing in production reads them, and a failure to
build them never changes the report or the exit code.
"""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import patch

import main  # puts src on sys.path, as the CLI does
from weekly_report.contracts import RegionMode
from weekly_report.debug_service import ExecutionTrace, debug_artifact_names, execution_trace
from weekly_report.delivery import DeliveryIdentity, DeliveryReceipt, DeliveryStatus
from weekly_report.production_runner import ProductionRunResult, ProductionRunStatus
from weekly_report.report_service import FinalReportArtifact, ReportDisclosure

ROOT = Path(__file__).resolve().parents[1]
RECIPIENT = "reader@example.test"
PERIOD = (date(2026, 10, 27), date(2026, 11, 2))
REQUIRED = (
    "run", "config", "search_coverage", "candidate_counts", "dedup", "event_counts",
    "top_rejection_reasons", "provider_failures", "validation_failures", "final_events",
    "artifacts", "declared_maiagent_role_version",
)


def _result() -> ProductionRunResult:
    artifact = FinalReportArtifact(
        "weekly-report-a1b2c3d4e5f60718", "formal-report-a1b2", "v1", (), (),
        "本期正式報告無事件。\n", ReportDisclosure(technical_gap_count=1), PERIOD[0], PERIOD[1],
    )
    receipt = DeliveryReceipt(
        DeliveryIdentity(artifact.report_id, artifact.artifact_id, "v1", RECIPIENT),
        DeliveryStatus.FAILED, (), error="delivery sender failed",
        failure_signature="LOGIN:SMTPAuthenticationError:535", recipient_counts={"not_reached": 1},
    )
    return ProductionRunResult(
        ProductionRunStatus.SUCCESS_WITH_TECHNICAL_GAPS, PERIOD[0], PERIOD[1], RegionMode.SELECTED,
        {
            "search_plan": 122, "search_attempts": 122, "search_unattempted": 0, "evidence_results": 330,
            "technical_gaps_evidence": 6, "temporal_results": 89, "event_identity_records": 69,
            "category_results": 40, "technical_gaps_category": 1, "ordered_results": 31, "formal_metadata": 19,
            "writer_blocks": 19, "validation_passed": 18, "validation_failed": 1, "final_report_events": 0,
            "technical_gaps": 7, "metadata_exclusions": 12,
        },
        final_report=artifact, delivery_result=receipt, search_failure_count=0,
        evidence_ready_count=136, evidence_rejected_count=194,
        evidence_reject_reason_distribution={"SOURCE_PAGE_MISMATCH": 142, "CONTENT_UNAVAILABLE": 48},
        technical_gap_signature_distribution={"Scope:SUBJECT:PROPOSAL_CONTRACT_VIOLATION:ENDPOINT_LABEL": 6},
        selection_audit={"audit_version": "selection-audit-v2", "candidates": []},
    )


class DebugArtifactTests(TestCase):
    def _write(self, result):
        directory = Path(tempfile.mkdtemp())
        lines: list[str] = []
        with execution_trace(ExecutionTrace(sink=lines.append)) as trace:
            ok = main._write_outputs(directory, result)
        return directory, trace, ok

    def test_both_files_come_from_one_run_trace_with_the_required_fields(self):
        result = _result()
        directory, trace, ok = self._write(result)
        self.assertTrue(ok)
        debug_name, summary_name = debug_artifact_names(PERIOD[1])
        self.assertEqual((debug_name, summary_name), ("developer_debug_weekly_2026-11-02.json", "engineering_summary_weekly_2026-11-02.json"))
        debug = json.loads((directory / debug_name).read_text(encoding="utf-8"))
        summary = json.loads((directory / summary_name).read_text(encoding="utf-8"))
        for document in (debug, summary):
            self.assertEqual(document["run"]["run_id"], trace.run_id)
            self.assertEqual(document["run"]["report_id"], result.final_report.report_id)
        for key in REQUIRED:
            self.assertIn(key, summary)
        # Candidate counts and Event counts stay separate.
        self.assertEqual(summary["candidate_counts"]["discovered"], 336)
        self.assertEqual(summary["dedup"]["events"], 41)
        self.assertEqual(summary["event_counts"]["validated"], 18)
        self.assertIsNone(summary["declared_maiagent_role_version"])
        self.assertEqual(debug["candidate_forensic_trace"], {"file": "selection_audit.json", "audit_version": "selection-audit-v2"})
        self.assertEqual(summary["artifacts"]["files"]["report_pdf"], "weekly-report-a1b2c3d4e5f60718.pdf")

    def test_no_recipient_or_secret_reaches_the_debug_files(self):
        directory, _, _ = self._write(_result())
        for name in debug_artifact_names(PERIOD[1]):
            text = (directory / name).read_text(encoding="utf-8")
            self.assertNotIn(RECIPIENT, text)
            self.assertNotIn("example.test", text)

    def test_a_debug_failure_changes_neither_the_report_nor_the_outcome(self):
        result = _result()
        baseline, _, baseline_ok = self._write(result)
        with patch("weekly_report.debug_service.build_engineering_summary", side_effect=RuntimeError("boom")):
            broken, _, broken_ok = self._write(result)
        self.assertEqual(baseline_ok, broken_ok)
        for name in ("run_summary.txt", "selection_audit.json", "weekly-report-a1b2c3d4e5f60718.md"):
            self.assertEqual((baseline / name).read_bytes(), (broken / name).read_bytes(), name)
        _, summary_name = debug_artifact_names(PERIOD[1])
        self.assertEqual(json.loads((broken / summary_name).read_text(encoding="utf-8"))["unavailable"], "RuntimeError")

    def test_the_cli_exit_code_does_not_depend_on_debug_output(self):
        class FakeRunner:
            @classmethod
            def from_environment(cls):
                return cls()

            def run(self, **kwargs):
                return _result()

        from contextlib import nullcontext

        codes = []
        for broken in (False, True):
            debug = patch("weekly_report.debug_service.build_developer_debug", side_effect=RuntimeError("boom"))
            with tempfile.TemporaryDirectory() as directory, patch.object(main, "ProductionRunner", FakeRunner):
                with debug if broken else nullcontext():
                    codes.append(main.main(["--output-dir", directory]))
        self.assertEqual(codes[0], codes[1])

    def test_no_production_owner_reads_the_debug_artifacts(self):
        package = ROOT / "src" / "weekly_report"
        for source in package.glob("*.py"):
            if source.name == "debug_service.py":
                continue
            text = source.read_text(encoding="utf-8")
            for name in ("build_developer_debug", "build_engineering_summary", "debug_artifact_names", "developer_debug_", "engineering_summary_"):
                self.assertNotIn(name, text, source.name)
