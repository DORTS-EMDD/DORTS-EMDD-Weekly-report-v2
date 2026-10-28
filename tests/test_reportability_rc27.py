"""RC-27: the helper names the principal occurrence; Python applies the low-value classes."""

from __future__ import annotations

from unittest import TestCase

from src.weekly_report.contracts import (
    LOW_VALUE_OCCURRENCES,
    ReportabilityOccurrence,
    ReportabilityProposalViolation,
    ReportabilityReason,
    ReportabilityState,
)
from src.weekly_report.maiagent_reportability_provider import MAIAGENT_REPORTABILITY_RESPONSE_SCHEMA
from src.weekly_report.reportability import Reportability
from tests.test_reportability_owner import _Provider, _decision, _group


def _reply(group, occurrence, state="REPORTABLE"):
    return {
        "event_id": group.event_id,
        "proposed_state": state,
        "examined_source_refs": ["M1"],
        "support_citations": [{"source_ref": "M1", "sentence_ids": ["S1"]}] if state == "REPORTABLE" else [],
        "rationale": "The evidence reports the occurrence.",
        "principal_occurrence": occurrence,
    }


class PrincipalOccurrenceTests(TestCase):
    def setUp(self) -> None:
        self.group = _group("C1")
        self.decision = _decision(self.group, {"C1": "The tram won a design award. The jury praised it."})

    def test_low_value_occurrence_is_not_reportable_even_if_proposed_reportable(self) -> None:
        for occurrence in sorted(LOW_VALUE_OCCURRENCES):
            with self.subTest(occurrence=occurrence):
                result = Reportability(_Provider(_reply(self.group, occurrence.value))).evaluate(self.decision)
                self.assertEqual(result.reportability_state, ReportabilityState.NOT_REPORTABLE)
                self.assertEqual(result.reportability_reason, ReportabilityReason.LOW_REPORTABILITY_VALUE)
                self.assertTrue(result.provenance.rationale.startswith(f"[{occurrence.value}]"))

    def test_substantive_occurrence_keeps_the_proposed_state(self) -> None:
        for occurrence in ("CONTRACT_OR_PROCUREMENT", "INCIDENT_OR_FAILURE", "LABOUR_ACTION"):
            with self.subTest(occurrence=occurrence):
                result = Reportability(_Provider(_reply(self.group, occurrence))).evaluate(self.decision)
                self.assertEqual(result.reportability_state, ReportabilityState.REPORTABLE)
        rejected = Reportability(
            _Provider(_reply(self.group, "DECISION_OR_APPROVAL", state="NOT_REPORTABLE"))
        ).evaluate(self.decision)
        self.assertEqual(rejected.reportability_state, ReportabilityState.NOT_REPORTABLE)

    def test_missing_or_unknown_occurrence_is_a_contract_violation(self) -> None:
        missing = _reply(self.group, "OTHER")
        del missing["principal_occurrence"]
        for reply in (missing, _reply(self.group, "PRESS_RELEASE")):
            with self.assertRaises(ReportabilityProposalViolation):
                Reportability(_Provider(reply)).evaluate(self.decision)

    def test_schema_enumerates_every_occurrence(self) -> None:
        field = MAIAGENT_REPORTABILITY_RESPONSE_SCHEMA["properties"]["principal_occurrence"]
        self.assertEqual(set(field["enum"]), {item.value for item in ReportabilityOccurrence})
        self.assertIn("principal_occurrence", MAIAGENT_REPORTABILITY_RESPONSE_SCHEMA["required"])
