"""The sole production owner of Category decisions for post-dedup Event Groups."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from types import MappingProxyType
from typing import Any, Protocol

from .maiagent_transport import UNTRUSTED_SOURCE_TEXT_INSTRUCTION
from . import category_observation
from .source_refs import cited_spans, source_payload, source_refs
from .contracts import (
    CategoryPrincipalAction,
    ProposalContractViolation,
    SemanticProviderConfigurationFailure,
    SemanticProviderTechnicalFailure,
    CategoryId,
    CategoryResolutionReason,
    CategoryResult,
    CategoryState,
    EvidenceState,
    EventGroup,
    EventIdentityFacts,
    EventIdentityRecord,
    ScopeState,
)


_CATEGORY_GUIDANCE = (
    "Name the evidenced principal current action of this one Event Group by choosing exactly one principal_action from the closed list below. Python maps the chosen action to the Category with a fixed table; never name a Category.",
    "Return principal_action null with an unresolved_reason only when no single principal action can be chosen: CONFLICTING_CATEGORY_DEFINING_CLAIMS, NO_UNIQUE_PRINCIPAL_ACTION or INSUFFICIENT_CATEGORY_EVIDENCE (defined below). Otherwise unresolved_reason is null.",
    "Every proposal must include at least one citation grounded in supplied evidence.",
    "Each source has a source_ref (M1, M2, ...) and sentences with sentence_ids assigned by Python. Each citation names one supplied source_ref and the sentence_ids of that source that support the proposal. Citations support the proposal as a whole; do not label them support or conflict citations. Never copy or retype source text or identifiers into a citation.",
    "TECHNOLOGY_TRIAL_OR_DEPLOYMENT: research results, prototypes, pilots, experiments, applied tests, deployments and substantive development whose subject is a technology, method or material itself. Putting a technology, method or material into use is a deployment, also when it changes how maintenance, inspection or monitoring is done, or when it gives passengers an amenity on board or at stations such as Wi-Fi or mobile network coverage. A pilot or trial of a new technology, method or material on an operating line remains this action. A technology name, equipment mention, procurement object, supplier award or delivery alone is not this action.",
    "SERVICE_OPENING: a new line, extension, station or train fleet actually begins carrying passengers.",
    "SERVICE_OPENING_ANNOUNCEMENT: the news is the operator's or authority's announcement of when a new line, extension, station, route or train fleet will begin carrying passengers. Give announced_opening_date. A delay or postponement of an expected opening, or a new target date for it, is PROJECT_STEP, not this action.",
    "announced_opening_date: only with SERVICE_OPENING_ANNOUNCEMENT; null with every other action. It is the calendar date (YYYY-MM-DD) on which the evidence states passenger service will begin, when the evidence fixes one day: a stated calendar date, or a named day that fixes one date in a stated or evident year (for example the first Sunday of Advent, or the timetable change on 14 December). It is null when the evidence gives only a month, season, year or range, or calls the date provisional, a target, an estimate or uncertain. Cite the sentences that state the date. Python decides what the date means for the report; never judge that.",
    "SERVICE_CHANGE: a planned or announced change to the passenger transport service itself reported as the news: timetable, headway, fare or ticketing, operating hours, how the passenger service is operated, a planned closure or suspension (for example for engineering works) or the service notice announcing it, the closure of a rail section after an external safety risk to it was discovered (for example an old mineshaft found under the track), and the replacement transport (replacement buses or shuttles) arranged for such a planned or risk closure when that arrangement, its contract or its cost is the news. An unplanned suspension, closure or curtailment caused by a failure or an accident is always FAILURE_SERVICE_DISRUPTION, not this action, also when the evidence reports replacement buses or other substitute transport for it. Extra, added or extended trains or hours for an exam, holiday, festival, sports match, concert or other event are TEMPORARY_EVENT_SERVICE, not this action.",
    "TEMPORARY_EVENT_SERVICE: a temporary routine adjustment of a running service for an exam, holiday, festival, sports match, concert or other event: extra or added trains, extended operating hours, shortened headways or crowd guidance for that day or period. A lasting timetable change, a suspension or closure, and a strike or other labour action remain their own actions.",
    "OPERATIONAL_DISPUTE: an evidenced operational dispute about the passenger service or its operation, such as a strike or other industrial action, a lawsuit, arbitration or protest. A strike notice or threatened strike, a work-to-rule or slowdown, and the negotiations about them are this action.",
    "OPERATIONAL_GOVERNANCE: an operational governance action on a running passenger service by its operator or authority, including publishing a completed incident investigation or substantive safety-governance findings that establish no new normative rule. An investigation report is this action, not INCIDENT_OR_FAILURE, even though it discusses an earlier incident. Ticket inspections, fare-evasion checks, security or safety patrols and similar safety or security initiatives on the running service are this action.",
    "INCIDENT_OR_FAILURE: an actual urban-rail accident, unexpected failure, safety incident or cybersecurity incident. An actual passenger, staff or public safety incident in an in-scope urban-rail context remains this action even when injury is minor or no train, system, evacuation, service or project impact occurs. Smoke or fire on or from a station, platform, tunnel, track, train, power supply or other rail equipment itself is this action.",
    "FAILURE_SERVICE_DISRUPTION: the news is an unplanned suspension, closure, curtailment, shortened route or reduced service of a running line caused by a technical problem, failure, fault, breakdown, damage or accident in the rail system (for example trains running only on part of a line after a fault near a station). This action takes precedence over SERVICE_CHANGE: replacement buses, shuttles or other substitute transport reported for the disruption, and their cost, do not change the action. A planned closure, a closure after an external safety risk was discovered, and a service notice announced in advance are SERVICE_CHANGE.",
    "NETWORK_EQUIPMENT_INSPECTION: the operator or authority carries out a comprehensive inspection of the equipment or facilities of a whole running line or of the whole network (for example an all-line high-intensity inspection after a series of failures, or a network-wide special inspection before winter). A site visit, inspection tour or walk-through by executives, officials, council members or a board is EVENT_OR_EXHIBITION, and an inspection of construction works is PROJECT_STEP, not this action.",
    "EXTERNAL_HAZARD_PRECAUTION: a fire, smoke, gas leak or other hazard whose source is outside the rail facilities (for example a car park, a nearby building, a road vehicle or vegetation) and that did not reach or damage a station, platform, tunnel, track, train or power equipment, when the only rail consequence is a precautionary, brief suspension, diversion or station closure. When the hazard reached or damaged rail facilities, the action is INCIDENT_OR_FAILURE.",
    "FORMAL_PROCUREMENT_ACTION: a formal tender, bid invitation, supplier selection, award, exercised option or equivalent formal procurement action that has taken place, including innovative, first-of-kind, AI, CBTC, cybersecurity and pilot-purpose procurements. A planned, expected or future tender, selection or award is PROJECT_STEP. Its object is an urban rail system, equipment, vehicle, infrastructure or rail service; a contract for anything else is NON_RAIL_CONTRACT. A formal decision authorising a procurement before any tender or award is PROCUREMENT_AUTHORIZATION.",
    "SUPPLIER_SYSTEM_ENGAGEMENT: the evidence states that a named company has been engaged, contracted or commissioned to provide, supply, integrate or install an electrical and mechanical system or its equipment for an urban rail line or network (for example signalling or train control, communications or radio networks, power supply, rolling stock, platform screen doors, fare collection or depot equipment), also as a subcontractor within a larger project. A company's announcement only that it takes part in or supports a project, without naming a system it was engaged to provide, is PROJECT_STEP, not this action.",
    "PROCUREMENT_AUTHORIZATION: a formal decision or resolution of a government body or of the operator (for example a council of government, cabinet, city council or board) that authorises the contracting of an electrical and mechanical system or equipment for an urban rail line or network, such as approving the contract or launching its award procedure, before any tender or award has taken place. Give authorization_terms. A plan, intention or announcement to tender without such a formal decision is PROJECT_STEP, not this action.",
    "authorization_terms: only with PROCUREMENT_AUTHORIZATION; null with every other action. An object with amount, the authorised amount, and scope, the items or works to be procured, each copied character for character from one cited sentence that states it (for example amount '3,4 millones de euros' and scope 'sustituir 720 componentes de aire acondicionado'). It is null when the evidence does not state both the amount and the scope. Python decides what the terms mean for the report; never judge that.",
    "NON_RAIL_CONTRACT: a tender, award or contract whose object is not an urban rail system, equipment, vehicle, infrastructure or rail service, such as replacement buses, ferries, cleaning, catering, advertising or office services. When the news is a rail section closed as planned or after an external safety risk was discovered, and the replacement transport arranged for it, the action is SERVICE_CHANGE; when the section stopped because of a failure or an accident, it is FAILURE_SERVICE_DISRUPTION.",
    "ASSET_DISPOSAL: the sale, auction, scrapping, write-off or disposal of vehicles, equipment, property or other assets, including damaged or retired trains. It is not FORMAL_PROCUREMENT_ACTION.",
    "NORMATIVE_ACTION: a published or revised regulation, mandatory technical rule, standard, applicable formal guidance or operator-wide specification, or a formal draft or consultation procedure. A penalty or enforcement decision under an existing rule, a procurement-specific specification and a citation of an existing standard are not this action.",
    "PRE_SERVICE_OR_ACCEPTANCE_TEST: testing the installed vehicles or systems of a line, station or depot before its opening or for its acceptance, test runs before opening, and the clearance or gauge, compatibility (electromagnetic compatibility included), commissioning, type, acceptance or homologation tests of newly delivered vehicles or equipment before they enter passenger service, also on a network that is already running, even when the tested system is signalling, train control, communication or power equipment.",
    "PROJECT_STEP: a step or plan of building or opening a line, station or depot, or of a project before its service opens: groundbreaking, site preparation, construction stages and progress, track or equipment installation, inspections of works, approvals, funding or budget requests and decisions, cost increases, route or land decisions, demolition and relocation, announcements of expected future openings or tenders, changes to or forecasts of an expected opening date (delays, postponements, new target dates), and the reporting, publicity, staffing or management of such a project. Selection for a funding, development or demonstration programme, and an announcement that a technology will be developed, piloted or demonstrated when that work has not started, are PROJECT_STEP, not TECHNOLOGY_TRIAL_OR_DEPLOYMENT. When the evidence reports a project step and mentions how the service of a running line was affected by it, the action is still PROJECT_STEP. When the evidence states that a named company was engaged to provide an electrical and mechanical system for the project, the action is SUPPLIER_SYSTEM_ENGAGEMENT. A formal decision authorising an electrical and mechanical equipment procurement is PROCUREMENT_AUTHORIZATION.",
    "DRILL_OR_TRAINING: a drill, exercise, rehearsal or training session (emergency, fire, evacuation, rescue or safety drills included, whoever holds it and whatever equipment or facilities it uses), unless the evidence reports an actual incident of its own.",
    "NON_TRANSPORT_SERVICE: a facility or service at a station or on board that is not the passenger transport service, such as a shop, clinic, consultation booth or vending service, also when that facility uses a technology.",
    "STATISTICS_RANKING_OR_AWARD: ridership counts or records, statistics or report releases, rankings, awards and media praise.",
    "STATEMENT_OR_COMMENTARY: statements, criticisms, demands, questions, interviews and opinion about an action, feature or background articles that recount earlier actions, and ordinary passenger complaints, requests, feedback records or operator logs. An earlier action that such a document describes as background is not its current action.",
    "EVENT_OR_EXHIBITION: a meeting, exchange, conference, exhibition, ceremony, visit or presentation that uses, teaches, presents, exhibits or discusses a technology, service, procurement or rule but is not itself one of the actions above. A site visit, inspection tour or safety walk-through by executives, officials or a board (for example a chief executive's safety inspection of a depot before a holiday) is EVENT_OR_EXHIBITION, not OPERATIONAL_GOVERNANCE, unless the evidence reports a decision, service change or safety measure that it produced.",
    "RECOMMENDATION_WITHOUT_ADOPTION: the evidence establishes a recommendation, proposal or suggestion that no competent authority or operator adopted, and no other listed action controls the event.",
    "OTHER: any other principal action that none of the entries above describes.",
    "Choose the action the evidence reports as its news, not a consequence of it. A service change is the principal action only when the evidence reports the service change itself as its news.",
    "Severity and report value do not determine the action; they belong to downstream Reportability.",
    "CONFLICTING_CATEGORY_DEFINING_CLAIMS applies only when competing evidence disagrees about the action itself and the supplied evidence cannot resolve the disagreement. Differences only in duration, count, magnitude, exact timing or consequence extent are not such a conflict when the action stays the same.",
    "NO_UNIQUE_PRINCIPAL_ACTION applies when evidence consistently establishes several equal, independent listed actions and no unique principal action can be identified; sources need not contradict each other.",
    "INSUFFICIENT_CATEGORY_EVIDENCE applies when the supplied evidence is insufficient to determine what action occurred; it is distinct from evidence that positively establishes one of the listed actions, including OTHER.",
    "Do not rank actions, vote by keywords, infer from source order, or prefer a canonical source. Preserve each source and its claims separately.",
    "Subtype is optional descriptive metadata, may be null, and never changes the mapping. When present it matches the response schema pattern: lowercase snake_case that starts with a letter a-z, followed only by letters a-z, digits and underscores (spell out a leading number, for example fifth_generation_network_deployment, not 5g_network_deployment).",
    "Event identity is already decided. Do not merge or split Event Groups. Ignore discovery metadata, report period, taxonomy, and Reportability.",
    UNTRUSTED_SOURCE_TEXT_INSTRUCTION,
)


# RC-80 (section A.61): the Classifier's fixed table from the helper's
# principal action to the Category, or to the CATEGORY_UNRESOLVED reason. It is
# the only place an action becomes a Category; the helper never names one.
PRINCIPAL_ACTION_CATEGORY: Mapping[CategoryPrincipalAction, CategoryId | CategoryResolutionReason] = MappingProxyType(
    {
        CategoryPrincipalAction.TECHNOLOGY_TRIAL_OR_DEPLOYMENT: CategoryId.TECHNICAL_DEVELOPMENT,
        CategoryPrincipalAction.SERVICE_OPENING: CategoryId.OPERATIONAL_CHANGE,
        # RC-84: the outcome when the announced date is absent or outside the
        # window; opening_announcement_category applies the window rule.
        CategoryPrincipalAction.SERVICE_OPENING_ANNOUNCEMENT: CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION,
        CategoryPrincipalAction.SERVICE_CHANGE: CategoryId.OPERATIONAL_CHANGE,
        CategoryPrincipalAction.TEMPORARY_EVENT_SERVICE: CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION,
        CategoryPrincipalAction.OPERATIONAL_DISPUTE: CategoryId.OPERATIONAL_CHANGE,
        CategoryPrincipalAction.OPERATIONAL_GOVERNANCE: CategoryId.OPERATIONAL_CHANGE,
        CategoryPrincipalAction.INCIDENT_OR_FAILURE: CategoryId.INCIDENT,
        # RC-86 (section A.67, user decisions 2026-11-25).
        CategoryPrincipalAction.FAILURE_SERVICE_DISRUPTION: CategoryId.INCIDENT,
        CategoryPrincipalAction.NETWORK_EQUIPMENT_INSPECTION: CategoryId.OPERATIONAL_CHANGE,
        CategoryPrincipalAction.EXTERNAL_HAZARD_PRECAUTION: CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION,
        CategoryPrincipalAction.FORMAL_PROCUREMENT_ACTION: CategoryId.PROCUREMENT,
        CategoryPrincipalAction.SUPPLIER_SYSTEM_ENGAGEMENT: CategoryId.PROCUREMENT,
        # RC-86: the outcome when the amount or scope is not stated;
        # procurement_authorization_category applies the terms rule.
        CategoryPrincipalAction.PROCUREMENT_AUTHORIZATION: CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION,
        CategoryPrincipalAction.NON_RAIL_CONTRACT: CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION,
        CategoryPrincipalAction.ASSET_DISPOSAL: CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION,
        CategoryPrincipalAction.NORMATIVE_ACTION: CategoryId.NORMATIVE_CHANGE,
        CategoryPrincipalAction.PRE_SERVICE_OR_ACCEPTANCE_TEST: CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION,
        CategoryPrincipalAction.PROJECT_STEP: CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION,
        CategoryPrincipalAction.DRILL_OR_TRAINING: CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION,
        CategoryPrincipalAction.NON_TRANSPORT_SERVICE: CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION,
        CategoryPrincipalAction.STATISTICS_RANKING_OR_AWARD: CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION,
        CategoryPrincipalAction.STATEMENT_OR_COMMENTARY: CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION,
        CategoryPrincipalAction.EVENT_OR_EXHIBITION: CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION,
        CategoryPrincipalAction.OTHER: CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION,
        CategoryPrincipalAction.RECOMMENDATION_WITHOUT_ADOPTION: CategoryResolutionReason.RECOMMENDATION_WITHOUT_ADOPTED_ACTION,
    }
)
if set(PRINCIPAL_ACTION_CATEGORY) != set(CategoryPrincipalAction):  # pragma: no cover - import-time invariant
    raise RuntimeError("every principal action needs exactly one mapping")
# RC-84 (section A.65): an announced opening is an operations event only when
# its announced date lies within the report period or at most this many days
# after its end. Python computes it; the helper only extracts the date.
OPENING_ANNOUNCEMENT_WINDOW_DAYS = 30


def opening_announcement_category(
    announced_opening_date: date | None,
    report_period: tuple[date, date] | None,
) -> CategoryId | CategoryResolutionReason:
    """The Category of a SERVICE_OPENING_ANNOUNCEMENT (RC-84), decided by date arithmetic only."""

    if announced_opening_date is None or report_period is None:
        return CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION
    start, end = report_period
    if start <= announced_opening_date <= end + timedelta(days=OPENING_ANNOUNCEMENT_WINDOW_DAYS):
        return CategoryId.OPERATIONAL_CHANGE
    return CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION


def procurement_authorization_category(terms_stated: bool) -> CategoryId | CategoryResolutionReason:
    """The Category of a PROCUREMENT_AUTHORIZATION (RC-86), decided by Python only.

    A formal authorisation is a procurement event only when the evidence states
    both the authorised amount and the procurement scope, verified by Python
    as exact text of a cited sentence (``_authorization_terms``).
    """

    return CategoryId.PROCUREMENT if terms_stated else CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION


# Reasons the helper may give instead of an action (no single action can be chosen).
UNRESOLVED_PROPOSAL_REASONS = frozenset(
    {
        CategoryResolutionReason.CONFLICTING_CATEGORY_DEFINING_CLAIMS,
        CategoryResolutionReason.NO_UNIQUE_PRINCIPAL_ACTION,
        CategoryResolutionReason.INSUFFICIENT_CATEGORY_EVIDENCE,
    }
)


@dataclass(frozen=True, slots=True)
class CategorySourceEvidence:
    """One source's principal body and evidence-backed action facts."""

    candidate_id: str
    substantive_content: str
    action_facts: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not self.candidate_id:
            raise ValueError("Category source requires candidate_id")
        if not self.substantive_content.strip():
            raise ValueError("Category source requires substantive content")
        if not isinstance(self.action_facts, Mapping):
            raise TypeError("action_facts must be a mapping")
        object.__setattr__(self, "action_facts", MappingProxyType(dict(self.action_facts)))

    def as_mapping(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "substantive_content": self.substantive_content,
            "action_facts": dict(self.action_facts),
        }


@dataclass(frozen=True, slots=True)
class CategorySemanticRequest:
    """Bounded, source-preserving input for the Classifier's semantic helper.

    Candidate search metadata and canonical-source preference are deliberately
    absent. Sources are presented as Python-assigned references (RC-16); a
    reference is a citation handle, not rank or priority.
    """

    sources: tuple[CategorySourceEvidence, ...]
    unresolved_claims: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = ()

    def __post_init__(self) -> None:
        ids = tuple(source.candidate_id for source in self.sources)
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("Category request requires unique source candidate IDs")
        if ids != tuple(sorted(ids)):
            raise ValueError("Category request sources must be in stable ID order")

    @property
    def source_refs(self) -> dict[str, str]:
        return source_refs(tuple(source.candidate_id for source in self.sources))

    def as_payload(self) -> dict[str, Any]:
        ref_of = {candidate_id: ref for ref, candidate_id in self.source_refs.items()}
        return {
            "contract_reference": "docs/ARCHITECTURE_CONTRACT.md §L, §A.10",
            "guidance": list(_CATEGORY_GUIDANCE),
            "source_order_is_authoritative": False,
            "sources": [
                {
                    **source_payload(ref_of[source.candidate_id], source.substantive_content),
                    "action_facts": dict(source.action_facts),
                }
                for source in self.sources
            ],
            "unresolved_event_claims": [
                {
                    "claim_key": claim_key,
                    "source_values": [
                        {"source_ref": ref_of[candidate_id], "value": value}
                        for candidate_id, value in candidate_values
                    ],
                }
                for claim_key, candidate_values in self.unresolved_claims
            ],
        }


@dataclass(frozen=True, slots=True)
class CategoryEvidenceSpan:
    """Classifier-canonicalized citation span into one supplied source body."""

    candidate_id: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class CategoryCitation:
    """An untrusted source reference and sentence IDs from a Category proposal."""

    source_ref: str
    sentence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CategorySemanticResponse:
    """Untrusted structured helper response (RC-80); Classifier validates and maps it."""

    principal_action: CategoryPrincipalAction | str | None = None
    unresolved_reason: CategoryResolutionReason | str | None = None
    subtype: str | None = None
    citations: tuple[CategoryCitation, ...] = ()
    # RC-84: ISO date string, only with SERVICE_OPENING_ANNOUNCEMENT.
    announced_opening_date: str | None = None
    # RC-86: {"amount": ..., "scope": ...}, only with PROCUREMENT_AUTHORIZATION.
    authorization_terms: Mapping[str, str] | None = None


@dataclass(frozen=True, slots=True)
class CategorySemanticHelperResult:
    """A proposal plus non-decision provider metadata for Classifier tracing."""

    proposal: object
    provenance: Mapping[str, str]

    def __post_init__(self) -> None:
        if not isinstance(self.provenance, Mapping):
            raise TypeError("helper provenance must be a mapping")
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))


class CategorySemanticHelper(Protocol):
    """Advisory no-search helper; it does not own the Category decision."""

    def __call__(self, request: CategorySemanticRequest) -> object:
        """Return a structured proposal based only on the supplied request."""


class InvalidCategorySemanticResponse(ValueError):
    """Raised when a semantic proposal fails the Classifier response contract."""

    def __init__(
        self,
        message: str,
        *,
        provenance: Mapping[str, str] | None = None,
        predicate: str | None = None,
    ) -> None:
        super().__init__(message)
        self.provenance = MappingProxyType(dict(provenance or {}))
        # Observation only (RC-66): the contract predicate that failed. It
        # names the gap in the TechnicalGap signature and decides nothing.
        self.predicate = predicate


class CategoryProposalViolation(ProposalContractViolation):
    """A Category proposal the owner cannot validate (RC-16).

    It isolates the EventGroup as a disclosed technical gap; it is never
    ``CATEGORY_UNRESOLVED``, which is reserved for domain reasons.
    """

    def __init__(self, message: str, predicate: str | None = None) -> None:
        super().__init__(message)
        if predicate is None:
            predicate = "CITATION_INVALID" if "citation" in message else "PROPOSAL_INVALID"
        self.failure_class = predicate


@dataclass(frozen=True, slots=True)
class _ValidatedCategoryResponse:
    principal_action: CategoryPrincipalAction | None
    category_state: CategoryState
    primary_category_id: CategoryId | None
    subtype: str | None
    category_resolution_reason: CategoryResolutionReason | None
    citation_spans: tuple[CategoryEvidenceSpan, ...]
    announced_opening_date: date | None = None
    opening_window: str | None = None
    authorization_terms: str | None = None


_RESPONSE_FIELDS = frozenset(
    {"principal_action", "unresolved_reason", "subtype", "announced_opening_date", "authorization_terms", "citations"}
)
_AUTHORIZATION_TERM_FIELDS = frozenset({"amount", "scope"})
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_CITATION_FIELDS = frozenset({"source_ref", "sentence_ids"})
_DOMAIN_UNRESOLVED_REASONS = frozenset(
    {
        CategoryResolutionReason.NO_CATEGORY_DEFINING_ACTION,
        CategoryResolutionReason.RECOMMENDATION_WITHOUT_ADOPTED_ACTION,
        CategoryResolutionReason.CONFLICTING_CATEGORY_DEFINING_CLAIMS,
        CategoryResolutionReason.NO_UNIQUE_PRINCIPAL_ACTION,
        CategoryResolutionReason.INSUFFICIENT_CATEGORY_EVIDENCE,
    }
)


def _citation_from_value(value: object) -> CategoryCitation:
    if isinstance(value, CategoryCitation):
        source_ref, sentence_ids = value.source_ref, value.sentence_ids
    else:
        if not isinstance(value, Mapping) or frozenset(value) != _CITATION_FIELDS:
            raise InvalidCategorySemanticResponse("citation fields do not match schema")
        source_ref = value["source_ref"]
        sentence_ids = value["sentence_ids"]
    if not isinstance(source_ref, str) or not source_ref:
        raise InvalidCategorySemanticResponse("citation source_ref must be a string")
    if not isinstance(sentence_ids, (list, tuple)):
        raise InvalidCategorySemanticResponse("citation sentence_ids must be an array")
    return CategoryCitation(source_ref, tuple(sentence_ids))


def _parse_citations(
    value: object,
    request: CategorySemanticRequest,
) -> tuple[CategoryEvidenceSpan, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise InvalidCategorySemanticResponse("citations must be an array")
    source_text = {source.candidate_id: source.substantive_content for source in request.sources}
    refs = request.source_refs
    spans: list[CategoryEvidenceSpan] = []
    for raw_citation in value:
        citation = _citation_from_value(raw_citation)
        candidate_id = refs.get(citation.source_ref)
        if candidate_id is None:
            raise InvalidCategorySemanticResponse("citation references an unknown source")
        resolved = cited_spans(source_text[candidate_id], citation.sentence_ids)
        if resolved is None:
            raise InvalidCategorySemanticResponse("citation sentence_ids do not resolve in the source")
        for start, end in resolved:
            span = CategoryEvidenceSpan(candidate_id, start, end)
            if span not in spans:
                spans.append(span)
    return tuple(spans)


def _announced_date(raw: object, action: CategoryPrincipalAction | None) -> date | None:
    if raw is None:
        return None
    if action is not CategoryPrincipalAction.SERVICE_OPENING_ANNOUNCEMENT:
        raise InvalidCategorySemanticResponse(
            "announced_opening_date is only given with SERVICE_OPENING_ANNOUNCEMENT", predicate="OPENING_DATE"
        )
    if not isinstance(raw, str) or not _ISO_DATE.fullmatch(raw):
        raise InvalidCategorySemanticResponse("announced_opening_date must be YYYY-MM-DD", predicate="OPENING_DATE")
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise InvalidCategorySemanticResponse("announced_opening_date is not a calendar date", predicate="OPENING_DATE") from exc


def _authorization_terms(
    raw: object,
    action: CategoryPrincipalAction | None,
    request: CategorySemanticRequest,
    spans: tuple[CategoryEvidenceSpan, ...],
) -> str | None:
    """RC-86: ``STATED`` or ``NOT_STATED`` for a PROCUREMENT_AUTHORIZATION, else None.

    Each term must be non-empty text that occurs exactly as written in one
    cited sentence, and the amount must contain a digit; anything else is a
    proposal contract violation (``AUTHORIZATION_TERMS``), never a Category.
    """

    if raw is None:
        return "NOT_STATED" if action is CategoryPrincipalAction.PROCUREMENT_AUTHORIZATION else None
    if action is not CategoryPrincipalAction.PROCUREMENT_AUTHORIZATION:
        raise InvalidCategorySemanticResponse(
            "authorization_terms are only given with PROCUREMENT_AUTHORIZATION", predicate="AUTHORIZATION_TERMS"
        )
    if not isinstance(raw, Mapping) or frozenset(raw) != _AUTHORIZATION_TERM_FIELDS:
        raise InvalidCategorySemanticResponse("authorization_terms fields do not match schema", predicate="AUTHORIZATION_TERMS")
    text = {source.candidate_id: source.substantive_content for source in request.sources}
    cited = [text[span.candidate_id][span.start:span.end] for span in spans]
    for key in ("amount", "scope"):
        value = raw[key]
        if not isinstance(value, str) or not value.strip():
            raise InvalidCategorySemanticResponse(f"authorization_terms.{key} must be text", predicate="AUTHORIZATION_TERMS")
        if not any(value in sentence for sentence in cited):
            raise InvalidCategorySemanticResponse(
                f"authorization_terms.{key} is not text of a cited sentence", predicate="AUTHORIZATION_TERMS"
            )
    if not any(character.isdigit() for character in raw["amount"]):
        raise InvalidCategorySemanticResponse("authorization_terms.amount states no number", predicate="AUTHORIZATION_TERMS")
    return "STATED"


def _validate_response(
    raw_response: object,
    request: CategorySemanticRequest,
    report_period: tuple[date, date] | None = None,
) -> _ValidatedCategoryResponse:
    if isinstance(raw_response, CategorySemanticResponse):
        payload = {
            "principal_action": raw_response.principal_action,
            "unresolved_reason": raw_response.unresolved_reason,
            "subtype": raw_response.subtype,
            "announced_opening_date": raw_response.announced_opening_date,
            "authorization_terms": raw_response.authorization_terms,
            "citations": raw_response.citations,
        }
    elif isinstance(raw_response, Mapping):
        payload = raw_response
    else:
        raise InvalidCategorySemanticResponse("response must be an object", predicate="RESPONSE_SHAPE")

    if frozenset(payload) != _RESPONSE_FIELDS:
        raise InvalidCategorySemanticResponse("response fields do not match schema", predicate="RESPONSE_SHAPE")
    raw_action, raw_reason = payload["principal_action"], payload["unresolved_reason"]
    if (raw_action is None) == (raw_reason is None):
        raise InvalidCategorySemanticResponse(
            "exactly one of principal_action and unresolved_reason is required", predicate="ACTION_OR_REASON"
        )
    action: CategoryPrincipalAction | None = None
    if raw_action is not None:
        try:
            action = CategoryPrincipalAction(raw_action)
        except (TypeError, ValueError) as exc:
            raise InvalidCategorySemanticResponse("invalid principal_action", predicate="PRINCIPAL_ACTION") from exc
        mapped = PRINCIPAL_ACTION_CATEGORY[action]
    else:
        try:
            mapped = CategoryResolutionReason(raw_reason)
        except (TypeError, ValueError) as exc:
            raise InvalidCategorySemanticResponse("invalid unresolved_reason", predicate="RESOLUTION_REASON") from exc
        if mapped not in UNRESOLVED_PROPOSAL_REASONS:
            raise InvalidCategorySemanticResponse(
                "unresolved_reason must say why no single action can be chosen", predicate="RESOLUTION_REASON"
            )

    subtype = payload["subtype"]
    if subtype is not None and (not isinstance(subtype, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", subtype)):
        raise InvalidCategorySemanticResponse("subtype must be snake_case when present", predicate="SUBTYPE_FORMAT")
    announced = _announced_date(payload["announced_opening_date"], action)
    window = None
    if action is CategoryPrincipalAction.SERVICE_OPENING_ANNOUNCEMENT:
        # RC-84: the helper only extracted the date; the window is Python's.
        mapped = opening_announcement_category(announced, report_period)
        window = (
            "NO_DATE" if announced is None
            else "NO_PERIOD" if report_period is None
            else "WITHIN" if isinstance(mapped, CategoryId)
            else "OUTSIDE"
        )

    citation_spans = _parse_citations(payload["citations"], request)
    if not citation_spans:
        raise InvalidCategorySemanticResponse("a semantic outcome requires at least one citation")
    terms = _authorization_terms(payload["authorization_terms"], action, request, citation_spans)
    if action is CategoryPrincipalAction.PROCUREMENT_AUTHORIZATION:
        # RC-86: the helper only copied the terms; the Category is Python's.
        mapped = procurement_authorization_category(terms == "STATED")

    if isinstance(mapped, CategoryId):
        return _ValidatedCategoryResponse(
            action, CategoryState.CATEGORY_ASSIGNED, mapped, subtype, None, citation_spans, announced, window, terms
        )
    # Subtype describes a Category; an unresolved outcome has none to describe.
    return _ValidatedCategoryResponse(
        action, CategoryState.CATEGORY_UNRESOLVED, None, None, mapped, citation_spans, announced, window, terms
    )


def _action_facts(facts: EventIdentityFacts | None) -> dict[str, Any]:
    if facts is None:
        return {}
    values: dict[str, Any] = {}
    for key in (
        "action",
        "lifecycle_step",
        "subject",
        "asset",
        "project",
        "package",
        "location",
        "occurrence_context",
    ):
        value = getattr(facts, key)
        if value.strip():
            values[key] = value
    if facts.non_identity_claims:
        values["source_claims"] = dict(sorted(facts.non_identity_claims.items()))
    return values


def _request_for(
    event_group: EventGroup,
    records: Sequence[EventIdentityRecord],
) -> CategorySemanticRequest:
    record_by_id: dict[str, EventIdentityRecord] = {}
    for record in records:
        if not isinstance(record, EventIdentityRecord):
            raise TypeError("Classifier requires EventIdentityRecord inputs")
        candidate_id = record.candidate.candidate_id
        if candidate_id in record_by_id:
            raise ValueError("Event Group records must have unique candidate IDs")
        record_by_id[candidate_id] = record

    if set(record_by_id) != set(event_group.member_candidate_ids):
        raise ValueError("records must match exactly the Event Group members")

    sources: list[CategorySourceEvidence] = []
    for candidate_id in sorted(event_group.member_candidate_ids):
        record = record_by_id[candidate_id]
        if record.evidence.state is not EvidenceState.READY:
            raise ValueError("Classifier requires EVIDENCE_READY for every Event Group member")
        if record.scope.state is not ScopeState.IN_SCOPE:
            raise ValueError("Classifier requires IN_SCOPE for every Event Group member")
        if not record.temporal.date_valid:
            raise ValueError("Classifier requires DATE_VALID for every Event Group member")
        sources.append(
            CategorySourceEvidence(
                candidate_id=candidate_id,
                substantive_content=record.evidence.substantive_content,
                action_facts=_action_facts(record.evidence.identity_facts),
            )
        )

    unresolved_claims = tuple(
        sorted(
            (
                claim.claim_key,
                tuple(sorted(claim.candidate_values)),
            )
            for claim in event_group.unresolved_claims
        )
    )
    return CategorySemanticRequest(tuple(sources), unresolved_claims)


def _span_provenance(spans: tuple[CategoryEvidenceSpan, ...]) -> list[dict[str, Any]]:
    return [
        {"candidate_id": span.candidate_id, "start": span.start, "end": span.end}
        for span in spans
    ]


def _proposal_payload(raw_response: object) -> Mapping[str, Any] | None:
    """The helper's proposal as returned, for observation only (RC-69)."""

    if isinstance(raw_response, CategorySemanticResponse):
        return {
            "principal_action": raw_response.principal_action,
            "unresolved_reason": raw_response.unresolved_reason,
            "subtype": raw_response.subtype,
            "announced_opening_date": raw_response.announced_opening_date,
            "authorization_terms": raw_response.authorization_terms,
            "citations": raw_response.citations,
        }
    if isinstance(raw_response, Mapping):
        return raw_response
    return None


def _observe(request: CategorySemanticRequest, outcome: str, **details: Any) -> dict[str, Any]:
    """RC-69 observer record; built after the decision is fixed, never raises."""

    try:
        return category_observation.observe_category_exchange(request, outcome=outcome, **details)
    except Exception:
        return category_observation.unavailable_category_exchange()


def _provider_provenance(value: object) -> dict[str, str]:
    allowed = {
        "provider_identifier",
        "model_identifier",
        "prompt_version",
        "schema_version",
        "helper_version",
    }
    if not isinstance(value, Mapping):
        return {}
    return {
        key: item
        for key, item in value.items()
        if key in allowed and isinstance(key, str) and isinstance(item, str)
    }


class Classifier:
    """Sole authoritative owner of Category for an eligible Event Group.

    The injected semantic helper proposes a structured interpretation of the
    supplied source evidence. This class validates the proposal and owns the
    terminal state. A proposal it cannot validate raises
    :class:`CategoryProposalViolation`, a disclosed technical gap (RC-16).
    """

    def __init__(self, semantic_helper: CategorySemanticHelper | None = None) -> None:
        self._semantic_helper = semantic_helper

    def classify(
        self,
        event_group: EventGroup,
        records: Sequence[EventIdentityRecord],
        *,
        report_period: tuple[date, date] | None = None,
    ) -> CategoryResult:
        """Classify exactly one already-grouped Event Group without external I/O.

        ``report_period`` (start, end) is the run's report period; only the
        RC-84 opening-announcement window reads it.
        """

        request = _request_for(event_group, records)
        if self._semantic_helper is None:
            return self._unresolved(
                event_group,
                CategoryResolutionReason.SEMANTIC_HELPER_UNAVAILABLE,
                {
                    "decision_basis": "semantic_helper_unavailable",
                    "semantic_exchange": _observe(
                        request,
                        category_observation.OUTCOME_NO_PROPOSAL,
                        category_result_state=CategoryState.CATEGORY_UNRESOLVED.value,
                    ),
                },
            )

        try:
            helper_result = self._semantic_helper(request)
        except (SemanticProviderTechnicalFailure, SemanticProviderConfigurationFailure) as failure:
            # RC-6: never converted into CATEGORY_UNRESOLVED.  RC-69: the same
            # exception object is re-raised; the observer record only rides on it.
            category_observation.attach_category_exchange(
                failure, _observe(request, category_observation.OUTCOME_NO_PROPOSAL)
            )
            raise
        except InvalidCategorySemanticResponse as exc:
            violation = CategoryProposalViolation(str(exc), exc.predicate)
            category_observation.attach_category_exchange(
                violation,
                _observe(
                    request,
                    category_observation.OUTCOME_REJECTED,
                    provider_provenance=exc.provenance,
                    predicate=violation.failure_class,
                ),
            )
        except Exception as exc:
            return self._unresolved(
                event_group,
                CategoryResolutionReason.SEMANTIC_HELPER_FAILURE,
                {
                    "decision_basis": "semantic_helper_failure",
                    "helper_error_type": type(exc).__name__,
                    **_provider_provenance(getattr(exc, "provenance", None)),
                    "semantic_exchange": _observe(
                        request,
                        category_observation.OUTCOME_NO_PROPOSAL,
                        provider_provenance=_provider_provenance(getattr(exc, "provenance", None)),
                        category_result_state=CategoryState.CATEGORY_UNRESOLVED.value,
                    ),
                },
            )
        else:
            violation = None
        if violation is not None:
            # Raised outside the handler: no provider-controlled context.
            raise violation

        helper_provenance: dict[str, str] = {}
        raw_response = helper_result
        if isinstance(helper_result, CategorySemanticHelperResult):
            raw_response = helper_result.proposal
            helper_provenance = _provider_provenance(helper_result.provenance)

        try:
            response = _validate_response(raw_response, request, report_period)
        except InvalidCategorySemanticResponse as exc:
            violation = CategoryProposalViolation(str(exc), exc.predicate)
        else:
            violation = None
        if violation is not None:
            category_observation.attach_category_exchange(
                violation,
                _observe(
                    request,
                    category_observation.OUTCOME_REJECTED,
                    proposal_payload=_proposal_payload(raw_response),
                    provider_provenance=helper_provenance,
                    predicate=violation.failure_class,
                ),
            )
            raise violation

        provenance = {
            "decision_basis": "constrained_semantic_helper",
            # RC-80: the helper's principal action; the Category comes from
            # PRINCIPAL_ACTION_CATEGORY, not from the helper.
            "principal_action": response.principal_action.value if response.principal_action else None,
            **(
                {
                    # RC-84: the extracted date and Python's window result.
                    "announced_opening_date": (
                        response.announced_opening_date.isoformat() if response.announced_opening_date else None
                    ),
                    "opening_window": response.opening_window,
                }
                if response.principal_action is CategoryPrincipalAction.SERVICE_OPENING_ANNOUNCEMENT
                else {}
            ),
            # RC-86: whether Python verified the stated amount and scope (no source text).
            **(
                {"authorization_terms": response.authorization_terms}
                if response.principal_action is CategoryPrincipalAction.PROCUREMENT_AUTHORIZATION
                else {}
            ),
            "source_candidate_ids": [source.candidate_id for source in request.sources],
            # Kept as the stable internal provenance key. Under proposal v4 it
            # means whole-proposal citations, with no support/conflict role split.
            "validated_support_spans": _span_provenance(response.citation_spans),
            **helper_provenance,
            # RC-69, observation only: read by the selection audit, never by an owner.
            "semantic_exchange": _observe(
                request,
                category_observation.OUTCOME_ACCEPTED,
                proposal_payload=_proposal_payload(raw_response),
                provider_provenance=helper_provenance,
                category_result_state=response.category_state.value,
            ),
        }
        if response.category_state is CategoryState.CATEGORY_UNRESOLVED:
            return self._unresolved(
                event_group,
                response.category_resolution_reason,
                provenance,
            )

        category_id = response.primary_category_id
        if category_id is None:
            violation = CategoryProposalViolation("assigned response requires a Category ID")
            category_observation.attach_category_exchange(
                violation,
                _observe(
                    request,
                    category_observation.OUTCOME_REJECTED,
                    proposal_payload=_proposal_payload(raw_response),
                    provider_provenance=helper_provenance,
                    predicate=violation.failure_class,
                ),
            )
            raise violation
        return CategoryResult(
            category_state=CategoryState.CATEGORY_ASSIGNED,
            event_id=event_group.event_id,
            primary_category_id=category_id,
            primary_category=category_id.display_label,
            subtype=response.subtype,
            classification_reason=f"PRINCIPAL_ACTION_{category_id.value}",
            provenance=provenance,
        )

    evaluate = classify

    @staticmethod
    def _unresolved(
        event_group: EventGroup,
        reason: CategoryResolutionReason,
        provenance: Mapping[str, Any],
    ) -> CategoryResult:
        return CategoryResult(
            category_state=CategoryState.CATEGORY_UNRESOLVED,
            event_id=event_group.event_id,
            classification_reason=CategoryState.CATEGORY_UNRESOLVED.value,
            category_resolution_reason=reason,
            provenance=provenance,
        )
