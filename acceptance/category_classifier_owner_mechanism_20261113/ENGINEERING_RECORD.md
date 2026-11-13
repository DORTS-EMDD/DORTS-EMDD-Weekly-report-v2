# Category Classifier Owner-Mechanism Correction — 2026-11-13

## Gate status

- Starting remote SHA: `7594eccb5e222fbda80709c1c851774599cda136`
- Working revision: uncommitted candidate; no accepted implementation SHA exists.
- Authoritative owner: `Classifier` (`CATEGORY_AUTHORITATIVE_OWNER_COUNT = 1`)
- Helper role: advisory action/lifecycle observations with Evidence citations only.
- Release status: **BLOCKED at bounded live Category acceptance after an RC-6
  transport technical gap**.

## Root cause and boundary

The prior path allowed a structurally valid Helper response containing final
Category semantics to become the authoritative `CategoryResult`. The correction
replaces that interface with cited action/lifecycle observations. The
Classifier validates the observations, selects only a Helper-declared principal
action when the Evidence supports uniqueness, and applies the existing §L
mapping once. No Category precedence rule, future-announcement adoption rule,
keyword rule, fallback, rescue, backfill, voting, or downstream reclassification
was added.

The preserved semantic boundary is:

- a technology/method/material action with `TECHNOLOGY_ITSELF` lifecycle may be
  `TECHNICAL_DEVELOPMENT`, including G64, G78 and G101;
- project delivery or pre-opening testing remains
  `CATEGORY_UNRESOLVED / NO_CATEGORY_DEFINING_ACTION`, including G93 and G100;
- an implemented operating-service timetable action remains
  `OPERATIONAL_CHANGE`, including G66;
- subsequent acceptance testing does not erase an evidenced completed
  technology deployment, including G78.

The previous v6/final-category Helper wording was replaced, not retained,
because it expressed the wrong owner boundary. The current identities are:

- prompt: `category-principal-action-v7`
- Helper schema: `category-action-lifecycle-proposal-v1`
- response contract: `category-action-lifecycle-response-contract-v1`
- adapter: `maiagent-chatbot-adapter-v3`
- acceptance: `category-v5-classifier-owner-seal-v2`
- acceptance evidence: `category-acceptance-evidence-v2`
- evaluation harness: `category-semantic-evaluation-v6`
- guidance digest: `03044f2d776637b58a9e42e4480430d31155c3021a7df6d35aa4aabb8fffcc11`
- final full-population configuration fingerprint:
  `9515bfd271c5fa254cebefedccd100d3ce826a81586a42680613f79a66086757`

## G03 fixture

G03 synthetic substantive content was repaired to make its already-established
technology-deployment scenario explicit. Its expected primary Category was not
changed. No G64/G78/G84/G100/G101/G93/G66 evidence or Golden expected outcome
was changed.

## Offline validation

- Direct Classifier, provider/schema, Category Golden, boundary, evaluation and
  RC-6 transport tests after the accounting correction: **67 passed**.
- Full repository regression in a valid project test environment:
  **1549 passed, 5 skipped**. The five skips are the repository's declared
  skips; no suite was silently omitted. A first run with the sandbox TEMP
  directory produced 20 errors and 5 failures from Windows TEMP permission
  errors; that environment result was discarded and not reported as product
  PASS. The repository-local TEMP/TMP rerun is the valid result.
- EventIdentity offline replay: `reproduced=true`, `events=69`,
  `differences=[]`. No EventIdentity production logic or research call was
  changed.

## Bounded live acceptance

The bounded population was frozen as exactly:
`G03, G64, G78, G84, G100, G101, G93, G66`, three rounds, 24 planned logical
calls, logical hard cap 24, and transport-attempt hard cap 48.

- Round 1: **PASS**, 8/8 exact, 8 transport attempts.
- Round 2: **FINDINGS**, 8/8 semantic outcomes exact with zero state, primary,
  resolution, invalid-response, or citation mismatches. G78 required a second
  provider attempt; both observed attempts returned HTTP 200 and the final
  response was scoreable. The previous strict gate's 9-attempt finding was
  corrected: RC-6 transport attempts are now separately accounted from the 8
  logical calls, and the retry reason is retained as `UNPARSEABLE_RESPONSE`.
- Fresh campaign output: Round 1 **PASS**, 8/8 exact, 8 logical calls and 8
  transport attempts, with accounting `PASS` and zero retries.
- Fresh campaign Round 2 terminated after a logical call received two
  `UNPARSEABLE_RESPONSE` outcomes; the shared RC-6 policy performed its one
  authorized retry and raised `SemanticProviderTechnicalFailure` after the
  second attempt. The script stopped before writing a Round 2 report; no
  semantic result was accepted from that failed call, and Round 3 was not run.
  The termination is recorded without response bodies or credentials in
  `bounded_rc6_accounting_v2/termination.json`.
- Fresh bounded verdict: **BLOCKED / TECHNICAL_GAP_AFTER_RC6_RETRY**. No
  replacement call, semantic retry, compensating round, formal seal, or
  production run followed.

## Formal and production status

- Formal current-configuration Category seal: **NOT RUN**.
- Formal population was not charged; the expected recomputed population remains
  85 fixtures / 52 Category-reaching fixtures / 53 EventGroups before seal.
- Real production weekly report: **NOT RUN**.
- `send_email`: `false` (no production run was performed and no email was sent).
- Deployment fingerprint read-back target: `ab75a4fb9e278c8f93ee60fff8a1deaa9e0a2ef3a9db9086af09a43e8746bbe7`.
- No commit or push was made because the fresh bounded gate failed after the
  authorized RC-6 retry.

## Files changed in the uncommitted candidate

- `docs/ARCHITECTURE_CONTRACT.md`
- `golden/cases/g03_valid_new_technology.json`
- `scripts/category_bounded_live_acceptance.py`
- `scripts/category_formal_v7_seal.py`
- `scripts/category_semantic_evaluation.py`
- `src/weekly_report/__init__.py`
- `src/weekly_report/category_semantic_provider.py`
- `src/weekly_report/classifier.py`
- Category Classifier/provider/Golden/evaluation tests

Architecture review: one Category owner remains; Helper final Category is not
copied as authority; no second owner, fallback, rescue, backfill, retry voting,
keyword classifier, event-specific rule, or downstream repair was added.

## Acceptance accounting correction

The previous `LIVE_CALL_COUNT == transport attempts` gate was not consistent
with RC-6's existing contract. The current acceptance layer keeps `LIVE_CALL_COUNT`
and `LOGICAL_CALL_COUNT` at one per logical Category invocation, records
`TRANSPORT_ATTEMPT_COUNT` and `HTTP_200_ATTEMPT_COUNT` separately, and binds all
attempt observations into the evidence chain. Only a retry whose observer record
is explicitly authorized by the shared transport policy can pass accounting;
parseable-result replays and changed requests fail closed. This is an
acceptance-only observer/accounting correction; no Category owner or production
transport behavior was added.

## Earliest unresolved blocker

The strict no-extra-attempt gate is corrected, but the fresh bounded campaign
still encountered a provider response that remained unparseable after the
authorized RC-6 retry. This is a disclosed transport TechnicalGap, not a
Category semantic result. The current candidate therefore remains blocked from
formal Category seal and real production validation.
