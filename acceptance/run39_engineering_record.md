# Run #39 engineering record

Run: `42548407130`

Period: `2026-10-12..2026-11-08`

Baseline: `46edf00e182f401d5f8408d55241b9611e0732fb`
Status: WIP; not release-ready

## Evidence and ownership

The downloaded production artifact was inspected from `selection_audit.json`
and `run_summary.txt`. It establishes two Category defects against locked
G100/G101 outcomes, both owned by the Classifier semantic guidance rather than
by a downstream formatter or report repair:

* Lyon T10 pre-opening signalling tests were assigned `TECHNICAL_DEVELOPMENT`
  (`preopening_signal_system_testing`), contrary to G100.
* Incheon Lines 1/2 5G Wi-Fi deployment was assigned `OPERATIONAL_CHANGE`
  (`passenger_wifi_service_launch`), contrary to G101.
* Tokyo Metro Point AI introduction was left
  `CATEGORY_UNRESOLVED / RECOMMENDATION_WITHOUT_ADOPTED_ACTION`. This is useful
  diagnostic evidence, but the current contract does not establish that a
  future-tense operator announcement alone is an adopted action, so no new
  Domain Rule or production correction is claimed for it.

The implementation had a broad technical-development sentence followed by
qualifications. Commit `8aa225d` also added two broader formulations that could
be read as treating future-tense announcements as adoption or as giving
technology a universal precedence over `OPERATIONAL_CHANGE`. Those formulations
were removed. The current wording is the single RC-66 definition: classify the
evidenced principal action, with the technology, method or material itself as
the subject, while retaining the project-step exclusions. Tokyo Point AI is
therefore a diagnostic only; no new adoption rule was invented. Prompt version
`category-principal-action-v6` remains the contract identity because the wording
now implements the already-authoritative RC-66 v6 contract. The acceptance
fingerprint now includes both the complete guidance and this prompt version, so
future evidence distinguishes the configuration without rewriting history. No
second Category owner or response backfill was added.

Current repository-controlled acceptance identity:
`category-v4-final-seal-v2`, `category-principal-action-v6`, 53 prepared
EventGroup requests, configuration fingerprint
`1fe427b77642df14792c4980096f7c4c881345befcc4d736878e45ba282c9534`.

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

* `src/weekly_report/classifier.py` — restored the single v6 definition and boundaries.
* `scripts/category_semantic_evaluation.py` — includes prompt identity in the acceptance fingerprint.
* `tests/test_category_boundary_golden.py` — locks the G100/G101 guidance boundaries.
* `tests/test_category_semantic_evaluation.py` — locks fingerprint sensitivity to prompt identity.
* `acceptance/run39_engineering_record.md` — records evidence, ownership and blockers.

Existing G100 and G101 expected outcomes were not changed. The complete
Category-focused pytest set (boundary Golden, Classifier, provider, semantic
evaluation and Category Golden) passed **69 tests**. The full repository offline
regression passed **1545 tests with 5 skips** after the declared
`requirements.txt` was installed into an isolated temporary target and pytest's
TEMP/TMP paths were redirected to a writable repository temp directory. An
initial default-TEMP run had 5 failures and 14 setup errors caused by sandbox
permission failures; the writable-temp rerun was clean. EventIdentity
replay/recorded-answer/failure-path/dedup tests passed **21 tests**. The
recorded Run #39 replay remains `reproduced=true`, `events=81`,
`differences=[]`. Changed Python files also passed `py_compile`. No live
production rerun was performed.

Complexity is unchanged: the patch changes prompt text and assertions only;
EventIdentity grouping, confirmation, complete-link behavior and asymptotic
cost are unchanged.

## RC66-R7 measurement preflight (2026-11-09)

Starting SHA: `22a66a74aef917048954d3282955b4f493b24249` on
`release/report-quality-wip`. The authoritative EventIdentity owner remains
the production EventIdentity grouping/confirmation path. No prompt, schema,
production behavior, Golden expected outcome, downstream rescue, or second
owner changed.

The baseline identity remains `event-identity-grouping-v10`, proposal schema
`event-identity-semantic-proposal-v1`, confirmation schema
`event-identity-semantic-confirmation-v1`, helper
`maiagent-structured-helper-event-identity-adapter-v1`, provider
`maiagent-structured-helper-event-identity`, and contract `event-identity-v1`.
Recorded replay remains `reproduced=true`, `events=81`, `differences=[]`.

The RC66-R7 corpus was rebuilt with the production Evidence fetcher and
`assess_document(...).body_text` SHA-256. The preflight contains 78 prepared
records: 65 hash-verified, 8 hash mismatches, 3 evidence-unavailable, and 2
records with required audit metadata unavailable. No substitute source was
used. Pure same-occurrence controls were added for the Daegu Myeongdeok
entrance, Seoul Line 2 ja/ko outage, Kim Min-seok statement, Kyiv attack, and
8-record Ulsan depot strata. One Kyiv Yahoo body remained unavailable and is
explicitly excluded.

D4/L1 remains unresolved for SmartToday candidate
`cand_9ce03b4da316d4ea90f2eb7cf957ecf0ff5b45a5287192fe06b97878e0938997`
(SHA-256 `6814dd94eb73c249ee4e98372801e68baa6bb750c7bb1f638476f742ecb0b96b`,
focus S1/S2). The preflight records the only permitted choices:
`INCHEON-WIFI-START` or `MINISTRY-EVENT`. No MaiAgent call was made.

The cited-focus RC-52 plus M-C design is estimated at about 192 calls
(120 + 72), within the proposed hard cap of 200. Phase C also mandates M-F
with the full validated focus for both batch and M-C, increasing the complete
bound to about 384 calls. This cap/design conflict is recorded as a blocker;
the preflight stops before paid measurement rather than exceeding the cap or
silently omitting M-F.

Validation at this checkpoint: targeted EventIdentity/Golden/failure-path
tests `169 passed`; full offline regression `1545 passed, 5 skipped`; compile
check passed; ED01-ED28 expected outcomes remain unchanged. Real production
EventIdentity validation was not run. The machine-readable details are in
`acceptance/event_identity/rc66_r7_preflight.json`.
