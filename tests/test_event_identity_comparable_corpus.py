"""Contract checks for the comparable multi-run EventIdentity corpus."""

from __future__ import annotations

import json
from pathlib import Path


ARTIFACT = (
    Path(__file__).resolve().parents[1]
    / "acceptance"
    / "phase_b_audit"
    / "event_identity_comparable_corpus.json"
)


def test_only_complete_independently_labelled_run_enters_primary_denominator():
    report = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    inventory = report["run_inventory"]
    assert report["new_maiagent_calls"] == 0
    assert report["runs_reviewed"] == 24
    assert [row["run"] for row in inventory if row["classification"] == "COMPARABLE_FULL"] == [39]
    assert [row["run"] for row in inventory if row["classification"] == "COMPARABLE_PARTIAL"] == [
        19,
        20,
        24,
        25,
        26,
        29,
        30,
        31,
        32,
        33,
        34,
    ]
    assert report["primary_comparable_denominator"]["same_pair_count"] == 21
    assert report["primary_comparable_denominator"]["different_pair_count"] == 0
    assert report["primary_comparable_denominator"]["independent_same_occurrence_clusters"] == 1
    assert report["primary_comparable_denominator"]["independent_different_occurrence_clusters"] == 0
    assert report["decision"]["result"] == "INCONCLUSIVE"
    assert report["decision"]["numerator"] == 7
    assert report["decision"]["denominator"] == 11


def test_secondary_and_unlabelled_evidence_are_explicitly_excluded():
    report = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    primary = report["primary_comparable_denominator"]
    assert report["secondary_partial_labelled_pairs"]["pair_count"] == 700
    assert report["secondary_partial_labelled_pairs"]["used_in_primary_hypothesis"] is False
    assert report["excluded_unlabelled_matrix"]["row_count"] == 1557
    assert report["excluded_unlabelled_matrix"]["used_in_primary_hypothesis"] is False
    assert primary["earliest_failure_counts"] == {
        "nomination_coverage": 7,
        "confirmation": 1,
        "technical": 0,
        "rc52_aggregation_after_sufficient_nomination": 0,
        "other": 3,
        "unknown": 0,
    }
    assert report["rc44_variance"]["primary_denominator_eligible"] is False
    assert report["architecture_acceptance"]["observer_only"] is True
