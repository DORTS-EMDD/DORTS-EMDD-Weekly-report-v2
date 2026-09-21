# V2 Golden Acceptance Corpus v1

Golden Corpus 是 V2 production implementation 開始前的 authoritative acceptance baseline。它用固定的 input facts 與 expected domain outcome，先定義代表性輸入應經過哪些 pipeline boundary，以及正確結果應為何。

Golden Corpus 不是 production code，也不是 executable Python test suite。後續 implementation tests 可以消費這些 JSON fixture，但本資料夾本身不負責實作 Evidence Service、Classifier、Selector、Event Dedup、MaiAgent、Validation 或任何其他 production owner。

## Authority and provenance

每個 expected outcome 都以 docs/ARCHITECTURE_CONTRACT.md 的 v0.5 FINAL_LOCKED 為 authoritative source。V1 只提供 read-only case material、regression intent 與 historical lessons；V1 的 expected outcome 不會自動成為 V2 正確答案。

本版 48 個 case 全部標示為 SYNTHETIC_CONTRACT_CASE。這是刻意的選擇：本次檢視到的 V1 regression tests 具有可用的 case intent，但沒有需要在 V2 中固化、且足以安全重建為 authoritative evidence snapshot 的完整歷史 fixture。未 materialize named historical cases，不以記憶杜撰新聞、官方公告或 source text。

本版沒有把 Bukit Gombak、TransLink elevator 或 Tokyo overhead-wire 等名稱假裝成 V2 historical fixture。若未來有合法、固定、可重現且不需大量複製受版權保護正文的 evidence snapshot，可新增 V1_HISTORICAL_FIXTURE 或 V1_REGRESSION_DERIVED case；否則應維持 synthetic case。

## Contract boundaries

### Candidate → Event

Candidate 是 Search / Retrieval 發現的單一候選來源。Candidate 必須先完成 Evidence、Scope、Date，才可交給 Event Identity 做跨來源的 Candidate-to-Candidate Event Equivalence。同一事件的多個 candidates 可以合併成一個 Event，但必須保留 candidate IDs、canonical / primary source、supporting sources 與 source-specific claim provenance。

相似 title 不等於同一 Event。G12 鎖定 multilingual candidates 應合併為一個事件；G13 鎖定不同城市、專案或 package 不得過度 dedup；G16 鎖定同一事件成立與 factual claim unresolved 可以同時存在。

### NOT_EVALUATED

NOT_EVALUATED 表示 upstream authoritative owner 已拒絕或尚未讓 pipeline 到達該欄位，因此 downstream 不得重新推導、補值或 assert 一個答案。

例如 G01、G02、G18 在 Evidence stage 被拒絕，所以 Scope、Date、Event Identity、Category、E&M Taxonomy 與 Reportability 都是 NOT_EVALUATED。G14 在 Scope stage 被拒絕，所以 Temporal 及其後欄位不應被當成正式結果。G15 在 Temporal stage 被拒絕，所以 Category 與 Reportability 不應被 assert。

這些 cases 驗證的是 pipeline boundary，而不只是最後的 label。

### Evidence and source content

source_content 是 fixture 的最小必要固定片段，不是新聞全文資料庫。G01 使用 null 代表 title / snippet-only；G02 使用 homepage-like content 代表 Source-to-Candidate Mismatch；G18 使用 search/navigation shell 代表缺乏事件 substantive content。所有 URL 都是 fixtures.invalid，不應被 live fetch。

### Procurement

G10、G11、G19、G20、G21 覆蓋 standard procurement、innovative procurement、below USD 3M、amount unknown 與無可靠匯率換算。原幣金額應保留；USD 3M 是 importance signal，不是 eligibility gate；不得猜匯率。

### E&M taxonomy

七大主系統只能使用：

* 電聯車
* 號誌
* 供電
* 通訊
* 自動收費
* 機廠維修設備
* 月臺門

[] 表示事件可成報，但沒有合理的七大主系統對應。G17 的 elevator case 因此保持空陣列，不建立「垂直運輸設備」或「通風空調系統」等第二套 registry。

## Case index

| Case | Contract purpose | Origin |
| --- | --- | --- |
| G01 | Title-only evidence rejection | Synthetic |
| G02 | Wrong landing page rejection | Synthetic |
| G03 | Valid new technology | Synthetic |
| G04 | Valid new material | Synthetic |
| G05 | Valid new method | Synthetic |
| G06 | Major urban-rail technical accident | Synthetic |
| G07 | Low-value in-scope accident | Synthetic |
| G08 | Operations policy | Synthetic |
| G09 | Operations dispute | Synthetic |
| G10 | Standard E&M procurement | Synthetic |
| G11 | Innovative procurement | Synthetic |
| G12 | Duplicate multilingual event | Synthetic |
| G13 | Similar titles, different events | Synthetic |
| G14 | Non-urban rail scope rejection | Synthetic |
| G15 | Out-of-range source rejection | Synthetic |
| G16 | Conflicting source claims | Synthetic |
| G17 | Non-seven-system but reportable | Synthetic |
| G18 | Search/navigation shell rejection | Synthetic |
| G19 | Below USD 3M but innovative | Synthetic |
| G20 | Amount unknown | Synthetic |
| G21 | No reliable currency conversion | Synthetic |
| G22 | Streetcar / Tram equivalence | Synthetic |
| G23 | Commuter rail without eligible-mode proof | Synthetic |
| G24 | Commuter label with explicit Metro proof | Synthetic |
| G25 | Airport Metro | Synthetic |
| G26 | Airport AGT / People Mover | Synthetic |
| G27 | Conventional airport express | Synthetic |
| G28 | Funicular out of scope | Synthetic |
| G29 | Cable railway out of scope | Synthetic |
| G30 | Urban maglev | Synthetic |
| G31 | Intercity / high-speed maglev | Synthetic |
| G32 | Mixed Metro and mainline, resolvable | Synthetic |
| G33 | Mixed Metro and mainline, unresolved | Synthetic |
| G34 | Urban-rail operator with non-urban event | Synthetic |
| G35 | Cross-language eligible Subway | Synthetic |
| G36 | Exact period_start | Synthetic |
| G37 | Exact period_end | Synthetic |
| G38 | One day before period_start | Synthetic |
| G39 | One day after period_end | Synthetic |
| G40 | Explicit offset source calendar date | Synthetic |
| G41 | Timezone-less source timestamp | Synthetic |
| G42 | Date-only source | Synthetic |
| G43 | Missing authoritative date | Synthetic |
| G44 | Discovery-only date | Synthetic |
| G45 | Publication versus modified date | Synthetic |
| G46 | Publication versus Event date | Synthetic |
| G47 | Conflicting publication facts | Synthetic |
| G48 | Procurement deadline versus notice publication | Synthetic |

## Source-associated date facts

Fixtures that formally reach Temporal provide a `candidates[].source_date_facts`
array. Each fact records the raw source value, its factual `date_kind`, the
principal-document association, source field/node provenance, and explicit
timezone or offset when present. `Candidate.published_at` remains discovery
metadata and is never authoritative by itself. Multiple same-kind facts for
one principal document are retained when they conflict so the expected
`DATE_CONFLICT` outcome is explicit.

## V1 files inspected

The following V1 files were inspected read-only for input shape, regression intent, and candidate/source patterns:

* test_rc2_evidence_independent_contract.py
* test_v55b_enrichment_evidence_validity.py
* test_v55c_multilingual_major_accident.py
* test_v21_quality_gates.py
* test_p2k3_category_gates.py
* test_v21_operational_topics.py
* test_electromechanical_procurement.py
* test_canonical_event_identity.py

No V1 private API, rescue behavior, backfill behavior, Streamlit state, V1 category precedence, or source-code string assertion is part of this corpus.

## Adding a case

To add a case:

1. Start from the common schema used by the existing JSON fixtures.
2. Separate candidates input facts from the expected domain outcome.
3. Assign a new stable case_id and update golden/manifest.json.
4. Set origin_type explicitly to V1_HISTORICAL_FIXTURE, V1_REGRESSION_DERIVED, or SYNTHETIC_CONTRACT_CASE.
5. Use only fixed source content or a minimal synthetic fragment; do not use live search or current fetches.
6. Derive expected values from the locked Architecture Contract.
7. Set downstream fields to NOT_EVALUATED whenever an upstream owner rejects the candidate.
8. Keep Candidate lifecycle and Event lifecycle separate.

既有 expected outcome 只有在下列情況之一成立時才可修改：

    A. Architecture Contract changed legitimately
    or
    B. Golden fixture itself was factually malformed

不得因 implementation currently fails、報告篇數不足、單一網站失敗或需要讓 tests passing 而修改答案。任何無法由 Architecture Contract 明確決定的 case，都應先列入 contract ambiguity，停止該 case 的 Golden lock，不得猜。

## Determinism

    LIVE_SEARCH = NO

本 corpus 不依賴 DDGS、Google News、RSS live result 或 current website fetch。Commit 後的 JSON 應在相同 input 下保留相同 expected contract。
