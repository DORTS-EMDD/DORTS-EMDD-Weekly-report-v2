# RC-66 R7 measurement package: confirmation and records that report two occurrences

Status: `BLOCKED_PAID_VALIDATION`. Nothing in this package has been run. No
prompt has been changed. It was prepared offline on 2026-11-07 and needs the
user's approval of the paid calls and of label L1 before it is run.

## 1. Problem statement

The Event Identity confirmation separates records that state the same
occurrence as their group when the record also reports an activity marking
that occurrence. The pattern is consistent within each run, and the same
across runs and subjects.

| Run | Records | Batch proposals | Confirmations | Result |
| --- | --- | --- | --- | --- |
| 42186338279 (Run #34, 64cbce0) | 3 Incheon 5G Wi-Fi records | 6 of 6 group all three | 3 of 3 separate 스마트투데이 | two report entries for one completion |
| 42148605765 (6ded7d1) | ABC Sydney opening, IndexBox, French report | ABC proposed in the `-n2` nominations | every confirmation separates ABC | duplicate Sydney entry |
| local round 3 (REPORT section 70.1; office PC, artifact not on GitHub) | ABC Sydney, focus S2,S3,S5,S6,S7 | proposed | 6 of 6 SEPARATED | duplicate Sydney entry |

What each separated record contains:

* **스마트투데이.** Its focus S1 says the Ministry upgraded the line's Wi-Fi from
  LTE to 5G **and** held an experience event. S2 says lines 1 and 2 are the
  first on which all three carriers started 5G Wi-Fi service. Those are the
  specific details the other two records state.
* **ABC.** Its focus states the first passenger service (4:31am, 13 km,
  Bankstown–Sydenham) and riders celebrating ("turned out to mark the
  opening").

## 2. Contract basis

* Section A.36, R3, the same occurrence: "A record that reports two
  occurrences goes only with the records whose specific details it shares.
  If that cannot be determined, it stays apart from both."
* R3 also lists "a milestone, and an activity held to mark or verify it" as
  different occurrences.
* Prompt `event-identity-grouping-v10`:
  * line 46 states the mixed-record rule;
  * line 45 lists the marking activity, with the example "a ride event";
  * line 55, for confirmation, says "never put records of different
    occurrences in one group".
* The confirmation instruction does not say how line 46 applies when a record
  reports both occurrences.
* Hypothesis (unproven; the helper's reasons are not observable): in a
  confirmation, lines 45 and 55 override line 46.

User decision that bounds this work (section A.30, RC-42): the operator's
Incheon opening and the Ministry's same-day experience event are different
events. This package does not change that: a record that reports **only**
the activity stays apart. **Label L1 needs the user's confirmation:** does
스마트투데이 report the completion, which is shared, or the Ministry
activity? The user's 2026-11-07 instruction says the Evidence points to the
same Wi-Fi completion and the 21 October launch. RC-42 recorded the activity
as a separate event. Claude does not decide between the two
(`BLOCKED_USER_DECISION`).

## 3. Valid corpus source (the RC-64 lesson)

RC-64 was invalid because its corpus was built from audit `evidence_highlights`
(at most 2 sentences, clipped to 240 characters), not from the Event Identity
input. The corpus here must be the real input:

1. For each record, fetch the audit's `canonical_source_url` again. Pass the
   page through the production `EvidenceService` principal-document path.
2. Accept the record only when `sha256(substantive_content)` equals the
   audit's `evidence.content_sha256`. Otherwise drop it and log it, and do not
   substitute anything.
3. Segment the content with `segment_evidence_sentences`. Take the sentences
   whose IDs are the audit's `event_identity.proposal_excerpt_sentence_ids`,
   which is the Scope focus within the RC-18 tiers, and number them S1..Sn
   (RC-42).
4. Build `EventIdentityGroupingRequest` records with the production code, not
   by hand.

| Run | Candidate (prefix) | Title | Excerpt IDs | content_sha256 (prefix) | Proposed label |
| --- | --- | --- | --- | --- | --- |
| 42186338279 | `cand_010cdde712fe2f1c` | 仁川地下鉄 5G Wi-Fi開通 (BigGo) | S8,S9,S10 | `29680c42d876` | INCHEON-WIFI-START |
| 42186338279 | `cand_7c5e6ae670391bb1` | 인천교통공사 5G Wi-Fi 시대 개막 (서울일보) | S1,S3 | `24b3ad7a91de` | INCHEON-WIFI-START |
| 42186338279 | `cand_9ce03b4da316d4ea` | 와이파이도 5G로 … 전환 완료 (스마트투데이) | S1,S2 | `6814dd94eb73` | **L1: INCHEON-WIFI-START or MINISTRY-EVENT (user)** |
| 42148605765 | `cand_1d6f2d3c0e368494` | 雪梨地鐵西南延伸線通車 (IndexBox) | S1,S2 | `4b6c036d39ce` | SYDNEY-SW-OPENING |
| 42148605765 | `cand_db84b77e41ccc784` | Ouverture du prolongement sud-ouest | S1,S2 | `c9ff934091d1` | SYDNEY-SW-OPENING |
| 42148605765 | `cand_3a95fcf226602be8` | 'Absolutely ecstatic' (ABC) | S2,S3,S5 | `971166d4e2c9` | SYDNEY-SW-OPENING |

Controls: different occurrences of a similar subject, which must stay
apart. Take all of them from the same two audits, with the same procedure:

* Run 42186338279:
  * Rome CAF Urbos commissioning (`Tram CAF Urbos`) and Bergamo T2 tests
    (`Tram per Villa d'Almè`);
  * Kraków phase-4 opening and Delft tram 19;
  * LA Metro D Line closure and the Sydney opening-date report;
  * the Daegu fire-brigade programme and the Daegu Transportation Corporation
    drill. These need a user label: section 59 accepted the Daegu-type
    residual duplicate, so it is unlabelled unless the user labels it.
* Run 42148605765: the Bergamo T2 and Taoyuan Green Line pre-opening items,
  which are different subjects.
* Unlabelled scheduled-versus-occurred pair (R3 "the same occurrence"):
  Wuhan 12 "間もなく全線開通" and "全線開通" (Run 42186338279). Include it only
  when the rebuilt text identifies the same scheduled act.

## 4. Measurement and acceptance criterion

* Procedure: the production RC-52 Event Identity evaluation, which is three
  independent procedures, each with two nominations and confirmations. One
  evaluation per prompt per round, three rounds:
  * the baseline `event-identity-grouping-v10`;
  * a candidate that only amends the confirmation line. Draft for review, not
    applied: "In a confirmation, a record that reports two occurrences goes
    with the records of the occurrence whose specific details it states;
    reporting an activity that marks or verifies that occurrence does not by
    itself make it a different event. It is a single-record group only when
    the shared details cannot be determined."
* Estimated cost: RC-64 used about 20 calls per evaluation on 19 records, so
  this needs about 2 prompts × 3 rounds × about 20 calls, roughly 120 paid
  calls. Proposed cap: 200.
* Adoption requires all of the following (R7, section A.36):
  1. In every round, no differently labelled pair is merged (0).
  2. Every same-labelled mixed-record pair (ABC and the other Sydney records;
     스마트투데이 and the other Incheon records, if L1 is INCHEON-WIFI-START)
     is merged in at least 2 of 3 rounds.
  3. Same-labelled recall on the other pairs is not lower than the baseline
     in any round. This is the RC-51 lesson: RC-51 was reverted because recall
     fell.
  4. Golden ED01–ED28 and the failure-path cases stay unchanged offline.
* Regression risks:
  * merging a record that reports only the marking activity (RC-42 Incheon
    Ministry event; R3);
  * merging an announcement-only record with the occurrence (RC-45);
  * lower batch recall from longer confirmation guidance.

## 5. Result required before adoption

Record the result in `acceptance/event_identity/rc66_r7_measurement.json`,
using the same fields as rc64, plus `corpus_source: "refetched,
sha256-verified Event Identity input"` and the list of records that failed
the hash. Without a passing result, prompt v10 stays in production. This
offline night changed no Event Identity rule, prompt, schema or Golden.

## 6. Adversarial review of this package (Phase B, 2026-11-07, offline)

The cross-run audit (REPORT section 72) found evidence that weakens the
hypothesis this package was written for. The acceptance design below is
amended. No Domain Rule or prompt is changed.

**Disconfirming evidence.**
* The "mixed record" explanation (section 1) covers only some of the wrong
  confirmation splits in runs #24–#34. The wrong splits also include:
  * pure same-occurrence reports with no marking activity: the Daegu
    Myeongdeok entrance (#24), the Seoul Line 2 outage reported in Japanese
    and Korean (#26), two reports of one Kim Min-seok statement (#32), two
    Kyiv attack reports (#34), and the 8 Ulsan depot records returned as 8
    single-record groups (#34);
  * near-identical copies: the Wuhan 【画像】 gallery pages (#25, #26, #33);
  * scheduled versus occurred: Wuhan "間もなく全線開通" (#26, #29, #34);
  * duplicate membership inside the confirmation answer (Wirye #26, #29;
    Incheon 10th anniversary #30; Gwangju #34).
* The helper is not consistent about marking activities. In #24 it grouped
  the Ministry's 5G verification record (디지털투데이) with the operator's
  launch (이데일리). That is the opposite of the RC-42 decision and of the
  separation seen in #25 and #34.
* Confirmation is also the only guard against batch mega-groups. In #29 it
  correctly split a 26-record group of unrelated items; in #31 it split a
  14-record group mixing IEC 61373, Hiroshima, Gera, Napoli and others. A
  candidate that loosens confirmation can only be judged safe when such
  groups are in the corpus.

**Defects in sections 3–4 and the amendments.**
1. *Controls that never reach the helper.* LA Metro D Line against Sydney is
   a `PROPOSAL_REGION_CONFLICT` pair that Python removes before
   confirmation, so it cannot test a confirmation prompt. Replace it.
2. *Too few negative controls, and none of the dangerous kind.* Add these
   real records, rebuilt with the same sha256 procedure:
   * all members of the #29 `event-identity-batch-1-p3-n2:group-5` (26) and
     `group-4` (12) groups, and of the #31 `event-identity-batch-1-p2:group-3`
     (14) group, as recorded confirmation inputs;
   * a record that reports only the Ministry activity (Run 40817530617
     records named in section A.26). This audit is selection-audit-v1; if a
     record cannot be rebuilt, record EVIDENCE_UNAVAILABLE;
   * the 국감 statement "[국감] 인천지하철 5G 와이파이 구축…전국 확대 '목소리'"
     (#20), which must stay apart from the launch (RC-45 statement rule);
   * the Barcelona fire, the TMB cause confirmation and the service-restored
     report (#30, #31): R3 says the incident and its later findings or
     measures are different occurrences.
3. *A vacuous criterion.* Criterion 1 (no false merge) is met trivially when
   the batch never nominates a control. Add a direct confirmation
   measurement:
   * **M-C:** replay the exact recorded confirmation inputs (record maps from
     the audits, with rebuilt excerpts) under v10 and the candidate, three
     times each.
   * Report, per input group, the partition against the labels.
   * Report the number of differently labelled pairs that reach a
     confirmation. It must be at least the number of same-labelled pairs.
4. *Mechanisms the candidate does not target.* Add same-labelled pure
   over-split pairs (Daegu entrance, Seoul outage, Kyiv, Kim Min-seok,
   Ulsan) as a separate stratum. Criterion 3 then shows whether the
   candidate helps, hurts or does nothing outside the mixed-record case.
   That result decides whether mixed records are the right target at all.
5. *Label leakage.* The labels in section 3 were drafted by Claude from
   titles. Before any paid call, labels must be set from the rebuilt excerpt
   text by the user or an independent pass, without seeing any helper
   answer. L1 and the Daegu pair stay user decisions.
6. *Duplicate membership.* A confirmation answer that names a record twice
   loses that record through RC-42 per-member rejection. This is not a
   prompt-content effect, so report it separately (count per round). It
   must not be counted as a split or a merge of the labelled pair.

**Verdict.** The package as first written would have measured a narrow fix
on a corpus biased toward merges. With amendments 1–6 it can detect false
merges and separate the mechanisms. It is still `BLOCKED_PAID_VALIDATION`.
Raise the estimated cost to about 200 calls (M-C adds about 12 confirmation
inputs × 2 prompts × 3).

## 7. Phase C additions (2026-11-08, offline)

* **Cross-language stratum is required.** A pair kept by some confirmation
  but split by another is split in 13% of cross-language confirmations and
  6% of same-language ones (2,806 observations, runs #24–#34). Include
  ja/ko/zh/latin mixed same-occurrence pairs: Seoul Line 2 outage (ja/ko),
  Sydney (zh/fr/en/es), Incheon (ja/ko).
* **Do not read the `-n2` gap as an ordering effect.** Confirmations of
  reversed nominations split 15% against 4%. That is a selection effect:
  RC-44 sends later confirmations only pairs no earlier confirmation judged.
  Any comparison must stratify by nomination.
* **A confirmation-only change cannot remove most duplicates.** Of 6
  final-report duplicate pairs detected by a same-language title proxy, 4
  were never proposed together by any nomination; only 2 were split by a
  confirmation. Report batch-recall misses alongside the M-C confirmation
  result.
