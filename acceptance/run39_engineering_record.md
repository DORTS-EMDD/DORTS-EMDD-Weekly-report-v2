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

## RC66-R7 execution attempt (2026-11-09)

Starting SHA: `5bb281813d2327a7de5327d997a8ab445b4a22de`. D4/L1 was frozen as
`INCHEON-WIFI-START` before execution. The branch, repository identity and
clean working tree were verified; origin matched the starting SHA.

The measurement was blocked before the first paid call. The existing runtime
exposes `MAIAGENT_API_BASE`, `MAIAGENT_API_KEY`, and the Writer-only
`MAIAGENT_CHATBOT_ID`, but does not expose the required
`MAIAGENT_STRUCTURED_HELPER_CHATBOT_ID`. The repository's EventIdentity
provider therefore returned `None` during the configuration check. Using the
Writer chatbot as a Structured Helper would violate the authoritative
provider boundary, so it was not attempted.

Actual MaiAgent calls: 0. Transport retries: 0. No R7 round, M-C, M-F,
candidate comparison, or acceptance predicate was measured. The blocked
result is recorded in `acceptance/event_identity/rc66_r7_measurement.json`.
Production EventIdentity, Scope, Golden outcomes, and downstream behavior
remain unchanged.

## RC66-R7 resumed execution attempt (2026-11-10)

Starting SHA: `be864067f2f5bc098735e25bdd8c574d88d7d89a`. The target branch and
remote remained aligned, and the Structured Helper configuration check passed:
the helper was present and distinct from the Writer chatbot. D4/L1 was frozen
as `INCHEON-WIFI-START`.

The measurement-only harness rebuilt 63 current hash-verified records from the
78-record prepared population. Two records that were previously inside the
65-record preflight verified population now have different current body hashes
and were excluded without substitution: the Singapore MRT depot automation
record and the Dhaka Metro Line 1 contract record. Ten direct confirmation
groups were rebuilt; the Kyiv pair could not be used because only one member
remained after the other recorded source was unavailable.

The paid measurement then began and completed the first baseline
`event-identity-grouping-v10` round-1 cited-focus RC-52 batch evaluation. The
measurement harness stopped immediately afterward because its scoring code
attempted to read `EventIdentityRun.exchanges`, which is not part of the
production result contract. The first attempt did not persist the transport
meter before that exception. Therefore the actual MaiAgent call count and
retry count are **UNKNOWN**, not zero, and no further paid call is authorized
under the 400-attempt hard cap until that count is externally recoverable or
the measurement window is explicitly reset.

Candidate comparison, M-C, M-F, rounds 2–3, and acceptance predicates were not
run. Production EventIdentity, Scope, prompt, schemas, Golden outcomes, and
downstream behavior remain unchanged. The measurement script was corrected to
persist a hash-only call journal before future attempts and to score duplicate
membership from the response envelope without depending on an internal
`EventIdentityRun.exchanges` field. This correction has not been used for a
second paid attempt.

## RC66-R7 measurement infrastructure repair (2026-11-10)

Starting SHA: `be864067f2f5bc098735e25bdd8c574d88d7d89a`.

The crash root cause is proven and is measurement-only: the scorer read
`EventIdentityRun.exchanges`, a field that does not exist in the authoritative
contract. The production observation surface is `proposal_exchanges`, which is
used by the repaired scorer. No compatibility alias was added to production
EventIdentity, and no production EventIdentity defect was introduced.

The interrupted baseline remains `INTERRUPTED_NOT_SCOREABLE`. The prior
MaiAgent call count and retry count remain **UNKNOWN** because the first
attempt did not persist a journal before the exception. No exact prior count or
safe auditable upper bound is available, so the cumulative 400-call campaign
is fail-closed as `BLOCKED_CALL_ACCOUNTING`; no paid resume is authorized. New
MaiAgent calls during this repair: **0**.

The repaired `MeteredTransport` requires an explicit prior count or conservative
upper bound for a new campaign, refuses to reset an existing journal, reserves
each attempt as `IN_FLIGHT` before network I/O, atomically persists completion
or failure, and reports cumulative attempted calls and safe remaining budget.
The journal contains request hashes, state, outcome and aggregate duplicate
membership counts only; it does not persist source bodies or credentials.

Files changed in this repair:

* `scripts/rc66_r7_measurement.py` — corrected the observation field and added
  cumulative crash-safe accounting.
* `tests/test_rc66_r7_measurement.py` — added offline observation and ledger
  boundary tests.
* `acceptance/event_identity/rc66_r7_measurement.json` — appended the repair
  result without rewriting the interrupted-attempt record.
* `acceptance/run39_engineering_record.md` — appended this truthful repair
  record.

Validation:

* New measurement infrastructure tests: **4 passed**.
* EventIdentity observation/RC52/observability targeted run: **24 passed**.
* EventIdentity/Golden/failure-path/replay/observability suite: **169 passed**;
  ED01–ED28 remain PASS.
* Full offline repository regression: **1549 passed, 5 skipped** after
  redirecting TEMP/TMP to a writable directory. The earlier default-TEMP run
  had 5 sandbox-permission failures, not product failures.
* Recorded replay remains `reproduced=true`, `events=81`,
  `differences=[]`.
* Compile/static checks and `git diff --check` passed.

Architecture review passes: one EventIdentity owner remains, no downstream
rescue/backfill or duplicated path was added, no Golden expected outcome was
changed, no production prompt/scope/configuration was changed, and no
country/language/event-specific rule was introduced. Real production
validation was not run, and release readiness is not claimed.

## RC66-R7 call-accounting recovery (2026-11-10)

Starting SHA: `bd6a13db90f0fd8176caf139ceb354a3f4bb484a`. The target branch was
fetched and verified at the same SHA; the working tree was clean before this
record-only update.

Phase 1 was performed read-only. The repository measurement artifacts and
engineering history still record the interrupted baseline as
`INTERRUPTED_NOT_SCOREABLE` with prior MaiAgent calls and transport retries
`UNKNOWN`. The RC66-R7 artifact history contains no durable campaign journal or
provider usage record. Workspace-local searches found only the repaired
ledger's synthetic pytest journals, which were not treated as campaign
evidence. No retained provider-side history or other configured read-only
provider log was available in this environment. No MaiAgent call was made.

The exact prior call count therefore remains **UNKNOWN**. A rigorous finite
upper bound also cannot be proven from the deterministic code alone: the
provider response schema does not bound the number of proposal groups, and the
number of confirmation calls can depend on that response, with the shared
transport retry applicable to each attempt. The 400-call cap was not reset.

Phase 2 does not credit the interrupted work as a completed acceptance round.
The frozen complete design remains the recorded preflight estimate of **384
future calls** (baseline and candidate, three rounds, cited-focus RC52/M-C and
BH-2 full-focus M-F RC52/M-C). Cumulative required calls are therefore
`UNKNOWN + 384`, so safety cannot be proven under cap 400.

Verdict: **BLOCKED_CALL_ACCOUNTING**. R7 was not resumed. No production
EventIdentity, Scope, prompt, schema, downstream path, or Golden outcome
changed. This section and the machine-readable recovery object are the only
new changes.

## RC66-R7 new independently accounted campaign (2026-11-10)

The interrupted campaign remains permanently **INTERRUPTED_NOT_SCOREABLE**;
its prior call count and retry count remain **UNKNOWN**, and its history was
not rewritten. A new campaign was started from `95cd459613cf68fd723329b6e40490dc190d2600`
with campaign ID `RC66-R7-CAMPAIGN-20261110-01`, an independent durable
hash-only journal, initial call count **0**, and a hard cap of **400**. The
baseline was `event-identity-grouping-v10`; the measurement-only candidate
was `event-identity-grouping-v10+rc66-confirmation-clarification-v1`.

The authoritative owner remains the production EventIdentity
grouping/confirmation path. The measured boundary remained confirmation-only:
a confirmation record is grouped with the occurrence whose specific details it
states, while an activity that marks or verifies that occurrence does not by
itself create a new event. No Scope, Category, Writer, Validator, downstream
repair, fallback, backfill, country/language rule, or second owner was added.
The earlier Category clarification at `8aa225d` was not changed by this
campaign.

The live campaign refetched the 78-record prepared corpus. It ultimately
verified **57** records, with **6 EVIDENCE_UNAVAILABLE** and **2 HASH_MISMATCH**
exclusions; no substitute source was used. The required ten direct groups
were all present after resuming the same campaign, yielding **12 batch round
results** and **120 direct confirmation results**. The first live fetch had
only six direct groups because four source records were transiently
unavailable; it was not scored as complete and was resumed with the same
journal and remaining budget. No cap increase or replacement round was used.

The campaign completed at **384 attempted MaiAgent calls**, **249 repeated
request-hash entries**, and **16 safe calls remaining**. Every recorded HTTP
outcome was `HTTP_200`; the journal and result contain no credentials or source
bodies. The recorded replay remains `reproduced=true`, `events=81`,
`differences=[]`.

R7 verdict is **R7_FAIL**, based on measured acceptance failures rather than
test status alone:

* Baseline cited-focus batch recall was `33/41, 33/41, 33/41`; candidate was
  `29/41, 33/41, 33/41`. This is a candidate recall regression in round 1.
* Baseline full validated-focus M-F recall was `38/41, 33/41, 33/41`;
  candidate was `32/41, 33/41, 33/41`. Candidate round 3 also emitted two
  duplicate-membership technical gaps.
* The required zero-differently-labelled-false-merges predicate failed in
  every measured batch family: candidate cited-focus false merges were
  `2, 2, 2`, and candidate M-F false merges were `2, 3, 3`.
* The direct mixed Incheon control met the 2-of-3 same-occurrence criterion
  only for candidate M-F (`2/3`) and met it `0/3` for candidate cited-focus;
  direct incident/follow-up controls produced six false-merge pairs per
  candidate direct arm across the three rounds.
* Pure over-split controls, cross-language/mixed controls, mega-group negative
  controls, duplicate membership, and batch recall were retained as separate
  measurements. Mega negative controls had zero false merges, but the
  mega-31 direct control still recorded duplicate membership in candidate
  focus modes. These observations do not authorize downstream rescue.

Offline validation after the final measurement-only guard:

* RC66-R7 harness tests: **8 passed**.
* EventIdentity replay/recorded-answer/RC52/observability/failure-path,
  dedup Golden, and RC66-R7 targeted suite: **176 passed**.
* Full repository offline regression: **1553 passed, 5 skipped** in the
  isolated environment built from `requirements.txt`, with writable TEMP/TMP.
* JSON validation, `py_compile`, and `git diff --check`: **passed**.

The only post-run code change is a measurement-only fail-closed guard that
requires all ten frozen direct confirmation group names before a live or
resumed campaign can spend calls. It adds no production behavior. Architecture
review passes for one owner, no fallback/rescue/backfill, no duplicated
classification path, no Golden expected-outcome mutation, no event-specific
logic, and no unnecessary production complexity. Production EventIdentity was
not changed, no new production report or email was sent, and real-production
validation remains **NO**. The machine-readable campaign evidence is stored
in `acceptance/event_identity/rc66_r7_campaign_20261110_01.json`, its plan, and
its independently accounted hash-only call journal.

## RC66-R7 post-run evidence-integrity finding (2026-11-10)

The raw campaign execution completed, but a post-run audit found that its
resume path was not scoreable as one frozen corpus. The first live fetch had
six direct groups and completed those units; the resumed fetch later produced
ten direct groups with different membership for six groups. Because the unit
key did not yet include a corpus fingerprint, the result combined the first
run's scoreable direct rows with the later manifest. **72 of 120 direct rows**
therefore do not match the final manifest's candidate membership. This is a
measurement-infrastructure defect, not evidence of a production EventIdentity
behavior change.

The raw result and call journal remain preserved. The raw diagnostic signals
(candidate batch false merges and recall regressions) are retained, but the
campaign is **BLOCKED_NOT_SCOREABLE** and is not credited as R7 acceptance.
The remaining 16 calls are not used to patch or selectively repeat the
campaign; a new campaign would require explicit future authorization. The
machine-readable assessment is
`acceptance/event_identity/rc66_r7_campaign_20261110_01_assessment.json`.

The measurement harness now computes a SHA-256 corpus fingerprint from the
verified manifest, persists it in the durable journal and plan, and refuses a
resume when the fingerprint is absent or changed. The guard is covered by an
offline regression test. Final validation after this repair was **9 RC66-R7
harness tests passed**, **1554 full repository tests passed with 5 skips**,
compile passed, JSON validation passed, and no paid call was made after the
integrity finding.

## Real-production quality acceptance (2026-11-10)

Starting SHA: `aa869dde27dc46a69b1c13323fa4b7bda4fed643` on
`release/report-quality-wip`. The branch was clean before execution and the
canonical V2 production path was used for `2026-10-12..2026-11-08` with
`run_production=true` and `send_email=false`. The existing MaiAgent API call
was explicitly preauthorized by the user; no email was sent and no other paid
provider was used.

The run completed as `SUCCESS_WITH_TECHNICAL_GAPS` (CLI exit code 2):

* RunTrace: `862b4757138643f8a3ad603504e7e0bf`.
* Report: `weekly-report-149ed145cfc3f441`.
* Artifact: `formal-report-149ed145cfc3f44134cce892adff4d91590ec006e192dde0fdbc47c48e3faf78`.
* Search: 213 planned, 213 attempted, 1 network technical failure (standards catalogue ordinal 152).
* Acquisition: 789; normalized observations: 213.
* Evidence: 559 total, 200 ready, 359 rejected. Rejections were
  `SOURCE_PAGE_MISMATCH=192`, `CONTENT_UNAVAILABLE=151`, and
  `INSUFFICIENT_SUBSTANCE=16`; rejection gates were
  `FETCH_TRANSPORT=151`, `PRINCIPAL_DOCUMENT=137`,
  `SEMANTIC_MATCH=45`, and `SOURCE_PROVENANCE=26`.
* Scope: 125 IN_SCOPE, 48 OUT_OF_SCOPE, and 27 disclosed Scope technical gaps.
  Temporal: 102 DATE_VALID and 23 DATE_INVALID.
* EventIdentity: 102 records and 69 EventGroups. The production prompt remained
  `event-identity-grouping-v10`; proposal and confirmation exchanges,
  procedure identities, diagnostics, and the one EventIdentity technical gap
  were retained in `selection_audit.json`. The current audit replay reproduced
  `true`, with `events=69` and `differences=[]`. The historical Run #39 replay
  remains `reproduced=true`, `events=81`, `differences=[]`.
* Category: 69 groups, 30 assigned and 39 `CATEGORY_UNRESOLVED`; every
  unresolved result used `NO_CATEGORY_DEFINING_ACTION`. Assigned totals were
  `TECHNICAL_DEVELOPMENT=4`, `INCIDENT=12`, `OPERATIONAL_CHANGE=9`, and
  `PROCUREMENT=5`.
* Reportability/ordering: 26 reportable and 26 ordered. Formal metadata
  projected 15 events and excluded 11 (`NON_DESIGNATED_REGION=10`,
  `REGION_NOT_ESTABLISHED=1`). Writer generated 15 blocks; Validator returned
  14 PASS and 1 event-level FAIL for
  `factual_factual_summary_quantity_ungrounded`; final report count was 14.
  Final distribution was `技術新知=4`, `事故及安全事件=5`, `營運動態=3`,
  `機電標案及採購動態=2`.

### Production findings and ownership

The earliest confirmed Category root cause remains the Classifier's semantic
proposal/guidance boundary, not Report Service, Writer, Validator, or a
downstream repair:

* Lyon T10 was emitted as `TECHNICAL_DEVELOPMENT /
  pre_opening_signal_testing` and included in the final report. This still
  violates G100: pre-opening signalling/control/communication/power testing
  as a project step must be `CATEGORY_UNRESOLVED /
  NO_CATEGORY_DEFINING_ACTION`.
* Bergamo T2 first track testing was also emitted as
  `TECHNICAL_DEVELOPMENT /
  pre_opening_testing`, showing the same project-step pollution boundary.
* Incheon operating-subway 5G was emitted as `OPERATIONAL_CHANGE /
  passenger_wifi_service_launch` and included. This still violates G101:
  the evidenced principal technology deployment on an operating rail system
  must remain `TECHNICAL_DEVELOPMENT`.
* Tokyo Point AI was emitted as `TECHNICAL_DEVELOPMENT /
  ai_driver_assistance_system_development` and included. The evidence is a
  useful control observation, but this run does not authorize a universal rule
  that future tense or an announcement alone proves adoption. No such rule was
  added.

Classifier remains the sole Category owner. The production run added no
fallback, rescue, backfill, second owner, downstream reclassification,
country/language/event-specific rule, or Golden mutation. The production
EventIdentity owner, prompt, nomination, confirmation, RC-52, complete-link
behavior, and Scope were unchanged.

For the Daegu Line 3 occurrence, this run's audit contains one EventGroup with
six supported occurrence members, so the Run #39 three-group split was absent
in this run. This is a run-specific observation only; it is not evidence that
the unchanged EventIdentity behavior has been generally fixed, and no rescue
was added.

The 14 final items were read in full. Their prose passed the canonical
Validator except for the one excluded event above; no internal/debug wording,
unsupported Taipei-specific operational claim, or broken/truncated prose was
found. A formal metadata quality finding remains: the Lyon item displays the
location as Korean `리옹` in an otherwise Traditional-Chinese report. This is
a presentation/metadata normalization issue, not a reason to alter Category
or Writer ownership.

### Deployment provenance and verification

The run used the existing MaiAgent API origin `api.maiagent.ai`. To avoid
recording credentials, the configured Writer and Structured Helper chatbot
identities are identified by stable SHA-256 fingerprints only:

* Writer chatbot ID fingerprint:
  `1eba425625dea9ff503554d5347b155094412fa45827ec43e00e936ab5b8e9a4`
  (length 36).
* Structured Helper chatbot ID fingerprint:
  `ae6703c51cb946e9e635c541d171bbbe178d4c851336049385b973feaf30b305`
  (length 37); distinct from Writer.
* Repository prompt identities remained Category
  `category-principal-action-v6`, EventIdentity
  `event-identity-grouping-v10`, and Writer `formal-report-writer-v10`.

The generated Engineering Summary truthfully reports
`declared_maiagent_role_status=NOT_DECLARED`; no platform management snapshot,
exact model label, role content, or platform schema read-back was available.
The fingerprints identify the two configured deployment identities but do not
claim `OBSERVED_AND_FROZEN` platform provenance.

Offline verification after production:

* Category/EventIdentity/Golden/observability/failure-path targeted suite:
  **240 passed**.
* Full repository regression in the declared isolated environment with
  writable temporary paths: **1558 passed, 5 skipped**.
* Current production selection-audit replay: **reproduced=true,
  events=69, differences=[]**.
* `compileall` for `src` and `scripts`: **passed**.

The six canonical production artifacts are preserved under
`acceptance/production_acceptance_20261110/`: run summary, selection audit,
Markdown report, PDF report, Developer Debug, and Engineering Summary. The
acceptance is not release-ready. Smallest remaining blockers, in owner order,
are: (1) Classifier guidance/deployment must produce G100 and G101 contract
outcomes without inventing a future-adoption precedence rule; (2) formal
metadata presentation must stop rendering the Lyon location as mixed-script
Korean; and (3) the missing platform read-back must be captured if release
governance requires frozen deployment provenance. The known EventIdentity
quality limitation remains observable and unchanged; this run is sufficient
for a later offline comparable-run assessment because the audit retains the
three RC-52 procedure proposal/confirmation exchange sets, but it is not an
EventIdentity acceptance experiment.

Verdict: **FINDINGS**. `REAL_PRODUCTION_VALIDATED=YES`;
`RELEASE_READY=NO`.
