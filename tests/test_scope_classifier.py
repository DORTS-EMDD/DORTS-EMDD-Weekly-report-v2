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
