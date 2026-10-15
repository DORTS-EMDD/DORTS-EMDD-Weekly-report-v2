"""Single production execution seam for the V2 report application.

This module composes the already-authoritative V2 owners and exposes only a
small, secret-free result for the CLI, Streamlit, and deployment diagnostics.
It deliberately contains no Search, Evidence, classification, or report
policy of its own.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import StrEnum
import os
from types import MappingProxyType
from typing import Any, Protocol

from .category_semantic_provider import build_maiagent_category_classifier
from .classifier import Classifier
from .contracts import (
    RegionMode,
    SearchAttemptResult,
    SearchPlan,
    SearchPlanItem,
    SearchTerminalStatus,
)
from .delivery import DeliveryReceipt, DeliveryService
from .evidence_service import EvidenceService
from .event_identity import EventIdentity
from .google_news_rss_provider import (
    GoogleNewsRssDiagnostic,
    GoogleNewsRssDiagnosticReason,
    GoogleNewsRssProvider,
)
from .maiagent_evidence_metadata_provider import build_maiagent_evidence_metadata_extractor
from .maiagent_reportability_provider import build_maiagent_reportability_provider
from .maiagent_semantic_judge_provider import build_maiagent_semantic_judge
from .maiagent_taxonomy_provider import build_maiagent_taxonomy_provider
from .maiagent_transport import MaiAgentJsonHttpTransport
from .maiagent_validation_provider import build_maiagent_validation_provider
from .ordering import Ordering
from .region_registry import RegionRegistry
from .report_application import ReportApplication, ReportApplicationResult, build_report_application
from .report_service import FinalReportArtifact, ReportService
from .report_workflow import build_report_workflow
from .scope_classifier import ScopeClassifier
from .search_executor import SearchExecutor
from .search_planner import SearchPlanner
from .temporal_rule import TemporalRule
from .writer import ReportWriter
from .validator import Validator


PRODUCTION_METADATA_MODEL = "GPT-OSS-120B"
HEALTH_PROBE_ORDINALS = (1, 10, 225, 230, 440, 449)


class ProductionConfigurationError(RuntimeError):
    """Production configuration was not complete enough to compose V2."""


class ProductionRunStatus(StrEnum):
    SUCCESS = "SUCCESS"
    TECHNICAL_FAILURE = "TECHNICAL_FAILURE"
    CONFIGURATION_FAILURE = "CONFIGURATION_FAILURE"
    APPLICATION_FAILURE = "APPLICATION_FAILURE"


@dataclass(frozen=True, slots=True)
class SearchFailureDiagnostic:
    """Safe deployment-level projection of one authoritative failed attempt."""

    ordinal: int
    plan_item_id: str
    market_id: str
    language_profile: str
    intent: str
    query_family_id: str
    terminal_status: str
    technical_failure_class: str
    reason_code: str
    http_status: int | None = None

    def __post_init__(self) -> None:
        if isinstance(self.ordinal, bool) or not isinstance(self.ordinal, int) or self.ordinal < 1:
            raise ValueError("SearchFailureDiagnostic ordinal must be positive")
        for field_name in (
            "plan_item_id",
            "market_id",
            "language_profile",
            "intent",
            "query_family_id",
            "terminal_status",
            "technical_failure_class",
            "reason_code",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"SearchFailureDiagnostic requires {field_name}")
        if self.http_status is not None and (
            isinstance(self.http_status, bool)
            or not isinstance(self.http_status, int)
            or not 100 <= self.http_status <= 599
        ):
            raise ValueError("SearchFailureDiagnostic http_status must be a valid HTTP status")


class _SearchFailureDiagnosticCollector:
    """Per-run passive provider observation channel."""

    def __init__(self) -> None:
        self._items: dict[str, GoogleNewsRssDiagnostic] = {}

    def clear(self) -> None:
        self._items.clear()

    def record(self, diagnostic: GoogleNewsRssDiagnostic) -> None:
        if not isinstance(diagnostic, GoogleNewsRssDiagnostic):
            return
        # One SearchPlanItem is attempted once.  Keeping the first observation
        # avoids an observer becoming an alternative source of truth if a
        # caller reuses the provider outside the normal runner path.
        self._items.setdefault(diagnostic.plan_item_id, diagnostic)

    def snapshot(self) -> Mapping[str, GoogleNewsRssDiagnostic]:
        return dict(self._items)


def _search_failure_projection(
    result: ReportApplicationResult,
    diagnostics: Mapping[str, GoogleNewsRssDiagnostic] | None,
) -> tuple[int, Mapping[str, int], Mapping[str, int], Mapping[str, int], tuple[SearchFailureDiagnostic, ...]]:
    """Project safe failure facts from the authoritative Search result."""

    item_by_id = {item.plan_item_id: (ordinal, item) for ordinal, item in enumerate(result.plan.items, 1)}
    class_distribution: dict[str, int] = {}
    reason_distribution: dict[str, int] = {}
    status_distribution: dict[str, int] = {}
    details: list[SearchFailureDiagnostic] = []
    for attempt in result.execution.attempt_results:
        if attempt.status is not SearchTerminalStatus.TECHNICAL_FAILURE:
            continue
        failure_class = str(attempt.technical_failure_class or "UNKNOWN")
        class_distribution[failure_class] = class_distribution.get(failure_class, 0) + 1
        diagnostic = diagnostics.get(attempt.plan_item_id) if diagnostics is not None else None
        reason_code = (
            str(diagnostic.reason_code)
            if diagnostic is not None
            else GoogleNewsRssDiagnosticReason.UNKNOWN.value
        )
        reason_distribution[reason_code] = reason_distribution.get(reason_code, 0) + 1
        if diagnostic is not None and diagnostic.http_status is not None:
            status_key = str(diagnostic.http_status)
            status_distribution[status_key] = status_distribution.get(status_key, 0) + 1
        ordinal, item = item_by_id.get(attempt.plan_item_id, (None, None))
        if item is None or ordinal is None:
            # SearchExecutionResult normally guarantees this cannot occur.  A
            # malformed test double must not make the observer authoritative.
            continue
        details.append(
            SearchFailureDiagnostic(
                ordinal=ordinal,
                plan_item_id=item.plan_item_id,
                market_id=item.market_id,
                language_profile=item.language_profile,
                intent=item.intent.value,
                query_family_id=item.query_family_id,
                terminal_status=attempt.status.value,
                technical_failure_class=failure_class,
                reason_code=reason_code,
                http_status=None if diagnostic is None else diagnostic.http_status,
            )
        )
    return (
        sum(class_distribution.values()),
        dict(class_distribution),
        dict(reason_distribution),
        dict(status_distribution),
        tuple(details),
    )


@dataclass(frozen=True, slots=True)
class ProductionRunResult:
    """Secret-free mechanical result consumed by all production shells."""

    status: ProductionRunStatus
    period_start: date
    period_end: date
    region_mode: RegionMode
    stage_counts: Mapping[str, int]
    final_report: FinalReportArtifact | None = None
    delivery_result: DeliveryReceipt | None = None
    failure_stage: str | None = None
    failure_class: str | None = None
    diagnostic: str | None = None
    search_failure_count: int | None = None
    search_failure_class_distribution: Mapping[str, int] = field(default_factory=dict)
    search_failure_reason_distribution: Mapping[str, int] = field(default_factory=dict)
    search_failure_http_status_distribution: Mapping[str, int] = field(default_factory=dict)
    search_failure_details: tuple[SearchFailureDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", ProductionRunStatus(self.status))
        object.__setattr__(self, "region_mode", RegionMode(self.region_mode))
        if not isinstance(self.period_start, date) or not isinstance(self.period_end, date):
            raise TypeError("ProductionRunResult requires date period bounds")
        if self.period_end < self.period_start:
            raise ValueError("ProductionRunResult period is reversed")
        counts = dict(self.stage_counts)
        if any(
            not isinstance(key, str)
            or not key.strip()
            or isinstance(value, bool)
            or not isinstance(value, int)
            or value < 0
            for key, value in counts.items()
        ):
            raise ValueError("ProductionRunResult stage_counts must be non-negative integers")
        object.__setattr__(self, "stage_counts", MappingProxyType(counts))
        if self.search_failure_count is not None and (
            isinstance(self.search_failure_count, bool)
            or not isinstance(self.search_failure_count, int)
            or self.search_failure_count < 0
        ):
            raise ValueError("search_failure_count must be a non-negative integer when present")
        for field_name in (
            "search_failure_class_distribution",
            "search_failure_reason_distribution",
            "search_failure_http_status_distribution",
        ):
            values = dict(getattr(self, field_name))
            if any(
                not isinstance(key, str)
                or not key.strip()
                or isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
                for key, value in values.items()
            ):
                raise ValueError(f"{field_name} must contain non-negative integer counts")
            object.__setattr__(self, field_name, MappingProxyType(values))
        details = tuple(self.search_failure_details)
        if any(not isinstance(detail, SearchFailureDiagnostic) for detail in details):
            raise TypeError("search_failure_details must contain SearchFailureDiagnostic values")
        object.__setattr__(self, "search_failure_details", details)
        for field_name in ("failure_stage", "failure_class", "diagnostic"):
            value = getattr(self, field_name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{field_name} must be non-empty when present")

    @property
    def successful(self) -> bool:
        return self.status is ProductionRunStatus.SUCCESS

    @property
    def artifact_id(self) -> str | None:
        return None if self.final_report is None else self.final_report.artifact_id

    def summary(self) -> str:
        counts = ",".join(f"{key}={value}" for key, value in self.stage_counts.items())
        parts = [
            f"status={self.status.value}",
            f"period={self.period_start.isoformat()}..{self.period_end.isoformat()}",
            f"region_mode={self.region_mode.value}",
            f"stages={counts or 'none'}",
        ]
        if self.artifact_id:
            parts.append(f"artifact_id={self.artifact_id}")
        if self.delivery_result is not None:
            parts.append(f"delivery={self.delivery_result.status.value}")
        if self.failure_stage:
            parts.append(f"failure_stage={self.failure_stage}")
        if self.failure_class:
            parts.append(f"failure_class={self.failure_class}")
        if self.diagnostic:
            parts.append(f"diagnostic={self.diagnostic}")
        if self.search_failure_count is not None:
            parts.append(f"search_failure_count={self.search_failure_count}")
            if self.search_failure_class_distribution:
                parts.append(
                    "search_failure_classes="
                    + _format_distribution(self.search_failure_class_distribution)
                )
            if self.search_failure_reason_distribution:
                parts.append(
                    "search_failure_reasons="
                    + _format_distribution(self.search_failure_reason_distribution)
                )
            if self.search_failure_http_status_distribution:
                parts.append(
                    "search_failure_http_statuses="
                    + _format_distribution(self.search_failure_http_status_distribution)
                )
            for detail in self.search_failure_details:
                parts.append(
                    "search_failure_item="
                    + ",".join(
                        (
                            f"ordinal={detail.ordinal}",
                            f"plan_item_id={detail.plan_item_id}",
                            f"market={detail.market_id}",
                            f"profile={detail.language_profile}",
                            f"intent={detail.intent}",
                            f"query_family={detail.query_family_id}",
                            f"terminal_status={detail.terminal_status}",
                            f"technical_failure_class={detail.technical_failure_class}",
                            f"reason_code={detail.reason_code}",
                            f"http_status={detail.http_status if detail.http_status is not None else 'NONE'}",
                        )
                    )
                )
        return " ".join(parts)


def _format_distribution(values: Mapping[str, int]) -> str:
    return ",".join(f"{key}={values[key]}" for key in sorted(values))


class RunnerApplication(Protocol):
    def run(
        self,
        mode: RegionMode | str,
        intents: Any = None,
        *,
        period_start: date | str,
        period_end: date | str,
    ) -> ReportApplicationResult:
        ...


def default_period(today: date | None = None) -> tuple[date, date]:
    """Return the preceding Monday-through-Sunday reporting period."""

    current = today or date.today()
    end = current - timedelta(days=current.weekday() + 1)
    return end - timedelta(days=6), end


def _safe_failure(exc: BaseException, *, stage: str) -> ProductionRunResult:
    start, end = default_period()
    return ProductionRunResult(
        ProductionRunStatus.APPLICATION_FAILURE,
        start,
        end,
        RegionMode.SELECTED,
        {},
        failure_stage=stage,
        failure_class=type(exc).__name__,
        diagnostic="production execution failed",
    )


def _stage_counts(result: ReportApplicationResult) -> dict[str, int]:
    """Project counts without retaining raw provider/debug data."""

    values: dict[str, int] = {
        "search_plan": len(result.plan.items),
        "search_attempts": len(result.execution.attempt_results),
        "search_unattempted": len(result.execution.unattempted_items),
        "acquisitions": len(result.acquisitions),
    }
    for name in (
        "normalized_observations",
        "evidence_results",
        "scope_results",
        "temporal_results",
        "event_identity_records",
        "category_results",
        "downstream_results",
        "ordered_results",
        "formal_metadata",
        "writer_blocks",
    ):
        value = getattr(result, name)
        if value is not None:
            values[name] = len(value)
    if result.validation_result is not None:
        values["validation_passed"] = result.validation_result.pass_count
        values["validation_failed"] = len(result.validation_result.failed)
    if result.final_report is not None:
        values["final_report_events"] = result.final_report.event_count
    return values


def _technical_class(result: ReportApplicationResult) -> str:
    for attempt in result.execution.attempt_results:
        if attempt.status is SearchTerminalStatus.TECHNICAL_FAILURE:
            return str(attempt.technical_failure_class or "UNKNOWN")
    if result.execution.infrastructure_failure is not None:
        return str(result.execution.infrastructure_failure.failure_class)
    return "UNKNOWN"


class ProductionRunner:
    """The one production composition and execution owner."""

    def __init__(
        self,
        application: RunnerApplication,
        *,
        delivery_recipient: str | None = None,
        diagnostic_collector: _SearchFailureDiagnosticCollector | None = None,
    ) -> None:
        if not callable(getattr(application, "run", None)):
            raise TypeError("ProductionRunner requires a ReportApplication-compatible application")
        if delivery_recipient is not None and (
            not isinstance(delivery_recipient, str) or not delivery_recipient.strip()
        ):
            raise ValueError("delivery_recipient must be non-empty when present")
        self._application = application
        self._delivery_recipient = delivery_recipient.strip() if delivery_recipient else None
        self._diagnostic_collector = diagnostic_collector

    @classmethod
    def from_environment(
        cls,
        *,
        environ: Mapping[str, str] | None = None,
        transport: MaiAgentJsonHttpTransport | None = None,
        rss_transport: Any | None = None,
    ) -> "ProductionRunner":
        """Compose V2 once from the governed process/.env configuration."""

        values = os.environ if environ is None else environ
        registry = RegionRegistry.from_file()
        diagnostic_collector = _SearchFailureDiagnosticCollector()
        provider = GoogleNewsRssProvider(
            rss_transport,
            diagnostic_sink=diagnostic_collector.record,
        )
        # Search providers are keyed by the canonical enum, not an adapter-owned name.
        from .contracts import SearchProviderId

        executor = SearchExecutor({SearchProviderId.GOOGLE_NEWS_RSS: provider})

        judge = build_maiagent_semantic_judge(
            model_identifier=PRODUCTION_METADATA_MODEL,
            transport=transport,
            environ=values,
        )
        metadata_extractor = build_maiagent_evidence_metadata_extractor(
            transport=transport,
            environ=values,
        )
        evidence_service = EvidenceService(
            semantic_judge=judge,
            judge_metadata=getattr(judge, "metadata", None),
            metadata_extractor=metadata_extractor,
        )
        classifier = build_maiagent_category_classifier(transport=transport, environ=values)
        taxonomy_provider = build_maiagent_taxonomy_provider(transport=transport, environ=values)
        reportability_provider = build_maiagent_reportability_provider(
            transport=transport, environ=values
        )
        if reportability_provider is None:
            raise ProductionConfigurationError("Reportability provider configuration is unavailable")
        workflow = build_report_workflow(
            taxonomy_proposal_provider=taxonomy_provider,
            reportability_proposal_provider=reportability_provider,
        )
        writer = ReportWriter.from_environment(environ=values, transport=transport)
        validation_provider = build_maiagent_validation_provider(transport=transport, environ=values)
        if writer is None or validation_provider is None:
            raise ProductionConfigurationError("Writer and Validator configuration is unavailable")
        validator = Validator(semantic_provider=validation_provider)
        delivery = DeliveryService(live_email_send=False)
        recipient = values.get("DEFAULT_RECIPIENTS") if isinstance(values, Mapping) else None
        recipient = recipient.strip() if isinstance(recipient, str) and recipient.strip() else None
        application = build_report_application(
            registry,
            executor,
            evidence_service=evidence_service,
            scope_classifier=ScopeClassifier(),
            temporal_rule=TemporalRule(),
            event_identity=EventIdentity(),
            classifier=classifier,
            report_workflow=workflow,
            ordering=Ordering(),
            report_service=ReportService(),
            writer=writer,
            validator=validator,
            delivery=delivery if recipient else None,
            delivery_recipient=recipient,
        )
        return cls(
            application,
            delivery_recipient=recipient,
            diagnostic_collector=diagnostic_collector,
        )

    @property
    def application(self) -> RunnerApplication:
        return self._application

    def run(
        self,
        *,
        region_mode: RegionMode | str = RegionMode.SELECTED,
        period_start: date | str | None = None,
        period_end: date | str | None = None,
    ) -> ProductionRunResult:
        mode = RegionMode(region_mode)
        default_start, default_end = default_period()
        start = default_start if period_start is None else date.fromisoformat(str(period_start))
        end = default_end if period_end is None else date.fromisoformat(str(period_end))
        if end < start:
            raise ValueError("period_end must not precede period_start")
        if self._diagnostic_collector is not None:
            self._diagnostic_collector.clear()
        try:
            result = self._application.run(mode, period_start=start, period_end=end)
        except Exception as exc:
            return ProductionRunResult(
                ProductionRunStatus.APPLICATION_FAILURE,
                start,
                end,
                mode,
                {},
                failure_stage="application",
                failure_class=type(exc).__name__,
                diagnostic="production execution failed",
            )
        if not hasattr(result, "execution") or not hasattr(result, "plan"):
            return ProductionRunResult(
                ProductionRunStatus.APPLICATION_FAILURE,
                start,
                end,
                mode,
                {},
                failure_stage="application",
                failure_class="INVALID_RESULT",
                diagnostic="application returned an invalid result",
            )
        counts = _stage_counts(result)
        if not result.execution.execution_complete or result.execution.has_technical_failures:
            (
                search_failure_count,
                class_distribution,
                reason_distribution,
                status_distribution,
                failure_details,
            ) = _search_failure_projection(
                result,
                None
                if self._diagnostic_collector is None
                else self._diagnostic_collector.snapshot(),
            )
            return ProductionRunResult(
                ProductionRunStatus.TECHNICAL_FAILURE,
                start,
                end,
                mode,
                counts,
                failure_stage="search",
                failure_class=_technical_class(result),
                diagnostic="Search execution did not reach a successful terminal state",
                search_failure_count=search_failure_count,
                search_failure_class_distribution=class_distribution,
                search_failure_reason_distribution=reason_distribution,
                search_failure_http_status_distribution=status_distribution,
                search_failure_details=failure_details,
            )
        if result.final_report is None:
            return ProductionRunResult(
                ProductionRunStatus.APPLICATION_FAILURE,
                start,
                end,
                mode,
                counts,
                failure_stage="final_report",
                failure_class="ARTIFACT_UNAVAILABLE",
                diagnostic="final formal report artifact was not produced",
            )
        return ProductionRunResult(
            ProductionRunStatus.SUCCESS,
            start,
            end,
            mode,
            counts,
            final_report=result.final_report,
            delivery_result=result.delivery_result,
        )


@dataclass(frozen=True, slots=True)
class HealthProbeResult:
    ordinal: int
    plan_item_id: str
    market_id: str
    language_profile: str
    intent: str
    status: str
    technical_failure_class: str | None = None


@dataclass(frozen=True, slots=True)
class GoogleNewsHealthCheckResult:
    plan_item_count: int
    probe_ordinals: tuple[int, ...]
    probes: tuple[HealthProbeResult, ...]
    success_count: int
    failure_count: int
    status: str

    @property
    def passed(self) -> bool:
        return self.status == "PASS"


class GoogleNewsHealthCheck:
    """Six-probe operational diagnostic over the authoritative Search plan."""

    def __init__(self, registry: RegionRegistry, provider: GoogleNewsRssProvider) -> None:
        self._registry = registry
        self._provider = provider

    def run(self) -> GoogleNewsHealthCheckResult:
        plan = SearchPlanner(self._registry).plan(RegionMode.SELECTED)
        if len(plan.items) < max(HEALTH_PROBE_ORDINALS):
            raise ValueError("Search plan is shorter than the fixed health probes")
        probes: list[HealthProbeResult] = []
        for ordinal in HEALTH_PROBE_ORDINALS:
            item = plan.items[ordinal - 1]
            outcome = self._provider.execute(item)
            if not isinstance(outcome, SearchAttemptResult) or outcome.plan_item_id != item.plan_item_id:
                status = SearchTerminalStatus.TECHNICAL_FAILURE.value
                failure = "INVALID_RESPONSE"
            else:
                status = outcome.status.value
                failure = (
                    str(outcome.technical_failure_class)
                    if outcome.status is SearchTerminalStatus.TECHNICAL_FAILURE
                    else None
                )
            probes.append(
                HealthProbeResult(
                    ordinal,
                    item.plan_item_id,
                    item.market_id,
                    item.language_profile,
                    item.intent.value,
                    status,
                    failure,
                )
            )
        success_count = sum(
            item.status in {
                SearchTerminalStatus.SUCCESS_WITH_RESULTS.value,
                SearchTerminalStatus.SUCCESS_ZERO_RESULTS.value,
            }
            for item in probes
        )
        failure_count = len(probes) - success_count
        return GoogleNewsHealthCheckResult(
            len(plan.items),
            HEALTH_PROBE_ORDINALS,
            tuple(probes),
            success_count,
            failure_count,
            "PASS" if success_count == len(HEALTH_PROBE_ORDINALS) else "FAIL",
        )


__all__ = [
    "GoogleNewsHealthCheck",
    "GoogleNewsHealthCheckResult",
    "HEALTH_PROBE_ORDINALS",
    "HealthProbeResult",
    "PRODUCTION_METADATA_MODEL",
    "ProductionConfigurationError",
    "ProductionRunResult",
    "ProductionRunStatus",
    "ProductionRunner",
    "SearchFailureDiagnostic",
    "default_period",
]
