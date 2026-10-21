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
        "action": {"label": action},
        "target": {"label": target},
        "system": {"label": system},
        "eligible_mode_family": mode,
        "action_target": {"status": action_status, "relation": action_relation, "quote": content},
        "target_system": {"status": system_status, "relation": system_relation, "quote": content, "target_reference": target},
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


def test_labels_anchored_in_one_relation_quote_accept_distinguishable_roles():
    source = "The operator installs platform doors on the Metro system."
    shared_quote = "installs platform doors"
    proposal = _semantic_proposal(
        source,
        action="installs",
        target="platform doors",
        system="Metro system",
    )
    proposal["action_target"]["quote"] = shared_quote
    proposal["target_system"]["quote"] = "installs platform doors on the Metro system"
    observations = []

    result = ScopeClassifier(lambda _request: proposal).classify(
        _evidence(source), observation_hook=observations.append
    )

    assert result.state is ScopeState.IN_SCOPE
    assert observations[0].first_rejection_predicate is None


def test_endpoint_label_outside_its_relation_quote_is_rejected():
    source = "The operator installs platform doors on the Metro system."
    proposal = _semantic_proposal(
        source,
        action="installs",
        target="Metro",
        system="Metro system",
    )
    proposal["action_target"]["quote"] = "installs platform doors"
    observations = []

    result = ScopeClassifier(lambda _request: proposal).classify(
        _evidence(source), observation_hook=observations.append
    )

    assert result.state is ScopeState.OUT_OF_SCOPE
    assert observations[0].first_rejection_predicate == "ACTION_TARGET_CONTAINMENT"

    invented = _semantic_proposal(source, target="platform screens")
    observations.clear()
    result = ScopeClassifier(lambda _request: invented).classify(
        _evidence(source), observation_hook=observations.append
    )
    assert result.state is ScopeState.OUT_OF_SCOPE
    assert observations[0].first_rejection_predicate == "ENDPOINT_LABEL"


def test_uncertain_proposal_with_shared_distinguishable_quotes_remains_out_of_scope():
    source = "合成技術公告。地下鉄事業者は駅のホームドア監視システムを導入し、試験結果と運用開始を発表した。本文は都市鉄道の地下鉄システムとその技術措置を明確に説明している。"
    event = "地下鉄事業者は駅のホームドア監視システムを導入し"
    proposal = _semantic_proposal(
        source,
        decision="UNCERTAIN",
        mode="UNKNOWN",
        action="導入",
        target="ホームドア監視システム",
        system="地下鉄システム",
    )
    proposal["event_focus"] = {"status": "RESOLVED", "quote": event}
    proposal["action_target"]["quote"] = event
    proposal["target_system"] = {"status": "UNESTABLISHED", "relation": "UNRESOLVED", "quote": "", "target_reference": ""}
    observations = []

    result = ScopeClassifier(lambda _request: proposal).classify(
        _evidence(source), observation_hook=observations.append
    )

    assert result.state is ScopeState.OUT_OF_SCOPE
    assert result.diagnostic is ScopeDiagnostic.SCOPE_NOT_ESTABLISHED
    assert observations[0].first_rejection_predicate is None
    assert observations[0].response_status == "OWNER_VALIDATED"


def test_first_actual_rejection_is_recorded_for_invalid_quotes_and_candidate_identity():
    bad_quote = _semantic_proposal(POSITIVE_SOURCE)
    bad_quote["action_target"]["quote"] = "not present in the source"
    observations = []
    result = ScopeClassifier(lambda _request: bad_quote).classify(
        _evidence(POSITIVE_SOURCE), observation_hook=observations.append
    )
    assert result.state is ScopeState.OUT_OF_SCOPE
    assert observations[0].first_rejection_predicate == "QUOTE_NOT_FOUND"

    # RC-3: a repeated string is no longer rejected for repetition; the
    # system endpoint is accepted only inside the relation quotation that
    # establishes it, and its provenance is bounded to that context.
    repeated_source = "The Metro operator installed platform doors on the Metro line."
    repeated = _semantic_proposal(
        repeated_source,
        action="installed",
        target="platform doors",
        system="Metro",
    )
    repeated["target_system"]["quote"] = "platform doors on the Metro line"
    observations.clear()
    result = ScopeClassifier(lambda _request: repeated).classify(
        _evidence(repeated_source), observation_hook=observations.append
    )
    assert observations[0].first_rejection_predicate is None
    assert result.state is ScopeState.IN_SCOPE
    line_metro = repeated_source.index("Metro line")
    assert result.provenance["relation_support"]["system"] == [
        {"start": line_metro, "end": line_metro + len("Metro")}
    ]

    # Repeated text cannot stitch a relation across unrelated contexts: the
    # system endpoint must lie inside the target-system quotation.
    stitched = _semantic_proposal(repeated_source, system="Metro operator")
    stitched["target_system"]["quote"] = "platform doors on the Metro line"
    observations.clear()
    result = ScopeClassifier(lambda _request: stitched).classify(
        _evidence(repeated_source), observation_hook=observations.append
    )
    assert result.state is ScopeState.OUT_OF_SCOPE
    assert observations[0].first_rejection_predicate == "TARGET_SYSTEM_CONTAINMENT"

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
    proposal["system"] = {"label": ""}
    proposal["target_system"] = {"status": "UNESTABLISHED", "relation": "UNRESOLVED", "quote": "", "target_reference": ""}
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


def test_positive_relation_cannot_borrow_system_from_another_event():
    source = "The Metro line renewed signalling equipment. The port installed cargo monitors for harbor businesses."
    candidate_event = "The port installed cargo monitors for harbor businesses."
    shared_quote = "installed cargo monitors"
    proposal = _semantic_proposal(
        source,
        action="installed",
        target="cargo monitors",
        system="Metro line",
    )
    proposal["event_focus"] = {"status": "RESOLVED", "quote": candidate_event}
    proposal["action_target"]["quote"] = candidate_event
    proposal["target_system"]["quote"] = source
    observations = []

    result = ScopeClassifier(lambda _request: proposal).classify(
        _evidence(source), observation_hook=observations.append
    )

    assert result.state is ScopeState.OUT_OF_SCOPE
    assert observations[0].first_rejection_predicate == "EVENT_FOCUS_CONTAINMENT"


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
        "target_reference": "public sculptures",
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
        "action": {"label": "fitted"},
        "target": {"label": "platform doors"},
        "system": {"label": "Metro line"},
        "eligible_mode_family": "METRO",
        "action_target": {"status": "ESTABLISHED", "relation": "AFFECTS", "quote": "fitted platform doors"},
        "target_system": {"status": "ESTABLISHED", "relation": "PART_OF", "quote": "platform doors as a component of the Metro line", "target_reference": "platform doors"},
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
    assert artifact["provider_proposal"]["action"]["label"] == "installed"
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
    proposal["action_target"]["quote"] = "missing endpoint"
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


def test_target_may_be_the_eligible_system_itself():
    # SC-1: a new line or network is both the affected target and the system.
    source = "Egypt is exploring a hydrogen-powered tram network for its New Administrative Capital."
    proposal = _semantic_proposal(
        source,
        mode="TRAM",
        action="exploring",
        target="a hydrogen-powered tram network",
        system="a hydrogen-powered tram network",
    )
    proposal["action_target"]["quote"] = "Egypt is exploring a hydrogen-powered tram network"
    proposal["target_system"]["quote"] = "a hydrogen-powered tram network"
    observations = []
    result = ScopeClassifier(lambda _request: proposal).classify(
        _evidence(source), observation_hook=observations.append
    )
    assert result.state is ScopeState.IN_SCOPE
    assert observations[0].first_rejection_predicate is None


def test_action_label_must_differ_from_target_label():
    proposal = _semantic_proposal(POSITIVE_SOURCE, action="platform doors")
    observations = []
    result = ScopeClassifier(lambda _request: proposal).classify(
        _evidence(POSITIVE_SOURCE), observation_hook=observations.append
    )
    assert result.state is ScopeState.OUT_OF_SCOPE
    assert observations[0].first_rejection_predicate == "ENDPOINT_ROLE_DISTINCTNESS"


def test_event_on_a_station_platform_of_the_system_is_in_scope():
    # D1: an incident taking place on a platform that belongs to the subway is
    # tied to that system; reportability is decided by Reportability.
    source = "A man died after being shot on a northbound E train platform at the Seventh Avenue-53rd Street subway station."
    proposal = _semantic_proposal(
        source,
        mode="SUBWAY",
        action="shot",
        target="northbound E train platform",
        system="subway station",
        action_relation="LOCATED_AT",
        system_relation="PART_OF",
    )
    proposal["action_target"]["quote"] = "shot on a northbound E train platform"
    proposal["target_system"]["quote"] = "northbound E train platform at the Seventh Avenue-53rd Street subway station"
    result = ScopeClassifier(lambda _request: proposal).classify(_evidence(source))
    assert result.state is ScopeState.IN_SCOPE


def test_location_without_system_membership_stays_out_of_scope():
    # D1 does not turn proximity or a located-at system relation into scope.
    proposal = _semantic_proposal(
        NEGATIVE_SOURCE,
        action="installed",
        target="public sculptures",
        system="Metro station",
        action_relation="LOCATED_AT",
        system_relation="LOCATED_AT",
    )
    result = ScopeClassifier(lambda _request: proposal).classify(_evidence(NEGATIVE_SOURCE))
    assert result.state is ScopeState.OUT_OF_SCOPE
    assert result.diagnostic is ScopeDiagnostic.SCOPE_NOT_ESTABLISHED


def test_noneligible_relation_of_another_action_is_not_a_focus_relation():
    # SC-2: a bus pilot in the same article is not the focus action's
    # noneligible relation; recording it there is an invalid proposal.
    source = "Seoul will add eight express trains on Metro Line 9. The city will also pilot four express bus routes."
    proposal = _semantic_proposal(
        source,
        action="add",
        target="eight express trains",
        system="Metro Line 9",
        noneligible_status="PRESENT",
        noneligible_kind="EXCLUDED_TRANSPORT_MODE",
        mode="NON_ELIGIBLE",
        decision="OUT_OF_SCOPE_SUPPORT",
    )
    proposal["noneligible_relation"]["quote"] = "The city will also pilot four express bus routes."
    observations = []
    result = ScopeClassifier(lambda _request: proposal).classify(
        _evidence(source), observation_hook=observations.append
    )
    assert result.state is ScopeState.OUT_OF_SCOPE
    assert observations[0].first_rejection_predicate == "NONELIGIBLE_RELATION_ENDPOINT"

    focus_only = _semantic_proposal(
        source, action="add", target="eight express trains", system="Metro Line 9"
    )
    focus_only["action_target"]["quote"] = "add eight express trains on Metro Line 9"
    focus_only["target_system"]["quote"] = "eight express trains on Metro Line 9"
    assert ScopeClassifier(lambda _request: focus_only).classify(_evidence(source)).state is ScopeState.IN_SCOPE


def test_endpoint_provenance_records_labels_inside_their_contexts_only():
    source = "The Metro operator installed platform doors on the Metro line."
    proposal = _semantic_proposal(source, system="Metro")
    proposal["action_target"]["quote"] = "installed platform doors"
    proposal["target_system"]["quote"] = "platform doors on the Metro line"
    result = ScopeClassifier(lambda _request: proposal).classify(_evidence(source))
    assert result.state is ScopeState.IN_SCOPE
    support = result.provenance["relation_support"]
    doors = source.index("platform doors")
    assert support["action"] == [{"start": source.index("installed"), "end": source.index("installed") + len("installed")}]
    assert support["target"] == [{"start": doors, "end": doors + len("platform doors")}]
    line_metro = source.index("Metro line")
    assert support["system"] == [{"start": line_metro, "end": line_metro + len("Metro")}]
    assert result.provenance["endpoint_labels"] == {
        "action": "installed", "target": "platform doors", "system": "Metro", "target_reference": "platform doors"
    }


HANOI = (
    "Hanoi has signed contracts to build five metro lines totaling about 253.5 kilometers. "
    "The contractors will handle all stages. The five lines, namely No. 1, 2, 8, 10, and 14, include depots."
)


def _anaphora_proposal(*, focus=HANOI, reference="The five lines", system="five metro lines"):
    proposal = _semantic_proposal(
        HANOI, action="build", target="five metro lines", system=system
    )
    proposal["event_focus"]["quote"] = focus
    proposal["action_target"]["quote"] = "signed contracts to build five metro lines"
    proposal["target_system"] = {
        "status": "ESTABLISHED",
        "relation": "PART_OF",
        "quote": "The five lines, namely No. 1, 2, 8, 10, and 14, include depots.",
        "target_reference": reference,
    }
    return proposal


def test_same_event_reference_to_a_target_that_is_the_system_is_accepted():
    # Legitimate anaphora: the source refers back to "five metro lines" as
    # "The five lines"; no quotation repeating the label is fabricated.
    observations = []
    result = ScopeClassifier(lambda _request: _anaphora_proposal()).classify(
        _evidence(HANOI), observation_hook=observations.append
    )
    assert result.state is ScopeState.IN_SCOPE
    assert observations[0].first_rejection_predicate is None
    reference = HANOI.index("The five lines")
    assert result.provenance["relation_support"]["target_reference"] == [
        {"start": reference, "end": reference + len("The five lines")}
    ]


def test_reference_must_occur_in_the_quote_and_stay_in_the_event_focus():
    absent = _anaphora_proposal(reference="the new lines")
    observations = []
    ScopeClassifier(lambda _request: absent).classify(_evidence(HANOI), observation_hook=observations.append)
    assert observations[0].first_rejection_predicate == "ENDPOINT_LABEL"

    # The reference sentence lies outside the Candidate focus: no borrowing.
    narrow = _anaphora_proposal(focus="Hanoi has signed contracts to build five metro lines totaling about 253.5 kilometers.")
    observations.clear()
    result = ScopeClassifier(lambda _request: narrow).classify(_evidence(HANOI), observation_hook=observations.append)
    assert result.state is ScopeState.OUT_OF_SCOPE
    assert observations[0].first_rejection_predicate == "EVENT_FOCUS_CONTAINMENT"

    # A distinct system must still be named inside the target-system quotation.
    other_system = _anaphora_proposal(system="Hanoi")
    observations.clear()
    result = ScopeClassifier(lambda _request: other_system).classify(_evidence(HANOI), observation_hook=observations.append)
    assert result.state is ScopeState.OUT_OF_SCOPE
    assert observations[0].first_rejection_predicate == "TARGET_SYSTEM_CONTAINMENT"


def test_omitted_target_reference_means_the_target_label():
    proposal = _semantic_proposal(POSITIVE_SOURCE)
    del proposal["target_system"]["target_reference"]
    assert ScopeClassifier(lambda _request: proposal).classify(_evidence(POSITIVE_SOURCE)).state is ScopeState.IN_SCOPE

    missing_label = _semantic_proposal(POSITIVE_SOURCE)
    del missing_label["target_system"]["target_reference"]
    missing_label["target_system"]["quote"] = "on the Metro line"
    observations = []
    ScopeClassifier(lambda _request: missing_label).classify(_evidence(POSITIVE_SOURCE), observation_hook=observations.append)
    assert observations[0].first_rejection_predicate == "TARGET_SYSTEM_CONTAINMENT"


def test_operator_service_reference_cannot_turn_buses_into_urban_rail():
    source = "The Metro operator bought new buses. The buses will serve suburban routes."
    proposal = _semantic_proposal(
        source, decision="IN_SCOPE_SUPPORT", action="bought", target="new buses", system="Metro operator",
        system_relation="OPERATED_BY",
    )
    proposal["target_system"]["target_reference"] = "new buses"
    result = ScopeClassifier(lambda _request: proposal).classify(_evidence(source))
    assert result.state is ScopeState.OUT_OF_SCOPE


def test_private_acceptance_directory_is_ignored_by_git():
    from pathlib import Path

    ignore_lines = (Path(__file__).resolve().parents[1] / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "/.scope-acceptance-*.json" in ignore_lines
