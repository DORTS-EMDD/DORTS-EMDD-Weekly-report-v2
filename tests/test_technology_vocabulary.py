"""Technology Search vocabulary: the seven approved concepts (search-discovery-v10).

The governed vocabulary is SEARCH_LANGUAGE_PROFILES.md section 5, materialized
into search_configuration.json (parity: scripts.materialize_search_configuration).
These tests read the production RegionRegistry and SearchPlanner only; they add
no vocabulary of their own to production.
"""

from __future__ import annotations

from collections import Counter
from datetime import date

import pytest

from scripts.materialize_search_configuration import validate_configuration
from src.weekly_report.contracts import DiscoveryIntent, MonitoredCheckMonth, SearchProviderId, SearchWindow
from src.weekly_report.region_registry import RegionRegistry
from src.weekly_report.search_planner import SearchPlanner, _query_words

CONCEPTS = ("CBTC", "ATO", "無人駕駛", "第三軌", "道岔", "狀態監測", "預測性維修")

# Per profile, per concept: the governed literal(s) that name it. A literal that
# existed before v10 (for example en "predictive maintenance") counts.
EXPECTED = {
    "en": {"CBTC": ["CBTC"], "ATO": ["automatic train operation"], "無人駕駛": ["driverless train"],
           "第三軌": ["conductor rail"], "道岔": ["switches and crossings", "track switch"],
           "狀態監測": ["condition monitoring"], "預測性維修": ["predictive maintenance"]},
    "zh": {"CBTC": ["CBTC"], "ATO": ["ATO"], "無人駕駛": ["無人駕駛列車/无人驾驶列车"], "第三軌": ["第三軌/第三轨"],
           "道岔": ["道岔"], "狀態監測": ["狀態監測/状态监测"], "預測性維修": ["預測性維修/预测性维修"]},
    "ja": {"CBTC": ["CBTC"], "ATO": ["ATO"], "無人駕駛": ["無人運転"], "第三軌": ["第三軌条"],
           "道岔": ["分岐器"], "狀態監測": ["状態監視"], "預測性維修": ["予知保全"]},
    "ko": {"CBTC": ["CBTC"], "ATO": ["ATO"], "無人駕駛": ["무인운전"], "第三軌": ["제3궤조"],
           "道岔": ["분기기"], "狀態監測": ["상태감시"], "預測性維修": ["예측정비"]},
    "de": {"CBTC": ["CBTC"], "ATO": ["automatisierter Fahrbetrieb"], "無人駕駛": ["fahrerlos"],
           "第三軌": ["Stromschiene"], "道岔": ["Weiche"], "狀態監測": ["Zustandsüberwachung"],
           "預測性維修": ["vorausschauende Instandhaltung"]},
    "fr": {"CBTC": ["CBTC"], "ATO": ["pilotage automatique"], "無人駕駛": ["sans conducteur"],
           "第三軌": ["troisième rail"], "道岔": ["aiguillage"], "狀態監測": ["surveillance conditionnelle"],
           "預測性維修": ["maintenance prédictive"]},
    "es": {"CBTC": ["CBTC"], "ATO": ["conducción automática"], "無人駕駛": ["sin conductor"],
           "第三軌": ["tercer carril"], "道岔": ["cambio de agujas"], "狀態監測": ["monitorización de estado"],
           "預測性維修": ["mantenimiento predictivo"]},
    "it": {"CBTC": ["CBTC"], "ATO": ["guida automatica"], "無人駕駛": ["senza conducente"],
           "第三軌": ["terza rotaia"], "道岔": ["deviatoio"], "狀態監測": ["monitoraggio delle condizioni"],
           "預測性維修": ["manutenzione predittiva"]},
    "pt": {"CBTC": ["CBTC"], "ATO": ["condução automática"], "無人駕駛": ["sem condutor"],
           "第三軌": ["terceiro carril"], "道岔": ["aparelho de mudança de via"],
           "狀態監測": ["monitorização do estado"], "預測性維修": ["manutenção preditiva"]},
    "nl": {"CBTC": ["CBTC"], "ATO": ["automatische treinbesturing"], "無人駕駛": ["zonder bestuurder"],
           "第三軌": ["derde rail"], "道岔": ["wissels"], "狀態監測": ["conditiemonitoring"],
           "預測性維修": ["voorspellend onderhoud"]},
    "sv": {"CBTC": ["CBTC"], "ATO": ["automatisk tågdrift"], "無人駕駛": ["förarlös"],
           "第三軌": ["strömskena"], "道岔": ["spårväxel"], "狀態監測": ["tillståndsövervakning"],
           "預測性維修": ["prediktivt underhåll"]},
    "da": {"CBTC": ["CBTC"], "ATO": ["automatisk togdrift"], "無人駕駛": ["førerløs"],
           "第三軌": ["strømskinne"], "道岔": ["sporskifte"], "狀態監測": ["tilstandsovervågning"],
           "預測性維修": ["prædiktiv vedligeholdelse"]},
    "no": {"CBTC": ["CBTC"], "ATO": ["automatisk togdrift"], "無人駕駛": ["førerløs"],
           "第三軌": ["strømskinne"], "道岔": ["sporveksel"], "狀態監測": ["tilstandsovervåking"],
           "預測性維修": ["prediktivt vedlikehold"]},
}

# search-discovery-v9 technology_terms, in order: every one is kept unchanged.
V9_TECHNOLOGY_TERMS = {
    "en": ["CBTC", "signalling", "communications", "rolling stock", "traction power", "AFC",
           "platform screen doors", "predictive maintenance", "digital twin", "automation"],
    "zh": ["號誌/信号", "通訊", "車輛/车辆", "電聯車", "供電", "自動收費", "月臺門/站台门", "數位孿生/数字孪生", "預測維護/预测维护"],
    "ja": ["信号", "車両", "通信", "電力", "CBTC", "自動運転", "予測保全", "デジタルツイン"],
    "ko": ["신호", "차량", "통신", "전력", "CBTC", "자동운전", "예지정비", "디지털 트윈"],
    "de": ["Signaltechnik", "Fahrzeuge", "Kommunikation", "Energieversorgung", "CBTC", "Zustandsüberwachung", "Digitalisierung"],
    "fr": ["signalisation", "matériel roulant", "communication", "alimentation électrique", "CBTC",
           "maintenance prédictive", "jumeau numérique"],
    "es": ["señalización", "material rodante", "comunicaciones", "energía de tracción", "CBTC",
           "mantenimiento predictivo", "gemelo digital"],
    "it": ["segnalamento", "materiale rotabile", "comunicazioni", "alimentazione", "CBTC",
           "manutenzione predittiva", "gemello digitale"],
    "pt": ["sinalização", "material circulante", "comunicações", "energia de tração", "CBTC",
           "manutenção preditiva", "gémeo digital"],
    "nl": ["seintechniek", "rollend materieel", "communicatie", "tractie-energie", "CBTC",
           "voorspellend onderhoud", "digitale tweeling"],
    "sv": ["signalteknik", "fordon", "kommunikation", "dragkraft", "CBTC", "tillståndsövervakning", "digital tvilling"],
    "da": ["signalteknik", "køretøjer", "kommunikation", "traktionsenergi", "CBTC",
           "tilstandsbaseret vedligehold", "digital tvilling"],
    "no": ["signalteknikk", "kjøretøy", "kommunikasjon", "trekkraft", "CBTC", "tilstandsbasert vedlikehold", "digital tvilling"],
}

WEEK = SearchWindow(date(2026, 11, 16), date(2026, 11, 22))


@pytest.fixture(scope="module")
def registry() -> RegionRegistry:
    return RegionRegistry.from_file()


def _terms(registry, profile_id: str) -> list[str]:
    return list(registry.profile(profile_id).intent_vocabulary["technology"]["technology_terms"])


def _quoted(term: str) -> str:
    return f'"{term}"' if any(character.isspace() for character in term) else term


def test_every_profile_covers_all_seven_concepts(registry):
    assert set(EXPECTED) == {profile.profile_id for profile in registry.profiles}
    for profile_id, concepts in EXPECTED.items():
        assert tuple(concepts) == CONCEPTS, profile_id
        terms = _terms(registry, profile_id)
        for concept, literals in concepts.items():
            for literal in literals:
                assert literal in terms, (profile_id, concept, literal)


def test_every_v9_term_is_kept_in_order_and_only_the_concepts_are_added(registry):
    for profile_id, before in V9_TECHNOLOGY_TERMS.items():
        terms = _terms(registry, profile_id)
        assert terms[: len(before)] == before, profile_id
        added = terms[len(before):]
        approved = {literal for literals in EXPECTED[profile_id].values() for literal in literals}
        assert set(added) <= approved and len(added) == len(set(added)), (profile_id, added)
        assert approved <= set(terms), profile_id
        assert len(terms) == len(set(terms)), profile_id


def test_ambiguous_bare_words_are_not_governed_vocabulary(registry):
    # The en mode words may appear anywhere in an article (not only the title).
    assert not {"driverless", "third rail", "turnout"} & set(_terms(registry, "en"))
    for profile_id in ("en", "es", "it", "pt"):
        assert "ATO" not in _terms(registry, profile_id), profile_id
    assert "無人駕駛/无人驾驶" not in _terms(registry, "zh")
    assert "Weichen" not in _terms(registry, "de")


def test_governed_document_and_materialized_configuration_agree():
    validate_configuration()


def test_every_new_literal_reaches_every_supported_edition_of_its_profile(registry):
    plan = SearchPlanner(registry).plan("selected", intents=(DiscoveryIntent.TECHNOLOGY,), window=WEEK)
    editions = {(item.market_id, item.language_profile) for item in plan.items}
    for market_id, profile_id in editions:
        queries = " ".join(item.query for item in plan.items
                           if (item.market_id, item.language_profile) == (market_id, profile_id))
        for literals in EXPECTED[profile_id].values():
            for literal in literals:
                assert _quoted(literal) in queries, (market_id, profile_id, literal)
    assert all(_query_words(item.query) <= 32 for item in plan.items)
    assert "da" not in {profile for _market, profile in editions}  # Denmark: no Google News edition


@pytest.mark.parametrize("mode", ["selected", "global"])
def test_request_counts(registry, mode):
    weekly = SearchPlanner(registry).plan(mode, window=WEEK)
    counts = Counter(item.intent.value for item in weekly.items)
    # v9: 122 = technology 49 + major_incident 31 + operations 21 + procurement 21.
    assert len(weekly.items) == 140
    assert counts == {"technology": 67, "major_incident": 31, "operations": 21, "procurement": 21}
    november = MonitoredCheckMonth(date(2026, 11, 1), date(2026, 11, 30))
    monthly = SearchPlanner(registry).plan(mode, window=SearchWindow(date(2026, 11, 30), date(2026, 12, 6)),
                                           monitored_check=november)
    monitored = [item for item in monthly.items if item.intent is DiscoveryIntent.MONITORED_STANDARDS
                 and item.provider_target is SearchProviderId.GOOGLE_NEWS_RSS]
    catalogue = [item for item in monthly.items if item.provider_target is SearchProviderId.STANDARDS_CATALOGUE]
    assert len(monitored) == 63 and len(catalogue) == 10
    assert len(monthly.items) == 140 + 63 + 10
