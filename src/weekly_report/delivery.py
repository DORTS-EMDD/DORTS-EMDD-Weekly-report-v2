"""The sole Delivery owner (contract sections R, A.20 and A.39 / RC-55).

Delivery never selects, validates, rewrites or reorders report events. It
decides what to send, which ledger state to record, what to release and the
result. Real email is opt-in and requires an explicit sender and the shared
handoff ledger (``delivery_ledger``); the ledger store and the sender report
facts and decide nothing.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from enum import StrEnum
import hashlib
import os
import re
from time import monotonic
from typing import Callable, Protocol
from uuid import uuid4

from .debug_service import current_run_id
from .delivery_ledger import (
    BLOCKING_STATES,
    EntryState,
    LedgerConflict,
    LedgerEntry,
    LedgerInvariantError,
    LedgerStore,
    LedgerUnavailable,
    MIN_SECRET_LENGTH,
    PeriodLedger,
    audit_fields,
    check_transition,
    claim_id_for,
    entry_reference,
    key_id,
    period_label,
    period_path,
    recipient_key,
)
from .report_service import FinalReportArtifact


class DeliveryStatus(StrEnum):
    STAGED = "STAGED"
    SENT = "SENT"
    DUPLICATE = "DUPLICATE"
    FAILED = "FAILED"


class DeliveryFailurePhase(StrEnum):
    """Where a failed attempt stopped (RC-54, observation only)."""

    MESSAGE = "MESSAGE"
    CONNECT = "CONNECT"
    LOGIN = "LOGIN"
    SENDMAIL = "SENDMAIL"
    REFUSED = "REFUSED"
    QUIT = "QUIT"
    SENDER = "SENDER"
    LEDGER = "LEDGER"
    RELEASE = "RELEASE"


# PHASE:ExceptionType[:SMTP reply code]; fixed tokens and digits only, so no
# server text, credential or address can travel in it.
_FAILURE_SIGNATURE = re.compile(
    rf"(?:{'|'.join(phase.value for phase in DeliveryFailurePhase)}):[A-Za-z_][A-Za-z0-9_]{{0,63}}(?::[1-5][0-9]{{2}})?"
)

# Section A.39 constants.
PROVABLE_REFUSALS = frozenset({"SMTPSenderRefused", "SMTPRecipientsRefused", "SMTPDataError"})
SEND_WINDOW_SECONDS = 3600.0
RELEASE_MIN_AGE = timedelta(hours=24)
LEDGER_ATTEMPTS = 3

RECIPIENT_COUNT_KEYS = ("sent", "already_sent", "not_sent", "not_reached", "blocked", "released")
HANDOFF_OBSERVED_UNRECORDED = "HANDOFF_OBSERVED_UNRECORDED"
HANDOFF_UNKNOWN = "HANDOFF_UNKNOWN"
CLAIM_UNCONFIRMED = "CLAIM_UNCONFIRMED"
REFUSED_UNRECORDED = "REFUSED_UNRECORDED"
_OBSERVATIONS = frozenset({HANDOFF_OBSERVED_UNRECORDED, HANDOFF_UNKNOWN, CLAIM_UNCONFIRMED, REFUSED_UNRECORDED})
_ATTEMPTED_LINE = re.compile(r"[0-9a-f]{16}@[A-Za-z0-9]{1,64}\|age=[0-9]+h(?:\|[A-Z_]+)?")
_RELEASE_PERIOD = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\.\.[0-9]{4}-[0-9]{2}-[0-9]{2}")
_RELEASE_CLAIM = re.compile(r"([0-9a-f]{16})@([A-Za-z0-9]{1,64})")
_ACTOR = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")


@dataclass(frozen=True, slots=True)
class DeliveryIdentity:
    report_id: str
    artifact_id: str
    artifact_version: str
    recipient_target: str = field(repr=False)

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


def _safe_signature(value: object, name: str) -> None:
    if value is not None and (not isinstance(value, str) or not _FAILURE_SIGNATURE.fullmatch(value)):
        raise ValueError(f"DeliveryReceipt {name} must be a safe signature")


@dataclass(frozen=True, slots=True)
class DeliveryReceipt:
    identity: DeliveryIdentity
    status: DeliveryStatus
    event_ids: tuple[str, ...]
    error: str | None = None
    # RC-54 (observation only): where a FAILED attempt stopped.
    failure_signature: str | None = None
    # RC-55 (observation only): per-recipient counts and the period's
    # ATTEMPTED claims as entry reference, claim run and age; never an address.
    recipient_counts: Mapping[str, int] = field(default_factory=dict)
    attempted_claims: tuple[str, ...] = ()
    # A problem after the handoff (for example at QUIT) never changes SENT.
    diagnostic: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.identity, DeliveryIdentity):
            raise TypeError("DeliveryReceipt requires DeliveryIdentity")
        status = DeliveryStatus(self.status)
        object.__setattr__(self, "status", status)
        if self.failure_signature is not None and status is not DeliveryStatus.FAILED:
            raise ValueError("DeliveryReceipt failure_signature belongs to a FAILED attempt")
        _safe_signature(self.failure_signature, "failure_signature")
        _safe_signature(self.diagnostic, "diagnostic")
        event_ids = tuple(self.event_ids)
        if any(not isinstance(event_id, str) or not event_id.strip() for event_id in event_ids):
            raise ValueError("DeliveryReceipt event_ids must be nonblank strings")
        object.__setattr__(self, "event_ids", event_ids)
        counts = dict(self.recipient_counts)
        if any(
            key not in RECIPIENT_COUNT_KEYS or isinstance(value, bool) or not isinstance(value, int) or value < 0
            for key, value in counts.items()
        ):
            raise ValueError("DeliveryReceipt recipient_counts must be known non-negative counts")
        object.__setattr__(self, "recipient_counts", counts)
        claims = tuple(self.attempted_claims)
        if any(not isinstance(line, str) or not _ATTEMPTED_LINE.fullmatch(line) for line in claims):
            raise ValueError("DeliveryReceipt attempted_claims must be entry references with claim runs")
        object.__setattr__(self, "attempted_claims", claims)

    @property
    def successful(self) -> bool:
        return self.status is DeliveryStatus.SENT

    @property
    def duplicate(self) -> bool:
        return self.status is DeliveryStatus.DUPLICATE


class DeliveryFailure(RuntimeError):
    """A delivery attempt failed without modifying the assembled artifact.

    RC-54: a sender names the phase where its attempt stopped, the type of
    the underlying exception and, when the server replied, the numeric SMTP
    code. The message text is never copied onto a receipt.
    """

    def __init__(
        self,
        message: str,
        *,
        phase: DeliveryFailurePhase | str = DeliveryFailurePhase.SENDER,
        failure_class: str = "",
        smtp_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.phase = DeliveryFailurePhase(phase)
        self.failure_class = failure_class or type(self).__name__
        self.smtp_code = smtp_code


def _signature(phase: DeliveryFailurePhase, failure_class: str, code: int | None = None) -> str:
    signature = f"{phase.value}:{failure_class}"
    if isinstance(code, int) and not isinstance(code, bool) and 100 <= code <= 599:
        signature += f":{code}"
    return signature if _FAILURE_SIGNATURE.fullmatch(signature) else f"{phase.value}:UNKNOWN"


def failure_signature(failure: BaseException) -> str:
    """The receipt's safe ``PHASE:ExceptionType[:code]`` for a failure."""

    if isinstance(failure, DeliveryFailure):
        return _signature(failure.phase, failure.failure_class, failure.smtp_code)
    return _signature(DeliveryFailurePhase.SENDER, type(failure).__name__)


@dataclass(frozen=True, slots=True)
class SendOutcome:
    """What a sender observed for one message; facts only, no ledger state."""

    accepted: bool
    phase: DeliveryFailurePhase = DeliveryFailurePhase.SENDMAIL
    failure_class: str = ""
    smtp_code: int | None = None
    # False when the session can no longer be used for another message.
    session_usable: bool = True

    def signature(self) -> str | None:
        return None if self.accepted else _signature(self.phase, self.failure_class or "UNKNOWN", self.smtp_code)


class DeliverySession(Protocol):
    def send(self, address: str) -> SendOutcome:
        """Send this recipient's message; report what was observed, never raise for SMTP."""

    def close(self) -> str | None:
        """End the session; return a diagnostic signature for a problem, else None."""


class DeliverySender(Protocol):
    def recipients(self, recipient_target: str) -> tuple[str, ...]:
        """Parse the configured recipient target into addresses."""

    def open(self, artifact: FinalReportArtifact, addresses: tuple[str, ...]) -> DeliverySession:
        """Build every message and open an authenticated session; raise DeliveryFailure."""


@dataclass(frozen=True, slots=True)
class DeliveryLedgerAccess:
    """The shared handoff ledger: a compare-and-swap store and the HMAC key."""

    store: LedgerStore
    secret: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not callable(getattr(self.store, "read", None)) or not callable(getattr(self.store, "write", None)):
            raise TypeError("DeliveryLedgerAccess requires a ledger store")
        if not isinstance(self.secret, bytes) or len(self.secret) < MIN_SECRET_LENGTH:
            raise ValueError(f"the delivery ledger key must be at least {MIN_SECRET_LENGTH} bytes")


@dataclass(frozen=True, slots=True)
class ReleaseRequest:
    """An operator's release of named ATTEMPTED claims (section A.39)."""

    period: str
    claims: tuple[tuple[str, str], ...]
    manual: bool
    actor: str

    @classmethod
    def parse(cls, period: str, claims: str, *, manual: bool, actor: str) -> "ReleaseRequest":
        period = (period or "").strip()
        items = [item.strip() for item in (claims or "").split(",") if item.strip()]
        if not _RELEASE_PERIOD.fullmatch(period):
            raise ValueError("release period must be YYYY-MM-DD..YYYY-MM-DD")
        matches = [_RELEASE_CLAIM.fullmatch(item) for item in items]
        if not matches or any(match is None for match in matches):
            raise ValueError("release claims must be <entry reference>@<run_id>, comma separated")
        parsed = tuple((match.group(1), match.group(2)) for match in matches if match is not None)
        if len(set(parsed)) != len(parsed):
            raise ValueError("release claims must not repeat")
        actor = (actor or "").strip()
        # A GitHub login (letters, digits, hyphens); anything else is recorded as unknown.
        return cls(period, parsed, bool(manual), actor if _ACTOR.fullmatch(actor) else "unknown")


class _ReleaseRefused(RuntimeError):
    pass


@dataclass
class _Run:
    """The bookkeeping of one live delivery; decisions stay in DeliveryService."""

    run_id: str
    counts: dict[str, int] = field(default_factory=lambda: dict.fromkeys(RECIPIENT_COUNT_KEYS, 0))
    signature: str | None = None
    observations: dict[str, str] = field(default_factory=dict)
    snapshot: PeriodLedger | None = None
    session_lost: bool = False

    def fail(self, signature: str) -> None:
        if self.signature is None:
            self.signature = signature


class DeliveryService:
    """Sole Delivery owner: per-recipient handoff ledger, single sender, one result."""

    def __init__(
        self,
        *,
        sender: DeliverySender | None = None,
        live_email_send: bool | None = None,
        ledger: DeliveryLedgerAccess | None = None,
        release: ReleaseRequest | None = None,
        audit: Mapping[str, str] | None = None,
        wall_clock: Callable[[], datetime] | None = None,
        monotonic_clock: Callable[[], float] | None = None,
        execution_id: str | None = None,
    ) -> None:
        if live_email_send is None:
            live_email_send = os.environ.get("LIVE_EMAIL_SEND", "0").strip() == "1"
        if type(live_email_send) is not bool:
            raise TypeError("live_email_send must be bool")
        if live_email_send and sender is None:
            raise ValueError("LIVE_EMAIL_SEND requires an explicit safe sender")
        if live_email_send and ledger is None:
            # Section A.39: no entry point sends live email without the ledger.
            raise ValueError("LIVE_EMAIL_SEND requires the delivery ledger")
        if ledger is not None and not isinstance(ledger, DeliveryLedgerAccess):
            raise TypeError("ledger must be a DeliveryLedgerAccess")
        if release is not None and not isinstance(release, ReleaseRequest):
            raise TypeError("release must be a ReleaseRequest")
        self._sender = sender
        self._live_email_send = live_email_send
        self._ledger = ledger
        self._release = release
        # Audit fields never overwrite a history field: only these two names pass.
        self._audit = {
            key: value
            for key, value in audit_fields(dict(audit or {})).items()
            if key in ("github_run_id", "github_run_attempt")
        }
        self._now = wall_clock or (lambda: datetime.now(timezone.utc))
        self._monotonic = monotonic_clock or monotonic
        self._execution_id = execution_id
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
        event_ids = tuple(event.event_id for event in artifact.events)
        if not self._live_email_send:
            return self._receipt(identity, DeliveryStatus.STAGED, event_ids)
        if artifact.period_start is None or artifact.period_end is None:
            raise ValueError("live delivery requires the artifact's reporting period")
        run = _Run(self._execution_id or current_run_id() or uuid4().hex)
        status, diagnostic = self._deliver_live(artifact, identity, run)
        return self._receipt(
            identity,
            status,
            event_ids,
            error="delivery sender failed" if status is DeliveryStatus.FAILED else None,
            failure_signature=(run.signature or _signature(DeliveryFailurePhase.LEDGER, "RecipientNotSent"))
            if status is DeliveryStatus.FAILED
            else None,
            recipient_counts=run.counts,
            attempted_claims=self._attempted_lines(run),
            diagnostic=diagnostic,
        )

    def _receipt(self, identity: DeliveryIdentity, status: DeliveryStatus, event_ids: tuple[str, ...], **values) -> DeliveryReceipt:
        receipt = DeliveryReceipt(identity, status, event_ids, **values)
        self.attempts.append(receipt)
        return receipt

    # -- the section A.39 sequence ------------------------------------------------

    def _deliver_live(
        self, artifact: FinalReportArtifact, identity: DeliveryIdentity, run: _Run
    ) -> tuple[DeliveryStatus, str | None]:
        assert self._sender is not None and self._ledger is not None
        start, end = artifact.period_start, artifact.period_end
        assert start is not None and end is not None
        try:
            addresses = self._sender.recipients(identity.recipient_target)
        except Exception as exc:  # noqa: BLE001 - the sender's own validation
            run.fail(failure_signature(exc))
            return DeliveryStatus.FAILED, None
        keys: dict[str, str] = {}
        for address in addresses:
            keys.setdefault(recipient_key(self._ledger.secret, start, end, address), address)
        path = period_path(start, end)
        expected_key_id = key_id(self._ledger.secret)
        try:
            ledger, _ = self._read(path, start, end)
        except (LedgerUnavailable, LedgerInvariantError) as exc:
            run.fail(_signature(DeliveryFailurePhase.LEDGER, type(exc).__name__))
            run.counts["not_reached"] = len(keys)
            return DeliveryStatus.FAILED, None
        if ledger is not None and ledger.key_id != expected_key_id:
            # A period file is never re-keyed; its entries cannot be matched.
            run.fail(_signature(DeliveryFailurePhase.LEDGER, "KeyMismatch"))
            run.counts["not_reached"] = len(keys)
            return DeliveryStatus.FAILED, None
        run.snapshot = ledger or PeriodLedger(start, end, expected_key_id)

        if self._release is not None:
            try:
                run.snapshot = self._apply_release(path, run, start, end)
            except _ReleaseRefused:
                run.fail(_signature(DeliveryFailurePhase.RELEASE, "ReleaseRefused"))
            except (LedgerUnavailable, LedgerConflict, LedgerInvariantError) as exc:
                run.fail(_signature(DeliveryFailurePhase.RELEASE, type(exc).__name__))

        eligible = []
        for key, address in keys.items():
            entry = run.snapshot.entry(key)
            if entry is None or entry.state not in BLOCKING_STATES:
                eligible.append((key, address))
            elif entry.state is EntryState.SENT:
                run.counts["already_sent"] += 1
            else:
                run.counts["blocked"] += 1

        diagnostic = None
        if eligible:
            # Section A.39: messages are built and the session is opened and
            # authenticated before the first claim; a failure writes nothing.
            try:
                session = self._sender.open(artifact, tuple(address for _, address in eligible))
            except Exception as exc:  # noqa: BLE001 - every sender failure is a FAILED result
                run.fail(failure_signature(exc))
                run.counts["not_reached"] += len(eligible)
            else:
                try:
                    for key, address in eligible:
                        self._deliver_one(session, path, start, end, key, address, run)
                finally:
                    diagnostic = session.close()

        total = len(keys)
        delivered = run.counts["sent"] + run.counts["already_sent"]
        if run.signature is None and delivered == total:
            return (DeliveryStatus.SENT if run.counts["sent"] else DeliveryStatus.DUPLICATE), diagnostic
        return DeliveryStatus.FAILED, diagnostic

    def _deliver_one(self, session: DeliverySession, path, start, end, key: str, address: str, run: _Run) -> None:
        if run.session_lost:
            run.counts["not_reached"] += 1
            return
        claim_id = claim_id_for(run.run_id, entry_reference(key))
        try:
            outcome, claimed_at = self._claim(path, start, end, key, claim_id, run)
        except LedgerInvariantError as exc:
            run.fail(_signature(DeliveryFailurePhase.LEDGER, type(exc).__name__))
            run.counts["not_reached"] += 1
            return
        if outcome == "BLOCKED_SENT":
            run.counts["already_sent"] += 1
            return
        if outcome == "BLOCKED":
            run.counts["blocked"] += 1
            return
        if outcome == "UNCONFIRMED":
            # The claim may have been written; nothing is sent on it.
            run.observations[key] = CLAIM_UNCONFIRMED
            run.fail(_signature(DeliveryFailurePhase.LEDGER, "ClaimUnconfirmed"))
            run.counts["blocked"] += 1
            return
        if outcome == "NOT_WRITTEN":
            run.fail(_signature(DeliveryFailurePhase.LEDGER, "ClaimNotWritten"))
            run.counts["not_reached"] += 1
            return

        # The claim is held. The holder never begins a transaction more than
        # an hour after its own claim (its own monotonic clock).
        if self._monotonic() - claimed_at > SEND_WINDOW_SECONDS:
            target = EntryState.NOT_SENT
            run.fail(_signature(DeliveryFailurePhase.SENDER, "SendWindowExpired"))
        else:
            sent = session.send(address)
            if not sent.session_usable:
                run.session_lost = True
            if sent.accepted:
                target = EntryState.SENT
            elif sent.failure_class in PROVABLE_REFUSALS:
                target = EntryState.NOT_SENT
                run.fail(sent.signature() or _signature(DeliveryFailurePhase.SENDMAIL, "UNKNOWN"))
            else:
                # Handoff unknown: the entry stays ATTEMPTED and blocks.
                run.fail(sent.signature() or _signature(DeliveryFailurePhase.SENDMAIL, "UNKNOWN"))
                run.observations[key] = HANDOFF_UNKNOWN
                run.counts["blocked"] += 1
                return
        try:
            self._record(path, start, end, key, claim_id, target, run)
        except (LedgerUnavailable, LedgerInvariantError) as exc:
            run.observations[key] = HANDOFF_OBSERVED_UNRECORDED if target is EntryState.SENT else REFUSED_UNRECORDED
            run.fail(_signature(DeliveryFailurePhase.LEDGER, type(exc).__name__))
            run.counts["blocked"] += 1
            return
        run.counts["sent" if target is EntryState.SENT else "not_sent"] += 1

    # -- ledger reads and compare-and-swap writes --------------------------------

    def _read(self, path: str, start, end) -> tuple[PeriodLedger | None, str | None]:
        assert self._ledger is not None
        last = "LedgerUnavailable"
        for _ in range(LEDGER_ATTEMPTS):
            try:
                text, sha = self._ledger.store.read(path)
            except LedgerUnavailable as exc:
                last = str(exc) or last
                continue
            if text is None:
                return None, None
            return PeriodLedger.from_json(text, start, end), sha
        raise LedgerUnavailable(last)

    def _read_once(self, path: str, start, end, run: _Run) -> tuple[PeriodLedger, str | None]:
        assert self._ledger is not None
        text, sha = self._ledger.store.read(path)
        expected = key_id(self._ledger.secret)
        ledger = PeriodLedger(start, end, expected) if text is None else PeriodLedger.from_json(text, start, end)
        if ledger.key_id != expected:
            raise LedgerInvariantError("the period file's key changed during the run")
        run.snapshot = ledger
        return ledger, sha

    def _history(self, state: EntryState, claim_id: str, **extra: str) -> dict[str, str]:
        return {"state": state.value, "claim_id": claim_id, "at": self._now_text(), **self._audit, **extra}

    def _now_text(self) -> str:
        return self._now().astimezone(timezone.utc).isoformat(timespec="seconds")

    def _claim(self, path, start, end, key: str, claim_id: str, run: _Run) -> tuple[str, float]:
        """Claim by compare-and-swap, reconciling by claim ID after any failure."""

        assert self._ledger is not None
        maybe_written = False
        claimed_at = self._monotonic()
        for _ in range(LEDGER_ATTEMPTS):
            try:
                ledger, sha = self._read_once(path, start, end, run)
            except LedgerUnavailable:
                continue
            entry = ledger.entry(key)
            if entry is not None and entry.claim_id == claim_id and entry.state is EntryState.ATTEMPTED:
                return "HELD", claimed_at
            if entry is not None and entry.state in BLOCKING_STATES:
                return ("BLOCKED_SENT" if entry.state is EntryState.SENT else "BLOCKED"), claimed_at
            check_transition(entry, EntryState.ATTEMPTED, claim_id)
            history = (entry.history if entry is not None else ()) + (self._history(EntryState.ATTEMPTED, claim_id),)
            claimed = LedgerEntry(EntryState.ATTEMPTED, claim_id, self._now_text(), history)
            updated = ledger.with_entry(key, claimed)
            claimed_at = self._monotonic()
            try:
                self._ledger.store.write(path, updated.to_json(), sha, f"claim {entry_reference(key)} by {run.run_id}")
            except LedgerConflict:
                continue
            except LedgerUnavailable:
                maybe_written = True
                continue
            run.snapshot = updated
            return "HELD", claimed_at
        return ("UNCONFIRMED" if maybe_written else "NOT_WRITTEN"), claimed_at

    def _record(self, path, start, end, key: str, claim_id: str, target: EntryState, run: _Run) -> None:
        """Write the holder's outcome by compare-and-swap, reconciling by claim ID."""

        assert self._ledger is not None
        for _ in range(LEDGER_ATTEMPTS):
            try:
                ledger, sha = self._read_once(path, start, end, run)
            except LedgerUnavailable:
                continue
            entry = ledger.entry(key)
            if entry is not None and entry.claim_id == claim_id and entry.state is target:
                return
            check_transition(entry, target, claim_id)
            assert entry is not None
            updated = ledger.with_entry(
                key, replace(entry, state=target, history=entry.history + (self._history(target, claim_id),))
            )
            try:
                self._ledger.store.write(path, updated.to_json(), sha, f"{target.value.lower()} {entry_reference(key)} by {run.run_id}")
            except (LedgerConflict, LedgerUnavailable):
                continue
            run.snapshot = updated
            return
        raise LedgerUnavailable("outcome write not confirmed")

    def _apply_release(self, path: str, run: _Run, start, end) -> PeriodLedger:
        """Release the named ATTEMPTED claims of this period, all or nothing."""

        assert self._ledger is not None and self._release is not None and run.snapshot is not None
        release = self._release
        if not release.manual or release.period != period_label(start, end):
            raise _ReleaseRefused()
        ledger, sha = run.snapshot, None
        for attempt in range(LEDGER_ATTEMPTS):
            if attempt or sha is None:
                try:
                    ledger, sha = self._read_once(path, start, end, run)
                except LedgerUnavailable:
                    continue
            updated, released = ledger, 0
            for reference, claim_run in release.claims:
                matches = ledger.keys_for_reference(reference)
                if len(matches) != 1:
                    raise _ReleaseRefused()
                entry = ledger.entry(matches[0])
                assert entry is not None
                named = claim_id_for(claim_run, reference)
                if entry.claim_id != named:
                    raise _ReleaseRefused()
                if entry.state is EntryState.RELEASED and entry.history and entry.history[-1].get("release_run") == run.run_id:
                    continue  # this run's own earlier write whose response was lost
                if entry.state is not EntryState.ATTEMPTED or not self._old_enough(entry):
                    raise _ReleaseRefused()
                check_transition(entry, EntryState.RELEASED, named)
                updated = updated.with_entry(
                    matches[0],
                    replace(
                        entry,
                        state=EntryState.RELEASED,
                        history=entry.history
                        + (self._history(EntryState.RELEASED, named, actor=release.actor, release_run=run.run_id),),
                    ),
                )
                released += 1
            if released == 0:
                run.counts["released"] = len(release.claims)
                return ledger
            try:
                self._ledger.store.write(
                    path,
                    updated.to_json(),
                    sha,
                    f"release {','.join(reference for reference, _ in release.claims)} by {release.actor} in {run.run_id}",
                )
            except (LedgerConflict, LedgerUnavailable):
                continue
            run.counts["released"] = len(release.claims)
            return updated
        raise LedgerUnavailable("release not confirmed")

    def _old_enough(self, entry: LedgerEntry) -> bool:
        try:
            claimed = datetime.fromisoformat(entry.claimed_at)
        except ValueError:
            return False
        if claimed.tzinfo is None:
            return False
        return self._now() - claimed >= RELEASE_MIN_AGE

    def _attempted_lines(self, run: _Run) -> tuple[str, ...]:
        lines: dict[str, str] = {}
        snapshot = run.snapshot
        now = self._now()
        if snapshot is not None:
            for key, entry in sorted(snapshot.entries.items()):
                if entry.state is not EntryState.ATTEMPTED:
                    continue
                try:
                    age = max(0, int((now - datetime.fromisoformat(entry.claimed_at)).total_seconds() // 3600))
                except (TypeError, ValueError):
                    age = 0
                claim_run = entry.claim_id.partition(".")[0]
                lines[key] = f"{entry_reference(key)}@{claim_run}|age={age}h"
        for key, observation in run.observations.items():
            if observation not in _OBSERVATIONS:
                continue
            base = lines.get(key, f"{entry_reference(key)}@{run.run_id}|age=0h")
            lines[key] = f"{base}|{observation}"
        return tuple(lines[key] for key in sorted(lines))


__all__ = [
    "DeliveryFailure",
    "DeliveryFailurePhase",
    "DeliveryIdentity",
    "DeliveryLedgerAccess",
    "DeliveryReceipt",
    "DeliverySender",
    "DeliveryService",
    "DeliverySession",
    "DeliveryStatus",
    "ReleaseRequest",
    "SendOutcome",
    "failure_signature",
]
