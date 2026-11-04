"""RC-54: a FAILED delivery records where the send attempt stopped.

Observation only (contract section S, provider diagnostics). Since RC-55
(section A.39) the signature also tells Delivery nothing it decides on except
the explicit SMTP refusals listed there; it never carries server text, a
credential or an address.
"""

from __future__ import annotations

from datetime import date
import json
import smtplib
from unittest import TestCase
from unittest.mock import patch

from tests.delivery_fakes import Clock, FakeLedgerStore, PERIOD, service
from src.weekly_report.contracts import RegionMode
from src.weekly_report.debug_service import ExecutionTrace, execution_trace, observe_stage
from src.weekly_report.delivery import (
    DeliveryFailurePhase,
    DeliveryIdentity,
    DeliveryReceipt,
    DeliveryService,
    DeliveryStatus,
)
from src.weekly_report.delivery_ledger import EntryState
from src.weekly_report.gmail_smtp import GmailSmtpConfig, GmailSmtpError, GmailSmtpSender
from src.weekly_report.production_runner import ProductionRunResult, ProductionRunStatus
from src.weekly_report.report_service import FinalReportArtifact

SECRET = "app-secret"
RECIPIENT = "first@example.com"


class _Smtp:
    """A fake Gmail server; ``failure`` names the step that goes wrong."""

    failure = ""
    sent = 0

    def __init__(self, host, port, *, context, timeout):
        if self.failure == "connect":
            raise TimeoutError("timed out")

    def login(self, user, password):
        if self.failure == "login":
            raise smtplib.SMTPAuthenticationError(535, b"5.7.8 Username and Password not accepted " + SECRET.encode())

    def sendmail(self, sender, recipients, message):
        if self.failure == "all_refused":
            raise smtplib.SMTPRecipientsRefused({address: (550, b"5.1.1 unknown") for address in recipients})
        if self.failure == "data":
            raise smtplib.SMTPDataError(554, b"5.7.1 rejected for first@example.com")
        if self.failure == "disconnect":
            raise smtplib.SMTPServerDisconnected("Connection unexpectedly closed")
        type(self).sent += 1
        return {}

    def quit(self):
        if self.failure == "quit":
            raise smtplib.SMTPResponseException(451, b"4.3.0 temporary failure for first@example.com")

    def close(self):
        pass


def _artifact() -> FinalReportArtifact:
    return FinalReportArtifact(
        "weekly-report-a1b2c3d4e5f60718", "artifact-001", "v1", (), (), "本期無符合正式報導條件之事件。",
        period_start=PERIOD[0], period_end=PERIOD[1],
    )


class FailureSignatureTests(TestCase):
    def _deliver(self, failure):
        _Smtp.failure, _Smtp.sent = failure, 0
        self.store = FakeLedgerStore()
        sender = GmailSmtpSender(GmailSmtpConfig("sender@example.com", SECRET))
        with (
            patch("src.weekly_report.gmail_smtp.ssl.create_default_context", return_value=object()),
            patch("src.weekly_report.gmail_smtp.smtplib.SMTP_SSL", _Smtp),
        ):
            return service(self.store, sender, Clock(), "run1").deliver(_artifact(), RECIPIENT)

    def _state(self):
        entries = self.store.entries()
        return None if not entries else next(iter(entries.values())).state

    def test_each_smtp_phase_has_its_own_signature(self):
        expected = {
            "connect": ("CONNECT:TimeoutError", 0, None),
            "login": ("LOGIN:SMTPAuthenticationError:535", 0, None),
            "all_refused": ("SENDMAIL:SMTPRecipientsRefused", 0, EntryState.NOT_SENT),
            "data": ("SENDMAIL:SMTPDataError:554", 0, EntryState.NOT_SENT),
            "disconnect": ("SENDMAIL:SMTPServerDisconnected", 0, EntryState.ATTEMPTED),
        }
        for failure, (signature, sent, state) in expected.items():
            with self.subTest(failure):
                receipt = self._deliver(failure)
                self.assertEqual(receipt.status, DeliveryStatus.FAILED)
                self.assertEqual(receipt.error, "delivery sender failed")
                self.assertEqual(receipt.failure_signature, signature)
                self.assertEqual(_Smtp.sent, sent)
                self.assertEqual(self._state(), state)

    def test_an_error_at_quit_after_the_handoff_is_only_a_diagnostic(self):
        receipt = self._deliver("quit")
        self.assertEqual((receipt.status, _Smtp.sent), (DeliveryStatus.SENT, 1))
        self.assertEqual(receipt.diagnostic, "QUIT:SMTPResponseException:451")
        self.assertEqual(self._state(), EntryState.SENT)

    def test_the_signature_never_carries_server_text_credentials_or_addresses(self):
        for failure in ("login", "all_refused", "data", "disconnect", "quit"):
            with self.subTest(failure):
                receipt = self._deliver(failure)
                signatures = f"{receipt.error} {receipt.failure_signature} {receipt.diagnostic}"
                for forbidden in (SECRET, "@", "Password", "unknown", "temporary", "rejected"):
                    self.assertNotIn(forbidden, signatures)
                # Claim lines use "@" only between entry reference and run.
                claims = " ".join(receipt.attempted_claims)
                for forbidden in (SECRET, RECIPIENT, "example.com"):
                    self.assertNotIn(forbidden, claims)

    def test_a_report_that_cannot_be_rendered_fails_in_the_message_phase(self):
        with patch("src.weekly_report.gmail_smtp.render_report_pdf", side_effect=RuntimeError("no font")):
            receipt = self._deliver("")
        self.assertEqual(receipt.failure_signature, "MESSAGE:RuntimeError")
        self.assertEqual((_Smtp.sent, self.store.files), (0, {}))

    def test_the_sender_error_keeps_its_phase(self):
        _Smtp.failure = "login"
        sender = GmailSmtpSender(GmailSmtpConfig("sender@example.com", SECRET))
        with (
            patch("src.weekly_report.gmail_smtp.ssl.create_default_context", return_value=object()),
            patch("src.weekly_report.gmail_smtp.smtplib.SMTP_SSL", _Smtp),
            self.assertRaises(GmailSmtpError) as raised,
        ):
            sender.open(_artifact(), (RECIPIENT,))
        self.assertIs(raised.exception.phase, DeliveryFailurePhase.LOGIN)
        self.assertEqual((raised.exception.failure_class, raised.exception.smtp_code), ("SMTPAuthenticationError", 535))

    def test_any_other_sender_failure_is_a_sender_phase_signature(self):
        class Broken:
            def recipients(self, target):
                return (RECIPIENT,)

            def open(self, artifact, addresses):
                raise ValueError("first@example.com rejected")

        receipt = service(FakeLedgerStore(), Broken(), Clock(), "run1").deliver(_artifact(), RECIPIENT)
        self.assertEqual(receipt.failure_signature, "SENDER:ValueError")

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
            recipient_counts={"not_reached": 1}, attempted_claims=(f"{'a' * 16}@run1|age=0h|HANDOFF_UNKNOWN",),
        )
        result = ProductionRunResult(
            ProductionRunStatus.SUCCESS, date(2026, 10, 27), date(2026, 11, 3), RegionMode.SELECTED, {},
            final_report=_artifact(), delivery_result=receipt,
        )
        summary = result.summary()
        self.assertIn("delivery=FAILED delivery_failure=LOGIN:SMTPAuthenticationError:535", summary)
        self.assertIn("delivery_recipients=not_reached=1", summary)
        self.assertIn(f"delivery_attempted={'a' * 16}@run1|age=0h|HANDOFF_UNKNOWN", summary)

        lines: list[str] = []
        with execution_trace(ExecutionTrace(sink=lines.append)):
            with observe_stage("Delivery", 1) as observation:
                observation.observe(receipt, final=True)
        completed = [json.loads(line) for line in lines if '"STAGE_COMPLETED"' in line]
        self.assertEqual(completed[-1]["reason_distribution"], {"LOGIN:SMTPAuthenticationError:535": 1})
        self.assertEqual(completed[-1]["terminal_distribution"], {"FAILED": 1})

    def test_staged_delivery_has_no_signature(self):
        receipt = DeliveryService(live_email_send=False).deliver(_artifact(), RECIPIENT)
        self.assertEqual((receipt.status, receipt.failure_signature), (DeliveryStatus.STAGED, None))
