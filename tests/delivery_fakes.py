"""Test-only fakes for RC-55 (section A.39): a compare-and-swap ledger store
with failure injection, a scripted SMTP sender and controllable clocks."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib

from src.weekly_report.delivery import (
    DeliveryFailure,
    DeliveryFailurePhase,
    DeliveryLedgerAccess,
    DeliveryService,
    SendOutcome,
)
from src.weekly_report.delivery_ledger import LedgerConflict, LedgerUnavailable, PeriodLedger, period_path

SECRET = b"rc55-test-key-0123456789abcdef-0123456789"
PERIOD = (date(2026, 10, 27), date(2026, 11, 2))
PATH = period_path(*PERIOD)


class Crash(BaseException):
    """A process death: nothing after it runs in that execution."""


class FakeLedgerStore:
    """Blob-SHA compare-and-swap, like the contents API, with injectable failures.

    ``write_plan`` scripts the next writes: "ok", "conflict", "unavailable"
    (nothing written), "lost" (written, then the response is lost) or "crash".
    ``read_failures`` makes that many next reads fail. ``before_write`` runs
    before a write is applied, so a test can make a competing change.
    """

    def __init__(self) -> None:
        self.files: dict[str, tuple[str, str]] = {}
        self.write_plan: list[str] = []
        self.read_failures = 0
        self.before_write = None
        self.commits: list[str] = []
        self._counter = 0

    def put(self, path: str, content: str) -> None:
        self._counter += 1
        self.files[path] = (content, hashlib.sha1(f"{self._counter}{content}".encode()).hexdigest())

    def read(self, path):
        if self.read_failures:
            self.read_failures -= 1
            raise LedgerUnavailable("HTTP_503")
        return self.files.get(path, (None, None))

    def write(self, path, content, sha, message):
        if self.before_write is not None:
            hook, self.before_write = self.before_write, None
            hook(self, path)
        action = self.write_plan.pop(0) if self.write_plan else "ok"
        if action == "unavailable":
            raise LedgerUnavailable("HTTP_502")
        if action == "crash":
            raise Crash()
        current_sha = self.files.get(path, (None, None))[1]
        if action == "conflict" or sha != current_sha:
            raise LedgerConflict("HTTP_409")
        self.put(path, content)
        self.commits.append(message)
        if action == "lost":
            raise LedgerUnavailable("TimeoutError")

    def ledger(self, path: str = PATH) -> PeriodLedger | None:
        content = self.files.get(path, (None, None))[0]
        return None if content is None else PeriodLedger.from_json(content, *PERIOD)

    def entries(self, path: str = PATH) -> dict:
        ledger = self.ledger(path)
        return {} if ledger is None else dict(ledger.entries)


class Clock:
    def __init__(self) -> None:
        self.wall = datetime(2026, 11, 3, 1, 0, tzinfo=timezone.utc)
        self.mono = 1000.0

    def now(self) -> datetime:
        return self.wall

    def monotonic(self) -> float:
        return self.mono

    def advance(self, seconds: float) -> None:
        self.wall += timedelta(seconds=seconds)
        self.mono += seconds


class FakeSender:
    """``script`` maps an address to what its send does:
    "accept", "accept_then_crash", "disconnect", "refuse", "data_reject",
    "refuse_421", or a callable returning a SendOutcome."""

    def __init__(self, script=None, *, open_error: BaseException | None = None, close_diagnostic=None) -> None:
        self.script = dict(script or {})
        self.open_error = open_error
        self.close_diagnostic = close_diagnostic
        self.opened: list[tuple[str, ...]] = []
        self.delivered: list[str] = []
        self.attempted: list[str] = []

    def recipients(self, recipient_target):
        return tuple(part.strip() for part in recipient_target.split(",") if part.strip())

    def open(self, artifact, addresses):
        if self.open_error is not None:
            raise self.open_error
        self.opened.append(tuple(addresses))
        return _FakeSession(self)


class _FakeSession:
    def __init__(self, sender: FakeSender) -> None:
        self._sender = sender

    def send(self, address):
        sender = self._sender
        sender.attempted.append(address)
        action = sender.script.get(address, "accept")
        if callable(action):
            return action(address)
        if action in ("accept", "accept_then_crash"):
            sender.delivered.append(address)
            if action == "accept_then_crash":
                raise Crash()
            return SendOutcome(True)
        if action == "disconnect":
            return SendOutcome(False, DeliveryFailurePhase.SENDMAIL, "SMTPServerDisconnected", session_usable=False)
        if action == "refuse":
            return SendOutcome(False, DeliveryFailurePhase.SENDMAIL, "SMTPRecipientsRefused")
        if action == "refuse_421":
            return SendOutcome(False, DeliveryFailurePhase.SENDMAIL, "SMTPSenderRefused", 421, session_usable=False)
        if action == "data_reject":
            return SendOutcome(False, DeliveryFailurePhase.SENDMAIL, "SMTPDataError", 554)
        raise AssertionError(action)

    def close(self):
        return self._sender.close_diagnostic


def login_failure() -> DeliveryFailure:
    return DeliveryFailure("login", phase=DeliveryFailurePhase.LOGIN, failure_class="SMTPAuthenticationError", smtp_code=535)


def service(store, sender, clock, run_id, *, release=None, secret=SECRET) -> DeliveryService:
    """One execution (process) of Delivery against the shared fake ledger."""

    return DeliveryService(
        sender=sender,
        live_email_send=True,
        ledger=DeliveryLedgerAccess(store, secret),
        release=release,
        audit={"github_run_id": "41585675879", "github_run_attempt": "1"},
        wall_clock=clock.now,
        monotonic_clock=clock.monotonic,
        execution_id=run_id,
    )
