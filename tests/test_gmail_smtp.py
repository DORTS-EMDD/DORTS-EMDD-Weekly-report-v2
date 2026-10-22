from __future__ import annotations

from email import policy
from email.parser import Parser
from unittest import TestCase
from unittest.mock import patch

from src.weekly_report.delivery import DeliveryService, DeliveryStatus
from src.weekly_report.gmail_smtp import (
    GMAIL_SMTP_HOST,
    GMAIL_SMTP_PORT,
    GmailSmtpConfigurationError,
    GmailSmtpError,
    GmailSmtpConfig,
    GmailSmtpSender,
    parse_recipient_target,
)
from src.weekly_report.production_runner import (
    ProductionConfigurationError,
    _delivery_configuration,
)
from src.weekly_report.report_service import FinalReportArtifact


class _FakeSmtp:
    instances: list["_FakeSmtp"] = []
    refused: dict[str, tuple[int, str]] = {}
    error: Exception | None = None

    def __init__(self, host, port, *, context, timeout):
        self.host = host
        self.port = port
        self.context = context
        self.timeout = timeout
        self.login_calls: list[tuple[str, str]] = []
        self.sendmail_calls: list[tuple[str, list[str], str]] = []
        self.__class__.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def login(self, user, password):
        self.login_calls.append((user, password))

    def sendmail(self, sender, recipients, message):
        self.sendmail_calls.append((sender, recipients, message))
        if self.__class__.error is not None:
            raise self.__class__.error
        return dict(self.__class__.refused)


class GmailSmtpTests(TestCase):
    def setUp(self):
        _FakeSmtp.instances = []
        _FakeSmtp.refused = {}
        _FakeSmtp.error = None

    @staticmethod
    def _artifact() -> FinalReportArtifact:
        return FinalReportArtifact(
            "weekly-report-a1b2c3d4e5f60718",
            "artifact-001",
            "v1",
            (),
            (),
            "標題\n完整的繁體中文週報內容\n",
        )

    def test_sender_uses_secure_gmail_endpoint_and_preserves_utf8_content(self):
        context = object()
        sender = GmailSmtpSender(GmailSmtpConfig("sender@example.com", "app-secret"))
        with (
            patch("src.weekly_report.gmail_smtp.ssl.create_default_context", return_value=context),
            patch("src.weekly_report.gmail_smtp.smtplib.SMTP_SSL", _FakeSmtp),
        ):
            sender(self._artifact(), "first@example.com, second@example.com")

        smtp = _FakeSmtp.instances[0]
        self.assertEqual((smtp.host, smtp.port), (GMAIL_SMTP_HOST, GMAIL_SMTP_PORT))
        self.assertIs(smtp.context, context)
        self.assertEqual(smtp.login_calls, [("sender@example.com", "app-secret")])
        self.assertEqual(smtp.sendmail_calls[0][1], ["first@example.com", "second@example.com"])
        message = Parser(policy=policy.default).parsestr(smtp.sendmail_calls[0][2])
        # RC-26: readable subject; identities travel in headers.
        self.assertEqual(message["Subject"], "捷運技術週報｜weekly-report-a1b2c3d4e5f60718｜0 則")
        self.assertEqual(message["X-Weekly-Report-Id"], "weekly-report-a1b2c3d4e5f60718")
        self.assertEqual(message["X-Weekly-Report-Artifact"], "artifact-001 v1")
        self.assertEqual(message["To"], "first@example.com, second@example.com")
        self.assertEqual(message.get_body(preferencelist=("plain",)).get_content(), self._artifact().content)
        attachments = list(message.iter_attachments())
        self.assertEqual([item.get_filename() for item in attachments], ["weekly-report-a1b2c3d4e5f60718.pdf"])
        self.assertTrue(attachments[0].get_content().startswith(b"%PDF"))

    def test_a_report_that_cannot_be_rendered_is_not_sent(self):
        sender = GmailSmtpSender(GmailSmtpConfig("sender@example.com", "app-secret"))
        with (
            patch("src.weekly_report.gmail_smtp.render_report_pdf", side_effect=RuntimeError("no font")),
            patch("src.weekly_report.gmail_smtp.smtplib.SMTP_SSL", _FakeSmtp),
        ):
            before = len(_FakeSmtp.instances)
            with self.assertRaises(GmailSmtpError):
                sender(self._artifact(), "first@example.com")
        self.assertEqual(len(_FakeSmtp.instances), before)

    def test_recipient_parser_rejects_invalid_targets(self):
        self.assertEqual(parse_recipient_target("Name <a@example.com>, b@example.com"), ("a@example.com", "b@example.com"))
        with self.assertRaises(GmailSmtpConfigurationError):
            parse_recipient_target("not-an-email")

    def test_live_configuration_requires_credentials_and_recipient(self):
        with self.assertRaises(ProductionConfigurationError):
            _delivery_configuration(
                {
                    "LIVE_EMAIL_SEND": "1",
                    "DEFAULT_RECIPIENTS": "a@example.com",
                    "GMAIL_USER": "",
                    "GMAIL_APP_PASS": "",
                }
            )
        with self.assertRaises(ProductionConfigurationError):
            _delivery_configuration(
                {
                    "LIVE_EMAIL_SEND": "1",
                    "DEFAULT_RECIPIENTS": "not-an-email",
                    "GMAIL_USER": "sender@example.com",
                    "GMAIL_APP_PASS": "app-secret",
                }
            )

    def test_staged_composition_does_not_require_or_call_smtp(self):
        with patch("src.weekly_report.gmail_smtp.smtplib.SMTP_SSL", _FakeSmtp):
            delivery, recipient = _delivery_configuration(
                {"LIVE_EMAIL_SEND": "0", "DEFAULT_RECIPIENTS": "a@example.com"}
            )
            receipt = delivery.deliver(self._artifact(), recipient)
        self.assertEqual(recipient, "a@example.com")
        self.assertEqual(receipt.status, DeliveryStatus.STAGED)
        self.assertEqual(_FakeSmtp.instances, [])

    def test_fake_success_and_refusal_have_safe_delivery_semantics(self):
        values = {
            "LIVE_EMAIL_SEND": "1",
            "DEFAULT_RECIPIENTS": "a@example.com",
            "GMAIL_USER": "sender@example.com",
            "GMAIL_APP_PASS": "app-secret",
        }
        with (
            patch("src.weekly_report.gmail_smtp.ssl.create_default_context", return_value=object()),
            patch("src.weekly_report.gmail_smtp.smtplib.SMTP_SSL", _FakeSmtp),
        ):
            delivery, recipient = _delivery_configuration(values)
            first = delivery.deliver(self._artifact(), recipient)
            duplicate = delivery.deliver(self._artifact(), recipient)
        self.assertEqual(first.status, DeliveryStatus.SENT)
        self.assertEqual(duplicate.status, DeliveryStatus.DUPLICATE)
        self.assertEqual(len(_FakeSmtp.instances), 1)

        _FakeSmtp.instances = []
        _FakeSmtp.refused = {"a@example.com": (550, "rejected")}
        with (
            patch("src.weekly_report.gmail_smtp.ssl.create_default_context", return_value=object()),
            patch("src.weekly_report.gmail_smtp.smtplib.SMTP_SSL", _FakeSmtp),
        ):
            delivery, recipient = _delivery_configuration(values)
            failed = delivery.deliver(self._artifact(), recipient)
        self.assertEqual(failed.status, DeliveryStatus.FAILED)
        self.assertEqual(failed.error, "delivery sender failed")
        self.assertNotIn("app-secret", repr(failed))

    def test_smtp_exception_is_safe_and_not_retried(self):
        _FakeSmtp.error = RuntimeError("server leaked app-secret")
        sender = GmailSmtpSender(GmailSmtpConfig("sender@example.com", "app-secret"))
        service = DeliveryService(sender=sender, live_email_send=True)
        with (
            patch("src.weekly_report.gmail_smtp.ssl.create_default_context", return_value=object()),
            patch("src.weekly_report.gmail_smtp.smtplib.SMTP_SSL", _FakeSmtp),
        ):
            receipt = service.deliver(self._artifact(), "a@example.com")
        self.assertEqual(receipt.status, DeliveryStatus.FAILED)
        self.assertNotIn("app-secret", repr(receipt))
        self.assertEqual(len(_FakeSmtp.instances), 1)


if __name__ == "__main__":
    import unittest

    unittest.main()
