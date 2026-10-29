"""MaiAgent adapter for the RC-15 Event Identity grouping proposal task.

This module owns transport mechanics for one task only.  It never forms an
EventGroup; Python ``EventIdentity`` validates the proposal and remains the
sole owner of Candidate-to-Candidate Event Equivalence.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import json
import math
import os
from typing import Any
from urllib.parse import quote, urlsplit

from .contracts import EventIdentityGroupingRequest
from .event_identity import grouping_response_schema
from .maiagent_transport import (
    MaiAgentJsonHttpTransport,
    UrllibMaiAgentJsonTransport,
    load_shared_maiagent_values,
    request_maiagent_proposal,
)


TASK_IDENTITY = "event_identity_semantic_proposal"
PROMPT_VERSION = "event-identity-grouping-v5"
SCHEMA_VERSION = "event-identity-semantic-proposal-v1"
# RC-31: a confirmation answer admits one-record groups (section A.25).
CONFIRMATION_SCHEMA_VERSION = "event-identity-semantic-confirmation-v1"
HELPER_VERSION = "maiagent-structured-helper-event-identity-adapter-v1"
PROVIDER_IDENTIFIER = "maiagent-structured-helper-event-identity"
# One request carries a whole batch of records, so it is allowed longer than
# a single-record helper call; the shared retry policy is unchanged.
EVENT_IDENTITY_TIMEOUT_SECONDS = 90.0

EVENT_IDENTITY_INSTRUCTIONS = (
    "You are a stateless proposal-only semantic helper for the Python EventIdentity owner.",
    "Each supplied record is one news source about one urban rail event. Identify records that report the same event, including records in different languages.",
    "Same event means one real-world occurrence at one time: the same accident, failure, opening, contract award, announcement, decision or test. Different lifecycle steps of the same project (for example a train delivery, a construction milestone and an opening date), different statements or meetings about the same project, and separate incidents on the same line are different events. Two incidents on consecutive days are different events. Occurrences in different cities, countries or systems are different events, even when they are of the same kind (for example two emergency drills or two construction milestones).",
    "Use only the supplied evidence_sentences and identity_facts. Each record has a record_id and each sentence a sentence_id, both assigned by Python; a sentence_id is valid only within its own record. Refer to records only by record_id.",
    "When event_identity_request.confirmation is false: return only groups of two or more records that report the same event. Leave every other record out; do not return single-record groups. Put all records of one event into a single group; never split one event across two groups.",
    "When event_identity_request.confirmation is true, the records are one group proposed earlier and you re-check it. Then return every supplied record exactly once: the records that report the same occurrence together in one group, and every other record as its own single-record group (a group whose members list holds that one record). The response schema for a confirmation allows single-record groups. Do not leave any record out; an empty groups list is never a valid confirmation answer.",
    "For every member cite sentence_ids of that record: subject_sentence_ids for the system, line, asset or project concerned; occurrence_sentence_ids for what happened; lifecycle_sentence_ids for the step reached (for example ordered, delivered, tested, opened, suspended, investigated). The same sentence may serve several roles. Never copy or translate source text into a citation.",
    "When the evidence does not establish that two records report the same occurrence, leave them apart. Similar topics, the same city, the same system or the same project are not sufficient.",
    "Do not search, browse, use tools, retrieve external knowledge, or infer from publishers, URLs or titles; none are supplied.",
    "Return exactly one JSON object with the supplied schema, no extra fields and no prose outside JSON.",
)


@dataclass(frozen=True, slots=True)
class MaiAgentEventIdentityProviderConfig:
    api_base: str
    api_key: str = field(repr=False)
    chatbot_id: str = field(repr=False)
    timeout_seconds: float = EVENT_IDENTITY_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        values = (self.api_base, self.api_key, self.chatbot_id)
        if any(not isinstance(value, str) for value in values):
            raise ValueError("MaiAgent Event Identity configuration values must be strings")
        if any("\r" in value or "\n" in value for value in values):
            raise ValueError("MaiAgent Event Identity configuration contains invalid characters")
        try:
            parsed = urlsplit(self.api_base)
            hostname = parsed.hostname
            parsed.port
        except (TypeError, ValueError):
            raise ValueError("MaiAgent API base must be an absolute HTTPS origin") from None
        if parsed.scheme != "https" or not parsed.netloc or hostname is None or parsed.username is not None or parsed.password is not None or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("MaiAgent API base must be an absolute HTTPS origin")
        if not self.api_key.strip() or not self.chatbot_id.strip():
            raise ValueError("MaiAgent Event Identity API key and chatbot ID are required")
        if isinstance(self.timeout_seconds, bool) or not isinstance(self.timeout_seconds, (int, float)) or not math.isfinite(float(self.timeout_seconds)) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

    @property
    def completion_endpoint(self) -> str:
        return f"{self.api_base.rstrip('/')}/api/v1/chatbots/{quote(self.chatbot_id, safe='')}/completions/"

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None, *, timeout_seconds: float = EVENT_IDENTITY_TIMEOUT_SECONDS, dotenv_path: str | os.PathLike[str] | None = None):
        values = load_shared_maiagent_values(environ, dotenv_path=dotenv_path)
        api_base, api_key, chatbot_id = (values.get(key) for key in ("MAIAGENT_API_BASE", "MAIAGENT_API_KEY", "MAIAGENT_STRUCTURED_HELPER_CHATBOT_ID"))
        if not all(isinstance(value, str) and value.strip() for value in (api_base, api_key, chatbot_id)):
            return None
        return cls(api_base.strip(), api_key.strip(), chatbot_id.strip(), timeout_seconds)


def build_maiagent_event_identity_model_input(request: EventIdentityGroupingRequest) -> dict[str, Any]:
    if not isinstance(request, EventIdentityGroupingRequest):
        raise TypeError("MaiAgent Event Identity input requires EventIdentityGroupingRequest")
    schema_version = CONFIRMATION_SCHEMA_VERSION if request.confirmation else SCHEMA_VERSION
    return {
        "task_identity": TASK_IDENTITY,
        "prompt_version": PROMPT_VERSION,
        "schema_version": schema_version,
        "helper_version": HELPER_VERSION,
        "instructions": list(EVENT_IDENTITY_INSTRUCTIONS),
        "event_identity_request": request.as_payload(),
        "authoritative_response_contract": {
            "schema_version": schema_version,
            "json_schema": grouping_response_schema(request),
        },
    }


class MaiAgentEventIdentityProposalProvider:
    def __init__(self, config: MaiAgentEventIdentityProviderConfig, *, transport: MaiAgentJsonHttpTransport | None = None) -> None:
        if not isinstance(config, MaiAgentEventIdentityProviderConfig):
            raise TypeError("MaiAgentEventIdentityProposalProvider requires MaiAgentEventIdentityProviderConfig")
        self._config = config
        self._transport = transport if transport is not None else UrllibMaiAgentJsonTransport()

    def __call__(self, request: EventIdentityGroupingRequest) -> object:
        if not isinstance(request, EventIdentityGroupingRequest):
            raise TypeError("MaiAgent Event Identity provider accepts only EventIdentityGroupingRequest")
        request_content = json.dumps(build_maiagent_event_identity_model_input(request), ensure_ascii=False, separators=(",", ":"))
        body = json.dumps({"message": {"role": "user", "content": request_content}, "conversation": None, "attachments": [], "is_streaming": False}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        # Technical failures propagate as typed SemanticProviderTechnicalFailure
        # after the shared bounded retry; parseable responses go to the owner.
        return request_maiagent_proposal(
            self._transport,
            self._config.completion_endpoint,
            headers={
                "Authorization": f"Api-Key {self._config.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            body=body,
            timeout_seconds=float(self._config.timeout_seconds),
            task=TASK_IDENTITY,
        )


def build_maiagent_event_identity_provider(config: MaiAgentEventIdentityProviderConfig | None = None, *, transport: MaiAgentJsonHttpTransport | None = None, environ: Mapping[str, str] | None = None, dotenv_path: str | os.PathLike[str] | None = None) -> MaiAgentEventIdentityProposalProvider | None:
    resolved = config or MaiAgentEventIdentityProviderConfig.from_environment(environ, dotenv_path=dotenv_path)
    return None if resolved is None else MaiAgentEventIdentityProposalProvider(resolved, transport=transport)


__all__ = [
    "CONFIRMATION_SCHEMA_VERSION", "EVENT_IDENTITY_INSTRUCTIONS", "EVENT_IDENTITY_TIMEOUT_SECONDS", "HELPER_VERSION", "MaiAgentEventIdentityProposalProvider", "MaiAgentEventIdentityProviderConfig", "PROMPT_VERSION", "PROVIDER_IDENTIFIER", "SCHEMA_VERSION", "TASK_IDENTITY", "build_maiagent_event_identity_model_input", "build_maiagent_event_identity_provider",
]
