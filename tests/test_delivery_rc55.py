"""RC-55 (contract section A.39): the Delivery handoff ledger.

Offline acceptance criteria: a compare-and-swap fake ledger store with failure
injection and a scripted SMTP sender. The rule under test: a recipient is sent
only on a confirmed claim; ATTEMPTED and SENT block; only the claim's own
execution records its outcome; claim age is never evidence; a release names an
ATTEMPTED claim at least 24 hours old, on a manual run, all or nothing.
"""

from __future__ import annotations

from datetime import date, timedelta
import json
from unittest import TestCase

from tests.delivery_fakes import (
    PATH,
    PERIOD,
    SECRET,
    Clock,
    Crash,
    FakeLedgerStore,
    FakeSender,
    login_failure,
    service,
)
from src.weekly_report.delivery import (
    DeliveryLedgerAccess,
    DeliveryReceipt,
    DeliveryService,
    DeliveryStatus,
    ReleaseRequest,
    SendOutcome,
)
from src.weekly_report.delivery_ledger import (
    EntryState,
    GitHubContentsLedgerStore,
    LedgerConflict,
    LedgerEntry,
    LedgerInvariantError,
    LedgerUnavailable,
    PeriodLedger,
    check_transition,
    entry_reference,
    key_id,
    recipient_key,
)
from src.weekly_report.report_service import ReportService
from src.weekly_report.validator import Validator
from src.weekly_report.writer import WriterReportBlock

from test_report_service import _semantic_provider, _workflow_result

A, B, C = "alpha@example.test", "bravo@example.test", "charlie@example.test"


def _artifact(summary: str = "事件摘要 Taiwan Metro"):
    result = _workflow_result()
    report_service = ReportService()
    metadata = report_service.project_formal_metadata((result,))
    validation = Validator(semantic_provider=_semantic_provider).validate(
        (result,), metadata, (WriterReportBlock("E1", "事件標題", summary, "可供臺北捷運評估規劃方向"),)
    )
    return report_service.assemble_final_report(validation, period=PERIOD)


def _key(address: str) -> str:
    return recipient_key(SECRET, *PERIOD, address)


def _ref(address: str) -> str:
    return entry_reference(_key(address))


class _Base(TestCase):
    def setUp(self) -> None:
        self.store = FakeLedgerStore()
        self.clock = Clock()
        self.artifact = _artifact()

    def run_delivery(self, sender, run_id, recipients=(A,), release=None):
        return service(self.store, sender, self.clock, run_id, release=release).deliver(self.artifact, ", ".join(recipients))

    def state(self, address):
        entry = self.store.entries().get(_key(address))
        return None if entry is None else entry.state

    def entry(self, address):
        return self.store.entries().get(_key(address))


class StatesAndSendsTests(_Base):
    def test_01_fresh_period_claims_then_records_sent(self):
        sender = FakeSender()
        receipt = self.run_delivery(sender, "run1", (A, B))
        self.assertEqual(receipt.status, DeliveryStatus.SENT)
        self.assertEqual(sender.delivered, [A, B])
        for address in (A, B):
            entry = self.entry(address)
            self.assertEqual(entry.state, EntryState.SENT)
            self.assertEqual([item["state"] for item in entry.history], ["ATTEMPTED", "SENT"])
            self.assertEqual(entry.claim_id, f"run1.{_ref(address)}")
        self.assertEqual(receipt.recipient_counts["sent"], 2)

    def test_02_rerun_is_duplicate_without_smtp(self):
        self.run_delivery(FakeSender(), "run1", (A, B))
        again = FakeSender()
        receipt = self.run_delivery(again, "run2", (A, B))
        self.assertEqual(receipt.status, DeliveryStatus.DUPLICATE)
        self.assertEqual((again.opened, again.attempted), ([], []))

    def test_03_session_that_cannot_open_writes_nothing_and_the_next_run_sends(self):
        receipt = self.run_delivery(FakeSender(open_error=login_failure()), "run1")
        self.assertEqual(receipt.status, DeliveryStatus.FAILED)
        self.assertEqual(receipt.failure_signature, "LOGIN:SMTPAuthenticationError:535")
        self.assertEqual(self.store.files, {})
        sender = FakeSender()
        self.assertEqual(self.run_delivery(sender, "run2").status, DeliveryStatus.SENT)
        self.assertEqual(sender.delivered, [A])

    def test_04_explicit_refusals_are_not_sent_and_the_next_run_sends(self):
        for action, signature in (("refuse", "SENDMAIL:SMTPRecipientsRefused"), ("data_reject", "SENDMAIL:SMTPDataError:554")):
            with self.subTest(action):
                self.setUp()
                receipt = self.run_delivery(FakeSender({A: action}), "run1")
                self.assertEqual((receipt.status, receipt.failure_signature), (DeliveryStatus.FAILED, signature))
                self.assertEqual(self.state(A), EntryState.NOT_SENT)
                sender = FakeSender()
                self.assertEqual(self.run_delivery(sender, "run2").status, DeliveryStatus.SENT)
                self.assertEqual(sender.delivered, [A])

    def test_05_disconnect_leaves_attempted_and_the_next_run_does_not_send(self):
        receipt = self.run_delivery(FakeSender({A: "disconnect"}), "run1")
        self.assertEqual(receipt.status, DeliveryStatus.FAILED)
        self.assertEqual(self.state(A), EntryState.ATTEMPTED)
        self.assertEqual(receipt.attempted_claims, (f"{_ref(A)}@run1|age=0h|HANDOFF_UNKNOWN",))
        sender = FakeSender()
        second = self.run_delivery(sender, "run2")
        self.assertEqual((second.status, sender.attempted), (DeliveryStatus.FAILED, []))
        self.assertEqual(second.recipient_counts["blocked"], 1)

    def test_06_error_at_quit_after_the_handoff_keeps_sent(self):
        receipt = self.run_delivery(FakeSender(close_diagnostic="QUIT:SMTPResponseException:451"), "run1")
        self.assertEqual(receipt.status, DeliveryStatus.SENT)
        self.assertEqual(receipt.diagnostic, "QUIT:SMTPResponseException:451")
        self.assertEqual(self.state(A), EntryState.SENT)

    def test_07_a_lost_session_leaves_later_recipients_unclaimed(self):
        receipt = self.run_delivery(FakeSender({A: "refuse_421"}), "run1", (A, B, C))
        self.assertEqual(receipt.status, DeliveryStatus.FAILED)
        self.assertEqual((self.state(A), self.state(B), self.state(C)), (EntryState.NOT_SENT, None, None))
        self.assertEqual(receipt.recipient_counts["not_reached"], 2)
        sender = FakeSender()
        self.assertEqual(self.run_delivery(sender, "run2", (A, B, C)).status, DeliveryStatus.SENT)
        self.assertEqual(sender.delivered, [A, B, C])

    def test_08_the_holder_does_not_begin_a_transaction_after_one_hour(self):
        def stall(store, path):
            self.clock.advance(3601)

        self.store.before_write = stall  # the claim write stalls an hour
        sender = FakeSender()
        receipt = self.run_delivery(sender, "run1")
        self.assertEqual((sender.attempted, self.state(A)), ([], EntryState.NOT_SENT))
        self.assertEqual(receipt.failure_signature, "SENDER:SendWindowExpired")

    def test_08b_an_hour_passing_during_the_transaction_never_makes_it_not_sent(self):
        def slow(outcome):
            def send(address):
                self.clock.advance(4000)
                return outcome
            return send

        for outcome, expected in (
            (SendOutcome(True), EntryState.SENT),
            (SendOutcome(False, failure_class="SMTPServerDisconnected", session_usable=False), EntryState.ATTEMPTED),
        ):
            with self.subTest(expected):
                self.setUp()
                self.run_delivery(FakeSender({A: slow(outcome)}), "run1")
                self.assertEqual(self.state(A), expected)


class PostHandoffLedgerFailureTests(_Base):
    def test_09_handoff_observed_but_unrecorded_stays_attempted_and_blocks(self):
        self.store.write_plan = ["ok", "unavailable", "unavailable", "unavailable"]
        sender = FakeSender()
        receipt = self.run_delivery(sender, "run1")
        self.assertEqual(sender.delivered, [A])
        self.assertEqual(receipt.status, DeliveryStatus.FAILED)
        self.assertEqual(self.entry(A).state, EntryState.ATTEMPTED)
        self.assertEqual(self.entry(A).claim_id, f"run1.{_ref(A)}")
        self.assertEqual(receipt.attempted_claims, (f"{_ref(A)}@run1|age=0h|HANDOFF_OBSERVED_UNRECORDED",))
        later = FakeSender()
        self.run_delivery(later, "run2")
        self.assertEqual(later.attempted, [])

    def test_10_outcome_write_with_a_lost_response_is_reconciled_without_a_second_write(self):
        self.store.write_plan = ["ok", "lost"]
        receipt = self.run_delivery(FakeSender(), "run1")
        self.assertEqual((receipt.status, self.state(A)), (DeliveryStatus.SENT, EntryState.SENT))
        self.assertEqual(len(self.store.commits), 2)

    def test_11_stale_outcome_write_is_retried_from_a_fresh_read(self):
        def competing(store, path):
            # Another recipient's entry changes in the same period file.
            ledger = store.ledger()
            other = "f" * 64
            store.put(path, ledger.with_entry(other, LedgerEntry(EntryState.ATTEMPTED, f"other.{other[:16]}", "2026-11-03T00:00:00+00:00")).to_json())

        def accept_then_compete(address):
            self.store.before_write = competing  # fires before the outcome write
            return SendOutcome(True)

        receipt = self.run_delivery(FakeSender({A: accept_then_compete}), "run1")
        self.assertEqual((receipt.status, self.state(A)), (DeliveryStatus.SENT, EntryState.SENT))
        self.assertIn(f"other.{'f' * 16}", self.store.files[PATH][0])

    def test_12_crash_after_the_handoff_blocks_the_next_run(self):
        with self.assertRaises(Crash):
            self.run_delivery(FakeSender({A: "accept_then_crash"}), "run1")
        later = FakeSender()
        self.assertEqual(self.run_delivery(later, "run2").status, DeliveryStatus.FAILED)
        self.assertEqual(later.attempted, [])

    def test_12a_crash_after_250_then_claim_ages_and_scheduled_runs_never_resend(self):
        first = FakeSender({A: "accept_then_crash"})
        with self.assertRaises(Crash):
            self.run_delivery(first, "run1")
        before = self.store.files[PATH][0]
        received = list(first.delivered)
        for index, hours in enumerate((1, 6, 24, 30 * 24), start=2):
            self.clock.advance(hours * 3600)
            later = FakeSender()
            receipt = self.run_delivery(later, f"run{index}")
            received += later.delivered
            self.assertEqual(received.count(A), 1, "the recipient must never receive a second message")
            self.assertEqual(self.store.files[PATH][0], before)
            self.assertEqual(receipt.status, DeliveryStatus.FAILED)
            self.assertTrue(receipt.attempted_claims[0].startswith(f"{_ref(A)}@run1|age="))
        # A manual run without a matching release sends nothing either.
        manual = FakeSender()
        unrelated = ReleaseRequest.parse("2026-10-27..2026-11-02", f"{'0' * 16}@run9", manual=True, actor="operator")
        self.run_delivery(manual, "run9", release=unrelated)
        self.assertEqual(manual.delivered, [])

    def test_12b_claims_belong_to_one_execution_even_with_equal_github_ids(self):
        with self.assertRaises(Crash):
            self.run_delivery(FakeSender({A: "accept_then_crash"}), "exec1")
        other = FakeSender()
        receipt = self.run_delivery(other, "exec2")  # same GitHub run/attempt audit values
        self.assertEqual(other.attempted, [])
        self.assertEqual(receipt.status, DeliveryStatus.FAILED)
        self.assertEqual(self.entry(A).claim_id, f"exec1.{_ref(A)}")

    def test_13_outcome_write_finding_another_claim_is_an_invariant_failure(self):
        def steal(store, path):
            ledger = store.ledger()
            key = _key(A)
            store.put(path, ledger.with_entry(key, LedgerEntry(EntryState.ATTEMPTED, f"thief.{_ref(A)}", "2026-11-03T00:00:00+00:00")).to_json())

        sent = []

        def accept_then_steal(address):
            sent.append(address)
            self.store.before_write = steal  # fires before the outcome write
            return SendOutcome(True)

        receipt = self.run_delivery(FakeSender({A: accept_then_steal}), "run1")
        self.assertEqual(receipt.status, DeliveryStatus.FAILED)
        self.assertEqual(receipt.failure_signature, "LEDGER:LedgerInvariantError")
        self.assertEqual(sent, [A])  # sent once, never again
        self.assertEqual(self.entry(A).claim_id, f"thief.{_ref(A)}")

    def test_14_claim_write_with_a_lost_response_is_held_and_sent_once(self):
        self.store.write_plan = ["lost"]
        sender = FakeSender()
        receipt = self.run_delivery(sender, "run1")
        self.assertEqual((receipt.status, sender.delivered), (DeliveryStatus.SENT, [A]))

    def test_15_unconfirmed_claim_is_never_acted_on(self):
        def reads_fail_after_this_write(store, path):
            store.read_failures = 10  # the claim is written, its response is lost, re-reads fail

        self.store.before_write = reads_fail_after_this_write
        self.store.write_plan = ["lost"]
        sender = FakeSender()
        receipt = self.run_delivery(sender, "run1")
        self.assertEqual(sender.attempted, [])
        self.assertEqual(receipt.status, DeliveryStatus.FAILED)
        self.assertEqual(receipt.attempted_claims, (f"{_ref(A)}@run1|age=0h|CLAIM_UNCONFIRMED",))
        self.assertEqual(self.entry(A).claim_id, f"run1.{_ref(A)}")  # written, but never acted on


class ConcurrencyTests(_Base):
    def test_16_two_writers_from_one_sha_hold_exactly_one_claim(self):
        def rival_claims(store, path):
            ledger = store.ledger() or PeriodLedger(*PERIOD, key_id(SECRET))
            store.put(path, ledger.with_entry(_key(A), LedgerEntry(EntryState.ATTEMPTED, f"rival.{_ref(A)}", "2026-11-03T01:00:00+00:00")).to_json())

        self.store.before_write = rival_claims
        sender = FakeSender()
        receipt = self.run_delivery(sender, "run1")
        self.assertEqual(sender.attempted, [])
        self.assertEqual(self.entry(A).claim_id, f"rival.{_ref(A)}")
        self.assertEqual(receipt.recipient_counts["blocked"], 1)

    def test_17_writers_on_different_recipients_both_succeed(self):
        def rival_takes_b(store, path):
            ledger = store.ledger() or PeriodLedger(*PERIOD, key_id(SECRET))
            store.put(path, ledger.with_entry(_key(B), LedgerEntry(EntryState.SENT, f"rival.{_ref(B)}", "2026-11-03T01:00:00+00:00")).to_json())

        self.store.before_write = rival_takes_b
        sender = FakeSender()
        receipt = self.run_delivery(sender, "run1", (A, B))
        self.assertEqual(sender.delivered, [A])
        self.assertEqual((self.state(A), self.state(B)), (EntryState.SENT, EntryState.SENT))
        self.assertEqual(receipt.status, DeliveryStatus.SENT)


class ReleaseTests(_Base):
    def _three_attempted(self):
        sender = FakeSender({A: "disconnect"})
        self.run_delivery(sender, "runA", (A,))
        self.run_delivery(FakeSender({B: "disconnect"}), "runB", (B,))
        self.run_delivery(FakeSender({C: "disconnect"}), "runC", (C,))
        self.run_delivery(FakeSender(), "runD", ("delta@example.test",))
        self.clock.advance(25 * 3600)

    def _release(self, claims, *, period="2026-10-27..2026-11-02", manual=True):
        return ReleaseRequest.parse(period, claims, manual=manual, actor="operator")

    def test_18_release_changes_only_the_named_claim(self):
        self._three_attempted()
        before = {key: entry.as_mapping() for key, entry in self.store.entries().items()}
        sender = FakeSender()
        receipt = self.run_delivery(sender, "runR", (A,), release=self._release(f"{_ref(A)}@runA"))
        after = self.store.entries()
        self.assertEqual(sender.delivered, [A])
        self.assertEqual(after[_key(A)].state, EntryState.SENT)
        released = [item for item in after[_key(A)].history if item["state"] == "RELEASED"][0]
        self.assertEqual((released["actor"], released["release_run"], released["claim_id"]), ("operator", "runR", f"runA.{_ref(A)}"))
        for address in (B, C, "delta@example.test"):
            self.assertEqual(after[_key(address)].as_mapping(), before[_key(address)])
        self.assertTrue(any(message.startswith(f"release {_ref(A)} by operator in runR") for message in self.store.commits))
        self.assertEqual(receipt.recipient_counts["released"], 1)

    def test_19_a_claim_younger_than_24_hours_is_not_released(self):
        self.run_delivery(FakeSender({A: "disconnect"}), "runA")
        self.clock.advance(23 * 3600)
        sender = FakeSender()
        receipt = self.run_delivery(sender, "runR", release=self._release(f"{_ref(A)}@runA"))
        self.assertEqual((receipt.failure_signature, sender.attempted), ("RELEASE:ReleaseRefused", []))
        self.assertEqual(self.state(A), EntryState.ATTEMPTED)

    def test_20_a_different_claim_on_the_named_entry_is_not_released(self):
        self.run_delivery(FakeSender({A: "disconnect"}), "runA")
        self.clock.advance(25 * 3600)
        receipt = self.run_delivery(FakeSender(), "runR", release=self._release(f"{_ref(A)}@runZ"))
        self.assertEqual(receipt.failure_signature, "RELEASE:ReleaseRefused")
        self.assertEqual(self.state(A), EntryState.ATTEMPTED)

    def test_21_any_invalid_name_releases_nothing(self):
        self._three_attempted()
        delta = "delta@example.test"
        unknown = "0" * 16
        for bad in (f"{_ref(delta)}@runD", f"{unknown}@runA"):
            with self.subTest(bad):
                before = self.store.files[PATH][0]
                receipt = self.run_delivery(FakeSender(), "runR", (A,), release=self._release(f"{_ref(A)}@runA,{bad}"))
                self.assertEqual(receipt.failure_signature, "RELEASE:ReleaseRefused")
                self.assertEqual(self.store.files[PATH][0], before)

    def test_21b_an_ambiguous_reference_releases_nothing(self):
        twin = _ref(A) + "0" * 48
        ledger = PeriodLedger(*PERIOD, key_id(SECRET)).with_entry(
            _key(A), LedgerEntry(EntryState.ATTEMPTED, f"runA.{_ref(A)}", "2026-11-01T00:00:00+00:00")
        ).with_entry(twin, LedgerEntry(EntryState.ATTEMPTED, f"runA.{_ref(A)}", "2026-11-01T00:00:00+00:00"))
        self.store.put(PATH, ledger.to_json())
        receipt = self.run_delivery(FakeSender(), "runR", release=self._release(f"{_ref(A)}@runA"))
        self.assertEqual(receipt.failure_signature, "RELEASE:ReleaseRefused")
        self.assertEqual(self.state(A), EntryState.ATTEMPTED)

    def test_22_scheduled_run_other_period_or_other_key_refuses_release(self):
        self.run_delivery(FakeSender({A: "disconnect"}), "runA")
        self.clock.advance(25 * 3600)
        name = f"{_ref(A)}@runA"
        for release in (self._release(name, manual=False), self._release(name, period="2026-10-20..2026-10-26")):
            with self.subTest(release):
                receipt = self.run_delivery(FakeSender(), "runR", release=release)
                self.assertEqual(receipt.failure_signature, "RELEASE:ReleaseRefused")
                self.assertEqual(self.state(A), EntryState.ATTEMPTED)
        other_key = service(self.store, FakeSender(), self.clock, "runK", release=self._release(name), secret=b"x" * 40)
        receipt = other_key.deliver(self.artifact, A)
        self.assertEqual(receipt.failure_signature, "LEDGER:KeyMismatch")
        self.assertEqual(self.state(A), EntryState.ATTEMPTED)

    def test_23_releasing_run_sends_released_and_new_recipients_only(self):
        self.run_delivery(FakeSender(), "run0", (B,))
        self.run_delivery(FakeSender({A: "disconnect"}), "runA", (A,))
        self.clock.advance(25 * 3600)
        sender = FakeSender()
        receipt = self.run_delivery(sender, "runR", (A, B, C), release=self._release(f"{_ref(A)}@runA"))
        self.assertEqual(sorted(sender.delivered), sorted([A, C]))
        self.assertEqual(receipt.status, DeliveryStatus.SENT)

    def test_24_releasing_a_handoff_observed_unrecorded_entry_resends_by_operator_decision(self):
        self.store.write_plan = ["ok", "unavailable", "unavailable", "unavailable"]
        first = FakeSender()
        self.run_delivery(first, "runA")
        self.clock.advance(25 * 3600)
        second = FakeSender()
        self.run_delivery(second, "runR", release=self._release(f"{_ref(A)}@runA"))
        # The rule accepts the release; the duplicate is the operator's decision.
        self.assertEqual(first.delivered + second.delivered, [A, A])


class InvariantAndPrivacyTests(_Base):
    def test_25_transition_table(self):
        attempted = LedgerEntry(EntryState.ATTEMPTED, f"run1.{'a' * 16}", "2026-11-03T00:00:00+00:00")
        check_transition(None, EntryState.ATTEMPTED, f"run1.{'a' * 16}")
        for state in (EntryState.NOT_SENT, EntryState.RELEASED):
            check_transition(LedgerEntry(state, f"run0.{'a' * 16}", "x"), EntryState.ATTEMPTED, f"run1.{'a' * 16}")
        for target in (EntryState.SENT, EntryState.NOT_SENT, EntryState.RELEASED):
            check_transition(attempted, target, f"run1.{'a' * 16}")
            with self.assertRaises(LedgerInvariantError):
                check_transition(attempted, target, f"run2.{'a' * 16}")
        sent = LedgerEntry(EntryState.SENT, f"run1.{'a' * 16}", "x")
        for target in EntryState:
            with self.assertRaises(LedgerInvariantError):
                check_transition(sent, target, f"run1.{'a' * 16}")
        with self.assertRaises(LedgerInvariantError):
            check_transition(attempted, EntryState.ATTEMPTED, f"run1.{'a' * 16}")
        with self.assertRaises(LedgerInvariantError):
            check_transition(None, EntryState.SENT, f"run1.{'a' * 16}")

    def test_26_recipients_added_or_removed(self):
        self.run_delivery(FakeSender(), "run1", (A, B))
        sender = FakeSender()
        receipt = self.run_delivery(sender, "run2", (A, C))
        self.assertEqual((sender.delivered, receipt.status), ([C], DeliveryStatus.SENT))

    def test_28_key_is_stable_across_case_and_differs_across_periods(self):
        self.assertEqual(recipient_key(SECRET, *PERIOD, " Alpha@Example.TEST "), _key(A))
        self.assertNotEqual(recipient_key(SECRET, date(2026, 11, 3), date(2026, 11, 9), A), _key(A))
        self.assertNotEqual(recipient_key(b"y" * 40, *PERIOD, A), _key(A))

    def test_29_no_address_key_or_secret_leaves_delivery(self):
        self.store.write_plan = ["ok", "unavailable", "unavailable", "unavailable"]
        receipt = self.run_delivery(FakeSender(), "run1", (A, B))
        published = "".join(content for content, _ in self.store.files.values()) + "".join(self.store.commits)
        observed = f"{receipt.attempted_claims}{receipt.recipient_counts}{receipt.failure_signature}{repr(receipt)}"
        for secret_value in (A, B, "alpha", SECRET.decode()):
            self.assertNotIn(secret_value, published)
            self.assertNotIn(secret_value, observed)
        self.assertNotIn(_key(A), observed)

    def test_30_live_email_requires_the_ledger(self):
        with self.assertRaises(ValueError):
            DeliveryService(sender=FakeSender(), live_email_send=True)

    def test_31_a_period_with_no_entries_is_sent_normally(self):
        sender = FakeSender()
        self.assertEqual(self.run_delivery(sender, "run1").status, DeliveryStatus.SENT)
        self.assertEqual(sender.delivered, [A])

    def test_staged_delivery_reads_and_writes_nothing(self):
        staged = DeliveryService(live_email_send=False).deliver(self.artifact, A)
        self.assertEqual(staged.status, DeliveryStatus.STAGED)
        self.assertEqual(self.store.files, {})

    def test_unreadable_or_malformed_ledger_sends_nothing(self):
        for setup in ("unreadable", "malformed"):
            with self.subTest(setup):
                self.setUp()
                if setup == "unreadable":
                    self.store.read_failures = 3
                else:
                    self.store.put(PATH, json.dumps({"sent": 3}))
                sender = FakeSender()
                receipt = self.run_delivery(sender, "run1")
                self.assertEqual((receipt.status, sender.opened), (DeliveryStatus.FAILED, []))
                self.assertTrue(receipt.failure_signature.startswith("LEDGER:"))

    def test_receipt_rejects_unsafe_observation_lines(self):
        from src.weekly_report.delivery import DeliveryIdentity

        identity = DeliveryIdentity("r", "a", "v1", "target")
        for line in ("alpha@example.test|age=1h", f"{'a' * 16}@run1|age=1h|alpha@example.test"):
            with self.assertRaises(ValueError):
                DeliveryReceipt(identity, DeliveryStatus.FAILED, (), attempted_claims=(line,))


class ReleaseRequestTests(TestCase):
    def test_parse_accepts_named_claims_only(self):
        request = ReleaseRequest.parse("2026-10-27..2026-11-02", f"{'a' * 16}@run1, {'b' * 16}@run2", manual=True, actor="op")
        self.assertEqual(request.claims, (("a" * 16, "run1"), ("b" * 16, "run2")))
        for period, claims in (
            ("2026-10-27", f"{'a' * 16}@run1"),
            ("2026-10-27..2026-11-02", ""),
            ("2026-10-27..2026-11-02", "alpha@example.test"),
            ("2026-10-27..2026-11-02", f"{'a' * 16}@run1,{'a' * 16}@run1"),
        ):
            with self.assertRaises(ValueError):
                ReleaseRequest.parse(period, claims, manual=True, actor="op")
        odd = ReleaseRequest.parse("2026-10-27..2026-11-02", f"{'a' * 16}@run1", manual=True, actor="op\nrelease *")
        self.assertEqual(odd.actor, "unknown")

    def test_audit_fields_never_overwrite_history_fields(self):
        store, clock = FakeLedgerStore(), Clock()
        live = DeliveryService(
            sender=FakeSender(), live_email_send=True,
            ledger=DeliveryLedgerAccess(store, SECRET),
            audit={"state": "SENT", "claim_id": "forged", "github_run_id": "123"},
            wall_clock=clock.now, monotonic_clock=clock.monotonic, execution_id="run1",
        )
        live.deliver(_artifact(), A)
        history = store.entries()[_key(A)].history
        self.assertEqual([item["state"] for item in history], ["ATTEMPTED", "SENT"])
        self.assertTrue(all(item["claim_id"] == f"run1.{_ref(A)}" and item["github_run_id"] == "123" for item in history))


class GitHubContentsLedgerStoreTests(TestCase):
    def _store(self, responses, calls):
        def transport(method, url, headers, body, timeout):
            calls.append((method, url, headers, body))
            response = responses.pop(0)
            if isinstance(response, BaseException):
                raise response
            return response

        return GitHubContentsLedgerStore("DORTS-EMDD/delivery-ledger", "token-value", transport=transport)

    def test_read_absent_present_and_errors(self):
        import base64

        calls = []
        body = json.dumps({"content": base64.b64encode("hello".encode()).decode(), "sha": "abc"}).encode()
        store = self._store([(404, b""), (200, body), (500, b""), OSError("down")], calls)
        self.assertEqual(store.read("periods/x.json"), (None, None))
        self.assertEqual(store.read("periods/x.json"), ("hello", "abc"))
        for _ in range(2):
            with self.assertRaises(LedgerUnavailable):
                store.read("periods/x.json")
        self.assertEqual(calls[0][0], "GET")
        self.assertTrue(calls[0][1].startswith("https://api.github.com/repos/DORTS-EMDD/delivery-ledger/contents/periods/x.json?ref="))
        self.assertEqual(calls[0][2]["Authorization"], "Bearer token-value")

    def test_write_is_compare_and_swap(self):
        calls = []
        store = self._store([(200, b""), (409, b""), (422, b""), (502, b"")], calls)
        store.write("periods/x.json", "text", "abc", "claim")
        self.assertEqual(json.loads(calls[0][3])["sha"], "abc")
        for expected in (LedgerConflict, LedgerConflict, LedgerUnavailable):
            with self.assertRaises(expected):
                store.write("periods/x.json", "text", "stale", "claim")
        store_without_sha = self._store([(201, b"")], calls)
        store_without_sha.write("periods/y.json", "text", None, "claim")
        self.assertNotIn("sha", json.loads(calls[-1][3]))

    def test_token_is_never_in_repr_and_configuration_is_checked(self):
        store = GitHubContentsLedgerStore("DORTS-EMDD/delivery-ledger", "token-value")
        self.assertNotIn("token-value", repr(store))
        for repository, token in (("no-slash", "t"), ("a/b", ""), ("a/b", "has space")):
            with self.assertRaises(ValueError):
                GitHubContentsLedgerStore(repository, token)
