"""RC-26: reporting period, readable subject and durable delivery record."""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from src.weekly_report.delivery import DeliveryLedger, DeliveryService, DeliveryStatus
from src.weekly_report.gmail_smtp import subject_for_artifact
from src.weekly_report.production_runner import ProductionConfigurationError, _delivery_configuration
from src.weekly_report.report_service import ReportService
from src.weekly_report.validator import Validator
from src.weekly_report.writer import WriterReportBlock

from test_report_service import _semantic_provider, _workflow_result

PERIOD = (date(2026, 10, 14), date(2026, 10, 20))


def _artifact(period=PERIOD, summary="事件摘要 Taiwan Metro"):
    result = _workflow_result()
    service = ReportService()
    metadata = service.project_formal_metadata((result,))
    validation = Validator(semantic_provider=_semantic_provider).validate(
        (result,), metadata,
        (WriterReportBlock("E1", "事件標題", summary, "可供臺北捷運評估規劃方向"),),
    )
    return service.assemble_final_report(validation, period=period)


class ReportPeriodTests(TestCase):
    def test_period_is_on_the_artifact_in_the_header_and_in_the_identity(self) -> None:
        artifact = _artifact()
        self.assertEqual((artifact.period_start, artifact.period_end), PERIOD)
        self.assertEqual(artifact.content.split("\n")[:2], ["捷運技術週報", "報告期間：2026-10-14～2026-10-20"])
        other_week = _artifact(period=(date(2026, 10, 21), date(2026, 10, 27)))
        self.assertNotEqual(artifact.report_id, other_week.report_id)

    def test_without_a_period_the_header_is_unchanged(self) -> None:
        artifact = _artifact(period=None)
        self.assertIsNone(artifact.period_display)
        self.assertEqual(artifact.content.split("\n")[:2], ["捷運技術週報", ""])

    def test_subject_names_period_and_event_count(self) -> None:
        self.assertEqual(subject_for_artifact(_artifact()), "捷運技術週報｜2026-10-14～2026-10-20｜1 則")


class DeliveryLedgerTests(TestCase):
    def setUp(self) -> None:
        import tempfile

        self._directory = tempfile.TemporaryDirectory()
        self.path = Path(self._directory.name) / "ledger" / "delivery.json"

    def tearDown(self) -> None:
        self._directory.cleanup()

    def _service(self, calls):
        return DeliveryService(
            sender=lambda artifact, recipient: calls.append(artifact.artifact_id),
            live_email_send=True,
            ledger=DeliveryLedger(self.path),
        )

    def test_rerun_of_the_same_period_is_a_duplicate_even_with_a_new_artifact(self) -> None:
        calls = []
        first = self._service(calls).deliver(_artifact(), "team@example.test")
        # A new process (automation rerun) rebuilds a different artifact.
        rebuilt = _artifact(summary="事件摘要 Taiwan Metro 重新產生")
        self.assertNotEqual(rebuilt.artifact_id, first.identity.artifact_id)
        second = self._service(calls).deliver(rebuilt, "team@example.test")
        self.assertEqual((first.status, second.status), (DeliveryStatus.SENT, DeliveryStatus.DUPLICATE))
        self.assertEqual(len(calls), 1)

    def test_other_recipient_or_period_is_not_blocked(self) -> None:
        calls = []
        self._service(calls).deliver(_artifact(), "team@example.test")
        other_recipient = self._service(calls).deliver(_artifact(), "other@example.test")
        next_week = self._service(calls).deliver(
            _artifact(period=(date(2026, 10, 21), date(2026, 10, 27))), "team@example.test"
        )
        self.assertEqual((other_recipient.status, next_week.status), (DeliveryStatus.SENT, DeliveryStatus.SENT))

    def test_failed_or_staged_sends_are_not_recorded_and_no_address_is_stored(self) -> None:
        def fail(artifact, recipient):
            raise RuntimeError("smtp down")

        failed = DeliveryService(sender=fail, live_email_send=True, ledger=DeliveryLedger(self.path))
        self.assertEqual(failed.deliver(_artifact(), "team@example.test").status, DeliveryStatus.FAILED)
        staged = DeliveryService(live_email_send=False, ledger=DeliveryLedger(self.path))
        self.assertEqual(staged.deliver(_artifact(), "team@example.test").status, DeliveryStatus.STAGED)
        self.assertFalse(self.path.exists())
        self._service([]).deliver(_artifact(), "team@example.test")
        stored = self.path.read_text(encoding="utf-8")
        self.assertNotIn("team@example.test", stored)
        self.assertEqual(json.loads(stored)["sent"][0]["period"], "2026-10-14～2026-10-20")

    def test_malformed_ledger_stops_live_composition(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{\"sent\": 3}", encoding="utf-8")
        environ = {
            "LIVE_EMAIL_SEND": "1",
            "DEFAULT_RECIPIENTS": "team@example.test",
            "GMAIL_USER": "sender@example.test",
            "GMAIL_APP_PASS": "app-secret",
            "DELIVERY_LEDGER_PATH": str(self.path),
        }
        with self.assertRaises(ProductionConfigurationError):
            _delivery_configuration(environ)
        self.path.unlink()
        service, recipient = _delivery_configuration(environ)
        self.assertEqual(recipient, "team@example.test")
        self.assertIsNotNone(service._ledger)


class CliDeliveryExitTests(TestCase):
    def test_failed_live_delivery_makes_the_cli_fail(self) -> None:
        import main

        failed = SimpleNamespace(status=DeliveryStatus.FAILED)
        result = SimpleNamespace(successful=True, complete=True, delivery_result=failed, summary=lambda: "status=SUCCESS")

        class FakeRunner:
            @classmethod
            def from_environment(cls):
                return cls()

            def run(self, **kwargs):
                return result

        with patch.object(main, "ProductionRunner", FakeRunner):
            self.assertEqual(main.main(["--period-start", "2026-10-14", "--period-end", "2026-10-20"]), 1)
