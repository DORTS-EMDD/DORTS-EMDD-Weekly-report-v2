"""RC-75 (section A.56): a system relation may leave the focus; one correction request."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.weekly_report.contracts import (
    EvidenceResult,
    EvidenceState,
    ScopeState,
    SemanticProviderTechnicalFailure,
)
from src.weekly_report.maiagent_scope_provider import PROMPT_VERSION, build_maiagent_scope_model_input
from src.weekly_report.production_runner import _stage_counts
from src.weekly_report.scope_classifier import (
    SCOPE_PROPOSAL_SCHEMA_VERSION,
    ScopeClassifier,
    ScopeProposalViolation,
    ScopeSemanticRequest,
)

SOURCE = (
    "The operator opened the Tram Line 4 extension to passengers. "
    "A crowd gathered at the first stop. "
    "The Tram Line 4 extension is part of the Metro system."
)


def _evidence(content: str = SOURCE) -> EvidenceResult:
    return EvidenceResult(candidate_id="C1", state=EvidenceState.READY, substantive_content=content, provenance={})


def _proposal(
    *,
    action: str = "opened",
    target: str = "Tram Line 4 extension",
    system: str = "Metro system",
    focus=("S1",),
    action_target=("S1",),
    target_system=("S1", "S3"),
    target_reference: str | None = None,
    action_status: str = "ESTABLISHED",
    noneligible=("ABSENT", [], "NONE"),
) -> dict:
    system_record = {"status": "ESTABLISHED", "relation": "PART_OF", "sentence_ids": list(target_system)}
    if target_reference is not None:
        system_record["target_reference"] = target_reference
    return {
        "candidate_id": "C1",
        "schema_version": SCOPE_PROPOSAL_SCHEMA_VERSION,
        "event_focus": {"status": "RESOLVED", "sentence_ids": list(focus)},
        "action": {"label": action},
        "target": {"label": target},
        "system": {"label": system},
        "eligible_mode_family": "TRAM",
        "action_target": {
            "status": action_status,
            "relation": "AFFECTS",
            "sentence_ids": list(action_target) if action_status == "ESTABLISHED" else [],
        },
        "target_system": system_record,
        "ambiguity": {"status": "NONE", "sentence_ids": []},
        "noneligible_relation": {"status": noneligible[0], "sentence_ids": noneligible[1]},
        "noneligible_kind": noneligible[2],
        "event_status": "ASSERTED",
        "decision": "IN_SCOPE_SUPPORT",
    }


def _classify(proposal: dict, content: str = SOURCE, hook=None):
    return ScopeClassifier(lambda _request: proposal).classify(_evidence(content), observation_hook=hook)


def _predicate(proposal: dict, content: str = SOURCE) -> str:
    with pytest.raises(ScopeProposalViolation) as caught:
        _classify(proposal, content)
    return caught.value.failure_class


# ---- C: the system relation may leave the focus -------------------------------------


def test_the_system_sentence_outside_the_focus_is_accepted_for_the_same_target():
    result = _classify(_proposal())
    assert result.state is ScopeState.IN_SCOPE
    # The Candidate event focus stays the occurrence sentence only.
    focus = result.provenance["candidate_event_focus"]
    assert focus == [{"start": 0, "end": len("The operator opened the Tram Line 4 extension to passengers.")}]
    # The system label is located inside the sentence that establishes it.
    system_at = SOURCE.index("Metro system")
    assert {"start": system_at, "end": system_at + len("Metro system")} in result.provenance["relation_support"]["system"]


def test_the_conditions_are_the_two_the_user_decided_and_nothing_stricter():
    # (a) the action-to-target relation is inside the focus and (b) the system
    # relation's target is that same target label. The system sentence need not
    # repeat the target label: the relation is read across the cited sentences.
    source = (
        "The port installed cargo monitors for harbor businesses. "
        "The Metro line renewed signalling equipment."
    )
    proposal = _proposal(
        action="installed", target="cargo monitors", system="Metro line", target_system=("S1", "S2")
    )
    assert _classify(proposal, source).state is ScopeState.IN_SCOPE


def test_a_target_reference_other_than_the_target_label_keeps_the_focus_bound():
    proposal = _proposal(target_reference="Tram Line 4")
    assert _predicate(proposal) == "EVENT_FOCUS_CONTAINMENT"


def test_the_action_target_relation_must_still_lie_in_the_focus():
    proposal = _proposal(action_target=("S1", "S3"))
    assert _predicate(proposal) == "EVENT_FOCUS_CONTAINMENT"


def test_an_unestablished_action_target_gives_no_exception():
    proposal = _proposal(action_status="UNESTABLISHED")
    assert _predicate(proposal) == "EVENT_FOCUS_CONTAINMENT"


def test_the_noneligible_relation_never_leaves_the_focus():
    proposal = _proposal(noneligible=("PRESENT", ["S1", "S3"], "NON_URBAN_RAIL"))
    proposal["eligible_mode_family"] = "NON_ELIGIBLE"
    assert _predicate(proposal) == "NONELIGIBLE_EVENT_FOCUS"


def test_the_system_label_must_be_in_the_cited_system_sentences():
    # S1 and S2 do not hold the system label; S3 does but is not cited.
    assert _predicate(_proposal(target_system=("S1", "S2"))) == "TARGET_SYSTEM_CONTAINMENT"
    # A label that is not source text at all is an endpoint violation.
    assert _predicate(_proposal(target_system=("S3",), system="Tram system")) == "ENDPOINT_LABEL"


# ---- E: one correction request ---------------------------------------------------------


class _Helper:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.requests: list[ScopeSemanticRequest] = []

    def __call__(self, request):
        self.requests.append(request)
        answer = self.answers[min(len(self.requests), len(self.answers)) - 1]
        if isinstance(answer, BaseException):
            raise answer
        return answer


def _classify_with(helper, hook=None):
    return ScopeClassifier(helper).classify(_evidence(), observation_hook=hook)


def test_a_label_that_is_not_source_text_is_corrected_once():
    bad = _proposal(action="was inaugurated")
    good = _proposal()
    helper = _Helper(bad, good)
    seen = []
    result = _classify_with(helper, seen.append)
    assert result.state is ScopeState.IN_SCOPE
    assert len(helper.requests) == 2
    assert helper.requests[0].correction is None
    correction = helper.requests[1].correction
    assert correction.predicate == "ENDPOINT_LABEL"
    assert correction.fields == ("action.label",)
    assert correction.rejected_proposal == bad
    payload = helper.requests[1].as_payload()["correction"]
    assert payload["violated_rule"] == "ENDPOINT_LABEL"
    assert payload["fields_at_fault"] == ["action.label"]
    assert "exact substring" in payload["rule"]
    assert payload["rejected_proposal"] == bad
    assert result.provenance["scope_correction"] == {
        "predicate": "ENDPOINT_LABEL",
        "fields": ["action.label"],
        "outcome": "ACCEPTED",
    }
    assert seen[-1].correction_predicate == "ENDPOINT_LABEL"
    assert seen[-1].response_status == "OWNER_VALIDATED"


def test_a_second_violation_is_the_technical_gap_and_there_is_no_third_request():
    helper = _Helper(_proposal(action="was inaugurated"), _proposal(system="Subway network"))
    seen = []
    with pytest.raises(ScopeProposalViolation) as caught:
        _classify_with(helper, seen.append)
    assert len(helper.requests) == 2
    assert caught.value.failure_class == "ENDPOINT_LABEL"
    assert caught.value.scope_correction == {
        "predicate": "ENDPOINT_LABEL",
        "fields": ["action.label"],
        "outcome": "STILL_VIOLATED",
        "second_predicate": "ENDPOINT_LABEL",
    }
    assert caught.value.observation is not None
    assert seen[-1].response_status == "PROPOSAL_VIOLATION"
    assert seen[-1].correction_predicate == "ENDPOINT_LABEL"


def test_the_correction_names_the_containment_field():
    helper = _Helper(_proposal(action_target=("S1", "S3")), _proposal())
    _classify_with(helper)
    correction = helper.requests[1].correction
    assert correction.predicate == "EVENT_FOCUS_CONTAINMENT"
    assert correction.fields == ("action_target.sentence_ids", "event_focus.sentence_ids")


def test_a_valid_proposal_gets_no_correction_request():
    helper = _Helper(_proposal())
    result = _classify_with(helper)
    assert len(helper.requests) == 1
    assert "scope_correction" not in result.provenance
    assert "correction" not in helper.requests[0].as_payload()


def test_a_missing_proposal_is_not_corrected():
    helper = _Helper(object())
    with pytest.raises(ScopeProposalViolation) as caught:
        _classify_with(helper)
    assert caught.value.failure_class == "PROPOSAL_MISSING"
    assert len(helper.requests) == 1
    assert caught.value.scope_correction is None


def test_a_transport_failure_on_the_correction_request_is_recorded_and_propagates():
    failure = SemanticProviderTechnicalFailure("TIMEOUT", attempts=2, transient=True, task="scope_semantic_proposal")
    helper = _Helper(_proposal(action="was inaugurated"), failure)
    with pytest.raises(SemanticProviderTechnicalFailure) as caught:
        _classify_with(helper)
    assert caught.value.scope_correction["outcome"] == "TRANSPORT_FAILURE"
    assert len(helper.requests) == 2


def test_the_provider_input_carries_the_correction_and_the_prompt_version_is_unchanged():
    helper = _Helper(_proposal(action="was inaugurated"), _proposal())
    _classify_with(helper)
    plain = build_maiagent_scope_model_input(helper.requests[0])
    corrected = build_maiagent_scope_model_input(helper.requests[1])
    assert "correction" not in plain["scope_request"]
    assert corrected["scope_request"]["correction"]["violated_rule"] == "ENDPOINT_LABEL"
    assert plain["prompt_version"] == corrected["prompt_version"] == PROMPT_VERSION == "scope-event-target-system-v13"


def test_corrections_are_counted_apart_from_transport_retries():
    result = SimpleNamespace(
        plan=SimpleNamespace(items=()),
        execution=SimpleNamespace(attempt_results=(), unattempted_items=()),
        acquisitions=(),
        validation_result=None,
        final_report=None,
        technical_gaps=(),
        metadata_exclusions=(),
        scope_corrections=(
            ("c1", {"predicate": "ENDPOINT_LABEL", "fields": ["action.label"], "outcome": "ACCEPTED"}),
            ("c2", {"predicate": "ENDPOINT_LABEL", "fields": ["action.label"], "outcome": "STILL_VIOLATED"}),
        ),
        **{
            name: None
            for name in (
                "normalized_observations", "evidence_results", "scope_results", "temporal_results",
                "event_identity_records", "category_results", "downstream_results", "ordered_results",
                "formal_metadata", "writer_blocks",
            )
        },
    )
    counts = _stage_counts(result)
    assert counts["scope_correction_requests"] == 2
    assert counts["scope_correction_accepted"] == 1
