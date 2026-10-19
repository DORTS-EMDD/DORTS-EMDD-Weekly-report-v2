"""Acceptance evidence and replay tests, separate from mechanical schema fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from scripts.scope_acceptance import capture_case, replay_artifact
from src.weekly_report.contracts import EvidenceResult, EvidenceState, ScopeDiagnostic, ScopeState
from src.weekly_report.maiagent_scope_provider import MaiAgentScopeProviderFailure
from src.weekly_report.scope_classifier import SCOPE_PROPOSAL_SCHEMA_VERSION, ScopeClassifier

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def capture_artifact():
    paths = []

    def capture(case, provider, **kwargs):
        kwargs["run_id"] = f"test-{uuid4().hex}-{kwargs['run_id']}"
        kwargs["artifact_directory"] = ROOT
        path = capture_case(case, provider, **kwargs)
        paths.append(path)
        return path

    yield capture
    for path in paths:
        if path.parent.resolve() == ROOT.resolve() and path.name.startswith(".scope-acceptance-test-"):
            path.unlink(missing_ok=True)


POSITIVE_SOURCE = "The operator installed platform doors on the Metro line."
NEGATIVE_SOURCE = "The city installed public sculptures at the Metro station for the neighboring park."


def _evidence(content: str, candidate_id: str = "C1") -> EvidenceResult:
    return EvidenceResult(
        candidate_id=candidate_id,
        state=EvidenceState.READY,
        substantive_content=content,
        provenance={"source_identity": "synthetic-fixture"},
    )


def _semantic_proposal(
    content: str,
    *,
    candidate_id: str = "C1",
    decision: str = "IN_SCOPE_SUPPORT",
    mode: str = "METRO",
    action: str = "installed",
    target: str = "platform doors",
    system: str = "Metro line",
    action_status: str = "ESTABLISHED",
    action_relation: str = "AFFECTS",
    system_status: str = "ESTABLISHED",
    system_relation: str = "BELONGS_TO",
    noneligible_status: str = "ABSENT",
    noneligible_kind: str = "NONE",
) -> dict:
    return {
        "candidate_id": candidate_id,
        "schema_version": SCOPE_PROPOSAL_SCHEMA_VERSION,
        "event_focus": {"status": "RESOLVED", "quote": content},
        "action": {"label": action, "quote": action},
        "target": {"label": target, "quote": target},
        "system": {"label": system, "quote": system},
        "eligible_mode_family": mode,
        "action_target": {"status": action_status, "relation": action_relation, "quote": content},
        "target_system": {"status": system_status, "relation": system_relation, "quote": content},
        "ambiguity": {"status": "NONE", "quote": content},
        "noneligible_relation": {"status": noneligible_status, "quote": content},
        "noneligible_kind": noneligible_kind,
        "event_status": "ASSERTED",
        "decision": decision,
    }


def _case(content: str = POSITIVE_SOURCE, **values) -> dict:
    return {
        "case_id": values.get("case_id", "semantic-positive"),
        "authoritative_input_identity": values.get("authoritative_input_identity", "synthetic://scope/positive-v1"),
        "candidate_id": values.get("candidate_id", "C1"),
        "candidate_title": values.get("candidate_title", "Platform door installation"),
        "source_content": content,
        "source_metadata": {"source_identity": "synthetic-fixture"},
    }


def test_semantic_endpoints_support_a_real_positive_and_valid_negative():
    positive = _semantic_proposal(POSITIVE_SOURCE)
    result = ScopeClassifier(lambda _request: positive).classify(_evidence(POSITIVE_SOURCE))
    assert result.state is ScopeState.IN_SCOPE

    negative = _semantic_proposal(
        NEGATIVE_SOURCE,
        decision="OUT_OF_SCOPE_SUPPORT",
        action="installed",
        target="public sculptures",
        system="Metro station",
        system_relation="LOCATED_AT",
    )
    result = ScopeClassifier(lambda _request: negative).classify(_evidence(NEGATIVE_SOURCE))
    assert result.state is ScopeState.OUT_OF_SCOPE
    assert result.diagnostic is ScopeDiagnostic.SCOPE_NOT_ESTABLISHED


def test_first_actual_rejection_is_recorded_for_invalid_quotes_and_candidate_identity():
    bad_quote = _semantic_proposal(POSITIVE_SOURCE)
    bad_quote["action_target"]["quote"] = "not present in the source"
    observations = []
    result = ScopeClassifier(lambda _request: bad_quote).classify(
        _evidence(POSITIVE_SOURCE), observation_hook=observations.append
    )
    assert result.state is ScopeState.OUT_OF_SCOPE
    assert observations[0].first_rejection_predicate == "QUOTE_NOT_FOUND"

    repeated_source = "The Metro operator installed platform doors on the Metro line."
    repeated = _semantic_proposal(
        repeated_source,
        action="installed",
        target="platform doors",
        system="Metro",
    )
    observations.clear()
    ScopeClassifier(lambda _request: repeated).classify(
        _evidence(repeated_source), observation_hook=observations.append
    )
    assert observations[0].first_rejection_predicate == "QUOTE_NOT_UNIQUE"

    wrong_identity = _semantic_proposal(POSITIVE_SOURCE, candidate_id="C2")
    observations.clear()
    ScopeClassifier(lambda _request: wrong_identity).classify(
        _evidence(POSITIVE_SOURCE), observation_hook=observations.append
    )
    assert observations[0].first_rejection_predicate == "CANDIDATE_ID"


def test_relation_endpoint_mismatch_and_contradictory_statuses_fail_closed():
    source = "The operator installed platform doors. The Metro line commissioned new signalling equipment."
    mismatch = _semantic_proposal(
        source,
        action="installed",
        target="platform doors",
        system="Metro line",
    )
    mismatch["target_system"]["quote"] = "The Metro line commissioned new signalling equipment."
    observations = []
    result = ScopeClassifier(lambda _request: mismatch).classify(
        _evidence(source), observation_hook=observations.append
    )
    assert result.state is ScopeState.OUT_OF_SCOPE
    assert observations[0].first_rejection_predicate == "TARGET_SYSTEM_CONTAINMENT"

    contradictory = _semantic_proposal(POSITIVE_SOURCE, action_status="UNESTABLISHED")
    observations.clear()
    result = ScopeClassifier(lambda _request: contradictory).classify(
        _evidence(POSITIVE_SOURCE), observation_hook=observations.append
    )
    assert result.state is ScopeState.OUT_OF_SCOPE
    assert observations[0].first_rejection_predicate == "POSITIVE_ACCEPTANCE_CONDITION"


def test_status_conditional_empty_quotes_are_accepted_without_fabricated_spans():
    proposal = _semantic_proposal(POSITIVE_SOURCE)
    proposal["ambiguity"]["quote"] = ""
    proposal["noneligible_relation"]["quote"] = ""
    observations = []
    result = ScopeClassifier(lambda _request: proposal).classify(
        _evidence(POSITIVE_SOURCE), observation_hook=observations.append
    )
    assert result.state is ScopeState.IN_SCOPE
    assert observations[0].first_rejection_predicate is None
    assert "ambiguity" not in result.provenance["relation_support"]
    assert "noneligible_relation" not in result.provenance["relation_support"]


def test_unestablished_target_system_accepts_empty_quotes_and_fails_closed():
    content = "The operator installed platform doors near an unidentified transit facility."
    proposal = _semantic_proposal(content, decision="UNCERTAIN")
    proposal["system"] = {"label": "", "quote": ""}
    proposal["target_system"] = {"status": "UNESTABLISHED", "relation": "UNRESOLVED", "quote": ""}
    observations = []
    result = ScopeClassifier(lambda _request: proposal).classify(
        _evidence(content), observation_hook=observations.append
    )
    assert result.state is ScopeState.OUT_OF_SCOPE
    assert result.diagnostic is ScopeDiagnostic.SCOPE_NOT_ESTABLISHED
    assert observations[0].first_rejection_predicate is None
    assert "system" not in result.provenance["relation_support"]
    assert "target_system" not in result.provenance["relation_support"]


def test_unestablished_action_target_accepts_empty_relation_quote():
    proposal = _semantic_proposal(POSITIVE_SOURCE, decision="UNCERTAIN")
    proposal["action_target"] = {"status": "UNESTABLISHED", "relation": "UNRESOLVED", "quote": ""}
    observations = []
    result = ScopeClassifier(lambda _request: proposal).classify(
        _evidence(POSITIVE_SOURCE), observation_hook=observations.append
    )
    assert result.state is ScopeState.OUT_OF_SCOPE
    assert observations[0].first_rejection_predicate is None
    assert "action_target" not in result.provenance["relation_support"]


def test_established_positive_target_system_requires_exact_quote():
    proposal = _semantic_proposal(POSITIVE_SOURCE)
    proposal["target_system"]["quote"] = ""
    observations = []
    result = ScopeClassifier(lambda _request: proposal).classify(
        _evidence(POSITIVE_SOURCE), observation_hook=observations.append
    )
    assert result.state is ScopeState.OUT_OF_SCOPE
    assert observations[0].first_rejection_predicate == "QUOTE_MISSING"


def test_positive_relation_with_nonexistent_quote_is_rejected():
    proposal = _semantic_proposal(POSITIVE_SOURCE)
    proposal["action_target"]["quote"] = "installed the signal doors on the Metro line"
    observations = []
    result = ScopeClassifier(lambda _request: proposal).classify(
        _evidence(POSITIVE_SOURCE), observation_hook=observations.append
    )
    assert result.state is ScopeState.OUT_OF_SCOPE
    assert observations[0].first_rejection_predicate == "QUOTE_NOT_FOUND"


def test_established_relation_with_wrong_endpoint_is_rejected():
    content = "The operator installed platform doors. The Metro line serves the central district."
    proposal = _semantic_proposal(
        content,
        action="installed",
        target="platform doors",
        system="Metro line",
    )
    proposal["target_system"]["quote"] = "The Metro line serves the central district."
    observations = []
    result = ScopeClassifier(lambda _request: proposal).classify(
        _evidence(content), observation_hook=observations.append
    )
    assert result.state is ScopeState.OUT_OF_SCOPE
    assert observations[0].first_rejection_predicate == "TARGET_SYSTEM_CONTAINMENT"


def test_location_only_relation_cannot_promote_scope():
    content = "The city installed public sculptures at the Metro station for the neighboring park."
    proposal = _semantic_proposal(
        content,
        decision="IN_SCOPE_SUPPORT",
        action="installed",
        target="public sculptures",
        system="Metro station",
    )
    proposal["target_system"] = {
        "status": "ESTABLISHED",
        "relation": "LOCATED_AT",
        "quote": "public sculptures at the Metro station",
    }
    result = ScopeClassifier(lambda _request: proposal).classify(_evidence(content))
    assert result.state is ScopeState.OUT_OF_SCOPE
    assert result.diagnostic is ScopeDiagnostic.SCOPE_NOT_ESTABLISHED


@pytest.mark.parametrize("relation", ["OWNED_BY", "OPERATED_BY"])
def test_operator_or_ownership_relation_cannot_promote_scope(relation):
    proposal = _semantic_proposal(POSITIVE_SOURCE)
    proposal["target_system"]["relation"] = relation
    result = ScopeClassifier(lambda _request: proposal).classify(_evidence(POSITIVE_SOURCE))
    assert result.state is ScopeState.OUT_OF_SCOPE
    assert result.diagnostic is ScopeDiagnostic.SCOPE_NOT_ESTABLISHED


def test_nonempty_optional_quote_is_still_validated():
    proposal = _semantic_proposal(POSITIVE_SOURCE)
    proposal["ambiguity"]["quote"] = "no ambiguity is stated here"
    observations = []
    result = ScopeClassifier(lambda _request: proposal).classify(
        _evidence(POSITIVE_SOURCE), observation_hook=observations.append
    )
    assert result.state is ScopeState.OUT_OF_SCOPE
    assert observations[0].first_rejection_predicate == "QUOTE_NOT_FOUND"


def test_conflicting_relation_requires_a_source_quotation():
    proposal = _semantic_proposal(POSITIVE_SOURCE, decision="UNCERTAIN")
    proposal["action_target"] = {"status": "CONFLICTING", "relation": "AFFECTS", "quote": ""}
    observations = []
    result = ScopeClassifier(lambda _request: proposal).classify(
        _evidence(POSITIVE_SOURCE), observation_hook=observations.append
    )
    assert result.state is ScopeState.OUT_OF_SCOPE
    assert observations[0].first_rejection_predicate == "QUOTE_MISSING"


def test_noneligible_diagnostic_requires_relevant_source_quote():
    content = "The city installed public sculptures at the Metro station for the neighboring park."
    proposal = _semantic_proposal(
        content,
        decision="OUT_OF_SCOPE_SUPPORT",
        mode="NON_ELIGIBLE",
        action="installed",
        target="public sculptures",
        system="Metro station",
        noneligible_status="PRESENT",
        noneligible_kind="NON_URBAN_RAIL",
    )
    proposal["noneligible_relation"]["quote"] = "for the neighboring park"
    observations = []
    result = ScopeClassifier(lambda _request: proposal).classify(
        _evidence(content), observation_hook=observations.append
    )
    assert result.state is ScopeState.OUT_OF_SCOPE
    assert result.diagnostic is ScopeDiagnostic.SCOPE_NOT_ESTABLISHED
    assert observations[0].first_rejection_predicate == "NONELIGIBLE_RELATION_ENDPOINT"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("event_status", "CONDITIONAL"),
        ("event_status", "NEGATED"),
        ("ambiguity.status", "CONFLICTING"),
    ],
)
def test_conflicting_conditional_and_negated_claims_remain_fail_closed(field, value):
    proposal = _semantic_proposal(POSITIVE_SOURCE)
    if field == "ambiguity.status":
        proposal["ambiguity"]["status"] = value
        proposal["ambiguity"]["quote"] = "The operator installed platform doors on the Metro line."
    else:
        proposal[field] = value
    observations = []
    result = ScopeClassifier(lambda _request: proposal).classify(
        _evidence(POSITIVE_SOURCE), observation_hook=observations.append
    )
    assert result.state is ScopeState.OUT_OF_SCOPE
    assert observations[0].first_rejection_predicate == "POSITIVE_ACCEPTANCE_CONDITION"


def test_meaningful_action_target_and_system_quotes_preserve_positive_acceptance():
    content = "The operator fitted platform doors as a component of the Metro line."
    proposal = {
        "candidate_id": "C1",
        "schema_version": SCOPE_PROPOSAL_SCHEMA_VERSION,
        "event_focus": {"status": "RESOLVED", "quote": content},
        "action": {"label": "fitted", "quote": "fitted"},
        "target": {"label": "platform doors", "quote": "platform doors"},
        "system": {"label": "Metro line", "quote": "Metro line"},
        "eligible_mode_family": "METRO",
        "action_target": {"status": "ESTABLISHED", "relation": "AFFECTS", "quote": "fitted platform doors"},
        "target_system": {"status": "ESTABLISHED", "relation": "PART_OF", "quote": "platform doors as a component of the Metro line"},
        "ambiguity": {"status": "NONE", "quote": ""},
        "noneligible_relation": {"status": "ABSENT", "quote": ""},
        "noneligible_kind": "NONE",
        "event_status": "ASSERTED",
        "decision": "IN_SCOPE_SUPPORT",
    }
    result = ScopeClassifier(lambda _request: proposal).classify(_evidence(content))
    assert result.state is ScopeState.IN_SCOPE
    assert result.diagnostic is ScopeDiagnostic.NONE


def test_existing_citation_can_pass_mechanical_checks_without_proving_semantics(capture_artifact):
    # The quote exists, but "at the Metro station" supports location only.
    # The current owner checks structure and relation labels, not semantic truth.
    proposal = _semantic_proposal(
        NEGATIVE_SOURCE,
        action="installed",
        target="public sculptures",
        system="Metro station",
        system_relation="BELONGS_TO",
    )
    result = ScopeClassifier(lambda _request: proposal).classify(_evidence(NEGATIVE_SOURCE))
    assert result.state is ScopeState.IN_SCOPE

    artifact_path = capture_artifact(
        _case(NEGATIVE_SOURCE, case_id="citation-limitation"),
        lambda _request: proposal,
        run_id="semantic-review",
        code_revision="a" * 40,
    )
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert artifact["semantic_acceptance_status"] == "REQUIRES_INDEPENDENT_SEMANTIC_REVIEW"
    assert replay_artifact(artifact_path)["replay_status"] == "PASS"


def test_capture_stores_complete_proposal_and_replay_makes_no_provider_call(capture_artifact):
    proposal = _semantic_proposal(POSITIVE_SOURCE)
    calls = []

    def provider(request):
        calls.append(request)
        return proposal

    artifact_path = capture_artifact(
        _case(), provider, run_id="offline-replay", code_revision="b" * 40
    )
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    production_result = ScopeClassifier(lambda _request: proposal).classify(_evidence(POSITIVE_SOURCE))
    assert artifact["provider_response_parse_status"] == "PARSED"
    assert artifact["provider_proposal"] == proposal
    assert artifact["provider_proposal"]["action"]["quote"] == "installed"
    assert artifact["source_content"] == POSITIVE_SOURCE
    assert artifact["source_content_sha256"]
    assert artifact["first_rejection_predicate"] is None
    assert artifact["python_scope_state"] == "IN_SCOPE"
    assert artifact["python_scope_state"] == production_result.state.value
    assert artifact["python_scope_diagnostic"] == production_result.diagnostic.value
    assert len(calls) == 1

    assert replay_artifact(artifact_path) == {
        "replay_status": "PASS",
        "provider_response_parse_status": "PARSED",
        "owner_replay_status": "PASS",
        "scope_state": "IN_SCOPE",
        "diagnostic": "NONE",
        "first_rejection_predicate": None,
        "provider_call_count": 0,
    }
    assert len(calls) == 1


def test_replay_reproduces_the_first_owner_rejection(capture_artifact):
    proposal = _semantic_proposal(POSITIVE_SOURCE)
    proposal["action"]["quote"] = "missing endpoint"
    artifact_path = capture_artifact(
        _case(case_id="owner-rejection"),
        lambda _request: proposal,
        run_id="rejection-replay",
        code_revision="c" * 40,
    )
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert artifact["first_rejection_predicate"] == "QUOTE_NOT_FOUND"
    replay = replay_artifact(artifact_path)
    assert replay["replay_status"] == "PASS"
    assert replay["first_rejection_predicate"] == "QUOTE_NOT_FOUND"
    assert replay["provider_call_count"] == 0

    artifact["candidate_title"] = "changed after capture"
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
    tampered_replay = replay_artifact(artifact_path)
    assert tampered_replay["replay_status"] == "FAIL"
    assert tampered_replay["reason"] == "REQUEST_IDENTITY_DIGEST_MISMATCH"


def test_provider_parse_failure_is_distinguished_and_safe(capture_artifact):
    case = _case(case_id="parse-failure")

    def provider(_request):
        raise MaiAgentScopeProviderFailure(
            "MaiAgent Scope provider response was invalid", failure_category="RESPONSE_PARSE"
        )

    artifact_path = capture_artifact(
        case,
        provider,
        run_id="parse-status",
        code_revision="d" * 40,
    )
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert artifact["provider_response_parse_status"] == "FAILED"
    assert artifact["technical_failure_category"] == "RESPONSE_PARSE"
    assert "provider_proposal" in artifact and artifact["provider_proposal"] is None
    assert replay_artifact(artifact_path)["provider_call_count"] == 0
    assert replay_artifact(artifact_path)["replay_status"] == "BLOCKED"
    assert replay_artifact(artifact_path)["provider_response_parse_status"] == "FAILED"
    assert replay_artifact(artifact_path)["owner_replay_status"] == "NOT_REPLAYABLE"


def test_capture_blocks_secret_values_and_observation_cannot_change_decision(capture_artifact):
    secret = "PRIVATE_CHATBOT_CONFIGURATION"
    unsafe_proposal = _semantic_proposal(POSITIVE_SOURCE)
    unsafe_proposal["private_note"] = secret
    artifact_path = capture_artifact(
        _case(case_id="secret-block"),
        lambda _request: unsafe_proposal,
        run_id="safe-artifact",
        code_revision="e" * 40,
        secret_values=(secret,),
    )
    artifact_text = artifact_path.read_text(encoding="utf-8")
    artifact = json.loads(artifact_text)
    assert secret not in artifact_text
    assert artifact["provider_response_parse_status"] == "PARSED_CAPTURE_BLOCKED"
    assert artifact["acceptance_status"] == "CAPTURE_INCOMPLETE"

    proposal = _semantic_proposal(POSITIVE_SOURCE)
    expected = ScopeClassifier(lambda _request: proposal).classify(_evidence(POSITIVE_SOURCE))

    def broken_observer(_observation):
        raise RuntimeError("observer failure")

    observed = ScopeClassifier(lambda _request: proposal).classify(
        _evidence(POSITIVE_SOURCE), observation_hook=broken_observer
    )
    assert observed == expected


def test_private_acceptance_directory_is_ignored_by_git():
    from pathlib import Path

    ignore_lines = (Path(__file__).resolve().parents[1] / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "/.scope-acceptance-*.json" in ignore_lines
