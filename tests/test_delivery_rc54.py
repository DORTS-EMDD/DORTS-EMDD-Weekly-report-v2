"""RC-54: a FAILED delivery records where the send attempt stopped.

Observation only (contract section S, provider diagnostics); every section
A.20 Delivery rule is unchanged.

Run 41585675879 reported ``delivery=FAILED`` with nothing else: the sender's
exception was replaced by fixed text, so a login rejection, a partial refusal
and an error after the server accepted the message looked the same. The
receipt now carries ``PHASE:ExceptionType[:SMTP code]``; never server text, a
credential or an address. Status, ledger and exit code are unchanged.
"""

from __future__ import annotations

from datetime import date
import json
import smtplib
from unittest import TestCase
from unittest.mock import patch

from src.weekly_report.contracts import RegionMode
from src.weekly_report.debug_service import ExecutionTrace, execution_trace, observe_stage
from src.weekly_report.delivery import (
    DeliveryFailurePhase,
    DeliveryIdentity,
    DeliveryLedger,
    DeliveryReceipt,
    DeliveryService,
    DeliveryStatus,
)
from src.weekly_report.gmail_smtp import GmailSmtpConfig, GmailSmtpError, GmailSmtpSender
from src.weekly_report.production_runner import ProductionRunResult, ProductionRunStatus
from src.weekly_report.report_service import FinalReportArtifact

SECRET = "app-secret"
RECIPIENTS = "first@example.com, second@example.com"


class _Smtp:
    """A fake Gmail server; ``failure`` names the step that goes wrong."""

    failure = ""
    sent = 0

    def __init__(self, host, port, *, context, timeout):
        if self.failure == "connect":
            raise TimeoutError("timed out")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        if self.failure == "quit":
            raise smtplib.SMTPResponseException(451, b"4.3.0 temporary failure for first@example.com")
        return False

    def login(self, user, password):
        if self.failure == "login":
            raise smtplib.SMTPAuthenticationError(535, b"5.7.8 Username and Password not accepted " + SECRET.encode())

    def sendmail(self, sender, recipients, message):
        if self.failure == "all_refused":
            raise smtplib.SMTPRecipientsRefused({address: (550, b"5.1.1 unknown") for address in recipients})
        type(self).sent += 1
        if self.failure == "partial":
            return {recipients[-1]: (550, b"5.1.1 unknown")}
        return {}


def _artifact() -> FinalReportArtifact:
    return FinalReportArtifact(
        "weekly-report-a1b2c3d4e5f60718", "artifact-001", "v1", (), (), "本期無符合正式報導條件之事件。",
        period_start=date(2026, 10, 27), period_end=date(2026, 11, 3),
    )


class FailureSignatureTests(TestCase):
    def _deliver(self, failure, ledger_dir=None):
        _Smtp.failure, _Smtp.sent = failure, 0
        ledger = DeliveryLedger(f"{ledger_dir}/ledger.json") if ledger_dir else None
        service = DeliveryService(sender=GmailSmtpSender(GmailSmtpConfig("sender@example.com", SECRET)), live_email_send=True, ledger=ledger)
        with (
            patch("src.weekly_report.gmail_smtp.ssl.create_default_context", return_value=object()),
            patch("src.weekly_report.gmail_smtp.smtplib.SMTP_SSL", _Smtp),
        ):
            return service.deliver(_artifact(), RECIPIENTS)

    def test_each_smtp_phase_has_its_own_signature(self):
        expected = {
            "connect": ("CONNECT:TimeoutError", 0),
            "login": ("LOGIN:SMTPAuthenticationError:535", 0),
            "all_refused": ("SENDMAIL:SMTPRecipientsRefused", 0),
            "partial": ("REFUSED:RecipientsPartiallyRefused", 1),
            "quit": ("QUIT:SMTPResponseException:451", 1),
        }
        for failure, (signature, sent) in expected.items():
            with self.subTest(failure):
                receipt = self._deliver(failure)
                self.assertEqual(receipt.status, DeliveryStatus.FAILED)
                self.assertEqual(receipt.error, "delivery sender failed")
                self.assertEqual(receipt.failure_signature, signature)
                # QUIT and REFUSED: the server had accepted the message.
                self.assertEqual(_Smtp.sent, sent)

    def test_the_signature_never_carries_server_text_credentials_or_addresses(self):
        for failure in ("login", "all_refused", "partial", "quit"):
            with self.subTest(failure):
                receipt = self._deliver(failure)
                text = f"{receipt.error} {receipt.failure_signature}"
                for forbidden in (SECRET, "@", "Password", "unknown", "temporary"):
                    self.assertNotIn(forbidden, text)

    def test_a_report_that_cannot_be_rendered_fails_in_the_message_phase(self):
        with patch("src.weekly_report.gmail_smtp.render_report_pdf", side_effect=RuntimeError("no font")):
            receipt = self._deliver("")
        self.assertEqual(receipt.failure_signature, "MESSAGE:RuntimeError")
        self.assertEqual(_Smtp.sent, 0)

    def test_the_sender_error_keeps_its_phase(self):
        _Smtp.failure = "login"
        sender = GmailSmtpSender(GmailSmtpConfig("sender@example.com", SECRET))
        with (
            patch("src.weekly_report.gmail_smtp.ssl.create_default_context", return_value=object()),
            patch("src.weekly_report.gmail_smtp.smtplib.SMTP_SSL", _Smtp),
            self.assertRaises(GmailSmtpError) as raised,
        ):
            sender(_artifact(), RECIPIENTS)
        self.assertIs(raised.exception.phase, DeliveryFailurePhase.LOGIN)
        self.assertEqual((raised.exception.failure_class, raised.exception.smtp_code), ("SMTPAuthenticationError", 535))

    def test_any_other_sender_failure_is_a_sender_phase_signature(self):
        def sender(artifact, recipient_target):
            raise ValueError("first@example.com rejected")

        receipt = DeliveryService(sender=sender, live_email_send=True).deliver(_artifact(), RECIPIENTS)
        self.assertEqual(receipt.failure_signature, "SENDER:ValueError")

    def test_status_ledger_and_success_are_unchanged(self):
        import os
        import tempfile

        for failure in ("login", "quit"):
            with self.subTest(failure), tempfile.TemporaryDirectory() as directory:
                self.assertEqual(self._deliver(failure, directory).status, DeliveryStatus.FAILED)
                # A FAILED attempt still records nothing (section A.20).
                self.assertFalse(os.path.exists(f"{directory}/ledger.json"))
        receipt = self._deliver("")
        self.assertEqual((receipt.status, receipt.failure_signature), (DeliveryStatus.SENT, None))

    def test_a_receipt_rejects_an_unsafe_or_misplaced_signature(self):
        identity = DeliveryIdentity("r", "a", "v1", "target")
        for signature in ("LOGIN:a@b", "LOGIN:SMTPAuthenticationError 535 text", "NOWHERE:TimeoutError", "LOGIN:Error:999"):
            with self.subTest(signature), self.assertRaises(ValueError):
                DeliveryReceipt(identity, DeliveryStatus.FAILED, (), failure_signature=signature)
        with self.assertRaises(ValueError):
            DeliveryReceipt(identity, DeliveryStatus.SENT, (), failure_signature="QUIT:SMTPResponseException:451")


class FailureObservationTests(TestCase):
    def test_the_run_summary_and_trace_show_the_signature(self):
        receipt = DeliveryReceipt(
            DeliveryIdentity("r", "a", "v1", "target"), DeliveryStatus.FAILED, (),
            error="delivery sender failed", failure_signature="LOGIN:SMTPAuthenticationError:535",
        )
        result = ProductionRunResult(
            ProductionRunStatus.SUCCESS, date(2026, 10, 27), date(2026, 11, 3), RegionMode.SELECTED, {},
            final_report=_artifact(), delivery_result=receipt,
        )
        self.assertIn("delivery=FAILED delivery_failure=LOGIN:SMTPAuthenticationError:535", result.summary())

        lines: list[str] = []
        with execution_trace(ExecutionTrace(sink=lines.append)):
            with observe_stage("Delivery", 1) as observation:
                observation.observe(receipt, final=True)
        completed = [json.loads(line) for line in lines if '"STAGE_COMPLETED"' in line]
        self.assertEqual(completed[-1]["reason_distribution"], {"LOGIN:SMTPAuthenticationError:535": 1})
        self.assertEqual(completed[-1]["terminal_distribution"], {"FAILED": 1})
