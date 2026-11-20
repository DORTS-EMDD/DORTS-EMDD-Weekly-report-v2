"""Observer-only record of one Category helper exchange (RC-69, section A.50).

The Classifier calls :func:`observe_category_exchange` at its existing exits,
after its decision is fixed, and keeps the returned mapping beside that
decision: in ``CategoryResult.provenance["semantic_exchange"]``, or as the
``category_exchange`` attribute of the exception that becomes a disclosed
TechnicalGap. Only the selection audit reads it. Nothing here takes part in a
Category, Taxonomy, Reportability, Writer, Validator or Delivery decision.

The record is public (selection audit artifact of a public repository), so it
holds IDs, hashes, allowlisted enum values, declared version identifiers, a
raw subtype that passes the subtype policy, and only the short structured
``action_facts`` and unresolved-claim values that pass the exposure policy.
Those admitted values may be short fragments of source text (a city name,
for example); a complete source sentence, guidance text, a provider response
body, credentials and other provider metadata are never held. Every other
value keeps only ``{withheld, sha256}``.

``semantic_request_fingerprint_sha256`` proves equality of
``CategorySemanticRequest.as_payload()`` only. A matching fingerprint with
the same versions and no withheld value is an input-equivalent semantic
replay; it is never an exact replay (model identity and inference parameters
are platform-held and not observable), and provider nondeterminism remains.

Every builder failure is contained: the caller receives the UNAVAILABLE
record, never an exception.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256
import json
import re
from typing import Any
import unicodedata

from .contracts import CategoryId, CategoryPrincipalAction, CategoryResolutionReason, CategoryState
from .evidence_sentences import segment_evidence_sentences

CATEGORY_EXCHANGE_OBSERVATION_SCHEMA = "category-exchange-observation-v2"
REPLAY_SCOPE = "INPUT_EQUIVALENT_SEMANTIC_ONLY"
FINGERPRINT_CANONICALIZATION = "json sort_keys, separators=(',',':'), ensure_ascii=false, UTF-8"

OUTCOME_ACCEPTED = "ACCEPTED"
OUTCOME_REJECTED = "REJECTED"
OUTCOME_NO_PROPOSAL = "NO_PROPOSAL"

# The keys ``classifier._action_facts`` can emit; any other key is withheld.
ALLOWED_ACTION_FACT_KEYS = frozenset(
    {"action", "lifecycle_step", "subject", "asset", "project", "package", "location", "occurrence_context"}
)
CLAIMS_KEY = "source_claims"

VALUE_LIMIT = 80
SUBTYPE_LIMIT = 128
CITATION_LIMIT = 8
SENTENCE_ID_LIMIT = 40
MAX_SERIALIZED_LENGTH = 16_000
# Room the selection audit may add (the TechnicalGap failure class) without
# crossing MAX_SERIALIZED_LENGTH; the builder caps records below it.
AUDIT_HEADROOM = 128

# Fail-closed allowlists for the proposal's enum fields and the validation block.
_CATEGORY_STATES = frozenset(item.value for item in CategoryState)
_CATEGORY_IDS = frozenset(item.value for item in CategoryId)
_RESOLUTION_REASONS = frozenset(item.value for item in CategoryResolutionReason)
_PRINCIPAL_ACTIONS = frozenset(item.value for item in CategoryPrincipalAction)
_PREDICATES = frozenset(
    {
        "RESPONSE_SHAPE", "CATEGORY_STATE", "CATEGORY_ID", "SUBTYPE_FORMAT", "RESOLUTION_REASON",
        "UNRESOLVED_ASSIGNMENT", "CITATION_INVALID", "PROPOSAL_INVALID",
    }
)
_OUTCOMES = frozenset({"ACCEPTED", "REJECTED", "NO_PROPOSAL"})
# Unicode categories never exposed: control, format (zero-width, bidi), private
# use, surrogate, unassigned, line and paragraph separators. Any space other
# than U+0020 (for example U+00A0 or U+3000) is also withheld.
_DISALLOWED_CATEGORIES = frozenset({"Cc", "Cf", "Co", "Cs", "Cn", "Zl", "Zp"})

_KEY_PATTERN = re.compile(r"^[a-z0-9_.]{1,64}$")
_SOURCE_REF_PATTERN = re.compile(r"^M\d{1,3}$")
_SENTENCE_ID_PATTERN = re.compile(r"^S\d{1,4}$")
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._\-]{0,127}$")
_FAILURE_CLASS = re.compile(r"^[A-Z0-9_]{1,64}$")
_SENTENCE_BREAK = re.compile(r"[.!?。！？]\s*\S")
_URL = re.compile(r"(?i)(https?://|www\.)")
_EMAIL = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")
_IP = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
_LONG_DIGITS = re.compile(r"\d{8,}")
_DIGIT_SEPARATORS = re.compile(r"[\s\-().+/]")
_TOKEN = re.compile(r"[A-Za-z0-9_\-]{24,}")
_SECRET_PREFIX = re.compile(r"(?i)(\bsk-|api[-_ ]?key|bearer\s|secret|password|token)")


def has_disallowed_character(value: str) -> bool:
    """True for control, format, separator, private-use or non-U+0020 space characters."""

    for character in value:
        category = unicodedata.category(character)
        if category in _DISALLOWED_CATEGORIES or (category == "Zs" and character != " "):
            return True
    return False


def _sensitive_pattern(value: str) -> bool:
    if _URL.search(value) or _EMAIL.search(value) or _IP.search(value):
        return True
    if _LONG_DIGITS.search(_DIGIT_SEPARATORS.sub("", value)):
        return True
    return bool(_SECRET_PREFIX.search(value))


def _mixed_token(value: str) -> bool:
    """A 24+ character run holding both a letter and a digit (keys, hex digests)."""

    return any(
        any(c.isdigit() for c in match.group()) and any(c.isalpha() for c in match.group())
        for match in _TOKEN.finditer(value)
    )


def _sha256(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def semantic_request_fingerprint(payload: Mapping[str, Any]) -> str:
    """SHA-256 of the canonical JSON of ``CategorySemanticRequest.as_payload()``."""

    return _sha256(_canonical(payload))


def _withheld(reason: str, raw: Any) -> dict[str, str]:
    text = raw if isinstance(raw, str) else _canonical(raw) if _json_safe(raw) else repr(type(raw))
    return {"withheld": reason, "sha256": _sha256(text)}


def _json_safe(value: Any) -> bool:
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return False
    return True


def exposure_violation(value: Any, source_sentences: Sequence[str] = ()) -> str | None:
    """The exposure-policy reason a value must be withheld, or None to expose it."""

    if not isinstance(value, str):
        return "CONTENT_BOUND"
    if len(value) > VALUE_LIMIT:
        return "SIZE_BOUND"
    stripped = value.strip()
    if not stripped or has_disallowed_character(value):
        return "CONTENT_BOUND"
    if any(stripped == sentence.strip() for sentence in source_sentences):
        return "CONTENT_BOUND"
    if _SENTENCE_BREAK.search(stripped):
        return "CONTENT_BOUND"
    if _sensitive_pattern(value) or _TOKEN.search(value):
        return "CONTENT_BOUND"
    return None


def subtype_violation(value: str) -> str | None:
    """The exposure-policy reason a raw subtype string must be withheld, or None."""

    if len(value) > SUBTYPE_LIMIT:
        return "SIZE_BOUND"
    if not value.strip() or has_disallowed_character(value):
        return "CONTENT_BOUND"
    if _SENTENCE_BREAK.search(value.strip()) or _sensitive_pattern(value) or _mixed_token(value):
        return "CONTENT_BOUND"
    return None


def _exposed(value: Any, source_sentences: Sequence[str], withheld: list[bool]) -> Any:
    reason = exposure_violation(value, source_sentences)
    if reason is None:
        return value
    withheld.append(True)
    return _withheld(reason, value)


def _action_facts(facts: Mapping[str, Any], source_sentences: Sequence[str], withheld: list[bool]) -> dict[str, Any]:
    observed: dict[str, Any] = {}
    for key in sorted(facts, key=str):
        value = facts[key]
        if key in ALLOWED_ACTION_FACT_KEYS:
            observed[key] = _exposed(value, source_sentences, withheld)
        elif key == CLAIMS_KEY and isinstance(value, Mapping):
            claims: dict[str, Any] = {}
            for claim_key in sorted(value, key=str):
                if isinstance(claim_key, str) and _KEY_PATTERN.match(claim_key):
                    claims[claim_key] = _exposed(value[claim_key], source_sentences, withheld)
                else:
                    withheld.append(True)
                    claims.setdefault("withheld_keys", []).append(_withheld("KEY_NOT_ALLOWED", str(claim_key)))
            observed[CLAIMS_KEY] = claims
        else:
            withheld.append(True)
            observed.setdefault("withheld_keys", []).append(_withheld("KEY_NOT_ALLOWED", str(key)))
    return observed


def _semantic_request(payload: Mapping[str, Any], sources: Sequence[Any], unresolved: Sequence[Any], refs: Mapping[str, str]) -> dict[str, Any]:
    ref_of = {candidate_id: ref for ref, candidate_id in refs.items()}
    withheld: list[bool] = []
    observed_sources = []
    action_facts: dict[str, Any] = {}
    sentences_of: dict[str, list[str]] = {}
    for source in sources:
        ref = ref_of[source.candidate_id]
        sentences = [sentence.text for sentence in segment_evidence_sentences(source.substantive_content)]
        sentences_of[source.candidate_id] = sentences
        observed_sources.append(
            {
                "source_ref": ref,
                "candidate_id": source.candidate_id,
                "content_sha256": _sha256(source.substantive_content),
            }
        )
        action_facts[ref] = _action_facts(dict(source.action_facts), sentences, withheld)
    claims = []
    for claim_key, candidate_values in unresolved:
        if isinstance(claim_key, str) and _KEY_PATTERN.match(claim_key):
            key: Any = claim_key
        else:
            withheld.append(True)
            key = _withheld("KEY_NOT_ALLOWED", str(claim_key))
        claims.append(
            {
                "claim_key": key,
                "source_values": [
                    {
                        "source_ref": ref_of.get(candidate_id, "UNKNOWN"),
                        "value": _exposed(value, sentences_of.get(candidate_id, ()), withheld),
                    }
                    for candidate_id, value in candidate_values
                ],
            }
        )
    from .category_semantic_provider import CATEGORY_SEMANTIC_PROMPT_VERSION  # lazy: the provider imports classifier

    return {
        "semantic_request_fingerprint_sha256": semantic_request_fingerprint(payload),
        "fingerprint_canonicalization": FINGERPRINT_CANONICALIZATION,
        "category_prompt_version": CATEGORY_SEMANTIC_PROMPT_VERSION,
        "guidance_sha256": _sha256(_canonical(list(payload["guidance"]))),
        "sources": observed_sources,
        "action_facts": action_facts,
        "unresolved_event_claims": claims,
        "input_exposure": "WITHHELD" if withheld else "FULL",
    }


def _allowlisted(value: Any, allowed: frozenset[str]) -> Any:
    """An enum member as itself; any other string only as {withheld, sha256}."""

    value = _enum_value(value)
    if value is None:
        return None
    if not isinstance(value, str):
        return "INVALID_VALUE"
    if value in allowed:
        return value
    return _withheld("NOT_ALLOWLISTED", value)


def _identifier(value: Any) -> Any:
    """A declared repository constant: lowercase identifier text only."""

    if value is None:
        return None
    if isinstance(value, str) and _IDENTIFIER.match(value) and not _mixed_token(value):
        return value
    if isinstance(value, str):
        return _withheld("NOT_IDENTIFIER", value)
    return "INVALID_VALUE"


def failure_class_value(value: Any) -> Any:
    """A TechnicalGap failure class (upper-case identifier) or {withheld, sha256}."""

    if value is None:
        return None
    if isinstance(value, str) and _FAILURE_CLASS.match(value):
        return value
    return _withheld("NOT_IDENTIFIER", value)


def _provider_declared(provenance: Mapping[str, Any] | None) -> dict[str, Any]:
    declared = dict(provenance or {})
    return {
        "provider_identifier": _identifier(declared.get("provider_identifier")),
        "message_version": _identifier(declared.get("prompt_version")),
        "schema_version": _identifier(declared.get("schema_version")),
        "helper_version": _identifier(declared.get("helper_version")),
        "model_identifier": _identifier(declared.get("model_identifier")),
        "inference_parameters": None,
    }


def _subtype(value: Any) -> Any:
    if value is None:
        return None
    if not isinstance(value, str):
        return "INVALID_VALUE"
    reason = subtype_violation(value)
    if reason is not None:
        return _withheld(reason, value)
    return value


def _citations(value: Any) -> tuple[list[dict[str, Any]], int]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return [], 0
    observed: list[dict[str, Any]] = []
    for raw in list(value)[:CITATION_LIMIT]:
        if isinstance(raw, Mapping):
            source_ref, ids = raw.get("source_ref"), raw.get("sentence_ids")
        else:
            source_ref, ids = getattr(raw, "source_ref", None), getattr(raw, "sentence_ids", None)
        ref = source_ref if isinstance(source_ref, str) and _SOURCE_REF_PATTERN.match(source_ref) else "INVALID_VALUE"
        ids = list(ids) if isinstance(ids, (list, tuple)) else []
        kept = [item for item in ids if isinstance(item, str) and _SENTENCE_ID_PATTERN.match(item)][:SENTENCE_ID_LIMIT]
        observed.append({"source_ref": ref, "sentence_ids": kept, "omitted_sentence_ids": len(ids) - len(kept)})
    return observed, max(0, len(value) - CITATION_LIMIT)


def _proposal(payload: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if payload is None:
        return None
    citations, omitted = _citations(payload.get("citations"))
    return {
        # RC-80 (section A.61): the helper proposes a principal action (or an
        # unresolved reason); the Category is the Classifier's mapping.
        "principal_action": _allowlisted(payload.get("principal_action"), _PRINCIPAL_ACTIONS),
        "unresolved_reason": _allowlisted(payload.get("unresolved_reason"), _RESOLUTION_REASONS),
        "subtype_raw": _subtype(payload.get("subtype")),
        "citations": citations,
        "citations_omitted": omitted,
    }


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def unavailable_category_exchange(error: str = "OBSERVATION_BUILD_FAILED") -> dict[str, Any]:
    """The record a reader sees when the observation could not be built."""

    return {
        "observation_schema": CATEGORY_EXCHANGE_OBSERVATION_SCHEMA,
        "observation_status": "UNAVAILABLE",
        "observation_error": error,
        "replay_scope": REPLAY_SCOPE,
        "semantic_request": None,
        "provider_declared": None,
        "proposal": None,
        "validation": None,
    }


def _build(
    request: Any,
    *,
    outcome: str,
    proposal_payload: Mapping[str, Any] | None,
    provider_provenance: Mapping[str, Any] | None,
    predicate: str | None,
    category_result_state: str | None,
) -> dict[str, Any]:
    record = unavailable_category_exchange()
    record["observation_status"] = "COMPLETE"
    record["observation_error"] = None
    failed = 0
    try:
        record["semantic_request"] = _semantic_request(
            request.as_payload(), request.sources, request.unresolved_claims, request.source_refs
        )
    except Exception:
        failed += 1
    try:
        record["provider_declared"] = _provider_declared(provider_provenance)
    except Exception:
        failed += 1
    try:
        record["proposal"] = _proposal(proposal_payload)
    except Exception:
        failed += 1
    record["validation"] = {
        "outcome": _allowlisted(outcome, _OUTCOMES),
        "predicate": _allowlisted(predicate, _PREDICATES),
        "technical_failure_class": None,
        "category_result_state": _allowlisted(category_result_state, _CATEGORY_STATES),
    }
    if failed:
        record["observation_status"] = "PARTIAL"
        record["observation_error"] = "OBSERVATION_BUILD_FAILED"
    if serialized_length(record) > MAX_SERIALIZED_LENGTH - AUDIT_HEADROOM:
        return unavailable_category_exchange("SIZE_BOUND")
    return record


def serialized_length(record: Any) -> int:
    """The one length measure for the record bound (compact canonical JSON)."""

    return len(_canonical(record))


def observe_category_exchange(
    request: Any,
    *,
    outcome: str,
    proposal_payload: Mapping[str, Any] | None = None,
    provider_provenance: Mapping[str, Any] | None = None,
    predicate: str | None = None,
    category_result_state: str | None = None,
) -> dict[str, Any]:
    """Build the observer record; it never raises and decides nothing."""

    try:
        return _build(
            request,
            outcome=outcome,
            proposal_payload=proposal_payload,
            provider_provenance=provider_provenance,
            predicate=predicate,
            category_result_state=category_result_state,
        )
    except Exception:
        return unavailable_category_exchange()


def attach_category_exchange(failure: BaseException, record: Mapping[str, Any]) -> None:
    """Attach the record to the failure that becomes a TechnicalGap; never raises."""

    try:
        failure.category_exchange = record  # type: ignore[attr-defined]
    except Exception:
        pass


__all__ = [
    "AUDIT_HEADROOM",
    "CATEGORY_EXCHANGE_OBSERVATION_SCHEMA",
    "MAX_SERIALIZED_LENGTH",
    "OUTCOME_ACCEPTED",
    "OUTCOME_NO_PROPOSAL",
    "OUTCOME_REJECTED",
    "REPLAY_SCOPE",
    "attach_category_exchange",
    "exposure_violation",
    "failure_class_value",
    "has_disallowed_character",
    "observe_category_exchange",
    "semantic_request_fingerprint",
    "serialized_length",
    "subtype_violation",
    "unavailable_category_exchange",
]
