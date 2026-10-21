"""RC-15: batch grouping proposal validated by the single EventIdentity owner."""

from __future__ import annotations

import json
import unittest

from src.weekly_report.contracts import (
    EventIdentityFacts,
    IdentityMetadataSupport,
    SemanticProviderConfigurationFailure,
    SemanticProviderTechnicalFailure,
    TechnicalGapKind,
)
from src.weekly_report.event_identity import (
    BATCH_RECORD_LIMIT,
    LEAD_CHARACTER_LIMIT,
    LEAD_SENTENCE_LIMIT,
    EventIdentity,
)
from src.weekly_report.maiagent_event_identity_provider import (
    TASK_IDENTITY,
    MaiAgentEventIdentityProviderConfig,
    build_maiagent_event_identity_provider,
)
from src.weekly_report.maiagent_transport import MaiAgentHttpResponse
from src.weekly_report.report_service import ReportDisclosure, ReportService
from tests.test_event_identity_contract import _grounded_member, _record


def _member(candidate_id, **citations):
    member = _grounded_member(candidate_id)
    member.update(citations)
    return member


class _Scripted:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        # Fixtures name members by candidate ID; the helper sees record IDs.
        record_ids = {record.candidate_id: record.record_id for record in request.records}
        for group in response.get("groups", ()) if isinstance(response, dict) else ():
            for member in group.get("members", ()):
                if "record_id" in member and member["record_id"] in record_ids:
                    member["record_id"] = record_ids[member["record_id"]]
        return response


def _three_records():
    return [
        _record("EN", facts=None, body="Line 4 signalling entered service on Monday. Riders noticed shorter headways."),
        _record("JA", facts=None, body="4号線の信号システムが月曜日に営業開始した。"),
        _record("OTHER", facts=None, body="A tram depot fire closed Route 9."),
    ]


class GroupingProposalTests(unittest.TestCase):
    def test_validated_group_merges_and_unproposed_record_stays_apart(self):
        advisor = _Scripted({"groups": [{"members": [_member("EN"), _member("JA")]}]})
        result = EventIdentity(advisor).evaluate(_three_records())
        self.assertEqual([group.member_candidate_ids for group in result.groups], [("EN", "JA"), ("OTHER",)])
        self.assertEqual(result.technical_gaps, ())
        self.assertEqual(len(advisor.requests), 1)

    def test_empty_proposal_keeps_every_record_unmerged_without_gap(self):
        result = EventIdentity(_Scripted({"groups": []})).evaluate(_three_records())
        self.assertEqual(len(result.groups), 3)
        self.assertEqual(result.technical_gaps, ())

    def test_request_carries_only_lead_sentences_and_identity_only_facts(self):
        body = "Taipei Metro in Taiwan reports the opening. " + " ".join(
            f"Sentence number {index} reports the metro event." for index in range(1, 12)
        )
        support = (
            IdentityMetadataSupport("location", 0, 6),
            IdentityMetadataSupport("transit_system_name", 0, 12),
            IdentityMetadataSupport("country", body.index("Taiwan"), body.index("Taiwan") + 6),
        )
        facts = EventIdentityFacts(
            action="opening",
            location="Taipei",
            country="Taiwan",
            transit_system_name="Taipei Metro",
            metadata_support=support,
        )
        advisor = _Scripted({"groups": []})
        EventIdentity(advisor).evaluate([
            _record("A", facts=facts, body=body, url="https://publisher.invalid/a"),
            _record("B", facts=None, body="The tram line opened."),
        ])
        payload = json.dumps(advisor.requests[0].as_payload(), ensure_ascii=False)
        record = advisor.requests[0].records[0]
        self.assertEqual((record.record_id, record.candidate_id), ("R1", "A"))
        self.assertNotIn('"candidate_id"', payload)
        self.assertLessEqual(len(record.sentences), LEAD_SENTENCE_LIMIT)
        self.assertLessEqual(sum(len(sentence.text) for sentence in record.sentences), LEAD_CHARACTER_LIMIT)
        self.assertEqual(record.sentences[0].sentence_id, "S1")
        self.assertEqual(dict(record.identity_facts), {"action": "opening", "location": "Taipei"})
        for forbidden in ("Taiwan\"", "Taipei Metro\"", "country", "transit_system_name", "metadata_support", "publisher.invalid", "Metro event report"):
            self.assertNotIn(forbidden, payload)

    def test_whole_response_violations_are_disclosed_gaps_without_merges(self):
        cases = {
            "SCHEMA_INVALID": {"groups": [{"members": [_member("EN"), _member("JA")], "reason": "x"}]},
            "UNKNOWN_RECORD": {"groups": [{"members": [_member("EN"), _member("ZZ")]}]},
            "DUPLICATE_MEMBERSHIP": {
                "groups": [
                    {"members": [_member("EN"), _member("JA")]},
                    {"members": [_member("JA"), _member("OTHER")]},
                ]
            },
        }
        for failure_class, response in cases.items():
            with self.subTest(failure_class=failure_class):
                result = EventIdentity(_Scripted(response)).evaluate(_three_records())
                self.assertEqual(len(result.groups), 3)
                self.assertEqual(
                    [(gap.stage, gap.subject_id, gap.kind, gap.failure_class) for gap in result.technical_gaps],
                    [("EventIdentity", "event-identity-batch-1", TechnicalGapKind.PROPOSAL_CONTRACT_VIOLATION, failure_class)],
                )

    def test_invalid_group_is_isolated_and_valid_group_still_merges(self):
        records = _three_records() + [_record("SOLO", facts=None, body="Another depot fire.")]
        response = {
            "groups": [
                {"members": [_member("EN"), _member("JA")]},
                {"members": [_member("OTHER", occurrence_sentence_ids=["S7"]), _member("SOLO")]},
            ]
        }
        result = EventIdentity(_Scripted(response)).evaluate(records)
        self.assertIn(("EN", "JA"), [group.member_candidate_ids for group in result.groups])
        self.assertEqual(len(result.groups), 3)
        self.assertEqual(
            [(gap.subject_id, gap.failure_class) for gap in result.technical_gaps],
            [("event-identity-batch-1:group-2", "CITATION_INVALID")],
        )

    def test_single_member_group_is_a_no_op_and_empty_citation_is_a_violation(self):
        response = {
            "groups": [
                {"members": [_member("OTHER")]},
                {"members": [_member("EN", lifecycle_sentence_ids=[]), _member("JA")]},
            ]
        }
        result = EventIdentity(_Scripted(response)).evaluate(_three_records())
        self.assertEqual(len(result.groups), 3)
        self.assertEqual(
            [(gap.subject_id, gap.failure_class) for gap in result.technical_gaps],
            [("event-identity-batch-1:group-2", "CITATION_INVALID")],
        )
        self.assertIn(("OTHER",), [item.candidate_ids for item in result.diagnostics if item.reason == "SINGLE_MEMBER_PROPOSAL"])

    def test_technical_failure_is_a_gap_and_configuration_failure_stops(self):
        failure = SemanticProviderTechnicalFailure("TIMEOUT", attempts=2, transient=True)
        result = EventIdentity(_Scripted(failure)).evaluate(_three_records())
        self.assertEqual(len(result.groups), 3)
        self.assertEqual(
            [(gap.kind, gap.failure_class, gap.attempts) for gap in result.technical_gaps],
            [(TechnicalGapKind.TRANSIENT_FAILURE_AFTER_RETRY, "TIMEOUT", 2)],
        )
        with self.assertRaises(SemanticProviderConfigurationFailure):
            EventIdentity(_Scripted(SemanticProviderConfigurationFailure("HTTP_401"))).evaluate(_three_records())

    def test_deterministic_exact_source_still_merges_without_proposal(self):
        records = [
            _record("C1", facts=None, body="Exact body.", url="https://fixtures.invalid/same"),
            _record("C2", facts=None, body="Exact body.", url="https://fixtures.invalid/same"),
        ]
        result = EventIdentity(_Scripted({"groups": []})).evaluate(records)
        self.assertEqual([group.member_candidate_ids for group in result.groups], [("C1", "C2")])

    def test_single_eligible_record_makes_no_call(self):
        advisor = _Scripted()
        result = EventIdentity(advisor).evaluate([_record("ONLY", facts=None)])
        self.assertEqual(len(result.groups), 1)
        self.assertEqual(advisor.requests, [])

    def test_batches_are_bounded_and_ordered_by_publication_time(self):
        records = [
            _record(f"C{index:03d}", facts=None, published_at=f"2026-09-{10 + index // 30:02d}T{index % 24:02d}:00:00Z")
            for index in range(BATCH_RECORD_LIMIT + 1)
        ]
        advisor = _Scripted({"groups": []}, {"groups": []})
        result = EventIdentity(advisor).evaluate(records)
        self.assertEqual([len(request.records) for request in advisor.requests], [BATCH_RECORD_LIMIT])
        # The 61st record forms a batch of one, which needs no call.
        self.assertEqual(len(result.groups), BATCH_RECORD_LIMIT + 1)
        ordered = sorted(records, key=lambda record: (record.candidate.published_at, record.candidate.candidate_id))
        self.assertEqual(
            [record.candidate_id for record in advisor.requests[0].records],
            [record.candidate.candidate_id for record in ordered[:BATCH_RECORD_LIMIT]],
        )


class EventIdentityProviderTests(unittest.TestCase):
    def test_provider_sends_self_contained_request_and_uses_shared_retry(self):
        bodies = []
        inner = json.dumps({"groups": []})

        def transport(endpoint, *, headers, body, timeout_seconds):
            bodies.append(json.loads(body))
            if len(bodies) == 1:
                return MaiAgentHttpResponse(503, b"")
            return MaiAgentHttpResponse(200, json.dumps({"content": inner}).encode())

        config = MaiAgentEventIdentityProviderConfig("https://maiagent.invalid", "key", "helper")
        provider = build_maiagent_event_identity_provider(config, transport=transport)
        result = EventIdentity(provider).evaluate(_three_records())
        self.assertEqual(len(result.groups), 3)
        self.assertEqual(len(bodies), 2)
        self.assertEqual(bodies[0], bodies[1])
        self.assertIsNone(bodies[0]["conversation"])
        self.assertEqual(bodies[0]["attachments"], [])
        content = json.loads(bodies[0]["message"]["content"])
        self.assertEqual(content["task_identity"], TASK_IDENTITY)
        self.assertEqual(len(content["event_identity_request"]["records"]), 3)

    def test_provider_is_built_from_the_shared_helper_key(self):
        environ = {
            "MAIAGENT_API_BASE": "https://maiagent.invalid",
            "MAIAGENT_API_KEY": "key",
            "MAIAGENT_STRUCTURED_HELPER_CHATBOT_ID": "helper",
        }
        self.assertIsNotNone(build_maiagent_event_identity_provider(environ=environ))
        self.assertIsNone(build_maiagent_event_identity_provider(environ={**environ, "MAIAGENT_STRUCTURED_HELPER_CHATBOT_ID": ""}))


class EventIdentityDisclosureTests(unittest.TestCase):
    def test_grouping_gap_discloses_possible_duplicates_not_exclusion(self):
        notes = ReportService._render_disclosure(ReportDisclosure(event_identity_gap_count=1))
        self.assertEqual(notes, ["本期跨來源同事件合併有部分因技術問題未完成，本報告可能含重複報導的事件。"])
        self.assertFalse(ReportDisclosure(event_identity_gap_count=1).complete)


if __name__ == "__main__":
    unittest.main()
