"""Contract tests for the Candidate-stage Scope owner."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.weekly_report.contracts import (
    EvidenceResult,
    EvidenceState,
    ScopeDiagnostic,
    ScopeState,
)
from src.weekly_report.scope_classifier import (
    ScopeClassifier,
    ScopeSemanticResponse,
    ScopeSemanticSupport,
    ScopeSupportSpan,
)


ROOT = Path(__file__).resolve().parents[1]


def _evidence(content: str, *, candidate_id: str = "C1", **provenance) -> EvidenceResult:
    return EvidenceResult(
        candidate_id=candidate_id,
        state=EvidenceState.READY,
        substantive_content=content,
        provenance=provenance,
    )


class _FixtureScopeHelper:
    """Bounded test provider for fixed authoritative fixture content.

    This is deliberately a test double: production does not contain a
    language or publisher dictionary.  It returns only constrained support
    spans so ScopeClassifier remains the final owner.
    """

    def __call__(self, request):
        text = request.principal_content
        folded = text.casefold()
        cases = (
            (
                "does not identify whether",
                ScopeSemanticSupport.OUT_OF_SCOPE_SUPPORT,
                ScopeDiagnostic.SCOPE_NOT_ESTABLISHED,
            ),
            (
                "commuter rail operator installed",
                ScopeSemanticSupport.OUT_OF_SCOPE_SUPPORT,
                ScopeDiagnostic.NON_URBAN_RAIL,
            ),
            (
                "conventional mainline airport express",
                ScopeSemanticSupport.OUT_OF_SCOPE_SUPPORT,
                ScopeDiagnostic.EXCLUDED_TRANSPORT_MODE,
            ),
            (
                "funicular installed",
                ScopeSemanticSupport.OUT_OF_SCOPE_SUPPORT,
                ScopeDiagnostic.EXCLUDED_TRANSPORT_MODE,
            ),
            (
                "cable railway replaced",
                ScopeSemanticSupport.OUT_OF_SCOPE_SUPPORT,
                ScopeDiagnostic.EXCLUDED_TRANSPORT_MODE,
            ),
            (
                "intercity high-speed maglev",
                ScopeSemanticSupport.OUT_OF_SCOPE_SUPPORT,
                ScopeDiagnostic.NON_URBAN_RAIL,
            ),
            (
                "intercity railway division",
                ScopeSemanticSupport.OUT_OF_SCOPE_SUPPORT,
                ScopeDiagnostic.NON_URBAN_RAIL,
            ),
            (
                "streetcar system is a tram network",
                ScopeSemanticSupport.IN_SCOPE_SUPPORT,
                ScopeDiagnostic.NONE,
            ),
            (
                "explicitly identified metro system",
                ScopeSemanticSupport.IN_SCOPE_SUPPORT,
                ScopeDiagnostic.NONE,
            ),
            (
                "airport service is the metro system",
                ScopeSemanticSupport.IN_SCOPE_SUPPORT,
                ScopeDiagnostic.NONE,
            ),
            (
                "automated guideway transit agt people mover",
                ScopeSemanticSupport.IN_SCOPE_SUPPORT,
                ScopeDiagnostic.NONE,
            ),
            (
                "urban maglev line classified by the operator as urban rail",
                ScopeSemanticSupport.IN_SCOPE_SUPPORT,
                ScopeDiagnostic.NONE,
            ),
            (
                "candidate action is the installation of platform doors at the metro station",
                ScopeSemanticSupport.IN_SCOPE_SUPPORT,
                ScopeDiagnostic.NONE,
            ),
        )
        for phrase, support, diagnostic in cases:
            start = folded.find(phrase)
            if start >= 0:
                return ScopeSemanticResponse(
                    support=support,
                    support_spans=(ScopeSupportSpan(start, start + len(phrase)),),
                    diagnostic=diagnostic,
                )
        if "地下鉄" in text:
            start = text.index("地下鉄")
            return ScopeSemanticResponse(
                support=ScopeSemanticSupport.IN_SCOPE_SUPPORT,
                support_spans=(ScopeSupportSpan(start, start + len("地下鉄")),),
            )
        return ScopeSemanticResponse(support=ScopeSemanticSupport.UNCERTAIN)


class ScopeClassifierTests(unittest.TestCase):
    def test_rejected_evidence_cannot_be_classified(self):
        evidence = EvidenceResult(
            candidate_id="C1",
            state=EvidenceState.REJECTED,
            reject_reason="TITLE_ONLY",
        )
        with self.assertRaises(ValueError):
            ScopeClassifier().classify(evidence)

    def test_no_helper_does_not_promote_lexical_content(self):
        result = ScopeClassifier().classify(
            _evidence("Metro train station line rail airport"),
            candidate_title="Metro opens Line 4",
        )
        self.assertEqual(result.state, ScopeState.OUT_OF_SCOPE)
        self.assertEqual(result.diagnostic, ScopeDiagnostic.SCOPE_NOT_ESTABLISHED)

    def test_authoritative_content_reaches_positive_scope_without_helper(self):
        manifest = json.loads((ROOT / "golden/manifest.json").read_text(encoding="utf-8"))
        for entry in manifest["cases"]:
            if not 22 <= int(entry["case_id"][1:]) <= 35:
                continue
            fixture = json.loads((ROOT / "golden" / entry["file"]).read_text(encoding="utf-8"))
            candidate = fixture["candidates"][0]
            result = ScopeClassifier().classify(
                _evidence(candidate["source_content"], candidate_id=candidate["candidate_id"]),
                candidate_title=candidate["title"],
            )
            expected = fixture["expected"]
            self.assertEqual(result.state.value, expected["scope"], entry["case_id"])
            self.assertEqual(result.diagnostic.value, expected["scope_diagnostic"], entry["case_id"])

    def test_non_authoritative_signals_cannot_promote_scope(self):
        cases = (
            _evidence(
                "The principal document describes a railway equipment change but does not establish a mode.",
                search_snippet="Metro platform upgrade",
                discovery_intent="technology",
            ),
            _evidence(
                "The publisher operates a Metro system but upgraded conventional intercity railway signalling.",
            ),
            _evidence("The railway upgraded signalling equipment on a conventional corridor."),
        )
        for evidence in cases:
            result = ScopeClassifier().classify(evidence, candidate_title="Metro opens Line 4")
            self.assertEqual(result.state, ScopeState.OUT_OF_SCOPE)

    def test_mixed_mode_unresolved_and_explicit_exclusion_remain_fail_closed(self):
        mixed = _evidence(
            "The shared corridor carries Metro and conventional railway services. "
            "The operator upgraded control equipment without identifying which mode received the upgrade."
        )
        mixed_result = ScopeClassifier().classify(mixed)
        self.assertEqual(mixed_result.state, ScopeState.OUT_OF_SCOPE)
        self.assertEqual(mixed_result.diagnostic, ScopeDiagnostic.SCOPE_NOT_ESTABLISHED)

        excluded = _evidence(
            "The funicular installed a new traction controller for its cable-hauled hillside railway."
        )
        excluded_result = ScopeClassifier().classify(excluded)
        self.assertEqual(excluded_result.state, ScopeState.OUT_OF_SCOPE)
        self.assertEqual(excluded_result.diagnostic, ScopeDiagnostic.EXCLUDED_TRANSPORT_MODE)

    def test_positive_scope_decision_is_deterministic(self):
        evidence = _evidence(
            "The identified Metro system commissioned a new signalling controller on its central line."
        )
        first = ScopeClassifier().classify(evidence)
        second = ScopeClassifier().classify(evidence)
        self.assertEqual(first, second)
        self.assertEqual(first.state, ScopeState.IN_SCOPE)

    def test_event_relation_rejects_operator_location_and_beneficiary_cooccurrence(self):
        cases = {
            "A": "The Metro system installed new charging stations for its bus fleet.",
            "B": "At the Metro station, the operator replaced the buses used for airport shuttles.",
            "C": "The Metro system announced a deployment of electric buses at its terminal.",
            "D": "The Metro station is next to the airport, and the airport installed new aircraft guidance systems.",
            "E": "地下鉄とバスの運営会社はバス用の充電設備を導入した。",
        }
        for case_id, content in cases.items():
            result = ScopeClassifier().classify(_evidence(content))
            self.assertEqual(result.state, ScopeState.OUT_OF_SCOPE, case_id)
            self.assertEqual(result.diagnostic, ScopeDiagnostic.NON_URBAN_RAIL, case_id)

    def test_event_relation_rejects_independent_preposition_false_positives(self):
        cases = (
            "A notice mentioning Metro at the airport announced the purchase of aircraft.",
            "The airline installed aircraft guidance systems at an airport near Metro.",
        )
        results = [ScopeClassifier().classify(_evidence(content)) for content in cases]
        self.assertEqual(results[0].state, ScopeState.OUT_OF_SCOPE)
        self.assertEqual(results[0].diagnostic, ScopeDiagnostic.SCOPE_NOT_ESTABLISHED)
        self.assertEqual(results[1].state, ScopeState.OUT_OF_SCOPE)
        self.assertEqual(results[1].diagnostic, ScopeDiagnostic.NON_URBAN_RAIL)

    def test_bounded_event_relation_supports_voice_cross_clause_and_languages(self):
        cases = (
            "The operator installed platform doors on the Metro line.",
            "The signalling system of the Metro was renewed.",
            "The line is the Metro system. The operator renewed the signalling controller on that line.",
            "Le métro a renouvelé son système de signalisation.",
            "Le système de signalisation du métro a été renouvelé.",
            "地下鉄路線の信号設備を更新した。",
        )
        for content in cases:
            result = ScopeClassifier().classify(_evidence(content))
            self.assertEqual(result.state, ScopeState.IN_SCOPE, content)
            self.assertEqual(result.diagnostic, ScopeDiagnostic.NONE, content)
            relation_support = result.provenance["relation_support"]
            for role in ("action", "target", "eligible_mode", "relation"):
                span = relation_support[role]
                self.assertTrue(content[span["start"] : span["end"]], (content, role))

    def test_location_only_and_ownership_only_do_not_bind_the_event(self):
        cases = (
            "At the Metro station, the operator replaced buses.",
            "The Metro operator renewed its signalling equipment.",
        )
        for content in cases:
            result = ScopeClassifier().classify(_evidence(content))
            self.assertEqual(result.state, ScopeState.OUT_OF_SCOPE, content)
            self.assertEqual(result.diagnostic, ScopeDiagnostic.NON_URBAN_RAIL if "buses" in content else ScopeDiagnostic.SCOPE_NOT_ESTABLISHED, content)

    def test_negated_conditional_and_unresolved_relations_fail_closed(self):
        cases = (
            "The Metro system did not install signalling equipment.",
            "The operator may install signalling equipment on the Metro line.",
            "The operator proposed installing signalling equipment on the Metro line.",
            "The shared corridor carries Metro and conventional railway services, but the operator upgraded control equipment without identifying which mode received the upgrade.",
        )
        for content in cases:
            result = ScopeClassifier().classify(_evidence(content))
            self.assertEqual(result.state, ScopeState.OUT_OF_SCOPE, content)
            self.assertEqual(result.diagnostic, ScopeDiagnostic.SCOPE_NOT_ESTABLISHED, content)

    def test_arbitrary_scope_facts_cannot_bypass_evidence(self):
        evidence = _evidence(
            "No eligible urban-rail mode is established.",
            scope_facts=[
                {
                    "mode_family": "Metro",
                    "action_relation": "eligible",
                    "action_association": "C1",
                }
            ],
        )
        result = ScopeClassifier().classify(evidence)
        self.assertEqual(result.state, ScopeState.OUT_OF_SCOPE)
        self.assertEqual(result.diagnostic, ScopeDiagnostic.SCOPE_NOT_ESTABLISHED)
        with self.assertRaises(TypeError):
            ScopeClassifier().classify(
                _evidence("No eligible mode is established."),
                scope_facts=[{"mode_family": "Metro", "action_relation": "eligible"}],
            )

    def test_helper_requires_validated_support_span(self):
        helper = lambda request: {
            "support": "IN_SCOPE_SUPPORT",
            "support_spans": [{"start": 0, "end": 999}],
        }
        result = ScopeClassifier(helper).classify(_evidence("Metro content"))
        self.assertEqual(result.state, ScopeState.OUT_OF_SCOPE)
        self.assertEqual(result.diagnostic, ScopeDiagnostic.SCOPE_NOT_ESTABLISHED)

    def test_golden_scope_cases_use_only_constrained_helper_support(self):
        manifest = json.loads((ROOT / "golden/manifest.json").read_text(encoding="utf-8"))
        classifier = ScopeClassifier(_FixtureScopeHelper())
        for entry in manifest["cases"]:
            if not 22 <= int(entry["case_id"][1:]) <= 35:
                continue
            fixture = json.loads((ROOT / "golden" / entry["file"]).read_text(encoding="utf-8"))
            candidate = fixture["candidates"][0]
            result = classifier.classify(
                _evidence(candidate["source_content"], candidate_id=candidate["candidate_id"]),
                candidate_title=candidate["title"],
            )
            expected = fixture["expected"]
            self.assertEqual(result.state.value, expected["scope"], entry["case_id"])
            self.assertEqual(result.diagnostic.value, expected["scope_diagnostic"], entry["case_id"])


if __name__ == "__main__":
    unittest.main()
