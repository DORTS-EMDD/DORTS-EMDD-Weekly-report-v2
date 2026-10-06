"""Authoritative deterministic Ordering domain owner."""

from __future__ import annotations

from datetime import date

from .contracts import EventGroup, EventIdentityRecord, ReportabilityState, TemporalResult
from .report_workflow import ReportWorkflowResult


class Ordering:
    """Order an already validated REPORTABLE population by the locked rule."""

    def order(
        self,
        events: tuple[ReportWorkflowResult, ...],
    ) -> tuple[ReportWorkflowResult, ...]:
        if not isinstance(events, tuple):
            raise TypeError("Ordering.order requires a tuple")

        validated: list[tuple[date, str, ReportWorkflowResult]] = []
        seen_event_ids: set[str] = set()
        for event in events:
            if not isinstance(event, ReportWorkflowResult):
                raise TypeError("Ordering.order requires ReportWorkflowResult values")
            if (
                event.reportability_state is not ReportabilityState.REPORTABLE
                or not event.downstream_eligible
            ):
                raise ValueError("Ordering.order requires REPORTABLE results")

            event_group = event.event_group
            if not isinstance(event_group, EventGroup):
                raise ValueError("Ordering event_group must be an EventGroup")
            event_id = event_group.event_id
            if not isinstance(event_id, str) or not event_id:
                raise ValueError("Ordering requires a valid event_id")
            if event_id in seen_event_ids:
                raise ValueError("Ordering rejects duplicate event_id values")
            seen_event_ids.add(event_id)

            member_records = event.member_records
            if not isinstance(member_records, tuple):
                raise ValueError("Ordering member_records must be a tuple")
            canonical_candidate_id = event_group.canonical_candidate_id
            if not isinstance(canonical_candidate_id, str) or not canonical_candidate_id:
                raise ValueError("Ordering requires a valid canonical candidate ID")
            group_member_ids = event_group.member_candidate_ids
            if (
                not isinstance(group_member_ids, tuple)
                or any(
                    not isinstance(candidate_id, str) or not candidate_id
                    for candidate_id in group_member_ids
                )
                or len(group_member_ids) != len(set(group_member_ids))
            ):
                raise ValueError("Ordering EventGroup membership must be typed and unique")
            matches: list[EventIdentityRecord] = []
            member_candidate_ids: list[str] = []
            for member in member_records:
                if not isinstance(member, EventIdentityRecord):
                    raise ValueError("Ordering member_records must be typed")
                candidate = getattr(member, "candidate", None)
                candidate_id = getattr(candidate, "candidate_id", None)
                temporal = getattr(member, "temporal", None)
                if not isinstance(candidate_id, str) or not candidate_id:
                    raise ValueError("Ordering member candidate ID must be typed")
                if not isinstance(temporal, TemporalResult):
                    raise ValueError("Ordering member Temporal result must be typed")
                if temporal.candidate_id != candidate_id:
                    raise ValueError("Ordering member Temporal result is inconsistent")
                member_candidate_ids.append(candidate_id)
                if candidate_id == canonical_candidate_id:
                    matches.append(member)

            if len(matches) != 1:
                raise ValueError("Ordering requires one canonical member")
            if (
                len(member_candidate_ids) != len(set(member_candidate_ids))
                or set(member_candidate_ids) != set(group_member_ids)
            ):
                raise ValueError("Ordering member membership is inconsistent")
            canonical_member = matches[0]
            if canonical_candidate_id not in group_member_ids:
                raise ValueError("Ordering canonical membership is inconsistent")
            temporal = canonical_member.temporal
            if temporal.candidate_id != canonical_candidate_id:
                raise ValueError("Ordering canonical Temporal result is inconsistent")
            if temporal.date_valid is not True:
                raise ValueError("Ordering requires a valid canonical date")

            controlling_date = temporal.controlling_calendar_date
            if type(controlling_date) is not date:
                raise ValueError("Ordering requires a canonical calendar date")
            validated.append((controlling_date, event_id, event))

        ordered = sorted(
            validated,
            key=lambda item: (-item[0].toordinal(), item[1]),
        )
        return tuple(item[2] for item in ordered)


__all__ = ["Ordering"]
