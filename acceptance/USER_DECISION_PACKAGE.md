# User decision package (prepared 2026-11-08, offline; no answer chosen)

Each item gives the question, the evidence, what each answer would change,
and what is already prepared. Claude does not decide any of them. Evidence:
REPORT sections 71–73 and `acceptance/phase_b_audit/`.

## D1. Project steps: are they report items? (section L vs section N conflict)

**Question.** Should project-lifecycle events reach the formal report? These
are construction milestones (groundbreaking, tunnelling, manufacturing
milestones), pre-opening and acceptance tests, plans, approvals and funding,
and changes to an expected opening date (delays).

**Why it is open.**
* Section N (RC-10, 2026-10-21) says: "Opening or construction of a line,
  extension or station is a concrete service or engineering change", which
  is an accepted value path.
* The Reportability helper (RC-27, user-directed) lists
  `CONSTRUCTION_MILESTONE` and `DELIVERY_TEST_OR_COMMISSIONING` as
  substantive occurrences.
* Section L RC-63 (2026-11-06, WIP branch only) makes construction stages,
  test runs before opening, plans and approvals, ridership counts, rankings,
  announcements of future openings, and statements about an action into
  `CATEGORY_UNRESOLVED`. That ends the Event Group before Reportability.
* RC-63 is not marked user-approved in the contract and is not on `main`.
* The user's own instruction of 2026-11-07 states only that these steps
  "本身不是技術新知" (are not technical development). It does not say that
  they have no Category or that they leave the report.

**Evidence of impact.** Runs #16–#33 run without RC-63. About 31 distinct
report items in those runs were project-lifecycle events:
* construction 8 (Dongtan groundbreaking, Vienna 1,000th car, NY A/C signal
  upgrade start ...);
* pre-opening and acceptance tests 6 (Bergamo T2, Rome CAF Urbos, Taoyuan
  Green Line ...);
* plans, approvals and funding 11;
* opening delays 6 (Wirye ×3, Paris 16/17, Lyon T9).

Under WIP RC-63 all of them are excluded. In Run #34, 31 of 66 Event Groups
ended `CATEGORY_UNRESOLVED`, against an average of about 5 per run before.

**What each answer means.**
* *Not report items:* section N's construction and opening value path, and
  the two Reportability occurrence classes, should be removed or marked
  unreachable. RC-63 stands.
* *Report items:* they need a Category. Section L would need a rule that says
  which one (OPERATIONAL_CHANGE? a lifecycle subtype?). RC-63's "no
  Category" sentence would be revised. Golden G92–G100 (all
  `CATEGORY_UNRESOLVED`) were written to RC-63 and would need their
  expectations revised under that contract change.
* *Split by kind* (for example delays and openings in, construction progress
  out): an explicit list is needed.

**Related drift (same decision).** Reportability's
`STATISTICS_OR_REPORT_RELEASE` is not a low-value class. Category RC-63 makes
ridership counts "no Category". Statements, rankings and features are held
by both owners with different outcomes (Melbourne G Class award: Category
OPERATIONAL/opening, Reportability AWARD).

## D2. Drills and training: which Category?

Emergency drills and fire-brigade trainings occur in most weeks: 20 events
in runs #16–#34, of which 16 reached reports. Category alternates between
技術新知 and 營運動態 for the same kind of event, for example the Daegu fire
drills. Prompt v6 only says such a drill is not 技術新知. Options:
* `OPERATIONAL_CHANGE`, as an operational-governance action on a running
  service;
* `CATEGORY_UNRESOLVED` (no Category-defining action).

## D3. Historical retrospectives: which date controls?

* The Kyoto "10月12日 … 1997（平成9）年" item reached Validation: its Evidence
  says only "東西線が開業した", and 1997 is in the title, which is not
  Evidence.
* Two other retrospectives, 1904 Pau and Norderstedt "vor 30 Jahren", were
  stopped only because their sites lack date markup
  (`DATE_PROVENANCE_INVALID`). A future date-extraction fix (D5) would let
  them through.
* Options:
  * the principal-source headline may establish a historical occurrence date
    as context for Reportability's existing anniversary and feature rule; or
  * the Temporal controlling date is the occurrence date when the Evidence
    states one; or
  * no change: accept the leak.

## D4. Incheon label L1, and the RC-42 decision

* RC-42 decided that the operator's Incheon 5G Wi-Fi launch and the
  Ministry's same-day verification event are different events.
* 스마트투데이 reports both the completion and the Ministry event. Confirmation
  separated it 3/3 in Run #34.
* Run #24 shows the helper merging a Ministry-only record with the launch, so
  the helper is inconsistent.
* Needed: the label of 스마트투데이 (launch or Ministry event) for the R7
  corpus. Prepared: `acceptance/event_identity/RC66_R7_MEASUREMENT_PACKAGE.md`
  (sections 1–6).

## D5. Fetching publisher pages to build structural fixtures (network, not paid)

Two deterministic Evidence losses cannot be fixed without page HTML, and the
audit never stores it:
* **Principal-document detection.** 160 of 175 hosts fail on every page.
  They include Yonhap and the two specialist rail-media sites the Search
  configuration queries on purpose (railway-news.com, masstransitmag.com:
  0 of 33 technology candidates ever passed).
* **Date markup.** 49 of 51 `DATE_PROVENANCE_INVALID` hosts fail on every
  page. At least 14 of 65 pages show a visible dateline in their own text
  (MHI, NHK, JETRO Auckland ...).

Needed: approval to fetch a bounded set of these pages (no helper calls) into
test fixtures, and, for dates, a decision whether a visible dateline may be a
date source. Visible datelines are not in today's extractor, and they
interact with D3.

## D6. Paid validation

Category v6, Writer v9 and v10 (currency and kept Korean names) and the R7
package all need real runs. The offline changes are on
`release/report-quality-wip` only.
