"""Bounded Gmail SMTP transport for the V2 DeliveryService.

This module owns only SMTP configuration and message transport.  Delivery
identity, idempotency, and the decision to invoke delivery remain owned by
``DeliveryService``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import parseaddr
from html import escape
import os
from pathlib import Path
import smtplib
import ssl
from typing import Final

from .delivery import DeliveryFailure, DeliveryFailurePhase, SendOutcome, failure_signature
from .pdf_renderer import pdf_filename, render_report_pdf
from .report_service import FinalReportArtifact


GMAIL_SMTP_HOST: Final = "smtp.gmail.com"
GMAIL_SMTP_PORT: Final = 465
_DELIVERY_CONFIG_KEYS: Final = (
    "GMAIL_USER",
    "GMAIL_APP_PASS",
    "DEFAULT_RECIPIENTS",
    "LIVE_EMAIL_SEND",
    # RC-55 (section A.39): the shared handoff ledger and an operator release.
    "DELIVERY_LEDGER_REPOSITORY",
    "DELIVERY_LEDGER_TOKEN",
    "DELIVERY_LEDGER_KEY",
    "DELIVERY_RELEASE_PERIOD",
    "DELIVERY_RELEASE_CLAIMS",
)


class GmailSmtpConfigurationError(ValueError):
    """Gmail SMTP configuration is incomplete or invalid."""


class GmailSmtpError(DeliveryFailure):
    """A Gmail SMTP attempt failed without exposing transport secrets."""


def _smtp_code(failure: BaseException) -> int | None:
    """The numeric SMTP reply code of a server response, never its text."""

    code = getattr(failure, "smtp_code", None)
    return code if isinstance(code, int) and not isinstance(code, bool) else None


def load_delivery_values(
    environ: Mapping[str, str] | None = None,
    *,
    dotenv_path: str | os.PathLike[str] | None = None,
) -> dict[str, str | None]:
    """Load delivery settings with process values taking precedence over .env."""

    process = os.environ if environ is None else environ
    dotenv: Mapping[str, object] = {}
    if not all(key in process for key in _DELIVERY_CONFIG_KEYS):
        env_file = (
            Path(dotenv_path)
            if dotenv_path is not None
            else Path(__file__).resolve().parents[2] / ".env"
        )
        try:
            from dotenv import dotenv_values

            dotenv = dotenv_values(env_file)
        except (ImportError, OSError, UnicodeError, ValueError):
            dotenv = {}

    values: dict[str, str | None] = {
        key: (str(process[key]) if process[key] is not None else None)
        if key in process
        else (str(dotenv[key]) if dotenv.get(key) is not None else None)
        for key in _DELIVERY_CONFIG_KEYS
    }
    return values


def parse_recipient_target(recipient_target: str) -> tuple[str, ...]:
    """Parse the existing comma-separated recipient setting safely."""

    if not isinstance(recipient_target, str) or not recipient_target.strip():
        raise GmailSmtpConfigurationError("DEFAULT_RECIPIENTS is required")
    if "\r" in recipient_target or "\n" in recipient_target:
        raise GmailSmtpConfigurationError("recipient target contains invalid characters")

    # V1 accepted a comma-separated recipient list.  Keep that existing
    # recipient contract and validate each address with the standard parser.
    parts = [part.strip() for part in recipient_target.split(",")]
    if not parts or any(not part for part in parts):
        raise GmailSmtpConfigurationError("DEFAULT_RECIPIENTS contains an empty recipient")
    addresses: list[str] = []
    for part in parts:
        _, address = parseaddr(part)
        if (
            not address
            or "@" not in address
            or address.count("@") != 1
            or any(character.isspace() for character in address)
            or any(character in address for character in "<>\r\n")
        ):
            raise GmailSmtpConfigurationError("DEFAULT_RECIPIENTS contains an invalid recipient")
        local, domain = address.rsplit("@", 1)
        if not local or not domain:
            raise GmailSmtpConfigurationError("DEFAULT_RECIPIENTS contains an invalid recipient")
        addresses.append(address)
    return tuple(addresses)


@dataclass(frozen=True, slots=True)
class GmailSmtpConfig:
    """Validated Gmail SMTP credentials and fixed secure endpoint."""

    user: str
    app_password: str = field(repr=False)
    host: str = GMAIL_SMTP_HOST
    port: int = GMAIL_SMTP_PORT

    def __post_init__(self) -> None:
        if not isinstance(self.user, str) or not self.user.strip():
            raise GmailSmtpConfigurationError("GMAIL_USER is required")
        if not isinstance(self.app_password, str) or not self.app_password.strip():
            raise GmailSmtpConfigurationError("GMAIL_APP_PASS is required")
        if "\r" in self.user or "\n" in self.user:
            raise GmailSmtpConfigurationError("GMAIL_USER contains invalid characters")
        if self.host != GMAIL_SMTP_HOST or self.port != GMAIL_SMTP_PORT:
            raise GmailSmtpConfigurationError("Gmail SMTP endpoint is fixed")

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        dotenv_path: str | os.PathLike[str] | None = None,
    ) -> "GmailSmtpConfig":
        values = load_delivery_values(environ, dotenv_path=dotenv_path)
        user = values.get("GMAIL_USER")
        app_password = values.get("GMAIL_APP_PASS")
        if not isinstance(user, str) or not user.strip():
            raise GmailSmtpConfigurationError("GMAIL_USER is required")
        if not isinstance(app_password, str) or not app_password.strip():
            raise GmailSmtpConfigurationError("GMAIL_APP_PASS is required")
        return cls(user.strip(), app_password)


def subject_for_artifact(artifact: FinalReportArtifact) -> str:
    """Build a readable, mechanically derived subject without changing content.

    The subject names the reporting period and event count; the report and
    artifact identities travel in X-Weekly-Report-* headers (RC-26).
    """

    if not isinstance(artifact, FinalReportArtifact):
        raise TypeError("Gmail SMTP requires FinalReportArtifact")
    period = artifact.period_display or artifact.report_id
    return f"捷運技術週報｜{period}｜{artifact.event_count} 則"


_ATTACHMENT_NOTE = "詳細內容及臺北捷運局啟示請參閱附件 PDF。"


def index_for_artifact(artifact: FinalReportArtifact) -> tuple[str, str]:
    """The message body: a short index of the attached report, as text and HTML.

    RC-31 (presentation only): title, reporting period, and each section's
    headlines in the assembled order, every headline linking its canonical
    source; the full report travels as the PDF attachment. Nothing is selected,
    reordered or rewritten here.
    """

    if not isinstance(artifact, FinalReportArtifact):
        raise TypeError("Gmail SMTP requires FinalReportArtifact")
    text = ["捷運技術週報"]
    html = ["<p><strong>捷運技術週報</strong>"]
    if artifact.period_display:
        text.append(f"報告期間：{artifact.period_display}")
        html.append(f"<br>報告期間：{escape(artifact.period_display)}")
    html.append("</p>")
    if artifact.no_event:
        statement = artifact.content.splitlines()[0]
        text.extend(("", statement))
        html.append(f"<p>{escape(statement)}</p>")
    for section in artifact.sections:
        text.extend(("", f"【{section.category}】"))
        html.append(f"<p><strong>【{escape(section.category)}】</strong></p><ul>")
        for event in section.events:
            text.extend((f"- {event.headline}", f"  {event.source_url}"))
            html.append(
                f'<li><a href="{escape(event.source_url, quote=True)}">{escape(event.headline)}</a></li>'
            )
        html.append("</ul>")
    note = _ATTACHMENT_NOTE if artifact.events else "詳細內容請參閱附件 PDF。"
    text.extend(("", note))
    html.append(f"<p>{escape(note)}</p>")
    return "\n".join(text) + "\n", "".join(html)


@dataclass(frozen=True, slots=True)
class GmailSmtpSender:
    """The Gmail ``DeliverySender``: one message per recipient over one SSL session."""

    config: GmailSmtpConfig
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not isinstance(self.config, GmailSmtpConfig):
            raise TypeError("GmailSmtpSender requires GmailSmtpConfig")
        if isinstance(self.timeout_seconds, bool) or self.timeout_seconds <= 0:
            raise ValueError("GmailSmtpSender timeout_seconds must be positive")

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        dotenv_path: str | os.PathLike[str] | None = None,
        timeout_seconds: float = 30.0,
    ) -> "GmailSmtpSender":
        return cls(
            GmailSmtpConfig.from_environment(environ, dotenv_path=dotenv_path),
            timeout_seconds=timeout_seconds,
        )

    def _message(self, artifact: FinalReportArtifact, address: str, pdf: bytes) -> str:
        # RC-55: one message per recipient; no other recipient appears in it.
        message = EmailMessage()
        message["From"] = self.config.user
        message["To"] = address
        message["Subject"] = subject_for_artifact(artifact)
        message["X-Weekly-Report-Id"] = artifact.report_id
        message["X-Weekly-Report-Artifact"] = f"{artifact.artifact_id} {artifact.artifact_version}"
        text, html = index_for_artifact(artifact)
        message.set_content(text, charset="utf-8")
        message.add_alternative(html, subtype="html", charset="utf-8")
        # The PDF carries the full assembled report; a report that cannot be
        # rendered is not sent (opening fails, Delivery records FAILED).
        message.add_attachment(pdf, maintype="application", subtype="pdf", filename=pdf_filename(artifact))
        return message.as_string()

    def recipients(self, recipient_target: str) -> tuple[str, ...]:
        return parse_recipient_target(recipient_target)

    def open(self, artifact: FinalReportArtifact, addresses: tuple[str, ...]) -> "GmailSmtpSession":
        """Build every message, then connect and log in; nothing is sent here."""

        if not isinstance(artifact, FinalReportArtifact):
            raise TypeError("Gmail SMTP requires FinalReportArtifact")
        try:
            pdf = render_report_pdf(artifact)
            messages = {address: self._message(artifact, address, pdf) for address in addresses}
        except Exception as exc:
            raise GmailSmtpError(
                "formal report PDF could not be rendered",
                phase=DeliveryFailurePhase.MESSAGE,
                failure_class=type(exc).__name__,
            ) from None
        # RC-54: only the phase, the exception type and a numeric reply code
        # are kept; never server text or credentials.
        phase = DeliveryFailurePhase.CONNECT
        smtp = None
        try:
            smtp = smtplib.SMTP_SSL(
                self.config.host,
                self.config.port,
                context=ssl.create_default_context(),
                timeout=self.timeout_seconds,
            )
            phase = DeliveryFailurePhase.LOGIN
            smtp.login(self.config.user, self.config.app_password)
        except Exception as exc:
            if smtp is not None:
                try:
                    smtp.close()
                except Exception:  # noqa: BLE001 - closing a failed session
                    pass
            raise GmailSmtpError(
                "Gmail SMTP session could not be opened",
                phase=phase,
                failure_class=type(exc).__name__,
                smtp_code=_smtp_code(exc),
            ) from None
        return GmailSmtpSession(smtp, self.config.user, messages)


class GmailSmtpSession:
    """One authenticated Gmail session; reports what each send observed."""

    def __init__(self, smtp: smtplib.SMTP, sender: str, messages: Mapping[str, str]) -> None:
        self._smtp = smtp
        self._sender = sender
        self._messages = dict(messages)

    def send(self, address: str) -> SendOutcome:
        try:
            refused = self._smtp.sendmail(self._sender, [address], self._messages[address])
        except Exception as exc:  # noqa: BLE001 - reported as facts, never raised
            code = _smtp_code(exc)
            explicit = isinstance(exc, (smtplib.SMTPSenderRefused, smtplib.SMTPRecipientsRefused, smtplib.SMTPDataError))
            return SendOutcome(
                False,
                DeliveryFailurePhase.SENDMAIL,
                type(exc).__name__,
                code,
                # smtplib keeps the session after an explicit refusal unless
                # the server closed it (421); anything else ends the session.
                session_usable=explicit and code != 421,
            )
        if refused:
            # One recipient per message, so smtplib cannot return a partial
            # refusal; treat one as unknown rather than as a handoff.
            return SendOutcome(False, DeliveryFailurePhase.REFUSED, "RecipientsPartiallyRefused", session_usable=False)
        return SendOutcome(True)

    def close(self) -> str | None:
        try:
            self._smtp.quit()
        except Exception as exc:  # noqa: BLE001 - after the handoff, only a diagnostic
            return failure_signature(GmailSmtpError("quit", phase=DeliveryFailurePhase.QUIT, failure_class=type(exc).__name__, smtp_code=_smtp_code(exc)))
        finally:
            try:
                self._smtp.close()
            except Exception:  # noqa: BLE001
                pass
        return None


def build_gmail_smtp_sender(
    environ: Mapping[str, str] | None = None,
    *,
    dotenv_path: str | os.PathLike[str] | None = None,
) -> GmailSmtpSender:
    return GmailSmtpSender.from_environment(environ, dotenv_path=dotenv_path)


__all__ = [
    "GMAIL_SMTP_HOST",
    "GMAIL_SMTP_PORT",
    "GmailSmtpConfigurationError",
    "GmailSmtpError",
    "GmailSmtpConfig",
    "GmailSmtpSender",
    "GmailSmtpSession",
    "build_gmail_smtp_sender",
    "index_for_artifact",
    "load_delivery_values",
    "parse_recipient_target",
    "subject_for_artifact",
]
