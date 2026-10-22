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
import os
from pathlib import Path
import smtplib
import ssl
from typing import Final

from .pdf_renderer import pdf_filename, render_report_pdf
from .report_service import FinalReportArtifact


GMAIL_SMTP_HOST: Final = "smtp.gmail.com"
GMAIL_SMTP_PORT: Final = 465
_DELIVERY_CONFIG_KEYS: Final = (
    "GMAIL_USER",
    "GMAIL_APP_PASS",
    "DEFAULT_RECIPIENTS",
    "LIVE_EMAIL_SEND",
)


class GmailSmtpConfigurationError(ValueError):
    """Gmail SMTP configuration is incomplete or invalid."""


class GmailSmtpError(RuntimeError):
    """A Gmail SMTP attempt failed without exposing transport secrets."""


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
    """Build a stable, mechanically derived subject without changing content."""

    if not isinstance(artifact, FinalReportArtifact):
        raise TypeError("Gmail SMTP requires FinalReportArtifact")
    return (
        "Weekly-report V2 | "
        f"{artifact.report_id} | {artifact.artifact_id} | {artifact.artifact_version}"
    )


@dataclass(frozen=True, slots=True)
class GmailSmtpSender:
    """One-shot ``DeliverySender`` using Gmail's SSL SMTP endpoint."""

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

    def _message(self, artifact: FinalReportArtifact, recipients: tuple[str, ...]) -> EmailMessage:
        message = EmailMessage()
        message["From"] = self.config.user
        message["To"] = ", ".join(recipients)
        message["Subject"] = subject_for_artifact(artifact)
        message.set_content(artifact.content, charset="utf-8")
        # The PDF is the same assembled content; a report that cannot be
        # rendered is not sent (the sender raises, Delivery records FAILED).
        message.add_attachment(
            render_report_pdf(artifact),
            maintype="application",
            subtype="pdf",
            filename=pdf_filename(artifact),
        )
        return message

    def __call__(self, artifact: FinalReportArtifact, recipient_target: str) -> None:
        if not isinstance(artifact, FinalReportArtifact):
            raise TypeError("Gmail SMTP requires FinalReportArtifact")
        recipients = parse_recipient_target(recipient_target)
        try:
            message = self._message(artifact, recipients)
        except Exception:
            raise GmailSmtpError("formal report PDF could not be rendered") from None
        try:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(
                self.config.host,
                self.config.port,
                context=context,
                timeout=self.timeout_seconds,
            ) as smtp:
                smtp.login(self.config.user, self.config.app_password)
                refused = smtp.sendmail(
                    self.config.user,
                    list(recipients),
                    message.as_string(),
                )
                if refused:
                    raise GmailSmtpError("Gmail SMTP refused one or more recipients")
        except GmailSmtpError:
            raise
        except Exception:
            # Keep server, credentials, and provider response details out of
            # receipts and deployment logs. DeliveryService supplies the
            # public FAILED status and safe error text.
            raise GmailSmtpError("Gmail SMTP send failed") from None


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
    "build_gmail_smtp_sender",
    "load_delivery_values",
    "parse_recipient_target",
    "subject_for_artifact",
]
