"""Candidate-stage Scope owner.

The deterministic path in this module is intentionally bounded.  It builds a
small event relation from authoritative source text (action, affected target,
eligible system, and the link between them); vocabulary alone never produces
an ``IN_SCOPE`` result.  The optional helper remains a non-authoritative
proposal path with the original validation and failure semantics.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
import re
from typing import Any, Protocol

from .contracts import (
    EvidenceResult,
    EvidenceState,
    ScopeDiagnostic,
    ScopeResult,
    ScopeState,
)


class ScopeSemanticSupport(StrEnum):
    """Non-authoritative relation returned by an optional Scope helper."""

    IN_SCOPE_SUPPORT = "IN_SCOPE_SUPPORT"
    OUT_OF_SCOPE_SUPPORT = "OUT_OF_SCOPE_SUPPORT"
    UNCERTAIN = "UNCERTAIN"


@dataclass(frozen=True, slots=True)
class ScopeSupportSpan:
    """A helper citation into the supplied principal content."""

    start: int
    end: int


@dataclass(frozen=True, slots=True)
class ScopeSemanticRequest:
    """The complete bounded input available to a Scope semantic helper."""

    candidate_id: str
    candidate_title: str
    principal_content: str
    source_metadata: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ScopeSemanticResponse:
    """Validated-shape response supplied by a constrained helper."""

    support: ScopeSemanticSupport | str
    support_spans: tuple[ScopeSupportSpan, ...] = ()
    diagnostic: ScopeDiagnostic = ScopeDiagnostic.SCOPE_NOT_ESTABLISHED


class ScopeSemanticHelper(Protocol):
    """A non-authoritative, no-I/O semantic interpretation helper."""

    def __call__(
        self, request: ScopeSemanticRequest
    ) -> ScopeSemanticResponse | Mapping[str, Any] | object:
        ...


# These finite lexical front-ends only identify candidates for the relation
# parser.  They are never sufficient to produce IN_SCOPE by themselves.
_ELIGIBLE_MODE_PATTERN = (
    r"metro|mrt|subway|light\s+rail|tram|streetcar|urban[- ]rail|agt|"
    r"automated\s+guideway\s+transit|monorail|people[- ]mover|métro"
)
_ELIGIBLE_MODE = re.compile(
    rf"(?<![\w-])(?:{_ELIGIBLE_MODE_PATTERN})(?![\w-])", re.IGNORECASE
)
_JAPANESE_MODE = re.compile(r"地下鉄|都市鉄道")
_EXCLUDED_MODE = re.compile(
    r"\b(?:funicular|cable\s+rail(?:way)?|cable-hauled|"
    r"conventional\s+(?:mainline\s+)?airport\s+express|"
    r"mainline\s+airport\s+express)\b",
    re.IGNORECASE,
)
_NON_URBAN = re.compile(
    r"\b(?:bus(?:es)?|electric\s+buses?|aircraft|airline|aviation|"
    r"intercity|high[- ]speed|commuter|suburban|regional|mainline|"
    r"conventional|rolling\s+stock)\b",
    re.IGNORECASE,
)
_NON_URBAN_JP = re.compile(r"バス|航空|飛行機|高速鉄道|都市間")
_EXCLUDED_JP = re.compile(r"ケーブル|鋼索|ケーブルカー")
_EQUIPMENT = re.compile(
    r"\b(?:system|equipment|controller|module|infrastructure|facility|"
    r"facilities|signall?ing|signal|platform\s+doors?|charging\s+stations?|"
    r"control\s+(?:module|system|zone)|monitoring|traction|guidance|"
    r"doors?|route|line|network|segment|portion|station|système|"
    r"signalisation|équipement|infrastructure)\b",
    re.IGNORECASE,
)
_EQUIPMENT_JP = re.compile(r"設備|装置|機器|システム|ホームドア|信号|充電")
_JP_SYSTEM_COMPONENT = re.compile(r"駅|ホーム|路線|線|信号|車両|運行|列車|軌道|停車|プラットフォーム")
_ACTION = re.compile(
    r"\b(?:install(?:ed|s|ation)?|commission(?:ed|s)?|upgrade(?:d|s)?|"
    r"open(?:ed|s|ing)?|deploy(?:ed|s|ment)?|pilot(?:ed|s|ing)?|"
    r"replace(?:d|s|ment)?|add(?:ed|s|ing)?|introduc(?:e|ed|es|ing)|"
    r"implement(?:ed|s|ation)?|construct(?:ed|s|ion)?|"
    r"launch(?:ed|es|ing)?|complete(?:d|s|ion)?|test(?:ed|s|ing)?|"
    r"renew(?:ed|s|al)?|retrofit(?:ted|s|ting)?|receive(?:d|s)?|"
    r"deliver(?:ed|s)?|award(?:ed|s)?|moderni[sz](?:ed|ation)|"
    r"build(?:ing|t|s)?|commissioning|renewal|replacement|deployment|"
    r"installation|upgrade|construction|testing)\b|"
    r"\b(?:installé|installés|renouvelé|renouvelés|déployé|déployés|"
    r"remplacé|remplacés|modernisé|introduit|mis\s+en\s+service)\b|"
    r"(?:導入|設置|更新|改修|運用開始|発表|試験|建設|交換)",
    re.IGNORECASE,
)
_UNRESOLVED = re.compile(
    r"(?:does\s+not\s+identify\s+whether|does\s+not\s+identify\s+which|"
    r"does\s+not\s+establish\s+(?:which|whether)|cannot\s+identify|"
    r"cannot\s+be\s+resolved|cannot\s+be\s+reliably\s+isolated|"
    r"does\s+not\s+say\s+whether|does\s+not\s+(?:tie|link|associate|attribute)\b|"
    r"shared\s+(?:corridor|control)|unclear\s+whether)",
    re.IGNORECASE,
)
_ONLY_NON_URBAN = re.compile(
    r"(?:\b(?:event|action|activity)\b.{0,55}\bconcerns?\s+only\b|"
    r"\b(?:only|solely)\s+(?:the\s+)?(?:intercity|mainline|conventional|"
    r"commuter|regional|suburban)\b|\bno\s+(?:eligible\s+)?(?:urban[- ]rail|"
    r"mode|metro|mrt|subway|tram|agt|monorail|people[- ]mover)\b)",
    re.IGNORECASE,
)
_RELATION_PREPOSITION = re.compile(
    r"\b(?:on|at|for|to|within|along|between|of|from|inside)\b", re.IGNORECASE
)
_ACTOR_NOUN = re.compile(
    r"\b(?:operator|publisher|company|agency|authority|division|owner|"
    r"airline|carrier|organizer)\b",
    re.IGNORECASE,
)
_LOCATION_PREPOSITION = re.compile(
    r"\b(?:near|next\s+to|beside|outside|around|mentioning|at)\b", re.IGNORECASE
)


@dataclass(frozen=True, slots=True)
class _Sentence:
    start: int
    end: int
    text: str
    index: int


@dataclass(frozen=True, slots=True)
class _ModeMention:
    family: str
    start: int
    end: int
    sentence_index: int
    negated: bool = False
    role: str = "system"


@dataclass(frozen=True, slots=True)
class _ActionMention:
    start: int
    end: int
    sentence_index: int
    clause_start: int
    clause_end: int
    nominal: bool = False
    japanese: bool = False


@dataclass(frozen=True, slots=True)
class _Target:
    start: int
    end: int
    text: str
    status: str
    equipment: bool


@dataclass(frozen=True, slots=True)
class _Relation:
    action: _ActionMention
    target: _Target
    mode: _ModeMention
    link_start: int
    link_end: int


@dataclass(frozen=True, slots=True)
class _EventInterpretation:
    action: _ActionMention
    target: _Target
    status: str
    relation: _Relation | None = None


def _content_sentences(content: str) -> tuple[_Sentence, ...]:
    """Split source text while preserving exact original offsets."""

    result: list[_Sentence] = []
    for index, match in enumerate(
        re.finditer(r"[^.!?。！？;；\n]+(?:[.!?。！？;；\n]|$)", content)
    ):
        raw = match.group(0)
        left = len(raw) - len(raw.lstrip())
        right = len(raw.rstrip())
        if right <= left:
            continue
        result.append(
            _Sentence(match.start() + left, match.start() + right, raw[left:right], index)
        )
    return tuple(result)


def _mode_family(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value.casefold()).strip()
    if normalized in {"streetcar", "tram"}:
        return "Tram"
    if normalized in {"urban rail", "urban-rail"}:
        return "Urban Rail"
    if normalized in {"agt", "automated guideway transit"}:
        return "AGT"
    if normalized in {"people mover", "people-mover"}:
        return "People Mover"
    if normalized == "métro":
        return "Metro"
    return normalized.upper() if normalized == "mrt" else normalized.title()


def _mode_negated(text: str, start: int, end: int, *, japanese: bool = False) -> bool:
    left = text[max(0, start - 100) : start]
    right = text[end : min(len(text), end + 42)]
    if japanese:
        return bool(re.search(r"(?:ない|ず|未確立|明確でない)", right))
    return bool(
        re.search(
            r"(?:\bno\s+(?:eligible\s+)?|\bwithout\s+(?:an?\s+)?eligible\b|"
            r"\bnot\s+(?:an?\s+)?(?:the\s+)?|\bdoes\s+not\s+(?:establish|identify)\b|"
            r"\bdoesn't\s+(?:establish|identify)\b|\bne\s+[^.]{0,25}\bpas\b)",
            left,
            re.IGNORECASE,
        )
    )


def _mode_role(text: str, start: int, end: int) -> str:
    left = text[max(0, start - 70) : start]
    right = text[end : min(len(text), end + 70)]
    right_head = re.split(r"[,;]|\b(?:and|but|while|whereas)\b", right, maxsplit=1, flags=re.IGNORECASE)[0]
    if _LOCATION_PREPOSITION.search(left):
        return "location"
    if _ACTOR_NOUN.search(right_head) or re.search(
        r"\b(?:operates|owns|manages|serves)\s*$", left, re.IGNORECASE
    ):
        return "actor"
    return "system"


def _mode_mentions(sentence: _Sentence) -> tuple[_ModeMention, ...]:
    mentions: list[_ModeMention] = []
    for match in _ELIGIBLE_MODE.finditer(sentence.text):
        mentions.append(
            _ModeMention(
                _mode_family(match.group()),
                sentence.start + match.start(),
                sentence.start + match.end(),
                sentence.index,
                _mode_negated(sentence.text, match.start(), match.end()),
                _mode_role(sentence.text, match.start(), match.end()),
            )
        )
    for match in _JAPANESE_MODE.finditer(sentence.text):
        mentions.append(
            _ModeMention(
                "Subway" if "地下鉄" in match.group() else "Urban Rail",
                sentence.start + match.start(),
                sentence.start + match.end(),
                sentence.index,
                _mode_negated(sentence.text, match.start(), match.end(), japanese=True),
                _mode_role(sentence.text, match.start(), match.end()),
            )
        )
    return tuple(mentions)


def _clause_bounds(text: str, action_start: int, action_end: int) -> tuple[int, int]:
    boundaries = [0, len(text)]
    for match in re.finditer(
        r"[,;]|\b(?:and|but|while|whereas|or|et|mais)\b|、", text, re.IGNORECASE
    ):
        boundaries.append(match.start())
        boundaries.append(match.end())
    boundaries = sorted(set(boundaries))
    left = max(value for value in boundaries if value <= action_start)
    right = min(value for value in boundaries if value >= action_end)
    while left < right and text[left].isspace():
        left += 1
    return left, right


def _action_mentions(sentence: _Sentence) -> tuple[_ActionMention, ...]:
    actions: list[_ActionMention] = []
    for match in _ACTION.finditer(sentence.text):
        value = match.group().casefold()
        japanese = bool(re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", match.group()))
        nominal = bool(
            re.search(
                r"(?:ation|ment|renewal|replacement|deployment|installation|"
                r"upgrade|construction|testing)$",
                value,
                re.IGNORECASE,
            )
        )
        clause_start, clause_end = _clause_bounds(sentence.text, match.start(), match.end())
        actions.append(
            _ActionMention(
                sentence.start + match.start(),
                sentence.start + match.end(),
                sentence.index,
                sentence.start + clause_start,
                sentence.start + clause_end,
                nominal,
                japanese,
            )
        )
    return tuple(actions)


def _trimmed_span(content: str, start: int, end: int) -> tuple[int, int]:
    while start < end and (content[start].isspace() or content[start] in ".,;:!?。！？"):
        start += 1
    while start < end and (content[end - 1].isspace() or content[end - 1] in ".,;:!?。！？"):
        end -= 1
    return start, end


def _target_status(text: str, *, japanese: bool = False) -> tuple[str, bool]:
    if japanese:
        if _EXCLUDED_JP.search(text):
            return "excluded", False
        if _NON_URBAN_JP.search(text):
            return "nonurban", False
        return "", bool(_EQUIPMENT_JP.search(text))
    if _EXCLUDED_MODE.search(text):
        return "excluded", False
    if _NON_URBAN.search(text):
        return "nonurban", False
    return "", bool(_EQUIPMENT.search(text))


def _action_not_asserted(content: str, action: _ActionMention) -> bool:
    """Reject negated, conditional, and merely proposed event predicates."""

    left = content[max(action.clause_start, action.start - 100) : action.start]
    right = content[action.end : min(action.clause_end, action.end + 60)]
    if action.japanese:
        return bool(re.search(r"(?:なかった|ない|未導入|予定|計画|可能|場合)", right))
    if re.search(
        r"(?:\b(?:not|never|without|would|could|might|may|if|unless)\b|"
        r"\b(?:planned|proposed|announced|reported)\b.{0,25}\b(?:to|a|the)?\s*$|"
        r"\b(?:did|does|do|was|were|has|have|had)\s+not\s*$|\bpas\s*$)",
        left,
        re.IGNORECASE,
    ):
        return True
    if re.search(
        r"\b(?:not|never)\s+(?:associated|linked|connected|tied|attributed)\b",
        left + right,
        re.IGNORECASE,
    ):
        return True
    return False


def _target_for_action(content: str, action: _ActionMention) -> _Target:
    clause_start, clause_end = action.clause_start, action.clause_end
    before = content[clause_start : action.start]
    after = content[action.end : clause_end]

    passive = re.search(
        r"(?P<target>[^,;]+?)\b(?:was|were|is|are|has\s+been|had\s+been|"
        r"a\s+été|ont\s+été|est|sont)\s*$",
        before,
        re.IGNORECASE,
    )
    if passive:
        raw_start = clause_start + passive.start("target")
        raw_end = clause_start + passive.end("target")
        raw_start, raw_end = _trimmed_span(content, raw_start, raw_end)
        target_text = content[raw_start:raw_end]
        status, equipment = _target_status(target_text, japanese=action.japanese)
        return _Target(raw_start, raw_end, target_text, status, equipment)

    if action.japanese:
        raw_start = clause_start
        for marker in ("は", "が"):
            position = content.rfind(marker, clause_start, action.start)
            if position >= raw_start:
                raw_start = position + 1
        raw_end = action.start
        while raw_end > raw_start and content[raw_end - 1] in " \t\r\nをはが、,":
            raw_end -= 1
        last_no = content.rfind("の", raw_start, raw_end)
        if last_no >= raw_start:
            raw_start = last_no + 1
        raw_start, raw_end = _trimmed_span(content, raw_start, raw_end)
        target_text = content[raw_start:raw_end]
        status, equipment = _target_status(
            content[clause_start:clause_end], japanese=True
        )
        return _Target(raw_start, raw_end, target_text, status, equipment)

    object_start = action.end
    while object_start < clause_end and content[object_start].isspace():
        object_start += 1
    if action.nominal and content[object_start : object_start + 3].casefold() == "of ":
        object_start += 3
    object_end = clause_end
    relation = re.search(
        r"\b(?:for|on|at|to|within|along|between|of|from|inside)\b",
        content[object_start:clause_end],
        re.IGNORECASE,
    )
    if relation:
        object_end = object_start + relation.start()
    object_start, object_end = _trimmed_span(content, object_start, object_end)
    if object_start >= object_end:
        object_start, object_end = _trimmed_span(content, clause_start, action.start)
    target_text = content[object_start:object_end]
    full_clause = content[clause_start:clause_end]
    status, equipment = _target_status(full_clause)
    if not status:
        _, equipment = _target_status(target_text)
    if not status:
        for match in re.finditer(
            r"\b(?:for|on|at|to|within|along|between|of|from|inside)\b",
            content[action.end:clause_end],
            re.IGNORECASE,
        ):
            complement = content[action.end + match.end() : clause_end]
            next_relation = re.search(
                r"\b(?:for|on|at|to|within|along|between|of|from|inside)\b",
                complement,
                re.IGNORECASE,
            )
            if next_relation:
                complement = complement[: next_relation.start()]
            status, _ = _target_status(complement)
            if status:
                equipment = False
                break
    return _Target(object_start, object_end, target_text, status, equipment)


def _mode_in_text(mode: _ModeMention, start: int, end: int) -> bool:
    return mode.start >= start and mode.end <= end and not mode.negated


def _mode_relation_for_action(
    content: str,
    action: _ActionMention,
    target: _Target,
    modes: Sequence[_ModeMention],
) -> tuple[_ModeMention, int, int] | None:
    if target.status:
        return None
    clause_start, clause_end = action.clause_start, action.clause_end
    local_modes = tuple(
        mode for mode in modes if _mode_in_text(mode, clause_start, clause_end)
    )
    if not local_modes:
        return None

    for mode in local_modes:
        if target.start <= mode.start and mode.end <= target.end:
            return mode, mode.start, target.end

    for mode in local_modes:
        if mode.role == "location" and not target.equipment:
            continue
        if mode.role == "location" and not re.search(
            r"\b(?:station|line|route|segment|system|network)\b",
            content[mode.start : min(clause_end, mode.end + 50)],
            re.IGNORECASE,
        ):
            continue
        if mode.start < target.end:
            continue
        between = content[target.end : mode.start]
        if _RELATION_PREPOSITION.search(between):
            return mode, target.end, mode.end

    before = content[clause_start : action.start]
    for mode in local_modes:
        if mode.start >= action.start or mode.role in {"actor", "location"}:
            continue
        subject = before[: max(0, mode.end - clause_start)]
        after_mode = content[mode.end : action.start]
        if _ACTOR_NOUN.search(after_mode):
            continue
        if _LOCATION_PREPOSITION.search(subject[max(0, subject.rfind(",") + 1) :]):
            continue
        if re.search(
            r"(?:system|network|line|service|connector|station|route|segment|portion)\b",
            after_mode,
            re.IGNORECASE,
        ):
            return mode, mode.start, action.end
        before_mode = content[clause_start : mode.start]
        if re.search(
            r"(?:^|\b)(?:the|a|an|le|la|un|une)\s*$",
            before_mode,
            re.IGNORECASE,
        ):
            return mode, mode.start, action.end

    return None


def _cross_clause_reference(
    content: str,
    action: _ActionMention,
    target: _Target,
    groups: Sequence[tuple[int, tuple[_ModeMention, ...]]],
) -> tuple[_ModeMention, int, int] | None:
    """Bind a unique, explicit component reference to one system statement."""

    if target.status or not target.equipment or len(groups) != 1:
        return None
    clause = content[action.clause_start : action.clause_end]
    if not re.search(
        r"(?:\b(?:that|this|its|their)\s+(?:[\w-]+\s+)?(?:system|line|network|route|"
        r"segment|portion|station)\b|\b(?:central|main|airport|urban[- ]rail|"
        r"people[- ]mover)\s+(?:line|route|segment|system)\b)",
        clause,
        re.IGNORECASE,
    ):
        return None
    mode = next((item for item in groups[0][1] if not item.negated), None)
    if mode is None:
        return None
    return mode, action.clause_start, action.end


def _japanese_relation(
    content: str,
    sentence: _Sentence,
    action: _ActionMention,
    target: _Target,
) -> tuple[str, _Relation | None]:
    clause = content[action.clause_start : action.clause_end]
    if target.status:
        return target.status, None
    local_modes = tuple(
        mode
        for mode in _mode_mentions(sentence)
        if _mode_in_text(mode, action.clause_start, action.clause_end)
    )
    for mode in local_modes:
        prefix = content[action.clause_start : target.start]
        if re.search(r"地下鉄(?:路線|線|システム)の", prefix):
            return "eligible", _Relation(action, target, mode, mode.start, target.end)
    if (
        re.search(r"(?:地下鉄|都市鉄道)(?:システム|路線|線|事業者)", content)
        and _JP_SYSTEM_COMPONENT.search(target.text)
    ):
        mode = next((item for item in local_modes if not item.negated), None)
        if mode is not None and target.equipment:
            return "eligible", _Relation(action, target, mode, mode.start, target.end)
    return "ambiguous", None


def _interpret_authoritative_content(
    content: str,
    *,
    candidate_title: str = "",
) -> tuple[ScopeSemanticSupport, ScopeDiagnostic, tuple[ScopeSupportSpan, ...], Mapping[str, Any]]:
    """Interpret bounded action→target→mode relations in principal content."""

    sentences = _content_sentences(content)
    sentence_modes = {sentence.index: _mode_mentions(sentence) for sentence in sentences}
    groups: list[tuple[int, tuple[_ModeMention, ...]]] = []
    for index, modes in sentence_modes.items():
        usable = tuple(
            mode for mode in modes if not mode.negated and mode.role == "system"
        )
        if usable:
            groups.append((index, usable))

    events: list[_EventInterpretation] = []
    action_count = 0
    for sentence in sentences:
        modes = sentence_modes.get(sentence.index, ())
        for action in _action_mentions(sentence):
            action_count += 1
            if _action_not_asserted(content, action):
                target = _target_for_action(content, action)
                events.append(_EventInterpretation(action, target, target.status or "ambiguous"))
                continue
            target = _target_for_action(content, action)
            if action.japanese:
                status, relation = _japanese_relation(content, sentence, action, target)
            else:
                status = target.status
                relation = None
                if not status:
                    bound = _mode_relation_for_action(content, action, target, modes)
                    if bound is not None:
                        mode, link_start, link_end = bound
                        relation = _Relation(action, target, mode, link_start, link_end)
                        status = "eligible"
                    else:
                        cross = _cross_clause_reference(content, action, target, groups)
                        if cross is not None:
                            mode, link_start, link_end = cross
                            relation = _Relation(action, target, mode, link_start, link_end)
                            status = "eligible"
                        else:
                            status = "ambiguous"
            events.append(_EventInterpretation(action, target, status, relation))

    selected_events = tuple(events)
    focus_unresolved = False
    if len(events) > 1 and any(event.relation is not None for event in events):
        terms: list[str] = []
        for raw in re.findall(
            r"[A-Za-z0-9]+|[\u3040-\u30ff\u4e00-\u9fff]+", candidate_title.casefold()
        ):
            if re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", raw):
                terms.extend(
                    part
                    for part in re.split(
                        r"(?:が|は|を|に|の|へ|と|で|や|も|から|まで)", raw
                    )
                    if len(part) >= 2
                )
            elif len(raw) > 2 and raw not in {
                "the", "and", "for", "with", "from", "while"
            }:
                terms.append(raw)
        terms = list(dict.fromkeys(terms))
        if not terms:
            focus_unresolved = True
        else:
            scores = [
                sum(
                    term in (
                        content[event.action.clause_start : event.action.clause_end]
                        + " "
                        + event.target.text
                    ).casefold()
                    for term in terms
                )
                for event in events
            ]
            best = max(scores, default=0)
            if best <= 0 or scores.count(best) != 1:
                focus_unresolved = True
            else:
                selected_events = (events[scores.index(best)],)
    if focus_unresolved:
        return (
            ScopeSemanticSupport.OUT_OF_SCOPE_SUPPORT,
            ScopeDiagnostic.SCOPE_NOT_ESTABLISHED,
            (),
            {
                "decision_basis": "authoritative_event_mode_relation",
                "event_focus": "candidate_event_unresolved",
            },
        )
    relations = [event.relation for event in selected_events if event.relation is not None]
    statuses = [event.status for event in selected_events]

    if relations:
        support_spans: list[ScopeSupportSpan] = []
        role_spans: dict[str, dict[str, int]] = {}
        for relation in relations:
            role_values = {
                "action": (relation.action.start, relation.action.end),
                "target": (relation.target.start, relation.target.end),
                "eligible_mode": (relation.mode.start, relation.mode.end),
                "relation": (relation.link_start, relation.link_end),
            }
            for role, (start, end) in role_values.items():
                role_spans.setdefault(role, {"start": start, "end": end})
                support_spans.append(ScopeSupportSpan(start, end))
        unique: list[ScopeSupportSpan] = []
        seen: set[tuple[int, int]] = set()
        for span in support_spans:
            key = (span.start, span.end)
            if key not in seen and 0 <= span.start < span.end <= len(content):
                seen.add(key)
                unique.append(span)
        return (
            ScopeSemanticSupport.IN_SCOPE_SUPPORT,
            ScopeDiagnostic.NONE,
            tuple(unique),
            {
                "decision_basis": "authoritative_event_mode_relation",
                "relation_support": role_spans,
            },
        )

    if any(status == "excluded" for status in statuses):
        diagnostic = ScopeDiagnostic.EXCLUDED_TRANSPORT_MODE
    elif any(status == "nonurban" for status in statuses):
        diagnostic = ScopeDiagnostic.NON_URBAN_RAIL
    elif _UNRESOLVED.search(content) or "ambiguous" in statuses:
        diagnostic = ScopeDiagnostic.SCOPE_NOT_ESTABLISHED
    elif _ONLY_NON_URBAN.search(content) and _NON_URBAN.search(content):
        diagnostic = ScopeDiagnostic.NON_URBAN_RAIL
    elif action_count:
        diagnostic = ScopeDiagnostic.SCOPE_NOT_ESTABLISHED
    else:
        diagnostic = ScopeDiagnostic.SCOPE_NOT_ESTABLISHED
    return (
        ScopeSemanticSupport.OUT_OF_SCOPE_SUPPORT,
        diagnostic,
        (),
        {"decision_basis": "authoritative_event_mode_relation"},
    )


def _span_from_mapping(value: object) -> ScopeSupportSpan | None:
    if isinstance(value, ScopeSupportSpan):
        return value
    if not isinstance(value, Mapping):
        return None
    try:
        return ScopeSupportSpan(int(value["start"]), int(value["end"]))
    except (KeyError, TypeError, ValueError):
        return None


def _coerce_response(value: object) -> ScopeSemanticResponse | None:
    if isinstance(value, ScopeSemanticResponse):
        return value
    if not isinstance(value, Mapping):
        return None
    support = value.get("support", value.get("relation", ""))
    spans = value.get("support_spans", value.get("spans", ()))
    if isinstance(spans, Mapping):
        spans = (spans,)
    if isinstance(spans, (str, bytes)) or not isinstance(spans, Sequence):
        return None
    parsed_spans = tuple(
        span for item in spans if (span := _span_from_mapping(item)) is not None
    )
    diagnostic = value.get("diagnostic", ScopeDiagnostic.SCOPE_NOT_ESTABLISHED)
    try:
        diagnostic = ScopeDiagnostic(diagnostic)
    except ValueError:
        diagnostic = ScopeDiagnostic.SCOPE_NOT_ESTABLISHED
    return ScopeSemanticResponse(support=support, support_spans=parsed_spans, diagnostic=diagnostic)


def _valid_spans(
    spans: tuple[ScopeSupportSpan, ...], content: str
) -> tuple[ScopeSupportSpan, ...]:
    return tuple(
        span for span in spans if 0 <= span.start < span.end <= len(content)
    )


class ScopeClassifier:
    """The sole authoritative owner of IN_SCOPE / OUT_OF_SCOPE."""

    def __init__(self, semantic_helper: ScopeSemanticHelper | None = None) -> None:
        self._semantic_helper = semantic_helper

    def classify(
        self,
        evidence: EvidenceResult,
        *,
        candidate_title: str = "",
    ) -> ScopeResult:
        """Classify one EVIDENCE_READY Candidate without external I/O."""

        if evidence.state is not EvidenceState.READY:
            raise ValueError("ScopeClassifier requires EVIDENCE_READY evidence")

        if self._semantic_helper is None:
            support, diagnostic, spans, provenance = _interpret_authoritative_content(
                evidence.substantive_content,
                candidate_title=candidate_title,
            )
            if support is ScopeSemanticSupport.IN_SCOPE_SUPPORT and spans:
                provenance = dict(provenance)
                provenance["validated_support_spans"] = [
                    {"start": span.start, "end": span.end} for span in spans
                ]
                return ScopeResult(
                    candidate_id=evidence.candidate_id,
                    state=ScopeState.IN_SCOPE,
                    provenance=provenance,
                )
            return self._out_of_scope(evidence.candidate_id, diagnostic, provenance)

        request = ScopeSemanticRequest(
            candidate_id=evidence.candidate_id,
            candidate_title=candidate_title,
            principal_content=evidence.substantive_content,
            source_metadata=dict(evidence.provenance),
        )
        try:
            response = _coerce_response(self._semantic_helper(request))
        except Exception as exc:
            return self._out_of_scope(
                evidence.candidate_id,
                ScopeDiagnostic.SCOPE_NOT_ESTABLISHED,
                {"helper_error": type(exc).__name__},
            )
        if response is None:
            return self._out_of_scope(
                evidence.candidate_id,
                ScopeDiagnostic.SCOPE_NOT_ESTABLISHED,
                {"helper_response": "invalid"},
            )

        try:
            support = ScopeSemanticSupport(response.support)
        except ValueError:
            support = ScopeSemanticSupport.UNCERTAIN
        spans = _valid_spans(response.support_spans, evidence.substantive_content)
        if support is ScopeSemanticSupport.IN_SCOPE_SUPPORT and spans:
            return ScopeResult(
                candidate_id=evidence.candidate_id,
                state=ScopeState.IN_SCOPE,
                provenance={
                    "decision_basis": "constrained_scope_helper",
                    "validated_support_spans": [
                        {"start": span.start, "end": span.end} for span in spans
                    ],
                },
            )
        if support is ScopeSemanticSupport.OUT_OF_SCOPE_SUPPORT and spans:
            diagnostic = response.diagnostic
            if diagnostic is ScopeDiagnostic.NONE:
                diagnostic = ScopeDiagnostic.SCOPE_NOT_ESTABLISHED
            return self._out_of_scope(
                evidence.candidate_id,
                diagnostic,
                {
                    "decision_basis": "constrained_scope_helper",
                    "validated_support_spans": [
                        {"start": span.start, "end": span.end} for span in spans
                    ],
                },
            )
        return self._out_of_scope(
            evidence.candidate_id,
            ScopeDiagnostic.SCOPE_NOT_ESTABLISHED,
            {"decision_basis": "constrained_scope_helper", "support": support.value},
        )

    evaluate = classify

    @staticmethod
    def _out_of_scope(
        candidate_id: str,
        diagnostic: ScopeDiagnostic,
        provenance: Mapping[str, Any],
    ) -> ScopeResult:
        return ScopeResult(
            candidate_id=candidate_id,
            state=ScopeState.OUT_OF_SCOPE,
            diagnostic=diagnostic,
            provenance=dict(provenance),
        )


__all__ = [
    "ScopeClassifier",
    "ScopeSemanticHelper",
    "ScopeSemanticRequest",
    "ScopeSemanticResponse",
    "ScopeSemanticSupport",
    "ScopeSupportSpan",
]
