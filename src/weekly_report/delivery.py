"""Mechanical artifact delivery seam.

Delivery records identity and idempotency only.  It never selects, validates,
rewrites, or reorders report events.  Real email remains opt-in and requires an
explicit injected sender/staging endpoint.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
import os
from pathlib import Path

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


def _period_key(artifact: FinalReportArtifact, recipient_target: str) -> str | None:
    if artifact.period_start is None or artifact.period_end is None:
        return None
    raw = "\x1f".join(
        ("period", artifact.period_start.isoformat(), artifact.period_end.isoformat(), recipient_target)
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class DeliveryLedger:
    """Durable record of successful sends, shared across process restarts (RC-26).

    Automation reruns start a new process and rebuild a new artifact for the
    same period, so an in-memory record cannot stop a second email. The ledger
    stores only hashed keys (never a recipient address): the artifact identity
    key and a reporting-period-plus-recipient key. A run reads it before
    sending and records a key only after a successful send.
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self._path = Path(path)
        self._entries: list[dict[str, str]] = []
        if self._path.exists():
            data = json.loads(self._path.read_text(encoding="utf-8"))
            entries = data.get("sent") if isinstance(data, dict) else None
            if not isinstance(entries, list) or any(not isinstance(item, dict) for item in entries):
                raise ValueError("delivery ledger is malformed")
            self._entries = [dict(item) for item in entries]

    def contains(self, key: str) -> bool:
        return any(key in (entry.get("artifact_key"), entry.get("period_key")) for entry in self._entries)

    def record(self, artifact: FinalReportArtifact, artifact_key: str, period_key: str | None) -> None:
        self._entries.append(
            {
                "artifact_key": artifact_key,
                "period_key": period_key or "",
                "report_id": artifact.report_id,
                "period": artifact.period_display or "",
                "sent_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(self._path.suffix + ".tmp")
        temporary.write_text(json.dumps({"sent": self._entries}, ensure_ascii=False, indent=1), encoding="utf-8")
        temporary.replace(self._path)


DeliverySender = Callable[[FinalReportArtifact, str], None]


class DeliveryService:
    """Sole mechanical Delivery owner with stable artifact/recipient identity."""

    def __init__(
        self,
        *,
        sender: DeliverySender | None = None,
        live_email_send: bool | None = None,
        ledger: DeliveryLedger | None = None,
    ) -> None:
        if live_email_send is None:
            live_email_send = os.environ.get("LIVE_EMAIL_SEND", "0").strip() == "1"
        if type(live_email_send) is not bool:
            raise TypeError("live_email_send must be bool")
        if live_email_send and sender is None:
            raise ValueError("LIVE_EMAIL_SEND requires an explicit safe sender")
        if ledger is not None and not isinstance(ledger, DeliveryLedger):
            raise TypeError("ledger must be a DeliveryLedger")
        self._sender = sender
        self._live_email_send = live_email_send
        self._ledger = ledger
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
        period_key = _period_key(artifact, identity.recipient_target)
        if identity.stable_key in self._successful_keys or (
            self._ledger is not None
            and (
                self._ledger.contains(identity.stable_key)
                or (period_key is not None and self._ledger.contains(period_key))
            )
        ):
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
        if self._ledger is not None:
            self._ledger.record(artifact, identity.stable_key, period_key)
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
