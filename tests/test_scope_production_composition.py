from __future__ import annotations

from src.weekly_report.contracts import (
    DiscoveryIntent,
    DiscoveryResult,
    GoogleNewsRssEncoding,
    RegionMode,
    SearchAttemptResult,
    SearchPlan,
    SearchPlanItem,
    SearchProviderId,
    SearchTerminalStatus,
    ScopeState,
)
from src.weekly_report.evidence_service import EvidenceService, FetchedSource
from src.weekly_report.region_registry import RegionRegistry
from src.weekly_report.report_application import ReportApplication
from src.weekly_report.search_executor import SearchExecutor
from src.weekly_report.search_planner import SearchPlanner
from src.weekly_report.scope_classifier import ScopeClassifier


class _OfflineSearchProvider:
    """Deterministic discovery boundary; production SearchExecutor remains real."""

    def __init__(self, title: str) -> None:
        self._title = title

    def execute(self, request: SearchPlanItem) -> SearchAttemptResult:
        return SearchAttemptResult(
            request.plan_item_id,
            SearchTerminalStatus.SUCCESS_WITH_RESULTS,
            (
                DiscoveryResult(
                    self._title,
                    "https://fixtures.invalid/scope-production",
                    "Offline contract fixture",
                    "2026-09-15T08:00:00Z",
                    "",
                ),
            ),
        )


class _OfflinePlanner(SearchPlanner):
    """One-item plan at the ordinary planner boundary for an offline run."""

    def plan(self, mode, intents=None):
        return SearchPlan(
            "offline-scope-plan",
            RegionMode.SELECTED,
            (
                SearchPlanItem(
                    "offline-scope-item",
                    "fixture",
                    RegionMode.SELECTED,
                    DiscoveryIntent.TECHNOLOGY,
                    "en",
                    "fixture-family",
                    SearchProviderId.GOOGLE_NEWS_RSS,
                    "offline query",
                    GoogleNewsRssEncoding("en-US", "US", "US:en"),
                    "en-US",
                ),
            ),
            "offline-scope-plan-digest",
        )


class _OfflineSemanticJudge:
    """Evidence boundary substitute; it does not make a Scope decision."""

    def __call__(self, request):
        segment = request.principal_body_segments[0]
        return {
            "relation": "SAME_EVENT",
            "support_evidence": [
                {"segment_id": segment.segment_id, "exact_quote": segment.text}
            ],
            "conflict_evidence": [],
            "explanation": "deterministic offline Evidence fixture",
        }


def _run_offline_application(body: str, title: str):
    registry = RegionRegistry.from_file()
    planner = _OfflinePlanner(registry)

    def fetcher(url: str) -> FetchedSource:
        return FetchedSource(
            url=url,
            content=f"<article><h1>{title}</h1><p>{body}</p></article>",
            content_type="text/html",
            redirect_chain=(url,),
        )

    application = ReportApplication(
        registry,
        planner,
        SearchExecutor(
            {SearchProviderId.GOOGLE_NEWS_RSS: _OfflineSearchProvider(title)}
        ),
        evidence_service=EvidenceService(
            fetcher=fetcher,
            semantic_judge=_OfflineSemanticJudge(),
        ),
    )
    result = application.run(
        RegionMode.SELECTED,
        intents=(DiscoveryIntent.TECHNOLOGY,),
        period_start="2026-09-12",
        period_end="2026-09-18",
    )
    return application, result


def test_real_offline_composition_reaches_temporal_without_scope_helper():
    application, result = _run_offline_application(
        "The identified Metro system commissioned a new signalling controller on its central line.",
        "Metro controller upgrade",
    )

    assert type(application.scope_classifier) is ScopeClassifier
    assert getattr(application.scope_classifier, "_semantic_helper") is None
    assert result.evidence_results[0].state.value == "EVIDENCE_READY"
    assert result.scope_results[0].state is ScopeState.IN_SCOPE
    assert len(result.temporal_results) == 1


def test_real_offline_composition_keeps_unresolved_mixed_mode_out_of_temporal():
    application, result = _run_offline_application(
        "The shared corridor carries Metro and conventional railway services. "
        "The operator upgraded control equipment without identifying which mode received the upgrade.",
        "Shared corridor control upgrade",
    )

    assert type(application.scope_classifier) is ScopeClassifier
    assert getattr(application.scope_classifier, "_semantic_helper") is None
    assert result.evidence_results[0].state.value == "EVIDENCE_READY"
    assert result.scope_results[0].state is ScopeState.OUT_OF_SCOPE
    assert result.temporal_results == ()
