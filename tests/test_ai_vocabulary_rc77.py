"""RC-77 (section A.58, user decision 2026-11-19): AI technology terms in all 17 profiles.

Every profile's ``technology_terms`` gains AI terms. The general maintenance,
remote-monitoring and sensor terms are added only where they did not add a
request beyond the one the AI terms needed (the 32-word query limit). These are
discovery vocabulary only: Search intent is not Category.
"""

from __future__ import annotations

from collections import Counter

from src.weekly_report.contracts import DiscoveryIntent
from src.weekly_report.region_registry import RegionRegistry
from src.weekly_report.search_planner import SearchPlanner, _query_words

# Exactly what RC-77 appended to each profile, in order.
RC77_TECHNOLOGY_TERMS = {
    "en": ["AI", "artificial intelligence", "maintenance", "remote monitoring", "sensor"],
    "zh": ["AI", "人工智慧", "人工智能", "維修", "维修", "遠端監測", "远程监测", "感測器", "传感器"],
    "ja": ["AI", "人工知能", "保守", "遠隔監視"],
    "ko": ["AI", "인공지능"],
    "de": ["KI", "künstliche Intelligenz", "Instandhaltung", "Fernüberwachung", "Sensor"],
    "fr": ["IA", "intelligence artificielle", "maintenance", "télésurveillance", "capteur"],
    "es": ["IA", "inteligencia artificial"],
    "it": ["IA", "intelligenza artificiale", "manutenzione", "monitoraggio remoto", "sensore"],
    "pt": ["IA", "inteligência artificial", "manutenção", "monitorização remota", "sensor"],
    "nl": ["AI", "kunstmatige intelligentie", "onderhoud"],
    "sv": ["AI", "artificiell intelligens", "underhåll", "fjärrövervakning", "sensor"],
    "da": ["AI", "kunstig intelligens", "vedligeholdelse", "fjernovervågning", "sensor"],
    "no": ["KI", "kunstig intelligens", "vedlikehold", "fjernovervåking", "sensor"],
    "fi": ["tekoäly", "AI", "kunnossapito", "etävalvonta", "anturi"],
    "cs": ["AI", "umělá inteligence", "údržba", "dálkový monitoring", "senzor"],
    "pl": ["AI", "sztuczna inteligencja", "utrzymanie", "czujnik"],
    "he": ["AI", "בינה מלאכותית", "תחזוקה", "ניטור מרחוק"],
}
AI_TERMS = {"AI", "IA", "KI", "tekoäly"}

REGISTRY = RegionRegistry.from_file()


def _terms(profile_id: str) -> list[str]:
    return list(REGISTRY.profile(profile_id).intent_vocabulary["technology"]["technology_terms"])


def test_every_profile_ends_with_exactly_its_rc77_terms():
    assert set(RC77_TECHNOLOGY_TERMS) == set(REGISTRY.selected_profile_ids)
    for profile_id, added in RC77_TECHNOLOGY_TERMS.items():
        terms = _terms(profile_id)
        assert terms[-len(added):] == added, profile_id
        assert AI_TERMS & set(added), profile_id
        assert len(terms) == len(set(terms)), profile_id


def test_bare_ai_is_not_used_where_it_is_a_common_word():
    # French "ai" (j'ai) and Italian "ai" (to the) would match ordinary titles.
    assert "AI" not in _terms("fr") and "AI" not in _terms("it")


def test_plan_size_and_query_bound():
    plan = SearchPlanner(REGISTRY).plan("selected")
    counts = Counter(item.intent.value for item in plan.items)
    assert len(plan.items) == 292  # RC-88 zh forms split and 30-word queries (RC-85 239, RC-78 231, RC-77 221)
    assert counts["technology"] == 158  # RC-88: zh forms split and 30-word queries
    assert all(_query_words(item.query) <= 30 for item in plan.items)


def test_every_rc77_term_reaches_every_supported_edition_of_its_profile():
    plan = SearchPlanner(REGISTRY).plan("selected", intents=(DiscoveryIntent.TECHNOLOGY,))
    editions = {(item.market_id, item.language_profile) for item in plan.items
                if item.query_family_id == "urban_rail_or_groups"}
    for market_id, profile_id in editions:
        queries = " ".join(item.query for item in plan.items
                           if (item.market_id, item.language_profile) == (market_id, profile_id))
        for term in RC77_TECHNOLOGY_TERMS[profile_id]:
            assert (f'"{term}"' if " " in term else term) in queries, (market_id, term)
