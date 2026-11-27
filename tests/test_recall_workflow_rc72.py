"""Recall-test workflow: the job can never email, runs in order, and uses the shared CLI."""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.recall_candidates import candidate_lines  # noqa: E402
from scripts.recall_matrix import parse_periods  # noqa: E402

WORKFLOW = (ROOT / ".github" / "workflows" / "weekly-report.yml").read_text(encoding="utf-8")


def _job(name: str) -> str:
    start = WORKFLOW.index(f"\n  {name}:")
    following = re.search(r"\n  [a-z][a-z-]*:\n", WORKFLOW[start + 1 :])
    return WORKFLOW[start : start + 1 + following.start()] if following else WORKFLOW[start:]


RECALL = _job("recall-test")


def test_the_recall_job_can_never_send_email():
    assert 'LIVE_EMAIL_SEND: "0"' in RECALL
    for forbidden in ("GMAIL_", "DEFAULT_RECIPIENTS", "DELIVERY_", "send_email", "secrets.GITHUB_TOKEN"):
        assert forbidden not in RECALL, forbidden
    # only the MaiAgent secrets are passed in
    assert sorted(set(re.findall(r"secrets\.([A-Z0-9_]+)", RECALL))) == [
        "MAIAGENT_API_BASE",
        "MAIAGENT_API_KEY",
        "MAIAGENT_CHATBOT_ID",
        "MAIAGENT_STRUCTURED_HELPER_CHATBOT_ID",
    ]


def test_the_recall_job_runs_periods_in_order_and_independently():
    assert "max-parallel: 1" in RECALL
    assert "fail-fast: false" in RECALL
    assert "sleep 3600" in RECALL
    assert "strategy.job-index != 0 || inputs.recall_wait_first == true" in RECALL


def test_the_recall_job_uses_the_shared_cli_health_check_and_period_artifact():
    assert 'args=(--region-mode "$REGION_MODE" --output-dir report-output' in RECALL
    assert 'python main.py "${args[@]}"' in RECALL
    assert '--period-start "$PERIOD_START" --period-end "$PERIOD_END"' in RECALL
    assert "PERIOD_START: ${{ matrix.start }}" in RECALL and "PERIOD_END: ${{ matrix.end }}" in RECALL
    assert "python -m scripts.google_news_health_check" in RECALL
    assert "name: recall-${{ matrix.start }}_${{ matrix.end }}-${{ github.run_id }}" in RECALL
    assert "python -m scripts.recall_candidates" in RECALL


def test_the_other_jobs_do_not_start_on_recall_inputs():
    assert "recall" not in _job("production")
    assert "recall_periods" in WORKFLOW.split("jobs:")[0]


def test_matrix_parses_the_requested_periods():
    text = "2026-02-04:2026-02-06,2026-05-26:2026-05-28, 2026-10-08:2026-10-10,2026-10-27:2026-10-29"
    assert parse_periods(text) == [
        {"start": "2026-02-04", "end": "2026-02-06"},
        {"start": "2026-05-26", "end": "2026-05-28"},
        {"start": "2026-10-08", "end": "2026-10-10"},
        {"start": "2026-10-27", "end": "2026-10-29"},
    ]


@pytest.mark.parametrize(
    "text",
    ["", " , ", "2026-02-04", "2026-02-06:2026-02-04", "2026-02-30:2026-03-01", "2026-02-04:2026-02-06,2026-02-04:2026-02-06"]
)
def test_matrix_rejects_malformed_input(text):
    with pytest.raises(ValueError):
        parse_periods(text)


def test_matrix_limits_the_number_of_periods():
    many = ",".join(f"2026-01-{day:02d}:2026-01-{day:02d}" for day in range(1, 10))
    with pytest.raises(ValueError):
        parse_periods(many)


def test_candidate_listing_has_every_candidate_with_its_stage_and_category():
    audit = {
        "candidates": [
            {"discovery_title": "A", "publisher": "P", "terminal_stage": "FINAL_REPORT", "terminal_reason": "INCLUDED",
             "event": {"category": {"primary_category": "TECHNOLOGY_DEVELOPMENT"}}},
            {"discovery_title": "B", "publisher": None, "terminal_stage": "EVIDENCE", "terminal_reason": "NOT_REACHED"},
        ]
    }
    lines = candidate_lines(json.loads(json.dumps(audit)))
    assert lines == [
        "CANDIDATE | FINAL_REPORT | INCLUDED | category=TECHNOLOGY_DEVELOPMENT | publisher=P | title=A",
        "CANDIDATE | EVIDENCE | NOT_REACHED | category=- | publisher=- | title=B",
    ]


def test_the_log_carries_the_audit_and_the_score_tool_rebuilds_it(tmp_path, capsys):
    from scripts import recall_candidates
    from scripts.recall_score import load_audit

    audit = {"period": {"start": "2026-10-27", "end": "2026-10-29"}, "candidate_count": 1, "event_count": 0,
             "final_report_event_count": 0, "terminal_reason_distribution": {},
             "candidates": [{"candidate_id": "c1", "discovery_title": "東京メトロ", "publisher": "P",
                             "terminal_stage": "EVIDENCE", "terminal_reason": "NOT_REACHED"}], "events": []}
    path = tmp_path / "selection_audit.json"
    path.write_text(json.dumps(audit, ensure_ascii=False), encoding="utf-8")
    assert recall_candidates.main(["x", str(path)]) == 0
    log = tmp_path / "job.log"
    log.write_text("\n".join("2026-11-19T11:20:11.7Z " + line for line in capsys.readouterr().out.splitlines()),
                   encoding="utf-8")
    assert load_audit(log) == audit
    wrapped = tmp_path / "job.json"
    wrapped.write_text(json.dumps({"logs_content": log.read_text(encoding="utf-8")}), encoding="utf-8")
    assert load_audit(wrapped) == audit
