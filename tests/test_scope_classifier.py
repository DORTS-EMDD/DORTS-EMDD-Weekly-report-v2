"""Contract tests for the proposal-only Candidate-stage Scope owner."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.weekly_report.contracts import (
    EvidenceResult,
    EvidenceState,
    ProposalContractViolation,
    ScopeDiagnostic,
    ScopeState,
    TechnicalGap,
    TechnicalGapKind,
)
from src.weekly_report.scope_classifier import (
    SCOPE_PROPOSAL_SCHEMA_VERSION,
    SUPPORTED_SCOPE_MODE_FAMILIES,
    ScopeClassifier,
    ScopeProposalViolation,
)

ROOT = Path(__file__).resolve().parents[1]


def _evidence(content: str, *, candidate_id: str = "C1", **provenance) -> EvidenceResult:
    return EvidenceResult(candidate_id=candidate_id, state=EvidenceState.READY, substantive_content=content, provenance=provenance)


def _mechanical_schema_proposal(request, *, decision="IN_SCOPE_SUPPORT", mode="METRO", kind="NONE", sentence_ids=None):
    """Quarter-sliced endpoint labels are for mechanical contract tests only."""
    sentences = request.principal_sentences
    ids = [sentence.sentence_id for sentence in sentences] if sentence_ids is None else list(sentence_ids)
    first = next(sentence.text for sentence in sentences if sentence.sentence_id == ids[0])
    width = max(1, len(first) // 4)
    action_label = first[:width]
    target_label = first[width : width * 2]
    system_label = first[width * 2 : width * 3] or first[width * 2 :]
    noneligible = mode == "NON_ELIGIBLE"
    return {
        "candidate_id": request.candidate_id,
        "schema_version": SCOPE_PROPOSAL_SCHEMA_VERSION,
        "event_focus": {"status": "RESOLVED", "sentence_ids": ids},
        "action": {"label": action_label},
        "target": {"label": target_label},
        "system": {"label": system_label},
        "eligible_mode_family": mode,
        "action_target": {"status": "ESTABLISHED", "relation": "AFFECTS", "sentence_ids": ids},
        "target_system": {"status": "ESTABLISHED", "relation": "BELONGS_TO", "sentence_ids": ids},
        "ambiguity": {"status": "NONE", "sentence_ids": []},
        "noneligible_relation": {"status": "PRESENT" if noneligible else "ABSENT", "sentence_ids": ids if noneligible else []},
        "noneligible_kind": kind,
        "event_status": "ASSERTED",
        "decision": decision,
    }


class _ProposalHelper:
    """Mechanical proposal factory; its endpoint text is not semantic proof."""

    def __init__(self, *, mode="METRO", decision="IN_SCOPE_SUPPORT", kind="NONE"):
        self.mode = mode
        self.decision = decision
        self.kind = kind

    def __call__(self, request):
        return _mechanical_schema_proposal(request, mode=self.mode, decision=self.decision, kind=self.kind)


class ScopeClassifierTests(unittest.TestCase):
    def assertViolation(self, helper, content, predicate, **kwargs):
        observations = []
        with self.assertRaises(ScopeProposalViolation) as context:
            ScopeClassifier(helper).classify(_evidence(content), observation_hook=observations.append, **kwargs)
        self.assertEqual(context.exception.failure_class, predicate)
        self.assertEqual(observations[0].response_status, "PROPOSAL_VIOLATION")
        self.assertIsNone(observations[0].scope_state)
        return context.exception

    def test_rejected_evidence_cannot_be_classified(self):
        evidence = EvidenceResult(candidate_id="C1", state=EvidenceState.REJECTED, reject_reason="TITLE_ONLY")
        with self.assertRaises(ValueError):
            ScopeClassifier().classify(evidence)

    def test_without_authorized_helper_scope_fails_closed(self):
        result = ScopeClassifier().classify(_evidence("The identified Metro system commissioned a signalling controller."))
        self.assertEqual(result.state, ScopeState.OUT_OF_SCOPE)
        self.assertEqual(result.diagnostic, ScopeDiagnostic.SCOPE_NOT_ESTABLISHED)
        self.assertEqual(result.provenance["helper"], "not_configured")

    def test_span_only_legacy_response_is_a_disclosed_violation_not_out_of_scope(self):
        helper = lambda request: {"support": "IN_SCOPE_SUPPORT", "support_spans": [{"start": 0, "end": len(request.principal_content)}]}
        self.assertViolation(helper, "Metro content", "TOP_LEVEL_SHAPE")

    def test_violation_becomes_a_candidate_technical_gap(self):
        helper = lambda request: {"support": "IN_SCOPE_SUPPORT"}
        with self.assertRaises(ProposalContractViolation) as context:
            ScopeClassifier(helper).classify(_evidence("Metro content"))
        gap = TechnicalGap.from_failure("Scope", "C1", context.exception)
        self.assertEqual(gap.kind, TechnicalGapKind.PROPOSAL_CONTRACT_VIOLATION)
        self.assertEqual(gap.failure_class, "TOP_LEVEL_SHAPE")

    def test_non_authoritative_signals_cannot_promote_scope(self):
        for content in (
            "The principal document describes railway equipment but does not establish a mode.",
            "The publisher operates a Metro system but upgraded conventional intercity railway signalling.",
            "The railway upgraded signalling equipment on a conventional corridor.",
        ):
            result = ScopeClassifier().classify(_evidence(content), candidate_title="Metro opens Line 4")
            self.assertEqual(result.state, ScopeState.OUT_OF_SCOPE)

    def test_mixed_mode_without_proposal_remains_fail_closed(self):
        content = "The shared corridor carries Metro and conventional railway services. The operator upgraded control equipment without identifying which mode received the upgrade."
        result = ScopeClassifier().classify(_evidence(content))
        self.assertEqual(result.state, ScopeState.OUT_OF_SCOPE)
        self.assertEqual(result.diagnostic, ScopeDiagnostic.SCOPE_NOT_ESTABLISHED)

    def test_mechanical_helper_result_is_deterministic(self):
        content = "The identified Metro system commissioned a new signalling controller on its central line."
        classifier = ScopeClassifier(_ProposalHelper())
        self.assertEqual(classifier.classify(_evidence(content)), classifier.classify(_evidence(content)))

    def test_preposition_and_beneficiary_cooccurrence_without_proposal_cannot_promote_scope(self):
        for content in (
            "The Metro system installed new charging stations for its bus fleet.",
            "At the Metro station, the operator replaced the buses used for airport shuttles.",
            "The Metro station is next to the airport, and the airport installed aircraft guidance systems.",
            "地下鉄とバスの運営会社はバス用の充電設備を導入した。",
        ):
            self.assertEqual(ScopeClassifier().classify(_evidence(content)).state, ScopeState.OUT_OF_SCOPE)

    def test_scope_facts_are_not_an_extra_authority(self):
        with self.assertRaises(TypeError):
            ScopeClassifier().classify(_evidence("No eligible mode is established."), scope_facts={"mode": "Metro"})

    def test_mechanical_schema_proposal_with_complete_records_is_accepted(self):
        content = "The operator installed platform doors on the Metro line."
        result = ScopeClassifier(_ProposalHelper()).classify(_evidence(content))
        self.assertEqual(result.state, ScopeState.IN_SCOPE)
        self.assertEqual(result.diagnostic, ScopeDiagnostic.NONE)
        self.assertEqual(result.provenance["decision_basis"], "scope_semantic_proposal")
        self.assertEqual(result.provenance["cited_sentence_ids"]["action_target"], ["S1"])
        self.assertIn("relation_support", result.provenance)

    def test_request_carries_python_segmented_sentences_not_free_text(self):
        seen = []

        def helper(request):
            seen.append(request.as_payload())
            return _mechanical_schema_proposal(request)

        ScopeClassifier(helper).classify(_evidence("The Metro line opened. It has six stations."))
        self.assertNotIn("principal_content", seen[0])
        self.assertEqual(
            seen[0]["principal_sentences"],
            [{"sentence_id": "S1", "text": "The Metro line opened."}, {"sentence_id": "S2", "text": "It has six stations."}],
        )

    def test_mechanical_schema_accepts_the_nine_contract_mode_enums(self):
        content = "The operator installed platform doors on the eligible urban rail system."
        for mode in SUPPORTED_SCOPE_MODE_FAMILIES:
            result = ScopeClassifier(_ProposalHelper(mode=mode)).classify(_evidence(content))
            self.assertEqual(result.state, ScopeState.IN_SCOPE, mode)

    def test_whole_document_endpoint_labels_do_not_bypass_consistency(self):
        content = "The city installed public sculptures at the Metro station."

        def helper(request):
            proposal = _mechanical_schema_proposal(request)
            for field in ("action", "target", "system"):
                proposal[field] = {"label": content}
            return proposal

        self.assertViolation(helper, content, "ENDPOINT_ROLE_DISTINCTNESS")

    def test_unknown_or_repeated_sentence_ids_are_invalid_citations(self):
        content = "The operator installed platform doors on the Metro line."
        for ids in (["S9"], ["S1", "S1"], ["installed platform doors"]):
            with self.subTest(ids=ids):
                def helper(request, ids=ids):
                    proposal = _mechanical_schema_proposal(request)
                    proposal["action_target"]["sentence_ids"] = ids
                    return proposal

                self.assertViolation(helper, content, "CITATION_INVALID")

    def test_location_operator_and_generic_equipment_false_positives_fail_closed(self):
        cases = (
            "The city installed public sculptures at the Metro station.",
            "The port installed a cargo monitoring system at the Metro station to serve harbor businesses.",
            "The city installed an advertising system at the Metro station for local businesses.",
            "地下鉄事業者は住宅団地の信号装置を更新した。",
            "地下鉄事業者は空港の電源設備を更新した。本文は都市鉄道の地下鉄システムとその技術措置を明確に説明している。",
        )
        for content in cases:
            result = ScopeClassifier().classify(_evidence(content))
            self.assertEqual(result.state, ScopeState.OUT_OF_SCOPE, content)
            self.assertEqual(result.diagnostic, ScopeDiagnostic.SCOPE_NOT_ESTABLISHED, content)

    def test_provider_must_not_borrow_target_system_from_another_event(self):
        content = "The Metro line renewed signalling equipment. The port installed cargo monitoring equipment for harbor businesses."

        def helper(request):
            proposal = _mechanical_schema_proposal(request, sentence_ids=["S1"])
            # The Candidate focus is the second event while the relations cite
            # the first event; owner validation must reject the cross-event mix.
            proposal["event_focus"] = {"status": "RESOLVED", "sentence_ids": ["S2"]}
            return proposal

        self.assertViolation(helper, content, "EVENT_FOCUS_CONTAINMENT", candidate_title="Port cargo monitoring")

    def test_location_or_operator_relation_is_not_target_system_membership(self):
        content = "The city installed public sculptures at the Metro station."

        def helper(request):
            proposal = _mechanical_schema_proposal(request)
            proposal["target_system"]["relation"] = "LOCATED_AT"
            return proposal

        result = ScopeClassifier(helper).classify(_evidence(content))
        self.assertEqual(result.state, ScopeState.OUT_OF_SCOPE)
        self.assertEqual(result.diagnostic, ScopeDiagnostic.SCOPE_NOT_ESTABLISHED)

    def test_contradictory_noneligible_fields_are_a_violation(self):
        content = "The operator installed platform doors on the Metro line."
        self.assertViolation(_ProposalHelper(kind="NON_URBAN_RAIL"), content, "NONELIGIBLE_CONSISTENCY")

    def test_candidate_id_and_version_are_authoritative(self):
        content = "The operator installed platform doors on the Metro line."

        def wrong_candidate(request):
            proposal = _mechanical_schema_proposal(request)
            proposal["candidate_id"] = "wrong"
            return proposal

        self.assertViolation(wrong_candidate, content, "CANDIDATE_ID")

        def old_schema(request):
            proposal = _mechanical_schema_proposal(request)
            proposal["schema_version"] = "scope-semantic-proposal-v3"
            return proposal

        self.assertViolation(old_schema, content, "SCHEMA_VERSION")

    def test_relation_provenance_records_cited_sentence_spans(self):
        content = "Metro action. Metro action."
        result = ScopeClassifier(lambda request: _mechanical_schema_proposal(request, sentence_ids=["S2"])).classify(_evidence(content))
        self.assertEqual(result.state, ScopeState.IN_SCOPE)
        self.assertEqual(result.provenance["relation_support"]["event_focus"], [{"start": 14, "end": 27}])

    def test_negated_conditional_and_unresolved_proposals_stay_out_of_scope(self):
        content = "The operator may install signalling equipment on the Metro line."

        def helper(request):
            proposal = _mechanical_schema_proposal(request)
            proposal["event_status"] = "CONDITIONAL"
            return proposal

        observations = []
        result = ScopeClassifier(helper).classify(_evidence(content), observation_hook=observations.append)
        self.assertEqual(result.state, ScopeState.OUT_OF_SCOPE)
        self.assertEqual(result.diagnostic, ScopeDiagnostic.SCOPE_NOT_ESTABLISHED)
        self.assertEqual(observations[0].first_rejection_predicate, "POSITIVE_ACCEPTANCE_CONDITION")
        self.assertEqual(observations[0].response_status, "OWNER_VALIDATED")

    def test_noneligible_proposal_keeps_existing_diagnostic(self):
        content = "The conventional intercity railway replaced long-distance rolling stock."
        for mode in ("NON_ELIGIBLE", "UNKNOWN"):
            with self.subTest(mode=mode):
                def helper(request, mode=mode):
                    proposal = _mechanical_schema_proposal(request, mode="NON_ELIGIBLE", decision="OUT_OF_SCOPE_SUPPORT", kind="NON_URBAN_RAIL")
                    proposal["eligible_mode_family"] = mode
                    return proposal

                result = ScopeClassifier(helper).classify(_evidence(content))
                self.assertEqual(result.state, ScopeState.OUT_OF_SCOPE)
                self.assertEqual(result.diagnostic, ScopeDiagnostic.NON_URBAN_RAIL)

    def test_golden_g22_g35_states_remain_compatible_with_mechanical_proposals(self):
        manifest = json.loads((ROOT / "golden/manifest.json").read_text(encoding="utf-8"))
        for entry in manifest["cases"]:
            if not 22 <= int(entry["case_id"][1:]) <= 35:
                continue
            fixture = json.loads((ROOT / "golden" / entry["file"]).read_text(encoding="utf-8"))
            candidate = fixture["candidates"][0]
            expected = fixture["expected"]
            if expected["scope"] == "IN_SCOPE":
                helper = _ProposalHelper(mode="SUBWAY" if entry["case_id"] == "G35" else "METRO")
            elif expected["scope_diagnostic"] == "SCOPE_NOT_ESTABLISHED":
                helper = _ProposalHelper(mode="UNKNOWN", decision="UNCERTAIN")
            else:
                helper = _ProposalHelper(mode="NON_ELIGIBLE", decision="OUT_OF_SCOPE_SUPPORT", kind=expected["scope_diagnostic"])
            result = ScopeClassifier(helper).classify(_evidence(candidate["source_content"], candidate_id=candidate["candidate_id"]), candidate_title=candidate["title"])
            self.assertEqual(result.state.value, expected["scope"], entry["case_id"])
            self.assertEqual(result.diagnostic.value, expected["scope_diagnostic"], entry["case_id"])


if __name__ == "__main__":
    unittest.main()
