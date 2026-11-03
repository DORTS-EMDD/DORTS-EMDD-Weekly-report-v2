"""Section A.34: a run's Event Identity replays offline from its selection audit.

Event Identity records every helper exchange (IDs only); the replay rebuilds the
records from the audit and answers each request from its recorded exchange, so
the unchanged owner reproduces the live Events exactly. These tests run the
production pipeline, serialize its audit as main.py does, and replay it.
"""

from __future__ import annotations

import json

from scripts.event_identity_replay import audited_groups, main, replay, score
from tests.event_identity_single_procedure import _single_proposal_procedure  # noqa: F401  (RC-52: one procedure)
from src.weekly_report.contracts import SemanticProviderTechnicalFailure
from src.weekly_report.event_identity import SECOND_NOMINATION_SUFFIX, EventIdentity
from src.weekly_report.production_runner import ProductionRunner
from tests.test_event_identity_contract import _SemanticAdvisor
from tests.test_execution_trace import _full_app


def _audit(advisor):
    app, _ = _full_app()
    app._event_identity = EventIdentity(advisor)
    result = ProductionRunner(app).run(period_start="2026-09-12", period_end="2026-09-18")
    return json.loads(json.dumps(result.selection_audit, ensure_ascii=False))


def _gaps(run):
    return sorted(f"{gap.subject_id}:{gap.kind.value}:{gap.failure_class}" for gap in run.technical_gaps)


def _confirmed_by(run):
    return {
        candidate_id: sorted(
            item.detail.rpartition("|pairs=")[0]
            for item in run.diagnostics
            if item.reason == "PROPOSAL_CONFIRMED" and candidate_id in item.candidate_ids
        )
        for group in run.groups
        for candidate_id in group.member_candidate_ids
    }


def test_the_run_replays_exactly_from_its_selection_audit():
    audit = _audit(_SemanticAdvisor())
    subjects = [exchange["subject"] for exchange in audit["event_identity_exchanges"]]
    assert subjects[0] == "event-identity-batch-1" and "event-identity-batch-1" + SECOND_NOMINATION_SUFFIX in subjects
    assert any(subject.endswith(":confirmation") for subject in subjects)
    run = replay(audit)
    assert {group.member_candidate_ids for group in run.groups} == audited_groups(audit)
    assert any(len(group.member_candidate_ids) > 1 for group in run.groups)
    audited = {
        entry["candidate_id"]: entry["event_identity"]["proposal_confirmed_by"]
        for entry in audit["candidates"]
        if entry.get("event_identity")
    }
    assert _confirmed_by(run) == audited
    assert _gaps(run) == audit["event_identity_technical_gaps"] == []


def test_a_failed_nomination_replays_as_the_same_disclosed_gap():
    class SecondFails(_SemanticAdvisor):
        def __call__(self, request):
            if request.batch_id.endswith(SECOND_NOMINATION_SUFFIX):
                raise SemanticProviderTechnicalFailure("TIMEOUT", attempts=2, transient=True)
            return super().__call__(request)

    audit = _audit(SecondFails())
    run = replay(audit)
    assert _gaps(run) == audit["event_identity_technical_gaps"] == [
        "event-identity-batch-1-n2:TRANSIENT_FAILURE_AFTER_RETRY:TIMEOUT"
    ]
    assert {group.member_candidate_ids for group in run.groups} == audited_groups(audit)


def test_exchanges_hold_ids_only_even_when_the_helper_writes_text_into_a_citation():
    class TextCitation(_SemanticAdvisor):
        def __call__(self, request):
            answer = super().__call__(request)
            if not request.confirmation and answer["groups"]:
                answer["groups"][0]["members"][0]["occurrence_sentence_ids"] = ["The operator said the line opened."]
            return answer

    audit = _audit(TextCitation())
    recorded = json.dumps(audit["event_identity_exchanges"], ensure_ascii=False)
    assert "operator said" not in recorded and "INVALID" in recorded
    run = replay(audit)
    assert _gaps(run) == audit["event_identity_technical_gaps"]
    assert any(gap.endswith(":CITATION_INVALID") for gap in _gaps(run))
    assert {group.member_candidate_ids for group in run.groups} == audited_groups(audit)


def test_the_command_reports_a_reproduced_run(tmp_path, capsys):
    audit = _audit(_SemanticAdvisor())
    path = tmp_path / "selection_audit.json"
    path.write_text(json.dumps(audit), encoding="utf-8")
    assert main([str(path)]) == 0
    assert '"reproduced": true' in capsys.readouterr().out


def test_score_counts_labelled_merges_misses_and_wrong_merges():
    labels = {"A": "launch", "B": "launch", "C": "launch", "D": "call"}
    result = score([("A", "B", "D"), ("C",)], labels)
    assert result["same_pairs"] == 3 and result["same_pairs_merged"] == 1
    assert result["same_pairs_missed"] == [("A", "C"), ("B", "C")]
    assert result["different_pairs_merged"] == [("A", "D"), ("B", "D")]
