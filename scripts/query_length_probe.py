"""Observation-only probe: how many query words does Google News RSS keep? (no MaiAgent calls)

RC-88 (external review item 2, user decision 2026-11-26). Run 45645553592
and Run 45727969072 showed that Google News drops trailing query words: with
the ``after:``/``before:`` operators last, a planned query of 30 or 32 words
was answered without the date limit. This probe measures, per language, where
the limit lies in SearchPlanner's word count, using the planner's own terms:

* ``LIMIT`` (dates last). The planned query is cut to *k* terms of its second
  group and sent with the date operators last, for the past week
  2026-11-09..11-15. If every returned item is inside the week (one day of
  slack for time zones) the trailing dates were kept; any item outside it
  means they were dropped. A binary search over *k* finds the largest planned
  length whose trailing dates are kept (``kept``) and the smallest that drops
  them (``dropped``).
* ``TAIL`` (dates first). With the dates first, a term that occurs only in
  particular news of that week (the sentinel) is the last OR term of the
  query, at the proposed planner limit (``kept`` minus 2) and, as a control,
  past the measured limit. The probe counts how many returned titles contain
  the sentinel: present at the proposed limit means the last OR term is still
  used there; absent past the limit shows the test can see a dropped term.

Languages: en, ja, ko, zh with Traditional terms only, zh with Simplified
terms only (Chinese, Japanese and Korean are written without spaces, so
Google may count their words differently). The zh forms are told apart by
encoding: a Traditional form is not encodable in GB2312, a Simplified form is
not encodable in Big5; a term encodable in both belongs to both.

About 25 requests, 2 seconds apart. It prints counts, dates and word counts
only, never titles, and decides nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta, timezone
from email.utils import parsedate_to_datetime
import re
import sys
import time
from urllib.parse import urlencode

from src.weekly_report import google_news_rss_provider as rss
from src.weekly_report.contracts import SearchWindow
from src.weekly_report.region_registry import RegionRegistry
from src.weekly_report.search_planner import SearchPlanner, _query_words

LIMIT_WINDOW = (date(2026, 11, 9), date(2026, 11, 15))
PLAN_WINDOW = SearchWindow(date(2026, 11, 16), date(2026, 11, 22))
PAUSE_SECONDS = 2.0
_TWO_GROUPS = re.compile(r"^\(([^()]*)\) \(([^()]*)\)$")


@dataclass(frozen=True)
class Case:
    label: str
    profile: str
    market: str
    script: str | None  # "hant", "hans" or None
    sentinel: str | None
    sentinel_window: tuple[date, date] | None


CASES = (
    Case("en", "en", "united_kingdom", None, "Stadler", (date(2026, 11, 15), date(2026, 11, 18))),
    Case("ja", "ja", "japan", None, "スマホゲーム", (date(2026, 11, 15), date(2026, 11, 17))),
    Case("ko", "ko", "south_korea", None, "성수지선", (date(2026, 11, 18), date(2026, 11, 20))),
    Case("zh-Hant", "zh", "taiwan", "hant", "基隆", (date(2026, 11, 16), date(2026, 11, 18))),
    Case("zh-Hans", "zh", "hong_kong", "hans", None, None),
)


def _encodable(term: str, codec: str) -> bool:
    try:
        term.encode(codec)
    except UnicodeEncodeError:
        return False
    return True


def _in_script(term: str, script: str | None) -> bool:
    if script == "hant":
        return _encodable(term, "big5")
    if script == "hans":
        return _encodable(term, "gb2312")
    return True


def _terms(group: str) -> list[str]:
    return [term.strip() for term in group.split(" OR ") if term.strip()]


def _render(first: list[str], second: list[str]) -> str:
    return f"({' OR '.join(first)}) ({' OR '.join(second)})"


def _groups(plan, case: Case):
    first: list[str] = []
    second: list[str] = []
    encoding = None
    for item in plan.items:
        if item.provider_encoding is None or item.language_profile != case.profile:
            continue
        match = _TWO_GROUPS.match(item.query)
        if not match:
            continue
        if item.market_id == case.market and encoding is None:
            encoding = item.provider_encoding
        candidate = [t for t in _terms(match.group(1)) if _in_script(t, case.script)]
        if len(candidate) > len(first):
            first = candidate
        for term in _terms(match.group(2)):
            if term not in second and _in_script(term, case.script):
                second.append(term)
    return first, second, encoding


def _dates_operators(window: tuple[date, date]) -> str:
    return f"after:{window[0].isoformat()} before:{(window[1] + timedelta(days=1)).isoformat()}"


def _fetch(query: str, encoding):
    url = f"{rss.GOOGLE_NEWS_RSS_ENDPOINT}?" + urlencode(
        (("q", query), ("hl", encoding.hl), ("gl", encoding.gl), ("ceid", encoding.ceid))
    )
    body, status, _, _ = rss._response_parts(rss._default_transport(url, 20.0), url)
    return status, (rss._parse_rss(body) if status == 200 else [])


def _published(result) -> date | None:
    try:
        return parsedate_to_datetime(result.published_at).astimezone(timezone.utc).date()
    except (TypeError, ValueError, IndexError):
        return None


class Probe:
    def __init__(self, sleep=time.sleep):
        self.requests = 0
        self._sleep = sleep

    def send(self, query: str, encoding):
        if self.requests:
            self._sleep(PAUSE_SECONDS)
        self.requests += 1
        try:
            return _fetch(query, encoding)
        except Exception as exc:  # observation only
            return f"ERROR {type(exc).__name__}", []

    def limit_verdict(self, case: Case, first, second, k: int, encoding) -> tuple[str, int]:
        planned = _render(first, second[:k])
        status, results = self.send(f"{planned} {_dates_operators(LIMIT_WINDOW)}", encoding)
        slack = (LIMIT_WINDOW[0] - timedelta(days=1), LIMIT_WINDOW[1] + timedelta(days=1))
        found = [_published(r) for r in results]
        inside = sum(1 for d in found if d is not None and slack[0] <= d <= slack[1])
        outside = [d for d in found if d is not None and not slack[0] <= d <= slack[1]]
        verdict = "dropped" if outside else ("kept" if inside else "inconclusive")
        words = _query_words(planned)
        print(
            f"QUERY_LIMIT_PROBE {case.label} LIMIT k={k} planned_words={words} sent_words={words + 2} "
            f"status={status} items={len(found)} inside={inside} outside={len(outside)} "
            f"latest_outside={max(outside).isoformat() if outside else '-'} verdict={verdict}"
        )
        return verdict, words

    def tail(self, case: Case, first, second, planned_words: int, encoding, role: str) -> None:
        k = 0
        while k < len(second) and _query_words(_render(first, second[: k + 1] + [case.sentinel])) <= planned_words:
            k += 1
        planned = _render(first, second[:k] + [case.sentinel])
        status, results = self.send(f"{_dates_operators(case.sentinel_window)} {planned}", encoding)
        hits = sum(1 for r in results if case.sentinel.casefold() in r.title.casefold())
        words = _query_words(planned)
        print(
            f"QUERY_LIMIT_PROBE {case.label} TAIL role={role} sentinel_position={words} sent_words={words + 2} "
            f"status={status} items={len(results)} titles_with_sentinel={hits} "
            f"verdict={'present' if hits else ('absent' if results else 'no_items')}"
        )


def _search(probe: Probe, case: Case, first, second, encoding):
    """Largest kept and smallest dropped planned length (binary search over k)."""
    lo, hi = 1, len(second)
    while hi > 1 and _query_words(_render(first, second[:hi])) > 32:
        hi -= 1
    verdict, words = probe.limit_verdict(case, first, second, hi, encoding)
    if verdict == "kept":
        return words, None
    if verdict == "inconclusive":
        return None, None
    dropped_words = words
    kept_words = None
    while hi - lo > 1:
        mid = (lo + hi) // 2
        verdict, words = probe.limit_verdict(case, first, second, mid, encoding)
        if verdict == "kept":
            lo, kept_words = mid, words
        elif verdict == "dropped":
            hi, dropped_words = mid, words
        else:
            return kept_words, dropped_words
    if kept_words is None:
        verdict, words = probe.limit_verdict(case, first, second, lo, encoding)
        kept_words = words if verdict == "kept" else None
    return kept_words, dropped_words


def main(argv: list[str] | None = None, *, sleep=time.sleep) -> int:
    plan = SearchPlanner(RegionRegistry.from_file()).plan("selected", window=PLAN_WINDOW)
    probe = Probe(sleep)
    for case in CASES:
        first, second, encoding = _groups(plan, case)
        if not first or not second or encoding is None:
            print(f"QUERY_LIMIT_PROBE {case.label} SKIPPED no planned query of this shape")
            continue
        kept, dropped = _search(probe, case, first, second, encoding)
        print(
            f"QUERY_LIMIT_SUMMARY {case.label} largest_kept_planned={kept} smallest_dropped_planned={dropped} "
            f"proposed_planned_limit={kept - 2 if kept else None}"
        )
        if case.sentinel and kept:
            probe.tail(case, first, second, kept - 2, encoding, "at_proposed_limit")
            probe.tail(case, first, second, (dropped or kept) + 4, encoding, "past_limit_control")
    print(f"QUERY_LIMIT_SUMMARY requests={probe.requests}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
