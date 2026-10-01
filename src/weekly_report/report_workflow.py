"""Shared production workflow for the Category-to-Taxonomy population stage.

The service only orchestrates existing authoritative owners.  It does not
implement Category or E&M Taxonomy semantics and has no downstream fallback,
retry, rescue, or backfill behavior.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .contracts import (
    CategoryResult,
    EventDecisionRecord,
    EventGroup,
    EventIdentityRecord,
)
from .taxonomy import Taxonomy, TaxonomySemanticProposalProvider


class ReportWorkflow:
    """Existing shared workflow authority for one formal population run."""

    def __init__(self, taxonomy: Any) -> None:
        if not callable(getattr(taxonomy, "evaluate", None)):
            raise TypeError("ReportWorkflow requires a Taxonomy owner")
        self._taxonomy = taxonomy

    @property
    def taxonomy(self) -> Any:
        """Return the injected authoritative Taxonomy dependency."""

        return self._taxonomy

    def run(
        self,
        event_groups: Sequence[EventGroup],
        member_records: Mapping[str, Sequence[EventIdentityRecord]]
        | Sequence[Sequence[EventIdentityRecord]],
        category_results: Mapping[str, CategoryResult] | Sequence[CategoryResult],
    ) -> tuple[EventDecisionRecord, ...]:
        """Populate all EventGroups through Taxonomy before returning any result.

        The local list is intentionally not exposed until every EventGroup has
        completed successfully.  A :class:`TaxonomyStageFailure` therefore
        aborts the formal run without a partial-success result.
        """

        groups = self._validate_groups(event_groups)
        member_values = self._align_values(member_records, groups, "member_records")
        category_values = self._align_values(category_results, groups, "category_results")

        decisions: list[EventDecisionRecord] = []
        for group, records, category_result in zip(
            groups,
            member_values,
            category_values,
            strict=True,
        ):
            taxonomy_result = self._taxonomy.evaluate(group, records, category_result)
            decisions.append(
                EventDecisionRecord(
                    event_group=group,
                    member_records=tuple(records),
                    category_result=category_result,
                    taxonomy_result=taxonomy_result,
                )
            )
        return tuple(decisions)

    @staticmethod
    def _validate_groups(event_groups: Sequence[EventGroup]) -> tuple[EventGroup, ...]:
        if not isinstance(event_groups, Sequence) or isinstance(
            event_groups, (str, bytes, bytearray)
        ):
            raise TypeError("ReportWorkflow event_groups must be a sequence")
        groups = tuple(event_groups)
        if any(not isinstance(group, EventGroup) for group in groups):
            raise TypeError("ReportWorkflow event_groups must contain EventGroup values")
        event_ids = [group.event_id for group in groups]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("ReportWorkflow event_groups must have unique event IDs")
        return groups

    @staticmethod
    def _align_values(
        values: Mapping[str, Any] | Sequence[Any],
        groups: tuple[EventGroup, ...],
        name: str,
    ) -> tuple[Any, ...]:
        if isinstance(values, Mapping):
            try:
                return tuple(values[group.event_id] for group in groups)
            except KeyError as exc:
                raise ValueError(f"{name} is missing an EventGroup value") from exc
        if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
            raise TypeError(f"ReportWorkflow {name} must be a mapping or sequence")
        aligned = tuple(values)
        if len(aligned) != len(groups):
            raise ValueError(f"ReportWorkflow {name} must align with event_groups")
        return aligned


def build_report_workflow(
    *,
    taxonomy_proposal_provider: TaxonomySemanticProposalProvider | None = None,
) -> ReportWorkflow:
    """Compose the shared workflow with an injected proposal-only provider."""

    taxonomy = Taxonomy(proposal_provider=taxonomy_proposal_provider)
    return ReportWorkflow(taxonomy)


__all__ = ["ReportWorkflow", "build_report_workflow"]
