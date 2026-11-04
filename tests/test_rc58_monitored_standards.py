"""RC-58 (contract section A.42): standards-update monitoring is the V1 list.

The user-approved Domain Rule: only a formal lifecycle change of a standard on
the V1 monitored list is a standards update for this product. The list is one
data file; Search discovers by its identifiers; Reportability alone decides
whether a NORMATIVE_CHANGE event is such a change. Qualifying events appear in
the existing 「規範及標準動態」 section of the one weekly report.
"""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import re

import pytest

from src.weekly_report.contracts import (
    CanonicalCandidate,
    CategoryId,
    CategoryResult,
    CategoryState,
    DiscoveryIntent,
    EventDecisionRecord,
    EventGroup,
    EventIdentityRecord,
    EvidenceResult,
    EvidenceState,
    MonitoredStandardRequest,
    ReportabilityProposalViolation,
    ReportabilityReason,
    ReportabilitySemanticRequest,
    ReportabilityState,
    ScopeResult,
    ScopeState,
    SearchAttemptResult,
    SearchProviderId,
    SearchTerminalStatus,
    TaxonomyResult,
    TaxonomyState,
    TemporalDiagnostic,
    TemporalResult,
)
from src.weekly_report.delivery import DeliveryStatus
from src.weekly_report.gmail_smtp import index_for_artifact
from src.weekly_report.maiagent_reportability_provider import (
    MONITORED_STANDARD_PROMPT_VERSION,
    MONITORED_STANDARD_SCHEMA_VERSION,
    PROMPT_VERSION,
    SCHEMA_VERSION,
    build_maiagent_reportability_model_input,
)
from src.weekly_report.monitored_standards import (
    MonitoredStandards,
    load_monitored_standards_data,
    monitored_standards,
)
from src.weekly_report.region_registry import RegionRegistry
from src.weekly_report.report_service import FORMAL_REPORT_SECTIONS, ReportService
from src.weekly_report.reportability import Reportability
from src.weekly_report.search_executor import SearchExecutor
from src.weekly_report.search_planner import SearchPlanner, _query_words
from src.weekly_report.validator import ValidatedReportEvent, ValidationResult
from src.weekly_report.writer import WriterReportBlock
from tests.delivery_fakes import PERIOD, Clock, FakeLedgerStore, FakeSender, service
from tests.test_report_service import _workflow_result

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "weekly_report"
GOLDEN = json.loads((ROOT / "golden" / "monitored_standards_cases.json").read_text(encoding="utf-8"))
SECTION = "規範及標準動態"
LIST_ADDRESS = "weekly-list@example.test"

V1_LIST = {
    "碰撞/出軌類": ["EN 50126", "EN 50128", "EN 50129", "IEEE 1474.1", "EN 13674-1", "UIC 860-0", "IEC 61373"],
    "觸電/電弧爆炸類": ["EN 50122", "EN 50122-2", "EN 50327", "EN 50328", "EN 50329", "IEC 62271-100",
                    "IEC 62271-102", "IEC 60947-1", "IEC 60850"],
    "火災/中毒類": ["NFPA 130", "ASTM E119", "IEC 60754-1", "IEC 60754-2", "IEC 60332-1", "ASTM E662", "NFPA 258",
                "NFPA 70"],
    "結構性/爆炸性設備失效類": ["IEC 60076", "IEC 60076-11", "IEC 62695"],
}


# --- The monitored list: one data file, the exact V1 literal -----------------------------


def test_the_list_is_the_exact_v1_literal_with_its_recorded_digest():
    data = load_monitored_standards_data()
    standards = monitored_standards()
    assert {group["label"]: group["standards"] for group in data["groups"]} == V1_LIST
    assert len(standards.identifiers) == 27 and len(set(standards.identifiers)) == 27
    assert standards.source_literal_sha256(data) == data["provenance"]["source_literal_sha256"]
    assert data["provenance"]["copies_compared"] == 31 and data["provenance"]["copies_identical"] is True


def test_the_list_rejects_duplicates_and_malformed_identifiers():
    with pytest.raises(ValueError):
        MonitoredStandards({"reference_version": "x", "groups": [{"label": "a", "standards": ["EN 50126", "EN 50126"]}]})
    with pytest.raises(ValueError):
        MonitoredStandards({"reference_version": "x", "groups": [{"label": "a", "standards": ["EN50126"]}]})


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("CENELEC published EN 50126-1:2025", ("EN 50126",)),
        ("BS EN 50122-2:2010 amendment A1", ("EN 50122", "EN 50122-2")),
        ("IEEE Std 1474.1-2025", ("IEEE 1474.1",)),
        ("NFPA 70® 2026 edition", ("NFPA 70",)),
        ("ASTM E 119-24", ("ASTM E119",)),
        ("ＩＥＣ ６１３７３", ("IEC 61373",)),
        ("NFPA 70E workplace safety", ()),
        ("EN 501260", ()),
        ("IEEE 1474.10", ()),
        ("IEC 62271-1000", ()),
        ("IEC 62290-1 urban guided transport", ()),
    ],
)
def test_identifier_matching_is_mechanical(text, expected):
    assert monitored_standards().identifiers_in(text) == expected


# --- Search: discovery by the monitored identifiers ---------------------------------------


@pytest.fixture(scope="module")
def registry() -> RegionRegistry:
    return RegionRegistry.from_file()


def _supported(registry, markets):
    return {
        (market.market_id, profile_id)
        for market in markets
        for profile_id in registry.profiles_for_market(market)
        if registry.provider_profile_binding(market.market_id, profile_id, "google_news_rss").eligibility.value
        == "SUPPORTED"
    }


def test_the_discovery_intent_is_monitored_standards_and_not_a_category():
    assert DiscoveryIntent.MONITORED_STANDARDS.value == "monitored_standards"
    assert {intent.value for intent in DiscoveryIntent}.isdisjoint({category.value for category in CategoryId})
    assert not hasattr(DiscoveryIntent, "NORMATIVE")


@pytest.mark.parametrize("mode", ["selected", "global"])
def test_every_supported_edition_searches_every_monitored_identifier(registry, mode):
    plan = SearchPlanner(registry).plan(mode)
    markets = registry.selected_markets if mode == "selected" else registry.markets_for(mode)
    monitored = [item for item in plan.items if item.intent is DiscoveryIntent.MONITORED_STANDARDS]
    assert {(item.market_id, item.language_profile) for item in monitored} == _supported(registry, markets)
    assert {item.query_family_id for item in monitored} == {"monitored_standard_identifiers"}
    identifiers = set(monitored_standards().identifiers)
    for edition in _supported(registry, markets):
        queries = [item.query for item in monitored if (item.market_id, item.language_profile) == edition]
        terms = {term.strip('"') for query in queries for term in re.findall(r'"[^"]+"|[^\s()]+', query) if term != "OR"}
        # Only the identifiers: no mode, lifecycle or generic normative word.
        assert terms == identifiers, edition
    assert all(_query_words(item.query) <= 32 for item in monitored)
    # RC-57's generic normative lane is gone; the other requests are unchanged.
    others = [item for item in plan.items if item.intent is not DiscoveryIntent.MONITORED_STANDARDS]
    assert len(others) == 122 and len(monitored) == 63 and len(plan.items) == 185
    assert all(item.query_family_id != "monitored_standard_identifiers" for item in others)


def test_the_search_configuration_identifiers_are_a_materialized_copy_of_the_list(registry):
    identifiers = monitored_standards().identifiers
    for profile in registry.profiles:
        assert dict(profile.intent_vocabulary["monitored_standards"]) == {"monitored_standard_ids": identifiers}
    language = (ROOT / "docs" / "SEARCH_LANGUAGE_PROFILES.md").read_text(encoding="utf-8")
    assert language.count("`monitored_standard_ids=@monitored_standards`") == 13
    assert "normative_terms=" not in language


def test_every_monitored_request_is_planned_and_attempted_once(registry):
    calls: list[str] = []

    class _ZeroResults:
        def execute(self, item):
            calls.append(item.plan_item_id)
            return SearchAttemptResult(item.plan_item_id, SearchTerminalStatus.SUCCESS_ZERO_RESULTS)

    plan = SearchPlanner(registry).plan("selected")
    result = SearchExecutor({SearchProviderId.GOOGLE_NEWS_RSS: _ZeroResults()}).execute(plan)
    ids = [item.plan_item_id for item in plan.items if item.intent is DiscoveryIntent.MONITORED_STANDARDS]
    assert result.execution_complete and not result.unattempted_items
    assert all(calls.count(item_id) == 1 for item_id in ids)


def test_discovery_intent_is_read_only_by_normalization_and_the_audit_projection():
    readers = sorted(
        path.name
        for path in SRC.glob("*.py")
        if "discovery_intent" in path.read_text(encoding="utf-8")
        and path.name not in {"contracts.py", "region_registry.py"}
    )
    assert readers == ["candidate_normalizer.py", "selection_audit.py"]
    for owner in ("classifier.py", "reportability.py", "scope_classifier.py", "evidence_service.py",
                  "event_identity.py", "validator.py", "writer.py", "report_service.py"):
        text = (SRC / owner).read_text(encoding="utf-8")
        assert "DiscoveryIntent" not in text and "discovery_intent" not in text, owner


def test_only_reportability_decides_and_only_the_list_module_holds_identifiers():
    users = sorted(path.name for path in SRC.glob("*.py") if "monitored_standards()" in path.read_text(encoding="utf-8"))
    assert users == ["monitored_standards.py", "reportability.py"]
    for path in SRC.glob("*.py"):
        if path.name == "monitored_standards.py":
            continue
        text = path.read_text(encoding="utf-8")
        for identifier in ("EN 50126", "NFPA 130", "IEC 60076", "ASTM E119"):
            assert identifier not in text, (path.name, identifier)


# --- Golden: the domain outcome of each case, through the production owner -----------------


def _record(case) -> EventDecisionRecord:
    evidence = EvidenceResult(
        candidate_id="C1",
        state=EvidenceState.READY,
        canonical_source_url="https://fixtures.invalid/C1",
        source_type="authoritative",
        substantive_content=case["source_content"],
    )
    member = EventIdentityRecord(
        CanonicalCandidate("C1", "Title", evidence.canonical_source_url),
        evidence,
        ScopeResult("C1", ScopeState.IN_SCOPE),
        TemporalResult("C1", True, diagnostic=TemporalDiagnostic.NONE),
    )
    group = EventGroup("E1", ("C1",), "C1", identity_basis=())
    category = CategoryId(case["category_id"])
    return EventDecisionRecord(
        event_group=group,
        member_records=(member,),
        category_result=CategoryResult(
            category_state=CategoryState.CATEGORY_ASSIGNED,
            event_id="E1",
            primary_category_id=category,
            primary_category=category.display_label,
            classification_reason=f"PRINCIPAL_ACTION_{category.value}",
        ),
        taxonomy_result=TaxonomyResult(taxonomy_state=TaxonomyState.TAXONOMY_EVALUATED, event_id="E1"),
    )


class _ScriptedHelper:
    """Answers each request kind with the case's recorded answer."""

    def __init__(self, answers):
        self.answers = answers
        self.kinds: list[str] = []

    def __call__(self, request):
        if isinstance(request, MonitoredStandardRequest):
            self.kinds.append("monitored_standard")
            answer = self.answers["monitored_standard"]
            assert answer != "NOT_CALLED", "the monitored-standard question must not be asked"
            changed = answer["changed_standard"]
            return {
                "event_id": request.event_id,
                "examined_source_refs": list(request.source_refs),
                "changed_standard": changed,
                "lifecycle_action": answer["lifecycle_action"],
                "citations": [] if changed is None else [{"source_ref": "M1", "sentence_ids": answer["sentence_ids"]}],
                "rationale": "scripted answer",
            }
        assert isinstance(request, ReportabilitySemanticRequest)
        self.kinds.append("value_path")
        answer = self.answers["value_path"]
        assert answer != "NOT_CALLED", "the value-path question must not be asked"
        reportable = answer["proposed_state"] == "REPORTABLE"
        return {
            "event_id": request.event_id,
            "proposed_state": answer["proposed_state"],
            "examined_source_refs": list(request.source_refs),
            "support_citations": [{"source_ref": "M1", "sentence_ids": answer["sentence_ids"]}] if reportable else [],
            "rationale": "scripted answer",
            "principal_occurrence": answer["principal_occurrence"],
        }


def _section_of(category_id: str, state: ReportabilityState):
    if state is not ReportabilityState.REPORTABLE:
        return None
    return dict(FORMAL_REPORT_SECTIONS)[CategoryId(category_id)]


@pytest.mark.parametrize("case", GOLDEN["cases"], ids=[case["case_id"] for case in GOLDEN["cases"]])
def test_golden_monitored_standard_outcomes(case):
    helper = _ScriptedHelper(case["helper_answers"])
    result = Reportability(helper).evaluate(_record(case))
    expected = case["expected"]
    assert result.reportability_state.value == expected["reportability"]
    reason = result.reportability_reason.value if result.reportability_reason else None
    assert reason == expected["reportability_reason"]
    marker = re.match(r"\[MONITORED_STANDARD (.+) ([A-Z_]+)\]", result.provenance.rationale)
    assert (marker.groups() if marker else (None, None)) == (expected["monitored_standard"], expected["lifecycle_action"])
    assert _section_of(case["category_id"], result.reportability_state) == expected["report_section"]
    expected_kinds = [kind for kind in ("monitored_standard", "value_path") if case["helper_answers"][kind] != "NOT_CALLED"]
    assert helper.kinds == expected_kinds


def test_the_golden_covers_every_required_scenario():
    by_id = {case["case_id"]: case for case in GOLDEN["cases"]}
    assert by_id["MS01"]["expected"]["report_section"] == SECTION  # monitored revision
    assert by_id["MS02"]["expected"]["lifecycle_action"] == "DRAFT_OR_CONSULTATION"  # monitored draft
    assert by_id["MS03"]["expected"]["report_section"] != SECTION  # procurement citation
    assert by_id["MS04"]["expected"]["reportability"] == "NOT_REPORTABLE"  # mention only
    assert by_id["MS06"]["expected"]["reportability_reason"] == "OUTSIDE_MONITORED_STANDARDS"  # other standard
    assert by_id["MS07"]["expected"]["reportability_reason"] == "OUTSIDE_MONITORED_STANDARDS"  # local ordinance


# --- Failure paths of the monitored-standard answer (mechanism, not Golden) -------------------


def _ms01():
    return next(case for case in GOLDEN["cases"] if case["case_id"] == "MS01")


@pytest.mark.parametrize(
    "mutation",
    [
        {"changed_standard": "IEC 62290-1"},  # not a supplied identifier
        {"changed_standard": "EN 50126"},  # not mentioned, so never supplied
        {"sentence_ids": ["S9"]},  # citation does not resolve
    ],
)
def test_an_invalid_monitored_answer_is_a_disclosed_proposal_violation(mutation):
    case = _ms01()
    answers = json.loads(json.dumps(case["helper_answers"]))
    answers["monitored_standard"].update(mutation)
    with pytest.raises(ReportabilityProposalViolation):
        Reportability(_ScriptedHelper(answers)).evaluate(_record(case))


def test_a_citation_that_does_not_name_the_changed_standard_is_rejected():
    case = dict(_ms01())
    case["source_content"] = "The IEC published a new edition of IEC 61373. The test levels for bogie equipment changed."
    answers = {"monitored_standard": {"changed_standard": "IEC 61373", "lifecycle_action": "NEW_EDITION_OR_REVISION",
                                      "sentence_ids": ["S2"]},
               "value_path": case["helper_answers"]["value_path"]}
    with pytest.raises(ReportabilityProposalViolation):
        Reportability(_ScriptedHelper(answers)).evaluate(_record(case))


def test_a_monitored_change_without_report_value_stays_low_value():
    case = _ms01()
    answers = dict(case["helper_answers"])
    answers["value_path"] = {"proposed_state": "NOT_REPORTABLE", "principal_occurrence": "FEATURE_OR_BACKGROUND",
                             "sentence_ids": []}
    result = Reportability(_ScriptedHelper(answers)).evaluate(_record(case))
    assert result.reportability_reason is ReportabilityReason.LOW_REPORTABILITY_VALUE


# --- The helper request: same task, its own prompt and schema; the old request unchanged ------


def test_the_monitored_question_is_a_separate_request_kind_of_the_same_task():
    case = _ms01()
    record = _record(case)
    members = Reportability._request(record).members
    model_input = build_maiagent_reportability_model_input(MonitoredStandardRequest("E1", members, ("IEC 61373",)))
    assert model_input["task_identity"] == "reportability_semantic_proposal"
    assert (model_input["prompt_version"], model_input["schema_version"]) == (
        MONITORED_STANDARD_PROMPT_VERSION, MONITORED_STANDARD_SCHEMA_VERSION)
    assert model_input["monitored_standard_request"]["monitored_identifiers"] == ["IEC 61373"]
    ordinary = build_maiagent_reportability_model_input(ReportabilitySemanticRequest("E1", members))
    assert (ordinary["prompt_version"], ordinary["schema_version"]) == (
        "reportability-principal-body-v7", "reportability-semantic-proposal-v3") == (PROMPT_VERSION, SCHEMA_VERSION)


# --- Report and Delivery: one weekly report, one message, the same list ---------------------


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


def test_a_monitored_update_appears_in_the_existing_section():
    artifact = _artifact([("E1", "技術新知"), ("E2", "規範變動")])
    email_text, email_html = index_for_artifact(artifact)
    assert [section.category for section in artifact.sections] == ["技術新知", SECTION]
    assert f"【{SECTION}】" in artifact.content and f"【{SECTION}】" in email_text and f"【{SECTION}】" in email_html


def test_a_week_without_monitored_update_omits_the_section_and_keeps_the_report():
    artifact = _artifact([("E1", "技術新知"), ("E2", "事故事件"), ("E3", "採購事件")])
    email_text, email_html = index_for_artifact(artifact)
    assert SECTION not in artifact.content and SECTION not in email_text and SECTION not in email_html
    assert [section.category for section in artifact.sections] == ["技術新知", "事故及安全事件", "機電標案及採購動態"]


def test_the_report_is_one_message_per_recipient_per_week_with_or_without_an_update():
    store, clock = FakeLedgerStore(), Clock()
    sender = FakeSender()
    receipt = service(store, sender, clock, "run1").deliver(_artifact([("E1", "規範變動")]), LIST_ADDRESS)
    assert receipt.status is DeliveryStatus.SENT
    assert sender.opened == [(LIST_ADDRESS,)] and sender.delivered == [LIST_ADDRESS]
    for artifact in (_artifact([("E1", "規範變動")]), _artifact([("E1", "技術新知")])):
        again = FakeSender()
        assert service(store, again, clock, "run2").deliver(artifact, LIST_ADDRESS).status is DeliveryStatus.DUPLICATE
        assert again.attempted == []
    plain, plain_sender = FakeLedgerStore(), FakeSender()
    assert service(plain, plain_sender, Clock(), "run3").deliver(_artifact([("E1", "營運動態")]), LIST_ADDRESS).status \
        is DeliveryStatus.SENT
    assert plain_sender.delivered == [LIST_ADDRESS]


def test_delivery_and_mail_composition_have_no_standards_or_category_branch():
    for name in ("delivery.py", "delivery_ledger.py", "gmail_smtp.py"):
        text = (SRC / name).read_text(encoding="utf-8")
        for token in ("NORMATIVE", "CategoryId", "DiscoveryIntent", "monitored", "規範", "標準"):
            assert token not in text, (name, token)


def test_the_production_adapter_carries_both_request_kinds_end_to_end():
    from src.weekly_report.maiagent_reportability_provider import (
        MaiAgentReportabilityProposalProvider,
        MaiAgentReportabilityProviderConfig,
    )
    from src.weekly_report.maiagent_transport import MaiAgentHttpResponse

    case = _ms01()
    scripted = _ScriptedHelper(case["helper_answers"])
    sent: list[dict] = []

    def transport(endpoint, *, headers, body, timeout_seconds):
        content = json.loads(json.loads(body.decode("utf-8"))["message"]["content"])
        sent.append(content)
        payload = content.get("monitored_standard_request") or content["reportability_request"]
        if "monitored_standard_request" in content:
            request = MonitoredStandardRequest(payload["event_id"], Reportability._request(_record(case)).members,
                                               tuple(payload["monitored_identifiers"]))
        else:
            request = Reportability._request(_record(case))
        answer = json.dumps({"content": json.dumps(scripted(request), ensure_ascii=False)}, ensure_ascii=False)
        return MaiAgentHttpResponse(200, answer.encode("utf-8"))

    config = MaiAgentReportabilityProviderConfig("https://maiagent.example/", "synthetic-secret", "helper-id")
    result = Reportability(MaiAgentReportabilityProposalProvider(config, transport=transport)).evaluate(_record(case))
    assert result.reportability_state is ReportabilityState.REPORTABLE
    assert result.provenance.rationale.startswith("[MONITORED_STANDARD IEC 61373 NEW_EDITION_OR_REVISION]")
    assert [item["prompt_version"] for item in sent] == [MONITORED_STANDARD_PROMPT_VERSION, PROMPT_VERSION]
    assert all(item["task_identity"] == "reportability_semantic_proposal" for item in sent)
