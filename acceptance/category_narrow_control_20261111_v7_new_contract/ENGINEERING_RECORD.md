# Category subtype-contract engineering record

Status: WIP; current configuration is eligible for formal Category sealing, but
the seal and production report are intentionally not run in this task.

## Identity and decision

```text
AUTHORITATIVE_STARTING_SHA = a533cd8d95d627f15c6aeec0f41357b63e12f6eb
LOCAL_STARTING_HEAD = 1b53fde8cb04af56485a06ee647644b6fc111c82
CONTRACT_DECISION = SIMPLIFY_SUBTYPE_CONTRACT
AUTHORITATIVE_OWNER = Classifier / Category response contract
OLD_RESPONSE_CONTRACT_IDENTITY = category-full-response-contract-v2
NEW_RESPONSE_CONTRACT_IDENTITY = category-full-response-contract-v3
OLD_SCHEMA_IDENTITY = category-proposal-v5
NEW_SCHEMA_IDENTITY = category-proposal-v6
BASELINE_PROMPT_IDENTITY = category-principal-action-v6
REEVALUATED_GUIDANCE_IDENTITY = category-principal-action-v7
OLD_CONFIGURATION_FINGERPRINT = 695988ff08b5aa792c68abc6dc4ad243aea88f01fe6b2b7caa10ca174006d749
NEW_CONTRACT_BASELINE_CONFIGURATION_FINGERPRINT = cdb7b3a625d076fd6d55dedbfba33203f572b58c1ffbd1af5484b12d4f84a5d7
NEW_V7_CONFIGURATION_FINGERPRINT = 6282f2cb1495b6759fc4f7d81b6bad088fb609e97e6321772be80a3376259690
EXACT_V7_GUIDANCE_SOURCE_COMMIT = 8aa225d74cf8afae52c77368298949586fc31db9
```

The old contract unnecessarily coupled the primary Category decision to the
lexical form of optional subtype metadata. The authoritative owner remains the
Classifier. Subtype is retained for audit and observation, but is not a Domain
Rule or a decision input. No new Category rule was added.

The v6 production guidance was narrowed only to make subtype metadata truthful:
assigned subtype is a string or null, unresolved subtype is null, and lexical
style is not a Category decision. The previously rejected v7 principal-action
candidate was not edited or installed during Phase 1. Its exact guidance was
recovered from commit `8aa225d...` and used unchanged for the fresh acceptance.

## Strict and non-fatal contract rules

Fatal validation remains in force for response shape, category state, primary
Category ID, unresolved reason, state consistency, citation shape/source/sentence
resolution, and subtype type/state consistency. An assigned subtype may be any
string or null; an unresolved subtype must be null. No subtype string is
rewritten, dropped, backfilled, retried, voted, or rescued.

## Validation

```text
OFFLINE_CONTRACT_TESTS = 73 passed, 102 subtests passed
OFFLINE_CATEGORY_GOLDEN = 71 passed
FULL_REGRESSION = 1565 passed, 5 skipped
COMPILE_CHECK = PASS
EVENTIDENTITY_REPLAY = reproduced=true, events=69, differences=[]
```

The first sandbox full-suite attempt had 5 failures and 20 setup errors from
Windows temporary-directory ACL restrictions; the same suite was rerun in the
valid isolated elevated environment and passed as recorded above. No Golden
fixture or primary Category expected outcome was changed. The only Golden
contract-test adjustment removed the superseded subtype lexical assertion.

Fresh narrow live acceptance used the unchanged deployment fingerprint
`ab75a4fb...`, the same runtime Helper binding was `PROVEN`, and the exact
predeclared controls were G100/G101/G93/G66 for three rounds:

```text
PLANNED_LOGICAL_CALLS = 12
ACTUAL_LOGICAL_CALLS = 12
TRANSPORT_RETRIES = 0
UNSCOREABLE_CALLS = 0
G100 = PASS / PASS / PASS
G101 = PASS / PASS / PASS
G93 = PASS / PASS / PASS
G66 = PASS / PASS / PASS
NARROW_ACCEPTANCE = CURRENT_LIVE_BOUNDARIES_PASS
OLD_V7_FORMAL_ACCEPTANCE = REJECTED
PRODUCTION_REPORT_RUN = NO
```

## Architecture review

One Category owner remains. The Structured Helper remains proposal-only. The
schema, Classifier validation, and `CategoryResult` now express one versioned
contract. No fallback, backfill, post-hoc sanitization, downstream repair,
second owner, second response contract, keyword classifier, precedence rule,
event/country/language special case, retry/voting, or EventIdentity change was
added. G100/G101/G93/G66 and all Golden primary outcomes remain unchanged.

The remaining blocker is procedural: the formal current-configuration Category
live seal is required before any production report rerun. EventIdentity remains
outside this task and its separate RC66-R7 decision path is unchanged.

```text
COMMIT = this cohesive commit; exact final identity is reported from git after amend
PUSH_STATUS = pending non-force push to release/report-quality-wip
FULL_CATEGORY_SEAL_REQUIRED_NEXT = YES
REAL_PRODUCTION_VALIDATED = YES (narrow Helper acceptance only; no production report)
RELEASE_READY = NO
```
