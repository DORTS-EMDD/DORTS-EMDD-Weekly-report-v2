"""Per-candidate selection audit: an observer-only projection (RC-31).

``build_selection_audit`` reads the ``ReportApplicationResult`` that the
authoritative owners already produced and lays out, for every normalized
candidate, what each stage decided and where (and why) the candidate stopped.
It re-derives nothing: every state and reason is copied from an owner result,
a TechnicalGap or a metadata exclusion, and the earliest terminal stage is the
first stage, in pipeline order, whose recorded outcome ends the candidate's
path. It makes no call, changes no result and takes part in no decision.

Bounded and secret-free: titles and highlights are truncated, at most two
event-focus sentences per candidate are quoted, and no article body, prompt,
provider response or credential is included.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from datetime import date
from typing import Any

from .contracts import EvidenceState, ScopeState
from .evidence_sentences import event_focus_sentences

SELECTION_AUDIT_VERSION = "selection-audit-v1"
STAGES = (
    "EVIDENCE",
    "SCOPE",
    "TEMPORAL",
    "EVENT_IDENTITY",
    "CATEGORY",
    "TAXONOMY",
    "REPORTABILITY",
    "ORDERING",
    "FORMAL_METADATA",
    "WRITER",
    "VALIDATION",
    "FINAL_REPORT",
)
_GAP_STAGE = {
    "Evidence": "EVIDENCE",
    "Scope": "SCOPE",
    "Category": "CATEGORY",
    "Taxonomy": "TAXONOMY",
    "Reportability": "REPORTABILITY",
    "Writer": "WRITER",
    "Validator": "VALIDATION",
}
_TITLE_LIMIT = 200
_HIGHLIGHT_LIMIT = 240
_HIGHLIGHT_SENTENCES = 2


def _value(value: Any) -> Any:
    """Enum members as their value; everything else unchanged."""

    return getattr(value, "value", value)


def _clip(text: Any, limit: int) -> str:
    value = " ".join(str(text or "").split())
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _gap(gap: Any) -> dict[str, Any]:
    return {"kind": _value(gap.kind), "failure_class": gap.failure_class}


def _evidence(result: Any) -> dict[str, Any]:
    provenance = dict(result.provenance or {})
    return {
        "state": _value(result.state),
        "reject_reason": _value(result.reject_reason),
        "rejection_gate": provenance.get("evidence_rejection_gate"),
        "canonical_source_url": result.canonical_source_url or None,
    }


def _focus(evidence: Any, scope: Any) -> tuple[list[str], list[str]]:
    sentences = event_focus_sentences(
        evidence.substantive_content, dict(scope.provenance or {}).get("candidate_event_focus")
    )
    return (
        [sentence.sentence_id for sentence in sentences],
        [_clip(sentence.text, _HIGHLIGHT_LIMIT) for sentence in sentences[:_HIGHLIGHT_SENTENCES]],
    )


def _region(evidence: Any) -> dict[str, Any] | None:
    resolution = getattr(evidence.identity_facts, "region_resolution", None)
    if resolution is None:
        return None
    return {
        "basis": _value(resolution.basis),
        "region_id": resolution.region_id if resolution.established else None,
    }


_PAIR_PROPOSALS = frozenset({"PROPOSAL_NOT_CONFIRMED", "PROPOSAL_REGION_CONFLICT"})


def _rejected_groups(run: Any) -> list[dict[str, Any]]:
    """RC-40: each rejected proposal group, its failure class and the candidates it named."""

    rejected = []
    for diagnostic in getattr(run, "diagnostics", ()) or ():
        if diagnostic.reason != "PROPOSAL_GROUP_REJECTED":
            continue
        group, _, failure_class = diagnostic.detail.rpartition("|")
        rejected.append({"group": group, "reason": failure_class, "candidate_ids": list(diagnostic.candidate_ids)})
    return sorted(rejected, key=lambda item: item["group"])


def _identity_diagnostics(run: Any) -> tuple[dict[str, Counter], dict[str, list[dict[str, str]]]]:
    """Per candidate: diagnostic reason counts, and each proposed pair left apart."""

    counts: dict[str, Counter] = {}
    proposals: dict[str, list[dict[str, str]]] = {}
    for diagnostic in getattr(run, "diagnostics", ()) or ():
        for candidate_id in diagnostic.candidate_ids:
            counts.setdefault(candidate_id, Counter())[diagnostic.reason] += 1
        if diagnostic.reason in _PAIR_PROPOSALS and len(diagnostic.candidate_ids) == 2:
            left, right = diagnostic.candidate_ids
            for candidate_id, other in ((left, right), (right, left)):
                proposals.setdefault(candidate_id, []).append(
                    {"with": other, "reason": diagnostic.reason, "detail": diagnostic.detail}
                )
    return counts, proposals


def _event_outcomes(result: Any) -> dict[str, dict[str, Any]]:
    """Each Event's downstream outcome and its earliest terminal stage."""

    gaps = {(gap.stage, gap.subject_id): gap for gap in result.technical_gaps}
    category = {item.event_id: item for item in result.category_results or ()}
    downstream = {item.event_group.event_id: item for item in result.downstream_results or ()}
    order = {item.event_group.event_id: position for position, item in enumerate(result.ordered_results or (), start=1)}
    metadata = {item.event_id: item for item in result.formal_metadata or ()}
    exclusions = {item.event_id: item for item in result.metadata_exclusions}
    writer = {item.event_id for item in result.writer_blocks or ()}
    validation = result.validation_result
    passed = {item.metadata.event_id for item in (validation.passed if validation else ())}
    failed = {item.event_id: item for item in (validation.failed if validation else ())}
    final = {event.event_id: event for event in (result.final_report.events if result.final_report else ())}

    outcomes: dict[str, dict[str, Any]] = {}
    for group in getattr(result.event_identity_run, "groups", ()) or ():
        event_id = group.event_id
        outcome: dict[str, Any] = {
            "event_id": event_id,
            "member_candidate_ids": list(group.member_candidate_ids),
            "canonical_candidate_id": group.canonical_candidate_id,
        }
        steps: list[tuple[str, str | None]] = []

        def gap_or(stage_key: str, stage: str) -> str | None:
            gap = gaps.get((stage_key, event_id))
            if gap is not None:
                outcome[stage.lower()] = {"technical_gap": _gap(gap)}
                return f"TECHNICAL_GAP:{_value(gap.kind)}:{gap.failure_class}"
            return None

        reason = gap_or("Category", "CATEGORY")
        item = category.get(event_id)
        if reason is None and item is not None:
            outcome["category"] = {
                "state": _value(item.category_state),
                "primary_category": item.primary_category,
                "subtype": item.subtype,
                "resolution_reason": _value(item.category_resolution_reason),
            }
            if _value(item.category_state) != "CATEGORY_ASSIGNED":
                reason = _value(item.category_resolution_reason) or _value(item.category_state)
        steps.append(("CATEGORY", reason if reason or item is not None else "NOT_REACHED"))

        flow = downstream.get(event_id)
        reason = gap_or("Taxonomy", "TAXONOMY")
        if reason is None and flow is not None:
            taxonomy = flow.taxonomy_result
            outcome["taxonomy"] = {
                "state": _value(taxonomy.taxonomy_state),
                "systems": [system.display_label for system in taxonomy.systems],
                "resolution_reason": _value(taxonomy.taxonomy_resolution_reason),
            }
            if _value(taxonomy.taxonomy_state) != "TAXONOMY_EVALUATED":
                reason = _value(taxonomy.taxonomy_resolution_reason) or _value(taxonomy.taxonomy_state)
        steps.append(("TAXONOMY", reason if reason or flow is not None else "NOT_REACHED"))

        reason = gap_or("Reportability", "REPORTABILITY")
        reportability = getattr(flow, "reportability_result", None)
        if reason is None and reportability is not None:
            outcome["reportability"] = {
                "state": _value(reportability.reportability_state),
                "reason": _value(reportability.reportability_reason),
            }
            if _value(reportability.reportability_state) != "REPORTABLE":
                reason = _value(reportability.reportability_reason) or _value(reportability.reportability_state)
        steps.append(("REPORTABILITY", reason if reason or reportability is not None else "NOT_REACHED"))

        outcome["ordering_position"] = order.get(event_id)
        steps.append(("ORDERING", None if event_id in order else "NOT_REACHED"))

        exclusion = exclusions.get(event_id)
        meta = metadata.get(event_id)
        if meta is not None:
            outcome["formal_metadata"] = {
                "display_date": meta.display_date,
                "country": meta.country,
                "country_basis": _value(meta.country_basis),
                "transit_system_name": meta.transit_system_name,
                "transit_system_basis": _value(meta.transit_system_basis),
                "location": meta.location,
                "source_display": meta.source_display,
                "source_url": meta.source_url,
                "diagnostics": sorted({_value(item.reason) for item in meta.diagnostics}),
            }
        elif exclusion is not None:
            outcome["formal_metadata"] = {"exclusion_reason": _value(exclusion.reason)}
        steps.append(
            ("FORMAL_METADATA", _value(exclusion.reason) if exclusion is not None else (None if meta is not None else "NOT_REACHED"))
        )

        steps.append(("WRITER", gap_or("Writer", "WRITER") or (None if event_id in writer else "NOT_REACHED")))

        reason = gap_or("Validator", "VALIDATION")
        if reason is None and event_id in failed:
            failure = failed[event_id]
            outcome["validation"] = {"outcome": "FAIL", "reasons": list(failure.reasons), "corrected": failure.corrected}
            reason = "FAIL:" + ",".join(failure.reasons)
        elif reason is None and event_id in passed:
            outcome["validation"] = {"outcome": "PASS"}
        steps.append(("VALIDATION", reason if reason or event_id in passed else "NOT_REACHED"))

        included = event_id in final
        outcome["final_report_included"] = included
        if included:
            outcome["headline"] = final[event_id].headline
        steps.append(("FINAL_REPORT", None if included else "NOT_REACHED"))

        terminal = next(((stage, reason) for stage, reason in steps if reason is not None), ("FINAL_REPORT", "INCLUDED"))
        outcome["terminal_stage"], outcome["terminal_reason"] = terminal
        outcomes[event_id] = outcome
    return outcomes


def build_selection_audit(
    result: Any,
    *,
    period_start: date | None = None,
    period_end: date | None = None,
) -> dict[str, Any]:
    """Project every normalized candidate's path through the owners' results."""

    normalized = getattr(result.normalization_result, "normalized_candidates", ()) or ()
    gaps = {(gap.stage, gap.subject_id): gap for gap in result.technical_gaps}
    evidence = {item.candidate_id: item for item in result.evidence_results or ()}
    scope = {item.candidate_id: item for item in result.scope_results or ()}
    temporal = {item.candidate_id: item for item in result.temporal_results or ()}
    records = {item.candidate.candidate_id for item in result.event_identity_records or ()}
    run = result.event_identity_run
    event_of = {
        candidate_id: group
        for group in (getattr(run, "groups", ()) or ())
        for candidate_id in group.member_candidate_ids
    }
    identity_diagnostics, identity_proposals = _identity_diagnostics(run)
    rejected_groups = _rejected_groups(run)
    events = _event_outcomes(result)

    candidates: list[dict[str, Any]] = []
    for item in normalized:
        candidate = item.candidate
        candidate_id = candidate.candidate_id
        entry: dict[str, Any] = {
            "candidate_id": candidate_id,
            "discovery_title": _clip(candidate.title, _TITLE_LIMIT),
            "publisher": candidate.publisher or None,
            "published_at": candidate.published_at or None,
            "discovery_intent": candidate.discovery_intent or None,
        }
        terminal: tuple[str, str] | None = None

        def stop(stage: str, reason: str) -> None:
            nonlocal terminal
            if terminal is None:
                terminal = (stage, reason)

        found = evidence.get(candidate_id)
        gap = gaps.get(("Evidence", candidate_id))
        if gap is not None:
            entry["evidence"] = {"technical_gap": _gap(gap)}
            stop("EVIDENCE", f"TECHNICAL_GAP:{_value(gap.kind)}:{gap.failure_class}")
        elif found is None:
            stop("EVIDENCE", "NOT_REACHED")
        else:
            entry["evidence"] = _evidence(found)
            entry["region"] = _region(found)
            if found.state is not EvidenceState.READY:
                gate = entry["evidence"]["rejection_gate"]
                stop("EVIDENCE", f"{_value(found.reject_reason)}" + (f"|{gate}" if gate else ""))

        if terminal is None:
            gap = gaps.get(("Scope", candidate_id))
            judged = scope.get(candidate_id)
            if gap is not None:
                entry["scope"] = {"technical_gap": _gap(gap)}
                stop("SCOPE", f"TECHNICAL_GAP:{_value(gap.kind)}:{gap.failure_class}")
            elif judged is None:
                stop("SCOPE", "NOT_REACHED")
            else:
                sentence_ids, highlights = _focus(found, judged)
                entry["scope"] = {
                    "state": _value(judged.state),
                    "diagnostic": _value(judged.diagnostic),
                    "event_focus_sentence_ids": sentence_ids,
                }
                entry["evidence_highlights"] = highlights
                if judged.state is not ScopeState.IN_SCOPE:
                    stop("SCOPE", f"{_value(judged.state)}|{_value(judged.diagnostic)}")

        if terminal is None:
            dated = temporal.get(candidate_id)
            if dated is None:
                stop("TEMPORAL", "NOT_REACHED")
            else:
                entry["temporal"] = {
                    "date_valid": dated.date_valid,
                    "diagnostic": _value(dated.diagnostic),
                    "controlling_date": dated.controlling_calendar_date.isoformat()
                    if dated.controlling_calendar_date
                    else None,
                    "controlling_date_kind": _value(dated.controlling_date_kind),
                }
                if not dated.date_valid:
                    stop("TEMPORAL", str(_value(dated.diagnostic)))

        if terminal is None:
            group = event_of.get(candidate_id)
            if candidate_id not in records or group is None:
                stop("EVENT_IDENTITY", "NOT_REACHED")
            else:
                entry["event_identity"] = {
                    "event_id": group.event_id,
                    "merged_with": [other for other in group.member_candidate_ids if other != candidate_id],
                    "canonical": group.canonical_candidate_id == candidate_id,
                    "diagnostics": dict(sorted(identity_diagnostics.get(candidate_id, Counter()).items())),
                    # Proposed SAME_EVENT pairs that stayed apart, and why (RC-22, RC-31).
                    "proposals_not_merged": sorted(
                        identity_proposals.get(candidate_id, ()), key=lambda item: (item["with"], item["reason"])
                    ),
                    # RC-32: the sentences the grouping request carried for this record.
                    "proposal_excerpt_sentence_ids": list(
                        dict(getattr(run, "proposal_excerpts", {}) or {}).get(candidate_id, ())
                    ),
                    # RC-40: proposal groups naming this record that were rejected.
                    "proposal_groups_rejected": [
                        {"group": item["group"], "reason": item["reason"]}
                        for item in rejected_groups
                        if candidate_id in item["candidate_ids"]
                    ],
                }
                outcome = events[group.event_id]
                entry["event"] = {
                    key: value
                    for key, value in outcome.items()
                    if key not in {"event_id", "member_candidate_ids", "canonical_candidate_id"}
                }
                stop(outcome["terminal_stage"], outcome["terminal_reason"])

        entry["terminal_stage"], entry["terminal_reason"] = terminal or ("FINAL_REPORT", "INCLUDED")
        entry["final_report_included"] = entry["terminal_stage"] == "FINAL_REPORT" and entry["terminal_reason"] == "INCLUDED"
        candidates.append(entry)

    candidates.sort(key=lambda entry: (STAGES.index(entry["terminal_stage"]), entry["candidate_id"]), reverse=False)
    return {
        "audit_version": SELECTION_AUDIT_VERSION,
        "observer_only": True,
        "period": None if period_start is None or period_end is None else {
            "start": period_start.isoformat(),
            "end": period_end.isoformat(),
        },
        "report_id": result.final_report.report_id if result.final_report is not None else None,
        "candidate_count": len(candidates),
        "event_count": len(events),
        "final_report_event_count": sum(1 for outcome in events.values() if outcome["final_report_included"]),
        "terminal_stage_distribution": dict(
            sorted(Counter(entry["terminal_stage"] for entry in candidates).items(), key=lambda kv: STAGES.index(kv[0]))
        ),
        "terminal_reason_distribution": dict(
            sorted(Counter(f"{entry['terminal_stage']}:{entry['terminal_reason']}" for entry in candidates).items())
        ),
        "event_identity_excerpt_limits": getattr(run, "proposal_excerpt_limits", "") or None,
        "event_identity_rejected_groups": rejected_groups,
        "event_identity_technical_gaps": sorted(
            f"{gap.subject_id}:{_value(gap.kind)}:{gap.failure_class}"
            for gap in result.technical_gaps
            if gap.stage == "EventIdentity"
        ),
        "events": sorted(events.values(), key=lambda outcome: (outcome["ordering_position"] or 10**6, outcome["event_id"])),
        "candidates": candidates,
    }


def selection_audit_mapping_is_bounded(audit: Mapping[str, Any]) -> bool:
    """True when no quoted text exceeds the audit's bounds (for tests and shells)."""

    for entry in audit.get("candidates", ()):
        if len(entry.get("discovery_title", "")) > _TITLE_LIMIT:
            return False
        highlights = entry.get("evidence_highlights", ())
        if len(highlights) > _HIGHLIGHT_SENTENCES or any(len(text) > _HIGHLIGHT_LIMIT for text in highlights):
            return False
    return True


__all__ = ["SELECTION_AUDIT_VERSION", "STAGES", "build_selection_audit", "selection_audit_mapping_is_bounded"]
