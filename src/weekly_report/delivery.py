"""Mechanical artifact delivery seam.

Delivery records identity and idempotency only.  It never selects, validates,
rewrites, or reorders report events.  Real email remains opt-in and requires an
explicit injected sender/staging endpoint.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import os

from .report_service import FinalReportArtifact


class DeliveryStatus(StrEnum):
    STAGED = "STAGED"
    SENT = "SENT"
    DUPLICATE = "DUPLICATE"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class DeliveryIdentity:
    report_id: str
    artifact_id: str
    artifact_version: str
    recipient_target: str

    def __post_init__(self) -> None:
        for field_name in ("report_id", "artifact_id", "artifact_version", "recipient_target"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"DeliveryIdentity requires {field_name}")

    @property
    def stable_key(self) -> str:
        raw = "\x1f".join(
            (self.report_id, self.artifact_id, self.artifact_version, self.recipient_target)
        ).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class DeliveryReceipt:
    identity: DeliveryIdentity
    status: DeliveryStatus
    event_ids: tuple[str, ...]
    error: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.identity, DeliveryIdentity):
            raise TypeError("DeliveryReceipt requires DeliveryIdentity")
        status = DeliveryStatus(self.status)
        object.__setattr__(self, "status", status)
        event_ids = tuple(self.event_ids)
        if any(not isinstance(event_id, str) or not event_id.strip() for event_id in event_ids):
            raise ValueError("DeliveryReceipt event_ids must be nonblank strings")
        object.__setattr__(self, "event_ids", event_ids)

    @property
    def successful(self) -> bool:
        return self.status is DeliveryStatus.SENT

    @property
    def duplicate(self) -> bool:
        return self.status is DeliveryStatus.DUPLICATE


class DeliveryFailure(RuntimeError):
    """A delivery attempt failed without modifying the assembled artifact."""


DeliverySender = Callable[[FinalReportArtifact, str], None]


class DeliveryService:
    """Sole mechanical Delivery owner with stable artifact/recipient identity."""

    def __init__(
        self,
        *,
        sender: DeliverySender | None = None,
        live_email_send: bool | None = None,
    ) -> None:
        if live_email_send is None:
            live_email_send = os.environ.get("LIVE_EMAIL_SEND", "0").strip() == "1"
        if type(live_email_send) is not bool:
            raise TypeError("live_email_send must be bool")
        if live_email_send and sender is None:
            raise ValueError("LIVE_EMAIL_SEND requires an explicit safe sender")
        self._sender = sender
        self._live_email_send = live_email_send
        self._successful_keys: set[str] = set()
        self.attempts: list[DeliveryReceipt] = []

    @property
    def live_email_send(self) -> bool:
        return self._live_email_send

    def deliver(self, artifact: FinalReportArtifact, recipient_target: str) -> DeliveryReceipt:
        if not isinstance(artifact, FinalReportArtifact):
            raise TypeError("DeliveryService requires FinalReportArtifact")
        if not isinstance(recipient_target, str) or not recipient_target.strip():
            raise ValueError("DeliveryService requires recipient_target")
        identity = DeliveryIdentity(
            report_id=artifact.report_id,
            artifact_id=artifact.artifact_id,
            artifact_version=artifact.artifact_version,
            recipient_target=recipient_target.strip(),
        )
        if identity.stable_key in self._successful_keys:
            receipt = DeliveryReceipt(identity, DeliveryStatus.DUPLICATE, tuple(event.event_id for event in artifact.events))
            self.attempts.append(receipt)
            return receipt

        if not self._live_email_send:
            receipt = DeliveryReceipt(identity, DeliveryStatus.STAGED, tuple(event.event_id for event in artifact.events))
            self.attempts.append(receipt)
            return receipt

        try:
            assert self._sender is not None
            self._sender(artifact, identity.recipient_target)
        except Exception:
            receipt = DeliveryReceipt(
                identity,
                DeliveryStatus.FAILED,
                tuple(event.event_id for event in artifact.events),
                error="delivery sender failed",
            )
            self.attempts.append(receipt)
            return receipt
        self._successful_keys.add(identity.stable_key)
        receipt = DeliveryReceipt(identity, DeliveryStatus.SENT, tuple(event.event_id for event in artifact.events))
        self.attempts.append(receipt)
        return receipt


__all__ = [
    "DeliveryStatus",
    "DeliveryIdentity",
    "DeliveryReceipt",
    "DeliveryFailure",
    "DeliveryService",
]
