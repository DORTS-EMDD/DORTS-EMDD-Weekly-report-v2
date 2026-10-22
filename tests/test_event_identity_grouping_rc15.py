"""RC-15: batch grouping proposal validated by the single EventIdentity owner."""

from __future__ import annotations

import json
import unittest

from src.weekly_report.contracts import (
    EventIdentityFacts,
    IdentityMetadataSupport,
    RegionResolution,
    RegionResolutionBasis,
    SemanticProviderConfigurationFailure,
    SemanticProviderTechnicalFailure,
    TechnicalGapKind,
)
from src.weekly_report.event_identity import (
    BATCH_CHARACTER_LIMIT,
    LEAD_CHARACTER_LIMIT,
    LEAD_SENTENCE_LIMIT,
    LEAD_TIERS,
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

    def test_record_in_two_groups_contributes_only_proposed_pairs(self):
        # RC-21: overlapping groups are pair proposals; complete-link grouping
        # never merges EN with OTHER, which were not proposed together.
        response = {
            "groups": [
                {"members": [_member("EN"), _member("JA")]},
                {"members": [_member("JA"), _member("OTHER")]},
            ]
        }
        result = EventIdentity(_Scripted(response)).evaluate(_three_records())
        self.assertEqual(result.technical_gaps, ())
        self.assertEqual(len(result.groups), 2)
        merged = [group.member_candidate_ids for group in result.groups if len(group.member_candidate_ids) == 2]
        self.assertEqual(len(merged), 1)
        self.assertIn("JA", merged[0])
        self.assertNotEqual(set(merged[0]), {"EN", "OTHER"})
        self.assertTrue(any(item.reason == "INSUFFICIENT_IDENTITY" for item in result.diagnostics))

    def test_pair_in_different_established_regions_is_not_merged(self):
        # RC-22: one occurrence happens in one country/region; a proposed pair
        # whose members EvidenceService placed in different regions is dropped.
        def located(candidate_id, region_id, name, text):
            resolution = RegionResolution(
                RegionResolutionBasis.SOURCE_STATED, region_id=region_id, display_name=name,
                source_field="country", source_value=name, reference_version="geo-reference-v2",
            )
            facts = EventIdentityFacts(
                country=name,
                metadata_support=(IdentityMetadataSupport("country", 0, len(name)),),
                region_resolution=resolution,
            )
            return _record(candidate_id, facts=facts, body=f"{name}: {text}")

        records = [
            located("DAEGU", "KR", "Korea", "Daegu ran a subway fire drill."),
            located("NAGOYA1", "JP", "Japan", "Nagoya ran a derailment drill."),
            located("NAGOYA2", "JP", "Japan", "Nagoya subway staff drilled for a derailment."),
            _record("UNSTATED", facts=None, body="A subway drill took place."),
        ]
        response = {"groups": [{"members": [_member(name) for name in ("DAEGU", "NAGOYA1", "NAGOYA2")]}]}
        result = EventIdentity(_Scripted(response)).evaluate(records)
        self.assertEqual(
            sorted(group.member_candidate_ids for group in result.groups),
            [("DAEGU",), ("NAGOYA1", "NAGOYA2"), ("UNSTATED",)],
        )
        self.assertEqual(result.technical_gaps, ())
        self.assertEqual(
            sorted(item.candidate_ids for item in result.diagnostics if item.reason == "PROPOSAL_REGION_CONFLICT"),
            [("DAEGU", "NAGOYA1"), ("DAEGU", "NAGOYA2")],
        )

    def test_record_repeated_inside_one_group_invalidates_that_group(self):
        records = _three_records() + [_record("SOLO", facts=None, body="Another depot fire.")]
        response = {
            "groups": [
                {"members": [_member("EN"), _member("EN")]},
                {"members": [_member("OTHER"), _member("SOLO")]},
            ]
        }
        result = EventIdentity(_Scripted(response)).evaluate(records)
        self.assertIn(("OTHER", "SOLO"), [tuple(sorted(group.member_candidate_ids)) for group in result.groups])
        self.assertEqual(
            [(gap.subject_id, gap.failure_class) for gap in result.technical_gaps],
            [("event-identity-batch-1:group-1", "DUPLICATE_MEMBERSHIP")],
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

    def test_a_run_within_the_payload_bound_is_one_request_whatever_its_size(self):
        # RC-18: record count never splits a run; only the payload bound does.
        records = [
            _record(f"C{index:03d}", facts=None, published_at=f"2026-09-{10 + index // 40:02d}T{index % 24:02d}:00:00Z")
            for index in range(90)
        ]
        advisor = _Scripted({"groups": []})
        result = EventIdentity(advisor).evaluate(records)
        self.assertEqual([len(request.records) for request in advisor.requests], [90])
        self.assertEqual([record.record_id for record in advisor.requests[0].records][:3], ["R1", "R2", "R3"])
        self.assertNotIn("PROPOSAL_BATCH_SPLIT", [item.reason for item in result.diagnostics])

    def test_leads_shrink_before_a_run_is_split(self):
        long_body = " ".join(f"Sentence {index} reports the tram depot relocation in detail." for index in range(12))
        records = [_record(f"C{index:03d}", facts=None, body=long_body) for index in range(130)]
        advisor = _Scripted({"groups": []})
        EventIdentity(advisor).evaluate(records)
        self.assertEqual(len(advisor.requests), 1)
        lead = advisor.requests[0].records[0].sentences
        self.assertLess(len(lead), LEAD_SENTENCE_LIMIT)
        self.assertIn(len(lead), [sentences for sentences, _ in LEAD_TIERS])
        payload = sum(len(json.dumps(record.as_payload(), ensure_ascii=False)) for record in advisor.requests[0].records)
        self.assertLessEqual(payload, BATCH_CHARACTER_LIMIT)

    def test_a_split_is_the_last_resort_and_is_diagnosed(self):
        long_body = " ".join(f"Sentence {index} reports the tram depot relocation in great detail today." for index in range(12))
        records = [
            _record(f"C{index:03d}", facts=None, body=long_body, published_at=f"2026-09-15T{index % 24:02d}:{index % 60:02d}:00Z")
            for index in range(400)
        ]
        advisor = _Scripted(*({"groups": []} for _ in range(10)))
        result = EventIdentity(advisor).evaluate(records)
        self.assertGreater(len(advisor.requests), 1)
        self.assertTrue(all(len(request.records[0].sentences) <= LEAD_TIERS[-1][0] for request in advisor.requests))
        split = [item for item in result.diagnostics if item.reason == "PROPOSAL_BATCH_SPLIT"]
        self.assertEqual(len(split), 1)
        self.assertEqual(split[0].detail, f"{len(advisor.requests)} batches")


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


class CandidateEventFocusTests(unittest.TestCase):
    def test_excerpt_is_the_candidates_scope_event_focus(self):
        # RC-20: Event Identity compares Candidate events, not document leads.
        from dataclasses import replace

        from src.weekly_report.contracts import ScopeResult, ScopeState

        body = "The council met on Monday. The mayor warned the line may open late. Trains arrived last week."
        record = _record("C1", facts=None, body=body)
        focus = [{"start": body.index("The mayor"), "end": body.index(" Trains")}]
        record = replace(record, scope=ScopeResult("C1", ScopeState.IN_SCOPE, provenance={"candidate_event_focus": focus}))
        advisor = _Scripted({"groups": []})
        EventIdentity(advisor).evaluate([record, _record("C2", facts=None, body="Another event happened.")])
        sentences = advisor.requests[0].records[0].sentences
        self.assertEqual([(s.sentence_id, s.text) for s in sentences], [("S2", "The mayor warned the line may open late.")])
