"""RC-31: selection_audit.json is an observer-only, per-candidate projection."""

from __future__ import annotations

from dataclasses import fields
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

from src.weekly_report.contracts import EvidenceResult, EvidenceState, RejectReason, TechnicalGap, TechnicalGapKind
from src.weekly_report.production_runner import ProductionRunner
from src.weekly_report.selection_audit import STAGES, build_selection_audit, selection_audit_mapping_is_bounded

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_execution_trace import _full_app  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _result():
    app, _ = _full_app()
    return app.run("selected")


def test_every_normalized_candidate_is_audited_with_its_earliest_stage():
    result = _result()
    audit = build_selection_audit(result)
    normalized = [item.candidate.candidate_id for item in result.normalization_result.normalized_candidates]
    assert sorted(entry["candidate_id"] for entry in audit["candidates"]) == sorted(normalized)
    assert audit["candidate_count"] == len(normalized)
    assert all(entry["terminal_stage"] in STAGES for entry in audit["candidates"])
    included = [entry for entry in audit["candidates"] if entry["final_report_included"]]
    final_members = {
        candidate_id
        for item in result.validation_result.passed
        for candidate_id in item.result.event_group.member_candidate_ids
    }
    assert {entry["candidate_id"] for entry in included} == final_members
    assert audit["final_report_event_count"] == result.final_report.event_count
    for entry in included:
        assert entry["event"]["validation"] == {"outcome": "PASS"}
        assert entry["event"]["category"]["state"] == "CATEGORY_ASSIGNED"
        assert entry["event"]["reportability"]["state"] == "REPORTABLE"


def test_an_evidence_rejection_and_a_technical_gap_are_the_recorded_earliest_reasons():
    result = _result()
    first, second = (item.candidate.candidate_id for item in result.normalization_result.normalized_candidates[:2])
    rejected = EvidenceResult(
        candidate_id=first, state=EvidenceState.REJECTED, reject_reason=RejectReason.TITLE_ONLY,
        provenance={"evidence_rejection_gate": "PRINCIPAL_DOCUMENT"},
    )
    evidence = tuple(rejected if item.candidate_id == first else item for item in result.evidence_results if item.candidate_id != second)
    gap = TechnicalGap("Evidence", second, TechnicalGapKind.TRANSIENT_FAILURE_AFTER_RETRY, "TIMEOUT", 2)
    # The audit reads attributes only; a namespace copy avoids rebuilding a full run.
    view = SimpleNamespace(**{item.name: getattr(result, item.name) for item in fields(result)})
    view.evidence_results, view.technical_gaps = evidence, result.technical_gaps + (gap,)
    audit = build_selection_audit(view)
    by_id = {entry["candidate_id"]: entry for entry in audit["candidates"]}
    assert (by_id[first]["terminal_stage"], by_id[first]["terminal_reason"]) == ("EVIDENCE", "TITLE_ONLY|PRINCIPAL_DOCUMENT")
    assert (by_id[second]["terminal_stage"], by_id[second]["terminal_reason"]) == (
        "EVIDENCE", "TECHNICAL_GAP:TRANSIENT_FAILURE_AFTER_RETRY:TIMEOUT"
    )
    assert "scope" not in by_id[first] and "event" not in by_id[first]


def test_the_audit_is_bounded_serializable_and_carries_no_article_body():
    result = _result()
    audit = build_selection_audit(result)
    rendered = json.dumps(audit, ensure_ascii=False)
    assert selection_audit_mapping_is_bounded(audit)
    for item in result.evidence_results:
        body = item.substantive_content
        if len(body) > 300:
            assert body not in rendered
    for secret in ("api_key", "Api-Key", "instructions", "authoritative_response_contract"):
        assert secret not in rendered


def test_the_audit_is_deterministic_and_observer_only():
    app, _ = _full_app()
    plain = app.run("selected")
    assert build_selection_audit(plain) == build_selection_audit(plain)
    app2, _ = _full_app()
    with patch("src.weekly_report.production_runner.build_selection_audit", side_effect=RuntimeError("audit broke")):
        broken = ProductionRunner(app2).run(period_start="2026-09-12", period_end="2026-09-18")
    app3, _ = _full_app()
    healthy = ProductionRunner(app3).run(period_start="2026-09-12", period_end="2026-09-18")
    # A failing projection changes nothing but the audit itself.
    assert broken.status == healthy.status
    assert broken.final_report == healthy.final_report
    assert broken.stage_counts == healthy.stage_counts
    assert dict(broken.selection_audit) == {"audit_version": "selection-audit-v1", "unavailable": "RuntimeError"}
    assert healthy.selection_audit["period"] == {"start": "2026-09-12", "end": "2026-09-18"}


def test_the_cli_writes_the_audit_beside_the_report(tmp_path):
    sys.path.insert(0, str(ROOT))
    import main

    app, _ = _full_app()
    result = ProductionRunner(app).run(period_start="2026-09-12", period_end="2026-09-18")
    with patch("weekly_report.pdf_renderer.render_report_pdf", return_value=b"%PDF-stub"):
        assert main._write_outputs(tmp_path, result)
    audit = json.loads((tmp_path / "selection_audit.json").read_text(encoding="utf-8"))
    assert audit["report_id"] == result.final_report.report_id
    assert {path.name for path in tmp_path.iterdir()} == {
        "run_summary.txt", "selection_audit.json", f"{result.final_report.report_id}.md", f"{result.final_report.report_id}.pdf"
    }


def test_a_proposed_pair_left_apart_names_its_partner_and_why():
    from src.weekly_report.event_identity import EventIdentity
    from tests.test_event_identity_grouping_rc15 import _Scripted, _confirm, _member

    result = _result()
    left, right = (record.candidate.candidate_id for record in result.event_identity_records[:2])
    run = EventIdentity(
        _Scripted({"groups": [{"members": [_member(left), _member(right)]}]}, _confirm(separate=(left, right)))
    ).evaluate(result.event_identity_records)
    view = SimpleNamespace(**{item.name: getattr(result, item.name) for item in fields(result)})
    view.event_identity_run = run
    by_id = {entry["candidate_id"]: entry for entry in build_selection_audit(view)["candidates"]}
    assert by_id[left]["event_identity"]["proposals_not_merged"] == [
        {"with": right, "reason": "PROPOSAL_NOT_CONFIRMED", "detail": "event-identity-batch-1:group-1|size=2|SEPARATED"}
    ]
    assert by_id[right]["event_identity"]["proposals_not_merged"][0]["with"] == left
