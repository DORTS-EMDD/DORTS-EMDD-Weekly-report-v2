from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.weekly_report.contracts import (  # noqa: E402
    RegionMode,
    SearchAttemptResult,
    SearchTerminalStatus,
    SearchTechnicalFailureClass,
)
from src.weekly_report.google_news_rss_provider import (  # noqa: E402
    GoogleNewsRssProvider,
    RssTransportResponse,
)
from src.weekly_report.production_runner import (  # noqa: E402
    GoogleNewsHealthCheck,
    HEALTH_PROBE_ORDINALS,
    ProductionRunStatus,
    ProductionRunner,
)
from src.weekly_report.region_registry import RegionRegistry  # noqa: E402
from src.weekly_report.report_service import FinalReportArtifact  # noqa: E402
from src.weekly_report.search_planner import SearchPlanner  # noqa: E402


def _application_result(*, technical: bool = False, artifact=None):
    plan = SimpleNamespace(items=())
    attempt = (
        SearchAttemptResult(
            "fixture",
            SearchTerminalStatus.TECHNICAL_FAILURE,
            technical_failure_class=SearchTechnicalFailureClass.TIMEOUT,
        )
        if technical
        else None
    )
    execution = SimpleNamespace(
        execution_complete=True,
        has_technical_failures=technical,
        attempt_results=tuple(item for item in (attempt,) if item is not None),
        unattempted_items=(),
        infrastructure_failure=None,
    )
    return SimpleNamespace(
        plan=plan,
        execution=execution,
        acquisitions=(),
        normalized_observations=(),
        evidence_results=(),
        scope_results=(),
        temporal_results=(),
        event_identity_records=(),
        category_results=(),
        downstream_results=(),
        ordered_results=(),
        formal_metadata=(),
        writer_blocks=(),
        validation_result=None,
        final_report=artifact,
        delivery_result=None,
    )


class _FakeApplication:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def run(self, mode, *, period_start, period_end):
        self.calls += 1
        self.last_call = (mode, period_start, period_end)
        return self.result


class ProductionRunnerTests(unittest.TestCase):
    def test_runner_invokes_one_shared_application_and_propagates_artifact(self):
        artifact = FinalReportArtifact("report-1", "artifact-1", "v1", (), (), "# empty")
        app = _FakeApplication(_application_result(artifact=artifact))
        runner = ProductionRunner(app)
        result = runner.run(
            region_mode=RegionMode.SELECTED,
            period_start=date(2026, 10, 1),
            period_end=date(2026, 10, 7),
        )
        self.assertEqual(app.calls, 1)
        self.assertIs(result.final_report, artifact)
        self.assertEqual(result.status, ProductionRunStatus.SUCCESS)
        self.assertEqual(result.artifact_id, "artifact-1")
        self.assertNotIn("MAIAGENT_API_KEY", result.summary())

    def test_search_technical_failure_is_a_runner_failure_without_retry(self):
        app = _FakeApplication(_application_result(technical=True))
        result = ProductionRunner(app).run(
            period_start="2026-10-01", period_end="2026-10-07"
        )
        self.assertEqual(app.calls, 1)
        self.assertEqual(result.status, ProductionRunStatus.TECHNICAL_FAILURE)
        self.assertEqual(result.failure_stage, "search")
        self.assertEqual(result.failure_class, "TIMEOUT")

    def test_legal_zero_event_artifact_is_success(self):
        artifact = FinalReportArtifact("report-0", "artifact-0", "v1", (), (), "No events")
        result = ProductionRunner(_FakeApplication(_application_result(artifact=artifact))).run(
            period_start="2026-10-01", period_end="2026-10-07"
        )
        self.assertTrue(result.successful)
        self.assertEqual(result.final_report.event_count, 0)


class GoogleNewsHealthCheckTests(unittest.TestCase):
    def test_six_authoritative_probes_pass_without_extra_requests(self):
        calls = []

        def transport(url, timeout):
            calls.append(url)
            return RssTransportResponse(
                b"<rss><channel><item><title>t</title><link>https://example.test/a</link></item></channel></rss>"
            )

        registry = RegionRegistry.from_file()
        expected = SearchPlanner(registry).plan(RegionMode.SELECTED)
        result = GoogleNewsHealthCheck(registry, GoogleNewsRssProvider(transport)).run()
        self.assertEqual(result.plan_item_count, len(expected.items))
        self.assertEqual(result.probe_ordinals, HEALTH_PROBE_ORDINALS)
        self.assertEqual(result.success_count, 6)
        self.assertEqual(result.status, "PASS")
        self.assertEqual(len(calls), 6)

    def test_one_probe_failure_fails_without_retry(self):
        calls = []

        def transport(url, timeout):
            calls.append(url)
            status = 503 if len(calls) == 3 else 200
            body = b"" if status != 200 else b"<rss><channel></channel></rss>"
            return RssTransportResponse(body, status_code=status)

        result = GoogleNewsHealthCheck(
            RegionRegistry.from_file(), GoogleNewsRssProvider(transport)
        ).run()
        self.assertEqual(result.status, "FAIL")
        self.assertEqual(result.failure_count, 1)
        self.assertEqual(len(calls), 6)


class ShellIntegrationTests(unittest.TestCase):
    def test_cli_uses_runner_and_returns_success_code(self):
        import main

        artifact = FinalReportArtifact("report", "artifact", "v1", (), (), "ok")
        fake_result = SimpleNamespace(
            successful=True,
            summary=lambda: "status=SUCCESS",
        )

        class FakeRunner:
            @classmethod
            def from_environment(cls):
                return cls()

            def run(self, **kwargs):
                self.kwargs = kwargs
                return fake_result

        with patch.object(main, "ProductionRunner", FakeRunner):
            self.assertEqual(main.main(["--period-start", "2026-10-01", "--period-end", "2026-10-07"]), 0)

    def test_streamlit_and_workflow_are_thin_shared_shells(self):
        source = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        workflow = (ROOT / ".github" / "workflows" / "weekly-report.yml").read_text(encoding="utf-8")
        self.assertIn("ProductionRunner", source)
        self.assertNotIn("ReportApplication(", source)
        self.assertIn("python main.py", workflow)
        self.assertNotIn("ReportApplication", workflow)
        self.assertIn("workflow_dispatch:", workflow)


if __name__ == "__main__":
    unittest.main()
