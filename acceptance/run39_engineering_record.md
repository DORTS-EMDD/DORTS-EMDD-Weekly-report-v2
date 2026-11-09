# Run #39 engineering record

Run: `42548407130`

Period: `2026-10-12..2026-11-08`

Baseline: `46edf00e182f401d5f8408d55241b9611e0732fb`
Status: WIP; not release-ready

## Evidence and ownership

The downloaded production artifact was inspected from `selection_audit.json`
and `run_summary.txt`. The three confirmed Category defects are owned by the
Classifier semantic guidance, not by a downstream formatter or report repair:

* Lyon T10 pre-opening signalling tests were assigned `TECHNICAL_DEVELOPMENT`
  (`preopening_signal_system_testing`), contrary to G100.
* Incheon Lines 1/2 5G Wi-Fi deployment was assigned `OPERATIONAL_CHANGE`
  (`passenger_wifi_service_launch`), contrary to G101.
* Tokyo Metro Point AI introduction was left
  `CATEGORY_UNRESOLVED / RECOMMENDATION_WITHOUT_ADOPTED_ACTION`, although the
  operator's announced introduction is an adopted technology action.

The implementation had a broad technical-development sentence followed by
qualifications, but did not state the precedence for an operator-announced
technology deployment or for a technology deployment that enables a passenger
service. The minimal fix keeps prompt version
`category-principal-action-v6`, qualifies the definition at the principal
action, and makes those existing RC-63/RC-66 boundaries explicit. No second
Category owner or response backfill was added.

## EventIdentity finding

The Daegu Line 3 reports establish the same occurrence: the 2026-11-07
14:24-ish failure between Jisan and Beommul, whole-line delay, and restoration
after about 30 minutes. Run #39 nevertheless produced three EventGroups:

* `evt_15e7db19899d816bf61b7feb`: `cand_d4a07977...`
* `evt_72bcf54b60446e28f13ce2b8`: `cand_d66a73d6...`
* `evt_c696d8a2d98ca569ec332563`: five other Daegu Line 3 reports

The exact recorded exchange shows the pair `d4a07977...` / `d66a73d6...`
entered the same 64-record `event-identity-batch-1-n2:group-19` proposal, but
the confirmation returned them as separate singleton groups, producing
`PROPOSAL_NOT_CONFIRMED ... SEPARATED`. No Python downstream merge was added:
RC-48 makes this an `UNCERTAIN` helper outcome, and the current contract does
not authorize a new DISTINCT/SAME basis or a Scope workaround. The existing
EventIdentity owner and prompt remain unchanged; the paid/labelled RC66-R7
measurement package remains the required path before any prompt change.

The production artifact replay was run offline:

```text
reproduced: true
events: 81
differences: []
```

This confirms the recorded-answer path is reproducible, while also proving
that this Run #39 EventIdentity split is a helper confirmation defect rather
than an unobserved Python mutation.

## Changes and verification

Changed files:

* `src/weekly_report/classifier.py` — qualified v6 guidance only.
* `tests/test_category_boundary_golden.py` — locks the new guidance boundaries.
* `acceptance/run39_engineering_record.md` — records evidence, ownership and blockers.

Existing G100 and G101 expected outcomes were not changed. The offline
Category boundary and Classifier unittest invocation passed 28 tests. The
standalone Run #39 EventIdentity replay passed as shown above.

The repository's configured test runtime does not currently contain `pytest`
or `jsonschema`; pytest-based EventIdentity and provider suites therefore need
the project test dependencies before they can run. No live production rerun
was performed.

Complexity is unchanged: the patch changes prompt text and assertions only;
EventIdentity grouping, confirmation, complete-link behavior and asymptotic
cost are unchanged.
