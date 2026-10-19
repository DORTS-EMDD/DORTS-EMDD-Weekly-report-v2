"""Local capture and deterministic replay for bounded Scope acceptance runs.

This script records provider proposals and the sole Python Scope owner's result.
It never owns or changes a Scope decision and replay never constructs a provider.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Mapping
from uuid import uuid4


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from src.weekly_report.contracts import EvidenceResult, EvidenceState
from src.weekly_report.maiagent_scope_provider import (
    HELPER_VERSION,
    PROMPT_VERSION,
    PROVIDER_IDENTIFIER,
    SCHEMA_VERSION,
    TASK_IDENTITY,
    MaiAgentScopeProviderConfig,
    MaiAgentScopeProviderFailure,
    build_maiagent_scope_provider,
)
from src.weekly_report.scope_classifier import ScopeClassifier, ScopeValidationObservation


ARTIFACT_VERSION = "scope-acceptance-case-v1"
DEFAULT_ARTIFACT_DIRECTORY = REPOSITORY_ROOT
MAX_CASES_PER_RUN = 20
MAX_PROPOSAL_BYTES = 512 * 1024
_SAFE_CASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
_SENSITIVE_KEY = re.compile(r"(?i)(api.?key|authorization|cookie|password|secret|chatbot.?id|credential|access.?token)")
_SAFE_PROVIDER_FAILURES = {"TRANSPORT", "HTTP_STATUS", "RESPONSE_PARSE"}


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _assert_safe_tree(value: Any, *, secret_values: tuple[str, ...] = (), path: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str) or _SENSITIVE_KEY.search(key):
                raise ValueError(f"sensitive field blocked at {path}")
            _assert_safe_tree(item, secret_values=secret_values, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_safe_tree(item, secret_values=secret_values, path=f"{path}[{index}]")
    elif isinstance(value, str):
        if any(secret and secret in value for secret in secret_values):
            raise ValueError(f"configured secret blocked at {path}")
    elif value is None or isinstance(value, (bool, int, float)):
        return
    else:
        raise ValueError(f"non-JSON value blocked at {path}")


def _write_atomic(path: Path, artifact: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(_canonical_json(artifact) + b"\n")
    temporary.replace(path)


def _current_revision() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return "UNAVAILABLE"
    revision = result.stdout.strip()
    return revision if re.fullmatch(r"[0-9a-f]{40,64}", revision) else "UNAVAILABLE"


def _validate_case(case: Mapping[str, Any], *, secret_values: tuple[str, ...]) -> dict[str, Any]:
    required = {"case_id", "authoritative_input_identity", "candidate_id", "candidate_title", "source_content"}
    if not isinstance(case, Mapping) or not required.issubset(case):
        raise ValueError("acceptance case is missing required fields")
    case_id = case["case_id"]
    if not isinstance(case_id, str) or _SAFE_CASE_ID.fullmatch(case_id) is None:
        raise ValueError("case_id must be a short filesystem-safe identifier")
    for field_name in ("authoritative_input_identity", "candidate_id", "candidate_title", "source_content"):
        if not isinstance(case[field_name], str) or not case[field_name].strip():
            raise ValueError(f"{field_name} must be a nonempty string")
    source_metadata = case.get("source_metadata", {})
    if not isinstance(source_metadata, Mapping):
        raise ValueError("source_metadata must be a JSON object")
    safe_case = {
        "case_id": case_id,
        "authoritative_input_identity": case["authoritative_input_identity"],
        "candidate_id": case["candidate_id"],
        "candidate_title": case["candidate_title"],
        "source_content": case["source_content"],
        "source_metadata": dict(source_metadata),
    }
    _assert_safe_tree(safe_case, secret_values=secret_values)
    _canonical_json(safe_case)
    return safe_case


def _failure_category(exc: Exception) -> str:
    if isinstance(exc, TimeoutError):
        return "TIMEOUT"
    if isinstance(exc, MaiAgentScopeProviderFailure):
        category = getattr(exc, "failure_category", "")
        return category if category in _SAFE_PROVIDER_FAILURES else "PROVIDER_FAILURE"
    return "PROVIDER_FAILURE"


def _acceptance_status(parse_status: str, first_rejection: str | None, scope_state: str) -> str:
    if parse_status == "PARSED_CAPTURE_BLOCKED":
        return "CAPTURE_INCOMPLETE"
    if parse_status == "FAILED":
        return "PROVIDER_FAILURE"
    if first_rejection is not None:
        return "OWNER_VALIDATION_REJECTED"
    if scope_state == "IN_SCOPE":
        return "OWNER_ACCEPTED_IN_SCOPE"
    return "OWNER_ACCEPTED_OUT_OF_SCOPE"


def capture_case(
    case: Mapping[str, Any],
    provider: Any,
    *,
    run_id: str,
    artifact_directory: str | Path = DEFAULT_ARTIFACT_DIRECTORY,
    code_revision: str | None = None,
    secret_values: tuple[str, ...] = (),
) -> Path:
    """Make exactly one provider call, capture it, and run the real Scope owner."""
    safe_case = _validate_case(case, secret_values=secret_values)
    if not isinstance(run_id, str) or _SAFE_CASE_ID.fullmatch(run_id) is None:
        raise ValueError("run_id must be a short filesystem-safe identifier")
    source_content = safe_case["source_content"]
    source_metadata = safe_case["source_metadata"]
    content_digest = _sha256(source_content.encode("utf-8"))
    metadata_digest = _sha256(_canonical_json(source_metadata))
    request_identity = {
        "authoritative_input_identity": safe_case["authoritative_input_identity"],
        "candidate_id": safe_case["candidate_id"],
        "candidate_title": safe_case["candidate_title"],
        "source_content_sha256": content_digest,
        "source_metadata_sha256": metadata_digest,
    }
    artifact_path = Path(artifact_directory) / f".scope-acceptance-{run_id}-{safe_case['case_id']}.json"
    if artifact_path.exists():
        raise FileExistsError("refusing to overwrite an existing Scope acceptance artifact")
    artifact: dict[str, Any] = {
        "artifact_version": ARTIFACT_VERSION,
        "run_id": run_id,
        "case_id": safe_case["case_id"],
        "authoritative_input_identity": safe_case["authoritative_input_identity"],
        "candidate_id": safe_case["candidate_id"],
        "candidate_title": safe_case["candidate_title"],
        "source_content": source_content,
        "source_content_sha256": content_digest,
        "source_metadata": source_metadata,
        "source_metadata_sha256": metadata_digest,
        "request_identity_sha256": _sha256(_canonical_json(request_identity)),
        "task_identity": TASK_IDENTITY,
        "prompt_version": PROMPT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "helper_version": HELPER_VERSION,
        "provider_identifier": PROVIDER_IDENTIFIER,
        "source_code_revision": code_revision or _current_revision(),
        "provider_response_parse_status": "NOT_STARTED",
        "provider_proposal": None,
        "provider_diagnostic": None,
        "technical_failure_category": None,
        "python_scope_state": None,
        "python_scope_diagnostic": None,
        "first_rejection_predicate": None,
        "acceptance_status": "CAPTURE_STARTED",
        "semantic_acceptance_status": "REQUIRES_INDEPENDENT_SEMANTIC_REVIEW",
    }
    _write_atomic(artifact_path, artifact)

    class RecordingProvider:
        def __call__(self, request: Any) -> object:
            try:
                response = provider(request)
            except Exception as exc:
                artifact["provider_response_parse_status"] = "FAILED"
                artifact["technical_failure_category"] = _failure_category(exc)
                artifact["provider_diagnostic"] = {"exception_type": type(exc).__name__}
                _write_atomic(artifact_path, artifact)
                raise
            try:
                _assert_safe_tree(response, secret_values=secret_values, path="provider_proposal")
                serialized = _canonical_json(response)
                if len(serialized) > MAX_PROPOSAL_BYTES:
                    raise ValueError("provider proposal exceeded the local capture bound")
            except Exception as exc:
                artifact["provider_response_parse_status"] = "PARSED_CAPTURE_BLOCKED"
                artifact["technical_failure_category"] = "CAPTURE_SAFETY"
                artifact["provider_diagnostic"] = {"exception_type": type(exc).__name__}
                _write_atomic(artifact_path, artifact)
                return response
            artifact["provider_response_parse_status"] = "PARSED"
            artifact["provider_proposal"] = json.loads(serialized.decode("utf-8"))
            artifact["provider_proposal_sha256"] = _sha256(serialized)
            _write_atomic(artifact_path, artifact)
            return response

    def observe(value: ScopeValidationObservation) -> None:
        artifact["first_rejection_predicate"] = value.first_rejection_predicate
        artifact["owner_observation_status"] = value.response_status
        artifact["python_scope_state"] = value.scope_state.value
        artifact["python_scope_diagnostic"] = value.diagnostic.value
        artifact["acceptance_status"] = _acceptance_status(
            artifact["provider_response_parse_status"],
            value.first_rejection_predicate,
            value.scope_state.value,
        )
        _write_atomic(artifact_path, artifact)

    evidence = EvidenceResult(
        candidate_id=safe_case["candidate_id"],
        state=EvidenceState.READY,
        substantive_content=source_content,
        provenance=source_metadata,
    )
    result = ScopeClassifier(RecordingProvider()).classify(
        evidence,
        candidate_title=safe_case["candidate_title"],
        observation_hook=observe,
    )
    artifact["python_scope_state"] = result.state.value
    artifact["python_scope_diagnostic"] = result.diagnostic.value
    artifact["acceptance_status"] = _acceptance_status(
        artifact["provider_response_parse_status"],
        artifact["first_rejection_predicate"],
        result.state.value,
    )
    _write_atomic(artifact_path, artifact)
    return artifact_path


def replay_artifact(path: str | Path) -> dict[str, Any]:
    """Replay a saved parsed proposal through ScopeClassifier with no provider."""
    artifact = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(artifact, dict) or artifact.get("artifact_version") != ARTIFACT_VERSION:
        raise ValueError("unsupported Scope acceptance artifact")
    content = artifact.get("source_content")
    metadata = artifact.get("source_metadata")
    proposal = artifact.get("provider_proposal")
    if not isinstance(content, str) or _sha256(content.encode("utf-8")) != artifact.get("source_content_sha256"):
        return {"replay_status": "FAIL", "reason": "SOURCE_CONTENT_DIGEST_MISMATCH", "provider_call_count": 0}
    if not isinstance(metadata, dict) or _sha256(_canonical_json(metadata)) != artifact.get("source_metadata_sha256"):
        return {"replay_status": "FAIL", "reason": "SOURCE_METADATA_DIGEST_MISMATCH", "provider_call_count": 0}
    request_identity = {
        "authoritative_input_identity": artifact.get("authoritative_input_identity"),
        "candidate_id": artifact.get("candidate_id"),
        "candidate_title": artifact.get("candidate_title"),
        "source_content_sha256": artifact.get("source_content_sha256"),
        "source_metadata_sha256": artifact.get("source_metadata_sha256"),
    }
    if _sha256(_canonical_json(request_identity)) != artifact.get("request_identity_sha256"):
        return {"replay_status": "FAIL", "reason": "REQUEST_IDENTITY_DIGEST_MISMATCH", "provider_call_count": 0}
    if artifact.get("provider_response_parse_status") != "PARSED" or not isinstance(proposal, dict):
        return {
            "replay_status": "BLOCKED",
            "provider_response_parse_status": artifact.get("provider_response_parse_status"),
            "owner_replay_status": "NOT_REPLAYABLE",
            "reason": "NO_REPLAYABLE_PARSED_PROPOSAL",
            "provider_call_count": 0,
        }
    if _sha256(_canonical_json(proposal)) != artifact.get("provider_proposal_sha256"):
        return {"replay_status": "FAIL", "reason": "PROPOSAL_DIGEST_MISMATCH", "provider_call_count": 0}

    evidence = EvidenceResult(
        candidate_id=artifact["candidate_id"],
        state=EvidenceState.READY,
        substantive_content=content,
        provenance=metadata,
    )
    observations: list[ScopeValidationObservation] = []
    result = ScopeClassifier(lambda _request: proposal).classify(
        evidence,
        candidate_title=artifact["candidate_title"],
        observation_hook=observations.append,
    )
    first_rejection = observations[0].first_rejection_predicate if observations else None
    reproduced = (
        result.state.value == artifact.get("python_scope_state")
        and result.diagnostic.value == artifact.get("python_scope_diagnostic")
        and first_rejection == artifact.get("first_rejection_predicate")
    )
    return {
        "replay_status": "PASS" if reproduced else "FAIL",
        "provider_response_parse_status": artifact["provider_response_parse_status"],
        "owner_replay_status": "PASS" if reproduced else "FAIL",
        "scope_state": result.state.value,
        "diagnostic": result.diagnostic.value,
        "first_rejection_predicate": first_rejection,
        "provider_call_count": 0,
    }


def _load_cases(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases") if isinstance(payload, dict) else None
    if not isinstance(cases, list) or not cases or len(cases) > MAX_CASES_PER_RUN:
        raise ValueError(f"input must contain 1 to {MAX_CASES_PER_RUN} cases")
    if any(not isinstance(case, dict) for case in cases):
        raise ValueError("every acceptance case must be a JSON object")
    case_ids = [case.get("case_id") for case in cases]
    if len(set(case_ids)) != len(case_ids):
        raise ValueError("case_id values must be unique within a run")
    return cases


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capture or replay bounded Scope acceptance evidence.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    capture_parser = subparsers.add_parser("capture", help="make one configured provider call per fixed input case")
    capture_parser.add_argument("--input", required=True, type=Path, help="JSON object with a cases array")
    replay_parser = subparsers.add_parser("replay", help="replay one saved parsed proposal offline")
    replay_parser.add_argument("artifact", type=Path)
    args = parser.parse_args(argv)

    if args.command == "replay":
        print(json.dumps(replay_artifact(args.artifact), ensure_ascii=False, sort_keys=True))
        return 0

    config = MaiAgentScopeProviderConfig.from_environment()
    if config is None:
        parser.error("MaiAgent Scope provider configuration is unavailable")
    provider = build_maiagent_scope_provider(config)
    if provider is None:
        parser.error("MaiAgent Scope provider could not be constructed")
    cases = _load_cases(args.input)
    run_id = uuid4().hex
    secret_values = (config.api_key, config.chatbot_id)
    validated_cases = [_validate_case(case, secret_values=secret_values) for case in cases]
    paths = [
        capture_case(case, provider, run_id=run_id, secret_values=secret_values)
        for case in validated_cases
    ]
    print(json.dumps({"run_id": run_id, "case_count": len(paths), "artifact_paths": [str(path) for path in paths]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
