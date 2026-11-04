"""RC-56 (contract section A.40): reporting week, schedule and recipients.

The reporting week is [Monday 00:00, next Monday 00:00) Asia/Taipei, shown as
the inclusive dates Monday..Sunday. One owner decides it
(``production_runner.default_period``) from the Taipei calendar date of the
run, never from the machine's local date; the workflow only says when to
start. Subscriber membership lives in an external mailing list: V2's only
recipients are the configured distribution addresses.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from src.weekly_report import production_runner
from src.weekly_report.production_runner import REPORT_TIMEZONE, REPORT_TIMEZONE_NAME, default_period

ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc


def _taipei(year, month, day, hour=0, minute=0, second=0):
    return datetime(year, month, day, hour, minute, second, tzinfo=REPORT_TIMEZONE)


class ReportingWeekTests(TestCase):
    def test_a_monday_0630_taipei_run_reports_the_week_that_just_ended(self):
        # 2026-11-09 06:30 Asia/Taipei is 2026-11-08 22:30 UTC (still Sunday).
        run = datetime(2026, 11, 8, 22, 30, tzinfo=UTC)
        self.assertEqual(run.astimezone(REPORT_TIMEZONE).strftime("%A %H:%M"), "Monday 06:30")
        self.assertEqual(default_period(run), (date(2026, 11, 2), date(2026, 11, 8)))

    def test_the_boundary_is_monday_midnight_taipei(self):
        self.assertEqual(default_period(_taipei(2026, 11, 9, 0, 0, 0)), (date(2026, 11, 2), date(2026, 11, 8)))
        # One second earlier the week is not complete yet.
        self.assertEqual(default_period(_taipei(2026, 11, 8, 23, 59, 59)), (date(2026, 10, 26), date(2026, 11, 1)))

    def test_a_delayed_run_later_in_the_week_reports_the_same_week(self):
        for later in (_taipei(2026, 11, 9, 9, 0), _taipei(2026, 11, 10, 2, 0), _taipei(2026, 11, 15, 23, 59)):
            self.assertEqual(default_period(later), (date(2026, 11, 2), date(2026, 11, 8)))

    def test_month_and_year_boundaries(self):
        self.assertEqual(default_period(_taipei(2026, 12, 7, 6, 30)), (date(2026, 11, 30), date(2026, 12, 6)))
        self.assertEqual(default_period(_taipei(2027, 1, 4, 6, 30)), (date(2026, 12, 28), date(2027, 1, 3)))
        self.assertEqual(default_period(_taipei(2028, 3, 6, 6, 30)), (date(2028, 2, 28), date(2028, 3, 5)))  # leap year

    def test_consecutive_scheduled_weeks_tile_without_overlap_or_gap(self):
        monday = _taipei(2026, 11, 9, 6, 30)
        previous = None
        for week in range(160):  # about three years of Mondays
            start, end = default_period((monday + timedelta(weeks=week)).astimezone(UTC))
            self.assertEqual(start.weekday(), 0)
            self.assertEqual((end - start).days, 6)
            if previous is not None:
                self.assertEqual(start, previous + timedelta(days=1))  # no gap, no overlap
            previous = end

    def test_the_instant_must_carry_its_time_zone(self):
        with self.assertRaises(ValueError):
            default_period(datetime(2026, 11, 9, 6, 30))

    def test_the_runner_uses_the_owner_and_an_explicit_period_wins(self):
        seen = {}

        class Application:
            def run(self, mode, *, period_start, period_end):
                seen["period"] = (period_start, period_end)
                raise RuntimeError("stop")

        runner = production_runner.ProductionRunner(Application())
        with patch.object(production_runner, "default_period", return_value=(date(2026, 11, 2), date(2026, 11, 8))):
            runner.run()
        self.assertEqual(seen["period"], (date(2026, 11, 2), date(2026, 11, 8)))
        runner.run(period_start="2026-10-01", period_end="2026-10-07")
        self.assertEqual(seen["period"], (date(2026, 10, 1), date(2026, 10, 7)))


class SingleOwnerTests(TestCase):
    def test_no_entry_point_computes_its_own_week(self):
        for path in (ROOT / "streamlit_app.py", ROOT / "main.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("weekday()", text, path.name)
            self.assertNotIn("date.today()", text, path.name)
        self.assertIn("default_period()", (ROOT / "streamlit_app.py").read_text(encoding="utf-8"))
        for source in (ROOT / "src" / "weekly_report").glob("*.py"):
            if source.name == "production_runner.py":
                continue
            self.assertNotIn("date.today()", source.read_text(encoding="utf-8"), source.name)

    def test_the_schedule_starts_at_0630_in_the_reporting_time_zone(self):
        workflow = (ROOT / ".github" / "workflows" / "weekly-report.yml").read_text(encoding="utf-8")
        self.assertIn(f'cron: "30 6 * * 1"\n      timezone: "{REPORT_TIMEZONE_NAME}"', workflow)
        self.assertEqual(REPORT_TIMEZONE.utcoffset(None), timedelta(hours=8))
        # Scheduled email stays behind its own explicit opt-in.
        self.assertIn("vars.WEEKLY_REPORT_SCHEDULE == 'enabled'", workflow)
        self.assertIn("vars.LIVE_EMAIL_SEND == '1'", workflow)


class RecipientOwnershipTests(TestCase):
    def test_v2_has_no_subscriber_registry(self):
        # Membership is owned by the external mailing list; V2 knows only the
        # configured distribution addresses (DEFAULT_RECIPIENTS, a secret).
        for source in list((ROOT / "src" / "weekly_report").glob("*.py")) + [ROOT / "main.py", ROOT / "streamlit_app.py"]:
            text = source.read_text(encoding="utf-8").lower()
            self.assertNotIn("subscriber", text, source.name)
        runner = (ROOT / "src" / "weekly_report" / "production_runner.py").read_text(encoding="utf-8")
        self.assertIn('values.get("DEFAULT_RECIPIENTS")', runner)

    def test_a_distribution_list_is_one_recipient_and_a_rerun_is_duplicate(self):
        from tests.delivery_fakes import PERIOD, Clock, FakeLedgerStore, FakeSender, service
        from src.weekly_report.delivery import DeliveryStatus
        from src.weekly_report.report_service import FinalReportArtifact

        artifact = FinalReportArtifact("weekly-report-0000000000000056", "formal-report-56", "v1", (), (), "本期無符合正式報導條件之事件。",
                                       period_start=PERIOD[0], period_end=PERIOD[1])
        store, clock = FakeLedgerStore(), Clock()
        first_sender, rerun_sender = FakeSender(), FakeSender()
        first = service(store, first_sender, clock, "run1").deliver(artifact, "weekly-list@example.test")
        rerun = service(store, rerun_sender, clock, "run2").deliver(artifact, "weekly-list@example.test")
        self.assertEqual((first.status, rerun.status), (DeliveryStatus.SENT, DeliveryStatus.DUPLICATE))
        self.assertEqual((first_sender.delivered, rerun_sender.delivered), (["weekly-list@example.test"], []))
