"""Contract tests for the proposal-only Candidate-stage Scope owner."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.weekly_report.contracts import EvidenceResult, EvidenceState, ScopeDiagnostic, ScopeState
from src.weekly_report.scope_classifier import ScopeClassifier, ScopeSemanticResponse, SCOPE_PROPOSAL_SCHEMA_VERSION

ROOT = Path(__file__).resolve().parents[1]


def _evidence(content: str, *, candidate_id: str = "C1", **provenance) -> EvidenceResult:
    return EvidenceResult(candidate_id=candidate_id, state=EvidenceState.READY, substantive_content=content, provenance=provenance)


def _proposal(request, *, decision="IN_SCOPE_SUPPORT", mode="METRO", diagnostic="NONE", quote=None):
    content = request.principal_content
    quote = content if quote is None else quote
    return {
        "candidate_id": request.candidate_id,
        "schema_version": SCOPE_PROPOSAL_SCHEMA_VERSION,
        "event_focus": {"status": "RESOLVED", "quote": quote},
        "action": {"label": quote, "quote": quote},
        "target": {"label": quote, "quote": quote},
        "system": {"label": quote, "quote": quote},
        "eligible_mode_family": mode,
        "action_target": {"status": "ESTABLISHED", "relation": "AFFECTS", "quote": quote},
        "target_system": {"status": "ESTABLISHED", "relation": "BELONGS_TO", "quote": quote},
        "ambiguity": {"status": "NONE", "quote": quote},
        "noneligible_relation": {"status": "PRESENT" if mode == "NON_ELIGIBLE" else "ABSENT", "quote": quote},
        "noneligible_kind": diagnostic,
        "event_status": "ASSERTED",
        "decision": decision,
    }


class _ProposalHelper:
    def __init__(self, *, mode="METRO", decision="IN_SCOPE_SUPPORT", diagnostic="NONE"):
        self.mode = mode
        self.decision = decision
        self.diagnostic = diagnostic

    def __call__(self, request):
        return _proposal(request, mode=self.mode, decision=self.decision, diagnostic=self.diagnostic)


class ScopeClassifierTests(unittest.TestCase):
    def test_rejected_evidence_cannot_be_classified(self):
        evidence = EvidenceResult(candidate_id="C1", state=EvidenceState.REJECTED, reject_reason="TITLE_ONLY")
        with self.assertRaises(ValueError):
            ScopeClassifier().classify(evidence)

    def test_without_authorized_helper_scope_fails_closed(self):
        result = ScopeClassifier().classify(_evidence("The identified Metro system commissioned a signalling controller."))
        self.assertEqual(result.state, ScopeState.OUT_OF_SCOPE)
        self.assertEqual(result.diagnostic, ScopeDiagnostic.SCOPE_NOT_ESTABLISHED)
        self.assertEqual(result.provenance["helper"], "not_configured")

    def test_span_only_legacy_response_is_rejected(self):
        helper = lambda request: {"support": "IN_SCOPE_SUPPORT", "support_spans": [{"start": 0, "end": len(request.principal_content)}]}
        result = ScopeClassifier(helper).classify(_evidence("Metro content"))
        self.assertEqual(result.state, ScopeState.OUT_OF_SCOPE)
        self.assertEqual(result.diagnostic, ScopeDiagnostic.SCOPE_NOT_ESTABLISHED)

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

    def test_helper_positive_result_is_deterministic(self):
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

    def test_complete_event_target_system_proposal_is_accepted(self):
        content = "The operator installed platform doors on the Metro line."
        result = ScopeClassifier(_ProposalHelper()).classify(_evidence(content))
        self.assertEqual(result.state, ScopeState.IN_SCOPE)
        self.assertEqual(result.diagnostic, ScopeDiagnostic.NONE)
        self.assertEqual(result.provenance["decision_basis"], "scope_semantic_proposal")
        self.assertIn("relation_support", result.provenance)

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
            first, second = content.split(". ")
            proposal = _proposal(request, quote=first + ".")
            # The candidate focus is the second event while the relation cites
            # the first event; owner validation must reject the cross-event mix.
            proposal["event_focus"] = {"status": "RESOLVED", "quote": second}
            return proposal

        result = ScopeClassifier(helper).classify(_evidence(content), candidate_title="Port cargo monitoring")
        self.assertEqual(result.state, ScopeState.OUT_OF_SCOPE)
        self.assertEqual(result.diagnostic, ScopeDiagnostic.SCOPE_NOT_ESTABLISHED)

    def test_location_or_operator_relation_is_not_target_system_membership(self):
        content = "The city installed public sculptures at the Metro station."

        def helper(request):
            proposal = _proposal(request)
            proposal["target_system"] = {"status": "ESTABLISHED", "relation": "LOCATED_AT", "quote": content}
            return proposal

        result = ScopeClassifier(helper).classify(_evidence(content))
        self.assertEqual(result.state, ScopeState.OUT_OF_SCOPE)
        self.assertEqual(result.diagnostic, ScopeDiagnostic.SCOPE_NOT_ESTABLISHED)

    def test_candidate_id_version_shape_and_quotes_are_authoritative(self):
        content = "The operator installed platform doors on the Metro line."

        def invalid(request):
            proposal = _proposal(request)
            proposal["candidate_id"] = "wrong"
            return proposal

        self.assertEqual(ScopeClassifier(invalid).classify(_evidence(content)).state, ScopeState.OUT_OF_SCOPE)

        def ambiguous(request):
            proposal = _proposal(request, quote="Metro")
            return proposal

        repeated = _evidence("Metro action. Metro action.")
        self.assertEqual(ScopeClassifier(ambiguous).classify(repeated).state, ScopeState.OUT_OF_SCOPE)

    def test_negated_conditional_and_unresolved_proposals_fail_closed(self):
        content = "The operator may install signalling equipment on the Metro line."

        def helper(request):
            proposal = _proposal(request)
            proposal["event_status"] = "CONDITIONAL"
            return proposal

        result = ScopeClassifier(helper).classify(_evidence(content))
        self.assertEqual(result.state, ScopeState.OUT_OF_SCOPE)
        self.assertEqual(result.diagnostic, ScopeDiagnostic.SCOPE_NOT_ESTABLISHED)

    def test_noneligible_proposal_keeps_existing_diagnostic(self):
        content = "The conventional intercity railway replaced long-distance rolling stock."
        result = ScopeClassifier(_ProposalHelper(mode="NON_ELIGIBLE", decision="OUT_OF_SCOPE_SUPPORT", diagnostic="NON_URBAN_RAIL")).classify(_evidence(content))
        self.assertEqual(result.state, ScopeState.OUT_OF_SCOPE)
        self.assertEqual(result.diagnostic, ScopeDiagnostic.NON_URBAN_RAIL)

    def test_golden_g22_g35_expected_states_use_structured_proposals(self):
        manifest = json.loads((ROOT / "golden/manifest.json").read_text(encoding="utf-8"))
        for entry in manifest["cases"]:
            if not 22 <= int(entry["case_id"][1:]) <= 35:
                continue
            fixture = json.loads((ROOT / "golden" / entry["file"]).read_text(encoding="utf-8"))
            candidate = fixture["candidates"][0]
            expected = fixture["expected"]
            if expected["scope"] == "IN_SCOPE":
                helper = _ProposalHelper(mode="SUBWAY" if entry["case_id"] == "G35" else "METRO")
            else:
                diag = expected["scope_diagnostic"]
                helper = _ProposalHelper(mode="NON_ELIGIBLE" if diag != "SCOPE_NOT_ESTABLISHED" else "UNKNOWN", decision="OUT_OF_SCOPE_SUPPORT", diagnostic=diag)
            result = ScopeClassifier(helper).classify(_evidence(candidate["source_content"], candidate_id=candidate["candidate_id"]), candidate_title=candidate["title"])
            self.assertEqual(result.state.value, expected["scope"], entry["case_id"])
            self.assertEqual(result.diagnostic.value, expected["scope_diagnostic"], entry["case_id"])


if __name__ == "__main__":
    unittest.main()
