"""Offline cancellation, authority and safe-output acceptance for execution trace."""

from datetime import date
import io
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.weekly_report.contracts import EvidenceResult, EvidenceState, RejectReason
from src.weekly_report.contracts import CandidateNormalizationFailure
from src.weekly_report.candidate_normalizer import CandidateNormalizer, CandidateNormalizationError
from src.weekly_report.debug_service import (
    CHECKPOINT_ITEMS, STAGES, ExecutionTrace, execution_trace, observe_stage,
)
from src.weekly_report.production_runner import ProductionRunner
from src.weekly_report.report_service import ReportService
from src.weekly_report.writer import ReportWriter
from src.weekly_report.validator import Validator
from src.weekly_report.delivery import DeliveryService
from src.weekly_report.scope_classifier import ScopeClassifier

import test_report_application as application_fixtures
from test_report_application import (
    TwoFormalResultProvider, FormalEvidenceService,
    RecordingScopeClassifier, RecordingTemporalRule, RecordingEventIdentity,
    RecordingClassifier, RecordingDownstreamWorkflow, RecordingOrdering,
    FakeProvider, _semantic_provider,
    FailOnSecondEvidenceService,
)


ROOT = Path(__file__).resolve().parents[1]


def rejected(index=0, **provenance):
    return EvidenceResult(
        f"candidate-{index}", EvidenceState.REJECTED,
        reject_reason=RejectReason.CONTENT_UNAVAILABLE,
        provenance={"evidence_rejection_gate": "FETCH_TRANSPORT", "status_code": 503, **provenance},
    )


def records(lines):
    return [json.loads(line) for line in lines]


def test_checkpoints_are_partial_counts_and_final_zero_is_distinct_from_not_reached():
    lines = []
    ticks = iter(range(1000))
    trace = ExecutionTrace(sink=lines.append, clock=lambda: next(ticks), environ={
        "GITHUB_RUN_ID": "38828809650", "GITHUB_RUN_ATTEMPT": "1",
    })
    with execution_trace(trace):
        with observe_stage("Evidence", 201) as stage:
            values = []
            for index in range(201):
                values.append(rejected(index))
                stage.observe(values)
            stage.observe(values, final=True)
        with observe_stage("Scope", 0) as stage:
            stage.observe((), final=True)
    output = records(lines)
    progress = [row for row in output if row["event"] == "STAGE_PROGRESS"]
    assert [row["completed_count"] for row in progress] == [1, 100, 200]
    assert all(row["status"] == "PARTIAL" for row in progress)
    assert progress[-1]["unfinished_count"] == 1
    assert progress[-1]["terminal_distribution"]["EVIDENCE_REJECTED"] == 200
    completed = [row for row in output if row["event"] == "STAGE_COMPLETED"]
    assert [(row["stage"], row["completed_count"], row["output_count"]) for row in completed] == [
        ("Evidence", 201, 0), ("Scope", 0, 0),
    ]
    assert output[-1]["stage_statuses"]["Temporal"] == "NOT_REACHED"
    assert output[-1]["stage_statuses"]["Scope"] == "COMPLETED"
    assert [row["sequence"] for row in output] == list(range(1, len(output) + 1))
    assert len({row["run_id"] for row in output}) == 1
    assert all(row["github_run_id"] == "38828809650" for row in output)
    assert completed[0]["elapsed_ms"] > 0
    assert CHECKPOINT_ITEMS == 100


def test_stdout_sink_flushes_every_snapshot_and_local_identity_needs_no_github():
    class Stream(io.StringIO):
        flush_count = 0

        def flush(self):
            self.flush_count += 1
            super().flush()

    stream = Stream()
    with patch.object(sys, "stdout", stream):
        with execution_trace(ExecutionTrace(environ={"GITHUB_RUN_ID": "API_KEY_SECRET"})):
            with observe_stage("Evidence", 0) as stage:
                stage.observe((), final=True)
    output = records(stream.getvalue().splitlines())
    assert stream.flush_count == len(output)
    assert all(row["github_run_id"] is None for row in output)
    assert "API_KEY_SECRET" not in stream.getvalue()


def test_catchable_exception_retains_prior_stages_and_exact_completed_population():
    lines = []
    with pytest.raises(RuntimeError, match="exception secret"):
        with execution_trace(ExecutionTrace(sink=lines.append)):
            with observe_stage("Acquisition", 1) as stage:
                stage.observe((object(),), final=True)
            with observe_stage("Evidence", 200) as stage:
                values = []
                for index in range(23):
                    values.append(rejected(index))
                    stage.observe(values)
                raise RuntimeError("exception secret https://private.test/?api_key=secret")
    output = records(lines)
    failure = next(row for row in output if row["event"] == "STAGE_FAILED")
    assert failure["stage"] == "Evidence"
    assert failure["completed_count"] == 23
    assert failure["unfinished_count"] == 177
    assert failure["technical_distribution"]["RuntimeError"] == 1
    assert failure["technical_distribution"]["HTTP_STATUS:503"] == 23
    assert failure["reason_distribution"] == {"CONTENT_UNAVAILABLE": 23}
    assert failure["stage_statuses"]["Acquisition"] == "COMPLETED"
    assert failure["stage_statuses"]["Evidence"] == "FAILED"
    assert output[-1]["stage_statuses"]["Scope"] == "NOT_REACHED"
    assert output[-1]["event"] == "EXECUTION_FAILED"
    assert "exception secret" not in "".join(lines)
    assert "private.test" not in "".join(lines)


def test_trace_never_projects_raw_evidence_or_provider_fields():
    secrets = [
        "ARTICLE_BODY_SECRET", "CANDIDATE_TITLE_SECRET", "SEARCH_QUERY_SECRET",
        "API_KEY_SECRET", "MAIAGENT_RAW_SECRET", "PROVIDER_PAYLOAD_SECRET",
        "https://secret.example/private?token=secret",
    ]
    values = [
        EvidenceResult("candidate-ready", EvidenceState.READY,
                       substantive_content=secrets[0], provenance={
                           "title": secrets[1], "query": secrets[2], "api_key": secrets[3],
                           "raw_relation": secrets[4], "raw_provider_payload": secrets[5],
                           "candidate_url": secrets[6], "resolved_url": secrets[6],
                           "metadata_extraction_status": secrets[3],
                       }),
        rejected(transport_error=secrets[3], page_kind=secrets[0]),
    ]
    lines = []
    with execution_trace(ExecutionTrace(sink=lines.append)):
        with observe_stage("Evidence", 2) as stage:
            stage.observe(values, final=True)
    text = "".join(lines)
    assert all(secret not in text for secret in secrets)
    assert "https://" not in text
    completed = next(row for row in records(lines) if row["event"] == "STAGE_COMPLETED")
    assert completed["terminal_distribution"] == {"EVIDENCE_READY": 1, "EVIDENCE_REJECTED": 1}
    assert completed["reason_distribution"] == {"CONTENT_UNAVAILABLE": 1}
    assert completed["technical_distribution"]["HTTP_STATUS:503"] == 1


def test_failed_sink_is_disabled_without_retries_or_fabricated_completion():
    lines = []
    calls = []

    def sink(line):
        calls.append(line)
        if json.loads(line)["event"] == "STAGE_COMPLETED":
            raise OSError("sink secret")
        lines.append(line)

    trace = ExecutionTrace(sink=sink)
    with execution_trace(trace):
        with observe_stage("Evidence", 1) as stage:
            stage.observe([rejected()], final=True)
        with observe_stage("Scope", 0) as stage:
            stage.observe((), final=True)
    assert len(calls) == 3  # start, stage start, failed emission; no alternate sink/retry
    assert all(row["event"] != "STAGE_COMPLETED" for row in records(lines))
    assert trace._statuses["Evidence"] == "STARTED"


def test_search_progress_is_emitted_before_next_provider_call():
    lines = []
    seen = []

    class Provider(FakeProvider):
        def execute(self, item):
            if self.calls:
                seen.extend(row for row in records(lines) if row["stage"] == "Search" and row["event"] == "STAGE_PROGRESS")
            return super().execute(item)

    provider = Provider()
    app = application_fixtures.ReportApplicationTests()._app(provider)
    with execution_trace(ExecutionTrace(sink=lines.append)):
        result = app.run("selected")
    assert provider.calls == [item.plan_item_id for item in result.plan.items]
    assert seen[0]["completed_count"] == 1
    assert seen[0]["input_count"] == 2


def _full_app():
    calls = []

    def writer(request):
        calls.append(request)
        return {
            "event_id": request["writer_request"]["event_id"],
            "headline": "事件標題", "factual_summary": "事件摘要 Taiwan Metro",
            "taipei_insight": "可供臺北捷運評估相關規劃方向",
        }

    app = application_fixtures.ReportApplicationTests()._app(
        TwoFormalResultProvider(), evidence_service=FormalEvidenceService(),
        scope_classifier=RecordingScopeClassifier(),
        temporal_rule=RecordingTemporalRule(default_date=date(2026, 9, 18)),
        event_identity=RecordingEventIdentity(), classifier=RecordingClassifier(),
        report_workflow=RecordingDownstreamWorkflow(reportable=True),
        ordering=RecordingOrdering(), report_service=ReportService(),
        writer=ReportWriter(provider=writer), validator=Validator(semantic_provider=_semantic_provider),
        delivery=DeliveryService(live_email_send=False), delivery_recipient="staging@example.test",
    )
    return app, calls


def _call_population(app, writer_calls):
    return {
        "Search": len(next(iter(app.executor.dispatch.values())).calls),
        "Evidence": len(app.evidence_service.calls), "Scope": len(app.scope_classifier.calls),
        "Temporal": len(app.temporal_rule.calls), "EventIdentity": len(app.event_identity.calls),
        "Category": len(app.classifier.calls), "Taxonomy": len(app.report_workflow.taxonomy.calls),
        "Reportability": len(app.report_workflow.reportability.calls),
        "Ordering": len(app.ordering.calls), "Writer": len(writer_calls),
        "Validator": app.validator.semantic_call_count, "Delivery": len(app.delivery.attempts),
    }


@pytest.mark.parametrize("observer", ["healthy", "broken_sink", "late_broken_sink", "broken_projection"])
def test_trace_and_observer_failures_preserve_all_domain_results_calls_order_and_artifact(observer):
    plain_app, plain_calls = _full_app()
    expected = plain_app.run("selected")
    app, writer_calls = _full_app()
    lines = []

    def broken_sink(line):
        raise OSError("sink secret")

    def late_broken_sink(line):
        row = json.loads(line)
        if row["stage"] == "Evidence" and row["event"] == "STAGE_PROGRESS":
            raise OSError("late sink secret")
        lines.append(line)

    sink = {"broken_sink": broken_sink, "late_broken_sink": late_broken_sink}.get(observer, lines.append)
    trace = ExecutionTrace(sink=sink)
    with execution_trace(trace):
        if observer == "broken_projection":
            with patch("src.weekly_report.debug_service._facts", side_effect=RuntimeError("projection secret")):
                actual = app.run("selected")
        else:
            actual = app.run("selected")
    assert actual == expected
    assert _call_population(app, writer_calls) == _call_population(plain_app, plain_calls)
    assert tuple(item.event_group.event_id for item in actual.ordered_results) == tuple(
        item.event_group.event_id for item in expected.ordered_results
    )
    assert actual.final_report == expected.final_report
    if observer == "healthy":
        completed = [row for row in records(lines) if row["event"] == "STAGE_COMPLETED"]
        assert {row["stage"] for row in completed} == set(STAGES)
        assert records(lines)[-1]["stage_statuses"] == dict.fromkeys(STAGES, "COMPLETED")


def test_runner_uses_one_invocation_trace_and_same_evidence_projection_as_final_summary():
    app, _ = _full_app()
    lines = []
    with execution_trace(ExecutionTrace(sink=lines.append)):
        result = ProductionRunner(app).run(period_start="2026-09-12", period_end="2026-09-18")
    output = records(lines)
    evidence = next(row for row in output if row["stage"] == "Evidence" and row["event"] == "STAGE_COMPLETED")
    assert evidence["output_count"] == result.evidence_ready_count
    assert evidence["terminal_distribution"]["EVIDENCE_REJECTED"] == result.evidence_rejected_count
    assert sum(row["event"] == "EXECUTION_STARTED" for row in output) == 1
    assert len({row["run_id"] for row in output}) == 1
    assert output[-1]["report_id"] == result.final_report.report_id
    assert result.successful


def test_zero_population_trace_preserves_default_scope_behavior_and_zero_writer_calls():
    app, writer_calls = _full_app()
    app._scope_classifier = ScopeClassifier()
    lines = []
    with execution_trace(ExecutionTrace(sink=lines.append)):
        result = app.run("selected")
    output = records(lines)
    scope = next(row for row in output if row["stage"] == "Scope" and row["event"] == "STAGE_COMPLETED")
    assert scope["input_count"] == 2
    assert scope["output_count"] == 0
    assert scope["reason_distribution"] == {"SCOPE_NOT_ESTABLISHED": 2}
    assert result.final_report.event_count == 0
    assert writer_calls == []
    assert app.validator.semantic_call_count == 0
    assert output[-1]["stage_statuses"] == dict.fromkeys(STAGES, "COMPLETED")


@pytest.mark.parametrize("configuration_failure", [False, True])
def test_cli_trace_starts_before_composition_and_uses_one_identity(capsys, configuration_failure):
    import main

    class Runner:
        @classmethod
        def from_environment(cls):
            initial = records(capsys.readouterr().out.splitlines())
            assert initial[0]["event"] == "EXECUTION_STARTED"
            assert initial[0]["run_id"]
            cls.run_id = initial[0]["run_id"]
            if configuration_failure:
                raise RuntimeError("configuration secret")
            return cls()

        def run(self, **kwargs):
            return SimpleNamespace(successful=True, summary=lambda: "status=SUCCESS")

    with patch.object(main, "ProductionRunner", Runner):
        code = main.main([])
    text = capsys.readouterr().out
    output = records(line for line in text.splitlines() if line.startswith("{"))
    assert code == int(configuration_failure)
    assert output[-1]["run_id"] == Runner.run_id
    assert output[-1]["event"] == ("EXECUTION_FAILED" if configuration_failure else "EXECUTION_COMPLETED")
    assert "configuration secret" not in text


def test_application_exception_keeps_search_and_normalization_and_reports_failed_evidence():
    service = FailOnSecondEvidenceService(RuntimeError("unlogged provider secret"))
    app = application_fixtures.ReportApplicationTests()._app(
        TwoFormalResultProvider(), evidence_service=service,
    )
    lines = []
    with execution_trace(ExecutionTrace(sink=lines.append)):
        result = ProductionRunner(app).run(period_start="2026-09-12", period_end="2026-09-18")
    output = records(lines)
    failure = next(row for row in output if row["event"] == "STAGE_FAILED")
    assert not result.successful
    assert result.failure_stage == "application"  # preserve the existing Runner surface
    assert failure["stage"] == "Evidence"
    assert failure["completed_count"] == 1
    assert failure["input_count"] == 2
    assert failure["stage_statuses"]["Normalization"] == "COMPLETED"
    assert failure["stage_statuses"]["Scope"] == "NOT_REACHED"
    assert "unlogged provider secret" not in "".join(lines)


def test_consumed_normalization_failure_is_failed_not_completed_without_changing_result():
    failure = CandidateNormalizationFailure("INVALID_URL")

    class Normalizer(CandidateNormalizer):
        def normalize(self, acquisitions):
            raise CandidateNormalizationError(failure)

    app = application_fixtures.ReportApplicationTests()._app(FakeProvider(), normalizer=Normalizer())
    lines = []
    with execution_trace(ExecutionTrace(sink=lines.append)):
        result = app.run("selected")
    assert result.normalization_failure is failure
    observed = next(row for row in records(lines) if row["event"] == "STAGE_FAILED")
    assert observed["stage"] == "Normalization"
    assert observed["reason_distribution"] == {"INVALID_URL": 1}
    assert not any(row["stage"] == "Normalization" and row["event"] == "STAGE_COMPLETED" for row in records(lines))


@pytest.mark.parametrize("stage_name", ["Taxonomy", "Reportability"])
def test_internal_workflow_failure_is_attributed_without_fabricated_later_completion(stage_name):
    app, _ = _full_app()
    owner = app.report_workflow.taxonomy if stage_name == "Taxonomy" else app.report_workflow.reportability
    owner.fail_on_call = 2
    lines = []
    with execution_trace(ExecutionTrace(sink=lines.append)):
        result = ProductionRunner(app).run(period_start="2026-09-12", period_end="2026-09-18")
    assert not result.successful
    output = records(lines)
    failure = next(row for row in output if row["event"] == "STAGE_FAILED")
    assert failure["stage"] == stage_name
    assert failure["completed_count"] == 1
    assert failure["stage_statuses"]["Ordering"] == "NOT_REACHED"
    assert len(owner.calls) == 2


def test_hard_kill_keeps_flushed_2300_of_4794_checkpoint_without_finally_or_completion():
    child = r'''
import sys
from src.weekly_report.debug_service import execution_trace, observe_stage
from src.weekly_report.contracts import EvidenceResult, EvidenceState, RejectReason
with execution_trace():
    with observe_stage("Acquisition", 1) as stage:
        stage.observe((object(),), final=True)
    with observe_stage("Evidence", 4794) as stage:
        values = []
        for index in range(2300):
            values.append(EvidenceResult(str(index), EvidenceState.REJECTED,
                reject_reason=RejectReason.CONTENT_UNAVAILABLE))
            stage.observe(values)
        sys.stdin.read(1)  # parent kills us here, before any final return/finally
        stage.observe(values, final=True)
'''
    process = subprocess.Popen(
        [sys.executable, "-B", "-c", child], cwd=ROOT,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8",
    )
    received = queue.Queue()
    captured = []

    def read_stdout():
        for line in process.stdout:
            captured.append(line)
            received.put(json.loads(line))
        received.put(None)

    reader = threading.Thread(target=read_stdout, daemon=True)
    reader.start()
    try:
        while True:
            checkpoint = received.get(timeout=15)
            assert checkpoint is not None, process.stderr.read()
            if checkpoint["stage"] == "Evidence" and checkpoint["completed_count"] == 2300:
                break
        process.kill()
        process.wait(timeout=5)
        reader.join(timeout=5)
        assert not reader.is_alive()
        assert checkpoint["status"] == "PARTIAL"
        assert checkpoint["input_count"] == 4794
        assert checkpoint["unfinished_count"] == 2494
        assert checkpoint["terminal_distribution"]["EVIDENCE_REJECTED"] == 2300
        assert checkpoint["stage_statuses"]["Acquisition"] == "COMPLETED"
        output = records(captured)
        assert not any(row["stage"] == "Evidence" and row["event"] == "STAGE_COMPLETED" for row in output)
        assert not any(row["event"].startswith("EXECUTION_COMPLETED") for row in output)
        assert output[-1]["stage_statuses"]["Evidence"] == "PARTIAL"
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        reader.join(timeout=5)
        process.stdin.close()
        process.stdout.close()
        process.stderr.close()
