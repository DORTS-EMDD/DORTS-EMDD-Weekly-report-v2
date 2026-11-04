from __future__ import annotations

from unittest import TestCase

from src.weekly_report.delivery import DeliveryService, DeliveryStatus
from src.weekly_report.report_service import ReportService
from src.weekly_report.validator import Validator
from src.weekly_report.writer import WriterReportBlock

from test_report_service import _semantic_provider, _workflow_result


class DeliveryServiceTests(TestCase):
    def _validation(self):
        result = _workflow_result()
        metadata = ReportService().project_formal_metadata((result,))
        return Validator(semantic_provider=_semantic_provider).validate(
            (result,), metadata,
            (WriterReportBlock("E1", "事件標題", "事件摘要 Taiwan Metro", "可供臺北捷運評估規劃方向"),),
        )

    def _artifact(self):
        return ReportService().assemble_final_report(self._validation())

    def test_default_delivery_is_staged_without_real_email(self) -> None:
        receipt = DeliveryService().deliver(self._artifact(), "staging@example.test")
        self.assertEqual(receipt.status, DeliveryStatus.STAGED)
        self.assertFalse(receipt.successful)

    def test_stable_identity_prevents_duplicate_success(self) -> None:
        # RC-55: the shared handoff ledger, not process memory, stops a resend.
        from datetime import date

        from tests.delivery_fakes import Clock, FakeLedgerStore, FakeSender, service

        store, clock = FakeLedgerStore(), Clock()
        artifact = ReportService().assemble_final_report(
            self._validation(), period=(date(2026, 10, 27), date(2026, 11, 2))
        )
        first_sender, second_sender = FakeSender(), FakeSender()
        first = service(store, first_sender, clock, "run1").deliver(artifact, "a@example.test")
        second = service(store, second_sender, clock, "run2").deliver(artifact, "a@example.test")
        self.assertEqual(first.status, DeliveryStatus.SENT)
        self.assertEqual(second.status, DeliveryStatus.DUPLICATE)
        self.assertEqual((first_sender.delivered, second_sender.delivered), (["a@example.test"], []))
        self.assertEqual(first.event_ids, ("E1",))

    def test_failed_delivery_does_not_change_artifact(self) -> None:
        from datetime import date

        from tests.delivery_fakes import Clock, FakeLedgerStore, FakeSender, login_failure, service

        artifact = ReportService().assemble_final_report(
            self._validation(), period=(date(2026, 10, 27), date(2026, 11, 2))
        )
        content = artifact.content
        receipt = service(FakeLedgerStore(), FakeSender(open_error=login_failure()), Clock(), "run1").deliver(
            artifact, "a@example.test"
        )
        self.assertEqual(receipt.status, DeliveryStatus.FAILED)
        self.assertEqual(artifact.content, content)

if __name__ == "__main__":
    import unittest

    unittest.main()
