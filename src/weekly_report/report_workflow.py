"""Shared production workflow for the Category-to-Taxonomy population stage.

The service only orchestrates existing authoritative owners.  It does not
implement Category or E&M Taxonomy semantics and has no downstream fallback,
retry, rescue, or backfill behavior.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .contracts import (
    CategoryResult,
    CategoryState,
    EventDecisionRecord,
    EventGroup,
    EventIdentityRecord,
    ReportabilityResult,
    ReportabilitySemanticProposalProvider,
    ReportabilityState,
    TaxonomyResult,
    TaxonomyState,
)
from .reportability import Reportability
from .taxonomy import Taxonomy, TaxonomySemanticProposalProvider

REPORTABILITY_NOT_EVALUATED = "NOT_EVALUATED"


@dataclass(frozen=True, slots=True)
class ReportWorkflowResult:
    """Structural workflow output around one upstream decision handoff.

    ``decision`` remains the existing immutable Category/Taxonomy handoff.
    ``reportability_result`` is present only when that handoff reaches the
    authoritative Reportability owner.  The derived state and eligibility
    properties are projections for downstream orchestration; they do not
    duplicate or reinterpret any semantic result.
    """

    decision: EventDecisionRecord
    reportability_result: ReportabilityResult | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.decision, EventDecisionRecord):
            raise TypeError("ReportWorkflowResult requires an EventDecisionRecord")
        if self.reportability_result is not None:
            if not isinstance(self.reportability_result, ReportabilityResult):
                raise TypeError("ReportWorkflowResult requires a ReportabilityResult")
            if self.reportability_result.event_id != self.event_group.event_id:
                raise ValueError("ReportWorkflowResult ReportabilityResult event_id does not match")

    @property
    def event_group(self) -> EventGroup:
        return self.decision.event_group

    @property
    def member_records(self) -> tuple[EventIdentityRecord, ...]:
        return self.decision.member_records

    @property
    def category_result(self) -> CategoryResult:
        return self.decision.category_result

    @property
    def taxonomy_result(self) -> TaxonomyResult:
        return self.decision.taxonomy_result

    @property
    def reportability_state(self) -> ReportabilityState | str:
        if self.reportability_result is None:
            return REPORTABILITY_NOT_EVALUATED
        return self.reportability_result.reportability_state

    @property
    def reportability_projection(self) -> ReportabilityState | str:
        """Return the two-state result or the upstream terminal projection."""

        return self.reportability_state

    @property
    def downstream_eligible(self) -> bool:
        return self.reportability_state is ReportabilityState.REPORTABLE


class ReportWorkflow:
    """Existing shared workflow authority for one formal population run."""

    def __init__(
        self,
        taxonomy: Any,
        reportability: Any | None = None,
    ) -> None:
        if not callable(getattr(taxonomy, "evaluate", None)):
            raise TypeError("ReportWorkflow requires a Taxonomy owner")
        if reportability is not None and not callable(getattr(reportability, "evaluate", None)):
            raise TypeError("ReportWorkflow requires a Reportability owner")
        self._taxonomy = taxonomy
        self._reportability = reportability

    @property
    def taxonomy(self) -> Any:
        """Return the injected authoritative Taxonomy dependency."""

        return self._taxonomy

    @property
    def reportability(self) -> Any | None:
        """Return the injected authoritative Reportability dependency."""

        return self._reportability

    def run(
        self,
        event_groups: Sequence[EventGroup],
        member_records: Mapping[str, Sequence[EventIdentityRecord]]
        | Sequence[Sequence[EventIdentityRecord]],
        category_results: Mapping[str, CategoryResult] | Sequence[CategoryResult],
    ) -> tuple[EventDecisionRecord, ...] | tuple[ReportWorkflowResult, ...]:
        """Populate upstream decisions and the reached Reportability population.

        The local lists are intentionally not exposed until every stage has
        completed successfully.  A TaxonomyStageFailure or
        ReportabilityStageFailure therefore aborts the formal run without a
        partial-success result.  A workflow composed without a Reportability
        owner retains the pre-integration taxonomy-only return shape for
        callers that explicitly exercise that lower-level seam.
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
        if self._reportability is None:
            return tuple(decisions)

        results: list[ReportWorkflowResult] = []
        for decision in decisions:
            category_state = decision.category_result.category_state
            taxonomy_state = decision.taxonomy_result.taxonomy_state
            reportability_result: ReportabilityResult | None = None
            if (
                category_state is CategoryState.CATEGORY_ASSIGNED
                and taxonomy_state is TaxonomyState.TAXONOMY_EVALUATED
            ):
                reportability_result = self._reportability.evaluate(decision)
            results.append(ReportWorkflowResult(decision, reportability_result))
        return tuple(results)

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
    reportability_proposal_provider: ReportabilitySemanticProposalProvider,
) -> ReportWorkflow:
    """Compose the shared workflow with proposal-only owner dependencies."""

    taxonomy = Taxonomy(proposal_provider=taxonomy_proposal_provider)
    reportability = Reportability(proposal_provider=reportability_proposal_provider)
    return ReportWorkflow(taxonomy, reportability=reportability)


__all__ = [
    "REPORTABILITY_NOT_EVALUATED",
    "ReportWorkflow",
    "ReportWorkflowResult",
    "build_report_workflow",
]
