# Weekly-report V2 — AGENTS.md

本專案為「捷運技術週報 AI 自動產生系統」V2。

本檔為所有工程工作的第一層治理規則。

完整且具拘束力的 Domain / Architecture Contract 位於：

`docs/ARCHITECTURE_CONTRACT.md`

凡涉及 architecture、domain rule、owner、pipeline、Evidence、分類、選題、MaiAgent、Validation、Debug、Delivery 或 Golden contract 的修改，修改前必須先讀完整 Architecture Contract。

若本檔與 Architecture Contract 出現實質矛盾，不得自行選一邊實作；應停止修改並指出矛盾。

## 1. 最高原則

### 禁止挖東牆補西牆

任何 bug / regression 必須先確認：

* earliest root cause
* authoritative owner
* existing contract
* minimum correct modification boundary

不得用下游 fallback、rescue、backfill、duplicated logic、second source of truth 或 test-specific production special case 掩蓋上游 root cause。

只有能證明為合法且可泛化之 domain rule，才可新增 architecture mechanism。

## 2. Tests Passing 不是充分條件

Tests passing 是必要條件，不是完成的充分條件。

若修改造成 owner 重複、source of truth 分散、duplicated decision logic、fallback 疊加、architecture complexity 無合理需求或偷偷改變既有正確 contract，即使 tests 全過仍判定 FAIL。

不得為了讓 tests 通過而修改正確的 Golden / contract。

## 3. Single Owner

一個 Domain Decision 只能有一個 authoritative owner。

Downstream consumer 不得重新推導 upstream decision、不得修改 upstream decision、不得在 upstream reject 後重新救回。

Owner 名稱可調整，但責任不得重複。

## 4. Core Pipeline

Production pipeline 原則固定為：

```text
Config
→ Search / Retrieval
→ Canonical Candidate
→ Authoritative Evidence
→ Scope + Date
→ Event Dedup
→ Category + E&M Taxonomy
→ Reportability + Ordering
→ MaiAgent
→ Validation
→ Report Assembly
→ PDF / Email / Debug
```

Pipeline 原則上只能向前。

## 5. Search

Search 只負責 discovery。

Search 不得正式決定 Evidence Ready、Scope、Date validity、Category 或 Reportability。

正式執行必須涵蓋四種 discovery intent：

* technology
* major incident
* operations
* procurement

每個啟用 intent 都必須至少 `PLANNED + ATTEMPTED`。

搜尋最高 discovery priority：

> 新技術、新材料、新方式。

Search intent 不等於正式 Category。

## 6. Evidence First

沒有可信且與事件相符的 substantive source content，不得進正式報告流程。

Title、Google News / DDGS snippet、homepage、search result page、category page 等，不得單獨作為 Formal Evidence。

`EVIDENCE_READY` 至少必須同時符合：

* Source Resolved
* Substantive Content Available
* Source-to-Candidate Match
* Factual Substance

不得只靠 title、snippet、字數、title overlap 或 source domain 判定 Evidence Ready。

若原始來源不可用，只有 Evidence Service 可以在同一 evidence acquisition responsibility 內尋找同事件可信替代來源。

## 7. Candidate 與 Event 必須分離

Candidate 是搜尋所得的候選來源。

完成 Evidence、Scope、Date 後，由 Event Identity 做跨來源合併。

Candidate lifecycle 與 Event lifecycle 不得混為同一條。

Event Dedup 後：

* Classifier 判 Category
* E&M Taxonomy 判相關主系統
* Selector 只判 Reportability 與 Ordering

## 8. Category

Primary Category 固定為：

* 技術新知
* 重大事故
* 營運動態
* 機電標案

Subtype 不得形成新的 workflow lane。

事件若透過採購發生，但主要價值是新技術、新材料、新方式，可歸為：

```text
primary_category = 技術新知
subtype = procurement
```

Downstream 不得再建立第二套 category conflict resolver。

## 9. E&M Taxonomy

七大主系統固定為：

* 電聯車
* 號誌
* 供電
* 通訊
* 自動收費
* 機廠維修設備
* 月臺門

七大主系統不得作 Candidate survival gate。

電梯、電扶梯、通風空調等非七大主系統設備，如事件本身有足夠都市軌道價值仍可成報，但不得硬映射成七大主系統。

## 10. Reportability

Selection 的正式責任只有：

```text
REPORTABLE / NOT_REPORTABLE
+
DETERMINISTIC ORDERING
```

沒有最低篇數、最高篇數、Category quota、A/B/C level、backfill 或 rescue。

有多少合格事件，就寫多少。

0 篇是合法結果。

「對臺北捷運有參考價值」不得單獨救回缺乏事件本身實質價值的普通事件。

Ordering 採可解釋 deterministic / lexicographic rules，不使用不透明總分。

## 11. MaiAgent

MaiAgent 只有一個 production responsibility：

> 正式週報撰稿。

MaiAgent 不得搜尋、選題、Fetch、Dedup、補 Evidence、修改 Scope、修改 Category、修改 Reportability、猜缺漏 metadata 或自行查外部背景資訊。

事件摘要：

> Evidence 能證明多少，就寫多少。

「臺北捷運局啟示」可以做專業分析，但不得捏造臺北捷運現況、設備狀態、法規要求或其他未提供事實。

MaiAgent 平台角色設定屬 external configuration；Repository 只保存 reference / declared version，不得假裝 Git 已驗證平台實際設定。

## 12. Validation

Validator 與 MaiAgent Writer 必須是不同責任。

Validator 只檢查：

* factual grounding
* source integrity
* required fields
* DORTS implication boundary

每個 Event 最多一次 semantic correction。

單一 Event FAIL 只淘汰該 Event，不得拖垮其他 PASS Events。

Transport retry 與 semantic correction 必須分開計算。

## 13. Report / Delivery

```text
Final report count = Validation PASS count
```

0 篇仍正常產生正式 artifact。

GitHub Actions 負責 production automation。

Streamlit 只做 UI / manual operation。

兩者共用同一 Email / Delivery owner。

Automation retry 不得造成同一正式 artifact 重複成功寄送。

## 14. Debug

Debug 只能觀察，不得參與 production decision。

每次 execution 只有一份 authoritative：

```text
RunTrace
```

由同一 RunTrace 產生：

```text
developer_debug_*.json
engineering_summary_*.json
```

兩份 JSON 不得各自重新計算 Domain Decision。

Candidate counts 與 Event counts 必須分開。

每次執行必須具有：

```text
report_id
run_id
```

## 15. UI

Streamlit 只負責 Config、Progress、Result display、Download、Manual Email 與 Developer summary。

核心 pipeline 必須可脫離 Streamlit 執行。

UI 不得持有任何 Domain Decision。

### Entry Point Contract

`main.py` 與 `streamlit_app.py` 必須共用同一 production core workflow；entry point 可以不同，但 Domain Logic 不得分叉。

* `main.py` 為 automation / CLI entry point。
* `streamlit_app.py` 為 interactive UI entry point。
* 兩者不得各自實作或重新推導 Search、Evidence、Scope、Date、Event Dedup、Category、E&M Taxonomy、Reportability、MaiAgent workflow、Validation 或 Report Assembly。
* GitHub Actions 只負責 orchestration，不得建立另一套 domain logic。
* Streamlit 只負責 UI / manual operations，不得建立 UI-specific fallback、rescue、category 或 selection logic。

## 16. Golden / Tests

V2 不整套搬 V1 tests。

優先：

1. Golden contract tests
2. Owner unit tests
3. Pipeline E2E
4. Delivery tests

Historical incident 可以變成 Golden Case，但不得變成 production special case。

Golden expected outcome 不得只為讓 tests passing 而修改。

## 17. V1 Reuse

V1 為：

```text
FROZEN_REFERENCE
```

可 selective reuse：

* provider transport
* MaiAgent API transport
* pure URL / date helpers
* PDF primitives
* SMTP / MIME primitives
* formatting assets
* GitHub Actions orchestration primitives
* Golden regression cases

不得整體移植：

* V1 selector
* V1 evidence lifecycle
* rescue / backfill
* A/B/C survival tiers
* multi-stage dedup
* whole-report all-or-nothing validation
* historical report repair / reconciliation architecture

V2 不要求輸出與 V1 相同。

## 18. Architecture Change Guard

若 implementation 需要新增第二個 owner、fallback、rescue、backfill、duplicated Category / Evidence logic、downstream 修改 upstream decision 或 test-specific rule，必須先停止 implementation，重新確認 Domain Requirement 與 Architecture Contract。

不得直接繼續補洞。

## 19. Definition of Done

功能完成至少同時符合：

1. root cause / requirement 明確
2. owner 明確
3. contract 明確
4. 無 duplicated owner
5. tests passing
6. Golden 無 regression
7. pipeline trace 可解釋
8. 無不必要 fallback / rescue / workaround
9. 既有正確 behavior 未被偷偷改變
10. architecture complexity 未不合理增加

> Tests passing alone 不代表完成。

## STATUS

```text
AGENTS_VERSION = concise-v1
ARCHITECTURE_CONTRACT = docs/ARCHITECTURE_CONTRACT.md
ARCHITECTURE_BASELINE = v0.5 FINAL_LOCKED
V1_STATUS = FROZEN_REFERENCE
ENTRY_POINT_CLARIFICATION = APPLIED
```
