"""RC-57 (contract section A.41): active discovery of normative/standard changes.

The user-approved Domain Rule: Search actively looks for changes of the kinds the
existing NORMATIVE_CHANGE definition describes; qualifying events appear in the
weekly report's existing 「規範及標準動態」 section and travel with that report.
These tests pin the boundary: one more discovery lane owned by SearchPlanner,
nothing decided by it downstream, no second report, message, state or schedule.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import re

import pytest

from src.weekly_report.contracts import CategoryId, DiscoveryIntent, SearchAttemptResult, SearchProviderId, SearchTerminalStatus
from src.weekly_report.delivery import DeliveryStatus
from src.weekly_report.region_registry import RegionRegistry
from src.weekly_report.report_service import ReportService
from src.weekly_report.search_executor import SearchExecutor
from src.weekly_report.search_planner import SearchPlanner, _query_words
from src.weekly_report.gmail_smtp import index_for_artifact
from src.weekly_report.validator import ValidatedReportEvent, ValidationResult
from src.weekly_report.writer import WriterReportBlock
from tests.delivery_fakes import PERIOD, Clock, FakeLedgerStore, FakeSender, service
from tests.test_report_service import _workflow_result

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "weekly_report"
SECTION = "規範及標準動態"
LIST_ADDRESS = "weekly-list@example.test"


@pytest.fixture(scope="module")
def registry() -> RegionRegistry:
    return RegionRegistry.from_file()


def _supported_editions(registry: RegionRegistry, markets) -> set[tuple[str, str]]:
    return {
        (market.market_id, profile_id)
        for market in markets
        for profile_id in registry.profiles_for_market(market)
        if registry.provider_profile_binding(market.market_id, profile_id, "google_news_rss").eligibility.value
        == "SUPPORTED"
    }


# --- Search: the production plan actively looks for normative changes -------------------


def test_normative_is_a_canonical_discovery_intent_and_not_a_category():
    assert DiscoveryIntent("normative") is DiscoveryIntent.NORMATIVE
    assert DiscoveryIntent.NORMATIVE.display_label == "normative"
    assert DiscoveryIntent.NORMATIVE.value != CategoryId.NORMATIVE_CHANGE.value


@pytest.mark.parametrize("mode", ["selected", "global"])
def test_every_supported_edition_has_a_normative_request_in_the_production_plan(registry, mode):
    plan = SearchPlanner(registry).plan(mode)
    markets = registry.selected_markets if mode == "selected" else registry.markets_for(mode)
    normative = [item for item in plan.items if item.intent is DiscoveryIntent.NORMATIVE]
    assert {(item.market_id, item.language_profile) for item in normative} == _supported_editions(registry, markets)
    assert {item.query_family_id for item in normative} == {"urban_rail_or_groups"}
    assert all(_query_words(item.query) <= 32 for item in normative)
    # The normative lane does not displace any other required intent.
    assert {item.intent for item in plan.items} == set(DiscoveryIntent)
    assert len(plan.items) == 155 and len(normative) == 33


def test_normative_queries_use_only_governed_generic_normative_vocabulary(registry):
    plan = SearchPlanner(registry).plan("selected")
    for item in (i for i in plan.items if i.intent is DiscoveryIntent.NORMATIVE):
        groups = registry.profile(item.language_profile).intent_vocabulary["normative"]
        assert set(groups) == {"urban_rail_terms", "normative_terms"}
        allowed = set(groups["urban_rail_terms"]) | set(groups["normative_terms"])
        used = {
            term.removeprefix("intitle:").strip('"')
            for term in re.findall(r'"[^"]+"|[^\s()]+', item.query)
            if term != "OR"
        }
        assert used <= allowed, (item.market_id, used - allowed)
        # Mode terms stay in the title, as for every intent (RC-12).
        assert "intitle:" in item.query


def test_normative_vocabulary_names_no_standard_number_body_regulator_or_site(registry):
    forbidden = re.compile(
        r"\d|site:|https?:|\.(com|org|gov)\b|"
        r"\b(IEC|ISO|EN|IEEE|NFPA|UIC|ASTM|ANSI|CEN|CENELEC|BSI|DIN|JIS|KS|CNS|APTA|ERA|ORR|FTA|LTA)\b"
    )
    for profile in registry.profiles:
        for group, terms in profile.intent_vocabulary["normative"].items():
            for term in terms:
                assert not forbidden.search(term), (profile.profile_id, group, term)


def test_every_normative_request_is_planned_and_attempted_once(registry):
    calls: list[str] = []

    class _ZeroResults:
        def execute(self, item):
            calls.append(item.plan_item_id)
            return SearchAttemptResult(item.plan_item_id, SearchTerminalStatus.SUCCESS_ZERO_RESULTS)

    plan = SearchPlanner(registry).plan("selected")
    result = SearchExecutor({SearchProviderId.GOOGLE_NEWS_RSS: _ZeroResults()}).execute(plan)
    normative_ids = [item.plan_item_id for item in plan.items if item.intent is DiscoveryIntent.NORMATIVE]
    assert result.execution_complete and not result.unattempted_items
    assert all(calls.count(item_id) == 1 for item_id in normative_ids)
    # A week without normative news is a legal zero-result search, not a failure.
    assert {r.status for r in result.attempt_results} == {SearchTerminalStatus.SUCCESS_ZERO_RESULTS}


# --- Search intent is never Category or Reportability authority -------------------------


def test_discovery_intent_is_read_only_by_normalization_and_the_audit_projection():
    readers = sorted(
        path.name
        for path in SRC.glob("*.py")
        if "discovery_intent" in path.read_text(encoding="utf-8")
        and path.name not in {"contracts.py", "region_registry.py"}
    )
    # candidate_normalizer writes the non-authoritative projection; the
    # selection audit only displays it. No owner decides anything from it.
    assert readers == ["candidate_normalizer.py", "selection_audit.py"]
    for owner in ("classifier.py", "reportability.py", "scope_classifier.py", "evidence_service.py",
                  "event_identity.py", "taxonomy.py", "validator.py", "writer.py", "report_service.py"):
        path = SRC / owner
        if path.exists():
            text = path.read_text(encoding="utf-8")
            assert "DiscoveryIntent" not in text and "discovery_intent" not in text, owner


# --- Report and Delivery: the same weekly report, one message, no extra state ---------------


def _artifact(categories):
    report_service = ReportService()
    base = report_service.project_formal_metadata((_workflow_result(),))[0]
    passed = []
    for event_id, category in categories:
        metadata = replace(base, event_id=event_id, category=category)
        block = WriterReportBlock(event_id, f"標題{event_id}", "事件摘要 Taiwan Metro", "可供臺北捷運評估規劃方向")
        passed.append(ValidatedReportEvent(_workflow_result(event_id), metadata, block))
    validation = ValidationResult(tuple(i.result for i in passed), tuple(i.metadata for i in passed), tuple(passed))
    return report_service.assemble_final_report(validation, period=PERIOD)


def test_a_normative_change_appears_in_the_existing_section_of_the_weekly_report():
    artifact = _artifact([("E1", "技術新知"), ("E2", "規範變動")])
    assert [section.category for section in artifact.sections] == ["技術新知", SECTION]
    email_text, email_html = index_for_artifact(artifact)
    assert f"【{SECTION}】" in artifact.content and f"【{SECTION}】" in email_text and f"【{SECTION}】" in email_html


def test_a_week_without_normative_change_omits_the_section_and_still_has_a_report():
    artifact = _artifact([("E1", "技術新知"), ("E2", "事故事件")])
    email_text, email_html = index_for_artifact(artifact)
    assert SECTION not in artifact.content and SECTION not in email_text and SECTION not in email_html
    assert [section.category for section in artifact.sections] == ["技術新知", "事故及安全事件"]


def test_normative_events_travel_in_the_one_weekly_message_per_recipient():
    store, clock = FakeLedgerStore(), Clock()
    with_normative = _artifact([("E1", "技術新知"), ("E2", "規範變動")])
    sender = FakeSender()
    receipt = service(store, sender, clock, "run1").deliver(with_normative, LIST_ADDRESS)
    assert receipt.status is DeliveryStatus.SENT
    assert sender.opened == [(LIST_ADDRESS,)] and sender.delivered == [LIST_ADDRESS]
    # A second run of the same week, with or without normative events, sends nothing more.
    for artifact in (with_normative, _artifact([("E1", "技術新知")])):
        again = FakeSender()
        assert service(store, again, clock, "run2").deliver(artifact, LIST_ADDRESS).status is DeliveryStatus.DUPLICATE
        assert again.attempted == []


def test_a_week_without_normative_change_is_still_delivered_once():
    store, clock, sender = FakeLedgerStore(), Clock(), FakeSender()
    receipt = service(store, sender, clock, "run1").deliver(_artifact([("E1", "營運動態")]), LIST_ADDRESS)
    assert receipt.status is DeliveryStatus.SENT and sender.delivered == [LIST_ADDRESS]


def test_delivery_and_mail_composition_have_no_category_or_standards_branch():
    for name in ("delivery.py", "delivery_ledger.py", "gmail_smtp.py"):
        text = (SRC / name).read_text(encoding="utf-8")
        # The mail body renders the sections ReportService assembled; it never
        # names a Category or branches on one.
        for token in ("NORMATIVE", "CategoryId", "DiscoveryIntent", "規範", "標準"):
            assert token not in text, (name, token)
