"""RC-58 and RC-59 (contract sections A.42, A.43): monitored standards.

* RC-58: only the V1 list's standards are monitored; only a proven formal
  lifecycle change of one of them is a standards update.
* RC-59: the list is checked once per calendar month, in the weekly report
  whose period contains the month's last day; the check searches that month.
  ScopeClassifier owns the one narrow basis: a proven formal lifecycle change
  of a monitored standard is in scope without an urban-rail tie, and such an
  event is exempt from the region rule. Nothing else changes.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import re
import unicodedata

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
    MonitoredCheckMonth,
    ProposalContractViolation,
    ReportabilityEvidenceProvenance,
    ReportabilityReason,
    ReportabilityResult,
    ReportabilitySemanticRequest,
    ReportabilityState,
    ScopeResult,
    ScopeState,
    SearchAttemptResult,
    SearchProviderId,
    SearchTerminalStatus,
    SearchWindow,
    SourceDateFact,
    TaxonomyResult,
    TaxonomyState,
)
from src.weekly_report.delivery import DeliveryStatus
from src.weekly_report.gmail_smtp import index_for_artifact
from src.weekly_report.maiagent_scope_provider import (
    MONITORED_STANDARD_INSTRUCTIONS,
    MONITORED_STANDARD_PROMPT_VERSION,
    MONITORED_STANDARD_SCHEMA_VERSION,
    PROMPT_VERSION as SCOPE_PROMPT_VERSION,
    build_maiagent_scope_model_input,
)
from src.weekly_report.monitored_standards import (
    MonitoredStandards,
    load_monitored_standards_data,
    monitored_check_month,
    monitored_standards,
)
from src.weekly_report.production_runner import default_period
from src.weekly_report.region_registry import RegionRegistry
from src.weekly_report.report_service import FORMAL_REPORT_SECTIONS, ReportService
from src.weekly_report.reportability import Reportability
from src.weekly_report.scope_classifier import MonitoredStandardScopeRequest, ScopeClassifier, ScopeSemanticRequest
from src.weekly_report.search_executor import SearchExecutor
from src.weekly_report.search_planner import SearchPlanner, _query_words
from src.weekly_report.temporal_rule import TemporalRule
from src.weekly_report.validator import ValidatedReportEvent, ValidationResult
from src.weekly_report.writer import WriterReportBlock
from tests.delivery_fakes import PERIOD, Clock, FakeLedgerStore, FakeSender, service
from tests.test_golden_contract import GOLDEN as GOLDEN_DIR, _materialize_ordering_case
from tests.test_report_service import _workflow_result
from tests.test_scope_classifier import _mechanical_schema_proposal

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "weekly_report"
GOLDEN = json.loads((ROOT / "golden" / "monitored_standards_cases.json").read_text(encoding="utf-8"))
SECTION = "規範及標準動態"
LIST_ADDRESS = "weekly-list@example.test"
TAIPEI = timezone(timedelta(hours=8))

V1_LIST = {
    "碰撞/出軌類": ["EN 50126", "EN 50128", "EN 50129", "IEEE 1474.1", "EN 13674-1", "UIC 860-0", "IEC 61373"],
    "觸電/電弧爆炸類": ["EN 50122", "EN 50122-2", "EN 50327", "EN 50328", "EN 50329", "IEC 62271-100",
                    "IEC 62271-102", "IEC 60947-1", "IEC 60850"],
    "火災/中毒類": ["NFPA 130", "ASTM E119", "IEC 60754-1", "IEC 60754-2", "IEC 60332-1", "ASTM E662", "NFPA 258",
                "NFPA 70"],
    "結構性/爆炸性設備失效類": ["IEC 60076", "IEC 60076-11", "IEC 62695"],
}
NOVEMBER = MonitoredCheckMonth(date(2026, 11, 1), date(2026, 11, 30))


# --- The monitored list: one data file, the exact V1 literal (RC-58) ------------------------


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
        # RC-62 (section A.46): ownership is exact; numbering alone never makes a part monitored.
        ("CENELEC published EN 50126-1:2025", ()),
        ("BS EN 50122-2:2010 amendment A1", ("EN 50122-2",)),
        ("EN 50122-2:2010/A1:2026", ("EN 50122-2",)),
        ("IEC 60076-11:2018", ("IEC 60076-11",)),
        ("IEC 60076-5:2026", ()),
        ("IEC 60332-1-2:2025", ()),
        ("IEC 62271-100:2021+AMD1", ("IEC 62271-100",)),
        ("ASTM E662-21ae01", ("ASTM E662",)),
        ("UIC 860-0", ("UIC 860-0",)),
        ("UIC 860", ()),
        # User decision (section A.46): a final -YYYY may be the edition year; the explicit publication comes first.
        ("IEC 61373-2010", ("IEC 61373",)),
        ("EN 50129-2018", ("EN 50129",)),
        ("IEC 60076-11-2018", ("IEC 60076-11",)),
        ("EN 50122-2-2022/A1", ("EN 50122-2",)),
        ("EN 50126-1-2017", ()),  # the year is removed; the part still needs its own owner
        ("IEC 61373-2100", ("IEC 61373",)),  # no date range is set
        ("UIC 860-0-2010", ("UIC 860-0",)),  # no body condition is set
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


def _with_families(families):
    data = json.loads(json.dumps(load_monitored_standards_data()))
    data["family_coverage"] = {"note": "test", "families": families}
    return MonitoredStandards(data)


def test_no_family_is_defined_until_the_user_decides_its_coverage():
    data = load_monitored_standards_data()
    assert data["family_coverage"]["families"] == {}
    assert monitored_standards().family_coverage == {}


# Parts the issuing bodies publish under the four series entries. Under D1
# (section A.46) structure, numbering and splits are not coverage, and no
# family is defined, so none of these parts is monitored.
UNCOVERED_SERIES_PARTS = {
    "IEC 60076": ("IEC 60076-1:2011", "IEC 60076-2:2011", "IEC 60076-5:2006", "IEC 60076-7:2018", "IEC 60076-16:2018"),
    "IEC 60332-1": ("IEC 60332-1-1:2004", "IEC 60332-1-2:2025", "IEC 60332-1-3:2004"),
    "EN 50122": ("EN 50122-1:2022", "EN 50122-3:2022"),
    "EN 50126": ("EN 50126-1:2017", "EN 50126-2:2017/A1:2024"),
}


@pytest.mark.parametrize("family", sorted(UNCOVERED_SERIES_PARTS))
def test_the_four_series_families_stay_fail_closed_until_their_coverage_is_decided(family):
    standards = monitored_standards()
    assert family not in standards.family_coverage
    for part in UNCOVERED_SERIES_PARTS[family]:
        assert standards.identifiers_in(f"The body published {part}.") == (), part
    assert standards.identifiers_in(f"The body published {family}.") == (family,)
    assert standards.identifiers_in("IEC 60076-11:2018") == ("IEC 60076-11",)
    assert standards.identifiers_in("EN 50122-2:2022") == ("EN 50122-2",)


def test_a_configured_family_part_is_owned_by_its_parent_and_nothing_else_is():
    standards = _with_families({"IEC 60076": ["IEC 60076-5"]})
    assert standards.identifiers_in("IEC published IEC 60076-5:2026") == ("IEC 60076",)
    assert standards.identifiers_in("IEC 60076-11:2018 Amendment 1") == ("IEC 60076-11",)
    assert standards.identifiers_in("IEC 60076-2:2026") == ()


@pytest.mark.parametrize(
    "families",
    [
        {"IEC 60076": ["IEC 60076-11"]},  # an explicit child owns itself
        {"EN 50122": ["EN 50122-2"]},
        {"IEC 60076": ["IEC 60076-5"], "IEC 60076-11": ["IEC 60076-5"]},  # owned twice
        {"IEC 60076": ["IEC 60076-5", "IEC 60076-5"]},  # listed twice in one family
        {"IEC 60076": ["IEC 60076"]},  # the parent itself
        {"IEC 60077": ["IEC 60077-1"]},  # parent not listed
        {"IEEE 1474.1": ["IEEE 1474-2"]},  # cannot be located as itself, so never owned
        {"IEC 60076": ["IEC60076-5"]},  # malformed
    ],
)
def test_family_coverage_rejects_any_second_owner_or_derived_part(families):
    with pytest.raises(ValueError):
        _with_families(families)


def test_family_membership_is_whatever_the_configuration_defines():
    # D1 sets no numbering or body condition on a family: only single, explicit ownership.
    standards = _with_families({"IEEE 1474.1": ["IEEE 1474.3"], "IEC 60076": ["IEC 61378-1"]})
    assert standards.identifiers_in("IEEE Std 1474.3-2008") == ("IEEE 1474.1",)
    assert standards.identifiers_in("IEC 61378-1:2011") == ("IEC 60076",)


# The pre-RC-62 matcher (RC-58, contract section A.42), kept here only as the
# reference for recall: every form it accepted for an identifier itself, other
# than a further numbered part, must still resolve to that identifier.
def _pre_rc62_pattern(identifier):
    prefix, letter, number = re.match(r"^([A-Z]{2,5}) ([A-Z]?)(\d+(?:\.\d+)?(?:-\d+)*)$", identifier).groups()
    number_pattern = re.escape(letter) + r"\s?" + re.escape(number) if letter else re.escape(number)
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(prefix) + r"(?:\s*Std\.?)?[\s-]*" + number_pattern
                      + r"(?![0-9A-Za-z])(?!\.[0-9])")


EDITION_SUFFIXES = ("", ":2026", ":2010/COR1:2011", ":2010/A1:2026", ":2021+AMD1:2024 CSV", "/AC:2019",
                    "-2010", "-2026", " Ed. 3", " (2026)", " edition 2026", "\u00ae", ", 2026")


def test_every_identifier_keeps_its_pre_rc62_recall_for_edition_and_year_forms():
    standards = monitored_standards()
    checked = 0
    for identifier in standards.identifiers:
        written = [identifier, unicodedata.normalize("NFKC", identifier)]
        if identifier.startswith("IEEE "):
            written.append(identifier.replace("IEEE ", "IEEE Std "))
        if identifier.startswith("ASTM E"):
            written.append(identifier.replace("ASTM E", "ASTM E "))
        for form in written:
            for suffix in EDITION_SUFFIXES:
                text = f"The publication {form}{suffix} was issued."
                assert _pre_rc62_pattern(identifier).search(text), text  # a form the old matcher accepted
                assert identifier in standards.identifiers_in(text), text
                checked += 1
    assert checked >= 27 * len(EDITION_SUFFIXES)


def test_a_configured_publication_ending_in_a_year_shaped_segment_keeps_its_number():
    standards = _with_families({"IEC 60076": ["IEC 60076-2010"]})
    assert standards.identifiers_in("IEC 60076-2010") == ("IEC 60076",)
    assert standards.identifiers_in("IEC 61373-2010") == ("IEC 61373",)


def test_a_listed_identifier_that_cannot_be_located_as_itself_fails_closed():
    data = json.loads(json.dumps(load_monitored_standards_data()))
    data["groups"][0]["standards"].append("IEEE 1474-2")
    data.pop("catalogue_records")
    with pytest.raises(ValueError):
        MonitoredStandards(data)


def test_the_monitored_question_never_offers_a_parent_for_an_explicit_child():
    evidence = _evidence(_ms("MS16"))
    assert monitored_standards().identifiers_in(evidence.substantive_content) == ("EN 50122-2",)


def test_only_the_list_module_holds_identifiers_and_only_scope_judges_them():
    users = sorted(path.name for path in SRC.glob("*.py") if "identifiers_in(" in path.read_text(encoding="utf-8"))
    assert users == ["monitored_standards.py", "scope_classifier.py"]
    for path in SRC.glob("*.py"):
        if path.name == "monitored_standards.py":
            continue
        text = path.read_text(encoding="utf-8")
        for identifier in ("EN 50126", "NFPA 130", "IEC 60076", "ASTM E119"):
            assert identifier not in text, (path.name, identifier)


# --- RC-59 cadence: once per calendar month, decided by the report period ------------------


def _weeks(first_monday: date, count: int):
    return [(first_monday + timedelta(days=7 * i), first_monday + timedelta(days=7 * i + 6)) for i in range(count)]


def test_consecutive_weekly_runs_check_the_standards_only_in_the_month_end_week():
    weeks = _weeks(date(2026, 11, 2), 9)  # 2026-11-02 .. 2027-01-03
    checks = {week: monitored_check_month(*week) for week in weeks}
    assert [week for week, check in checks.items() if check] == [
        (date(2026, 11, 30), date(2026, 12, 6)),
        (date(2026, 12, 28), date(2027, 1, 3)),
    ]
    assert checks[(date(2026, 11, 30), date(2026, 12, 6))] == NOVEMBER
    assert checks[(date(2026, 12, 28), date(2027, 1, 3))] == MonitoredCheckMonth(date(2026, 12, 1), date(2026, 12, 31))


def test_every_calendar_month_is_checked_exactly_once_with_no_gap_or_overlap():
    weeks = _weeks(date(2026, 12, 28), 60)
    months = [check for check in (monitored_check_month(*week) for week in weeks) if check]
    assert [check.label for check in months] == [f"{2026 + (11 + i) // 12}-{(11 + i) % 12 + 1:02d}" for i in range(len(months))]
    for earlier, later in zip(months, months[1:]):
        assert later.start == earlier.end + timedelta(days=1)
    # A month ending on a Sunday is checked by the week ending that day.
    assert monitored_check_month(date(2027, 2, 22), date(2027, 2, 28)) == MonitoredCheckMonth(date(2027, 2, 1), date(2027, 2, 28))


@pytest.mark.parametrize(
    "run_instant",
    [
        datetime(2026, 12, 7, 6, 30, tzinfo=TAIPEI),  # the scheduled run
        datetime(2026, 12, 7, 13, 11, tzinfo=TAIPEI),  # a six-hour GitHub delay
        datetime(2026, 12, 9, 10, 0, tzinfo=TAIPEI),  # a manual rerun two days later
        datetime(2026, 12, 13, 23, 59, tzinfo=TAIPEI),  # the last minute of that week
    ],
)
def test_delayed_and_repeated_runs_of_one_period_get_the_same_monthly_answer(run_instant):
    period = default_period(run_instant)
    assert period == (date(2026, 11, 30), date(2026, 12, 6))
    assert monitored_check_month(*period) == NOVEMBER


def test_the_next_week_after_a_check_does_not_check_again():
    period = default_period(datetime(2026, 12, 14, 6, 30, tzinfo=TAIPEI))
    assert period == (date(2026, 12, 7), date(2026, 12, 13)) and monitored_check_month(*period) is None


# --- Search: the identifier lane exists only in the monthly check -------------------------


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


def test_a_weekly_plan_has_no_monitored_standard_request(registry):
    week = SearchWindow(date(2026, 11, 16), date(2026, 11, 22))
    plan = SearchPlanner(registry).plan("selected", window=week)
    assert len(plan.items) == 140  # search-discovery-v10 technology vocabulary
    assert all(item.intent is not DiscoveryIntent.MONITORED_STANDARDS for item in plan.items)
    with pytest.raises(ValueError):
        SearchPlanner(registry).plan("selected", intents=(DiscoveryIntent.MONITORED_STANDARDS,), window=week)


@pytest.mark.parametrize("mode", ["selected", "global"])
def test_the_monthly_plan_searches_every_identifier_over_the_whole_month(registry, mode):
    week = SearchWindow(date(2026, 11, 30), date(2026, 12, 6))
    plan = SearchPlanner(registry).plan(mode, window=week, monitored_check=NOVEMBER)
    markets = registry.selected_markets if mode == "selected" else registry.markets_for(mode)
    monitored = [item for item in plan.items if item.intent is DiscoveryIntent.MONITORED_STANDARDS
                 and item.provider_target is SearchProviderId.GOOGLE_NEWS_RSS]
    catalogue = [item for item in plan.items if item.provider_target is SearchProviderId.STANDARDS_CATALOGUE]
    others = [item for item in plan.items if item.intent is not DiscoveryIntent.MONITORED_STANDARDS]
    assert len(others) == 140 and len(monitored) == 63 and len(catalogue) == 10  # RC-60: one per configured record
    assert {(item.market_id, item.language_profile) for item in monitored} == _supported(registry, markets)
    assert {item.search_window for item in monitored} == {SearchWindow(date(2026, 11, 1), date(2026, 11, 30))}
    assert {item.search_window for item in others} == {week}
    identifiers = set(monitored_standards().identifiers)
    for edition in _supported(registry, markets):
        queries = [item.query for item in monitored if (item.market_id, item.language_profile) == edition]
        terms = {term.strip('"') for query in queries for term in re.findall(r'"[^"]+"|[^\s()]+', query) if term != "OR"}
        assert terms == identifiers, edition
    assert all(_query_words(item.query) <= 32 for item in monitored)


def test_a_rerun_of_the_same_period_freezes_the_same_plan(registry):
    week = SearchWindow(date(2026, 11, 30), date(2026, 12, 6))
    first = SearchPlanner(registry).plan("selected", window=week, monitored_check=monitored_check_month(week.start, week.end))
    again = SearchPlanner(registry).plan("selected", window=week, monitored_check=monitored_check_month(week.start, week.end))
    assert first.plan_id == again.plan_id


def test_every_monthly_request_is_planned_and_attempted_once(registry):
    calls: list[str] = []

    class _ZeroResults:
        def execute(self, item):
            calls.append(item.plan_item_id)
            return SearchAttemptResult(item.plan_item_id, SearchTerminalStatus.SUCCESS_ZERO_RESULTS)

    plan = SearchPlanner(registry).plan("selected", window=SearchWindow(date(2026, 11, 30), date(2026, 12, 6)),
                                        monitored_check=NOVEMBER)
    result = SearchExecutor({SearchProviderId.GOOGLE_NEWS_RSS: _ZeroResults(),
                             SearchProviderId.STANDARDS_CATALOGUE: _ZeroResults()}).execute(plan)
    assert result.execution_complete and not result.unattempted_items
    assert sorted(calls) == sorted(item.plan_item_id for item in plan.items)


def test_the_search_configuration_identifiers_are_a_materialized_copy_of_the_list(registry):
    identifiers = monitored_standards().identifiers
    for profile in registry.profiles:
        assert dict(profile.intent_vocabulary["monitored_standards"]) == {"monitored_standard_ids": identifiers}
    language = (ROOT / "docs" / "SEARCH_LANGUAGE_PROFILES.md").read_text(encoding="utf-8")
    assert language.count("`monitored_standard_ids=@monitored_standards`") == 13


def test_report_application_derives_the_check_from_the_period_and_passes_it_on():
    from tests.test_report_application import FixturePlanner, FixtureReportApplication, RecordingEvidenceService, _fixture_plan, _registry

    seen: list[object] = []

    class RecordingPlanner(FixturePlanner):
        def plan(self, mode, intents=None, *, window=None, monitored_check=None):
            seen.append(monitored_check)
            return super().plan(mode, intents, window=window, monitored_check=monitored_check)

    class _Zero:
        def execute(self, item):
            return SearchAttemptResult(item.plan_item_id, SearchTerminalStatus.SUCCESS_ZERO_RESULTS)

    registry = _registry()
    app = FixtureReportApplication(
        registry, RecordingPlanner(registry, _fixture_plan()), SearchExecutor({SearchProviderId.GOOGLE_NEWS_RSS: _Zero()}),
        None, RecordingEvidenceService(),
    )
    app.run("selected", period_start=date(2026, 11, 30), period_end=date(2026, 12, 6))
    app.run("selected", period_start=date(2026, 11, 16), period_end=date(2026, 11, 22))
    assert seen == [NOVEMBER, None]


def test_discovery_intent_is_read_only_by_normalization_and_the_audit_projection():
    readers = sorted(
        path.name
        for path in SRC.glob("*.py")
        if "discovery_intent" in path.read_text(encoding="utf-8")
        and path.name not in {"contracts.py", "region_registry.py"}
    )
    assert readers == ["candidate_normalizer.py", "selection_audit.py"]


# --- Golden: Scope, Temporal and Reportability through the production owners ---------------


class _ScopeHelper:
    def __init__(self, answers):
        self.answers = answers
        self.kinds: list[str] = []

    def __call__(self, request):
        if isinstance(request, MonitoredStandardScopeRequest):
            self.kinds.append("monitored_standard")
            answer = self.answers["monitored_standard"]
            assert answer != "NOT_CALLED", "the monitored-standard question must not be asked"
            return {"candidate_id": request.candidate_id, "changed_standard": answer["changed_standard"],
                    "lifecycle_action": answer["lifecycle_action"], "sentence_ids": answer["sentence_ids"],
                    "rationale": "scripted answer"}
        assert isinstance(request, ScopeSemanticRequest)
        self.kinds.append("ordinary_scope")
        answer = self.answers["ordinary_scope"]
        assert answer != "NOT_CALLED", "the ordinary Scope question must not be asked"
        if answer == "IN_SCOPE":
            return _mechanical_schema_proposal(request)
        return _mechanical_schema_proposal(request, decision="OUT_OF_SCOPE_SUPPORT", mode="NON_ELIGIBLE", kind="NON_URBAN_RAIL")


class _ValuePathHelper:
    def __init__(self, answer):
        self.answer = answer
        self.calls = 0

    def __call__(self, request):
        assert isinstance(request, ReportabilitySemanticRequest)
        assert self.answer != "NOT_CALLED", "the value-path question must not be asked"
        self.calls += 1
        reportable = self.answer["proposed_state"] == "REPORTABLE"
        return {
            "event_id": request.event_id,
            "proposed_state": self.answer["proposed_state"],
            "examined_source_refs": list(request.source_refs),
            "support_citations": [{"source_ref": "M1", "sentence_ids": self.answer["sentence_ids"]}] if reportable else [],
            "rationale": "scripted answer",
            "principal_occurrence": self.answer["principal_occurrence"],
        }


def _evidence(case) -> EvidenceResult:
    return EvidenceResult(
        candidate_id="C1",
        state=EvidenceState.READY,
        canonical_source_url="https://fixtures.invalid/C1",
        source_type="authoritative",
        substantive_content=case["source_content"],
        source_date_facts=(SourceDateFact(f"{case['source_date']}T08:00:00Z", "ORIGINAL_PUBLICATION", "C1",
                                          "fixture.publication_date", "Z"),),
    )


def _record(case, evidence, scope, temporal) -> EventDecisionRecord:
    member = EventIdentityRecord(CanonicalCandidate("C1", "Title", evidence.canonical_source_url), evidence, scope, temporal)
    category = CategoryId(case["category_id"])
    return EventDecisionRecord(
        event_group=EventGroup("E1", ("C1",), "C1", identity_basis=()),
        member_records=(member,),
        category_result=CategoryResult(category_state=CategoryState.CATEGORY_ASSIGNED, event_id="E1",
                                       primary_category_id=category, primary_category=category.display_label,
                                       classification_reason=f"PRINCIPAL_ACTION_{category.value}"),
        taxonomy_result=TaxonomyResult(taxonomy_state=TaxonomyState.TAXONOMY_EVALUATED, event_id="E1"),
    )


def _run(case):
    period = tuple(date.fromisoformat(value) for value in case["report_period"])
    evidence = _evidence(case)
    scope_helper = _ScopeHelper(case["helper_answers"])
    scope = ScopeClassifier(scope_helper).classify(evidence, candidate_title="Title",
                                                   monitored_check=monitored_check_month(*period))
    outcome = {"scope": scope.state.value, "scope_basis": None, "date_valid": None, "monitored_standard": None,
               "reportability": None, "reportability_reason": None, "report_section": None}
    if scope.state is ScopeState.IN_SCOPE:
        outcome["scope_basis"] = "MONITORED_STANDARD" if scope.monitored_standard else "URBAN_RAIL"
        temporal = TemporalRule().evaluate("C1", evidence.source_date_facts, *period, source_type="authoritative",
                                           scope_result=scope)
        outcome["date_valid"] = temporal.date_valid
        if temporal.date_valid:
            value_helper = _ValuePathHelper(case["helper_answers"]["value_path"])
            result = Reportability(value_helper).evaluate(_record(case, evidence, scope, temporal))
            outcome["reportability"] = result.reportability_state.value
            outcome["reportability_reason"] = result.reportability_reason.value if result.reportability_reason else None
            outcome["monitored_standard"] = result.monitored_standard
            if result.reportability_state is ReportabilityState.REPORTABLE:
                outcome["report_section"] = dict(FORMAL_REPORT_SECTIONS)[CategoryId(case["category_id"])]
            assert value_helper.calls == (0 if case["helper_answers"]["value_path"] == "NOT_CALLED" else 1)
    expected_kinds = [kind for kind in ("monitored_standard", "ordinary_scope") if case["helper_answers"][kind] != "NOT_CALLED"]
    assert scope_helper.kinds == expected_kinds
    return outcome


@pytest.mark.parametrize("case", GOLDEN["cases"], ids=[case["case_id"] for case in GOLDEN["cases"]])
def test_golden_monitored_standard_outcomes(case):
    assert _run(case) == case["expected"]


def test_the_golden_covers_every_required_scenario():
    by_id = {case["case_id"]: case for case in GOLDEN["cases"]}
    assert by_id["MS10"]["expected"]["scope_basis"] == "MONITORED_STANDARD"  # no metro wording (criterion 6)
    assert "metro" not in by_id["MS10"]["source_content"].lower()
    assert by_id["MS16"]["expected"]["report_section"] == SECTION  # issuing body outside the 20 regions (criterion 7)
    assert "Brussels" in by_id["MS16"]["source_content"]
    # RC-61 (section A.45): only the identified standard's own issuing body changes it.
    # RC-62 (section A.46): each family without defined coverage stays fail-closed.
    for case_id, family in (("MS19", "IEC 60076"), ("MS20", "IEC 60332-1"), ("MS21", "EN 50126"), ("MS22", "EN 50122")):
        assert family not in monitored_standards().family_coverage, case_id
        assert by_id[case_id]["expected"]["monitored_standard"] is None, case_id
        assert by_id[case_id]["helper_answers"]["monitored_standard"] == "NOT_CALLED", case_id
    for case_id in ("MS09", "MS11", "MS17", "MS18"):  # national, regional and other-body adoptions
        assert by_id[case_id]["expected"]["monitored_standard"] is None, case_id
        assert by_id[case_id]["expected"]["report_section"] is None, case_id
    assert by_id["MS06"]["expected"]["reportability_reason"] == "OUTSIDE_MONITORED_STANDARDS"  # other standard (8)
    assert by_id["MS15"]["expected"]["scope"] == "OUT_OF_SCOPE"  # ordinance cannot use the basis (9)
    assert by_id["MS14"]["expected"]["scope"] == "OUT_OF_SCOPE"  # mention only, no urban rail (10)
    assert by_id["MS12"]["expected"]["scope"] == "OUT_OF_SCOPE"  # no check in an ordinary week (1)
    assert by_id["MS13"]["expected"]["date_valid"] is False  # next month's change waits for its check (3)


# --- Failure paths of the monitored answer (mechanism, not Golden) --------------------------


def _ms(case_id):
    return next(case for case in GOLDEN["cases"] if case["case_id"] == case_id)


@pytest.mark.parametrize(
    "mutation",
    [
        {"changed_standard": "IEC 62290-1"},  # not supplied
        {"changed_standard": "EN 50126"},  # not mentioned, so never supplied
        {"sentence_ids": ["S9"]},  # does not resolve
        {"sentence_ids": []},  # no citation
        {"lifecycle_action": "REVIEWED"},  # not a lifecycle action
    ],
)
def test_an_invalid_monitored_answer_is_a_disclosed_proposal_violation(mutation):
    case = json.loads(json.dumps(_ms("MS10")))
    case["helper_answers"]["monitored_standard"].update(mutation)
    with pytest.raises(ProposalContractViolation):
        _run(case)


def test_a_citation_that_does_not_name_the_changed_standard_is_rejected():
    case = json.loads(json.dumps(_ms("MS10")))
    case["source_content"] = "The NFPA Standards Council issued an amendment to NFPA 70. It revises ground-fault protection."
    case["helper_answers"]["monitored_standard"]["sentence_ids"] = ["S2"]
    with pytest.raises(ProposalContractViolation):
        _run(case)


def test_a_monitored_basis_never_licenses_another_category():
    case = json.loads(json.dumps(_ms("MS10")))
    case["category_id"] = "OPERATIONAL_CHANGE"
    case["helper_answers"]["value_path"] = "NOT_CALLED"
    outcome = _run(case)
    assert (outcome["reportability"], outcome["reportability_reason"]) == ("NOT_REPORTABLE", "OUTSIDE_MONITORED_STANDARDS")


def test_a_monitored_change_without_report_value_stays_low_value():
    case = json.loads(json.dumps(_ms("MS01")))
    case["helper_answers"]["value_path"] = {"proposed_state": "NOT_REPORTABLE", "principal_occurrence": "FEATURE_OR_BACKGROUND", "sentence_ids": []}
    assert _run(case)["reportability_reason"] == "LOW_REPORTABILITY_VALUE"


def test_contracts_keep_the_basis_narrow():
    change = ScopeClassifier(_ScopeHelper(_ms("MS10")["helper_answers"])).classify(
        _evidence(_ms("MS10")), monitored_check=NOVEMBER).monitored_standard
    with pytest.raises(ValueError):
        ScopeResult("C1", ScopeState.OUT_OF_SCOPE, monitored_standard=change)
    with pytest.raises(ValueError):
        ReportabilityResult("E1", ReportabilityState.NOT_REPORTABLE, ReportabilityReason.LOW_REPORTABILITY_VALUE,
                            ReportabilityEvidenceProvenance(("C1",), (), "x"), monitored_standard="NFPA 70")
    with pytest.raises(ValueError):
        MonitoredCheckMonth(date(2026, 11, 2), date(2026, 11, 30))


def test_the_monitored_question_is_a_second_request_kind_of_the_scope_task():
    request = MonitoredStandardScopeRequest("C1", _ms("MS10")["source_content"], ("NFPA 70",))
    model_input = build_maiagent_scope_model_input(request)
    assert model_input["task_identity"] == "scope_semantic_proposal"
    assert (model_input["prompt_version"], model_input["schema_version"]) == (
        MONITORED_STANDARD_PROMPT_VERSION, MONITORED_STANDARD_SCHEMA_VERSION)
    assert model_input["monitored_standard_request"]["monitored_identifiers"] == ["NFPA 70"]
    assert "monitored_identifiers" not in json.dumps(build_maiagent_scope_model_input(
        ScopeSemanticRequest("C1", "Title", "A metro line opened.", {})))
    assert SCOPE_PROMPT_VERSION == "scope-event-target-system-v12"


def test_only_the_issuing_body_changes_a_monitored_standard():
    # RC-61 (section A.45): a national or regional adoption by another body is not a change.
    assert MONITORED_STANDARD_PROMPT_VERSION == "scope-monitored-standard-v2"
    text = " ".join(MONITORED_STANDARD_INSTRUCTIONS)
    assert "national adoption" in text and "regional adoption" in text and "is not a change of it" in text
    assert "including its formal national adoption" not in text
    assert "or by a body formally adopting it" not in text
    assert "body that issues the identified standard itself" in text


# --- RC-28: the region rule is lifted only for a reported monitored update ------------------


def _region_case(name):
    return _materialize_ordering_case(json.loads((GOLDEN_DIR / "cases" / name).read_text(encoding="utf-8")))


def _as_monitored(results):
    out = []
    for result in results:
        rr = result.reportability_result
        out.append(replace(result, reportability_result=replace(rr, monitored_standard="NFPA 70")))
    return tuple(out)


@pytest.mark.parametrize("name", ["region_non_designated_event.json", "region_not_stated_event.json", "region_unresolved_event.json"])
def test_a_monitored_update_is_not_excluded_by_the_region_rule_and_nothing_else_is(name, registry):
    service_ = ReportService(formal_region_ids=registry.formal_region_ids)
    ordinary = service_.project_formal_metadata_population(_region_case(name))
    assert not ordinary.metadata and ordinary.exclusions
    monitored = service_.project_formal_metadata_population(_as_monitored(_region_case(name)))
    assert len(monitored.metadata) == len(ordinary.exclusions) and not monitored.exclusions


# --- Report and Delivery: the one weekly report, one message, the same list -----------------


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


def test_a_monitored_update_appears_in_the_existing_section_of_the_weekly_report():
    artifact = _artifact([("E1", "技術新知"), ("E2", "規範變動")])
    email_text, email_html = index_for_artifact(artifact)
    assert [section.category for section in artifact.sections] == ["技術新知", SECTION]
    assert f"【{SECTION}】" in artifact.content and f"【{SECTION}】" in email_text and f"【{SECTION}】" in email_html


def test_without_a_monitored_update_the_section_is_omitted_and_the_report_stays():
    artifact = _artifact([("E1", "技術新知"), ("E2", "事故事件"), ("E3", "採購事件")])
    email_text, email_html = index_for_artifact(artifact)
    assert SECTION not in artifact.content and SECTION not in email_text and SECTION not in email_html
    assert [section.category for section in artifact.sections] == ["技術新知", "事故及安全事件", "機電標案及採購動態"]


def test_one_message_per_recipient_per_week_with_or_without_an_update():
    store, clock, sender = FakeLedgerStore(), Clock(), FakeSender()
    assert service(store, sender, clock, "run1").deliver(_artifact([("E1", "規範變動")]), LIST_ADDRESS).status \
        is DeliveryStatus.SENT
    assert sender.opened == [(LIST_ADDRESS,)] and sender.delivered == [LIST_ADDRESS]
    for artifact in (_artifact([("E1", "規範變動")]), _artifact([("E1", "技術新知")])):
        again = FakeSender()
        assert service(store, again, clock, "run2").deliver(artifact, LIST_ADDRESS).status is DeliveryStatus.DUPLICATE
        assert again.attempted == []
    plain, plain_sender = FakeLedgerStore(), FakeSender()
    assert service(plain, plain_sender, Clock(), "run3").deliver(_artifact([("E1", "營運動態")]), LIST_ADDRESS).status \
        is DeliveryStatus.SENT
    assert plain_sender.delivered == [LIST_ADDRESS]


def test_delivery_schedule_and_mail_have_no_standards_branch():
    for name in ("delivery.py", "delivery_ledger.py", "gmail_smtp.py"):
        text = (SRC / name).read_text(encoding="utf-8")
        for token in ("NORMATIVE", "CategoryId", "DiscoveryIntent", "monitored", "規範", "標準"):
            assert token not in text, (name, token)
    workflow = (ROOT / ".github" / "workflows" / "weekly-report.yml").read_text(encoding="utf-8")
    assert workflow.count("cron:") == 1 and "monitored" not in workflow
