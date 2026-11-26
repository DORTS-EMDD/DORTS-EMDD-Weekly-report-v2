"""RC-88: the query-limit probe finds the word position where Google News drops trailing words."""

from __future__ import annotations

from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from scripts import query_length_probe as probe
from src.weekly_report.google_news_rss_provider import RssTransportResponse
from scripts.query_length_probe import _query_words

LIMIT = 26  # simulated: Google keeps the first 26 words as the planner counts them


def _item(title: str, published: str) -> str:
    return (
        f"<item><title>{title}</title><link>https://news.google.com/rss/articles/x</link>"
        f"<source url='https://a.test'>A</source><pubDate>{published}</pubDate></item>"
    )


def _kept_words(query: str) -> list[str]:
    words, kept = query.replace("(", " ( ").replace(")", " ) ").split(), []
    count = 0
    for word in words:
        if word not in "()":
            count += 1
        if count > LIMIT:
            break
        kept.append(word)
    return kept


def _transport(url, timeout):
    query = parse_qs(urlsplit(url).query)["q"][0]
    kept = " ".join(_kept_words(query))
    words = kept.split()
    after = [w for w in words if w.startswith("after:")]
    if after and any(w.startswith("before:") for w in words):
        start = after[0].removeprefix("after:")
        items = [_item("dated", f"{int(start[8:]) + 1:02d} Nov 2026 10:00:00 GMT")]
    else:  # the date operators were dropped: results from any date
        items = [_item("dated", "11 Nov 2026 10:00:00 GMT"), _item("later", "24 Nov 2026 10:00:00 GMT")]
    for sentinel in ("Stadler", "スマホゲーム", "성수지선", "基隆"):
        if sentinel in kept:
            items.append(_item(f"news {sentinel} today", "Tue, 17 Nov 2026 10:00:00 GMT"))
    body = f"<?xml version='1.0'?><rss><channel>{''.join(items)}</channel></rss>"
    return RssTransportResponse(body=body.encode(), status_code=200, final_url=url, headers={})


def test_the_probe_measures_the_limit_and_the_tail_term(capsys):
    sleeps = []
    with patch.object(probe.rss, "_default_transport", side_effect=_transport):
        assert probe.main([], sleep=sleeps.append) == 0
    out = capsys.readouterr().out.splitlines()
    summaries = {line.split()[1]: line for line in out if line.startswith("QUERY_LIMIT_SUMMARY") and "largest_kept" in line}
    assert set(summaries) == {"en", "ja", "ko", "zh-Hant", "zh-Hans"}
    for label, line in summaries.items():
        kept = int(line.split("largest_kept_planned=")[1].split()[0])
        dropped = int(line.split("smallest_dropped_planned=")[1].split()[0])
        assert kept <= LIMIT - 2 < dropped, label  # the two trailing date words fit only up to the limit
        assert f"proposed_planned_limit={kept - 2}" in line
    tails = [line for line in out if " TAIL " in line]
    assert len(tails) == 8
    assert all("verdict=present" in line for line in tails if "at_proposed_limit" in line)
    assert all("verdict=absent" in line for line in tails if "past_limit_control" in line)
    total = int(out[-1].split("requests=")[1])
    assert total <= 30 and len(sleeps) == total - 1
    assert not any("dated" in line or "today" in line for line in out)  # never titles


def test_zh_terms_are_split_by_script():
    assert probe._in_script("脫軌", "hant") and not probe._in_script("脫軌", "hans")
    assert probe._in_script("脱轨", "hans") and not probe._in_script("脱轨", "hant")
    assert probe._in_script("CBTC", "hant") and probe._in_script("CBTC", "hans")
    assert _query_words(probe._render(["a"], ['"b c"', "d"])) == 5


def test_the_character_step_sends_one_query_per_band_and_language(capsys):
    with patch.object(probe.rss, "_default_transport", side_effect=_transport):
        assert probe.main(["--characters"], sleep=lambda seconds: None) == 0
    lines = [line for line in capsys.readouterr().out.splitlines() if line.startswith("QUERY_CHARACTER_PROBE")]
    assert len(lines) == 8
    lengths = [int(line.split("characters=")[1].split()[0]) for line in lines]
    assert all(185 <= n <= 200 for n in lengths[0::2]) and all(201 <= n <= 215 for n in lengths[1::2])


def test_the_command_line_flag_selects_the_character_step(capsys):
    with patch.object(probe.rss, "_default_transport", side_effect=_transport), patch.object(
        probe.sys, "argv", ["query_length_probe", "--characters"]
    ):
        assert probe.main(sleep=lambda seconds: None) == 0
    out = capsys.readouterr().out
    assert "QUERY_CHARACTER_PROBE" in out and "QUERY_LIMIT_PROBE" not in out
