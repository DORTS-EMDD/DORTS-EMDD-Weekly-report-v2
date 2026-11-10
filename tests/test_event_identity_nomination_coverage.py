"""Contract checks for the offline nomination-coverage artifact."""

from __future__ import annotations

import json
from pathlib import Path


ARTIFACT = (
    Path(__file__).resolve().parents[1]
    / "acceptance"
    / "phase_b_audit"
    / "event_identity_nomination_coverage.json"
)


def test_run39_rc52_pair_coverage_is_reproducible_and_observer_only():
    report = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    run39 = report["run39"]
    metrics = run39["metrics"]

    assert report["owner"] == "EventIdentity"
    assert report["production_prompt"] == "event-identity-grouping-v10"
    assert report["new_maiagent_calls"] == 0
    assert report["production_eventidentity_changed"] is False
    assert report["production_scope_changed"] is False
    assert report["downstream_rescue_added"] is False
    assert report["second_owner_added"] is False
    assert report["golden_expected_outcome_changed"] is False
    assert run39["recorded_replay"] == {"reproduced": True, "events": 81, "differences": []}
    assert run39["labelled_same_occurrence_pairs"] == 21
    assert run39["labelled_different_occurrence_pairs"] == 0
    assert metrics["same_nominated_0_of_3"] == 5
    assert metrics["same_nominated_1_of_3"] == 3
    assert metrics["same_nominated_2_of_3"] == 3
    assert metrics["same_nominated_3_of_3"] == 10
    assert metrics["same_with_lt2_joint_nominations"] == 8
    assert metrics["same_reached_confirmation"] == 16
    assert metrics["same_confirmation_splits"] == 5
    assert metrics["same_rc52_not_reached"] == 8
    assert metrics["same_final_same"] == 10
    assert metrics["technical_nomination_losses"] == 1
    assert metrics["valid_semantic_nomination_misses"] == 7
    assert metrics["earliest_failure_counts"] == {
        "COMPLETE_LINK": 3,
        "CONFIRMATION": 1,
        "NOMINATION_COVERAGE": 7,
        "NO_FAILURE": 10,
    }
    assert all(
        all(row["valid_eventidentity_inputs_by_procedure"].values())
        and all(row["legitimate_batch_opportunity_by_procedure"].values())
        for row in run39["pairs"]
    )


def test_legacy_labelled_sources_are_not_silently_pooled_with_rc52():
    report = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    historical = report["historical_labelled"]["runs"]
    assert historical["40999869397"]["same_with_lt2_joint_nominations"] == 9
    assert historical["41018554355"]["nomination_observed_same_pairs"] == 0
    assert report["excluded_historical_evidence"]["used_for_truth_metrics"] is False
    assert report["decision"]["result"] == "INCONCLUSIVE"
