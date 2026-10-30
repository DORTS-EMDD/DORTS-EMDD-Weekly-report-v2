"""MaiAgent adapter for the authorized Scope semantic proposal task.

This module owns transport mechanics for one task only.  It never constructs
or returns ``ScopeResult``; Python ``ScopeClassifier`` validates the proposal
and remains the authoritative owner.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import json
import math
import os
from typing import Any
from urllib.parse import quote, urlsplit

from .maiagent_transport import (
    MaiAgentHttpResponse,
    MaiAgentJsonHttpTransport,
    MaiAgentResponseError,
    UrllibMaiAgentJsonTransport,
    load_shared_maiagent_values,
    parse_maiagent_response,
    MAIAGENT_HELPER_TIMEOUT_SECONDS,
    request_maiagent_proposal,
)
from .scope_classifier import (
    SCOPE_PROPOSAL_SCHEMA_VERSION,
    SCOPE_SEMANTIC_RESPONSE_SCHEMA,
    ScopeSemanticRequest,
)


TASK_IDENTITY = "scope_semantic_proposal"
PROMPT_VERSION = "scope-event-target-system-v11"
SCHEMA_VERSION = SCOPE_PROPOSAL_SCHEMA_VERSION
HELPER_VERSION = "maiagent-structured-helper-scope-adapter-v1"
PROVIDER_IDENTIFIER = "maiagent-structured-helper-scope"

SCOPE_TASK_IDENTITY = TASK_IDENTITY
SCOPE_PROMPT_VERSION = PROMPT_VERSION
SCOPE_SCHEMA_VERSION = SCHEMA_VERSION
SCOPE_HELPER_VERSION = HELPER_VERSION
MAIAGENT_SCOPE_PROVIDER_IDENTIFIER = PROVIDER_IDENTIFIER

SCOPE_SEMANTIC_INSTRUCTIONS = (
    "You are a stateless proposal-only semantic helper for the Python ScopeClassifier.",
    "Use only the supplied principal_sentences and same-document metadata. Each sentence has a sentence_id assigned by Python.",
    "Cite Evidence only by sentence_id. Never copy, retype, translate or summarize source text into a citation; a citation is a list of sentence_ids.",
    "Interpret in order: identify the Candidate event, its asserted action, what the action actually affects or where the event takes place, and the transport system that target belongs to or functions for; only then propose an eligible mode if supported.",
    "The affected target is not automatically the operator, owner, city, publisher, nearby station, route, or whole Metro system. For example, installed platform-door equipment is the target, and irrigation or sculptures installed for a neighbouring park remain park equipment. Do not infer target-system membership from transport vocabulary or proximity.",
    "Use action_target relation AFFECTS when the action acts on the target. Use LOCATED_AT only when the Candidate event itself takes place on or in the target, and the target is a station, platform, train, depot, track or other facility of the transport system (for example a derailment, fire, assault or breakdown on a platform or train). Proximity, nearby or adjacent locations are never LOCATED_AT. Whether such an event is worth reporting is decided elsewhere, not here.",
    "When the source supports eligibility, use exactly one canonical eligible_mode_family: METRO, MRT, SUBWAY, LIGHT_RAIL, TRAM, URBAN_RAIL, AGT, MONORAIL, or PEOPLE_MOVER. Urban maglev maps to URBAN_RAIL; AGT and People Mover remain distinct. NON_ELIGIBLE and UNKNOWN are valid when their respective noneligible or unresolved status is supported; do not force an eligible family.",
    "Mode words in any language state the family: 捷運 (Taiwan's word for MRT, including 機場捷運) is MRT; 地鐵, 地铁, 地下鉄 and 지하철 are METRO or SUBWAY; 도시철도 (urban railway) is URBAN_RAIL; 輕軌, 轻轨, ライトレール and 경전철 are LIGHT_RAIL; 路面電車, 有軌電車 and 트램 are TRAM. A system named with such a word (for example 基隆捷運, 桃園捷運綠線 or 臺北捷運) is described by the source as that mode. Conventional and high-speed railways such as 台鐵/臺鐵, 高鐵 and JR intercity lines are not urban rail.",
    "Commuter, suburban, regional, S-Bahn, S-tog and RER labels neither include nor exclude a system by name. Use an eligible family for such a service only when the supplied source itself describes the affected system as metro, light rail, tram, or urban rapid transit; a commuter or suburban description alone is UNKNOWN or NON_URBAN_RAIL, never URBAN_RAIL.",
    "Endpoints are labels: action.label, target.label and system.label are short exact source-surface substrings (original language and form; do not translate, paraphrase, normalize, conjugate, or invent). action.label must differ from target.label and system.label. target.label and system.label may be the same text when the action affects the system itself, such as a new line, extension or network.",
    "Copy each label character for character from one sentence, keeping its inflection, conjugation and particles exactly as written there (if the sentence says 'agredidos', the label is 'agredidos', not 'agresión'; if it says 'trikk', not 'trikken'). Cite in action_target and in target_system every sentence that contains one of that relation's labels, so each relation's citation contains its endpoints.",
    "Citation obligations: event_focus.sentence_ids is required for RESOLVED or CONFLICTING; action_target and target_system sentence_ids are required when ESTABLISHED or CONFLICTING; ambiguity only for CONFLICTING; noneligible_relation only for PRESENT. Otherwise use an empty list.",
    "The sentences cited by action_target must contain both the action label and the target label. The sentences cited by target_system must contain the system label and either the target label or, when the source refers back to the target, the exact referring words in target_system.target_reference (such as 'The five lines', 'This', 'the line', '該線'). Omit target_reference when the target label itself appears there.",
    "event_focus cites the consecutive sentences describing the Candidate event; every sentence cited by a relation must lie within the range from the first to the last event_focus sentence. Do not borrow support from a separate event in the same document.",
    "When the target phrase itself names its system or mode, such as 'five metro lines', 'tram Route 19', 'Chennai Metro's Yellow Line' or '電車', that phrase already states membership: cite the sentence containing it for target_system, with the system label equal to the target label or the system word inside it.",
    "A station, platform, track, train, depot or service of a named station, line or network of the system is PART_OF that system; for example 'a northbound E train platform at the 53rd Street subway station' is PART_OF the subway, and a tram that derailed is PART_OF the tram system.",
    "For contract, procurement, operation and maintenance, authorisation, funding or study events, the target is the work, service, equipment, line or project the action covers (for example 'the operation and maintenance of lines M1 to M4' or 'a 6.2 km underground line'), not the contract document itself. It FUNCTIONS_FOR or is PART_OF the system when the source identifies those lines, stations, trains or services as that system's own.",
    "Equipment, devices or systems installed on, fitted to or carried by a vehicle, train, track, station or other facility take that facility's membership. A system's trains, and vehicles that inspect or maintain the system's own track (for example track-maintenance vehicles working inside its track at night), FUNCTIONS_FOR or are PART_OF that system, and so does equipment installed on them. An operator's assets that do not run on or serve its rail system, such as buses, ferries or real estate, remain outside it.",
    "IN_SCOPE_SUPPORT requires a RESOLVED Candidate event, an ASSERTED action, an established AFFECTS or LOCATED_AT action-to-target relation, and an established BELONGS_TO, PART_OF or FUNCTIONS_FOR target-to-system relation to an eligible system.",
    "A location, operator identity alone, ownership identity, generic equipment word, or nearby station is not target-to-system membership; an operator's buses, ferries or real estate never become urban rail through the operator. Use BELONGS_TO, PART_OF, or FUNCTIONS_FOR for eligible membership; LOCATED_AT, OWNED_BY, and OPERATED_BY never establish target-to-system eligibility.",
    "Interpret source-grounded anaphora, demonstratives, possessives, component relationships, and cross-sentence grammatical references, including Japanese, Korean and French constructions. These may support a relationship only when the supplied source clearly connects the actual target to the system; preserve UNCERTAIN if the antecedent or relation remains ambiguous, and do not use outside knowledge.",
    "Interpret action-to-target independently from target eligibility: when the source clearly establishes an action affecting a target, mark action_target ESTABLISHED even if target_system is UNESTABLISHED or a supported noneligible relationship.",
    "noneligible_relation concerns only the Candidate focus action's own target or system. Do not record other actions reported in the same document, such as a bus pilot announced together with a metro service change. When status is ABSENT, noneligible_kind must be NONE. When status is PRESENT, its sentences must contain the target or system label, eligible_mode_family must be NON_ELIGIBLE or UNKNOWN, and kind must be EXCLUDED_TRANSPORT_MODE or NON_URBAN_RAIL. For a genuinely unresolved noneligible relationship, use UNRESOLVED status and kind.",
    "ambiguity concerns only whether the Candidate event is tied to an eligible system or which system it belongs to. Uncertainty about details that leave the system unchanged, such as whether an incident happened on the platform or on the train of the same subway, the exact time, or the cause, is NONE.",
    "Record noneligible, ambiguous, contradictory, negated, conditional, and unasserted events explicitly. event_status is NEGATED when the focus sentences state that the action did not or will not take place (for example 'no works have been announced on the line tonight' or 'trains run as normal'); such a statement is never an ASSERTED event. Use UNESTABLISHED or UNRESOLVED when evidence does not establish a relation; do not label uncertainty as an affirmative relation merely to fill a field.",
    "Do not force a positive proposal or output IN_SCOPE_SUPPORT to satisfy a benchmark. A complete citation is a necessary mechanical condition, not independent proof of a semantic relation.",
    "Do not search, browse, use tools, retrieve external knowledge, or return a ScopeResult or diagnostic.",
    "Return exactly one JSON object with the supplied schema, no extra fields and no prose outside JSON.",
)


MAIAGENT_SCOPE_RESPONSE_SCHEMA = SCOPE_SEMANTIC_RESPONSE_SCHEMA
SCOPE_RESPONSE_SCHEMA = MAIAGENT_SCOPE_RESPONSE_SCHEMA


@dataclass(frozen=True, slots=True)
class MaiAgentScopeProviderConfig:
    api_base: str
    api_key: str = field(repr=False)
    chatbot_id: str = field(repr=False)
    timeout_seconds: float = MAIAGENT_HELPER_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        values = (self.api_base, self.api_key, self.chatbot_id)
        if any(not isinstance(value, str) for value in values):
            raise ValueError("MaiAgent Scope configuration values must be strings")
        if any("\r" in value or "\n" in value for value in values):
            raise ValueError("MaiAgent Scope configuration contains invalid characters")
        try:
            parsed = urlsplit(self.api_base)
            hostname = parsed.hostname
            parsed.port
        except (TypeError, ValueError):
            raise ValueError("MaiAgent API base must be an absolute HTTPS origin") from None
        if parsed.scheme != "https" or not parsed.netloc or hostname is None or parsed.username is not None or parsed.password is not None or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("MaiAgent API base must be an absolute HTTPS origin")
        if not self.api_key.strip() or not self.chatbot_id.strip():
            raise ValueError("MaiAgent Scope API key and chatbot ID are required")
        if isinstance(self.timeout_seconds, bool) or not isinstance(self.timeout_seconds, (int, float)) or not math.isfinite(float(self.timeout_seconds)) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

    @property
    def completion_endpoint(self) -> str:
        return f"{self.api_base.rstrip('/')}/api/v1/chatbots/{quote(self.chatbot_id, safe='')}/completions/"

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None, *, timeout_seconds: float = MAIAGENT_HELPER_TIMEOUT_SECONDS, dotenv_path: str | os.PathLike[str] | None = None):
        values = load_shared_maiagent_values(environ, dotenv_path=dotenv_path)
        api_base, api_key, chatbot_id = (values.get(key) for key in ("MAIAGENT_API_BASE", "MAIAGENT_API_KEY", "MAIAGENT_STRUCTURED_HELPER_CHATBOT_ID"))
        if not all(isinstance(value, str) and value.strip() for value in (api_base, api_key, chatbot_id)):
            return None
        return cls(api_base.strip(), api_key.strip(), chatbot_id.strip(), timeout_seconds)


def build_maiagent_scope_model_input(request: ScopeSemanticRequest) -> dict[str, Any]:
    if not isinstance(request, ScopeSemanticRequest):
        raise TypeError("MaiAgent Scope input requires ScopeSemanticRequest")
    return {
        "task_identity": TASK_IDENTITY,
        "prompt_version": PROMPT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "helper_version": HELPER_VERSION,
        "instructions": list(SCOPE_SEMANTIC_INSTRUCTIONS),
        "scope_request": request.as_payload(),
        "authoritative_response_contract": {"schema_version": SCHEMA_VERSION, "json_schema": MAIAGENT_SCOPE_RESPONSE_SCHEMA},
    }


class MaiAgentScopeProviderFailure(RuntimeError):
    """Safe technical provider failure without provider-controlled details."""

    def __init__(self, message: str, *, failure_category: str = "PROVIDER_FAILURE") -> None:
        super().__init__(message)
        self.failure_category = failure_category


class MaiAgentScopeProposalProvider:
    def __init__(self, config: MaiAgentScopeProviderConfig, *, transport: MaiAgentJsonHttpTransport | None = None) -> None:
        if not isinstance(config, MaiAgentScopeProviderConfig):
            raise TypeError("MaiAgentScopeProposalProvider requires MaiAgentScopeProviderConfig")
        self._config = config
        self._transport = transport if transport is not None else UrllibMaiAgentJsonTransport()

    def __call__(self, request: ScopeSemanticRequest) -> object:
        if not isinstance(request, ScopeSemanticRequest):
            raise TypeError("MaiAgent Scope provider accepts only ScopeSemanticRequest")
        request_content = json.dumps(build_maiagent_scope_model_input(request), ensure_ascii=False, separators=(",", ":"))
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
            task="scope_semantic_proposal",
        )


MaiAgentScopeProvider = MaiAgentScopeProposalProvider
MaiAgentScopeAdapter = MaiAgentScopeProposalProvider
MaiAgentScopeFailure = MaiAgentScopeProviderFailure


def build_maiagent_scope_provider(config: MaiAgentScopeProviderConfig | None = None, *, transport: MaiAgentJsonHttpTransport | None = None, environ: Mapping[str, str] | None = None, timeout_seconds: float = MAIAGENT_HELPER_TIMEOUT_SECONDS, dotenv_path: str | os.PathLike[str] | None = None) -> MaiAgentScopeProposalProvider | None:
    resolved = config or MaiAgentScopeProviderConfig.from_environment(environ, timeout_seconds=timeout_seconds, dotenv_path=dotenv_path)
    return None if resolved is None else MaiAgentScopeProposalProvider(resolved, transport=transport)


build_maiagent_scope_proposal_provider = build_maiagent_scope_provider

__all__ = [
    "HELPER_VERSION", "MAIAGENT_SCOPE_PROVIDER_IDENTIFIER", "MAIAGENT_SCOPE_RESPONSE_SCHEMA", "MaiAgentScopeAdapter", "MaiAgentScopeFailure", "MaiAgentScopeProposalProvider", "MaiAgentScopeProvider", "MaiAgentScopeProviderConfig", "MaiAgentScopeProviderFailure", "PROMPT_VERSION", "PROVIDER_IDENTIFIER", "SCHEMA_VERSION", "SCOPE_HELPER_VERSION", "SCOPE_PROMPT_VERSION", "SCOPE_RESPONSE_SCHEMA", "SCOPE_SCHEMA_VERSION", "SCOPE_SEMANTIC_INSTRUCTIONS", "SCOPE_TASK_IDENTITY", "TASK_IDENTITY", "build_maiagent_scope_model_input", "build_maiagent_scope_proposal_provider", "build_maiagent_scope_provider",
]
