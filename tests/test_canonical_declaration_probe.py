"""The RC-86 canonical probe compares the three rules and prints no page text (observation only)."""

from __future__ import annotations

from unittest.mock import patch

from scripts import canonical_declaration_probe as probe
from src.weekly_report.evidence_service import FetchedSource

LONG = "https://www.local-oslo.test/full-stans/s/30-128-26544"
SHORT = "https://www.local-oslo.test/30-128-26544"


def _page(*declarations: tuple[str, str]) -> str:
    head = "".join(
        f"<meta property='og:url' content='{url}'>" if kind == "og" else f"<link rel='canonical' href='{url}'>"
        for kind, url in declarations
    )
    return f"<html><head>{head}</head><body><main><article><h1>T</h1><p>Body sentence of the page.</p></article></main></body></html>"


def test_the_three_rules():
    assert probe._rules((SHORT, LONG), LONG, ()) == {"D5": "CANONICAL_RESOURCE_MISMATCH", "R86": "OK", "R86B": "OK", "declarations": "2"}
    mobile = "https://m.local-oslo.test/30-128-26544"
    assert probe._rules((LONG, mobile), LONG, ()) == {"D5": "OK", "R86": "CANONICAL_OTHER_SITE", "R86B": "OK", "declarations": "2"}
    other = "https://www.other-site.test/a"
    assert probe._rules((other,), LONG, ())["R86B"] == "CANONICAL_OTHER_SITE"
    assert probe._rules((), LONG, ()) == {"D5": "OK", "R86": "OK", "R86B": "OK", "declarations": "0"}


def test_the_probe_prints_urls_and_outcomes_only(tmp_path, capsys):
    rows = tmp_path / "pages.tsv"
    rows.write_text(f"cand_aaaaaaaaaaaaaaaa\tREADY\t{LONG}\n", encoding="utf-8")
    page = FetchedSource(url=LONG, content=_page(("og", SHORT), ("link", LONG)), content_type="text/html")
    with patch.object(probe.evidence_service, "_default_fetcher", return_value=page):
        assert probe.main([str(rows)]) == 0
    out = capsys.readouterr().out
    assert "D5=CANONICAL_RESOURCE_MISMATCH R86=OK R86B=OK" in out
    assert "CANONICAL_PROBE_SUMMARY pages=1 fetched=1" in out
    assert "Body sentence" not in out
