"""Replay a run's Event Identity offline from its selection audit (section A.34).

Every Event Identity helper exchange of a run is recorded in the selection
audit with IDs only (the request's record map, the validated groups and their
citations, or the failure). Rebuilding each Event Identity record from the
audit (candidate ID, discovery publication time, canonical URL, the
EvidenceService region and the excerpt sentence IDs) and answering every
request from its recorded exchange runs the unchanged EventIdentity owner on
exactly what the live run received. No network and no source text: the
excerpt sentences are placeholders carrying the recorded sentence IDs.

With ``--labels`` (a JSON map of candidate ID to occurrence label) the replayed
Events are scored: labelled same-occurrence pairs merged or left apart, and
differently labelled pairs merged.

Exit status: 0 when the replay reproduces the audited Events, 1 otherwise.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from itertools import combinations
import json
from pathlib import Path
import sys
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.weekly_report.contracts import (  # noqa: E402
    CanonicalCandidate,
    EventIdentityFacts,
    EventIdentityGroupingRequest,
    EventIdentityRecord,
    EventIdentityRun,
    EvidenceResult,
    EvidenceState,
    IdentityMetadataSupport,
    RegionResolution,
    RegionResolutionBasis,
    ScopeResult,
    ScopeState,
    SemanticProviderTechnicalFailure,
    TemporalDiagnostic,
    TemporalResult,
)
from src.weekly_report.event_identity import EventIdentity, EventIdentityProposalViolation  # noqa: E402
from src.weekly_report.evidence_sentences import segment_evidence_sentences  # noqa: E402

_ESTABLISHED = {RegionResolutionBasis.SOURCE_STATED.value, RegionResolutionBasis.REFERENCE_MAPPED.value}


class ReplayMismatch(RuntimeError):
    """The replay asked for an exchange the run did not record."""


def _region(entry: Mapping[str, Any] | None, body: str) -> EventIdentityFacts | None:
    """The audited EvidenceService region; an established one is anchored in the body's last line."""

    if not entry:
        return None
    basis, region_id = entry.get("basis"), entry.get("region_id")
    if basis in _ESTABLISHED and region_id:
        resolution = RegionResolution(
            basis, region_id=region_id, display_name=region_id, source_field="country",
            source_value=region_id, reference_version="replay",
        )
        start = body.rindex(region_id)
        return EventIdentityFacts(
            country=region_id,
            metadata_support=(IdentityMetadataSupport("country", start, start + len(region_id)),),
            region_resolution=resolution,
        )
    return EventIdentityFacts(region_resolution=RegionResolution(basis or RegionResolutionBasis.NOT_STATED.value))


def records_from_audit(audit: Mapping[str, Any]) -> list[EventIdentityRecord]:
    """The Event Identity records of an audited run, rebuilt without source text."""

    reached = [entry for entry in audit["candidates"] if entry.get("event_identity")]

    def excerpt_of(entry: Mapping[str, Any]) -> list[str]:
        return list(entry["event_identity"].get("proposal_excerpt_sentence_ids") or ["S1"])

    # Records with identical Evidence text (same content hash) get identical
    # placeholder bodies, so the deterministic exact-source path replays too.
    def content_key(entry: Mapping[str, Any]) -> str:
        return (entry.get("evidence") or {}).get("content_sha256") or entry["candidate_id"]

    lengths: dict[str, int] = {}
    for entry in reached:
        key = content_key(entry)
        lengths[key] = max(lengths.get(key, 0), *(int(sentence_id[1:]) for sentence_id in excerpt_of(entry)))

    records = []
    for entry in reached:
        candidate_id = entry["candidate_id"]
        excerpt = excerpt_of(entry)
        key = content_key(entry)
        body = "\n".join(f"Replay {key} sentence {index}." for index in range(1, lengths[key] + 1))
        region_id = (entry.get("region") or {}).get("region_id")
        if region_id:
            body += f"\nRegion {region_id}"
        sentences = {sentence.sentence_id: sentence for sentence in segment_evidence_sentences(body)}
        focus = [{"start": sentences[sid].start, "end": sentences[sid].end} for sid in excerpt]
        url = (entry.get("evidence") or {}).get("canonical_source_url") or f"https://replay.invalid/{candidate_id}"
        candidate = CanonicalCandidate(
            candidate_id=candidate_id, title="replay", url=url, publisher="replay",
            published_at=entry.get("published_at") or "", source_type="replay",
        )
        evidence = EvidenceResult(
            candidate_id=candidate_id, state=EvidenceState.READY, canonical_source_url=url, source_type="replay",
            substantive_content=body, provenance={}, reject_reason=None, identity_facts=_region(entry.get("region"), body),
        )
        scope = ScopeResult(candidate_id, ScopeState.IN_SCOPE, provenance={"candidate_event_focus": focus})
        temporal = TemporalResult(candidate_id, True, diagnostic=TemporalDiagnostic.NONE)
        records.append(EventIdentityRecord(candidate, evidence, scope, temporal))
    return records


class RecordedAdvisor:
    """Answers each grouping request with the exchange the run recorded for it."""

    def __init__(self, exchanges: Sequence[Mapping[str, Any]]) -> None:
        self._exchanges = {exchange["subject"]: exchange for exchange in exchanges}

    def __call__(self, request: EventIdentityGroupingRequest) -> object:
        exchange = self._exchanges.get(request.batch_id)
        if exchange is None or bool(exchange["confirmation"]) != request.confirmation:
            raise ReplayMismatch(f"no recorded exchange for {request.batch_id}")
        failure = exchange.get("failure")
        if failure is not None:
            if failure["kind"] == "TECHNICAL":
                raise SemanticProviderTechnicalFailure(
                    failure["failure_class"], attempts=int(failure["attempts"]), transient=bool(failure["transient"])
                )
            raise EventIdentityProposalViolation(failure["failure_class"])
        recorded_candidate = dict(exchange["records"])
        replay_id = {record.candidate_id: record.record_id for record in request.records}
        if set(recorded_candidate.values()) != set(replay_id):
            raise ReplayMismatch(f"{request.batch_id} names other records than the run recorded")
        return {
            "groups": [
                {
                    "members": [
                        {**member, "record_id": replay_id[recorded_candidate[member["record_id"]]]}
                        for member in group["members"]
                    ]
                }
                for group in exchange["response"]["groups"]
            ]
        }


def replay(audit: Mapping[str, Any]) -> EventIdentityRun:
    """Run the unchanged EventIdentity owner on the audited records and recorded answers."""

    return EventIdentity(RecordedAdvisor(audit.get("event_identity_exchanges") or ())).evaluate(records_from_audit(audit))


def audited_groups(audit: Mapping[str, Any]) -> set[tuple[str, ...]]:
    reached = {entry["candidate_id"] for entry in audit["candidates"] if entry.get("event_identity")}
    return {
        tuple(sorted(event["member_candidate_ids"]))
        for event in audit["events"]
        if set(event["member_candidate_ids"]) <= reached
    }


def score(groups: Sequence[Sequence[str]], labels: Mapping[str, str]) -> dict[str, Any]:
    """Labelled same-occurrence pairs merged and missed; differently labelled pairs merged."""

    merged = {tuple(sorted(pair)) for group in groups for pair in combinations(group, 2)}
    labelled = sorted(candidate for candidate in labels if any(candidate in group for group in groups))
    same = {tuple(sorted(pair)) for pair in combinations(labelled, 2) if labels[pair[0]] == labels[pair[1]]}
    different = {tuple(sorted(pair)) for pair in combinations(labelled, 2) if labels[pair[0]] != labels[pair[1]]}
    return {
        "same_pairs": len(same),
        "same_pairs_merged": len(same & merged),
        "same_pairs_missed": sorted(same - merged),
        "different_pairs_merged": sorted(different & merged),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("audit", type=Path)
    parser.add_argument("--labels", type=Path)
    args = parser.parse_args(argv)
    audit = json.loads(args.audit.read_text(encoding="utf-8"))
    run = replay(audit)
    replayed = {group.member_candidate_ids for group in run.groups}
    expected = audited_groups(audit)
    reproduced = replayed == expected
    print(json.dumps({"reproduced": reproduced, "events": len(replayed), "differences": sorted(replayed ^ expected)}, indent=1))
    if args.labels:
        labels = json.loads(args.labels.read_text(encoding="utf-8"))
        print(json.dumps(score([group.member_candidate_ids for group in run.groups], labels), indent=1))
    return 0 if reproduced else 1


if __name__ == "__main__":
    raise SystemExit(main())
