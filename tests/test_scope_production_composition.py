from __future__ import annotations

import json
from pathlib import Path
import sys
from unittest.mock import patch

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
from src.weekly_report.google_news_rss_provider import RssTransportResponse
from src.weekly_report.maiagent_transport import MaiAgentHttpResponse
from src.weekly_report.production_runner import ProductionRunner
from src.weekly_report.region_registry import RegionRegistry
from src.weekly_report.report_application import ReportApplication
from src.weekly_report.search_executor import SearchExecutor
from src.weekly_report.search_planner import SearchPlanner
from src.weekly_report.scope_classifier import ScopeClassifier
from src.weekly_report.scope_classifier import SCOPE_PROPOSAL_SCHEMA_VERSION
from src.weekly_report.temporal_rule import TemporalRule


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


class _OfflineScopeProposal:
    """Deterministic proposal fixture; ScopeClassifier remains authoritative."""

    def __call__(self, request):
        content = request.principal_content
        negative = "conventional" in content.casefold() or "intercity" in content.casefold()
        quote = content
        return {
            "candidate_id": request.candidate_id,
            "schema_version": SCOPE_PROPOSAL_SCHEMA_VERSION,
            "event_focus": {"status": "RESOLVED", "quote": quote},
            "action": {"label": quote, "quote": quote},
            "target": {"label": quote, "quote": quote},
            "system": {"label": quote, "quote": quote},
            "eligible_mode_family": "NON_ELIGIBLE" if negative else "METRO",
            "action_target": {"status": "ESTABLISHED", "relation": "AFFECTS", "quote": quote},
            "target_system": {"status": "ESTABLISHED", "relation": "BELONGS_TO", "quote": quote},
            "ambiguity": {"status": "NONE", "quote": quote},
            "noneligible_relation": {"status": "PRESENT" if negative else "ABSENT", "quote": quote},
            "noneligible_kind": "NON_URBAN_RAIL" if negative else "NONE",
            "event_status": "ASSERTED",
            "decision": "OUT_OF_SCOPE_SUPPORT" if negative else "IN_SCOPE_SUPPORT",
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
        scope_classifier=ScopeClassifier(_OfflineScopeProposal()),
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
    assert getattr(application.scope_classifier, "_semantic_helper") is not None
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
    assert getattr(application.scope_classifier, "_semantic_helper") is not None
    assert result.evidence_results[0].state.value == "EVIDENCE_READY"
    assert result.scope_results[0].state is ScopeState.OUT_OF_SCOPE
    assert result.temporal_results == ()


def test_real_production_factory_offline_pairs_scope_and_temporal_without_live_io():
    """The governed factory reaches Temporal only for the real positive relation."""

    positive = "The Metro line signalling system was renewed."
    negative = (
        "The source discusses a Metro system, but this event concerns only the "
        "conventional intercity railway division and its mainline signalling corridor."
    )
    titles = {
        "https://fixtures.invalid/positive": ("Metro signalling renewal", positive),
        "https://fixtures.invalid/negative": ("Intercity signalling renewal", negative),
    }
    rss_calls = 0
    fetch_calls: list[str] = []
    helper_tasks: list[str] = []

    rss_body = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item><title>Metro signalling renewal</title><link>https://fixtures.invalid/positive</link>
    <pubDate>Tue, 15 Sep 2026 08:00:00 GMT</pubDate><description>Metro signalling renewal</description></item>
  <item><title>Intercity signalling renewal</title><link>https://fixtures.invalid/negative</link>
    <pubDate>Tue, 15 Sep 2026 09:00:00 GMT</pubDate><description>Intercity signalling renewal</description></item>
</channel></rss>""".encode()

    def rss_transport(url: str, timeout_seconds: float) -> RssTransportResponse:
        nonlocal rss_calls
        rss_calls += 1
        # The first real SearchExecutor request supplies the paired candidates;
        # subsequent real planner requests are legal empty RSS responses.
        return RssTransportResponse(
            rss_body if rss_calls == 1 else b"<?xml version='1.0'?><rss><channel/></rss>",
            final_url=url,
        )

    def fetcher(url: str, timeout_seconds: float) -> FetchedSource:
        fetch_calls.append(url)
        title, body = titles[url]
        return FetchedSource(
            url=url,
            content=f"<article><h1>{title}</h1><p>{body}</p></article>",
            content_type="text/html",
            redirect_chain=(url,),
        )

    def maiagent_transport(endpoint, *, headers, body, timeout_seconds):
        payload = json.loads(body)
        message = payload["message"]["content"]
        request = json.loads(message)
        task = request.get("task_identity", "")
        helper_tasks.append(task)
        if task == "evidence_source_candidate_match":
            segment = request["semantic_judge_request"]["principal_body_segments"][0]
            proposal = {
                "relation": "SAME_EVENT",
                "support_evidence": [
                    {"segment_id": segment["segment_id"], "exact_quote": segment["text"]}
                ],
                "conflict_evidence": [],
                "explanation": "offline Evidence fixture",
            }
        elif task == "evidence_metadata_extraction":
            proposal = {"observations": []}
        elif task == "scope_semantic_proposal":
            scope_request = request["scope_request"]
            content = scope_request["principal_content"]
            negative = "conventional" in content.casefold() or "intercity" in content.casefold()
            proposal = {
                "candidate_id": scope_request["candidate_id"],
                "schema_version": SCOPE_PROPOSAL_SCHEMA_VERSION,
                "event_focus": {"status": "RESOLVED", "quote": content},
                "action": {"label": content, "quote": content},
                "target": {"label": content, "quote": content},
                "system": {"label": content, "quote": content},
                "eligible_mode_family": "NON_ELIGIBLE" if negative else "METRO",
                "action_target": {"status": "ESTABLISHED", "relation": "AFFECTS", "quote": content},
                "target_system": {"status": "ESTABLISHED", "relation": "BELONGS_TO", "quote": content},
                "ambiguity": {"status": "NONE", "quote": content},
                "noneligible_relation": {"status": "PRESENT" if negative else "ABSENT", "quote": content},
                "noneligible_kind": "NON_URBAN_RAIL" if negative else "NONE",
                "event_status": "ASSERTED",
                "decision": "OUT_OF_SCOPE_SUPPORT" if negative else "IN_SCOPE_SUPPORT",
            }
        else:
            raise AssertionError(f"unexpected live-like helper task: {task}")
        return MaiAgentHttpResponse(200, json.dumps({"content": json.dumps(proposal)}).encode())

    settings = {
        "MAIAGENT_API_BASE": "https://offline.invalid",
        "MAIAGENT_API_KEY": "offline-key",
        "MAIAGENT_STRUCTURED_HELPER_CHATBOT_ID": "offline-helper",
        "MAIAGENT_CHATBOT_ID": "offline-writer",
        "DEFAULT_RECIPIENTS": "",
    }
    original_profile = sys.getprofile()
    temporal_calls = 0

    def profile(frame, event, argument):
        nonlocal temporal_calls
        if event == "call" and frame.f_code is TemporalRule.evaluate.__code__:
            temporal_calls += 1
        if original_profile is not None:
            original_profile(frame, event, argument)

    with (
        patch("src.weekly_report.evidence_service._default_fetcher", side_effect=fetcher),
        patch.object(Path, "is_file", return_value=False),
    ):
        runner = ProductionRunner.from_environment(
            environ=settings,
            transport=maiagent_transport,
            rss_transport=rss_transport,
        )
        sys.setprofile(profile)
        try:
            result = runner.application.run(
                RegionMode.SELECTED,
                intents=(DiscoveryIntent.TECHNOLOGY,),
                period_start="2026-09-12",
                period_end="2026-09-18",
            )
        finally:
            sys.setprofile(original_profile)

    assert type(runner.application.scope_classifier) is ScopeClassifier
    assert getattr(runner.application.scope_classifier, "_semantic_helper") is not None
    assert [item.state.value for item in result.evidence_results] == [
        "EVIDENCE_READY",
        "EVIDENCE_READY",
    ]
    scope_by_candidate = {item.candidate_id: item.state for item in result.scope_results}
    assert {
        evidence.canonical_source_url: scope_by_candidate[evidence.candidate_id]
        for evidence in result.evidence_results
    } == {
        "https://fixtures.invalid/positive": ScopeState.IN_SCOPE,
        "https://fixtures.invalid/negative": ScopeState.OUT_OF_SCOPE,
    }
    assert temporal_calls == 1
    assert len(result.temporal_results) == 1
    assert set(fetch_calls) == {
        "https://fixtures.invalid/positive",
        "https://fixtures.invalid/negative",
    }
    assert helper_tasks.count("evidence_source_candidate_match") == 2
    assert helper_tasks.count("evidence_metadata_extraction") == 2
    assert helper_tasks.count("scope_semantic_proposal") == 2
