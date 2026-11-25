"""RC-85 (section A.66): the Scope correction request carries Python-computed label locations.

Two Monday Run 45103217994 records are reproduced in shape with synthetic text
(the public repository holds no source articles):

* VårtOslo "Trikk sporet av nederst på Løkka": target_system cited [S3], while
  the target and system labels occur only in S1, S4, S6, S10, S12 and S13; the
  correction (TARGET_SYSTEM_CONTAINMENT) was still violated.
* Urban Transport Magazine "Stadler ... Helsinki": target_system cited [S3],
  while the system label occurs only in S2 and S12; the first correction was
  EVENT_FOCUS_CONTAINMENT.

The request now names those sentence IDs. The helper's answers are scripted;
Python still validates the corrected proposal exactly as before.
"""

from __future__ import annotations

import pytest

from src.weekly_report.contracts import EvidenceResult, EvidenceState, ScopeState
from src.weekly_report.scope_classifier import (
    SCOPE_PROPOSAL_SCHEMA_VERSION,
    ScopeClassifier,
    ScopeProposalViolation,
)

OSLO = " ".join(
    [
        "Trikken på linje 11 fra Sporveien sporet av nederst på Løkka.",  # S1
        "Ingen ble skadet.",  # S2
        "Hendelsen skjedde rett etter klokken tre.",  # S3
        "Trikken på linje 11 kjøres av Sporveien.",  # S4
        "Politiet kom raskt til stedet.",  # S5
        "Sporveien sier at trikken på linje 11 sto i ro i flere timer.",  # S6
        "Det var store forsinkelser.",  # S7
        "Busser erstattet trikkene.",  # S8
        "Årsaken er ikke kjent.",  # S9
        "Sporveien undersøker hvorfor trikken på linje 11 sporet av.",  # S10
        "Passasjerene ble flyttet.",  # S11
        "Trikken på linje 11 er tilbake i drift, opplyser Sporveien.",  # S12
        "Sporveien beklager forsinkelsene for trikken på linje 11.",  # S13
    ]
)
HELSINKI = " ".join(
    [
        "Stadler and the city operator signed a contract for 63 TANGO trams.",  # S1
        "The TANGO trams will run on the Helsinki tram network.",  # S2
        "The contract also covers service for more than 30 years.",  # S3
        "An option allows up to 120 more vehicles.",  # S4
        "The first vehicle is due in 2029.",  # S5
        "A competing bidder had challenged the award.",  # S6
        "The courts upheld the decision.",  # S7
        "The new vehicles replace older ones.",  # S8
        "They will be built in Switzerland.",  # S9
        "Testing follows delivery.",  # S10
        "Two new lines opened last week.",  # S11
        "The Helsinki tram network now has fourteen lines.",  # S12
    ]
)


def _proposal(*, action, target, system, focus, action_target, target_system):
    return {
        "candidate_id": "C1",
        "schema_version": SCOPE_PROPOSAL_SCHEMA_VERSION,
        "event_focus": {"status": "RESOLVED", "sentence_ids": list(focus)},
        "action": {"label": action},
        "target": {"label": target},
        "system": {"label": system},
        "eligible_mode_family": "TRAM",
        "action_target": {"status": "ESTABLISHED", "relation": "AFFECTS", "sentence_ids": list(action_target)},
        "target_system": {"status": "ESTABLISHED", "relation": "PART_OF", "sentence_ids": list(target_system)},
        "ambiguity": {"status": "NONE", "sentence_ids": []},
        "noneligible_relation": {"status": "ABSENT", "sentence_ids": []},
        "noneligible_kind": "NONE",
        "event_status": "ASSERTED",
        "decision": "IN_SCOPE_SUPPORT",
    }


class _Helper:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        return self.answers[min(len(self.requests), len(self.answers)) - 1]


def _classify(helper, content):
    evidence = EvidenceResult(candidate_id="C1", state=EvidenceState.READY, substantive_content=content, provenance={})
    return ScopeClassifier(helper).classify(evidence)


def _oslo(target_system):
    return _proposal(action="sporet av", target="trikken på linje 11", system="Sporveien",
                     focus=("S1", "S2", "S3"), action_target=("S1",), target_system=target_system)


def _helsinki(target_system):
    return _proposal(action="signed", target="TANGO trams", system="Helsinki tram network",
                     focus=("S1",), action_target=("S1",), target_system=target_system)


def test_the_oslo_correction_names_where_the_labels_are():
    helper = _Helper(_oslo(("S3",)), _oslo(("S1",)))
    result = _classify(helper, OSLO)
    correction = helper.requests[1].as_payload()["correction"]
    assert correction["violated_rule"] == "TARGET_SYSTEM_CONTAINMENT"
    located = ["S1", "S4", "S6", "S10", "S12", "S13"]
    assert correction["label_locations"]["target.label"] == located
    assert correction["label_locations"]["system.label"] == located
    assert "label_locations_note" in correction
    # The corrected proposal is validated by Python as before.
    assert result.state is ScopeState.IN_SCOPE
    assert result.provenance["scope_correction"]["outcome"] == "ACCEPTED"


def test_the_helsinki_correction_names_where_the_system_label_is():
    helper = _Helper(_helsinki(("S3",)), _helsinki(("S1", "S2")))
    result = _classify(helper, HELSINKI)
    correction = helper.requests[1].as_payload()["correction"]
    assert correction["violated_rule"] == "EVENT_FOCUS_CONTAINMENT"
    assert correction["label_locations"]["system.label"] == ["S2", "S12"]
    assert correction["label_locations"]["target.label"] == ["S1", "S2"]
    assert result.state is ScopeState.IN_SCOPE


def test_the_facts_do_not_relax_validation():
    # A correction that still cites a sentence without the labels is the gap, as before.
    helper = _Helper(_oslo(("S3",)), _oslo(("S3",)))
    with pytest.raises(ScopeProposalViolation) as caught:
        _classify(helper, OSLO)
    assert caught.value.failure_class == "TARGET_SYSTEM_CONTAINMENT"
    assert caught.value.scope_correction["outcome"] == "STILL_VIOLATED"
    assert len(helper.requests) == 2
