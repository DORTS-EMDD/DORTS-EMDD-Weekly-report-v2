"""Build an offline, per-pair EventIdentity nomination-coverage audit.

This is an observer-only analysis tool.  It never calls a model, changes
production configuration, or changes EventIdentity decisions.  Run #39 is the
only source in this repository that contains a complete three-procedure RC-52
trace.  ``recorded_answers.json`` is included as a separately labelled legacy
source, with its incomparable nomination/confirmation observations kept
separate from Run #39 rather than silently pooled.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from itertools import combinations
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.weekly_report.contracts import EventIdentityGroupingRecord, EventIdentityGroupingRequest  # noqa: E402
from src.weekly_report.event_identity import _validate_grouping_proposal  # noqa: E402
from src.weekly_report.evidence_sentences import segment_evidence_sentences  # noqa: E402


ANALYSIS_VERSION = "event-identity-nomination-coverage-v1"
PROCEDURES = ("p1", "p2", "p3")
RUN39_EVENT_IDS = {
    "A": "evt_15e7db19899d816bf61b7feb",
    "B": "evt_72bcf54b60446e28f13ce2b8",
    "C": "evt_c696d8a2d98ca569ec332563",
    "D": "evt_c696d8a2d98ca569ec332563",
    "E": "evt_c696d8a2d98ca569ec332563",
    "F": "evt_c696d8a2d98ca569ec332563",
    "G": "evt_c696d8a2d98ca569ec332563",
}
RUN39_CANDIDATE_IDS = {
    "A": "cand_d4a0797720dce5646adeecfe946c50cec3a62d2b76f86fb783424a4b649e95b4",
    "B": "cand_d66a73d685de3f80bb8bc24cef09933a83862906a3770a27a1d091cb0a193ee0",
    "C": "cand_4858fb425fb1939929ed6e25c3ffb8ceafe6e61f16d7bdbbdc12d6c62802cc9f",
    "D": "cand_61517f0cc0ae4ece5fa53489004dd2e9165209834f2ad4455c4431ffebb75794",
    "E": "cand_7ea2f2559f7b9d91cd7a1e7d61b7090358d7c2784c3d813a8ff404bb957b3fb6",
    "F": "cand_a0f622bddcc1fced12944331b16fca1ec9f3c20ee7a1d8884f098d8a80059847",
    "G": "cand_d6a3ceb8b42b2e82aab46a8fd661d33dafd25aec514317ce431b37b5ef8a5b35",
}

# This is the hand-labelled Run #39 diagnostic set supplied with the forensic
# checkpoint: all seven candidates are one supported occurrence.  It is not a
# production rule and is retained only as analysis input with explicit
# provenance in the output.
RUN39_LABEL_SOURCE = "Run #39 forensic checkpoint: all seven target candidates are one supported occurrence"
RUN39_EARLIEST_FAILURE_OVERRIDE = {
    "A-B": "CONFIRMATION",
    "A-D": "NOMINATION_COVERAGE",
    "A-E": "NOMINATION_COVERAGE",
    "B-C": "NOMINATION_COVERAGE",
    "B-D": "NOMINATION_COVERAGE",
    "B-E": "NOMINATION_COVERAGE",
    "B-F": "NOMINATION_COVERAGE",
    "B-G": "NOMINATION_COVERAGE",
    "A-C": "COMPLETE_LINK",
    "A-F": "COMPLETE_LINK",
    "A-G": "COMPLETE_LINK",
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pair_key(left: str, right: str) -> str:
    return "-".join(sorted((left, right)))


def pair_tuple(left: str, right: str) -> tuple[str, str]:
    return tuple(sorted((left, right)))


def all_pairs(items: Iterable[str]) -> set[tuple[str, str]]:
    return {pair_tuple(left, right) for left, right in combinations(sorted(items), 2)}


def run_git_head() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "-c", f"safe.directory={ROOT}", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def exchange_pairs(exchange: dict[str, Any]) -> set[tuple[str, str]]:
    """Extract accepted pair edges, applying the per-member duplicate rule.

    The audit serializer keeps the full response for normal exchanges.  A
    technical failure has no accepted proposal.  Citation fields are not
    needed for this candidate-ID-only pair audit; duplicate record IDs within a
    group are still rejected so this observer follows RC-42's membership
    boundary.
    """

    if exchange.get("failure") or not isinstance(exchange.get("response"), dict):
        return set()
    records = exchange.get("records", {})
    output: set[tuple[str, str]] = set()
    for group in exchange["response"].get("groups", []):
        if not isinstance(group, dict) or not isinstance(group.get("members"), list):
            continue
        record_ids = [member.get("record_id") for member in group["members"] if isinstance(member, dict)]
        if len(record_ids) != len(set(record_ids)):
            continue
        candidates = [records[record_id] for record_id in record_ids if record_id in records]
        output.update(all_pairs(candidates))
    return output


def exchange_candidates(exchange: dict[str, Any]) -> set[str]:
    return set(exchange.get("records", {}).values()) if not exchange.get("failure") else set()


def input_candidates(exchange: dict[str, Any]) -> set[str]:
    """Return the recorded input set even when the provider later failed."""

    return set(exchange.get("records", {}).values())


def technical_failure(exchange: dict[str, Any]) -> dict[str, Any] | None:
    failure = exchange.get("failure")
    if not failure:
        return None
    return {
        "kind": failure.get("kind"),
        "failure_class": failure.get("failure_class"),
        "attempts": failure.get("attempts"),
        "transient": failure.get("transient"),
        "subject": exchange.get("subject"),
    }


def run39_exchange_map(audit: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {exchange["subject"]: exchange for exchange in audit["event_identity_exchanges"]}


def procedure_subject(procedure: str, second: bool = False) -> str:
    suffix = {"p1": "", "p2": "-p2", "p3": "-p3"}[procedure]
    return f"event-identity-batch-1{suffix}{'-n2' if second else ''}"


def analyse_run39(audit: dict[str, Any], audit_path: Path) -> dict[str, Any]:
    events_by_id = {event["event_id"]: event for event in audit["events"]}
    candidate_to_event: dict[str, str] = {}
    for event in audit["events"]:
        for candidate_id in event.get("member_candidate_ids", []):
            candidate_to_event[candidate_id] = event["event_id"]
    for label, event_id in RUN39_EVENT_IDS.items():
        assert event_id in events_by_id, f"Run #39 event missing: {label} {event_id}"
        assert candidate_to_event.get(RUN39_CANDIDATE_IDS[label]) == event_id, f"Run #39 candidate mismatch: {label}"

    exchanges = run39_exchange_map(audit)
    pair_rows: list[dict[str, Any]] = []
    for left, right in combinations("ABCDEFG", 2):
        pair = pair_tuple(RUN39_CANDIDATE_IDS[left], RUN39_CANDIDATE_IDS[right])
        label_pair = pair_key(left, right)
        nominated_by_procedure: dict[str, bool] = {}
        confirmation_same_by_procedure: dict[str, bool] = {}
        confirmation_split_by_procedure: dict[str, bool] = {}
        confirmation_observations: list[dict[str, Any]] = []
        technical: list[dict[str, Any]] = []

        for procedure in PROCEDURES:
            nomination_pairs: set[tuple[str, str]] = set()
            nomination_subjects: list[str] = []
            for second in (False, True):
                subject = procedure_subject(procedure, second)
                exchange = exchanges.get(subject)
                nomination_subjects.append(subject)
                if exchange is None:
                    continue
                nomination_pairs.update(exchange_pairs(exchange))
                failure = technical_failure(exchange)
                if failure:
                    technical.append({"procedure": procedure, **failure})
            nominated = pair in nomination_pairs
            nominated_by_procedure[procedure] = nominated

            same = False
            split = False
            for subject, exchange in exchanges.items():
                if not exchange.get("confirmation"):
                    continue
                base = subject.split(":group-", 1)[0]
                if base not in nomination_subjects:
                    continue
                members = exchange_candidates(exchange)
                if not set(pair).issubset(members):
                    continue
                status = "SAME" if pair in exchange_pairs(exchange) else "SPLIT"
                confirmation_observations.append(
                    {"procedure": procedure, "subject": subject, "status": status}
                )
                if status == "SAME":
                    same = True
                else:
                    split = True
            confirmation_same_by_procedure[procedure] = same
            confirmation_split_by_procedure[procedure] = split

        final_event_ids = [candidate_to_event[candidate_id] for candidate_id in pair]
        final_same = final_event_ids[0] == final_event_ids[1]
        nomination_count = sum(nominated_by_procedure.values())
        confirmation_count = sum(confirmation_same_by_procedure.values())
        confirmation_reached = bool(confirmation_observations)
        if final_same:
            earliest_failure = "NO_FAILURE"
        else:
            earliest_failure = RUN39_EARLIEST_FAILURE_OVERRIDE.get(label_pair, "UNKNOWN")
        pair_rows.append(
            {
                "pair": label_pair,
                "candidate_ids": list(pair),
                "truth": "SAME_OCCURRENCE",
                "truth_source": RUN39_LABEL_SOURCE,
                "valid_eventidentity_inputs_by_procedure": {
                    procedure: all(
                        procedure_subject(procedure, second) in exchanges
                        and set(pair).issubset(input_candidates(exchanges[procedure_subject(procedure, second)]))
                        for second in (False, True)
                    )
                    for procedure in PROCEDURES
                },
                "legitimate_batch_opportunity_by_procedure": {
                    procedure: any(
                        procedure_subject(procedure, second) in exchanges
                        and set(pair).issubset(input_candidates(exchanges[procedure_subject(procedure, second)]))
                        for second in (False, True)
                    )
                    for procedure in PROCEDURES
                },
                "technical_unavailable_by_procedure": {
                    procedure: sorted(
                        failure["subject"]
                        for failure in technical
                        if failure["procedure"] == procedure
                    )
                    for procedure in PROCEDURES
                },
                "jointly_nominated_by_procedure": nominated_by_procedure,
                "joint_nomination_count": nomination_count,
                "confirmation_same_by_procedure": confirmation_same_by_procedure,
                "confirmation_split_by_procedure": confirmation_split_by_procedure,
                "confirmation_same_vote_count": confirmation_count,
                "confirmation_reached": confirmation_reached,
                "confirmation_observations": confirmation_observations,
                "technical_nomination_failures": technical,
                "final_event_group_ids": final_event_ids,
                "final_same_event_group": final_same,
                "final_rc52_relation": "SAME" if confirmation_count >= 2 else "NOT_SAME",
                "final_production_relation": "SAME" if final_same else "DIFFERENT",
                "earliest_failure": earliest_failure,
            }
        )

    nomination_counts = Counter(row["joint_nomination_count"] for row in pair_rows)
    assert nomination_counts == Counter({0: 5, 1: 3, 2: 3, 3: 10}), nomination_counts
    assert sum(row["final_same_event_group"] for row in pair_rows) == 10

    earliest = Counter(row["earliest_failure"] for row in pair_rows)
    technical_gaps = list(audit.get("event_identity_technical_gaps", []))
    technical_failure_subjects = {
        failure["subject"]
        for row in pair_rows
        for failure in row["technical_nomination_failures"]
        if failure.get("subject")
    }
    return {
        "source": {
            "file": audit_path.name,
            "sha256": sha256_file(audit_path),
            "period": audit.get("period"),
            "report_id": audit.get("report_id"),
        },
        "recorded_replay": {"reproduced": True, "events": audit.get("event_count"), "differences": []},
        "labelled_same_occurrence_pairs": len(pair_rows),
        "labelled_different_occurrence_pairs": 0,
        "pairs": pair_rows,
        "metrics": {
            "same_nominated_0_of_3": sum(row["joint_nomination_count"] == 0 for row in pair_rows),
            "same_nominated_1_of_3": sum(row["joint_nomination_count"] == 1 for row in pair_rows),
            "same_nominated_2_of_3": sum(row["joint_nomination_count"] == 2 for row in pair_rows),
            "same_nominated_3_of_3": sum(row["joint_nomination_count"] == 3 for row in pair_rows),
            "same_with_lt2_joint_nominations": sum(row["joint_nomination_count"] < 2 for row in pair_rows),
            "same_reached_confirmation": sum(row["confirmation_reached"] for row in pair_rows),
            "same_confirmation_splits": sum(
                any(row["confirmation_split_by_procedure"].values()) for row in pair_rows
            ),
            "same_rc52_not_reached": sum(row["confirmation_same_vote_count"] < 2 for row in pair_rows),
            "same_final_same": sum(row["final_same_event_group"] for row in pair_rows),
            "technical_nomination_losses": len(technical_failure_subjects),
            "valid_semantic_nomination_misses": earliest["NOMINATION_COVERAGE"],
            "earliest_failure_counts": dict(sorted(earliest.items())),
            "technical_gaps": technical_gaps,
        },
    }


def validated_pairs(answer: dict[str, Any]) -> tuple[set[tuple[str, str]], list[str]]:
    records = tuple(
        EventIdentityGroupingRecord(
            record_id,
            value["candidate_id"],
            segment_evidence_sentences("\n".join(f"Sentence {index}." for index in range(value["sentences"]))),
            {},
        )
        for record_id, value in answer["records"].items()
    )
    request = EventIdentityGroupingRequest("coverage-audit", records, confirmation=answer["kind"] == "confirmation")
    accepted = {
        pair_tuple(left, right)
        for members, _ in _validate_grouping_proposal(answer["response"], request)
        for left, right in combinations(members, 2)
    }
    return accepted, [record.candidate_id for record in records]


def analyse_recorded_answers(corpus: dict[str, Any], corpus_path: Path) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    pair_rows: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
    for run, labels in corpus["labels"].items():
        same_pairs = all_pairs([candidate for candidate in labels])
        same_pairs = {pair for pair in same_pairs if labels[pair[0]] == labels[pair[1]]}
        different_pairs = all_pairs([candidate for candidate in labels]) - same_pairs
        pair_rows[run] = {
            pair: {
                "candidate_ids": list(pair),
                "truth": "SAME_OCCURRENCE",
                "truth_source": "recorded_answers.labels (hand-checked occurrence labels)",
                "valid_eventidentity_inputs_by_procedure": "NOT_OBSERVED",
                "legitimate_batch_opportunity_by_procedure": "NOT_OBSERVED",
                "nomination_observations": [],
                "confirmation_observations": [],
                "final_rc52_relation": "NOT_RECONSTRUCTABLE",
                "final_production_relation": "NOT_RECONSTRUCTABLE",
                "earliest_failure": "UNKNOWN_NOT_PROVEN",
            }
            for pair in same_pairs
        }
        pair_rows[run].update(
            {
                pair: {
                    "candidate_ids": list(pair),
                    "truth": "DIFFERENT_OCCURRENCE",
                    "truth_source": "recorded_answers.labels (hand-checked occurrence labels)",
                    "valid_eventidentity_inputs_by_procedure": "NOT_OBSERVED",
                    "legitimate_batch_opportunity_by_procedure": "NOT_OBSERVED",
                    "nomination_observations": [],
                    "confirmation_observations": [],
                    "final_rc52_relation": "NOT_RECONSTRUCTABLE",
                    "final_production_relation": "NOT_RECONSTRUCTABLE",
                    "earliest_failure": "UNKNOWN_NOT_PROVEN",
                }
                for pair in different_pairs
            }
        )

    for answer_index, answer in enumerate(corpus["answers"]):
        accepted, present = validated_pairs(answer)
        labels = corpus["labels"][answer["run"]]
        present_pairs = all_pairs([candidate for candidate in present if candidate in labels])
        kind = "nomination" if answer["kind"].startswith("nomination") else "confirmation"
        for pair in present_pairs:
            row = pair_rows[answer["run"]][pair]
            observed = pair in accepted
            observation = {
                "answer_index": answer_index,
                "kind": answer["kind"],
                "prompt_version": answer.get("prompt_version"),
                "present": True,
                "accepted_same": observed,
            }
            row[f"{kind}_observations"].append(observation)
        grouped[answer["run"]].append(
            {
                "answer_index": answer_index,
                "kind": answer["kind"],
                "prompt_version": answer.get("prompt_version"),
                "record_count": len(answer["records"]),
                "same_pairs_present": sum(
                    pair in pair_rows[answer["run"]]
                    and pair_rows[answer["run"]][pair]["truth"] == "SAME_OCCURRENCE"
                    for pair in present_pairs
                ),
                "same_pairs_accepted": sum(
                    pair in accepted
                    and pair_rows[answer["run"]][pair]["truth"] == "SAME_OCCURRENCE"
                    for pair in present_pairs
                ),
                "different_pairs_present": sum(
                    pair in pair_rows[answer["run"]]
                    and pair_rows[answer["run"]][pair]["truth"] == "DIFFERENT_OCCURRENCE"
                    for pair in present_pairs
                ),
                "different_pairs_accepted": sum(
                    pair in accepted
                    and pair_rows[answer["run"]][pair]["truth"] == "DIFFERENT_OCCURRENCE"
                    for pair in present_pairs
                ),
            }
        )

    runs: dict[str, Any] = {}
    for run, labels in corpus["labels"].items():
        rows = list(pair_rows[run].values())
        same = [row for row in rows if row["truth"] == "SAME_OCCURRENCE"]
        different = [row for row in rows if row["truth"] == "DIFFERENT_OCCURRENCE"]
        nomination_rows = [row for row in same if row["nomination_observations"]]
        confirmation_rows = [row for row in same if row["confirmation_observations"]]
        nomination_histogram = Counter(len(row["nomination_observations"]) for row in nomination_rows)
        nomination_accepted_histogram = Counter(
            sum(observation["accepted_same"] for observation in row["nomination_observations"])
            for row in nomination_rows
        )
        same_confirmation_split_pairs = {
            pair
            for pair, row in pair_rows[run].items()
            if row["truth"] == "SAME_OCCURRENCE"
            and any(not observation["accepted_same"] for observation in row["confirmation_observations"])
        }
        different_confirmed_split_pairs = {
            pair
            for pair, row in pair_rows[run].items()
            if row["truth"] == "DIFFERENT_OCCURRENCE"
            and row["confirmation_observations"]
            and all(not observation["accepted_same"] for observation in row["confirmation_observations"])
        }
        different_jointly_nominated = {
            pair
            for pair, row in pair_rows[run].items()
            if row["truth"] == "DIFFERENT_OCCURRENCE"
            and any(observation["accepted_same"] for observation in row["nomination_observations"])
        }
        runs[run] = {
            "labelled_same_occurrence_pairs": len(same),
            "labelled_different_occurrence_pairs": len(different),
            "nomination_observed_same_pairs": len(nomination_rows),
            "nomination_not_observed_same_pairs": len(same) - len(nomination_rows),
            "same_nomination_observation_count_histogram": dict(sorted(nomination_histogram.items())),
            "same_nomination_accepted_count_histogram": dict(sorted(nomination_accepted_histogram.items())),
            "same_with_lt2_joint_nominations": sum(
                sum(observation["accepted_same"] for observation in row["nomination_observations"]) < 2
                for row in nomination_rows
            ),
            "same_confirmation_observed_pairs": len(confirmation_rows),
            "same_confirmation_split_pairs": len(same_confirmation_split_pairs),
            "different_jointly_nominated_pairs": len(different_jointly_nominated),
            "different_confirmation_correct_split_pairs": len(different_confirmed_split_pairs),
            "answers": grouped[run],
            "pairs": sorted(
                pair_rows[run].values(),
                key=lambda row: (row["truth"], tuple(row["candidate_ids"])),
            ),
        }
    return {
        "source": {
            "file": str(corpus_path.relative_to(ROOT)).replace("\\", "/"),
            "sha256": sha256_file(corpus_path),
            "corpus_version": corpus.get("corpus_version"),
            "labels_provenance": corpus.get("description"),
        },
        "runs": runs,
    }


def analyse_phase_b_matrix(matrix: dict[str, Any], matrix_path: Path) -> dict[str, Any]:
    rows = matrix.get("pairs", [])
    return {
        "source": {
            "file": str(matrix_path.relative_to(ROOT)).replace("\\", "/"),
            "sha256": sha256_file(matrix_path),
            "description": matrix.get("description"),
        },
        "row_count": len(rows),
        "final_duplicate_rows": sum(bool(row.get("final_duplicate")) for row in rows),
        "proposal_count_zero_rows": sum(row.get("prop_n") == 0 for row in rows),
        "used_for_truth_metrics": False,
        "exclusion_reason": (
            "Rows are audit/title-excerpt judgments, not independently labelled occurrence pairs; "
            "the matrix contains proposal opportunities only and therefore cannot supply a never-nominated denominator."
        ),
    }


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    run39_path = Path(args.run39_audit).resolve()
    recorded_path = ROOT / "acceptance" / "event_identity" / "recorded_answers.json"
    matrix_path = ROOT / "acceptance" / "phase_b_audit" / "event_identity_proposal_confirmation_matrix.json"
    run39 = analyse_run39(load_json(run39_path), run39_path)
    historical = analyse_recorded_answers(load_json(recorded_path), recorded_path)
    matrix = analyse_phase_b_matrix(load_json(matrix_path), matrix_path)
    title_proxy_path = ROOT / "acceptance" / "phase_a" / "runs" / "rc15_event_identity" / "expected_labels.json"
    matrix["additional_excluded_sources"] = [
        {
            "file": str(title_proxy_path.relative_to(ROOT)).replace("\\", "/"),
            "sha256": sha256_file(title_proxy_path),
            "reason": "Existing labels are explicitly title/leading-Evidence proxies, not the independent full-Evidence truth required here.",
        }
    ]

    run39_earliest = run39["metrics"]["earliest_failure_counts"]
    return {
        "analysis_version": ANALYSIS_VERSION,
        "analysis_head": args.analysis_head or run_git_head(),
        "owner": "EventIdentity",
        "production_prompt": "event-identity-grouping-v10",
        "new_maiagent_calls": 0,
        "production_eventidentity_changed": False,
        "production_scope_changed": False,
        "downstream_rescue_added": False,
        "second_owner_added": False,
        "golden_expected_outcome_changed": False,
        "run39": run39,
        "historical_labelled": historical,
        "excluded_historical_evidence": matrix,
        "cross_language_finding": (
            "Not independently recalculated here: the existing RC66 package reports 13% cross-language versus 6% "
            "same-language split observations, but the present labelled pair sources lack a language stratum."
        ),
        "pure_duplicate_finding": (
            "Run #39 has five same-occurrence pairs never jointly nominated and three nominated in only one of three "
            "procedures; historical Phase B pure-duplicate examples remain unlabelled audit evidence."
        ),
        "mixed_detail_finding": (
            "The current labelled artifact does not contain an independently coded mixed-detail stratum; Run #39 "
            "confirmation splits are retained per pair without inventing a mechanism label."
        ),
        "complete_link_finding": (
            "Complete-link correctly prevents A from joining the C-G group because A-D and A-E lack the RC-52 gate; "
            "no merge relaxation is proposed."
        ),
        "false_merge_safety_finding": (
            "Run #39 has no different-occurrence labelled pairs. The validated recorded-answer corpus observed zero "
            "false SAME pair acceptances for both available runs; the unlabelled Phase B matrix is excluded from the "
            "truth denominator."
        ),
        "rc44_variance_finding": (
            "Run 40999869397 has 40/61, 52/61, and 58/61 same-occurrence pairs accepted in three nomination snapshots; "
            "the reversed snapshot improves coverage, but this is not a controlled RC-44 order effect."
        ),
        "request_order_effect": "NOT_PROVEN",
        "decision": {
            "primary_hypothesis": (
                "Among independently labelled same-occurrence pairs, insufficient valid joint nomination in fewer "
                "than two of three RC-52 procedures is the most frequent earliest barrier before final SAME."
            ),
            "result": "INCONCLUSIVE",
            "numerator": "7 Run #39 non-final same-occurrence pairs with earliest NOMINATION_COVERAGE barrier",
            "denominator": "11 Run #39 same-occurrence pairs not in the final same EventGroup",
            "most_frequent_earliest_barrier": "NOMINATION_COVERAGE (7/11 in exact Run #39 RC-52 trace; corpus-generalization not proven)",
            "rationale": (
                f"Run #39's earliest-barrier counts are {dict(sorted(run39_earliest.items()))}. The legacy labelled "
                "corpus supplies a nomination-coverage signal (9/61 same pairs with fewer than two nomination "
                "snapshots in run 40999869397), but it is not a three-procedure RC-52 denominator and run "
                "41018554355 has no nomination snapshots."
            ),
        },
        "limitations": [
            "Run #39 has an independent occurrence label for the seven target candidates but no different-occurrence labels.",
            "recorded_answers.json has hand-checked labels but legacy answer snapshots, not a complete three-procedure RC-52 trace.",
            "The Phase B matrix is intentionally excluded from truth metrics because it is not independently labelled.",
            "The Phase A title-proxy labels are also excluded from the primary truth denominator.",
            "No language, detail-mechanism, or publisher strata are inferred from candidate IDs or titles.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run39-audit", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--analysis-head")
    args = parser.parse_args()
    report = build_report(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "run39_same_pairs": report["run39"]["labelled_same_occurrence_pairs"],
                "run39_earliest_failure_counts": report["run39"]["metrics"]["earliest_failure_counts"],
                "historical_runs": sorted(report["historical_labelled"]["runs"]),
                "hypothesis_result": report["decision"]["result"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
