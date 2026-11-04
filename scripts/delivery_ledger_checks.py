"""RC-55 live checks L1-L3 (contract section A.39): verification tooling only.

Not a production path and not a second owner. L1 and L3 drive the unchanged
Delivery owner (``DeliveryService``) and ledger store against the real private
ledger repository; L2 only probes the token's scope. Nothing printed or
written to the step summary carries an address, a key or a token.

* l1-l2: L1 compare-and-swap on the real contents API, then the owner's
  reconciliation under a real conflict; L2 the token's scope. No email.
* l3: one message, through the Delivery owner, to the sending account only;
  a second invocation must be DUPLICATE. Re-running l3 sends nothing more.

Usage: python -m scripts.delivery_ledger_checks {l1-l2|l3}
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.weekly_report.delivery import (  # noqa: E402
    DeliveryLedgerAccess,
    DeliveryService,
    DeliveryStatus,
    SendOutcome,
)
from src.weekly_report.delivery_ledger import (  # noqa: E402
    EntryState,
    GitHubContentsLedgerStore,
    LedgerConflict,
    LedgerEntry,
    LedgerUnavailable,
    PeriodLedger,
    entry_reference,
    key_id,
    period_path,
    recipient_key,
)
from src.weekly_report.report_service import FinalReportArtifact  # noqa: E402

# Synthetic periods that are never report periods.
L1_PERIOD = (date(1999, 1, 4), date(1999, 1, 10))
L3_PERIOD = (date(2000, 1, 3), date(2000, 1, 9))
APP_REPOSITORY = "DORTS-EMDD/DORTS-EMDD-Weekly-report-v2"


class CheckConfigurationError(RuntimeError):
    pass


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise CheckConfigurationError(f"{name} is not configured")
    return value


def _run_token() -> str:
    run_id, attempt = os.environ.get("GITHUB_RUN_ID", ""), os.environ.get("GITHUB_RUN_ATTEMPT", "")
    return f"{run_id}a{attempt}" if run_id.isdigit() and attempt.isdigit() else uuid4().hex[:16]


def _artifact(period: tuple[date, date], report_id: str, text: str) -> FinalReportArtifact:
    return FinalReportArtifact(report_id, f"formal-report-{report_id[-16:]}", "v1", (), (), text,
                               period_start=period[0], period_end=period[1])


class _NoSmtpSender:
    """L1 only: the owner's sender seam without SMTP; counts sends."""

    def __init__(self) -> None:
        self.sends = 0

    def recipients(self, recipient_target: str) -> tuple[str, ...]:
        return (recipient_target,)

    def open(self, artifact, addresses):
        sender = self

        class _Session:
            def send(self, address):
                sender.sends += 1
                return SendOutcome(True)

            def close(self):
                return None

        return _Session()


class _RacingStore:
    """Delegates to the real store; before the first write, a rival claims the same entry for real."""

    def __init__(self, store, rival: Callable[[], None]) -> None:
        self._store, self._rival = store, rival

    def read(self, path):
        return self._store.read(path)

    def write(self, path, content, sha, message):
        if self._rival is not None:
            rival, self._rival = self._rival, None
            rival()
        return self._store.write(path, content, sha, message)


def check_l1(store, secret: bytes, token: str) -> dict[str, bool]:
    """L1: real compare-and-swap, then the owner's reconciliation under a real conflict."""

    results: dict[str, bool] = {}
    path = f"checks/l1-{token}.json"
    store.write(path, json.dumps({"synthetic": True, "step": 1}), None, "L1 check: create synthetic file")
    _, sha_one = store.read(path)
    store.write(path, json.dumps({"synthetic": True, "step": 2}), sha_one, "L1 check: update synthetic file")
    try:
        store.write(path, json.dumps({"synthetic": True, "step": 3}), sha_one, "L1 check: stale write (must be rejected)")
        results["stale_write_rejected"] = False
    except LedgerConflict:
        results["stale_write_rejected"] = True
    try:
        store.write(path, json.dumps({"synthetic": True, "step": 4}), None, "L1 check: blind create (must be rejected)")
        results["blind_overwrite_rejected"] = False
    except LedgerConflict:
        results["blind_overwrite_rejected"] = True
    text, _ = store.read(path)
    results["stored_value_is_the_last_accepted_write"] = json.loads(text or "{}").get("step") == 2

    # The owner under a real conflict: a rival claims the entry between the
    # owner's read and its claim write; the provider rejects the owner's
    # stale write, and the owner re-reads, sees the rival claim and sends nothing.
    address = f"l1-race-{token}@ledger-check.invalid"
    key = recipient_key(secret, *L1_PERIOD, address)
    ledger_path = period_path(*L1_PERIOD)
    rival_claim = f"rival{token.replace('a', '')}.{entry_reference(key)}"

    def rival() -> None:
        text, sha = store.read(ledger_path)
        ledger = PeriodLedger(*L1_PERIOD, key_id(secret)) if text is None else PeriodLedger.from_json(text, *L1_PERIOD)
        claimed = ledger.with_entry(key, LedgerEntry(EntryState.ATTEMPTED, rival_claim, "1999-01-11T00:00:00+00:00"))
        store.write(ledger_path, claimed.to_json(), sha, "L1 check: rival claim")

    sender = _NoSmtpSender()
    raced = DeliveryService(sender=sender, live_email_send=True, ledger=DeliveryLedgerAccess(_RacingStore(store, rival), secret),
                            execution_id=f"l1race{token.replace('a', '')}")
    receipt = raced.deliver(_artifact(L1_PERIOD, "weekly-report-0000000000000001", "RC-55 L1 synthetic"), address)
    text, _ = store.read(ledger_path)
    entry = PeriodLedger.from_json(text, *L1_PERIOD).entry(key)
    results["owner_sent_nothing_on_a_lost_race"] = sender.sends == 0
    results["rival_claim_kept"] = entry is not None and entry.claim_id == rival_claim and entry.state is EntryState.ATTEMPTED
    results["owner_reported_blocked"] = receipt.status is DeliveryStatus.FAILED and receipt.recipient_counts.get("blocked") == 1

    # The owner's own claim and outcome on the real provider (no SMTP).
    address = f"l1-own-{token}@ledger-check.invalid"
    key = recipient_key(secret, *L1_PERIOD, address)
    sender = _NoSmtpSender()
    first = DeliveryService(sender=sender, live_email_send=True, ledger=DeliveryLedgerAccess(store, secret),
                            execution_id=f"l1own{token.replace('a', '')}").deliver(
        _artifact(L1_PERIOD, "weekly-report-0000000000000001", "RC-55 L1 synthetic"), address)
    second = DeliveryService(sender=sender, live_email_send=True, ledger=DeliveryLedgerAccess(store, secret),
                             execution_id=f"l1again{token.replace('a', '')}").deliver(
        _artifact(L1_PERIOD, "weekly-report-0000000000000001", "RC-55 L1 synthetic"), address)
    text, _ = store.read(ledger_path)
    entry = PeriodLedger.from_json(text, *L1_PERIOD).entry(key)
    results["owner_claim_then_sent"] = (
        first.status is DeliveryStatus.SENT
        and entry is not None
        and [item["state"] for item in entry.history] == ["ATTEMPTED", "SENT"]
    )
    results["second_owner_run_is_duplicate"] = second.status is DeliveryStatus.DUPLICATE and sender.sends == 1
    return results


def check_l2(token_value: str, ledger_repository: str, l1_path: str, *, transport=None) -> dict[str, bool]:
    """L2: the token reads the ledger and cannot write to the application repository."""

    results: dict[str, bool] = {}
    ledger = GitHubContentsLedgerStore(ledger_repository, token_value, transport=transport)
    text, _ = ledger.read(l1_path)
    results["ledger_readable"] = text is not None
    probe = GitHubContentsLedgerStore(APP_REPOSITORY, token_value, transport=transport)
    try:
        # A stale SHA can never change the file: a permitted token gets 409/422,
        # a token without write access gets 403/404.
        probe.write("README.md", "L2 probe", "0" * 40, "L2 probe: must be denied")
        results["application_repository_write_denied"] = False
    except LedgerConflict:
        results["application_repository_write_denied"] = False
    except LedgerUnavailable as exc:
        results["application_repository_write_denied"] = str(exc) in {"HTTP_403", "HTTP_404"}
    return results


def check_l3(store, secret: bytes, sender, recipient: str, token: str) -> dict[str, bool]:
    """L3: one message to the sending account through the Delivery owner; the second run is DUPLICATE."""

    events: list[str] = []
    key = recipient_key(secret, *L3_PERIOD, recipient)

    class _Observed:
        def read(self, path):
            return store.read(path)

        def write(self, path, content, sha, message):
            store.write(path, content, sha, message)
            entry = PeriodLedger.from_json(content, *L3_PERIOD).entry(key)
            events.append(f"write:{entry.state.value if entry else 'none'}")

    class _CountingSender:
        def __init__(self) -> None:
            self.sends = 0

        def recipients(self, target):
            return sender.recipients(target)

        def open(self, artifact, addresses):
            session = sender.open(artifact, addresses)
            outer = self

            class _Session:
                def send(self, address):
                    outer.sends += 1
                    events.append("send")
                    return session.send(address)

                def close(self):
                    return session.close()

            return _Session()

    counting = _CountingSender()
    artifact = _artifact(L3_PERIOD, "weekly-report-0000000000000003",
                         "RC-55 Delivery 驗證訊息：由交付檢查寄給寄件帳號本身，不是正式週報。")
    access = DeliveryLedgerAccess(_Observed(), secret)
    first = DeliveryService(sender=counting, live_email_send=True, ledger=access,
                            execution_id=f"l3first{token.replace('a', '')}").deliver(artifact, recipient)
    second = None
    if first.status in (DeliveryStatus.SENT, DeliveryStatus.DUPLICATE):
        # The duplicate check runs only after a handoff: L3 never retries a failed send.
        second = DeliveryService(sender=counting, live_email_send=True, ledger=access,
                                 execution_id=f"l3second{token.replace('a', '')}").deliver(artifact, recipient)
    text, _ = store.read(period_path(*L3_PERIOD))
    entry = None if text is None else PeriodLedger.from_json(text, *L3_PERIOD).entry(key)
    already = first.status is DeliveryStatus.DUPLICATE
    print(f"l3 first: status={first.status.value} counts={dict(first.recipient_counts)} "
          f"failure={first.failure_signature} diagnostic={first.diagnostic}")
    if second is not None:
        print(f"l3 second: status={second.status.value} counts={dict(second.recipient_counts)}")
    print(f"l3 entry: reference={entry_reference(key)} state={None if entry is None else entry.state.value} "
          f"history={[] if entry is None else [item['state'] for item in entry.history]} events={events}")
    return {
        "first_run_sent_or_already_verified": first.status is DeliveryStatus.SENT or already,
        "claim_persisted_before_smtp": already or events[:2] == ["write:ATTEMPTED", "send"],
        "sent_recorded_after_handoff": entry is not None and entry.state is EntryState.SENT
        and [item["state"] for item in entry.history][-2:] == ["ATTEMPTED", "SENT"],
        "exactly_one_message": counting.sends == (0 if already else 1),
        "second_run_is_duplicate": second is not None and second.status is DeliveryStatus.DUPLICATE,
    }


def _report(title: str, results: dict[str, bool]) -> bool:
    passed = all(results.values())
    lines = [f"{title}: {'PASS' if passed else 'FAIL'}"] + [f"- {name}: {'PASS' if ok else 'FAIL'}" for name, ok in results.items()]
    print("\n".join(lines))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n\n")
    return passed


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    mode = args[0] if args else ""
    if mode not in {"l1-l2", "l3"}:
        print("usage: python -m scripts.delivery_ledger_checks {l1-l2|l3}")
        return 2
    try:
        repository, token_value = _env("DELIVERY_LEDGER_REPOSITORY"), _env("DELIVERY_LEDGER_TOKEN")
        secret = _env("DELIVERY_LEDGER_KEY").encode("utf-8")
        store = GitHubContentsLedgerStore(repository, token_value)
        token = _run_token()
        if mode == "l1-l2":
            l1 = _report("L1 compare-and-swap", check_l1(store, secret, token))
            l2 = _report("L2 token scope", check_l2(token_value, repository, f"checks/l1-{token}.json"))
            return 0 if l1 and l2 else 1
        from src.weekly_report.gmail_smtp import GmailSmtpSender

        sender = GmailSmtpSender.from_environment(os.environ)
        return 0 if _report("L3 controlled delivery", check_l3(store, secret, sender, _env("GMAIL_USER"), token)) else 1
    except Exception as exc:  # noqa: BLE001 - report the class only; never values
        print(f"{mode}: FAIL failure_class={type(exc).__name__}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
