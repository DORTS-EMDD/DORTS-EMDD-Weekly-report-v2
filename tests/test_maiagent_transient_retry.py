"""RC-6: one shared, bounded MaiAgent transport policy for every task."""

from __future__ import annotations

import json
from pathlib import Path
import unittest

from src.weekly_report.contracts import (
    SemanticProviderConfigurationFailure,
    SemanticProviderTechnicalFailure,
    TechnicalGap,
    TechnicalGapKind,
)
from src.weekly_report.maiagent_transport import (
    MAIAGENT_HELPER_TIMEOUT_SECONDS,
    MaiAgentHttpResponse,
    request_maiagent_proposal,
)
from src.weekly_report.writer import MaiAgentWriterProvider, MaiAgentWriterProviderConfig

ROOT = Path(__file__).resolve().parents[1]
ADAPTERS = (
    "maiagent_evidence_metadata_provider.py",
    "maiagent_semantic_judge_provider.py",
    "maiagent_scope_provider.py",
    "category_semantic_provider.py",
    "maiagent_taxonomy_provider.py",
    "maiagent_reportability_provider.py",
    "maiagent_validation_provider.py",
    "writer.py",
)


def _ok(proposal: dict) -> MaiAgentHttpResponse:
    return MaiAgentHttpResponse(200, json.dumps({"content": json.dumps(proposal)}).encode())


class _Scripted:
    """Return or raise each scripted outcome in order and record requests."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def __call__(self, endpoint, *, headers, body, timeout_seconds):
        self.calls.append((endpoint, dict(headers), body, timeout_seconds))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _call(transport):
    return request_maiagent_proposal(
        transport,
        "https://maiagent.example/api/v1/chatbots/x/completions/",
        headers={"Authorization": "Api-Key secret"},
        body=b'{"message": "identical"}',
        timeout_seconds=MAIAGENT_HELPER_TIMEOUT_SECONDS,
        task="unit",
    )


class SharedTransportPolicyTests(unittest.TestCase):
    def test_success_needs_one_call(self):
        transport = _Scripted(_ok({"a": 1}))
        self.assertEqual(_call(transport), {"a": 1})
        self.assertEqual(len(transport.calls), 1)

    def test_transient_failure_then_success_uses_identical_request(self):
        for first in (
            TimeoutError(),
            RuntimeError("connection reset"),
            MaiAgentHttpResponse(429, b""),
            MaiAgentHttpResponse(500, b""),
            MaiAgentHttpResponse(502, b""),
            MaiAgentHttpResponse(503, b""),
            MaiAgentHttpResponse(504, b""),
            MaiAgentHttpResponse(200, b'{"content": "{} {}"}'),
        ):
            with self.subTest(first=repr(first)):
                transport = _Scripted(first, _ok({"ok": True}))
                self.assertEqual(_call(transport), {"ok": True})
                self.assertEqual(len(transport.calls), 2)
                self.assertEqual(transport.calls[0], transport.calls[1])

    def test_transient_failure_twice_raises_typed_failure_after_two_attempts(self):
        for outcome, failure_class in (
            (TimeoutError(), "TIMEOUT"),
            (MaiAgentHttpResponse(503, b""), "HTTP_503"),
            (MaiAgentHttpResponse(200, b"not-json"), "UNPARSEABLE_RESPONSE"),
        ):
            with self.subTest(failure_class=failure_class):
                transport = _Scripted(outcome, outcome)
                with self.assertRaises(SemanticProviderTechnicalFailure) as raised:
                    _call(transport)
                self.assertEqual(raised.exception.failure_class, failure_class)
                self.assertEqual(raised.exception.attempts, 2)
                self.assertTrue(raised.exception.transient)
                self.assertNotIn("secret", str(raised.exception))
                self.assertEqual(len(transport.calls), 2)

    def test_configuration_failures_stop_without_retry(self):
        for status in (401, 403, 404):
            with self.subTest(status=status):
                transport = _Scripted(MaiAgentHttpResponse(status, b"secret"))
                with self.assertRaises(SemanticProviderConfigurationFailure):
                    _call(transport)
                self.assertEqual(len(transport.calls), 1)

    def test_other_non_200_is_non_transient_and_not_retried(self):
        for status in (400, 413, 422):
            with self.subTest(status=status):
                transport = _Scripted(MaiAgentHttpResponse(status, b""))
                with self.assertRaises(SemanticProviderTechnicalFailure) as raised:
                    _call(transport)
                self.assertFalse(raised.exception.transient)
                self.assertEqual(raised.exception.attempts, 1)
                self.assertEqual(len(transport.calls), 1)

    def test_parseable_response_is_never_retried_whatever_its_content(self):
        # Schema validity and semantic outcomes belong to the owners.
        for proposal in ({"relation": "UNCERTAIN"}, {"unexpected": "shape"}, {"proposed_state": "NOT_REPORTABLE"}):
            with self.subTest(proposal=proposal):
                transport = _Scripted(_ok(proposal))
                self.assertEqual(_call(transport), proposal)
                self.assertEqual(len(transport.calls), 1)

    def test_every_adapter_uses_the_shared_policy_and_no_direct_transport_call(self):
        for name in ADAPTERS:
            with self.subTest(adapter=name):
                source = (ROOT / "src" / "weekly_report" / name).read_text(encoding="utf-8")
                self.assertIn("request_maiagent_proposal(", source)
                self.assertNotIn("response = self._transport(", source)

    def test_writer_retries_a_transient_failure_once(self):
        config = MaiAgentWriterProviderConfig("https://maiagent.example", "secret", "writer-id")
        block = {"event_id": "E1", "headline": "標題", "factual_summary": "摘要", "taipei_insight": "啟示"}
        transport = _Scripted(MaiAgentHttpResponse(503, b""), _ok(block))
        self.assertEqual(MaiAgentWriterProvider(config, transport=transport)({"writer_request": {}}), block)
        self.assertEqual(len(transport.calls), 2)


class TechnicalGapTests(unittest.TestCase):
    def test_gap_kinds_derive_from_failure_type(self):
        transient = SemanticProviderTechnicalFailure("TIMEOUT", attempts=2, transient=True)
        permanent = SemanticProviderTechnicalFailure("HTTP_400", attempts=1, transient=False)
        self.assertEqual(TechnicalGap.from_failure("Evidence", "C1", transient).kind, TechnicalGapKind.TRANSIENT_FAILURE_AFTER_RETRY)
        self.assertEqual(TechnicalGap.from_failure("Writer", "E1", permanent).kind, TechnicalGapKind.NON_TRANSIENT_PROVIDER_FAILURE)
        with self.assertRaises(TypeError):
            TechnicalGap.from_failure("Evidence", "C1", RuntimeError("not technical"))
        with self.assertRaises(ValueError):
            TechnicalGap("Delivery", "E1", TechnicalGapKind.TRANSIENT_FAILURE_AFTER_RETRY, "TIMEOUT", 2)


if __name__ == "__main__":
    unittest.main()
