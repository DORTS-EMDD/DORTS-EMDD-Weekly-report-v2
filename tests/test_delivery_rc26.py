"""RC-26: reporting period, readable subject and exit code.

The durable delivery record of RC-26 is replaced by the RC-55 handoff ledger
(section A.39, tests/test_delivery_rc55.py); its composition is tested here.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from src.weekly_report.delivery import DeliveryStatus
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


class DeliveryCompositionTests(TestCase):
    """RC-55: live email is composed only with the shared handoff ledger."""

    LIVE = {
        "LIVE_EMAIL_SEND": "1",
        "DEFAULT_RECIPIENTS": "team@example.test",
        "GMAIL_USER": "sender@example.test",
        "GMAIL_APP_PASS": "app-secret",
        "DELIVERY_LEDGER_REPOSITORY": "DORTS-EMDD/delivery-ledger",
        "DELIVERY_LEDGER_TOKEN": "ledger-token",
        "DELIVERY_LEDGER_KEY": "k" * 40,
        # Every delivery setting is explicit, so no local .env value is read.
        "DELIVERY_RELEASE_PERIOD": "",
        "DELIVERY_RELEASE_CLAIMS": "",
    }

    def test_live_email_needs_every_ledger_setting(self) -> None:
        for missing in ("DELIVERY_LEDGER_REPOSITORY", "DELIVERY_LEDGER_TOKEN", "DELIVERY_LEDGER_KEY"):
            with self.subTest(missing), self.assertRaises(ProductionConfigurationError):
                _delivery_configuration({**self.LIVE, missing: ""})
        with self.assertRaises(ProductionConfigurationError):
            _delivery_configuration({**self.LIVE, "DELIVERY_LEDGER_KEY": "too-short"})
        service, recipient = _delivery_configuration(self.LIVE)
        self.assertEqual(recipient, "team@example.test")
        self.assertTrue(service.live_email_send)

    def test_staged_composition_needs_no_ledger(self) -> None:
        service, _ = _delivery_configuration({"LIVE_EMAIL_SEND": "0", "DEFAULT_RECIPIENTS": "team@example.test"})
        self.assertFalse(service.live_email_send)

    def test_release_input_is_parsed_and_a_scheduled_run_never_releases(self) -> None:
        release = {
            "DELIVERY_RELEASE_PERIOD": "2026-10-27..2026-11-02",
            "DELIVERY_RELEASE_CLAIMS": f"{'a' * 16}@run1",
        }
        manual, _ = _delivery_configuration({**self.LIVE, **release, "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_ACTOR": "operator"})
        scheduled, _ = _delivery_configuration({**self.LIVE, **release, "GITHUB_EVENT_NAME": "schedule"})
        self.assertTrue(manual._release.manual)
        self.assertEqual(manual._release.actor, "operator")
        self.assertFalse(scheduled._release.manual)
        with self.assertRaises(ProductionConfigurationError):
            _delivery_configuration({**self.LIVE, "DELIVERY_RELEASE_PERIOD": "2026-10-27..2026-11-02", "DELIVERY_RELEASE_CLAIMS": "team@example.test"})


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
