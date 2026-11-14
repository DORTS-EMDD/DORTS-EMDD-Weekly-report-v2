"""Opt-in MaiAgent Category acceptance over sealed Golden Event Groups.

Run one predeclared round manually with ``--run-live-maiagent``, an explicit
``--round-index``, and a deployment snapshot read-back file.
The deterministic test suite never calls a live provider.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.weekly_report import category_semantic_provider as category_provider_module
from src.weekly_report import classifier as classifier_module
from src.weekly_report.category_semantic_provider import (
    _CATEGORY_RESPONSE_SCHEMA,
    _MAIAGENT_CATEGORY_RESPONSE_SCHEMA,
    CATEGORY_SEMANTIC_PROMPT_VERSION,
    CATEGORY_SEMANTIC_SCHEMA_VERSION,
    MAIAGENT_CATEGORY_MESSAGE_VERSION,
    MAIAGENT_CATEGORY_PROVIDER_IDENTIFIER,
    MAIAGENT_CATEGORY_SEMANTIC_HELPER_VERSION,
    MaiAgentCategorySemanticProvider,
    MaiAgentCategorySemanticProviderConfig,
    MaiAgentHttpResponse,
    UrllibMaiAgentJsonTransport,
    build_maiagent_category_classifier,
)
from src.weekly_report.maiagent_transport import (
    MAIAGENT_CONFIGURATION_HTTP_STATUSES,
    MAIAGENT_MAX_ATTEMPTS,
    MAIAGENT_TRANSIENT_HTTP_STATUSES,
    MaiAgentResponseError,
    parse_maiagent_response,
)
from src.weekly_report.classifier import (
    _CATEGORY_GUIDANCE,
    CategoryProposalViolation,
    CategorySemanticHelperResult,
    CategorySemanticRequest,
    CategorySemanticResponse,
    Classifier,
    _request_for,
)
from src.weekly_report.contracts import (
    CanonicalCandidate,
    CategoryResolutionReason,
    CategoryResult,
    CategoryState,
    EventGroup,
    EventIdentityFacts,
    EventIdentityRecord,
    EvidenceResult,
    EvidenceState,
    IdentityMetadataSupport,
    ScopeResult,
    ScopeState,
    TemporalResult,
    UnresolvedClaim,
)

FORMAL_CURRENT_CONFIGURATION_SEAL = "FORMAL_CURRENT_CONFIGURATION_SEAL"
CANDIDATE_EXPERIMENT = "CANDIDATE_EXPERIMENT"
FORMAL_SEAL_PRODUCTION_CONFIGURATION_MISMATCH = (
    "FORMAL_SEAL_PRODUCTION_CONFIGURATION_MISMATCH"
)


@dataclass(frozen=True, slots=True)
class CategoryAcceptanceConfigurationIdentity:
    """Repository-controlled identity of one Category acceptance target."""

    guidance_digest: str
    prompt_identity: str
    response_contract_identity: str
    schema_identity: str
    configuration_fingerprint: str

    def as_mapping(self) -> dict[str, str]:
        return {
            "guidance_digest": self.guidance_digest,
            "prompt_identity": self.prompt_identity,
            "response_contract_identity": self.response_contract_identity,
            "schema_identity": self.schema_identity,
            "configuration_fingerprint": self.configuration_fingerprint,
        }


class CategoryConfigurationBindingError(RuntimeError):
    """A formal seal target is not the checked-in production configuration."""

    reason_code = FORMAL_SEAL_PRODUCTION_CONFIGURATION_MISMATCH

    def __init__(self, mismatches: Mapping[str, Mapping[str, str]]) -> None:
        self.mismatches = {key: dict(value) for key, value in mismatches.items()}
        super().__init__(self.reason_code)


class _CaptureProvider:
    def __init__(self, provider, *, expected_payloads: list[str] | None = None):
        self.provider = provider
        self.last_proposal: object | None = None
        self.last_request: CategorySemanticRequest | None = None
        self.last_provenance: Mapping[str, str] = {}
        self.expected_payloads = expected_payloads
        self.call_count = 0
        self.integrity_error: str | None = None
        self.call_evidence: list[dict[str, Any]] = []

    def __call__(self, request):
        self.last_proposal = None
        self.last_request = request
        serialized = _serialized_request(request)
        evidence = {
            "request_payload_sha256": hashlib.sha256(
                serialized.encode("utf-8")
            ).hexdigest(),
            "request_payload_bytes": len(serialized.encode("utf-8")),
            "proposal": None,
            "proposal_sha256": None,
            "provider_provenance": {},
            "proposal_evidence_status": "NOT_RECEIVED",
        }
        self.call_evidence.append(evidence)
        if self.expected_payloads is not None:
            if self.call_count >= len(self.expected_payloads):
                self.integrity_error = "classifier produced an unplanned Category request"
                raise RuntimeError(self.integrity_error)
            actual_payload = _serialized_request(request)
            if actual_payload != self.expected_payloads[self.call_count]:
                self.integrity_error = "classifier request differs from the oracle-isolated preflight"
                raise RuntimeError(self.integrity_error)
        self.call_count += 1
        try:
            result = self.provider(request)
        except Exception as exc:
            evidence["proposal_evidence_status"] = "PROVIDER_RAISED"
            evidence["provider_error_type"] = type(exc).__name__
            raise
        self.last_proposal = result.proposal if isinstance(result, CategorySemanticHelperResult) else result
        self.last_provenance = (
            dict(result.provenance)
            if isinstance(result, CategorySemanticHelperResult)
            else {}
        )
        proposal = _proposal_evidence(self.last_proposal)
        evidence["proposal"] = proposal
        evidence["proposal_sha256"] = hashlib.sha256(
            _canonical_json(proposal).encode("utf-8")
        ).hexdigest()
        evidence["provider_provenance"] = dict(self.last_provenance)
        evidence["proposal_evidence_status"] = "PARSED_PROPOSAL_RETAINED"
        return result


class _RecordingMaiAgentTransport:
    """Observe transport attempts without changing the shared policy."""

    def __init__(self, transport):
        self.transport = transport
        self.observations: list[dict[str, Any]] = []

    def __call__(self, endpoint, *, headers, body, timeout_seconds):
        try:
            response = self.transport(
                endpoint,
                headers=headers,
                body=body,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:
            self.observations.append(
                {
                    "status_code": None,
                    "transport_error_type": type(exc).__name__,
                    "retry_authorized": True,
                    "retry_reason": (
                        "TIMEOUT" if isinstance(exc, TimeoutError) else "CONNECTION"
                    ),
                    "request_body_sha256": hashlib.sha256(body).hexdigest(),
                    "request_body_bytes": len(body),
                }
            )
            raise
        if isinstance(response, MaiAgentHttpResponse):
            if response.status_code == 200:
                try:
                    parse_maiagent_response(response.body)
                except MaiAgentResponseError:
                    response_parse_status = "UNPARSEABLE_RESPONSE"
                    retry_authorized = True
                    retry_reason = "UNPARSEABLE_RESPONSE"
                else:
                    response_parse_status = "PARSEABLE_RESPONSE"
                    retry_authorized = False
                    retry_reason = None
            elif response.status_code in MAIAGENT_TRANSIENT_HTTP_STATUSES:
                response_parse_status = "NOT_APPLICABLE"
                retry_authorized = True
                retry_reason = f"HTTP_{response.status_code}"
            elif response.status_code in MAIAGENT_CONFIGURATION_HTTP_STATUSES:
                response_parse_status = "NOT_APPLICABLE"
                retry_authorized = False
                retry_reason = f"HTTP_{response.status_code}"
            else:
                response_parse_status = "NOT_APPLICABLE"
                retry_authorized = False
                retry_reason = f"HTTP_{response.status_code}"
            self.observations.append(
                {
                    "status_code": response.status_code,
                    "response_parse_status": response_parse_status,
                    "retry_authorized": retry_authorized,
                    "retry_reason": retry_reason,
                    "request_body_sha256": hashlib.sha256(body).hexdigest(),
                    "request_body_bytes": len(body),
                    "response_body_sha256": hashlib.sha256(response.body).hexdigest(),
                    "response_body_bytes": len(response.body),
                }
            )
        else:
            self.observations.append(
                {
                    "status_code": None,
                    "transport_error_type": "InvalidTransportResponse",
                    "retry_authorized": True,
                    "retry_reason": "INVALID_TRANSPORT_RESPONSE",
                    "request_body_sha256": hashlib.sha256(body).hexdigest(),
                    "request_body_bytes": len(body),
                }
            )
        return response


def _transport_attempt_accounting(
    transport_attempts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Validate RC-6 transport attempts for one logical Category call.

    This is acceptance-only observation.  It does not select a response or
    invoke a second provider path; the shared transport policy already owns
    retry execution.
    """

    attempts = [dict(item) for item in transport_attempts]
    result = {
        "status": "FINDINGS",
        "attempt_count": len(attempts),
        "retry_count": max(0, len(attempts) - 1),
        "retry_reasons": [],
        "request_body_consistent": False,
        "final_response_parse_status": None,
        "unauthorized_retry": False,
        "failure": None,
    }
    if not attempts:
        result["failure"] = "NO_TRANSPORT_ATTEMPT"
        return result
    if len(attempts) > MAIAGENT_MAX_ATTEMPTS:
        result["failure"] = "TRANSPORT_ATTEMPT_LIMIT_EXCEEDED"
        result["unauthorized_retry"] = True
        return result
    request_hashes = [item.get("request_body_sha256") for item in attempts]
    result["request_body_consistent"] = bool(request_hashes) and all(
        isinstance(item, str) and item == request_hashes[0] for item in request_hashes
    )
    if not result["request_body_consistent"]:
        result["failure"] = "RETRY_REQUEST_CHANGED"
        result["unauthorized_retry"] = len(attempts) > 1
        return result
    for attempt in attempts[:-1]:
        if attempt.get("retry_authorized") is not True:
            result["failure"] = "UNAUTHORIZED_TRANSPORT_RETRY"
            result["unauthorized_retry"] = True
            return result
        reason = attempt.get("retry_reason")
        if not isinstance(reason, str) or not reason:
            result["failure"] = "RETRY_REASON_NOT_RETAINED"
            result["unauthorized_retry"] = True
            return result
        result["retry_reasons"].append(reason)
    final = attempts[-1]
    result["final_response_parse_status"] = final.get("response_parse_status")
    if (
        final.get("status_code") != 200
        or final.get("response_parse_status") != "PARSEABLE_RESPONSE"
    ):
        result["failure"] = "FINAL_RESPONSE_NOT_PARSEABLE_HTTP_200"
        return result
    result["status"] = "PASS"
    return result


@dataclass(frozen=True, slots=True)
class _UpstreamFixture:
    """Sealed pre-Category fixture outcomes, with no Category answer fields."""

    evidence_state: str
    scope: str
    date_valid: bool
    event_identity_expectation: str
    event_count_after_dedup: int | str


def _upstream_fixture(fixture: dict[str, Any]) -> _UpstreamFixture:
    """Read only the sealed upstream outcomes needed for Category setup."""

    expected = fixture["expected"]
    return _UpstreamFixture(
        evidence_state=expected["evidence_state"],
        scope=expected["scope"],
        date_valid=expected["date_valid"],
        event_identity_expectation=expected["event_identity_expectation"],
        # An integer post-dedup count marks Event Identity completion. It is
        # upstream lifecycle output, not a Category result.
        event_count_after_dedup=expected["event_count_after_dedup"],
    )


def _reaches_category(upstream: _UpstreamFixture) -> bool:
    return (
        upstream.evidence_state == EvidenceState.READY.value
        and upstream.scope == ScopeState.IN_SCOPE.value
        and upstream.date_valid is True
        and type(upstream.event_count_after_dedup) is int
        and upstream.event_count_after_dedup > 0
    )


def _records(candidates: list[dict[str, Any]]) -> tuple[EventIdentityRecord, ...]:
    original_ids = sorted(str(candidate["candidate_id"]) for candidate in candidates)
    opaque_ids = {candidate_id: f"source-{index}" for index, candidate_id in enumerate(original_ids, 1)}
    records = []
    for candidate in candidates:
        original_id = str(candidate["candidate_id"])
        opaque_id = opaque_ids[original_id]
        event_facts = candidate.get("event_facts", {})
        claim = candidate.get("claim", {})
        facts = EventIdentityFacts(
            action=str(event_facts.get("action", "")),
            lifecycle_step=str(event_facts.get("lifecycle", "")),
            project=str(event_facts.get("project", "")),
            location=str(event_facts.get("city", "")),
            non_identity_claims=(
                {str(claim["field"]): str(claim["value"])}
                if claim.get("field") is not None
                else {}
            ),
        )
        source_content = str(candidate["source_content"])
        if facts.location:
            if facts.location not in source_content:
                source_content = f"{source_content} {facts.location}"
            start = source_content.index(facts.location)
            facts = EventIdentityFacts(
                action=facts.action,
                lifecycle_step=facts.lifecycle_step,
                project=facts.project,
                location=facts.location,
                non_identity_claims=facts.non_identity_claims,
                metadata_support=(
                    IdentityMetadataSupport("location", start, start + len(facts.location)),
                ),
            )
        canonical_input = {key: value for key, value in candidate.items() if key in {
            "title", "url", "publisher", "published_at", "discovery_intent", "search_snippet", "source_type"
        }}
        canonical_input["candidate_id"] = opaque_id
        records.append(
            EventIdentityRecord(
                CanonicalCandidate.from_mapping(canonical_input),
                EvidenceResult(
                    candidate_id=opaque_id,
                    state=EvidenceState.READY,
                    canonical_source_url=str(candidate.get("url", "")),
                    source_type="synthetic_golden_source",
                    substantive_content=source_content,
                    identity_facts=facts,
                ),
                ScopeResult(candidate_id=opaque_id, state=ScopeState.IN_SCOPE),
                TemporalResult(candidate_id=opaque_id, date_valid=True),
            )
        )
    return tuple(records)


def _groups(upstream: _UpstreamFixture, records: tuple[EventIdentityRecord, ...]) -> tuple[EventGroup, ...]:
    # Event Identity's locked upstream expectation only constructs the groups.
    if upstream.event_identity_expectation == "DIFFERENT_EVENTS":
        partitions = tuple((record,) for record in records)
    else:
        partitions = (records,)
    output = []
    for index, partition in enumerate(partitions, 1):
        ids = tuple(sorted(record.candidate.candidate_id for record in partition))
        values_by_key: dict[str, list[tuple[str, str]]] = {}
        for record in partition:
            facts = record.evidence.identity_facts
            if facts:
                for key, value in facts.non_identity_claims.items():
                    values_by_key.setdefault(key, []).append((record.candidate.candidate_id, value))
        unresolved = tuple(
            UnresolvedClaim(key, tuple(sorted(values)))
            for key, values in sorted(values_by_key.items())
            if len({value for _, value in values}) > 1
        )
        output.append(
            EventGroup(
                event_id=f"evaluation-event-{index}",
                member_candidate_ids=ids,
                canonical_candidate_id=ids[0],
                identity_basis=(),
                unresolved_claims=unresolved,
            )
        )
    return tuple(output)


ACCEPTANCE_VERSION = "category-v7-relationship-completeness-seal-v1"
ACCEPTANCE_EVIDENCE_VERSION = "category-acceptance-evidence-v3"
EVALUATION_HARNESS_VERSION = "category-semantic-evaluation-v7"
DEPLOYMENT_SNAPSHOT_CONTRACT_VERSION = "category-deployment-snapshot-v1"
TOTAL_GOLDEN_FIXTURES = 85
CATEGORY_REACHED_FIXTURES = 52
FINAL_SEAL_ROUNDS = 3
GROUPS_PER_ROUND = 53
TOTAL_PLANNED_LIVE_CALLS = FINAL_SEAL_ROUNDS * GROUPS_PER_ROUND
LIVE_CALL_BUDGET = GROUPS_PER_ROUND
PROXY_ENV_VARS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)
_ORACLE_ONLY_KEYS = frozenset(
    {
        "expected",
        "expected_category",
        "expected_state",
        "expected_subtype",
        "expected_resolution_reason",
        "expected_result",
        "expected_outcome",
        "expected_pass",
        "expected_fail",
        "pass_fail_expectation",
        "passed",
        "failed",
        "case_id",
        "case_class",
        "fixture_filename",
        "category_fixture_context",
        "matches_golden",
        "category_state",
        "primary_category_id",
        "primary_category",
        "subtype",
        "classification_reason",
        "category_resolution_reason",
        "reportability",
        "e&m_taxonomy",
    }
)


def _serialized_request(request: CategorySemanticRequest) -> str:
    return json.dumps(request.as_payload(), ensure_ascii=False, separators=(",", ":"))


def _group_specs_for_fixture(
    fixture: dict[str, Any],
    *,
    filename: str = "",
) -> list[dict[str, Any]]:
    """Build Category inputs only from upstream outcomes and source candidates."""

    upstream = _upstream_fixture(fixture)
    if not _reaches_category(upstream):
        return []
    records = _records(fixture["candidates"])
    groups = _groups(upstream, records)
    if len(groups) != upstream.event_count_after_dedup:
        raise ValueError("Event Identity fixture count does not match prepared groups")

    original_ids = sorted(str(candidate["candidate_id"]) for candidate in fixture["candidates"])
    original_by_opaque = {
        f"source-{index}": candidate_id
        for index, candidate_id in enumerate(original_ids, 1)
    }
    specs: list[dict[str, Any]] = []
    for group_index, group in enumerate(groups, 1):
        group_records = tuple(
            record
            for record in records
            if record.candidate.candidate_id in group.member_candidate_ids
        )
        request = _request_for(group, group_records)
        specs.append(
            {
                "case_id": fixture["case_id"],
                "filename": filename,
                "fixture": fixture,
                "upstream": upstream,
                "records": group_records,
                "group": group,
                "group_index": group_index,
                "group_count": len(groups),
                "member_candidate_ids": list(group.member_candidate_ids),
                "fixture_candidate_ids": [
                    original_by_opaque[candidate_id]
                    for candidate_id in group.member_candidate_ids
                ],
                "request": request,
                "request_payload": _serialized_request(request),
            }
        )
    return specs


def _expected_for_group(fixture: dict[str, Any], group_count: int) -> dict[str, str]:
    """Map fixture oracle to a group only when Golden makes it explicit."""

    if group_count > 1:
        notes = fixture.get("contract_notes", ())
        explicit_independent_mapping = any(
            note.strip()
            == "The expected category and taxonomy apply independently to each resulting event."
            for note in notes
            if isinstance(note, str)
        )
        if not explicit_independent_mapping:
            raise ValueError(
                f"{fixture.get('case_id', 'unknown fixture')} has multiple Event Groups "
                "without an explicit group-level oracle mapping"
            )

    expected = fixture["expected"]
    state = expected.get("category_state")
    if state == CategoryState.CATEGORY_ASSIGNED.value:
        category_id = expected.get("primary_category_id")
        if not isinstance(category_id, str) or not category_id:
            raise ValueError("assigned Golden oracle has no primary_category_id")
        return {"category_state": state, "primary_category_id": category_id}
    if state == CategoryState.CATEGORY_UNRESOLVED.value:
        reason = expected.get("category_resolution_reason")
        if not isinstance(reason, str) or not reason or reason == "NONE":
            raise ValueError("unresolved Golden oracle has no resolution reason")
        return {"category_state": state, "category_resolution_reason": reason}
    raise ValueError("Category-reached fixture has no terminal Category oracle")


def _collect_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        found: set[str] = set(value)
        for child in value.values():
            found.update(_collect_keys(child))
        return found
    if isinstance(value, list):
        found_list: set[str] = set()
        for child in value:
            found_list.update(_collect_keys(child))
        return found_list
    return set()


def _oracle_leakage_check(specs: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    failures: list[str] = []
    for spec in specs:
        payload = spec["request"].as_payload()
        serialized = spec["request_payload"]
        if _collect_keys(payload) & _ORACLE_ONLY_KEYS:
            failures.append(f"{spec['case_id']}: oracle-only key found in request payload")
        if spec["case_id"] in serialized:
            failures.append(f"{spec['case_id']}: Golden fixture ID found in request payload")
        if spec["filename"] and spec["filename"] in serialized:
            failures.append(f"{spec['case_id']}: Golden filename found in request payload")
    return not failures, failures


def _load_population() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = json.loads((ROOT / "golden" / "manifest.json").read_text(encoding="utf-8"))
    fixtures = [
        {
            "filename": entry["file"],
            "fixture": json.loads(
                (ROOT / "golden" / entry["file"]).read_text(encoding="utf-8")
            ),
        }
        for entry in manifest["cases"]
    ]
    return manifest, fixtures


def _phase_a_reconcile(
    fixtures: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], dict[str, str]], dict[str, int]]:
    specs: list[dict[str, Any]] = []
    total_reached_fixtures = 0
    expected_fixture_states = {
        CategoryState.CATEGORY_ASSIGNED.value: 0,
        CategoryState.CATEGORY_UNRESOLVED.value: 0,
        "NOT_EVALUATED": 0,
    }
    for item in fixtures:
        fixture = item["fixture"]
        state = fixture["expected"]["category_state"]
        expected_fixture_states[state] = expected_fixture_states.get(state, 0) + 1
        fixture_specs = _group_specs_for_fixture(fixture, filename=item["filename"])
        if fixture_specs:
            total_reached_fixtures += 1
            specs.extend(fixture_specs)

    oracle_by_group: dict[tuple[str, str], dict[str, str]] = {}
    mapping_rows: list[dict[str, Any]] = []
    for spec in specs:
        expected = _expected_for_group(spec["fixture"], spec["group_count"])
        key = (spec["case_id"], spec["group"].event_id)
        if key in oracle_by_group:
            raise ValueError(f"duplicate Event Group oracle key: {key[0]}/{key[1]}")
        oracle_by_group[key] = expected
        mapping_rows.append(
            {
                "fixture_id": spec["case_id"],
                "event_group_id": spec["group"].event_id,
                "member_candidate_ids": spec["member_candidate_ids"],
                "fixture_candidate_ids": spec["fixture_candidate_ids"],
                "expected": expected,
            }
        )

    counts = {
        "total_fixtures": len(fixtures),
        "category_reached_fixtures": total_reached_fixtures,
        "fixture_assigned": expected_fixture_states[CategoryState.CATEGORY_ASSIGNED.value],
        "fixture_unresolved": expected_fixture_states[CategoryState.CATEGORY_UNRESOLVED.value],
        "fixture_not_evaluated": expected_fixture_states["NOT_EVALUATED"],
        "prepared_event_groups": len(specs),
        "group_level_assigned": sum(
            row["expected"]["category_state"] == CategoryState.CATEGORY_ASSIGNED.value
            for row in mapping_rows
        ),
        "group_level_unresolved": sum(
            row["expected"]["category_state"] == CategoryState.CATEGORY_UNRESOLVED.value
            for row in mapping_rows
        ),
    }
    return specs, oracle_by_group, {**counts, "mapping_rows": mapping_rows}


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _proposal_evidence(value: object) -> dict[str, Any]:
    """Return a JSON-safe copy of the untrusted proposal for audit only."""

    if isinstance(value, CategorySemanticResponse):
        return {
            "actions": [
                {
                    "action_id": action.action_id,
                    "action_kind": action.action_kind,
                    "subject_kind": action.subject_kind,
                    "lifecycle_relation": action.lifecycle_relation,
                    "adoption_status": action.adoption_status,
                    "citations": [
                        {
                            "source_ref": citation.source_ref,
                            "sentence_ids": list(citation.sentence_ids),
                        }
                        for citation in action.citations
                    ],
                }
                for action in value.actions
            ],
            "principal_action_id": value.principal_action_id,
            "subtype": value.subtype,
            "examined_citations": [
                {
                    "source_ref": citation.source_ref,
                    "sentence_ids": list(citation.sentence_ids),
                }
                for citation in value.examined_citations
            ],
            "relationships": [
                {
                    "relationship_type": relationship.relationship_type,
                    "member_action_ids": list(relationship.member_action_ids),
                    "principal_action_id": relationship.principal_action_id,
                    "dependent_action_id": relationship.dependent_action_id,
                    "dependence_kind": relationship.dependence_kind,
                    "citations": [
                        {
                            "source_ref": citation.source_ref,
                            "sentence_ids": list(citation.sentence_ids),
                        }
                        for citation in relationship.citations
                    ],
                }
                for relationship in value.relationships
            ],
        }
    if isinstance(value, Mapping):
        try:
            return json.loads(_canonical_json(value))
        except (TypeError, ValueError) as exc:
            raise ValueError("acceptance proposal evidence is not JSON-serializable") from exc
    raise ValueError("acceptance proposal evidence has an unsupported shape")


def _guidance_digest(guidance: tuple[str, ...] | list[str]) -> str:
    """Digest the exact ordered guidance body without normalizing its text."""

    return hashlib.sha256(_canonical_json(list(guidance)).encode("utf-8")).hexdigest()


def _configuration_fingerprint_for(
    specs: list[dict[str, Any]],
    oracle_mapping: Mapping[tuple[str, str], Mapping[str, str]],
    *,
    guidance: tuple[str, ...] | list[str],
    prompt_identity: str,
    response_contract_identity: str,
    schema_identity: str,
    authoritative_response_schema: Mapping[str, Any],
    provider_schema_projection: Mapping[str, Any],
    provider_identifier: str,
    helper_version: str,
) -> str:
    """Hash only repository-controlled inputs that can alter acceptance."""

    ordered_oracle = [
        {
            "fixture_id": fixture_id,
            "event_group_id": event_group_id,
            "expected": dict(oracle_mapping[(fixture_id, event_group_id)]),
        }
        for fixture_id, event_group_id in sorted(oracle_mapping)
    ]
    material = {
        "acceptance_version": ACCEPTANCE_VERSION,
        "acceptance_evidence_version": ACCEPTANCE_EVIDENCE_VERSION,
        "evaluation_harness_version": EVALUATION_HARNESS_VERSION,
        "category_prompt_version": prompt_identity,
        "category_guidance": list(guidance),
        "authoritative_response_schema": authoritative_response_schema,
        "provider_schema_projection": provider_schema_projection,
        "provider_message_version": response_contract_identity,
        "category_schema_version": schema_identity,
        "provider_identifier": provider_identifier,
        "helper_version": helper_version,
        "prepared_request_payloads": [
            json.loads(spec["request_payload"])
            for spec in specs
        ],
        "golden_oracle_mapping": ordered_oracle,
        "final_seal_contract": {
            "total_golden_fixtures": TOTAL_GOLDEN_FIXTURES,
            "category_reached_fixtures": CATEGORY_REACHED_FIXTURES,
            "rounds": FINAL_SEAL_ROUNDS,
            "groups_per_round": GROUPS_PER_ROUND,
            "total_planned_live_calls": TOTAL_PLANNED_LIVE_CALLS,
        },
    }
    return hashlib.sha256(_canonical_json(material).encode("utf-8")).hexdigest()


def _configuration_fingerprint(
    specs: list[dict[str, Any]],
    oracle_mapping: Mapping[tuple[str, str], Mapping[str, str]],
) -> str:
    """Fingerprint the configuration currently selected by this harness."""

    return _configuration_fingerprint_for(
        specs,
        oracle_mapping,
        guidance=_CATEGORY_GUIDANCE,
        prompt_identity=CATEGORY_SEMANTIC_PROMPT_VERSION,
        response_contract_identity=MAIAGENT_CATEGORY_MESSAGE_VERSION,
        schema_identity=CATEGORY_SEMANTIC_SCHEMA_VERSION,
        authoritative_response_schema=_CATEGORY_RESPONSE_SCHEMA,
        provider_schema_projection=_MAIAGENT_CATEGORY_RESPONSE_SCHEMA,
        provider_identifier=MAIAGENT_CATEGORY_PROVIDER_IDENTIFIER,
        helper_version=MAIAGENT_CATEGORY_SEMANTIC_HELPER_VERSION,
    )


def _target_configuration_identity(
    specs: list[dict[str, Any]],
    oracle_mapping: Mapping[tuple[str, str], Mapping[str, str]],
) -> CategoryAcceptanceConfigurationIdentity:
    """Resolve the configuration the acceptance target is about to exercise."""

    return CategoryAcceptanceConfigurationIdentity(
        guidance_digest=_guidance_digest(_CATEGORY_GUIDANCE),
        prompt_identity=CATEGORY_SEMANTIC_PROMPT_VERSION,
        response_contract_identity=MAIAGENT_CATEGORY_MESSAGE_VERSION,
        schema_identity=CATEGORY_SEMANTIC_SCHEMA_VERSION,
        configuration_fingerprint=_configuration_fingerprint(specs, oracle_mapping),
    )


def _resolve_checked_in_production_configuration(
    *,
    category_config: MaiAgentCategorySemanticProviderConfig | None = None,
) -> tuple[
    CategoryAcceptanceConfigurationIdentity,
    list[dict[str, Any]],
    dict[tuple[str, str], dict[str, str]],
    dict[str, Any],
]:
    """Resolve production identity through the production Category factory.

    This function intentionally reads the live checked-in Classifier owner and
    provider module, not the acceptance module's imported or overridden
    aliases.  The factory is constructed with no transport invocation.
    """

    production_classifier = build_maiagent_category_classifier(
        config=category_config,
        environ={} if category_config is None else None,
    )
    if not isinstance(production_classifier, Classifier):
        raise TypeError("production Category factory did not return Classifier")

    _, fixtures = _load_population()
    specs, oracle, counts = _phase_a_reconcile(fixtures)
    identity = CategoryAcceptanceConfigurationIdentity(
        guidance_digest=_guidance_digest(classifier_module._CATEGORY_GUIDANCE),
        prompt_identity=category_provider_module.CATEGORY_SEMANTIC_PROMPT_VERSION,
        response_contract_identity=category_provider_module.MAIAGENT_CATEGORY_MESSAGE_VERSION,
        schema_identity=category_provider_module.CATEGORY_SEMANTIC_SCHEMA_VERSION,
        configuration_fingerprint=_configuration_fingerprint_for(
            specs,
            oracle,
            guidance=classifier_module._CATEGORY_GUIDANCE,
            prompt_identity=category_provider_module.CATEGORY_SEMANTIC_PROMPT_VERSION,
            response_contract_identity=category_provider_module.MAIAGENT_CATEGORY_MESSAGE_VERSION,
            schema_identity=category_provider_module.CATEGORY_SEMANTIC_SCHEMA_VERSION,
            authoritative_response_schema=category_provider_module._CATEGORY_RESPONSE_SCHEMA,
            provider_schema_projection=category_provider_module._MAIAGENT_CATEGORY_RESPONSE_SCHEMA,
            provider_identifier=category_provider_module.MAIAGENT_CATEGORY_PROVIDER_IDENTIFIER,
            helper_version=category_provider_module.MAIAGENT_CATEGORY_SEMANTIC_HELPER_VERSION,
        ),
    )
    return identity, specs, oracle, counts


def enforce_category_configuration_binding(
    *,
    production: CategoryAcceptanceConfigurationIdentity,
    target: CategoryAcceptanceConfigurationIdentity,
    mode: str,
) -> dict[str, Any]:
    """Fail closed for a formal seal; explicitly label candidate experiments."""

    if mode not in {FORMAL_CURRENT_CONFIGURATION_SEAL, CANDIDATE_EXPERIMENT}:
        raise ValueError(f"unsupported Category acceptance mode: {mode}")

    fields = (
        "guidance_digest",
        "prompt_identity",
        "response_contract_identity",
        "schema_identity",
        "configuration_fingerprint",
    )
    mismatches = {
        field: {
            "production": getattr(production, field),
            "target": getattr(target, field),
        }
        for field in fields
        if getattr(production, field) != getattr(target, field)
    }
    if mode == CANDIDATE_EXPERIMENT:
        return {
            "mode": mode,
            "status": "CANDIDATE_EXPERIMENT_ALLOWED",
            "mismatches": mismatches,
        }
    if mismatches:
        raise CategoryConfigurationBindingError(mismatches)
    return {"mode": mode, "status": "PASS", "mismatches": {}}


_ZERO_ERROR_ROUND_EXPECTATIONS = {
    "LIVE_CALL_COUNT": GROUPS_PER_ROUND,
    "HTTP_200_COUNT": GROUPS_PER_ROUND,
    "LOGICAL_CALL_COUNT": GROUPS_PER_ROUND,
    "FINAL_HTTP_200_COUNT": GROUPS_PER_ROUND,
    "TRANSPORT_ACCOUNTING_STATUS": "PASS",
    "UNAUTHORIZED_TRANSPORT_RETRY_COUNT": 0,
    "CLASSIFIER_ACCEPTED_COUNT": GROUPS_PER_ROUND,
    "CLASSIFIER_INVALID_COUNT": 0,
    "CATEGORY_STATE_MISMATCH_COUNT": 0,
    "PRIMARY_CATEGORY_MISMATCH_COUNT": 0,
    "RESOLUTION_REASON_MISMATCH_COUNT": 0,
    "EXACT_CATEGORY_MATCH_COUNT": GROUPS_PER_ROUND,
}
_HISTORICAL_ZERO_ERROR_ROUND_EXPECTATIONS = {
    "LIVE_CALL_COUNT": GROUPS_PER_ROUND,
    "HTTP_200_COUNT": GROUPS_PER_ROUND,
    "CLASSIFIER_ACCEPTED_COUNT": GROUPS_PER_ROUND,
    "CLASSIFIER_INVALID_COUNT": 0,
    "CATEGORY_STATE_MISMATCH_COUNT": 0,
    "PRIMARY_CATEGORY_MISMATCH_COUNT": 0,
    "RESOLUTION_REASON_MISMATCH_COUNT": 0,
    "EXACT_CATEGORY_MATCH_COUNT": GROUPS_PER_ROUND,
}
_DEPLOYMENT_SNAPSHOT_REQUIRED_FIELDS = frozenset(
    {
        "snapshot_contract_version",
        "platform",
        "role_instruction",
        "structured_output",
        "unavailable_platform_facts",
    }
)
_DEPLOYMENT_SNAPSHOT_OBSERVABLE_FIELDS = frozenset(
    {
        "answer_mode",
        "knowledge_base",
        "skills_tools",
        "generation_settings",
        "context_memory_settings",
    }
)
_DEPLOYMENT_SNAPSHOT_OPTIONAL_FIELDS = frozenset(
    {"optional_platform_metadata", "audit_metadata"}
)
_DEPLOYMENT_PLATFORM_FIELDS = frozenset(
    {"provider", "chatbot_instance_id", "model_identifier"}
)
_DEPLOYMENT_ROLE_FIELDS = frozenset({"content"})
_DEPLOYMENT_STRUCTURED_OUTPUT_FIELDS = frozenset({"schema"})
_DEPLOYMENT_KNOWLEDGE_BASE_FIELDS = frozenset({"state"})
_DEPLOYMENT_SKILLS_TOOLS_FIELDS = frozenset({"selected"})
_DEPLOYMENT_OPTIONAL_METADATA_FIELDS = frozenset(
    {"chatbot_configuration_revision", "schema_identity", "schema_version"}
)
_PLACEHOLDER_VALUES = frozenset({"", "unknown", "n/a", "unavailable"})


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(  # noqa: TRY004
            f"deployment snapshot {label} must be an object"
        )
    return value


def _check_fields(
    value: Mapping[str, Any],
    required: frozenset[str],
    optional: frozenset[str],
    label: str,
) -> None:
    fields = frozenset(value)
    missing = required - fields
    unexpected = fields - required - optional
    if missing:
        raise ValueError(f"deployment snapshot {label} missing required fields")
    if unexpected:
        raise ValueError(f"deployment snapshot {label} has unsupported fields")


def _observed_string(value: object, label: str) -> str:
    if not isinstance(value, str) or value.strip().lower() in _PLACEHOLDER_VALUES:
        raise ValueError(f"deployment snapshot {label} requires an observed string")
    return value


def _validate_deployment_snapshot(value: Mapping[str, Any]) -> dict[str, Any]:
    snapshot = _mapping(value, "root")
    _check_fields(
        snapshot,
        _DEPLOYMENT_SNAPSHOT_REQUIRED_FIELDS,
        _DEPLOYMENT_SNAPSHOT_OBSERVABLE_FIELDS | _DEPLOYMENT_SNAPSHOT_OPTIONAL_FIELDS,
        "root",
    )
    if snapshot["snapshot_contract_version"] != DEPLOYMENT_SNAPSHOT_CONTRACT_VERSION:
        raise ValueError("deployment snapshot contract version is unsupported")

    platform = _mapping(snapshot["platform"], "platform")
    _check_fields(platform, _DEPLOYMENT_PLATFORM_FIELDS, frozenset(), "platform")
    _provider = _observed_string(platform["provider"], "platform.provider")
    instance_id = _observed_string(
        platform["chatbot_instance_id"], "platform.chatbot_instance_id"
    )
    _model_identifier = _observed_string(
        platform["model_identifier"], "platform.model_identifier"
    )

    role_instruction = _mapping(snapshot["role_instruction"], "role_instruction")
    _check_fields(role_instruction, _DEPLOYMENT_ROLE_FIELDS, frozenset(), "role_instruction")
    role_content = role_instruction["content"]
    if (
        not isinstance(role_content, str)
        or role_content == ""
        or role_content.strip().lower() in _PLACEHOLDER_VALUES
    ):
        raise ValueError("deployment snapshot role_instruction.content is required")

    structured_output = _mapping(snapshot["structured_output"], "structured_output")
    _check_fields(
        structured_output,
        _DEPLOYMENT_STRUCTURED_OUTPUT_FIELDS,
        frozenset(),
        "structured_output",
    )
    _schema = _mapping(structured_output["schema"], "structured_output.schema")

    unavailable = snapshot["unavailable_platform_facts"]
    if not isinstance(unavailable, list) or any(
        not isinstance(item, str) or not item or item != item.strip()
        or item.lower() in _PLACEHOLDER_VALUES
        for item in unavailable
    ):
        raise ValueError(
            "deployment snapshot unavailable_platform_facts must be a string list"
        )
    if len(set(unavailable)) != len(unavailable):
        raise ValueError("deployment snapshot unavailable facts must be unique")

    observable_unavailable_facts = {
        "answer_mode": "answer_mode",
        "knowledge_base": "knowledge_base",
        "skills_tools": "skills_tools",
        "generation_settings": "generation_settings",
        "context_memory_settings": "context_memory_settings",
    }
    for field, fact in observable_unavailable_facts.items():
        if field not in snapshot and fact not in unavailable:
            raise ValueError(
                f"deployment snapshot {field} must be observed or explicitly unavailable"
            )

    if "answer_mode" in snapshot:
        _observed_string(snapshot["answer_mode"], "answer_mode")
    if "knowledge_base" in snapshot:
        knowledge_base = _mapping(snapshot["knowledge_base"], "knowledge_base")
        _check_fields(
            knowledge_base,
            _DEPLOYMENT_KNOWLEDGE_BASE_FIELDS,
            frozenset(),
            "knowledge_base",
        )
        _observed_string(knowledge_base["state"], "knowledge_base.state")
    if "skills_tools" in snapshot:
        skills_tools = _mapping(snapshot["skills_tools"], "skills_tools")
        _check_fields(
            skills_tools, _DEPLOYMENT_SKILLS_TOOLS_FIELDS, frozenset(), "skills_tools"
        )
        selected = skills_tools["selected"]
        if not isinstance(selected, list) or any(
            not isinstance(item, str) or not item or item != item.strip()
            for item in selected
        ):
            raise ValueError("deployment snapshot skills_tools.selected must be a string list")
        if len(set(selected)) != len(selected):
            raise ValueError("deployment snapshot skills_tools.selected must be unique")
    else:
        selected = None

    for field in ("generation_settings", "context_memory_settings"):
        if field in snapshot:
            _mapping(snapshot[field], field)

    optional_metadata = snapshot.get("optional_platform_metadata", {})
    optional_metadata = _mapping(optional_metadata, "optional_platform_metadata")
    _check_fields(
        optional_metadata,
        frozenset(),
        _DEPLOYMENT_OPTIONAL_METADATA_FIELDS,
        "optional_platform_metadata",
    )
    for key, item in optional_metadata.items():
        _observed_string(item, f"optional_platform_metadata.{key}")
    if optional_metadata.get("chatbot_configuration_revision") == instance_id:
        raise ValueError(
            "chatbot instance ID cannot masquerade as configuration revision"
        )

    audit_metadata = snapshot.get("audit_metadata", {})
    _mapping(audit_metadata, "audit_metadata")

    # json.loads() supplies JSON-compatible values, but direct unit callers may
    # not.  This also makes the canonical fingerprint failure explicit.
    try:
        canonical = json.loads(_canonical_json(dict(snapshot)))
    except (TypeError, ValueError) as exc:
        raise ValueError("deployment snapshot contains non-JSON values") from exc
    if selected is not None:
        canonical["skills_tools"]["selected"] = sorted(selected)
    canonical["unavailable_platform_facts"] = sorted(unavailable)
    return canonical


def _identity_fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _deployment_provenance_record(
    value: Mapping[str, Any] | None,
    *,
    runtime_helper_identity: str | None = None,
) -> dict[str, Any]:
    """Validate and bind a platform snapshot to the actual runtime Helper.

    A snapshot is never considered observed/frozen without the identity used
    by the provider configuration for the calls.  The raw identity is only
    compared in memory; artifacts retain fingerprints, not the identifier.
    """

    if value is None:
        return {
            "DEPLOYMENT_PROVENANCE_STATUS": "DEPLOYMENT_PROVENANCE_UNAVAILABLE",
            "DEPLOYMENT_BINDING_STATUS": "DEPLOYMENT_SNAPSHOT_UNAVAILABLE",
        }
    snapshot = _validate_deployment_snapshot(value)
    snapshot_identity = snapshot["platform"]["chatbot_instance_id"]
    if runtime_helper_identity is None:
        return {
            "DEPLOYMENT_PROVENANCE_STATUS": "DEPLOYMENT_PROVENANCE_UNAVAILABLE",
            "DEPLOYMENT_SNAPSHOT_CONTRACT_VERSION": snapshot["snapshot_contract_version"],
            "DEPLOYMENT_BINDING_STATUS": "RUNTIME_HELPER_IDENTITY_UNAVAILABLE",
        }
    if (
        not isinstance(runtime_helper_identity, str)
        or not runtime_helper_identity
        or runtime_helper_identity != runtime_helper_identity.strip()
    ):
        raise ValueError("runtime Helper identity is not canonical")
    if snapshot_identity != runtime_helper_identity:
        raise ValueError("deployment snapshot Helper identity does not match runtime Helper identity")
    fingerprint_material = {
        key: item for key, item in snapshot.items() if key != "audit_metadata"
    }
    return {
        "DEPLOYMENT_PROVENANCE_STATUS": "OBSERVED_AND_FROZEN",
        "DEPLOYMENT_SNAPSHOT_CONTRACT_VERSION": snapshot["snapshot_contract_version"],
        "DEPLOYMENT_FINGERPRINT": hashlib.sha256(
            _canonical_json(fingerprint_material).encode("utf-8")
        ).hexdigest(),
        "DEPLOYMENT_BINDING_STATUS": "SAME_RUNTIME_HELPER_PROVEN",
        "SAME_RUNTIME_HELPER_BINDING": "PROVEN",
        "RUNTIME_HELPER_IDENTITY_FINGERPRINT": _identity_fingerprint(
            runtime_helper_identity
        ),
        "DEPLOYMENT_SNAPSHOT_IDENTITY_FINGERPRINT": _identity_fingerprint(
            snapshot_identity
        ),
    }


def _report_has_complete_live_evidence(report: Mapping[str, Any]) -> bool:
    results = report.get("RESULTS")
    return (
        isinstance(results, list)
        and len(results) == GROUPS_PER_ROUND
        and all(
            isinstance(row, Mapping)
            and isinstance(row.get("acceptance_evidence"), Mapping)
            and _live_evidence_complete(row["acceptance_evidence"])
            for row in results
        )
    )


def _assess_final_seal_batch(
    round_reports: Sequence[Mapping[str, Any]],
    *,
    require_current_evidence: bool,
) -> dict[str, Any]:
    """Assess exactly the three predeclared rounds without replacing failures."""

    result: dict[str, Any] = {
        "CATEGORY_V4_FINAL_SEAL": "BLOCKED",
        "ACCEPTANCE_VERSION": ACCEPTANCE_VERSION,
        "ACCEPTANCE_EVIDENCE_VERSION": (
            ACCEPTANCE_EVIDENCE_VERSION
            if require_current_evidence
            else "NOT_RECORDED_HISTORICAL"
        ),
        "DEPLOYMENT_SNAPSHOT_CONTRACT_VERSION": DEPLOYMENT_SNAPSHOT_CONTRACT_VERSION,
        "PLANNED_ROUNDS": FINAL_SEAL_ROUNDS,
        "GROUPS_PER_ROUND": GROUPS_PER_ROUND,
        "TOTAL_PLANNED_LIVE_CALLS": TOTAL_PLANNED_LIVE_CALLS,
        "FAILED_ROUNDS": [],
    }
    if len(round_reports) != FINAL_SEAL_ROUNDS:
        result["BLOCKER"] = "EXACTLY_THREE_PREDECLARED_ROUND_REPORTS_REQUIRED"
        return result
    indices = [report.get("ROUND_INDEX") for report in round_reports]
    if set(indices) != set(range(1, FINAL_SEAL_ROUNDS + 1)):
        result["BLOCKER"] = "ROUND_INDICES_MUST_BE_EXACTLY_1_2_3"
        return result
    versions = {report.get("ACCEPTANCE_VERSION") for report in round_reports}
    fingerprints = {report.get("CONFIGURATION_FINGERPRINT") for report in round_reports}
    if versions != {ACCEPTANCE_VERSION} or len(fingerprints) != 1 or None in fingerprints:
        result["BLOCKER"] = "ROUND_CONFIGURATION_IS_NOT_IDENTICAL_AND_FROZEN"
        return result
    if require_current_evidence:
        evidence_versions = {
            report.get("ACCEPTANCE_EVIDENCE_VERSION") for report in round_reports
        }
        binding_statuses = {
            report.get("SAME_RUNTIME_HELPER_BINDING") for report in round_reports
        }
        chain_statuses = {
            report.get("ACCEPTANCE_EVIDENCE_CHAIN_STATUS") for report in round_reports
        }
        complete_counts = {
            report.get("ACCEPTANCE_EVIDENCE_COMPLETE_COUNT")
            for report in round_reports
        }
        if evidence_versions != {ACCEPTANCE_EVIDENCE_VERSION}:
            result["BLOCKER"] = "CURRENT_ACCEPTANCE_EVIDENCE_VERSION_REQUIRED"
            return result
        if binding_statuses != {"PROVEN"}:
            result["BLOCKER"] = "CURRENT_ACCEPTANCE_RUNTIME_BINDING_REQUIRED"
            return result
        if chain_statuses != {"COMPLETE"} or complete_counts != {GROUPS_PER_ROUND}:
            result["BLOCKER"] = "CURRENT_ACCEPTANCE_EVIDENCE_CHAIN_REQUIRED"
            return result
        if not all(_report_has_complete_live_evidence(report) for report in round_reports):
            result["BLOCKER"] = "CURRENT_ACCEPTANCE_EVIDENCE_ROWS_REQUIRED"
            return result
    deployment_statuses = {
        report.get("DEPLOYMENT_PROVENANCE_STATUS") for report in round_reports
    }
    deployment_snapshot_versions = {
        report.get("DEPLOYMENT_SNAPSHOT_CONTRACT_VERSION") for report in round_reports
    }
    deployment_fingerprints = {
        report.get("DEPLOYMENT_FINGERPRINT") for report in round_reports
    }
    if (
        deployment_statuses != {"OBSERVED_AND_FROZEN"}
        or deployment_snapshot_versions != {DEPLOYMENT_SNAPSHOT_CONTRACT_VERSION}
        or len(deployment_fingerprints) != 1
        or None in deployment_fingerprints
    ):
        result["BLOCKER"] = "DEPLOYMENT_PROVENANCE_IS_NOT_OBSERVED_AND_FROZEN"
        return result

    failed_rounds: list[dict[str, Any]] = []
    for report in sorted(round_reports, key=lambda item: item["ROUND_INDEX"]):
        expectations = (
            _ZERO_ERROR_ROUND_EXPECTATIONS
            if require_current_evidence
            else _HISTORICAL_ZERO_ERROR_ROUND_EXPECTATIONS
        )
        failures = {
            key: {"expected": expected, "actual": report.get(key)}
            for key, expected in expectations.items()
            if report.get(key) != expected
        }
        if report.get("CATEGORY_53_GROUP_LIVE_ACCEPTANCE") != "PASS":
            failures["CATEGORY_53_GROUP_LIVE_ACCEPTANCE"] = {
                "expected": "PASS",
                "actual": report.get("CATEGORY_53_GROUP_LIVE_ACCEPTANCE"),
            }
        if failures:
            failed_rounds.append({"round_index": report["ROUND_INDEX"], "failures": failures})
    result["CONFIGURATION_FINGERPRINT"] = next(iter(fingerprints))
    result["DEPLOYMENT_FINGERPRINT"] = next(iter(deployment_fingerprints))
    result["FAILED_ROUNDS"] = failed_rounds
    result["CATEGORY_V4_FINAL_SEAL"] = "PASS" if not failed_rounds else "FINDINGS"
    return result


def assess_final_seal_batch(round_reports: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Assess current live rounds; unbound reports cannot be current PASS evidence."""

    return _assess_final_seal_batch(round_reports, require_current_evidence=True)


def assess_historical_final_seal_batch(
    round_reports: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Assess the frozen historical seal without treating it as current acceptance."""

    result = _assess_final_seal_batch(round_reports, require_current_evidence=False)
    result["ACCEPTANCE_SCOPE"] = "HISTORICAL_ONLY"
    result["CURRENT_LIVE_SCOREABILITY"] = "NO"
    return result


def _classify_for_evaluation(classifier: Classifier, spec: dict[str, Any]) -> CategoryResult:
    """Run the owner; report an RC-16 proposal violation as an invalid response."""

    try:
        return classifier.classify(spec["group"], spec["records"])
    except CategoryProposalViolation as exc:
        return CategoryResult(
            category_state=CategoryState.CATEGORY_UNRESOLVED,
            event_id=spec["group"].event_id,
            classification_reason=CategoryState.CATEGORY_UNRESOLVED.value,
            category_resolution_reason=CategoryResolutionReason.SEMANTIC_HELPER_INVALID_RESPONSE,
            provenance={
                "decision_basis": "proposal_contract_violation",
                "validation_error": str(exc),
                "validation_predicate": exc.failure_class,
            },
        )


def _citation_details(
    actual,
    request: CategorySemanticRequest,
    proposal: object,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    source_text = {source.candidate_id: source.substantive_content for source in request.sources}
    refs = request.source_refs
    citation_entries: list[tuple[str | None, object]] = []
    if isinstance(proposal, Mapping):
        for action in proposal.get("actions", ()):
            if isinstance(action, Mapping):
                action_id = action.get("action_id")
                for citation in action.get("citations", ()):
                    citation_entries.append((action_id if isinstance(action_id, str) else None, citation))
        for citation in proposal.get("examined_citations", ()):
            citation_entries.append((None, citation))
        for relationship_index, relationship in enumerate(proposal.get("relationships", ())):
            if isinstance(relationship, Mapping):
                relationship_label = f"relationship:{relationship_index}:{relationship.get('relationship_type')}"
                for citation in relationship.get("citations", ()):
                    citation_entries.append((relationship_label, citation))
    canonical_spans: list[dict[str, Any]] = []
    validated_actions = actual.provenance.get("validated_action_spans", {})
    if isinstance(validated_actions, Mapping):
        for spans in validated_actions.values():
            if isinstance(spans, list):
                canonical_spans.extend(span for span in spans if isinstance(span, Mapping))
    examined_spans = actual.provenance.get("validated_examined_spans", ())
    if isinstance(examined_spans, list):
        canonical_spans.extend(span for span in examined_spans if isinstance(span, Mapping))
    validated_relationships = actual.provenance.get("validated_relationships", ())
    if isinstance(validated_relationships, list):
        for relationship in validated_relationships:
            if isinstance(relationship, Mapping):
                spans = relationship.get("validated_spans", ())
                if isinstance(spans, list):
                    canonical_spans.extend(span for span in spans if isinstance(span, Mapping))
    details: list[dict[str, Any]] = []
    for action_id, citation in citation_entries:
        if not isinstance(citation, Mapping):
            continue
        source_ref = citation.get("source_ref")
        sentence_ids = citation.get("sentence_ids")
        candidate_id = refs.get(source_ref) if isinstance(source_ref, str) else None
        source = source_text.get(candidate_id) if candidate_id is not None else None
        # RC-16: each cited sentence is one canonical span, in order.
        count = len(sentence_ids) if isinstance(sentence_ids, list) else 0
        spans = [span for span in canonical_spans if span.get("candidate_id") == candidate_id][:count]
        for span in spans:
            canonical_spans.remove(span)
        resolved_source = source if bool(spans) and isinstance(source, str) else None
        resolved = resolved_source is not None
        start = spans[0]["start"] if resolved else None
        end = spans[-1]["end"] if resolved else None
        details.append(
            {
                "candidate_id": candidate_id,
                "action_id": action_id,
                "source_ref": source_ref,
                "sentence_ids": sentence_ids,
                "resolved_start": start,
                "resolved_end": end,
                "resolved_substring": (
                    resolved_source[start:end]
                    if isinstance(resolved_source, str)
                    and isinstance(start, int)
                    and isinstance(end, int)
                    else None
                ),
            }
        )
    concerns: list[dict[str, Any]] = []
    for citation in details:
        text = citation["resolved_substring"]
        start, end = citation["resolved_start"], citation["resolved_end"]
        candidate_id = citation["candidate_id"]
        source = source_text.get(candidate_id) if isinstance(candidate_id, str) else None
        flags: list[str] = []
        if isinstance(text, str) and not any(character.isalnum() for character in text):
            flags.append("punctuation_or_whitespace_only")
        if isinstance(source, str) and isinstance(start, int) and isinstance(end, int):
            if (
                start > 0
                and start < len(source)
                and source[start - 1].isascii()
                and source[start - 1].isalnum()
                and source[start].isascii()
                and source[start].isalnum()
            ):
                flags.append("starts_inside_ascii_word")
            if (
                end > 0
                and end < len(source)
                and source[end - 1].isascii()
                and source[end - 1].isalnum()
                and source[end].isascii()
                and source[end].isalnum()
            ):
                flags.append("ends_inside_ascii_word")
        if flags:
            concerns.append({**citation, "diagnostic_flags": flags})
    return details, concerns


def _first_failure(actual, expected, transport_observation) -> str | None:
    if transport_observation is not None:
        status = transport_observation.get("status_code")
        if status is None or status != 200:
            return "TRANSPORT_FAILURE"
    provenance = actual.provenance
    if provenance.get("helper_error_type"):
        return "TRANSPORT_FAILURE"
    validation_error = str(provenance.get("validation_error", ""))
    if validation_error.startswith(("MaiAgent response", "MaiAgent content", "MaiAgent proposal")):
        return "MAIAGENT_ENVELOPE_INVALID"
    if actual.category_resolution_reason is not None and actual.category_resolution_reason.value == "SEMANTIC_HELPER_INVALID_RESPONSE":
        return "CLASSIFIER_INVALID_RESPONSE"
    if actual.category_state.value != expected["category_state"]:
        return "CATEGORY_STATE_MISMATCH"
    if expected["category_state"] == CategoryState.CATEGORY_ASSIGNED.value:
        actual_category = actual.primary_category_id.value if actual.primary_category_id else None
        if actual_category != expected["primary_category_id"]:
            return "PRIMARY_CATEGORY_MISMATCH"
    elif actual.category_resolution_reason is None or actual.category_resolution_reason.value != expected["category_resolution_reason"]:
        return "RESOLUTION_REASON_MISMATCH"
    return None


def _evaluate_spec(
    spec: dict[str, Any],
    *,
    classifier: Classifier,
    capture: _CaptureProvider,
    expected: dict[str, str],
    transport_observation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    capture.last_proposal = None
    actual = _classify_for_evaluation(classifier, spec)
    citations, citation_concerns = _citation_details(
        actual, spec["request"], capture.last_proposal
    )
    first_failure = _first_failure(actual, expected, transport_observation)
    actual_state = actual.category_state.value
    matches = first_failure not in {
        "TRANSPORT_FAILURE",
        "MAIAGENT_ENVELOPE_INVALID",
        "CLASSIFIER_INVALID_RESPONSE",
        "CATEGORY_STATE_MISMATCH",
        "PRIMARY_CATEGORY_MISMATCH",
        "RESOLUTION_REASON_MISMATCH",
    }
    expected_summary = dict(expected)
    row = {
        "fixture_id": spec["case_id"],
        "event_group_id": spec["group"].event_id,
        "member_candidate_ids": spec["member_candidate_ids"],
        "fixture_candidate_ids": spec["fixture_candidate_ids"],
        "expected": expected_summary,
        "actual": actual.as_mapping(),
        "proposal": capture.last_proposal,
        "earliest_failure_type": first_failure,
        "matches_golden": matches,
        "citations": citations,
        "semantic_citation_concerns": citation_concerns,
        "semantic_citation_review": "HUMAN_REVIEW_REQUIRED",
        "validation_error": actual.provenance.get("validation_error"),
        "http_status": transport_observation.get("status_code") if transport_observation else None,
    }
    row["outcome_class"] = _outcome_class(
        expected_state=expected["category_state"],
        actual_state=actual_state,
        matches_golden=matches,
    )
    return row


def _evaluate_fixture(
    fixture: dict[str, Any],
    *,
    classifier: Classifier,
    capture: _CaptureProvider,
) -> list[dict[str, Any]]:
    """Offline fixture seam; only its request contains input facts, never the oracle."""

    specs = _group_specs_for_fixture(fixture)
    rows: list[dict[str, Any]] = []
    for spec in specs:
        row = _evaluate_spec(
            spec,
            classifier=classifier,
            capture=capture,
            expected=_expected_for_group(fixture, spec["group_count"]),
        )
        rows.append(row)
    return rows


def _outcome_class(*, expected_state: str, actual_state: str, matches_golden: bool) -> str:
    assigned = CategoryState.CATEGORY_ASSIGNED.value
    unresolved = CategoryState.CATEGORY_UNRESOLVED.value
    if expected_state not in {assigned, unresolved} or actual_state not in {assigned, unresolved}:
        raise ValueError("Category evaluation rows require assigned or unresolved states")
    if matches_golden:
        return "CORRECT_ASSIGNED" if expected_state == assigned else "CORRECT_UNRESOLVED"
    if expected_state == assigned:
        return "WRONG_ASSIGNED_CATEGORY" if actual_state == assigned else "FALSE_UNRESOLVED"
    return "FALSE_ASSIGNED" if actual_state == assigned else "WRONG_UNRESOLVED_REASON"


def _proxy_blockers(environ: Mapping[str, str] | None = None) -> list[str]:
    values = environ if environ is not None else os.environ
    return [name for name in PROXY_ENV_VARS if name in values]


def _summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    failure_names = (
        "TRANSPORT_FAILURE",
        "MAIAGENT_ENVELOPE_INVALID",
        "CLASSIFIER_INVALID_RESPONSE",
        "CATEGORY_STATE_MISMATCH",
        "PRIMARY_CATEGORY_MISMATCH",
        "RESOLUTION_REASON_MISMATCH",
    )
    failures = {name: 0 for name in failure_names}
    for row in rows:
        name = row["earliest_failure_type"]
        if name in failures:
            failures[name] += 1
    return {
        "CLASSIFIER_ACCEPTED_COUNT": sum(
            row["earliest_failure_type"] not in {
                "TRANSPORT_FAILURE", "MAIAGENT_ENVELOPE_INVALID",
                "CLASSIFIER_INVALID_RESPONSE",
            }
            for row in rows
        ),
        "CLASSIFIER_INVALID_COUNT": sum(
            row["earliest_failure_type"] in {
                "CLASSIFIER_INVALID_RESPONSE",
            }
            for row in rows
        ),
        "EXACT_CATEGORY_MATCH_COUNT": sum(row["matches_golden"] for row in rows),
        "CATEGORY_STATE_MISMATCH_COUNT": failures["CATEGORY_STATE_MISMATCH"],
        "PRIMARY_CATEGORY_MISMATCH_COUNT": failures["PRIMARY_CATEGORY_MISMATCH"],
        "RESOLUTION_REASON_MISMATCH_COUNT": failures["RESOLUTION_REASON_MISMATCH"],
        "SEMANTIC_CITATION_CONCERN_COUNT": sum(
            len(row["semantic_citation_concerns"]) for row in rows
        ),
        "FAILURE_BREAKDOWN": failures,
        "SEMANTIC_CITATION_REVIEW": "HUMAN_REVIEW_REQUIRED",
        "MISMATCH_DETAILS": [row for row in rows if not row["matches_golden"]],
    }


def _acceptance_evidence_for(
    *,
    call_evidence: Mapping[str, Any],
    actual: CategoryResult,
    expected: Mapping[str, str],
    round_index: int,
    ordinal: int,
    configuration_fingerprint: str,
    deployment_fingerprint: str | None,
    runtime_identity_fingerprint: str | None,
    transport_attempts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Bind exact request, proposal, validation and deployment evidence."""

    validated_result = actual.as_mapping()
    evidence = dict(call_evidence)
    evidence["ordinal"] = ordinal
    evidence["round_index"] = round_index
    evidence["configuration_fingerprint"] = configuration_fingerprint
    evidence["deployment_fingerprint"] = deployment_fingerprint
    evidence["runtime_helper_identity_fingerprint"] = runtime_identity_fingerprint
    evidence["validated_result"] = validated_result
    evidence["validated_result_sha256"] = hashlib.sha256(
        _canonical_json(validated_result).encode("utf-8")
    ).hexdigest()
    evidence["validation_status"] = (
        "CLASSIFIER_REJECTED_PROPOSAL"
        if actual.provenance.get("decision_basis") == "proposal_contract_violation"
        else "CLASSIFIER_ACCEPTED"
    )
    evidence["transport_attempts"] = [dict(item) for item in transport_attempts]
    evidence["transport_accounting"] = _transport_attempt_accounting(transport_attempts)
    latest_transport = transport_attempts[-1] if transport_attempts else {}
    evidence["provider_request_body_sha256"] = latest_transport.get(
        "request_body_sha256"
    )
    evidence["provider_response_body_sha256"] = latest_transport.get(
        "response_body_sha256"
    )
    chain_material = {
        "evidence_version": ACCEPTANCE_EVIDENCE_VERSION,
        "round_index": round_index,
        "ordinal": ordinal,
        "configuration_fingerprint": configuration_fingerprint,
        "deployment_fingerprint": deployment_fingerprint,
        "runtime_helper_identity_fingerprint": runtime_identity_fingerprint,
        "request_payload_sha256": evidence.get("request_payload_sha256"),
        "provider_request_body_sha256": evidence.get("provider_request_body_sha256"),
        "provider_response_body_sha256": evidence.get("provider_response_body_sha256"),
        "transport_attempts": evidence["transport_attempts"],
        "transport_accounting": evidence["transport_accounting"],
        "proposal_sha256": evidence.get("proposal_sha256"),
        "validated_result_sha256": evidence["validated_result_sha256"],
        "expected": dict(expected),
    }
    evidence["chain_sha256"] = hashlib.sha256(
        _canonical_json(chain_material).encode("utf-8")
    ).hexdigest()
    return evidence


def _live_evidence_complete(evidence: Mapping[str, Any]) -> bool:
    required = (
        "request_payload_sha256",
        "provider_request_body_sha256",
        "provider_response_body_sha256",
        "proposal_sha256",
        "validated_result_sha256",
        "chain_sha256",
    )
    accounting = evidence.get("transport_accounting")
    attempts = evidence.get("transport_attempts")
    return (
        all(isinstance(evidence.get(key), str) and evidence[key] for key in required)
        and isinstance(attempts, list)
        and isinstance(accounting, Mapping)
        and accounting.get("status") == "PASS"
        and accounting.get("attempt_count") == len(attempts)
        and accounting.get("retry_count") == max(0, len(attempts) - 1)
    )


def _base_report(
    manifest,
    fixtures,
    specs,
    oracle_mapping,
    counts,
    leakage,
    *,
    round_index: int,
    deployment_provenance: Mapping[str, Any] | None,
    runtime_helper_identity: str | None,
) -> dict[str, Any]:
    return {
        "CATEGORY_53_GROUP_LIVE_ACCEPTANCE": "BLOCKED",
        "ACCEPTANCE_VERSION": ACCEPTANCE_VERSION,
        "ACCEPTANCE_EVIDENCE_VERSION": ACCEPTANCE_EVIDENCE_VERSION,
        "DEPLOYMENT_SNAPSHOT_CONTRACT_VERSION": DEPLOYMENT_SNAPSHOT_CONTRACT_VERSION,
        "CONFIGURATION_FINGERPRINT": _configuration_fingerprint(specs, oracle_mapping),
        "ROUND_INDEX": round_index,
        "PLANNED_ROUNDS": FINAL_SEAL_ROUNDS,
        "GROUPS_PER_ROUND": GROUPS_PER_ROUND,
        "TOTAL_PLANNED_LIVE_CALLS": TOTAL_PLANNED_LIVE_CALLS,
        **_deployment_provenance_record(
            deployment_provenance,
            runtime_helper_identity=runtime_helper_identity,
        ),
        "TOTAL_GOLDEN_FIXTURES": counts["total_fixtures"],
        "CATEGORY_REACHED_FIXTURES": counts["category_reached_fixtures"],
        "PREPARED_EVENT_GROUPS": counts["prepared_event_groups"],
        "GROUP_LEVEL_ASSIGNED_EXPECTED": counts["group_level_assigned"],
        "GROUP_LEVEL_UNRESOLVED_EXPECTED": counts["group_level_unresolved"],
        "GROUP_LEVEL_TOTAL_EXPECTED": counts["group_level_assigned"] + counts["group_level_unresolved"],
        "ORACLE_MAPPING": "PASS" if len(oracle_mapping) == len(specs) else "FINDINGS",
        "ORACLE_MAPPING_DETAILS": counts["mapping_rows"],
        "ORACLE_LEAKAGE_CHECK": "PASS" if leakage[0] else "FINDINGS",
        "ORACLE_LEAKAGE_DETAILS": leakage[1],
        "LIVE_CALL_BUDGET": LIVE_CALL_BUDGET,
        "LIVE_CALL_COUNT": 0,
        "HTTP_200_COUNT": 0,
        "LOGICAL_CALL_COUNT": 0,
        "TRANSPORT_ATTEMPT_COUNT": 0,
        "FINAL_HTTP_200_COUNT": 0,
        "HTTP_200_ATTEMPT_COUNT": 0,
        "AUTHORIZED_TRANSPORT_RETRY_COUNT": 0,
        "UNAUTHORIZED_TRANSPORT_RETRY_COUNT": 0,
        "TRANSPORT_ACCOUNTING_STATUS": "NOT_COMPLETE",
        "TRANSPORT_RETRY_REASON_COUNTS": {},
        "CLASSIFIER_ACCEPTED_COUNT": 0,
        "CLASSIFIER_INVALID_COUNT": 0,
        "EXACT_CATEGORY_MATCH_COUNT": 0,
        "CATEGORY_STATE_MISMATCH_COUNT": 0,
        "PRIMARY_CATEGORY_MISMATCH_COUNT": 0,
        "RESOLUTION_REASON_MISMATCH_COUNT": 0,
        "SEMANTIC_CITATION_CONCERN_COUNT": 0,
        "FAILURE_BREAKDOWN": {},
        "MISMATCH_DETAILS": [],
        "RESULTS": [],
        "MAIAGENT_ADAPTER_USED": "NO",
        "RESPONSES_ADAPTER_USED": "NO",
        "WRITER_CHATBOT_USED": "NO",
        "FALLBACK_PRESENT": "NO",
        "RETRY_PRESENT": "NO",
        "SEMANTIC_RETRY_PRESENT": "NO",
        "RESCUE_PRESENT": "NO",
        "BACKFILL_PRESENT": "NO",
        "REQUEST_EVIDENCE": "EXACT_SERIALIZATION_SHA256",
        "RESPONSE_EVIDENCE": "PARSED_ACTION_LIFECYCLE_PROPOSAL_AND_CLASSIFIER_VALIDATED_CATEGORY_RESULT",
        "ACCEPTANCE_EVIDENCE_CHAIN": "REQUIRED_FOR_LIVE_SCOREABILITY",
        "ACCEPTANCE_EVIDENCE_CHAIN_STATUS": "NOT_COMPLETE",
        "ACCEPTANCE_EVIDENCE_COMPLETE_COUNT": 0,
    }


def run_evaluation(
    *,
    config: MaiAgentCategorySemanticProviderConfig | None = None,
    provider=None,
    transport=None,
    round_index: int = 1,
    deployment_provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run offline stub evaluation or the explicitly requested live MaiAgent run."""

    if round_index not in range(1, FINAL_SEAL_ROUNDS + 1):
        raise ValueError("round_index must be one of 1, 2, or 3")

    live = provider is None
    resolved_config = None
    runtime_helper_identity = None
    if live:
        resolved_config = config or MaiAgentCategorySemanticProviderConfig.from_environment()
        if resolved_config is not None:
            runtime_helper_identity = resolved_config.chatbot_id

    manifest, fixtures = _load_population()
    specs, oracle_mapping, counts = _phase_a_reconcile(fixtures)
    leakage = _oracle_leakage_check(specs)
    report = _base_report(
        manifest,
        fixtures,
        specs,
        oracle_mapping,
        counts,
        leakage,
        round_index=round_index,
        deployment_provenance=deployment_provenance,
        runtime_helper_identity=runtime_helper_identity,
    )
    if not leakage[0]:
        report["CATEGORY_53_GROUP_LIVE_ACCEPTANCE"] = "BLOCKED"
        report["BLOCKER"] = "ORACLE_LEAKAGE_PREFLIGHT_FAILED"
        return report
    if (
        counts["total_fixtures"] != TOTAL_GOLDEN_FIXTURES
        or counts["category_reached_fixtures"] != CATEGORY_REACHED_FIXTURES
        or len(specs) != GROUPS_PER_ROUND
    ):
        report["BLOCKER"] = "FINAL_SEAL_ACCEPTANCE_POPULATION_MISMATCH"
        return report
    if len(oracle_mapping) != len(specs):
        report["ORACLE_MAPPING"] = "FINDINGS"
        report["BLOCKER"] = "EVENT_GROUP_ORACLE_MAPPING_INCOMPLETE"
        return report

    if live:
        proxy_blockers = _proxy_blockers()
        if proxy_blockers:
            report["BLOCKER"] = "LOCAL_PROXY_VARIABLES_MUST_BE_ABSENT"
            report["PROXY_VARIABLES_PRESENT"] = proxy_blockers
            return report
        if resolved_config is None:
            report["BLOCKER"] = "CATEGORY_MAIAGENT_CONFIGURATION_UNAVAILABLE"
            return report
        if report["DEPLOYMENT_PROVENANCE_STATUS"] != "OBSERVED_AND_FROZEN":
            report["BLOCKER"] = "DEPLOYMENT_RUNTIME_BINDING_REQUIRED"
            return report
        recording_transport = _RecordingMaiAgentTransport(
            transport or UrllibMaiAgentJsonTransport()
        )
        actual_provider = MaiAgentCategorySemanticProvider(
            resolved_config,
            transport=recording_transport,
        )
        provider = actual_provider
        report["MAIAGENT_ADAPTER_USED"] = "YES"
    else:
        recording_transport = None

    capture = _CaptureProvider(
        provider,
        expected_payloads=[spec["request_payload"] for spec in specs],
    )
    classifier = Classifier(capture)
    rows: list[dict[str, Any]] = []
    for spec in specs:
        key = (spec["case_id"], spec["group"].event_id)
        observation_index = len(rows)
        transport_start = (
            len(recording_transport.observations)
            if recording_transport is not None
            else 0
        )
        actual = _classify_for_evaluation(classifier, spec)
        transport_attempts = (
            recording_transport.observations[transport_start:]
            if recording_transport is not None
            else []
        )
        observation = transport_attempts[-1] if transport_attempts else None
        expected = oracle_mapping[key]
        citations, citation_concerns = _citation_details(
            actual, spec["request"], capture.last_proposal
        )
        first_failure = _first_failure(actual, expected, observation)
        matches = first_failure not in {
            "TRANSPORT_FAILURE",
            "MAIAGENT_ENVELOPE_INVALID",
            "CLASSIFIER_INVALID_RESPONSE",
            "CATEGORY_STATE_MISMATCH",
            "PRIMARY_CATEGORY_MISMATCH",
            "RESOLUTION_REASON_MISMATCH",
        }
        actual_state = actual.category_state.value
        row = {
            "fixture_id": spec["case_id"],
            "event_group_id": spec["group"].event_id,
            "member_candidate_ids": spec["member_candidate_ids"],
            "fixture_candidate_ids": spec["fixture_candidate_ids"],
            "expected": dict(expected),
            "actual": actual.as_mapping(),
            "proposal": capture.last_proposal,
            "earliest_failure_type": first_failure,
            "matches_golden": matches,
            "citations": citations,
            "semantic_citation_concerns": citation_concerns,
            "semantic_citation_review": "HUMAN_REVIEW_REQUIRED",
            "validation_error": actual.provenance.get("validation_error"),
            "http_status": observation.get("status_code") if observation else None,
        }
        call_evidence = capture.call_evidence[observation_index]
        acceptance_evidence = _acceptance_evidence_for(
            call_evidence=call_evidence,
            actual=actual,
            expected=expected,
            round_index=round_index,
            ordinal=observation_index + 1,
            configuration_fingerprint=report["CONFIGURATION_FINGERPRINT"],
            deployment_fingerprint=report.get("DEPLOYMENT_FINGERPRINT"),
            runtime_identity_fingerprint=report.get(
                "RUNTIME_HELPER_IDENTITY_FINGERPRINT"
            ),
            transport_attempts=transport_attempts,
        )
        row["proposal"] = acceptance_evidence.get("proposal")
        row["acceptance_evidence"] = acceptance_evidence
        row["outcome_class"] = _outcome_class(
            expected_state=expected["category_state"],
            actual_state=actual_state,
            matches_golden=matches,
        )
        rows.append(row)
        if capture.integrity_error:
            report["BLOCKER"] = "PRECHECKED_REQUEST_CHANGED_BEFORE_PROVIDER_CALL"
            break

    metrics = _summarize_rows(rows)
    report.update(metrics)
    report["RESULTS"] = rows
    all_attempts = (
        recording_transport.observations if recording_transport is not None else []
    )
    report["LIVE_CALL_COUNT"] = len(rows)
    report["HTTP_200_COUNT"] = report["FINAL_HTTP_200_COUNT"] = sum(
        bool(row.get("acceptance_evidence", {}).get("transport_attempts"))
        and row["acceptance_evidence"]["transport_attempts"][-1].get("status_code") == 200
        for row in rows
    )
    report["HTTP_200_ATTEMPT_COUNT"] = sum(
        item.get("status_code") == 200 for item in all_attempts
    )
    report["LOGICAL_CALL_COUNT"] = len(rows)
    report["TRANSPORT_ATTEMPT_COUNT"] = len(all_attempts)
    retry_accounting = [
        row.get("acceptance_evidence", {}).get("transport_accounting", {})
        for row in rows
    ]
    retry_reasons: dict[str, int] = {}
    for accounting in retry_accounting:
        for reason in accounting.get("retry_reasons", []):
            retry_reasons[reason] = retry_reasons.get(reason, 0) + 1
    report["AUTHORIZED_TRANSPORT_RETRY_COUNT"] = sum(
        int(item.get("retry_count", 0))
        for item in retry_accounting
        if item.get("status") == "PASS"
    )
    report["UNAUTHORIZED_TRANSPORT_RETRY_COUNT"] = sum(
        int(item.get("unauthorized_retry", False)) for item in retry_accounting
    )
    report["TRANSPORT_RETRY_REASON_COUNTS"] = retry_reasons
    report["TRANSPORT_ACCOUNTING_STATUS"] = (
        "PASS"
        if all(item.get("status") == "PASS" for item in retry_accounting)
        and len(retry_accounting) == len(rows)
        else "FINDINGS"
    )
    report["TRANSPORT_RETRY_PRESENT"] = (
        "YES" if report["AUTHORIZED_TRANSPORT_RETRY_COUNT"] else "NO"
    )
    if live and (
        len(rows) != len(specs)
        or any(not _live_evidence_complete(row["acceptance_evidence"]) for row in rows)
        or report.get("SAME_RUNTIME_HELPER_BINDING") != "PROVEN"
        or report["TRANSPORT_ACCOUNTING_STATUS"] != "PASS"
    ):
        report["CATEGORY_53_GROUP_LIVE_ACCEPTANCE"] = "BLOCKED"
        report["BLOCKER"] = (
            "TRANSPORT_ATTEMPT_ACCOUNTING_INCOMPLETE"
            if report["TRANSPORT_ACCOUNTING_STATUS"] != "PASS"
            else "ACCEPTANCE_EVIDENCE_CHAIN_INCOMPLETE"
        )
        return report
    if live:
        report["ACCEPTANCE_EVIDENCE_CHAIN_STATUS"] = "COMPLETE"
        report["ACCEPTANCE_EVIDENCE_COMPLETE_COUNT"] = len(rows)
    if report.get("BLOCKER"):
        return report
    if live and report["EXACT_CATEGORY_MATCH_COUNT"] == len(specs):
        report["CATEGORY_53_GROUP_LIVE_ACCEPTANCE"] = "PASS"
    elif live:
        report["CATEGORY_53_GROUP_LIVE_ACCEPTANCE"] = "FINDINGS"
    else:
        report["CATEGORY_53_GROUP_LIVE_ACCEPTANCE"] = "NOT_LIVE_TEST"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--run-live-maiagent",
        action="store_true",
        help="send one completion per reconciled Event Group (maximum 53)",
    )
    action.add_argument(
        "--assess-round-reports",
        nargs=FINAL_SEAL_ROUNDS,
        metavar=("ROUND_1", "ROUND_2", "ROUND_3"),
        help="assess exactly three current live round JSON reports with evidence-chain proof",
    )
    action.add_argument(
        "--assess-historical-round-reports",
        nargs=FINAL_SEAL_ROUNDS,
        metavar=("ROUND_1", "ROUND_2", "ROUND_3"),
        help="assess the frozen historical round JSON reports as historical-only evidence",
    )
    parser.add_argument(
        "--round-index",
        type=int,
        choices=range(1, FINAL_SEAL_ROUNDS + 1),
        help="predeclared Final Seal round index for one explicit live run",
    )
    parser.add_argument(
        "--deployment-provenance-file",
        help="JSON read-back of the category-deployment-snapshot-v1 contract",
    )
    args = parser.parse_args()
    if args.assess_round_reports or args.assess_historical_round_reports:
        report_paths = args.assess_round_reports or args.assess_historical_round_reports
        reports = [
            json.loads(Path(path).read_text(encoding="utf-8"))
            for path in report_paths
        ]
        assessor = (
            assess_final_seal_batch
            if args.assess_round_reports
            else assess_historical_final_seal_batch
        )
        assessment = assessor(reports)
        print(json.dumps(assessment, ensure_ascii=False, indent=2))
        return 0 if assessment["CATEGORY_V4_FINAL_SEAL"] == "PASS" else 2
    if not args.run_live_maiagent:
        print(
            json.dumps(
                {
                    "CATEGORY_53_GROUP_LIVE_ACCEPTANCE": "NOT_RUN",
                    "ACCEPTANCE_VERSION": ACCEPTANCE_VERSION,
                    "ACCEPTANCE_EVIDENCE_VERSION": ACCEPTANCE_EVIDENCE_VERSION,
                    "DEPLOYMENT_SNAPSHOT_CONTRACT_VERSION": DEPLOYMENT_SNAPSHOT_CONTRACT_VERSION,
                    "PLANNED_ROUNDS": FINAL_SEAL_ROUNDS,
                    "GROUPS_PER_ROUND": GROUPS_PER_ROUND,
                    "TOTAL_PLANNED_LIVE_CALLS": TOTAL_PLANNED_LIVE_CALLS,
                    "NEXT_STEP": "pass --run-live-maiagent, --round-index 1, 2, or 3, and --deployment-provenance-file after category-deployment-snapshot-v1 platform read-back in a local process with all six proxy variables absent",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.round_index is None:
        parser.error("--run-live-maiagent requires an explicit --round-index")
    if args.deployment_provenance_file is None:
        parser.error("--run-live-maiagent requires --deployment-provenance-file")
    try:
        deployment_provenance = json.loads(
            Path(args.deployment_provenance_file).read_text(encoding="utf-8")
        )
        report = run_evaluation(
            round_index=args.round_index,
            deployment_provenance=deployment_provenance,
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {
                    "CATEGORY_53_GROUP_LIVE_ACCEPTANCE": "BLOCKED",
                    "ACCEPTANCE_VERSION": ACCEPTANCE_VERSION,
                    "ACCEPTANCE_EVIDENCE_VERSION": ACCEPTANCE_EVIDENCE_VERSION,
                    "DEPLOYMENT_PROVENANCE_STATUS": "INVALID",
                    "BLOCKER": "DEPLOYMENT_SNAPSHOT_INVALID",
                    "ERROR": str(exc),
                    "LIVE_CALL_COUNT": 0,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["CATEGORY_53_GROUP_LIVE_ACCEPTANCE"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
