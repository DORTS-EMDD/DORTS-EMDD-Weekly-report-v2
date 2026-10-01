"""Opt-in MaiAgent Category acceptance over sealed Golden Event Groups.

Run one predeclared round manually with ``--run-live-maiagent``, an explicit
``--round-index``, and a deployment snapshot read-back file.
The deterministic test suite never calls a live provider.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.weekly_report.category_semantic_provider import (  # noqa: E402
    CATEGORY_SEMANTIC_SCHEMA_VERSION,
    MAIAGENT_CATEGORY_MESSAGE_VERSION,
    MAIAGENT_CATEGORY_PROVIDER_IDENTIFIER,
    MAIAGENT_CATEGORY_SEMANTIC_HELPER_VERSION,
    MaiAgentCategorySemanticProvider,
    MaiAgentCategorySemanticProviderConfig,
    MaiAgentHttpResponse,
    UrllibMaiAgentJsonTransport,
    _CATEGORY_RESPONSE_SCHEMA,
    _MAIAGENT_CATEGORY_RESPONSE_SCHEMA,
)
from src.weekly_report.classifier import (  # noqa: E402
    CategorySemanticHelperResult,
    CategorySemanticRequest,
    Classifier,
    _CATEGORY_GUIDANCE,
    _request_for,
)
from src.weekly_report.contracts import (  # noqa: E402
    CanonicalCandidate,
    CategoryState,
    EvidenceResult,
    EvidenceState,
    EventGroup,
    EventIdentityFacts,
    EventIdentityRecord,
    ScopeResult,
    ScopeState,
    TemporalResult,
    UnresolvedClaim,
)


class _CaptureProvider:
    def __init__(self, provider, *, expected_payloads: list[str] | None = None):
        self.provider = provider
        self.last_proposal: object | None = None
        self.last_request: CategorySemanticRequest | None = None
        self.expected_payloads = expected_payloads
        self.call_count = 0
        self.integrity_error: str | None = None

    def __call__(self, request):
        self.last_proposal = None
        self.last_request = request
        if self.expected_payloads is not None:
            if self.call_count >= len(self.expected_payloads):
                self.integrity_error = "classifier produced an unplanned Category request"
                raise RuntimeError(self.integrity_error)
            actual_payload = _serialized_request(request)
            if actual_payload != self.expected_payloads[self.call_count]:
                self.integrity_error = "classifier request differs from the oracle-isolated preflight"
                raise RuntimeError(self.integrity_error)
        self.call_count += 1
        result = self.provider(request)
        self.last_proposal = result.proposal if isinstance(result, CategorySemanticHelperResult) else result
        return result


class _RecordingMaiAgentTransport:
    """Observe one status per adapter call without changing request behavior."""

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
            self.observations.append({"status_code": None, "transport_error_type": type(exc).__name__})
            raise
        if isinstance(response, MaiAgentHttpResponse):
            self.observations.append({"status_code": response.status_code})
        else:
            self.observations.append({"status_code": None, "transport_error_type": "InvalidTransportResponse"})
        return response


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
                    substantive_content=str(candidate["source_content"]),
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


ACCEPTANCE_VERSION = "category-v4-final-seal-v2"
EVALUATION_HARNESS_VERSION = "category-semantic-evaluation-v3"
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
        found = set(value)
        for child in value.values():
            found.update(_collect_keys(child))
        return found
    if isinstance(value, list):
        found: set[str] = set()
        for child in value:
            found.update(_collect_keys(child))
        return found
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


def _configuration_fingerprint(
    specs: list[dict[str, Any]],
    oracle_mapping: Mapping[tuple[str, str], Mapping[str, str]],
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
        "evaluation_harness_version": EVALUATION_HARNESS_VERSION,
        "category_guidance": list(_CATEGORY_GUIDANCE),
        "authoritative_response_schema": _CATEGORY_RESPONSE_SCHEMA,
        "provider_schema_projection": _MAIAGENT_CATEGORY_RESPONSE_SCHEMA,
        "provider_message_version": MAIAGENT_CATEGORY_MESSAGE_VERSION,
        "category_schema_version": CATEGORY_SEMANTIC_SCHEMA_VERSION,
        "provider_identifier": MAIAGENT_CATEGORY_PROVIDER_IDENTIFIER,
        "helper_version": MAIAGENT_CATEGORY_SEMANTIC_HELPER_VERSION,
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


_ZERO_ERROR_ROUND_EXPECTATIONS = {
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
        raise ValueError(f"deployment snapshot {label} must be an object")
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
    provider = _observed_string(platform["provider"], "platform.provider")
    instance_id = _observed_string(
        platform["chatbot_instance_id"], "platform.chatbot_instance_id"
    )
    model_identifier = _observed_string(
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
    schema = _mapping(structured_output["schema"], "structured_output.schema")

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


def _deployment_provenance_record(
    value: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if value is None:
        return {"DEPLOYMENT_PROVENANCE_STATUS": "DEPLOYMENT_PROVENANCE_UNAVAILABLE"}
    snapshot = _validate_deployment_snapshot(value)
    fingerprint_material = {
        key: item for key, item in snapshot.items() if key != "audit_metadata"
    }
    return {
        "DEPLOYMENT_PROVENANCE_STATUS": "OBSERVED_AND_FROZEN",
        "DEPLOYMENT_SNAPSHOT_CONTRACT_VERSION": snapshot["snapshot_contract_version"],
        "DEPLOYMENT_FINGERPRINT": hashlib.sha256(
            _canonical_json(fingerprint_material).encode("utf-8")
        ).hexdigest(),
    }


def assess_final_seal_batch(round_reports: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Assess exactly the three predeclared rounds without replacing failures."""

    result: dict[str, Any] = {
        "CATEGORY_V4_FINAL_SEAL": "BLOCKED",
        "ACCEPTANCE_VERSION": ACCEPTANCE_VERSION,
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
        failures = {
            key: {"expected": expected, "actual": report.get(key)}
            for key, expected in _ZERO_ERROR_ROUND_EXPECTATIONS.items()
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


def _citation_details(
    actual,
    request: CategorySemanticRequest,
    proposal: object,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    source_text = {source.candidate_id: source.substantive_content for source in request.sources}
    raw_citations = proposal.get("citations", ()) if isinstance(proposal, Mapping) else ()
    canonical_spans = actual.provenance.get("validated_support_spans", ())
    details: list[dict[str, Any]] = []
    if isinstance(raw_citations, list):
        for index, citation in enumerate(raw_citations):
            if not isinstance(citation, Mapping):
                continue
            candidate_id = citation.get("candidate_id")
            quote = citation.get("quote")
            source = source_text.get(candidate_id) if isinstance(candidate_id, str) else None
            span = canonical_spans[index] if index < len(canonical_spans) else None
            resolved = (
                span is not None
                and span.get("candidate_id") == candidate_id
                and isinstance(source, str)
            )
            start = span["start"] if resolved else None
            end = span["end"] if resolved else None
            details.append(
                {
                    "candidate_id": candidate_id,
                    "quote": quote,
                    "resolved_start": start,
                    "resolved_end": end,
                    "resolved_substring": source[start:end] if resolved else None,
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
    actual = classifier.classify(spec["group"], spec["records"])
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
) -> dict[str, Any]:
    return {
        "CATEGORY_53_GROUP_LIVE_ACCEPTANCE": "BLOCKED",
        "ACCEPTANCE_VERSION": ACCEPTANCE_VERSION,
        "DEPLOYMENT_SNAPSHOT_CONTRACT_VERSION": DEPLOYMENT_SNAPSHOT_CONTRACT_VERSION,
        "CONFIGURATION_FINGERPRINT": _configuration_fingerprint(specs, oracle_mapping),
        "ROUND_INDEX": round_index,
        "PLANNED_ROUNDS": FINAL_SEAL_ROUNDS,
        "GROUPS_PER_ROUND": GROUPS_PER_ROUND,
        "TOTAL_PLANNED_LIVE_CALLS": TOTAL_PLANNED_LIVE_CALLS,
        **_deployment_provenance_record(deployment_provenance),
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
        "RESCUE_PRESENT": "NO",
        "BACKFILL_PRESENT": "NO",
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

    live = provider is None
    if live:
        proxy_blockers = _proxy_blockers()
        if proxy_blockers:
            report["BLOCKER"] = "LOCAL_PROXY_VARIABLES_MUST_BE_ABSENT"
            report["PROXY_VARIABLES_PRESENT"] = proxy_blockers
            return report
        if report["DEPLOYMENT_PROVENANCE_STATUS"] != "OBSERVED_AND_FROZEN":
            report["BLOCKER"] = "DEPLOYMENT_PROVENANCE_READBACK_REQUIRED"
            return report
        resolved_config = config or MaiAgentCategorySemanticProviderConfig.from_environment()
        if resolved_config is None:
            report["BLOCKER"] = "CATEGORY_MAIAGENT_CONFIGURATION_UNAVAILABLE"
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
        actual = classifier.classify(spec["group"], spec["records"])
        observation = (
            recording_transport.observations[observation_index]
            if recording_transport is not None and observation_index < len(recording_transport.observations)
            else None
        )
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
    report["LIVE_CALL_COUNT"] = (
        len(recording_transport.observations) if recording_transport is not None else 0
    )
    report["HTTP_200_COUNT"] = (
        sum(item.get("status_code") == 200 for item in recording_transport.observations)
        if recording_transport is not None
        else 0
    )
    if report.get("BLOCKER"):
        return report
    if live and (
        report["LIVE_CALL_COUNT"] != len(specs)
        or report["HTTP_200_COUNT"] != len(specs)
    ):
        report["CATEGORY_53_GROUP_LIVE_ACCEPTANCE"] = "FINDINGS"
    elif live and report["EXACT_CATEGORY_MATCH_COUNT"] == len(specs):
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
        help="assess exactly three saved round JSON reports without network access",
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
    if args.assess_round_reports:
        reports = [
            json.loads(Path(path).read_text(encoding="utf-8"))
            for path in args.assess_round_reports
        ]
        assessment = assess_final_seal_batch(reports)
        print(json.dumps(assessment, ensure_ascii=False, indent=2))
        return 0 if assessment["CATEGORY_V4_FINAL_SEAL"] == "PASS" else 2
    if not args.run_live_maiagent:
        print(
            json.dumps(
                {
                    "CATEGORY_53_GROUP_LIVE_ACCEPTANCE": "NOT_RUN",
                    "ACCEPTANCE_VERSION": ACCEPTANCE_VERSION,
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
