from __future__ import annotations

from unittest import TestCase

from src.weekly_report.delivery import DeliveryService, DeliveryStatus
from src.weekly_report.report_service import ReportService
from src.weekly_report.validator import Validator
from src.weekly_report.writer import WriterReportBlock

from test_report_service import _workflow_result


class DeliveryServiceTests(TestCase):
    def _artifact(self):
        result = _workflow_result()
        service = ReportService()
        metadata = service.project_formal_metadata((result,))
        validation = Validator().validate(
            (result,), metadata,
            (WriterReportBlock("E1", "事件標題", "事件摘要 Taiwan Metro", "可供臺北捷運評估規劃方向"),),
        )
        return service.assemble_final_report(validation)

    def test_default_delivery_is_staged_without_real_email(self) -> None:
        receipt = DeliveryService().deliver(self._artifact(), "staging@example.test")
        self.assertEqual(receipt.status, DeliveryStatus.STAGED)
        self.assertFalse(receipt.successful)

    def test_stable_identity_prevents_duplicate_success(self) -> None:
        calls = []
        service = DeliveryService(sender=lambda artifact, recipient: calls.append((artifact.artifact_id, recipient)), live_email_send=True)
        artifact = self._artifact()
        first = service.deliver(artifact, "a@example.test")
        second = service.deliver(artifact, "a@example.test")
        self.assertEqual(first.status, DeliveryStatus.SENT)
        self.assertEqual(second.status, DeliveryStatus.DUPLICATE)
        self.assertEqual(len(calls), 1)
        self.assertEqual(first.event_ids, ("E1",))

    def test_failed_delivery_does_not_change_artifact(self) -> None:
        artifact = self._artifact()
        service = DeliveryService(sender=lambda *_: (_ for _ in ()).throw(RuntimeError()), live_email_send=True)
        receipt = service.deliver(artifact, "a@example.test")
        self.assertEqual(receipt.status, DeliveryStatus.FAILED)
        self.assertEqual(artifact.content, self._artifact().content)


if __name__ == "__main__":
    import unittest

    unittest.main()
