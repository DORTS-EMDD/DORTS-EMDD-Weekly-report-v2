"""Observational execution snapshots; never an input to production decisions.

Only flushed records are retained as checkpoints. There is no replay, record
cache, background worker, or observer retry. An unavailable sink is disabled
for that invocation without changing the domain execution.
Counts describe owner results received at that checkpoint, not unobserved
in-flight work. Missing completion records never imply completion.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from enum import Enum
import json
import os
import re
from time import monotonic
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from .contracts import EvidenceResult, EvidenceState, RejectReason, SearchExecutionResult
from .event_identity import SECOND_NOMINATION_SUFFIX, proposal_subject_level


STAGES = (
    "Search", "Acquisition", "Normalization", "Evidence", "Scope", "Temporal",
    "EventIdentity", "Category", "Taxonomy", "Reportability", "Ordering",
    "FormalMetadata", "Writer", "Validator", "Assembly", "Delivery",
)
CHECKPOINT_ITEMS = 100
_ACTIVE: ContextVar[ExecutionTrace | None] = ContextVar("execution_trace", default=None)
_STAGE: ContextVar[StageObservation | None] = ContextVar("execution_stage", default=None)


def _stdout(line: str) -> None:
    print(line, flush=True)


def _enum(value: object) -> str | None:
    # Only repository-owned finite vocabularies, never arbitrary str/Enum input.
    if not isinstance(value, Enum):
        return None
    module = type(value).__module__
    if module not in {
        f"{__package__}.contracts", f"{__package__}.validator",
        f"{__package__}.report_service", f"{__package__}.delivery",
    }:
        return None
    return str(value.value)


def _counts(values) -> dict[str, int]:
    return dict(sorted(Counter(value for value in values if value is not None).items()))


def _facts(stage: str, values: Any, input_count: int | None) -> dict[str, Any]:
    """Mechanical projections of completed owner results, with finite keys."""
    terminal: dict[str, int] = {}
    reasons: dict[str, int] = {}
    technical: dict[str, int] = {}
    partial = False
    if stage == "Search":
        execution = values if isinstance(values, SearchExecutionResult) else None
        attempts = execution.attempt_results if execution is not None else values
        completed = len(attempts)
        output = sum(len(item.results) for item in attempts)
        terminal = _counts(_enum(item.status) for item in attempts)
        technical = _counts(_enum(item.technical_failure_class) for item in attempts)
        if execution is not None:
            partial = not execution.execution_complete
            if execution.infrastructure_failure is not None:
                reason = _enum(execution.infrastructure_failure.failure_class)
                if reason is not None:
                    technical[reason] = technical.get(reason, 0) + 1
    elif stage == "Normalization":
        completed, output = input_count, len(values.normalized_candidates)
    elif stage == "Evidence":
        projection = evidence_projection(tuple(values))
        completed = len(values)
        output = projection["evidence_ready_count"]
        terminal = {"EVIDENCE_READY": output, "EVIDENCE_REJECTED": projection["evidence_rejected_count"]}
        vocabulary = {reason.value for reason in RejectReason}
        for key, count in projection["evidence_reject_reason_distribution"].items():
            safe_key = key if key in vocabulary else "UNKNOWN"
            reasons[safe_key] = reasons.get(safe_key, 0) + count
        # Reuse the existing projection, exposing only closed technical vocabularies.
        allowed = {
            "evidence_rejection_gate_distribution": set(_EVIDENCE_GATE_ORDER),
            "evidence_semantic_response_validation_distribution": {
                "valid", "invalid", "timeout", "transport_error", "not_configured",
                "not_attempted", "NOT_REACHED",
            },
            "evidence_metadata_extraction_status_distribution": {
                "not_configured", "timeout", "transport_error", "invalid_response",
                "valid_zero_metadata", "valid_metadata", "NOT_REACHED",
            },
            "evidence_acquisition_path_distribution": _ACQUISITION_PATHS,
            "evidence_acquisition_final_endpoint_distribution": _ACQUISITION_FINAL_ENDPOINTS,
            "evidence_acquisition_redirect_consistency_distribution": _ACQUISITION_REDIRECT_STATES,
            "evidence_source_provenance_mismatch_distribution": _SOURCE_PROVENANCE_FAILURES,
            "evidence_acquisition_latency_bucket_distribution": _LATENCY_BUCKETS,
            "evidence_redirect_hop_count_distribution": {
                *(str(index) for index in range(21)), "20+", "UNKNOWN",
            },
            "evidence_host_transition_distribution": {
                "SAME_HOST", "CHANGED_HOST", "RESOLVED_HOST_MISSING",
            },
        }
        for field, vocabulary in allowed.items():
            for key, count in projection[field].items():
                safe_key = key if key in vocabulary else "UNKNOWN"
                token = field + ":" + safe_key
                technical[token] = technical.get(token, 0) + count
        for field in (
            "evidence_acquisition_initial_hostname_distribution",
            "evidence_acquisition_failing_endpoint_hostname_distribution",
        ):
            for key, count in projection[field].items():
                safe_key = _safe_diag_token(key) or "UNKNOWN"
                token = field + ":" + safe_key
                technical[token] = technical.get(token, 0) + count
        for key, count in projection["evidence_http_status_distribution"].items():
            if key.isascii() and key.isdigit() and 100 <= int(key) <= 599:
                technical["HTTP_STATUS:" + key] = count
    elif stage == "Scope":
        completed = len(values)
        terminal = _counts(_enum(item.state) for item in values)
        reasons = _counts(_enum(item.diagnostic) for item in values)
        output = terminal.get("IN_SCOPE", 0)
    elif stage == "Temporal":
        completed = len(values)
        terminal = _counts("DATE_VALID" if item.date_valid else "DATE_INVALID" for item in values)
        reasons = _counts(_enum(item.diagnostic) for item in values)
        output = terminal.get("DATE_VALID", 0)
    elif stage == "EventIdentity":
        completed, output = input_count, len(values.groups)
        terminal = _counts("MERGED" if len(group.member_candidate_ids) > 1 else "UNMERGED" for group in values.groups)
        projection = event_identity_projection(values)
        reasons = projection["event_identity_diagnostic_distribution"]
        technical = projection["event_identity_gap_distribution"]
    elif stage == "Category":
        completed = len(values)
        terminal = _counts(_enum(item.category_state) for item in values)
        reasons = _counts(_enum(item.category_resolution_reason) for item in values)
        output = terminal.get("CATEGORY_ASSIGNED", 0)
    elif stage == "Taxonomy":
        completed = len(values)
        terminal = _counts(_enum(item.taxonomy_result.taxonomy_state) for item in values)
        reasons = _counts(_enum(item.taxonomy_result.taxonomy_resolution_reason) for item in values)
        output = terminal.get("TAXONOMY_EVALUATED", 0)
    elif stage == "Reportability":
        completed = len(values)
        terminal = _counts(
            "NOT_EVALUATED" if item.reportability_result is None
            else _enum(item.reportability_result.reportability_state) for item in values
        )
        reasons = _counts(
            _enum(item.reportability_result.reportability_reason)
            for item in values if item.reportability_result is not None
        )
        output = terminal.get("REPORTABLE", 0)
    elif stage == "Validator":
        completed = len(values.passed) + len(values.failed)
        output = values.pass_count
        terminal = {"PASS": output, "FAIL": len(values.failed)}
        allowed = {"language_" + field for field in ("headline", "factual_summary", "taipei_insight")}
        allowed.update(
            "semantic_" + field + "_" + assessment
            for field in ("headline", "factual_summary", "taipei_insight")
            for assessment in ("unsupported", "uncertain")
        )
        reasons = _counts(reason if reason in allowed else "UNKNOWN" for item in values.failed for reason in item.reasons)
    elif stage == "Assembly":
        completed, output = input_count, values.event_count
    elif stage == "Delivery":
        completed, output = 1, 1
        terminal = _counts((_enum(values.status),))
    else:
        completed = input_count if stage == "Acquisition" else len(values)
        output = len(values)
    return dict(completed_count=completed, output_count=output,
                terminal_distribution=terminal, reason_distribution=reasons,
                technical_distribution=technical, partial=partial)


class ExecutionTrace:
    """One execution's safe observation channel, isolated by execution context."""

    def __init__(self, *, sink: Callable[[str], None] | None = None,
                 clock: Callable[[], float] = monotonic,
                 environ: Mapping[str, str] | None = None) -> None:
        self.run_id = uuid4().hex
        self.report_id: str | None = None
        self._sink = sink if sink is not None else _stdout
        self._clock = clock
        self._started = clock()
        self._sequence = 0
        self._enabled = True
        self._outcome = "COMPLETED"
        self._statuses = dict.fromkeys(STAGES, "NOT_REACHED")
        values = os.environ if environ is None else environ
        self._github = {
            key: value if isinstance(value, str) and re.fullmatch(r"[0-9]{1,24}", value) else None
            for key, value in (("github_run_id", values.get("GITHUB_RUN_ID")),
                               ("github_run_attempt", values.get("GITHUB_RUN_ATTEMPT")))
        }

    def outcome(self, successful: bool, report_id: str | None = None, *, partial: bool = False) -> None:
        """COMPLETED, PARTIAL (artifact with disclosed technical gaps), or FAILED."""

        self._outcome = ("PARTIAL" if partial else "COMPLETED") if successful else "FAILED"
        self.bind_report_id(report_id)

    def bind_report_id(self, report_id: str | None) -> None:
        if isinstance(report_id, str) and re.fullmatch(r"weekly-report-[0-9a-f]{16}", report_id):
            self.report_id = report_id

    def emit(self, event: str, stage: str, status: str, *, started: float,
             input_count: int | None = None, completed_count: int | None = 0,
             output_count: int | None = None, terminal_distribution=None,
             reason_distribution=None, technical_distribution=None) -> None:
        if not self._enabled:
            return
        try:
            if stage not in (*STAGES, "Execution") or status not in {
                "NOT_REACHED", "STARTED", "RUNNING", "PARTIAL", "COMPLETED", "FAILED",
            } or event not in {
                "STAGE_STARTED", "STAGE_PROGRESS", "STAGE_COMPLETED", "STAGE_FAILED",
                "EXECUTION_STARTED", "EXECUTION_COMPLETED", "EXECUTION_PARTIAL", "EXECUTION_FAILED",
            }:
                self._enabled = False
                return
            statuses = dict(self._statuses)
            if stage in statuses:
                statuses[stage] = status
            record = {
                "trace_type": "execution_snapshot_v1", "event": event,
                "run_id": self.run_id, "report_id": self.report_id,
                **self._github, "sequence": self._sequence + 1,
                "stage": stage, "status": status, "stage_statuses": statuses,
                "input_count": input_count, "completed_count": completed_count,
                "output_count": output_count,
                "unfinished_count": None if input_count is None or completed_count is None else max(0, input_count - completed_count),
                "elapsed_ms": max(0, int((self._clock() - started) * 1000)),
                "terminal_distribution": dict(sorted((terminal_distribution or {}).items())),
                "reason_distribution": dict(sorted((reason_distribution or {}).items())),
                "technical_distribution": dict(sorted((technical_distribution or {}).items())),
            }
            self._sink(json.dumps(record, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
            # Never advertise a COMPLETED checkpoint that the sink did not accept.
            self._sequence += 1
            self._statuses = statuses
        except Exception:
            # Debug has no continuation authority. No retry or alternate sink.
            self._enabled = False


class StageObservation:
    def __init__(self, trace: ExecutionTrace | None, stage: str, input_count: int | None) -> None:
        self._trace, self.stage, self.input_count = trace, stage, input_count
        self.started = trace._clock() if trace is not None else 0.0
        self.facts: dict[str, Any] = {"completed_count": 0, "output_count": None}
        self._closed = False
        self._pending = None
        if trace is not None:
            trace.emit("STAGE_STARTED", stage, "STARTED", started=self.started, input_count=input_count)

    def observe(self, values: Any, *, final: bool = False) -> None:
        if self._trace is None or not self._trace._enabled:
            return
        try:
            self._pending = values
            count = len(values) if isinstance(values, (list, tuple)) else None
            if not final and count != 1 and (count is None or count % CHECKPOINT_ITEMS):
                return
            self.facts = _facts(self.stage, values, self.input_count)
            if final and self.stage == "Assembly":
                self._trace.bind_report_id(values.report_id)
            if not final:
                self._emit("STAGE_PROGRESS", "PARTIAL")
        except Exception:
            self._trace._enabled = False

    def _emit(self, event: str, status: str) -> None:
        if self._trace is not None:
            facts = {key: value for key, value in self.facts.items() if key != "partial"}
            self._trace.emit(event, self.stage, status, started=self.started,
                             input_count=self.input_count, **facts)

    def fail(self, exc: BaseException) -> None:
        if self._closed:
            return
        self._closed = True
        if self._trace is not None and self._pending is not None:
            try:
                self.facts = _facts(self.stage, self._pending, self.input_count)
            except Exception:
                self._trace._enabled = False
        self._pending = None
        classes = {
            "TypeError", "ValueError", "RuntimeError", "TimeoutError", "OSError",
            "CandidateNormalizationError", "TaxonomyStageFailure", "ReportabilityStageFailure",
            "ValidationStageFailure", "ValidationPopulationError", "FormalMetadataFailure",
            "WriterFailure", "WriterProviderFailure", "WriterResponseError", "WriterPopulationError",
            "KeyboardInterrupt", "SystemExit",
        }
        name = type(exc).__name__
        technical = dict(self.facts.get("technical_distribution", {}))
        failure_class = name if name in classes else "UNEXPECTED_EXCEPTION"
        technical[failure_class] = technical.get(failure_class, 0) + 1
        self.facts["technical_distribution"] = technical
        try:
            reason = _enum(getattr(exc, "reason", None)) or _enum(getattr(exc, "failure_class", None))
        except Exception:
            reason = None
        reasons = dict(self.facts.get("reason_distribution", {}))
        if reason is not None:
            reasons[reason] = reasons.get(reason, 0) + 1
        self.facts["reason_distribution"] = reasons
        self._emit("STAGE_FAILED", "FAILED")

    def finish(self) -> None:
        self._pending = None
        if not self._closed:
            self._closed = True
            partial = self.facts.get("partial", False)
            self._emit("STAGE_FAILED" if partial else "STAGE_COMPLETED", "PARTIAL" if partial else "COMPLETED")


@contextmanager
def observe_stage(stage: str, input_count: int | None = None):
    observation = StageObservation(_ACTIVE.get(), stage, input_count)
    token = _STAGE.set(observation)
    try:
        yield observation
    except BaseException as exc:
        observation.fail(exc)
        raise
    else:
        observation.finish()
    finally:
        _STAGE.reset(token)


def observe_progress(stage: str, values: Any) -> None:
    observation = _STAGE.get()
    if observation is not None and observation.stage == stage:
        observation.observe(values)


@contextmanager
def execution_trace(trace: ExecutionTrace | None = None):
    """CLI and Runner nest on the same invocation; direct lower seams stay quiet."""
    active = _ACTIVE.get()
    if active is not None:
        yield active
        return
    trace = trace if trace is not None else ExecutionTrace()
    token = _ACTIVE.set(trace)
    trace.emit("EXECUTION_STARTED", "Execution", "STARTED", started=trace._started)
    try:
        yield trace
    except BaseException:
        trace.outcome(False)
        raise
    finally:
        trace.emit("EXECUTION_" + trace._outcome, "Execution", trace._outcome, started=trace._started)
        _ACTIVE.reset(token)


_EVIDENCE_GATE_ORDER = {
    "URL_VALIDATION": 1,
    "LINK_RESOLUTION": 2,
    "FETCH_TRANSPORT": 3,
    "HTTP_STATUS": 4,
    "CONTENT_TYPE": 5,
    "SOURCE_PROVENANCE": 6,
    "PRINCIPAL_DOCUMENT": 7,
    "BODY_AVAILABILITY": 8,
    "FACTUAL_SUBSTANCE": 9,
    "SEMANTIC_MATCH": 10,
}


def _safe_diag_token(value: object, *, allowed: set[str] | None = None) -> str | None:
    if isinstance(value, bool):
        token = "TRUE" if value else "FALSE"
    elif value is None:
        return None
    else:
        token = str(value).strip()
    if not token:
        return None
    if allowed is not None:
        return token if token in allowed else "UNKNOWN"
    if len(token) > 96 or any(
        not (char.isalnum() or char in "._:+/-") for char in token
    ):
        return "OTHER"
    return token


def _safe_host(value: object) -> str | None:
    try:
        host = urlsplit(str(value or "")).hostname or ""
    except ValueError:
        return None
    return _safe_diag_token(host.casefold())


def _add_distribution(
    target: dict[str, int],
    value: str | None,
    *,
    max_distinct: int | None = None,
) -> None:
    if value is None:
        return
    if (
        max_distinct is not None
        and value not in target
        and len(target) >= max_distinct - 1
    ):
        value = "OTHER"
    target[value] = target.get(value, 0) + 1


_ACQUISITION_PATHS = {"DIRECT", "REDIRECTED", "UNKNOWN"}
_ACQUISITION_FINAL_ENDPOINTS = {"OBSERVED", "NOT_OBSERVED", "UNKNOWN"}
_ACQUISITION_REDIRECT_STATES = {
    "CONSISTENT", "MISMATCH", "UNKNOWN", "NOT_APPLICABLE",
}
_SOURCE_PROVENANCE_FAILURES = {
    "INVALID_CANDIDATE_RESOURCE_KEY",
    "INVALID_RESOLVED_RESOURCE_KEY",
    "INVALID_REDIRECT_CHAIN",
    "MISSING_REDIRECT_CHAIN",
    "FIRST_REDIRECT_ENDPOINT_MISMATCH",
    "FINAL_REDIRECT_ENDPOINT_MISMATCH",
    "CANONICAL_RESOURCE_MISMATCH",
}
_LATENCY_BUCKETS = {
    "0-9ms", "10-49ms", "50-99ms", "100-249ms", "250-499ms",
    "500-999ms", "1000-4999ms", "5000-9999ms", "10000ms+",
}
_MAX_HOST_KEYS = 32


def _latency_bucket(value: object) -> str | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    if value < 10:
        return "0-9ms"
    if value < 50:
        return "10-49ms"
    if value < 100:
        return "50-99ms"
    if value < 250:
        return "100-249ms"
    if value < 500:
        return "250-499ms"
    if value < 1000:
        return "500-999ms"
    if value < 5000:
        return "1000-4999ms"
    if value < 10000:
        return "5000-9999ms"
    return "10000ms+"


def _hop_bucket(value: object) -> str | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return str(value) if value <= 20 else "20+"


def _safe_host_value(value: object) -> str | None:
    if isinstance(value, str) and value.upper() in {
        "UNKNOWN", "NOT_APPLICABLE", "NOT_AVAILABLE",
    }:
        return value.upper()
    return _safe_host(value) or _safe_diag_token(value)


def _field_diagnostic(
    provenance: Mapping[str, Any],
    key: str,
    *,
    gate: str,
    reached_after_gate: int,
    allowed: set[str] | None = None,
) -> str | None:
    if key in provenance:
        return _safe_diag_token(provenance.get(key), allowed=allowed)
    if _EVIDENCE_GATE_ORDER.get(gate, 0) < reached_after_gate:
        return "NOT_REACHED"
    return None


_EVENT_IDENTITY_DIAGNOSTICS = frozenset({
    "EXACT_SOURCE_BODY", "INSUFFICIENT_IDENTITY", "PROPOSAL_BATCH_SPLIT", "PROPOSAL_CONFIRMED", "PROPOSAL_MEMBER_REJECTED",
    "PROPOSAL_NOT_CONFIRMED", "PROPOSAL_REGION_CONFLICT", "SINGLE_MEMBER_PROPOSAL", "UPSTREAM_NOT_ELIGIBLE",
})
_UNCONFIRMED_OUTCOMES = {"SEPARATED", "OMITTED", "MEMBER_INVALID", "CONFIRMATION_FAILED"}


def technical_gap_signature(gap: Any) -> str:
    """Stage, subject level, kind and failure class of one TechnicalGap, as safe tokens."""

    level = proposal_subject_level(gap.subject_id) if gap.stage == "EventIdentity" else "SUBJECT"
    return ":".join((gap.stage, level, str(gap.kind.value), _safe_diag_token(gap.failure_class) or "UNKNOWN"))


def event_identity_projection(run: Any) -> dict[str, dict[str, int]]:
    """Project the EventIdentityRun already produced: its diagnostics and technical gaps."""

    return {
        "event_identity_diagnostic_distribution": _counts(
            item.reason if item.reason in _EVENT_IDENTITY_DIAGNOSTICS else "UNKNOWN" for item in run.diagnostics
        ),
        "event_identity_gap_distribution": _counts(technical_gap_signature(gap) for gap in run.technical_gaps),
        # RC-31: why each proposed pair stayed apart (the confirmation separated
        # it, left a member out, rejected a member, or failed as a whole).
        "event_identity_unconfirmed_distribution": _counts(
            _safe_diag_token(item.detail.rsplit("|", 1)[-1], allowed=_UNCONFIRMED_OUTCOMES)
            for item in run.diagnostics
            if item.reason == "PROPOSAL_NOT_CONFIRMED"
        ),
        # Section A.33: confirmed pairs by the nomination that proposed them.
        "event_identity_confirmed_pairs": _nomination_pairs(run.diagnostics),
    }


def _nomination_pairs(diagnostics: Any) -> dict[str, int]:
    pairs: dict[str, int] = {}
    for item in diagnostics:
        if item.reason != "PROPOSAL_CONFIRMED":
            continue
        subject, _, count = item.detail.rpartition("|pairs=")
        nomination = "SECOND" if subject.split(":", 1)[0].endswith(SECOND_NOMINATION_SUFFIX) else "FIRST"
        pairs[nomination] = pairs.get(nomination, 0) + int(count)
    return dict(sorted(pairs.items()))


def evidence_projection(evidence_results: tuple[EvidenceResult, ...] | None) -> dict[str, Any]:
    """Project safe counts from the EvidenceResult objects already produced."""

    if evidence_results is None:
        return {}

    distributions: dict[str, dict[str, int]] = {
        "evidence_reject_reason_distribution": {},
        "evidence_rejection_gate_distribution": {},
        "evidence_reason_gate_distribution": {},
        "evidence_http_status_distribution": {},
        "evidence_transport_error_distribution": {},
        "evidence_content_type_distribution": {},
        "evidence_principal_document_status_distribution": {},
        "evidence_page_kind_distribution": {},
        "evidence_source_provenance_distribution": {},
        "evidence_canonical_related_distribution": {},
        "evidence_body_available_distribution": {},
        "evidence_factual_substance_distribution": {},
        "evidence_semantic_relation_distribution": {},
        "evidence_semantic_response_validation_distribution": {},
        "evidence_metadata_extraction_status_distribution": {},
        "evidence_candidate_hostname_distribution": {},
        "evidence_resolved_hostname_distribution": {},
        "evidence_redirect_hop_count_distribution": {},
        "evidence_host_transition_distribution": {},
        "evidence_rejection_signature_distribution": {},
        "evidence_acquisition_latency_bucket_distribution": {},
        "evidence_acquisition_path_distribution": {},
        "evidence_acquisition_final_endpoint_distribution": {},
        "evidence_acquisition_redirect_consistency_distribution": {},
        "evidence_acquisition_initial_hostname_distribution": {},
        "evidence_acquisition_failing_endpoint_hostname_distribution": {},
        "evidence_source_provenance_mismatch_distribution": {},
    }
    ready_count = 0
    rejected_count = 0
    semantic_relations = {"SAME_EVENT", "DIFFERENT_EVENT", "UNCERTAIN"}
    semantic_validation = {
        "valid",
        "invalid",
        "timeout",
        "transport_error",
        "not_configured",
        "not_attempted",
    }
    for evidence in evidence_results:
        if not isinstance(evidence, EvidenceResult):
            continue
        provenance = evidence.provenance
        gate = str(provenance.get("evidence_rejection_gate", "UNKNOWN"))
        gate_order = _EVIDENCE_GATE_ORDER.get(gate, 0)
        if evidence.state is EvidenceState.READY:
            ready_count += 1
        else:
            rejected_count += 1
            reason = str(evidence.reject_reason or "UNKNOWN")
            _add_distribution(distributions["evidence_reject_reason_distribution"], reason)
            _add_distribution(distributions["evidence_rejection_gate_distribution"], gate)
            _add_distribution(
                distributions["evidence_reason_gate_distribution"],
                f"{reason}|{gate}",
            )

        http_status = provenance.get("status_code")
        if isinstance(http_status, int) and not isinstance(http_status, bool):
            _add_distribution(distributions["evidence_http_status_distribution"], str(http_status))
        _add_distribution(
            distributions["evidence_transport_error_distribution"],
            _field_diagnostic(provenance, "transport_error", gate=gate, reached_after_gate=2),
        )
        content_type = provenance.get("content_type")
        if isinstance(content_type, str) and content_type:
            _add_distribution(
                distributions["evidence_content_type_distribution"],
                _safe_diag_token(content_type.split(";", 1)[0].casefold()),
            )
        _add_distribution(
            distributions["evidence_principal_document_status_distribution"],
            _field_diagnostic(provenance, "principal_document_status", gate=gate, reached_after_gate=6),
        )
        _add_distribution(
            distributions["evidence_page_kind_distribution"],
            _safe_diag_token(provenance.get("page_kind")),
        )
        _add_distribution(
            distributions["evidence_source_provenance_distribution"],
            _field_diagnostic(provenance, "source_provenance", gate=gate, reached_after_gate=5),
        )
        _add_distribution(
            distributions["evidence_canonical_related_distribution"],
            _field_diagnostic(provenance, "canonical_related", gate=gate, reached_after_gate=5),
        )
        _add_distribution(
            distributions["evidence_body_available_distribution"],
            _field_diagnostic(provenance, "body_text_available", gate=gate, reached_after_gate=6),
        )
        _add_distribution(
            distributions["evidence_factual_substance_distribution"],
            _field_diagnostic(provenance, "factual_substance", gate=gate, reached_after_gate=8),
        )
        _add_distribution(
            distributions["evidence_semantic_relation_distribution"],
            _field_diagnostic(
                provenance,
                "raw_relation",
                gate=gate,
                reached_after_gate=9,
                allowed=semantic_relations,
            ),
        )
        _add_distribution(
            distributions["evidence_semantic_response_validation_distribution"],
            _field_diagnostic(
                provenance,
                "response_validation_result",
                gate=gate,
                reached_after_gate=9,
                allowed=semantic_validation,
            ),
        )
        metadata_status = _safe_diag_token(provenance.get("metadata_extraction_status"))
        if metadata_status is not None:
            _add_distribution(
                distributions["evidence_metadata_extraction_status_distribution"],
                metadata_status,
            )
        elif evidence.state is EvidenceState.REJECTED:
            _add_distribution(
                distributions["evidence_metadata_extraction_status_distribution"],
                "NOT_REACHED",
            )

        candidate_host = _safe_host(provenance.get("candidate_url")) or _safe_diag_token(
            provenance.get("candidate_hostname")
        )
        resolved_host = _safe_host(provenance.get("resolved_url")) or _safe_diag_token(
            provenance.get("resolved_hostname")
        )
        _add_distribution(
            distributions["evidence_candidate_hostname_distribution"],
            candidate_host,
            max_distinct=_MAX_HOST_KEYS,
        )
        _add_distribution(
            distributions["evidence_resolved_hostname_distribution"],
            resolved_host,
            max_distinct=_MAX_HOST_KEYS,
        )
        _add_distribution(
            distributions["evidence_acquisition_initial_hostname_distribution"],
            _safe_host_value(provenance.get("acquisition_initial_hostname")),
            max_distinct=_MAX_HOST_KEYS,
        )
        _add_distribution(
            distributions["evidence_acquisition_failing_endpoint_hostname_distribution"],
            _safe_host_value(provenance.get("acquisition_failing_endpoint_hostname")),
            max_distinct=_MAX_HOST_KEYS,
        )
        hop_count = provenance.get("redirect_hop_count")
        if isinstance(hop_count, int) and not isinstance(hop_count, bool) and hop_count >= 0:
            _add_distribution(
                distributions["evidence_redirect_hop_count_distribution"],
                _hop_bucket(hop_count),
            )
        elif isinstance(provenance.get("provenance_path"), (list, tuple)):
            _add_distribution(
                distributions["evidence_redirect_hop_count_distribution"],
                _hop_bucket(max(0, len(provenance["provenance_path"]) - 1)),
            )
        acquisition_hop = _hop_bucket(provenance.get("acquisition_redirect_hop_count"))
        if acquisition_hop is not None and not (
            isinstance(hop_count, int)
            and not isinstance(hop_count, bool)
            and hop_count >= 0
        ) and not isinstance(provenance.get("provenance_path"), (list, tuple)):
            _add_distribution(
                distributions["evidence_redirect_hop_count_distribution"],
                acquisition_hop,
            )
        if candidate_host and resolved_host:
            transition = "SAME_HOST" if candidate_host == resolved_host else "CHANGED_HOST"
        else:
            transition = "RESOLVED_HOST_MISSING"
        _add_distribution(distributions["evidence_host_transition_distribution"], transition)
        _add_distribution(
            distributions["evidence_acquisition_latency_bucket_distribution"],
            _latency_bucket(provenance.get("acquisition_elapsed_ms")),
        )
        _add_distribution(
            distributions["evidence_acquisition_path_distribution"],
            _safe_diag_token(provenance.get("acquisition_path"), allowed=_ACQUISITION_PATHS),
        )
        _add_distribution(
            distributions["evidence_acquisition_final_endpoint_distribution"],
            _safe_diag_token(
                provenance.get("acquisition_final_endpoint"),
                allowed=_ACQUISITION_FINAL_ENDPOINTS,
            ),
        )
        _add_distribution(
            distributions["evidence_acquisition_redirect_consistency_distribution"],
            _safe_diag_token(
                provenance.get("acquisition_redirect_consistency"),
                allowed=_ACQUISITION_REDIRECT_STATES,
            ),
        )
        _add_distribution(
            distributions["evidence_source_provenance_mismatch_distribution"],
            _field_diagnostic(
                provenance,
                "source_provenance_mismatch_reason",
                gate=gate,
                reached_after_gate=5,
                allowed=_SOURCE_PROVENANCE_FAILURES,
            ),
        )

        if evidence.state is EvidenceState.REJECTED:
            signature_parts = [
                f"reject_reason={str(evidence.reject_reason or 'UNKNOWN')}",
                f"evidence_rejection_gate={gate}",
            ]
            for key in (
                "status_code",
                "transport_error",
                "principal_document_status",
                "page_kind",
                "source_provenance",
                "canonical_related",
                "body_text_available",
                "factual_substance",
                "raw_relation",
                "response_validation_result",
                "source_provenance_mismatch_reason",
                "acquisition_path",
                "acquisition_final_endpoint",
                "acquisition_redirect_consistency",
            ):
                if key not in provenance:
                    continue
                value = _safe_diag_token(provenance.get(key), allowed=(
                    semantic_relations if key == "raw_relation" else
                    semantic_validation if key == "response_validation_result" else
                    _SOURCE_PROVENANCE_FAILURES if key == "source_provenance_mismatch_reason" else
                    _ACQUISITION_PATHS if key == "acquisition_path" else
                    _ACQUISITION_FINAL_ENDPOINTS if key == "acquisition_final_endpoint" else
                    _ACQUISITION_REDIRECT_STATES if key == "acquisition_redirect_consistency" else
                    None
                ))
                if value is not None:
                    signature_parts.append(f"{key}={value}")
            _add_distribution(
                distributions["evidence_rejection_signature_distribution"],
                ";".join(signature_parts),
            )

    projection: dict[str, Any] = {
        "evidence_ready_count": ready_count,
        "evidence_rejected_count": rejected_count,
    }
    projection.update(distributions)
    return projection
