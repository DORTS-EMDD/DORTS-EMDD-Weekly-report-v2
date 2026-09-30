"""Focused tests for the authoritative proposal-only E&M Taxonomy owner."""

from __future__ import annotations

from collections.abc import Mapping
from traceback import format_exception
from unittest import TestCase

from src.weekly_report.contracts import (
    CanonicalCandidate,
    CategoryId,
    CategoryResolutionReason,
    CategoryResult,
    CategoryState,
    EvidenceResult,
    EvidenceState,
    EventGroup,
    EventIdentityRecord,
    ScopeResult,
    ScopeState,
    TemporalResult,
    TemporalDiagnostic,
    TaxonomyResolutionReason,
    TaxonomyState,
)
from src.weekly_report.taxonomy import (
    Taxonomy,
    TaxonomySemanticProposal,
    TaxonomyStageFailure,
)


def _record(
    candidate_id: str,
    body: str = "Traction substation breakers were replaced.",
    *,
    evidence_state: EvidenceState = EvidenceState.READY,
    scope_state: ScopeState = ScopeState.IN_SCOPE,
    date_valid: bool = True,
) -> EventIdentityRecord:
    evidence = EvidenceResult(
        candidate_id=candidate_id,
        state=evidence_state,
        canonical_source_url=f"https://example.test/{candidate_id}",
        source_type="authoritative",
        substantive_content=body if evidence_state is EvidenceState.READY else "",
        reject_reason=None if evidence_state is EvidenceState.READY else "CONTENT_UNAVAILABLE",
    )
    return EventIdentityRecord(
        CanonicalCandidate(candidate_id, f"Title {candidate_id}", evidence.canonical_source_url),
        evidence,
        ScopeResult(candidate_id, scope_state),
        TemporalResult(
            candidate_id,
            date_valid,
            diagnostic=TemporalDiagnostic.NONE if date_valid else TemporalDiagnostic.OUT_OF_RANGE,
        ),
    )


def _group(*candidate_ids: str, event_id: str = "E1") -> EventGroup:
    ids = tuple(sorted(candidate_ids))
    return EventGroup(event_id, ids, ids[0], identity_basis=())


def _assigned(group: EventGroup) -> CategoryResult:
    return CategoryResult(
        category_state=CategoryState.CATEGORY_ASSIGNED,
        event_id=group.event_id,
        primary_category_id=CategoryId.TECHNICAL_DEVELOPMENT,
        primary_category=CategoryId.TECHNICAL_DEVELOPMENT.display_label,
        classification_reason="PRINCIPAL_ACTION_TECHNICAL_DEVELOPMENT",
    )


def _category_unresolved(group: EventGroup) -> CategoryResult:
    return CategoryResult(
        category_state=CategoryState.CATEGORY_UNRESOLVED,
        event_id=group.event_id,
        classification_reason=CategoryState.CATEGORY_UNRESOLVED.value,
        category_resolution_reason=CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION,
    )


def _proposal(
    group: EventGroup,
    *,
    state: str = TaxonomyState.TAXONOMY_EVALUATED.value,
    systems: list[str] | None = None,
    reason: str | None = None,
    support: list[dict[str, str]] | None = None,
    conflict: list[dict[str, str]] | None = None,
    insufficient: dict[str, object] | None = None,
):
    return {
        "event_id": group.event_id,
        "taxonomy_state": state,
        "systems": systems or [],
        "taxonomy_resolution_reason": reason,
        "support_citations": support or [],
        "conflict_citations": conflict or [],
        "insufficient_provenance": insufficient,
    }


class _FakeProvider:
    def __init__(self, response=None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.calls = []

    def __call__(self, request):
        self.calls.append(request)
        if self.error:
            raise self.error
        return self.response(request) if callable(self.response) else self.response


class TaxonomyOwnerTests(TestCase):
    def test_category_unresolved_returns_not_evaluated_without_provider_call(self):
        group = _group("C1")
        provider = _FakeProvider()
        result = Taxonomy(provider).evaluate(group, (_record("C1"),), _category_unresolved(group))
        self.assertEqual(result.taxonomy_state, TaxonomyState.NOT_EVALUATED)
        self.assertEqual(provider.calls, [])

    def test_category_not_evaluated_returns_not_evaluated_without_provider_call(self):
        group = _group("C1")
        provider = _FakeProvider()
        category = CategoryResult.not_evaluated(event_id=group.event_id)
        result = Taxonomy(provider).evaluate(group, (_record("C1"),), category)
        self.assertEqual(result.taxonomy_state, TaxonomyState.NOT_EVALUATED)
        self.assertEqual(provider.calls, [])

    def test_mismatched_not_evaluated_category_event_id_fails_before_reachability(self):
        group = _group("C1")
        provider = _FakeProvider()
        category = CategoryResult.not_evaluated(event_id="OTHER_EVENT")
        with self.assertRaises(TaxonomyStageFailure) as raised:
            Taxonomy(provider).evaluate(group, (_record("C1"),), category)
        self.assertEqual(raised.exception.event_id, group.event_id)
        self.assertEqual(provider.calls, [])

    def test_empty_not_evaluated_category_event_id_fails_for_named_event_group(self):
        group = _group("C1")
        provider = _FakeProvider()
        category = CategoryResult.not_evaluated(event_id="")
        with self.assertRaises(TaxonomyStageFailure) as raised:
            Taxonomy(provider).evaluate(group, (_record("C1"),), category)
        self.assertEqual(raised.exception.event_id, group.event_id)
        self.assertEqual(provider.calls, [])

    def test_mismatched_assigned_category_event_id_fails_before_provider_call(self):
        group = _group("C1")
        provider = _FakeProvider()
        category = CategoryResult(
            category_state=CategoryState.CATEGORY_ASSIGNED,
            event_id="OTHER_EVENT",
            primary_category_id=CategoryId.TECHNICAL_DEVELOPMENT,
            primary_category=CategoryId.TECHNICAL_DEVELOPMENT.display_label,
            classification_reason="PRINCIPAL_ACTION_TECHNICAL_DEVELOPMENT",
        )
        with self.assertRaises(TaxonomyStageFailure) as raised:
            Taxonomy(provider).evaluate(group, (_record("C1"),), category)
        self.assertEqual(raised.exception.event_id, group.event_id)
        self.assertEqual(provider.calls, [])

    def test_assigned_category_reaches_provider_and_request_excludes_category_fields(self):
        group = _group("B", "A")
        records = (_record("B", "B body"), _record("A", "A body"))
        provider = _FakeProvider(
            lambda request: _proposal(
                group,
                systems=[],
            )
        )
        Taxonomy(provider).evaluate(group, records, _assigned(group))
        request = provider.calls[0]
        self.assertEqual(request.member_candidate_ids, ("A", "B"))
        self.assertEqual(request.as_payload(), {
            "event_id": "E1",
            "members": [
                {"candidate_id": "A", "substantive_content": "A body"},
                {"candidate_id": "B", "substantive_content": "B body"},
            ],
        })
        self.assertFalse(hasattr(request, "category_state"))
        self.assertFalse(any("title" in member for member in request.as_payload()["members"]))
        self.assertNotIn("expected", request.as_payload())
        self.assertNotIn("golden", request.as_payload())

    def test_request_and_proposal_boundaries_isolate_caller_collections(self):
        from src.weekly_report.taxonomy import TaxonomySemanticMember, TaxonomySemanticRequest

        members = [TaxonomySemanticMember("C1", "body")]
        request = TaxonomySemanticRequest("E1", members)
        members.append(TaxonomySemanticMember("C2", "other"))
        self.assertEqual(request.member_candidate_ids, ("C1",))

        systems = ["POWER_SUPPLY"]
        proposal = TaxonomySemanticProposal("E1", TaxonomyState.TAXONOMY_EVALUATED, systems=systems)
        systems.append("SIGNALLING")
        self.assertEqual(proposal.systems, ("POWER_SUPPLY",))

    def test_evaluated_empty_is_accepted(self):
        group = _group("C1")
        provider = _FakeProvider(_proposal(group))
        result = Taxonomy(provider).evaluate(group, (_record("C1"),), _assigned(group))
        self.assertEqual(result.taxonomy_state, TaxonomyState.TAXONOMY_EVALUATED)
        self.assertEqual(result.systems, ())

    def test_evaluated_one_system_requires_and_resolves_support(self):
        group = _group("C1")
        body = "Traction substation breakers were replaced."
        provider = _FakeProvider(_proposal(
            group,
            systems=["POWER_SUPPLY"],
            support=[{"system_id": "POWER_SUPPLY", "candidate_id": "C1", "exact_quote": "Traction substation"}],
        ))
        result = Taxonomy(provider).evaluate(group, (_record("C1", body),), _assigned(group))
        self.assertEqual(result.systems[0].value, "POWER_SUPPLY")
        span = result.support_spans[0]
        self.assertEqual(body[span.start:span.end], "Traction substation")

    def test_multi_label_is_canonically_ordered(self):
        group = _group("C1")
        body = "Signalling and traction substation equipment were upgraded."
        provider = _FakeProvider(_proposal(
            group,
            systems=["POWER_SUPPLY", "SIGNALLING"],
            support=[
                {"system_id": "POWER_SUPPLY", "candidate_id": "C1", "exact_quote": "traction substation"},
                {"system_id": "SIGNALLING", "candidate_id": "C1", "exact_quote": "Signalling"},
            ],
        ))
        result = Taxonomy(provider).evaluate(group, (_record("C1", body),), _assigned(group))
        self.assertEqual([item.value for item in result.systems], ["SIGNALLING", "POWER_SUPPLY"])

    def test_duplicate_systems_are_rejected(self):
        group = _group("C1")
        provider = _FakeProvider(_proposal(group, systems=["POWER_SUPPLY", "POWER_SUPPLY"]))
        with self.assertRaises(TaxonomyStageFailure):
            Taxonomy(provider).evaluate(group, (_record("C1"),), _assigned(group))

    def test_provider_cannot_propose_not_evaluated(self):
        group = _group("C1")
        provider = _FakeProvider(_proposal(group, state=TaxonomyState.NOT_EVALUATED.value))
        with self.assertRaises(TaxonomyStageFailure):
            Taxonomy(provider).evaluate(group, (_record("C1"),), _assigned(group))

    def test_evaluated_non_null_reason_is_rejected(self):
        group = _group("C1")
        provider = _FakeProvider(_proposal(
            group,
            reason=TaxonomyResolutionReason.INSUFFICIENT_SYSTEM_EVIDENCE.value,
        ))
        with self.assertRaises(TaxonomyStageFailure):
            Taxonomy(provider).evaluate(group, (_record("C1"),), _assigned(group))

    def test_unresolved_non_empty_systems_are_rejected(self):
        group = _group("C1")
        provider = _FakeProvider(_proposal(
            group,
            state=TaxonomyState.TAXONOMY_UNRESOLVED.value,
            systems=["POWER_SUPPLY"],
            reason=TaxonomyResolutionReason.INSUFFICIENT_SYSTEM_EVIDENCE.value,
            insufficient={"member_candidate_ids": ["C1"], "diagnostic": "insufficient"},
        ))
        with self.assertRaises(TaxonomyStageFailure):
            Taxonomy(provider).evaluate(group, (_record("C1"),), _assigned(group))

    def test_assigned_system_missing_support_is_rejected(self):
        group = _group("C1")
        provider = _FakeProvider(_proposal(group, systems=["POWER_SUPPLY"]))
        with self.assertRaises(TaxonomyStageFailure):
            Taxonomy(provider).evaluate(group, (_record("C1"),), _assigned(group))

    def test_support_for_unassigned_system_is_rejected(self):
        group = _group("C1")
        provider = _FakeProvider(_proposal(
            group,
            support=[{"system_id": "POWER_SUPPLY", "candidate_id": "C1", "exact_quote": "Traction"}],
        ))
        with self.assertRaises(TaxonomyStageFailure):
            Taxonomy(provider).evaluate(group, (_record("C1"),), _assigned(group))

    def test_nonmember_support_is_rejected(self):
        group = _group("C1")
        provider = _FakeProvider(_proposal(
            group,
            systems=["POWER_SUPPLY"],
            support=[{"system_id": "POWER_SUPPLY", "candidate_id": "C2", "exact_quote": "Traction"}],
        ))
        with self.assertRaises(TaxonomyStageFailure):
            Taxonomy(provider).evaluate(group, (_record("C1"),), _assigned(group))

    def test_empty_quote_is_rejected(self):
        group = _group("C1")
        provider = _FakeProvider(_proposal(
            group,
            systems=["POWER_SUPPLY"],
            support=[{"system_id": "POWER_SUPPLY", "candidate_id": "C1", "exact_quote": ""}],
        ))
        with self.assertRaises(TaxonomyStageFailure):
            Taxonomy(provider).evaluate(group, (_record("C1"),), _assigned(group))

    def test_quote_not_found_is_rejected(self):
        group = _group("C1")
        provider = _FakeProvider(_proposal(
            group,
            systems=["POWER_SUPPLY"],
            support=[{"system_id": "POWER_SUPPLY", "candidate_id": "C1", "exact_quote": "not present"}],
        ))
        with self.assertRaises(TaxonomyStageFailure):
            Taxonomy(provider).evaluate(group, (_record("C1"),), _assigned(group))

    def test_ambiguous_quote_is_rejected(self):
        group = _group("C1")
        provider = _FakeProvider(_proposal(
            group,
            systems=["POWER_SUPPLY"],
            support=[{"system_id": "POWER_SUPPLY", "candidate_id": "C1", "exact_quote": "power"}],
        ))
        with self.assertRaises(TaxonomyStageFailure):
            Taxonomy(provider).evaluate(
                group,
                (_record("C1", "power and power"),),
                _assigned(group),
            )

    def test_unique_exact_quote_maps_to_exact_source_slice(self):
        group = _group("C1")
        body = "A unique traction substation was inspected."
        provider = _FakeProvider(_proposal(
            group,
            systems=["POWER_SUPPLY"],
            support=[{"system_id": "POWER_SUPPLY", "candidate_id": "C1", "exact_quote": "traction substation"}],
        ))
        result = Taxonomy(provider).evaluate(group, (_record("C1", body),), _assigned(group))
        span = result.support_spans[0]
        self.assertEqual(body[span.start:span.end], "traction substation")

    def test_insufficient_provenance_requires_exact_member_set_and_diagnostic(self):
        group = _group("C1", "C2")
        valid = _proposal(
            group,
            state=TaxonomyState.TAXONOMY_UNRESOLVED.value,
            reason=TaxonomyResolutionReason.INSUFFICIENT_SYSTEM_EVIDENCE.value,
            insufficient={"member_candidate_ids": ["C1", "C2"], "diagnostic": "No parent is established."},
        )
        result = Taxonomy(lambda _: valid).evaluate(
            group, (_record("C2", "body 2"), _record("C1", "body 1")), _assigned(group)
        )
        self.assertEqual(result.taxonomy_resolution_reason, TaxonomyResolutionReason.INSUFFICIENT_SYSTEM_EVIDENCE)
        for member_ids in (["C1"], ["C1", "C2", "C3"]):
            invalid = dict(valid, insufficient_provenance={"member_candidate_ids": member_ids, "diagnostic": "why"})
            with self.subTest(member_ids=member_ids), self.assertRaises(TaxonomyStageFailure):
                Taxonomy(lambda _: invalid).evaluate(group, (_record("C1", "body 1"), _record("C2", "body 2")), _assigned(group))

    def test_insufficient_provenance_requires_nonempty_diagnostic(self):
        group = _group("C1")
        proposal = _proposal(
            group,
            state=TaxonomyState.TAXONOMY_UNRESOLVED.value,
            reason=TaxonomyResolutionReason.INSUFFICIENT_SYSTEM_EVIDENCE.value,
            insufficient={"member_candidate_ids": ["C1"], "diagnostic": ""},
        )
        with self.assertRaises(TaxonomyStageFailure):
            Taxonomy(lambda _: proposal).evaluate(group, (_record("C1"),), _assigned(group))

    def test_valid_conflict_requires_two_distinct_hypotheses(self):
        group = _group("C1", "C2")
        proposal = _proposal(
            group,
            state=TaxonomyState.TAXONOMY_UNRESOLVED.value,
            reason=TaxonomyResolutionReason.CONFLICTING_SYSTEM_EVIDENCE.value,
            conflict=[
                {"system_id": "SIGNALLING", "candidate_id": "C1", "exact_quote": "signal"},
                {"system_id": "POWER_SUPPLY", "candidate_id": "C2", "exact_quote": "power"},
            ],
        )
        result = Taxonomy(lambda _: proposal).evaluate(
            group,
            (_record("C2", "power equipment"), _record("C1", "signal equipment")),
            _assigned(group),
        )
        self.assertEqual(result.taxonomy_state, TaxonomyState.TAXONOMY_UNRESOLVED)
        self.assertEqual(len(result.provenance.conflict_spans), 2)

    def test_conflict_cannot_become_multilabel_or_single_hypothesis(self):
        group = _group("C1")
        for systems, conflict in (
            (["SIGNALLING", "POWER_SUPPLY"], []),
            ([], [{"system_id": "SIGNALLING", "candidate_id": "C1", "exact_quote": "signal"}]),
        ):
            proposal = _proposal(
                group,
                state=TaxonomyState.TAXONOMY_UNRESOLVED.value,
                systems=systems,
                reason=TaxonomyResolutionReason.CONFLICTING_SYSTEM_EVIDENCE.value,
                conflict=conflict,
            )
            with self.subTest(systems=systems), self.assertRaises(TaxonomyStageFailure):
                Taxonomy(lambda _: proposal).evaluate(group, (_record("C1", "signal"),), _assigned(group))

    def test_provider_exception_and_malformed_proposal_are_technical_failures_without_result(self):
        group = _group("C1")
        for provider in (_FakeProvider(error=RuntimeError("provider down")), _FakeProvider({"bad": "shape"})):
            with self.subTest(provider=provider.error is not None):
                with self.assertRaises(TaxonomyStageFailure) as raised:
                    Taxonomy(provider).evaluate(group, (_record("C1"),), _assigned(group))
                if provider.error is None:
                    self.assertEqual(
                        str(raised.exception),
                        "taxonomy proposal fields do not match the proposal contract",
                    )

    def test_provider_is_called_once_with_no_retry_or_fallback(self):
        group = _group("C1")
        provider = _FakeProvider(error=RuntimeError("down"))
        with self.assertRaises(TaxonomyStageFailure) as raised:
            Taxonomy(provider).evaluate(group, (_record("C1"),), _assigned(group))
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(raised.exception.event_id, group.event_id)

    def test_raw_provider_exception_is_sanitized_without_chained_secret(self):
        group = _group("C1")
        secret = "SYNTHETIC_SECRET_PROVIDER_PAYLOAD"
        provider = _FakeProvider(error=RuntimeError(secret))
        with self.assertRaises(TaxonomyStageFailure) as raised:
            Taxonomy(provider).evaluate(group, (_record("C1"),), _assigned(group))
        failure = raised.exception
        self.assertEqual(failure.event_id, group.event_id)
        self.assertNotIn(secret, str(failure))
        self.assertIsNone(failure.__cause__)
        self.assertIsNone(failure.__context__)

    def test_provider_taxonomy_failure_is_sanitized_as_owner_failure(self):
        group = _group("C1")
        secret = "SYNTHETIC_UNSAFE_PROVIDER_FAILURE"
        provider_failure = TaxonomyStageFailure(secret, event_id="")
        provider_failure.__cause__ = RuntimeError(secret)
        provider = _FakeProvider(error=provider_failure)
        with self.assertRaises(TaxonomyStageFailure) as raised:
            Taxonomy(provider).evaluate(group, (_record("C1"),), _assigned(group))
        failure = raised.exception
        self.assertEqual(failure.event_id, group.event_id)
        self.assertNotIn(secret, str(failure))
        self.assertNotIn(secret, repr(failure))
        self.assertIsNone(failure.__cause__)
        self.assertIsNone(failure.__context__)

    def test_malformed_proposal_exceptions_are_sanitized_without_traceback_secret(self):
        group = _group("C1")
        secret = "SYNTHETIC_SECRET_PROVIDER_PAYLOAD"

        class _SecretSequence(list):
            def __iter__(self):
                raise ValueError(secret)

        malformed_systems = _proposal(group)
        malformed_systems["systems"] = _SecretSequence()
        malformed_provenance = _proposal(
            group,
            state=TaxonomyState.TAXONOMY_UNRESOLVED.value,
            reason=TaxonomyResolutionReason.INSUFFICIENT_SYSTEM_EVIDENCE.value,
            insufficient={
                "member_candidate_ids": _SecretSequence(["C1"]),
                "diagnostic": "No parent is established.",
            },
        )

        for proposal in (malformed_systems, malformed_provenance):
            with self.subTest(proposal=proposal), self.assertRaises(TaxonomyStageFailure) as raised:
                Taxonomy(lambda _: proposal).evaluate(group, (_record("C1"),), _assigned(group))
            failure = raised.exception
            self.assertEqual(failure.event_id, group.event_id)
            self.assertIn(
                str(failure),
                {"malformed taxonomy proposal", "invalid insufficient taxonomy provenance"},
            )
            self.assertNotIn(secret, str(failure))
            self.assertNotIn(secret, repr(failure.args))
            self.assertIsNone(failure.__cause__)
            self.assertIsNone(failure.__context__)
            self.assertNotIn(secret, "".join(format_exception(failure)))

    def test_mapping_materialization_taxonomy_failure_is_sanitized(self):
        group = _group("C1")
        secret = "SYNTHETIC_SECRET_PROVIDER_PAYLOAD"

        class _UntrustedFailureSequence(list):
            def __iter__(self):
                raise TaxonomyStageFailure(secret, event_id="PROVIDER_EVENT")

        proposal = _proposal(group)
        proposal["systems"] = _UntrustedFailureSequence()
        with self.assertRaises(TaxonomyStageFailure) as raised:
            Taxonomy(lambda _: proposal).evaluate(group, (_record("C1"),), _assigned(group))
        failure = raised.exception
        self.assertEqual(failure.event_id, group.event_id)
        self.assertEqual(str(failure), "malformed taxonomy proposal")
        self.assertNotIn(secret, str(failure))
        self.assertNotIn(secret, repr(failure.args))
        self.assertIsNone(failure.__cause__)
        self.assertIsNone(failure.__context__)
        self.assertNotIn(secret, "".join(format_exception(failure)))

    def test_typed_materialization_taxonomy_failure_is_sanitized(self):
        group = _group("C1")
        secret = "SYNTHETIC_SECRET_PROVIDER_PAYLOAD"

        class _UntrustedFailureSequence(list):
            def __iter__(self):
                raise TaxonomyStageFailure(secret, event_id="PROVIDER_EVENT")

        proposal = TaxonomySemanticProposal(group.event_id, TaxonomyState.TAXONOMY_EVALUATED)
        object.__setattr__(proposal, "systems", _UntrustedFailureSequence())
        with self.assertRaises(TaxonomyStageFailure) as raised:
            Taxonomy(lambda _: proposal).evaluate(group, (_record("C1"),), _assigned(group))
        failure = raised.exception
        self.assertEqual(failure.event_id, group.event_id)
        self.assertEqual(str(failure), "malformed taxonomy proposal")
        self.assertNotIn(secret, str(failure))
        self.assertNotIn(secret, repr(failure.args))
        self.assertIsNone(failure.__cause__)
        self.assertIsNone(failure.__context__)
        self.assertNotIn(secret, "".join(format_exception(failure)))

    def test_top_level_mapping_key_iteration_taxonomy_failure_is_sanitized(self):
        group = _group("C1")
        secret = "SYNTHETIC_SECRET_PROVIDER_PAYLOAD"

        class _UntrustedMapping(Mapping):
            def __iter__(self):
                raise TaxonomyStageFailure(secret, event_id="PROVIDER_EVENT")

            def __len__(self):
                return len(_PROPOSAL_FIELDS_FOR_TEST)

            def __getitem__(self, key):
                raise KeyError(key)

        _PROPOSAL_FIELDS_FOR_TEST = {
            "event_id",
            "taxonomy_state",
            "systems",
            "taxonomy_resolution_reason",
            "support_citations",
            "conflict_citations",
            "insufficient_provenance",
        }
        with self.assertRaises(TaxonomyStageFailure) as raised:
            Taxonomy(lambda _: _UntrustedMapping()).evaluate(
                group, (_record("C1"),), _assigned(group)
            )
        failure = raised.exception
        self.assertEqual(failure.event_id, group.event_id)
        self.assertEqual(str(failure), "malformed taxonomy proposal")
        self.assertNotIn(secret, str(failure))
        self.assertNotIn(secret, repr(failure.args))
        self.assertIsNone(failure.__cause__)
        self.assertIsNone(failure.__context__)
        self.assertNotIn(secret, "".join(format_exception(failure)))

    def test_top_level_mapping_field_comparison_taxonomy_failure_is_sanitized(self):
        group = _group("C1")
        secret = "SYNTHETIC_SECRET_PROVIDER_PAYLOAD"
        base = _proposal(group)

        class _UntrustedKey(str):
            __hash__ = str.__hash__

            def __eq__(self, other):
                raise TaxonomyStageFailure(secret, event_id="PROVIDER_EVENT")

        class _UntrustedMapping(Mapping):
            def __iter__(self):
                return iter([_UntrustedKey("event_id"), *[key for key in base if key != "event_id"]])

            def __len__(self):
                return len(base)

            def __getitem__(self, key):
                return base[key]

        with self.assertRaises(TaxonomyStageFailure) as raised:
            Taxonomy(lambda _: _UntrustedMapping()).evaluate(
                group, (_record("C1"),), _assigned(group)
            )
        failure = raised.exception
        self.assertEqual(failure.event_id, group.event_id)
        self.assertEqual(str(failure), "malformed taxonomy proposal")
        self.assertNotIn(secret, str(failure))
        self.assertNotIn(secret, repr(failure.args))
        self.assertIsNone(failure.__cause__)
        self.assertIsNone(failure.__context__)
        self.assertNotIn(secret, "".join(format_exception(failure)))

    def test_nested_proposal_validation_failure_carries_current_event_id(self):
        group = _group("C1")
        proposal = _proposal(
            group,
            systems=["POWER_SUPPLY"],
            support=[{"invalid": "citation"}],
        )
        with self.assertRaises(TaxonomyStageFailure) as raised:
            Taxonomy(lambda _: proposal).evaluate(group, (_record("C1"),), _assigned(group))
        self.assertEqual(raised.exception.event_id, group.event_id)

    def test_duplicate_system_validation_failure_carries_current_event_id(self):
        group = _group("C1")
        proposal = _proposal(group, systems=["POWER_SUPPLY", "POWER_SUPPLY"])
        with self.assertRaises(TaxonomyStageFailure) as raised:
            Taxonomy(lambda _: proposal).evaluate(group, (_record("C1"),), _assigned(group))
        self.assertEqual(raised.exception.event_id, group.event_id)

    def test_source_arrival_order_does_not_change_request_or_result(self):
        group = _group("C1", "C2")
        body = {"C1": "signal equipment", "C2": "power equipment"}

        def response(request):
            return _proposal(
                group,
                systems=["POWER_SUPPLY", "SIGNALLING"],
                support=[
                    {"system_id": "POWER_SUPPLY", "candidate_id": "C2", "exact_quote": "power"},
                    {"system_id": "SIGNALLING", "candidate_id": "C1", "exact_quote": "signal"},
                ],
            )

        owner = Taxonomy(_FakeProvider(response))
        first = owner.evaluate(group, (_record("C1", body["C1"]), _record("C2", body["C2"])), _assigned(group))
        second = owner.evaluate(group, (_record("C2", body["C2"]), _record("C1", body["C1"])), _assigned(group))
        self.assertEqual(first.as_mapping(), second.as_mapping())

    def test_cross_event_group_support_is_rejected(self):
        group = _group("C1")
        proposal = _proposal(
            group,
            systems=["POWER_SUPPLY"],
            support=[{"system_id": "POWER_SUPPLY", "candidate_id": "C2", "exact_quote": "power"}],
        )
        with self.assertRaises(TaxonomyStageFailure):
            Taxonomy(lambda _: proposal).evaluate(group, (_record("C1", "signal"),), _assigned(group))

    def test_upstream_invariants_are_consumed_not_rederived(self):
        group = _group("C1")
        for record in (
            _record("C1", evidence_state=EvidenceState.REJECTED),
            _record("C1", scope_state=ScopeState.OUT_OF_SCOPE),
            _record("C1", date_valid=False),
        ):
            with self.subTest(record=record):
                with self.assertRaises(TaxonomyStageFailure):
                    Taxonomy(_FakeProvider(_proposal(group))).evaluate(group, (record,), _assigned(group))

    def test_contextual_boundary_outcomes_are_provider_proposals_not_keyword_rules(self):
        cases = (
            "SCADA alone",
            "OCC only",
            "depot location only",
            "generic train service",
            "AI predictive maintenance",
        )
        for text in cases:
            group = _group("C1", event_id=text)
            provider = _FakeProvider(_proposal(group))
            result = Taxonomy(provider).evaluate(group, (_record("C1", text),), _assigned(group))
            self.assertEqual(result.systems, ())

    def test_explicit_contextual_proposals_are_accepted_without_string_matching(self):
        cases = (
            ("traction power", "POWER_SUPPLY", "traction power"),
            ("workshop equipment", "DEPOT_MAINTENANCE_EQUIPMENT", "workshop equipment"),
            ("rolling stock", "ROLLING_STOCK", "rolling stock"),
        )
        for body, system, quote in cases:
            with self.subTest(system=system):
                group = _group("C1", event_id=system)
                proposal = _proposal(
                    group,
                    systems=[system],
                    support=[{"system_id": system, "candidate_id": "C1", "exact_quote": quote}],
                )
                result = Taxonomy(lambda _: proposal).evaluate(group, (_record("C1", body),), _assigned(group))
                self.assertEqual(result.systems[0].value, system)

    def test_missing_concrete_provider_binding_is_a_technical_failure_for_assigned_category(self):
        group = _group("C1")
        with self.assertRaises(TaxonomyStageFailure):
            Taxonomy().evaluate(group, (_record("C1"),), _assigned(group))


if __name__ == "__main__":
    import unittest

    unittest.main()
