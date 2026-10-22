"""Acceptance evidence and replay tests, separate from mechanical schema fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from scripts.scope_acceptance import capture_case, replay_artifact
from src.weekly_report.contracts import EvidenceResult, EvidenceState, ScopeDiagnostic, ScopeState
from src.weekly_report.evidence_sentences import segment_evidence_sentences
from src.weekly_report.maiagent_scope_provider import MaiAgentScopeProviderFailure
from src.weekly_report.scope_classifier import SCOPE_PROPOSAL_SCHEMA_VERSION, ScopeClassifier, ScopeProposalViolation



@pytest.fixture
def capture_artifact(tmp_path):
    def capture(case, provider, **kwargs):
        kwargs["run_id"] = f"test-{uuid4().hex}-{kwargs['run_id']}"
        kwargs["artifact_directory"] = tmp_path
        return capture_case(case, provider, **kwargs)

    return capture


POSITIVE_SOURCE = "The operator installed platform doors on the Metro line."
NEGATIVE_SOURCE = "The city installed public sculptures at the Metro station for the neighboring park."


def _evidence(content: str, candidate_id: str = "C1") -> EvidenceResult:
    return EvidenceResult(
        candidate_id=candidate_id,
        state=EvidenceState.READY,
        substantive_content=content,
        provenance={"source_identity": "synthetic-fixture"},
    )


def _ids(content: str) -> list[str]:
    return [sentence.sentence_id for sentence in segment_evidence_sentences(content)]


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
    ids = _ids(content)
    return {
        "candidate_id": candidate_id,
        "schema_version": SCOPE_PROPOSAL_SCHEMA_VERSION,
        "event_focus": {"status": "RESOLVED", "sentence_ids": ids},
        "action": {"label": action},
        "target": {"label": target},
        "system": {"label": system},
        "eligible_mode_family": mode,
        "action_target": {"status": action_status, "relation": action_relation, "sentence_ids": ids},
        "target_system": {"status": system_status, "relation": system_relation, "sentence_ids": ids},
        "ambiguity": {"status": "NONE", "sentence_ids": []},
        "noneligible_relation": {"status": noneligible_status, "sentence_ids": ids if noneligible_status == "PRESENT" else []},
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


def _classify(proposal: dict, content: str, observations: list | None = None):
    return ScopeClassifier(lambda _request: proposal).classify(
        _evidence(content), observation_hook=None if observations is None else observations.append
    )


def _violation(proposal: dict, content: str) -> str:
    with pytest.raises(ScopeProposalViolation) as caught:
        _classify(proposal, content)
    return caught.value.failure_class


def test_semantic_endpoints_support_a_real_positive_and_valid_negative():
    assert _classify(_semantic_proposal(POSITIVE_SOURCE), POSITIVE_SOURCE).state is ScopeState.IN_SCOPE

    negative = _semantic_proposal(
        NEGATIVE_SOURCE,
        decision="OUT_OF_SCOPE_SUPPORT",
        target="public sculptures",
        system="Metro station",
        system_relation="LOCATED_AT",
    )
    result = _classify(negative, NEGATIVE_SOURCE)
    assert result.state is ScopeState.OUT_OF_SCOPE
    assert result.diagnostic is ScopeDiagnostic.SCOPE_NOT_ESTABLISHED


def test_labels_inside_one_cited_sentence_accept_distinguishable_roles():
    source = "The operator installs platform doors on the Metro system."
    observations = []
    result = _classify(_semantic_proposal(source, action="installs", system="Metro system"), source, observations)
    assert result.state is ScopeState.IN_SCOPE
    assert observations[0].first_rejection_predicate is None


def test_endpoint_label_outside_its_relation_sentences_is_a_violation():
    source = "The operator installs platform doors. The doors serve the Metro system."
    proposal = _semantic_proposal(source, action="installs", target="Metro", system="Metro system")
    proposal["action_target"]["sentence_ids"] = ["S1"]
    assert _violation(proposal, source) == "ACTION_TARGET_CONTAINMENT"

    invented = _semantic_proposal(source, action="installs", target="platform screens", system="Metro system")
    assert _violation(invented, source) == "ENDPOINT_LABEL"


def test_uncertain_proposal_remains_a_validated_out_of_scope():
    source = "合成技術公告。地下鉄事業者は駅のホームドア監視システムを導入し、試験結果と運用開始を発表した。本文は都市鉄道の地下鉄システムとその技術措置を明確に説明している。"
    proposal = _semantic_proposal(
        source, decision="UNCERTAIN", mode="UNKNOWN", action="導入", target="ホームドア監視システム", system="地下鉄システム"
    )
    proposal["event_focus"]["sentence_ids"] = ["S2"]
    proposal["action_target"]["sentence_ids"] = ["S2"]
    proposal["target_system"] = {"status": "UNESTABLISHED", "relation": "UNRESOLVED", "sentence_ids": []}
    observations = []
    result = _classify(proposal, source, observations)
    assert result.state is ScopeState.OUT_OF_SCOPE
    assert result.diagnostic is ScopeDiagnostic.SCOPE_NOT_ESTABLISHED
    assert observations[0].first_rejection_predicate is None
    assert observations[0].response_status == "OWNER_VALIDATED"


def test_invalid_citation_and_identity_are_violations_and_provenance_is_bounded():
    bad = _semantic_proposal(POSITIVE_SOURCE)
    bad["action_target"]["sentence_ids"] = ["S9"]
    observations = []
    with pytest.raises(ScopeProposalViolation):
        _classify(bad, POSITIVE_SOURCE, observations)
    assert observations[0].first_rejection_predicate == "CITATION_INVALID"

    # A repeated string elsewhere is never support: the system label is
    # recorded only inside the sentence cited by the target-system relation.
    source = "The Metro operator won an award. It installed platform doors on the Metro line."
    repeated = _semantic_proposal(source, system="Metro")
    repeated["event_focus"]["sentence_ids"] = ["S2"]
    repeated["action_target"]["sentence_ids"] = ["S2"]
    repeated["target_system"]["sentence_ids"] = ["S2"]
    result = _classify(repeated, source)
    assert result.state is ScopeState.IN_SCOPE
    line_metro = source.index("Metro line")
    assert result.provenance["relation_support"]["system"] == [{"start": line_metro, "end": line_metro + len("Metro")}]

    stitched = _semantic_proposal(source, system="Metro operator")
    stitched["target_system"]["sentence_ids"] = ["S2"]
    assert _violation(stitched, source) == "TARGET_SYSTEM_CONTAINMENT"

    assert _violation(_semantic_proposal(POSITIVE_SOURCE, candidate_id="C2"), POSITIVE_SOURCE) == "CANDIDATE_ID"


def test_relation_endpoint_mismatch_is_a_violation_and_contradiction_stays_out():
    source = "The operator installed platform doors. The Metro line commissioned new signalling equipment."
    mismatch = _semantic_proposal(source)
    mismatch["target_system"]["sentence_ids"] = ["S2"]
    assert _violation(mismatch, source) == "TARGET_SYSTEM_CONTAINMENT"

    contradictory = _semantic_proposal(POSITIVE_SOURCE, action_status="UNESTABLISHED")
    observations = []
    result = _classify(contradictory, POSITIVE_SOURCE, observations)
    assert result.state is ScopeState.OUT_OF_SCOPE
    assert observations[0].first_rejection_predicate == "POSITIVE_ACCEPTANCE_CONDITION"


def test_status_conditional_empty_citations_are_accepted_without_fabricated_spans():
    result = _classify(_semantic_proposal(POSITIVE_SOURCE), POSITIVE_SOURCE)
    assert result.state is ScopeState.IN_SCOPE
    assert "ambiguity" not in result.provenance["relation_support"]
    assert "noneligible_relation" not in result.provenance["relation_support"]


def test_unestablished_target_system_accepts_empty_citation_and_stays_out():
    content = "The operator installed platform doors near an unidentified transit facility."
    proposal = _semantic_proposal(content, decision="UNCERTAIN")
    proposal["system"] = {"label": ""}
    proposal["target_system"] = {"status": "UNESTABLISHED", "relation": "UNRESOLVED", "sentence_ids": []}
    observations = []
    result = _classify(proposal, content, observations)
    assert result.state is ScopeState.OUT_OF_SCOPE
    assert result.diagnostic is ScopeDiagnostic.SCOPE_NOT_ESTABLISHED
    assert observations[0].first_rejection_predicate is None
    assert "system" not in result.provenance["relation_support"]
    assert "target_system" not in result.provenance["relation_support"]


def test_unestablished_action_target_accepts_empty_citation():
    proposal = _semantic_proposal(POSITIVE_SOURCE, decision="UNCERTAIN")
    proposal["action_target"] = {"status": "UNESTABLISHED", "relation": "UNRESOLVED", "sentence_ids": []}
    result = _classify(proposal, POSITIVE_SOURCE)
    assert result.state is ScopeState.OUT_OF_SCOPE
    assert "action_target" not in result.provenance["relation_support"]


def test_established_relation_requires_a_citation():
    proposal = _semantic_proposal(POSITIVE_SOURCE)
    proposal["target_system"]["sentence_ids"] = []
    assert _violation(proposal, POSITIVE_SOURCE) == "CITATION_MISSING"

    conflicting = _semantic_proposal(POSITIVE_SOURCE, decision="UNCERTAIN")
    conflicting["action_target"] = {"status": "CONFLICTING", "relation": "AFFECTS", "sentence_ids": []}
    assert _violation(conflicting, POSITIVE_SOURCE) == "CITATION_MISSING"


def test_nonempty_optional_citation_is_still_validated():
    proposal = _semantic_proposal(POSITIVE_SOURCE)
    proposal["ambiguity"]["sentence_ids"] = ["S7"]
    assert _violation(proposal, POSITIVE_SOURCE) == "CITATION_INVALID"


def test_positive_relation_cannot_borrow_system_from_another_event():
    source = "The Metro line renewed signalling equipment. The port installed cargo monitors for harbor businesses."
    proposal = _semantic_proposal(source, target="cargo monitors")
    proposal["event_focus"]["sentence_ids"] = ["S2"]
    proposal["action_target"]["sentence_ids"] = ["S2"]
    proposal["target_system"]["sentence_ids"] = ["S1", "S2"]
    assert _violation(proposal, source) == "EVENT_FOCUS_CONTAINMENT"


def test_location_only_relation_cannot_promote_scope():
    proposal = _semantic_proposal(NEGATIVE_SOURCE, target="public sculptures", system="Metro station", system_relation="LOCATED_AT")
    result = _classify(proposal, NEGATIVE_SOURCE)
    assert result.state is ScopeState.OUT_OF_SCOPE
    assert result.diagnostic is ScopeDiagnostic.SCOPE_NOT_ESTABLISHED


@pytest.mark.parametrize("relation", ["OWNED_BY", "OPERATED_BY"])
def test_operator_or_ownership_relation_cannot_promote_scope(relation):
    result = _classify(_semantic_proposal(POSITIVE_SOURCE, system_relation=relation), POSITIVE_SOURCE)
    assert result.state is ScopeState.OUT_OF_SCOPE
    assert result.diagnostic is ScopeDiagnostic.SCOPE_NOT_ESTABLISHED


def test_noneligible_diagnostic_requires_the_focus_target_or_system():
    source = "The city installed public sculptures at the Metro station. This serves the neighboring park."
    proposal = _semantic_proposal(
        source,
        decision="OUT_OF_SCOPE_SUPPORT",
        mode="NON_ELIGIBLE",
        target="public sculptures",
        system="Metro station",
        noneligible_status="PRESENT",
        noneligible_kind="NON_URBAN_RAIL",
    )
    proposal["noneligible_relation"]["sentence_ids"] = ["S2"]
    assert _violation(proposal, source) == "NONELIGIBLE_RELATION_ENDPOINT"


@pytest.mark.parametrize(
    ("field", "value"),
    [("event_status", "CONDITIONAL"), ("event_status", "NEGATED"), ("ambiguity.status", "CONFLICTING")],
)
def test_conflicting_conditional_and_negated_claims_remain_out_of_scope(field, value):
    proposal = _semantic_proposal(POSITIVE_SOURCE)
    if field == "ambiguity.status":
        proposal["ambiguity"] = {"status": value, "sentence_ids": ["S1"]}
    else:
        proposal[field] = value
    observations = []
    result = _classify(proposal, POSITIVE_SOURCE, observations)
    assert result.state is ScopeState.OUT_OF_SCOPE
    assert observations[0].first_rejection_predicate == "POSITIVE_ACCEPTANCE_CONDITION"


def test_meaningful_action_target_and_system_citations_preserve_positive_acceptance():
    content = "The operator fitted platform doors. The platform doors are a component of the Metro line."
    proposal = _semantic_proposal(content, action="fitted", system="Metro line", system_relation="PART_OF")
    proposal["action_target"]["sentence_ids"] = ["S1"]
    proposal["target_system"]["sentence_ids"] = ["S2"]
    result = _classify(proposal, content)
    assert result.state is ScopeState.IN_SCOPE
    assert result.diagnostic is ScopeDiagnostic.NONE


def test_existing_citation_can_pass_mechanical_checks_without_proving_semantics(capture_artifact):
    # The citation exists, but "at the Metro station" supports location only.
    # The owner checks structure and relation labels, not semantic truth.
    proposal = _semantic_proposal(NEGATIVE_SOURCE, target="public sculptures", system="Metro station", system_relation="BELONGS_TO")
    assert _classify(proposal, NEGATIVE_SOURCE).state is ScopeState.IN_SCOPE

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

    artifact_path = capture_artifact(_case(), provider, run_id="offline-replay", code_revision="b" * 40)
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    production_result = _classify(proposal, POSITIVE_SOURCE)
    assert artifact["provider_response_parse_status"] == "PARSED"
    assert artifact["provider_proposal"] == proposal
    assert artifact["provider_proposal"]["action"]["label"] == "installed"
    assert artifact["source_content"] == POSITIVE_SOURCE
    assert artifact["source_content_sha256"]
    assert artifact["first_rejection_predicate"] is None
    assert artifact["python_scope_state"] == production_result.state.value == "IN_SCOPE"
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


def test_replay_reproduces_a_proposal_violation(capture_artifact):
    proposal = _semantic_proposal(POSITIVE_SOURCE)
    proposal["action_target"]["sentence_ids"] = ["S5"]
    artifact_path = capture_artifact(
        _case(case_id="owner-rejection"), lambda _request: proposal, run_id="rejection-replay", code_revision="c" * 40
    )
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert artifact["first_rejection_predicate"] == "CITATION_INVALID"
    assert artifact["python_scope_state"] == "PROPOSAL_VIOLATION"
    assert artifact["acceptance_status"] == "PROPOSAL_CONTRACT_VIOLATION"
    replay = replay_artifact(artifact_path)
    assert replay["replay_status"] == "PASS"
    assert replay["first_rejection_predicate"] == "CITATION_INVALID"
    assert replay["provider_call_count"] == 0

    artifact["candidate_title"] = "changed after capture"
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
    tampered_replay = replay_artifact(artifact_path)
    assert tampered_replay["replay_status"] == "FAIL"
    assert tampered_replay["reason"] == "REQUEST_IDENTITY_DIGEST_MISMATCH"


def test_provider_parse_failure_is_distinguished_and_safe(capture_artifact):
    def provider(_request):
        raise MaiAgentScopeProviderFailure("MaiAgent Scope provider response was invalid", failure_category="RESPONSE_PARSE")

    artifact_path = capture_artifact(_case(case_id="parse-failure"), provider, run_id="parse-status", code_revision="d" * 40)
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert artifact["provider_response_parse_status"] == "FAILED"
    assert artifact["technical_failure_category"] == "RESPONSE_PARSE"
    assert "provider_proposal" in artifact and artifact["provider_proposal"] is None
    replay = replay_artifact(artifact_path)
    assert replay["provider_call_count"] == 0
    assert replay["replay_status"] == "BLOCKED"
    assert replay["provider_response_parse_status"] == "FAILED"
    assert replay["owner_replay_status"] == "NOT_REPLAYABLE"


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
    expected = _classify(proposal, POSITIVE_SOURCE)

    def broken_observer(_observation):
        raise RuntimeError("observer failure")

    observed = ScopeClassifier(lambda _request: proposal).classify(_evidence(POSITIVE_SOURCE), observation_hook=broken_observer)
    assert observed == expected


def test_target_may_be_the_eligible_system_itself():
    # SC-1: a new line or network is both the affected target and the system.
    source = "Egypt is exploring a hydrogen-powered tram network for its New Administrative Capital."
    label = "a hydrogen-powered tram network"
    proposal = _semantic_proposal(source, mode="TRAM", action="exploring", target=label, system=label)
    assert _classify(proposal, source).state is ScopeState.IN_SCOPE


def test_action_label_must_differ_from_target_label():
    assert _violation(_semantic_proposal(POSITIVE_SOURCE, action="platform doors"), POSITIVE_SOURCE) == "ENDPOINT_ROLE_DISTINCTNESS"


def test_event_on_a_station_platform_of_the_system_is_in_scope():
    # D1: an incident taking place on a platform that belongs to the subway is
    # tied to that system; reportability is decided by Reportability.
    source = "A man died after being shot on a northbound E train platform at the Seventh Avenue-53rd Street subway station."
    proposal = _semantic_proposal(
        source, mode="SUBWAY", action="shot", target="northbound E train platform", system="subway station",
        action_relation="LOCATED_AT", system_relation="PART_OF",
    )
    assert _classify(proposal, source).state is ScopeState.IN_SCOPE


def test_location_without_system_membership_stays_out_of_scope():
    proposal = _semantic_proposal(
        NEGATIVE_SOURCE, target="public sculptures", system="Metro station",
        action_relation="LOCATED_AT", system_relation="LOCATED_AT",
    )
    result = _classify(proposal, NEGATIVE_SOURCE)
    assert result.state is ScopeState.OUT_OF_SCOPE
    assert result.diagnostic is ScopeDiagnostic.SCOPE_NOT_ESTABLISHED


def test_noneligible_relation_of_another_action_is_not_a_focus_relation():
    # SC-2: a bus pilot in the same article is not the focus action's
    # noneligible relation; recording it there is a violation.
    source = "Seoul will add eight express trains on Metro Line 9. The city will also pilot four express bus routes."
    proposal = _semantic_proposal(
        source, action="add", target="eight express trains", system="Metro Line 9",
        noneligible_status="PRESENT", noneligible_kind="EXCLUDED_TRANSPORT_MODE", mode="NON_ELIGIBLE", decision="OUT_OF_SCOPE_SUPPORT",
    )
    proposal["noneligible_relation"]["sentence_ids"] = ["S2"]
    assert _violation(proposal, source) == "NONELIGIBLE_RELATION_ENDPOINT"

    focus_only = _semantic_proposal(source, action="add", target="eight express trains", system="Metro Line 9")
    focus_only["action_target"]["sentence_ids"] = ["S1"]
    focus_only["target_system"]["sentence_ids"] = ["S1"]
    assert _classify(focus_only, source).state is ScopeState.IN_SCOPE


def test_endpoint_provenance_records_labels_inside_their_contexts_only():
    source = "The Metro operator installed platform doors on the Metro line."
    result = _classify(_semantic_proposal(source, system="Metro line"), source)
    assert result.state is ScopeState.IN_SCOPE
    support = result.provenance["relation_support"]
    doors = source.index("platform doors")
    assert support["target"] == [{"start": doors, "end": doors + len("platform doors")}]
    assert result.provenance["endpoint_labels"] == {
        "action": "installed", "target": "platform doors", "system": "Metro line", "target_reference": "platform doors"
    }
    assert result.provenance["cited_sentence_ids"]["target_system"] == ["S1"]


HANOI = (
    "Hanoi has signed contracts to build five metro lines totaling about 253.5 kilometers. "
    "The contractors will handle all stages. The five lines, namely No. 1, 2, 8, 10, and 14, include depots."
)


def _anaphora_proposal(*, focus=("S1", "S2", "S3"), reference="The five lines", system="five metro lines"):
    proposal = _semantic_proposal(HANOI, action="build", target="five metro lines", system=system, system_relation="PART_OF")
    proposal["event_focus"]["sentence_ids"] = list(focus)
    proposal["action_target"]["sentence_ids"] = ["S1"]
    proposal["target_system"] = {"status": "ESTABLISHED", "relation": "PART_OF", "sentence_ids": ["S3"], "target_reference": reference}
    return proposal


def test_same_event_reference_to_a_target_that_is_the_system_is_accepted():
    # Legitimate anaphora: the source refers back to "five metro lines" as
    # "The five lines"; no citation repeating the label is required.
    assert _ids(HANOI) == ["S1", "S2", "S3"]
    result = _classify(_anaphora_proposal(), HANOI)
    assert result.state is ScopeState.IN_SCOPE
    reference = HANOI.index("The five lines")
    assert result.provenance["relation_support"]["target_reference"] == [{"start": reference, "end": reference + len("The five lines")}]


def test_reference_must_occur_in_the_citation_and_stay_in_the_event_focus():
    assert _violation(_anaphora_proposal(reference="the new lines"), HANOI) == "ENDPOINT_LABEL"
    # The reference sentence lies outside the Candidate focus: no borrowing.
    assert _violation(_anaphora_proposal(focus=("S1",)), HANOI) == "EVENT_FOCUS_CONTAINMENT"
    # A distinct system must still be named inside the target-system citation.
    assert _violation(_anaphora_proposal(system="Hanoi"), HANOI) == "TARGET_SYSTEM_CONTAINMENT"


def test_omitted_target_reference_means_the_target_label():
    proposal = _semantic_proposal(POSITIVE_SOURCE)
    assert "target_reference" not in proposal["target_system"]
    assert _classify(proposal, POSITIVE_SOURCE).state is ScopeState.IN_SCOPE

    source = "The operator installed platform doors. They are on the Metro line."
    missing_label = _semantic_proposal(source)
    missing_label["target_system"]["sentence_ids"] = ["S2"]
    assert _violation(missing_label, source) == "TARGET_SYSTEM_CONTAINMENT"


def test_operator_service_cannot_turn_buses_into_urban_rail():
    source = "The Metro operator bought new buses. The buses will serve suburban routes."
    proposal = _semantic_proposal(source, action="bought", target="new buses", system="Metro operator", system_relation="OPERATED_BY")
    proposal["target_system"]["sentence_ids"] = ["S1"]
    assert _classify(proposal, source).state is ScopeState.OUT_OF_SCOPE


def test_private_acceptance_directory_is_ignored_by_git():
    ignore_lines = (Path(__file__).resolve().parents[1] / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "/.scope-acceptance-*.json" in ignore_lines


def test_scope_request_carries_only_document_headlines_and_is_repeatable():
    # The helper may receive same-document factual metadata only; acquisition
    # timings would make every request unique and are not document facts.
    requests = []

    def helper(request):
        requests.append(request)
        raise ScopeProposalViolation("PROPOSAL_MISSING")

    for elapsed in (1574, 2210):
        evidence = EvidenceResult(
            candidate_id="C1",
            state=EvidenceState.READY,
            substantive_content=POSITIVE_SOURCE,
            provenance={
                "acquisition_elapsed_ms": elapsed,
                "resolved_url": "https://publisher.invalid/a",
                "excluded_region_reasons": ["node-0045:non_content_script"],
                "principal_source_headlines": ["Platform doors installed"],
            },
        )
        try:
            ScopeClassifier(helper).classify(evidence, candidate_title="Platform doors")
        except ScopeProposalViolation:
            pass
    assert requests[0].as_payload()["source_metadata"] == {"principal_source_headlines": ["Platform doors installed"]}
    assert requests[0].as_payload() == requests[1].as_payload()
