"""RC-40/41: rejected proposal group members are observable; formal report sections are fixed.

RC-40 (observation only): run 40838021391 rejected batch group-6 for
DUPLICATE_MEMBERSHIP, but nothing recorded which records it named. EventIdentity
records rejected members as a diagnostic; grouping is unchanged by it. RC-42
(section A.30) made validation per member, so the diagnostic is now
PROPOSAL_MEMBER_REJECTED and names only the rejected members.

RC-41 (contract section R, user-approved): ReportService presents sections in a
fixed order with formal titles, keyed by the Classifier's canonical CategoryId;
the Category decision and its own label are unchanged. Incident severity
ordering has no authoritative owner and is not implemented (BLOCKED_DOMAIN_RULE).
"""

from __future__ import annotations

from dataclasses import fields, replace
from types import SimpleNamespace

import pytest

from src.weekly_report import event_identity as event_identity_module
from src.weekly_report.contracts import CategoryId
from src.weekly_report.debug_service import event_identity_projection
from src.weekly_report.event_identity import EventIdentity
from src.weekly_report.gmail_smtp import index_for_artifact
from src.weekly_report.report_service import FORMAL_REPORT_SECTIONS, FormalMetadataFailure, ReportService
from src.weekly_report.selection_audit import build_selection_audit
from src.weekly_report.validator import ValidatedReportEvent, ValidationResult
from src.weekly_report.writer import WriterReportBlock
from tests.test_event_identity_contract import _record
from tests.test_event_identity_grouping_rc15 import _Scripted, _confirm, _member


def _scripted(*responses):
    """These tests examine one nomination's validation: the second nomination proposes nothing (RC-44)."""

    return _Scripted(*responses, second={"groups": []})
from tests.test_report_service import _workflow_result

BODIES = {
    "A": "The operator started 5G Wi-Fi on every car of Lines 1 and 2 on 21 October.",
    "B": "From 21 October all cars on Lines 1 and 2 carry 5G-backed Wi-Fi, the operator said.",
    "C": "A fire drill was held at a station on 20 October.",
    "D": "Firefighters and the operator drilled at the same station on 20 October.",
}


def _records():
    return [_record(name, facts=None, body=body) for name, body in BODIES.items()]


def _rejected(run):
    return [(item.candidate_ids, item.detail) for item in run.diagnostics if item.reason == "PROPOSAL_MEMBER_REJECTED"]


def _groups(run):
    return sorted(group.member_candidate_ids for group in run.groups)


# --- RC-40: rejected proposal group members --------------------------------------------


def test_a_member_rejected_for_duplicate_membership_is_recorded():
    batch = {"groups": [
        {"members": [_member("A"), _member("B"), _member("A")]},  # A listed twice
        {"members": [_member("C"), _member("D")]},
    ]}
    run = EventIdentity(_scripted(batch, _confirm("C", "D"))).evaluate(_records())
    assert _groups(run) == [("A",), ("B",), ("C", "D")]  # B alone proposes no merge
    assert [gap.subject_id for gap in run.technical_gaps] == ["event-identity-batch-1:group-1"]
    assert _rejected(run) == [(("A",), "event-identity-batch-1:group-1|DUPLICATE_MEMBERSHIP")]
    assert event_identity_projection(run)["event_identity_diagnostic_distribution"]["PROPOSAL_MEMBER_REJECTED"] == 1


def test_a_member_rejected_for_invalid_citations_is_recorded():
    batch = {"groups": [{"members": [_member("A", subject_sentence_ids=["S99"]), _member("B")]}]}
    run = EventIdentity(_scripted(batch)).evaluate(_records())
    assert _groups(run) == [("A",), ("B",), ("C",), ("D",)]
    assert _rejected(run) == [(("A",), "event-identity-batch-1:group-1|CITATION_INVALID")]


def test_a_rejected_confirmation_member_is_recorded_with_its_own_subject():
    batch = {"groups": [{"members": [_member("A"), _member("B")]}]}
    confirmation = {"groups": [{"members": [_member("A"), _member("A"), _member("B")]}]}
    run = EventIdentity(_scripted(batch, confirmation)).evaluate(_records())
    assert _groups(run) == [("A",), ("B",), ("C",), ("D",)]
    assert _rejected(run) == [
        (("A",), "event-identity-batch-1:group-1:confirmation:group-1|DUPLICATE_MEMBERSHIP")
    ]


def test_a_whole_response_violation_has_no_group_members_to_record():
    batch = {"groups": [{"members": [_member("A"), _member("R99")]}]}  # unknown record: whole response invalid
    run = EventIdentity(_scripted(batch)).evaluate(_records())
    assert _rejected(run) == []
    assert [gap.failure_class for gap in run.technical_gaps] == ["UNKNOWN_RECORD"]


def test_the_observation_does_not_change_any_grouping_outcome(monkeypatch):
    def scripted():
        return _scripted(
            {"groups": [{"members": [_member("A"), _member("B"), _member("A")]}, {"members": [_member("C"), _member("D")]}]},
            _confirm("C", "D"),
        )

    observed = EventIdentity(scripted()).evaluate(_records())
    monkeypatch.setattr(event_identity_module, "_record_rejected_members", lambda *args: None)
    unobserved = EventIdentity(scripted()).evaluate(_records())
    assert observed.groups == unobserved.groups
    assert observed.technical_gaps == unobserved.technical_gaps
    assert [d for d in observed.diagnostics if d.reason != "PROPOSAL_MEMBER_REJECTED"] == list(unobserved.diagnostics)


def test_the_diagnostic_carries_ids_only_never_source_text():
    run = EventIdentity(
        _scripted({"groups": [{"members": [_member("A"), _member("B"), _member("A")]}]})
    ).evaluate(_records())
    rendered = repr(_rejected(run))
    for body in BODIES.values():
        for word in body.split()[:4]:
            if len(word) > 3:
                assert word not in rendered


def test_the_selection_audit_traces_rejected_members_to_candidates():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_execution_trace import _full_app

    app, _ = _full_app()
    result = app.run("selected")
    left, right = (record.candidate.candidate_id for record in result.event_identity_records[:2])
    run = EventIdentity(
        _scripted({"groups": [{"members": [_member(left), _member(right), _member(left)]}]})
    ).evaluate(result.event_identity_records)
    view = SimpleNamespace(**{item.name: getattr(result, item.name) for item in fields(result)})
    view.event_identity_run = run
    audit = build_selection_audit(view)
    assert audit["event_identity_rejected_members"] == [
        {"group": "event-identity-batch-1:group-1", "reason": "DUPLICATE_MEMBERSHIP", "candidate_ids": [left]}
    ]
    by_id = {entry["candidate_id"]: entry for entry in audit["candidates"]}
    assert by_id[left]["event_identity"]["proposal_member_rejected"] == [
        {"group": "event-identity-batch-1:group-1", "reason": "DUPLICATE_MEMBERSHIP"}
    ]
    assert by_id[right]["event_identity"]["proposal_member_rejected"] == []


# --- RC-41: formal report sections --------------------------------------------------------


EXPECTED_TITLES = ["技術新知", "事故及安全事件", "營運動態", "機電標案及採購動態", "規範及標準動態"]


def _artifact(categories):
    """Assemble one validated event per (event_id, Category label) in the given Ordering order."""

    service = ReportService()
    base = service.project_formal_metadata((_workflow_result(),))[0]
    passed = []
    for event_id, category in categories:
        metadata = replace(base, event_id=event_id, category=category)
        block = WriterReportBlock(event_id, f"標題{event_id}", "事件摘要 Taiwan Metro", "可供臺北捷運評估規劃方向")
        passed.append(ValidatedReportEvent(_workflow_result(event_id), metadata, block))
    validation = ValidationResult(tuple(i.result for i in passed), tuple(i.metadata for i in passed), tuple(passed))
    return service.assemble_final_report(validation)


def test_the_section_contract_has_five_titles_in_the_approved_order_covering_every_category():
    assert [title for _, title in FORMAL_REPORT_SECTIONS] == EXPECTED_TITLES
    assert [category_id for category_id, _ in FORMAL_REPORT_SECTIONS] == [
        CategoryId.TECHNICAL_DEVELOPMENT, CategoryId.INCIDENT, CategoryId.OPERATIONAL_CHANGE,
        CategoryId.PROCUREMENT, CategoryId.NORMATIVE_CHANGE,
    ]
    assert len({category_id for category_id, _ in FORMAL_REPORT_SECTIONS}) == len(CategoryId)


def test_sections_follow_the_fixed_order_whatever_the_ordering_and_keep_its_subsequence_inside():
    # Ordering (date first) interleaves categories; incidents come first here.
    artifact = _artifact([
        ("E1", "事故事件"), ("E2", "規範變動"), ("E3", "技術新知"), ("E4", "事故事件"),
        ("E5", "採購事件"), ("E6", "營運動態"), ("E7", "技術新知"),
    ])
    assert [section.category for section in artifact.sections] == EXPECTED_TITLES
    assert [[e.event_id for e in section.events] for section in artifact.sections] == [
        ["E3", "E7"], ["E1", "E4"], ["E6"], ["E5"], ["E2"],
    ]


def test_missing_categories_are_omitted_and_the_rest_keep_their_order():
    artifact = _artifact([("E1", "採購事件"), ("E2", "事故事件")])
    assert [section.category for section in artifact.sections] == ["事故及安全事件", "機電標案及採購動態"]


def test_markdown_pdf_and_email_show_the_same_titles_in_the_same_order():
    fitz = pytest.importorskip("fitz")
    from src.weekly_report.pdf_renderer import render_report_pdf

    artifact = _artifact([("E1", "規範變動"), ("E2", "事故事件"), ("E3", "技術新知")])
    expected = ["技術新知", "事故及安全事件", "規範及標準動態"]

    def order_in(text):
        positions = {title: text.find(f"【{title}】") for title in EXPECTED_TITLES}
        return [title for title, position in sorted(positions.items(), key=lambda kv: kv[1]) if position >= 0]

    pdf_text = "".join(page.get_text() for page in fitz.open(stream=render_report_pdf(artifact), filetype="pdf"))
    email_text, email_html = index_for_artifact(artifact)
    assert order_in(artifact.content) == order_in(pdf_text.replace("\n", "")) == order_in(email_text) == expected
    assert all(f"【{title}】" in email_html for title in expected)


def test_the_category_decision_and_its_labels_are_unchanged():
    assert {category_id: category_id.display_label for category_id in CategoryId} == {
        CategoryId.TECHNICAL_DEVELOPMENT: "技術新知",
        CategoryId.INCIDENT: "事故事件",
        CategoryId.OPERATIONAL_CHANGE: "營運動態",
        CategoryId.PROCUREMENT: "採購事件",
        CategoryId.NORMATIVE_CHANGE: "規範變動",
    }
    artifact = _artifact([("E1", "事故事件")])
    assert artifact.events[0].category == "事故事件"  # the formal metadata keeps the Category label


def test_a_category_label_outside_the_canonical_registry_fails_closed():
    with pytest.raises(FormalMetadataFailure):
        _artifact([("E1", "重大事故")])


def test_incidents_keep_the_ordering_sequence_no_severity_ranking():
    # BLOCKED_DOMAIN_RULE: no authoritative severity decision exists, so the
    # incident section keeps exactly the Ordering subsequence.
    artifact = _artifact([("E9", "事故事件"), ("E1", "事故事件"), ("E5", "事故事件")])
    assert [event.event_id for event in artifact.sections[0].events] == ["E9", "E1", "E5"]
