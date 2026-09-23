# Weekly-report V2 — Engineering Governance & Architecture Contract

本專案為「捷運技術週報 AI 自動產生系統」V2。

本專案目標為責任單一、可追蹤、可驗證、可重現、易維護。

本檔為完整且具拘束力的 Domain / Architecture Contract。

Root `AGENTS.md` 為精簡每日工程治理入口。

任何 Domain / architecture 修改不得違反本檔。

## A. Governance

1. 禁止挖東牆補西牆。
2. Root cause、authoritative owner、existing contract、minimum correct boundary 優先。
3. Tests passing 不是充分條件。
4. 一個 Domain Decision 只能有一個 authoritative owner。
5. Downstream 不得修改 upstream decision。
6. Reject 後不得 downstream rescue。
7. Test-specific production special case 原則禁止。

任何 bug、regression 或 implementation 偏差，必須先確認 earliest root cause、authoritative owner、existing contract 與 minimum correct modification boundary。不得以 fallback、rescue、backfill、duplicated logic、second source of truth 或 test-specific production special case 掩蓋上游 root cause。

Tests passing 是必要條件，不是完成的充分條件。若修改造成 owner 重複、source of truth 分散、duplicated decision logic、fallback 疊加、architecture complexity 無合理需求或偷偷改變既有正確 contract，即使 tests 全過仍判定 FAIL。不得為了讓 tests 通過而修改正確的 Golden / contract。

一個 Domain Decision 只能有一個 authoritative owner。Downstream consumer 不得重新推導 upstream decision、不得修改 upstream decision、不得在 upstream reject 後重新救回。Owner 名稱可調整，但責任不得重複。

## B. Authoritative Owners

下列 responsibility 必須各自具有明確且唯一的 authoritative owner：

* Region Registry
* Search Planner
* Candidate Normalizer
* Evidence Service
* Temporal Rule
* Scope Classifier
* Event Identity
* Classifier
* E&M Taxonomy
* Selector / Reportability
* MaiAgent Writer
* Validator
* Report Service
* Delivery Service
* Debug Service

Owner module 名稱未來可調整，但 responsibility 不得重疊。若新增 owner、拆分 owner 或合併 owner 會改變 decision responsibility，必須先確認本 Contract 的 architecture guard。

## C. Core Pipeline

正式 pipeline：

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

Pipeline 原則只能向前。Downstream 不得回頭修改 upstream decision，也不得在 upstream reject 後以 rescue、backfill 或 fallback 將其救回。

## Entry Point Contract

本章是對既有 Single Owner、UI Contract、GitHub Actions orchestration 與 shared core pipeline 的 documentation-only clarification，不新增 Domain Owner 或新的 Domain Rule。

Production 可以有多個 entry point，但 Domain Logic 只能有一套：

```text
weekly.yml
→ main.py
→ shared production core workflow
```

以及：

```text
streamlit_app.py
→ shared production core workflow
```

正式規則：

1. Production 可以有多個 entry point，但 Domain Logic 只能有一套。
2. `main.py` 是 GitHub Actions / automation 的正式程式入口，也是 CLI entry point。
3. `streamlit_app.py` 是人工操作與展示入口，也是 interactive UI entry point。
4. 兩個 entry point 必須呼叫同一套 shared production core workflow。
5. 兩者不得各自實作或重新推導 Search、Evidence、Scope、Date、Event Dedup、Category、E&M Taxonomy、Reportability、MaiAgent workflow、Validation 或 Report Assembly。
6. GitHub Actions 只負責 orchestration，不得持有 Domain Decision 或建立另一套 domain logic。
7. Streamlit 只負責 UI / manual operations，不得持有 Domain Decision。
8. 禁止 CLI-specific Domain Logic、Streamlit-specific Domain Logic、GitHub Actions-specific eligibility rules、UI-specific fallback 與 UI-specific rescue。
9. 在相同 Run Config 與相同外部輸入條件下，`main.py` 與 `streamlit_app.py` 應透過 shared core workflow 得到相同 Domain Outcome。

Entry point 可以不同，Production Domain Logic 只能有一套。任何 entry point-specific workaround 都不得成為第二個 owner 或第二套 source of truth。

## D. Run Identity

每次執行必須分開：

```text
report_id
run_id
```

`report_id` 表示報告期別。

`run_id` 表示單次 execution。

Debug、artifact provenance、delivery audit 必須可追溯兩者。

## E. Region

只有：

```text
global
selected
```

兩種 region mode。

「指定先進國家」預設清單：

* 臺灣
* 韓國
* 香港
* 英國
* 德國
* 加拿大
* 荷蘭
* 義大利
* 奧地利
* 挪威
* 葡萄牙
* 日本
* 新加坡
* 澳洲
* 法國
* 美國
* 西班牙
* 瑞士
* 瑞典
* 丹麥

`global` 包含以上市場，以及印度、巴西、俄羅斯與其他未來支援市場。

Region Registry 為唯一 source of truth。

## F. Search / Discovery

Search 只做 discovery。

四種 discovery intent：

* technology
* major incident
* operations
* procurement

每個啟用 intent 至少：

```text
PLANNED + ATTEMPTED
```

Provider 0 result 不代表 coverage failure。

Provider failure 必須記錄。

最高 discovery priority：

> 新技術、新材料、新方式。

Search intent 不等於正式 Category。

Search 不得正式判：

* EvidenceReady
* Scope
* Date
* Category
* Reportability

Search early rejection 只允許：

* malformed result
* invalid URL
* exact duplicate URL
* 明確 provider noise

Search 不得因缺乏 snippet、標題相似度、來源 domain 或單一 provider 結果而正式決定 Evidence、Scope、Date、Category 或 Reportability。

Search keyword、discovery intent、query family、搜尋語言與搜尋結果都不是
Category authority：

```text
SEARCH_KEYWORDS_CATEGORY_AUTHORITY = NO
```

## G. Procurement

Procurement discovery 可來自：

* 政府採購平台
* 都市軌道 operator procurement page
* tender / award notice
* 搜尋與專業媒體補漏

USD 3M equivalent 為 importance signal，不是 eligibility gate。

低於 USD 3M 或金額未知，不得因此自動淘汰。

沒有可靠換算資料時：

> 保留原幣金額，不判 USD 3M signal。

MaiAgent 不得猜匯率。

## H. Evidence

Formal Evidence 可為：

* article body
* official press release
* government/operator notice
* procurement / award notice
* technical bulletin
* formal project release
* 其他可信 substantive source content

不得單獨作 Formal Evidence：

* title
* Google News / DDGS snippet
* publisher name
* search query
* redirect URL
* homepage
* category page
* search result page

`EVIDENCE_READY` 必須同時滿足：

1. Source Resolved
2. Substantive Content Available
3. Source-to-Candidate Match
4. Factual Substance

不得只靠：

* 字數
* title overlap
* source domain

判 EvidenceReady。

Evidence rejection reasons 可包含：

```text
URL_UNRESOLVED
CONTENT_UNAVAILABLE
SOURCE_PAGE_MISMATCH
TITLE_ONLY
INSUFFICIENT_SUBSTANCE
UNTRUSTWORTHY_SOURCE
```

Reason 只作 diagnostic，不建立 workflow lane。

Alternative source 只能由 Evidence Service 在同一 evidence acquisition responsibility 內處理。

沒有可信且與事件相符的 substantive source content，不得進正式報告流程。

### Evidence semantic match mechanism

`EvidenceService` remains the sole authoritative owner of:

```text
EVIDENCE_READY
EVIDENCE_REJECTED
```

EvidenceService may use a restricted Semantic Judge helper for the
Source-to-Candidate Match decision. The helper is not a second owner and
cannot create either Evidence terminal state.

EvidenceService may reject a Candidate before invoking the helper when a
deterministic structural Evidence gate fails, including unresolved or invalid
resource provenance, a discovery feed, a homepage / listing / search shell,
title-only content, missing principal substantive body content, or unusable
content. A Candidate that passes these gates must use the single semantic
judgment path. Exact H1, HTML title, URL, token overlap, numeric overlap,
keyword match, or fuzzy lexical match cannot create a positive deterministic
`EVIDENCE_READY` bypass.

The Semantic Judge receives only EvidenceService-supplied Candidate and
principal body material. It may return `SAME_EVENT`, `DIFFERENT_EVENT`, or
`UNCERTAIN` with validated body support or conflict spans. It may not search,
fetch, use external facts, decide Scope, Date, Category, E&M Taxonomy, or
Reportability, and it may not take on MaiAgent's writing responsibility.

EvidenceService validates the helper response and makes the final decision.
`SAME_EVENT` is usable only when its support spans point to supplied body text
and pass span validation. `DIFFERENT_EVENT`, `UNCERTAIN`, invalid or malformed
responses, invalid support spans, timeout, and transport/provider failure are
conservative Evidence rejection conditions. Phase 1 permits one semantic
judge call per Candidate and no retry to obtain a different relation.

The detailed input, output, validation, failure, versioning, and RunTrace
requirements are authoritative in
`docs/EVIDENCE_SEMANTIC_JUDGE.md`.

The structural representation, principal-document boundary, principal-body
extraction, ambiguity, and structural diagnostic requirements are
authoritative in `docs/EVIDENCE_STRUCTURAL_DOCUMENT.md`. This subordinate
implementation contract does not add a Domain Owner or change EvidenceService
ownership of `EVIDENCE_READY` / `EVIDENCE_REJECTED`.

## I. Temporal

正式期間 eligibility 預設使用：

> source publication / notice date

Event date 可保存，但不得拿來救回期間外來源。

Temporal Rule 唯一負責：

* parsing
* timezone
* inclusive / exclusive boundary
* DATE_VALID

下游不得重新解讀 publication / notice date 或以其他日期將期間外來源救回。

Controlling-date provenance、source-type precedence、calendar-date、timezone、
inclusive period boundary、failure diagnostics 與 Evidence factual interface 的
詳細規則，以 `docs/TEMPORAL_CONTRACT.md` 為 authoritative subordinate contract。
該文件不新增 Domain Owner、pipeline stage 或 workflow lane，Temporal Rule 仍為
`DATE_VALID` 的唯一 owner。

## J. Scope

正式範圍包括：

* Metro
* MRT
* Subway
* Light Rail
* Tram
* Urban Rail
* AGT
* Monorail
* People Mover

一般鐵路、高鐵、公車、航空、旅遊不屬正式 scope。

Scope 只由 Scope Classifier 判。

Eligible mode family、boundary mode、mixed-mode、diagnostic 與 constrained
semantic helper 的詳細規則，以 `docs/SCOPE_CONTRACT.md` 為 authoritative
subordinate contract。該文件不新增 Domain Owner、pipeline stage 或 workflow
lane，Scope Classifier 仍為 `IN_SCOPE` / `OUT_OF_SCOPE` 的唯一 owner。

## K. Event Dedup

Evidence、Scope、Date 完成後才進 Event Dedup。

Evidence Service 的：

```text
Source-to-Candidate Match
```

與 Event Identity 的：

```text
Candidate-to-Candidate Event Equivalence
```

必須分離。

同事件多來源形成單一 Event，可保存：

* event_id
* candidate_ids
* canonical / primary source
* authoritative evidence
* supporting sources
* source-specific claim provenance

跨來源 conflicting claims 不得自動融合。

若無法可靠裁決：

> 不寫該衝突 factual claim。

Event Identity 只在 Evidence、Scope、Date 完成後負責 Candidate-to-Candidate Event Equivalence；不得由 Evidence Service 或 Selector 取代。

## L. Category

Classifier 是唯一 Category owner，且只對已完成 Evidence、Scope、Temporal
及 Event Identity / Dedup 的 authoritative Event Group 作出一次 Category
決定。Category 表示來源證實的 event/action factual type。

```text
CATEGORY_AUTHORITATIVE_OWNER = Classifier
CATEGORY_AUTHORITATIVE_OWNER_COUNT = 1
CATEGORY_DECISION_UNIT = one authoritative Event Group after Event Identity / Dedup
```

正式 primary Category set：

| Canonical ID | 顯示名稱 |
| --- | --- |
| `TECHNICAL_DEVELOPMENT` | 技術新知 |
| `INCIDENT` | 事故事件 |
| `OPERATIONAL_CHANGE` | 營運動態 |
| `PROCUREMENT` | 採購事件 |
| `NORMATIVE_CHANGE` | 規範變動 |

Category 輸出及基數：

```text
CATEGORY_CARDINALITY = exactly one primary Category when assigned
PEER_SECONDARY_CATEGORY = NO
OPTIONAL_DESCRIPTIVE_SUBTYPE = YES
```

Classifier 唯一負責 `primary_category`、`subtype` 及 `classification_reason`。
Subtype 只描述已分類事件的性質，不形成新的 workflow lane 或第二個 Category。

輸出狀態為：

```text
NOT_EVALUATED
CATEGORY_ASSIGNED
CATEGORY_UNRESOLVED
```

`NOT_EVALUATED` 表示 Category stage 未執行，例如上游 prerequisite 未滿足。
`CATEGORY_ASSIGNED` 表示 Classifier 有足夠 authoritative Evidence 支持唯一
primary Category。`CATEGORY_UNRESOLVED` 表示 Classifier 已執行，但 evidence
不足、定義類別的 action 不明、來源間該 action 有重大衝突，或 Event Group
包含兩個同等獨立的類別定義 action 而無可辯護的 principal action。

`CATEGORY_UNRESOLVED` 是 Category stage 的合法終止結果。Classifier 擁有
該決定；orchestrator 只依該狀態終止此 Event Group，不成為另一個 Category
owner。該 Event Group 不進 Reportability、MaiAgent 或 Delivery。Selector 不得
補 Category，亦不得把此狀態改成 `NOT_REPORTABLE`。

Category 只分類已證明的 principal current action / lifecycle action。不得用
Category precedence、數值排名、關鍵字數量、新聞價值、importance score、來源
優先級或「core value」解決衝突。同一 Event Group 中若確有多個同等獨立的
category-defining actions，且無唯一 principal action，必須回
`CATEGORY_UNRESOLVED`；Category 不得 merge 或 split events。

### Category meanings and boundaries

* **`TECHNICAL_DEVELOPMENT` / 技術新知**：principal action 是具體研究成果、
  原型、試驗、應用技術測試、技術部署或實質技術發展。系統名稱、採購、供應商
  決標或設備交付本身不等於技術發展。
* **`INCIDENT` / 事故事件**：已實際發生的都市軌道事故、非預期故障或安全／
  資安事件。事故嚴重程度不是 Category threshold。死亡、受傷、服務中斷、火災、
  碰撞、損害及營運後果是來源支持的事實；是否值得報導由 Reportability 判定。
* **`OPERATIONAL_CHANGE` / 營運動態**：實際客運／營收服務啟用、服務或班表
  變更、票價或營運方式改變、已證實的營運爭議，以及營運性治理 action。一般
  客訴或負面報導本身不構成爭議。正式發布的法規或規範變動歸
  `NORMATIVE_CHANGE`，不得為了沿用舊分類而塞入本類。
* **`PROCUREMENT` / 採購事件**：來源證明 principal action 是正式 tender、
  bid invitation、supplier selection、award、exercised option 或其他正式採購
  action。採購標的是否為七大 E&M 系統由獨立 Taxonomy 表示。技術新穎性、AI、
  CBTC、資安或 first-of-kind 不會把採購事件改成技術發展。
* **`NORMATIVE_CHANGE` / 規範變動**：來源證明法規發布／修訂、強制技術規則、
  產業或技術標準修訂、有明確適用對象與規範內容的正式指引、營運者通用規格
  修訂，或正式草案／徵詢程序。需保留文件的拘束力及程序狀態。單一採購案規格、
  引用既有標準、研究者建議、傳聞中的未來規則、普通建議，或沒有明確規範變動
  的內容均不屬此類。

```text
SEVERITY_IS_CATEGORY_AUTHORITY = NO
INNOVATION_CAN_OVERRIDE_PROCUREMENT = NO
```

事故後發布的新強制規則屬 `NORMATIVE_CHANGE`，不是原事故。只發布有實質調查
發現的事故調查報告，而未制定新規範時，按其調查／安全治理 action 分類為
`OPERATIONAL_CHANGE`；報告中的建議不等於已採納規則。對票價、班表或服務安排
的實際決定屬 `OPERATIONAL_CHANGE`，即使透過政策公告發布。

### Procurement and technical lifecycle

Category 由 Event Group 已證明的 principal action 決定，不由「主要價值」或
新穎性覆寫。Formal procurement action 一律為 `PROCUREMENT`，即使採購內容新穎、
first-of-kind、有試點目的或描述新技術。技術新穎性可以保留為 Evidence fact、
technical descriptor、Taxonomy input 或 Reportability consideration，但不是
Category override。

先發生的 tender／award 與其後開始的 pilot／deployment，依 Event Identity
已確立的 lifecycle action 分別分類。Category 不自行拆 Event Group。列車開始
載客屬 `OPERATIONAL_CHANGE`；CBTC pilot 開始屬 `TECHNICAL_DEVELOPMENT`；若同一
正確 Event Group 中有兩個同等獨立 action 且無唯一 principal action，回
`CATEGORY_UNRESOLVED`。

### Authority boundaries

Category 可使用 Event Group 內保留來源歸屬的 authoritative claims、principal
source substantive content、由該內容支持的 event identity/action facts，以及
source metadata 作 provenance。Owned headline 只能作上下文，不能取代 substantive
Evidence。來源間若 category-defining factual claims 衝突且無法裁決，回
`CATEGORY_UNRESOLVED`；不得合併來源正文或編造調和敘事。

Category 不得以 search query、search snippet、Google News proxy title、RSS-only
tag、publisher/domain alone、URL tokens、discovery keyword、candidate
`published_at`、fetch time、report wording、MaiAgent output 或 downstream
Reportability 作 authority。不得有 site-specific、publisher-specific、language-
specific 或 report-period-specific Category branch。

Category 不得決定 Scope、Evidence、Date、Event Identity、E&M Taxonomy 或
Reportability；不得 merge、split、drop、score importance、套用 quota 或 rescue。
E&M Taxonomy 說明涉及哪些都市軌道機電系統／技術；系統名稱本身不決定 Category，
Taxonomy 不得更改 Category。Selector 只決定 `REPORTABLE` / `NOT_REPORTABLE`
與 deterministic ordering，不得分類或重新分類。MaiAgent 不得決定或修改 Category。

同一 factual Event Group 在 7、30、90、180 或 365 天報告期間必須有相同 Category。
Source iteration order、publisher priority、canonical-source position 及報告期間
均不得決定 Category。

```text
SEARCH_KEYWORDS_CATEGORY_AUTHORITY = NO
REPORT_PERIOD_SPECIFIC_CATEGORY_RULE = NO
CATEGORY_IS_REPORTABILITY_OWNER = NO
CATEGORY_CAN_DROP_EVENT = NO
CATEGORY_CAN_SCORE_IMPORTANCE = NO
CATEGORY_CAN_USE_REPORT_QUOTA = NO
CATEGORY_CAN_MERGE_EVENTS = NO
CATEGORY_CAN_SPLIT_EVENTS = NO
CATEGORY_CAN_ASSIGN_EM_SYSTEM = NO
TAXONOMY_CAN_CHANGE_CATEGORY = NO
CATEGORY_UNRESOLVED_IS_VALID_TERMINAL_STATE = YES
CATEGORY_UNRESOLVED_REACHES_REPORTABILITY = NO
CATEGORY_UNRESOLVED_REACHES_MAIAGENT = NO
CATEGORY_UNRESOLVED_REACHES_DELIVERY = NO
```

Classifier 是 Category 唯一 source of truth。不得新增 fallback、rescue、backfill、
default forced category、第二套 conflict resolver 或 downstream reclassification。

## M. E&M Taxonomy

固定七大主系統：

* 電聯車
* 號誌
* 供電
* 通訊
* 自動收費
* 機廠維修設備
* 月臺門

子系統不得自行升格。

七大系統不得作 Candidate survival gate。

E&M Taxonomy 描述系統，不決定 Category。跨系統或新興系統的分類仍依 Section L
所定義的 principal event/action；Taxonomy 結果不得覆寫該 Category。

電梯、電扶梯、通風空調等非七大主系統設備，如事件本身具有足夠都市軌道技術、安全、營運或示範價值仍可成報。

但不得硬映射至七大主系統。

E&M Taxonomy 只負責相關主系統與 taxonomy 結果，不負責 Candidate survival、Category、Scope 或 Reportability。

## N. Reportability / Ordering

Selection 正式責任只有：

```text
REPORTABLE / NOT_REPORTABLE
+
DETERMINISTIC ORDERING
```

Input 必須已完成：

```text
EVIDENCE_READY
IN_SCOPE
DATE_VALID
DEDUPED
CATEGORY_ASSIGNED
```

Selector 不得：

* Fetch
* 補 Evidence
* 修改 Scope
* 修改 Date
* 修改 Category
* 合併 Event

Reportability 必須建立在事件本身實質：

* 技術
* 系統
* 安全
* 營運
* 政策
* 爭議
* 採購
* 示範

價值上。

「對臺北捷運有參考價值」不得單獨救回普通事件。

Ordering 採 deterministic lexicographic priority：

1. 新技術、新材料、新方式
2. 都市軌道機電技術關聯度
3. 系統、安全或專案影響程度
4. 臺北捷運實質參考價值
5. 採購案重大性
6. 來源品質
7. 時效性
8. stable identity

不得改用不透明加權總分。

Category diversity 不作 Selection factor。

Selector 不得設定最低篇數、最高篇數、Category quota、A/B/C level、backfill 或 rescue。

## O. No Quota

正式報告沒有：

* minimum
* maximum
* category quota
* A/B/C
* backfill
* rescue

有多少 `REPORTABLE` 就寫多少。

0 篇合法。

任何篇數要求不得反向修改 Evidence、Scope、Date、Event Identity、Category、Taxonomy 或 Reportability 的 authoritative decision。

## P. MaiAgent

MaiAgent 只有：

> 正式技術週報撰稿

一個 production responsibility。

MaiAgent 不得：

* Search
* Select
* Fetch
* Dedup
* 補 Evidence
* 修改 Scope
* 修改 Category
* 修改 Reportability
* 猜 metadata
* 查外部背景

Input：

* Reportable Event metadata
* Authoritative Evidence
* canonical source metadata

Search snippet 不作 factual evidence。

Writing rule：

> Evidence 能證明多少，就寫多少。

DORTS implication 可以提出專業分析與建議，但不得捏造臺北捷運現況、設備狀態、法規或其他未提供事實。

MaiAgent platform role 為 external configuration。

Repository 應保存：

```text
docs/maiagent_role_reference.md
```

作 reference，但該檔不參與 runtime。

Debug 可保存：

```text
declared_maiagent_role_version
declared_maiagent_role_hash
```

不得假裝 Git 已驗證 platform 實際設定。

注意：`docs/maiagent_role_reference.md` **不是本輪必須建立的檔案**。等正式角色指令來源準備好後再建立，不要放假的 placeholder。

## Q. Validation

Validator 與 Writer 必須分離。

Validator 只檢查：

* factual grounding
* source integrity
* required fields
* DORTS implication boundary

每 Event 最多一次 semantic correction。

單 Event FAIL：

> 只淘汰該 Event。

已 PASS Event 不得因其他 Event 失敗而重新生成。

Transport retry 與 semantic correction 分開計算。

Validator 不得代替 Writer，也不得修改 upstream domain decision。Semantic correction 只限於該 Event，且最多一次。

## R. Report / Delivery

```text
Final report count = Validation PASS count
```

0 篇仍建立正式 artifact：

> 本期無符合正式報導條件之事件。

Report Service 唯一負責：

* PASS events assembly
* category section ordering
* artifact naming
* report metadata

Delivery Service 不得做 domain decision。

GitHub Actions 為 production automation。

Streamlit 可 manual email。

兩者共用一個 Email / Delivery owner。

Delivery 必須具 stable delivery identity，至少可追溯：

* report identity
* artifact identity / version
* recipient target

Retry 不得造成同一 artifact 重複成功寄送。

Report Service 不得改寫 Validation 結果；Delivery Service 不得選題、分類、修正 Evidence 或執行其他 domain decision。

## S. Debug

Debug 只能觀察。

每 execution 只有一個 authoritative：

```text
RunTrace
```

RunTrace 包含：

```text
report_id
run_id
```

同一 RunTrace 產生：

```text
developer_debug_<report_type>_<date>.json
engineering_summary_<report_type>_<date>.json
```

Full Debug：

* incident investigation
* candidate forensic trace
* evidence diagnostics
* provider diagnostics
* validation diagnostics

Engineering Summary：

* 快速工程判讀

Engineering Summary 應至少包含：

```text
run
config
search_coverage
candidate_counts
dedup
event_counts
top_rejection_reasons
provider_failures
validation_failures
final_events
artifacts
declared_maiagent_role_version
```

Candidate counts 與 Event counts 必須分開。

Candidate lifecycle：

```text
DISCOVERED
→ EVIDENCE_READY
→ IN_SCOPE
→ DATE_VALID
→ GROUPED
```

Event lifecycle：

```text
CREATED
→ CATEGORY_ASSIGNED
→ REPORTABLE
→ GENERATED
→ VALIDATED
→ DELIVERED
```

若 Category owner 回傳 `CATEGORY_UNRESOLVED`，該 Event Group 在 Category stage
終止，不進入後續 Event lifecycle stages。`CATEGORY_ASSIGNED` 是 Selector 的
分類前置條件。

Debug state 永遠不得控制：

* eligibility
* reportability
* retry eligibility
* rescue
* backfill

兩份 JSON 必須由同一 RunTrace 產生，不得各自重新計算 Domain Decision。

## T. UI

Streamlit 只負責：

* Config input
* Progress
* Result display
* Download
* Manual Email
* Developer summary

核心 pipeline 必須可完全脫離 Streamlit 執行。

UI 不得擁有 Domain Decision。

## U. Golden / Tests

V2 不整套搬 V1 tests。

測試優先順序：

1. Golden contract tests
2. Owner unit tests
3. Pipeline E2E
4. Delivery tests

Golden Corpus 至少涵蓋 case classes：

* valid new technology
* valid new material
* valid new method
* urban-rail incident, including technical failure and severity consequences
* low-value incident that is assigned `INCIDENT` and independently rejected by Reportability
* operations policy
* operations dispute
* formal procurement action, including innovative procurement that remains `PROCUREMENT`
* technical pilot/deployment as a distinct lifecycle action
* enacted regulation and mandatory technical rule
* industry/technical standard revision and formal guidance
* normative change versus ordinary recommendation and procurement-only specification
* `CATEGORY_UNRESOLVED` terminal disposition
* mixed independent category-defining actions with no principal action
* cybersecurity procurement, incident, and regulation as distinct event types
* duplicate multilingual event
* different events with similar titles
* title-only evidence
* wrong landing page
* search/navigation shell
* non-urban rail
* out-of-range
* conflicting source claims
* non-seven-system but reportable equipment

Golden Case 應定義：

```text
evidence_state
scope
date_valid
event_identity_expectation
category
e&m_taxonomy
reportability
expected_reject_reason
```

不得只為 tests passing 修改 Golden expected outcome。

Historical incident 可以成為 Golden Case，但不得變成 production special case。

## V. V1 Reuse

V1：

```text
FROZEN_REFERENCE
```

可 selective reuse：

* provider transport
* MaiAgent API transport
* URL / date pure functions
* PDF rendering primitives
* SMTP / MIME primitives
* formatting assets
* GitHub Actions orchestration primitives
* Golden regression cases

不得整體搬：

* V1 selector
* V1 evidence lifecycle
* rescue / backfill
* A/B/C survival tiers
* multi-stage dedup
* whole-report all-or-nothing validation
* historical report repair / reconciliation architecture

V2 不以輸出與 V1 相同為目標。

本輪只建立治理文件；V1 維持未修改的 FROZEN_REFERENCE。

## W. Architecture Complexity Guard

若 implementation 需要：

* 第二套 owner
* fallback
* rescue
* backfill
* duplicated Category logic
* duplicated Evidence logic
* downstream 修改 upstream decision
* test-specific production rule

必須停止 implementation，先確認是否真為合法 Domain Requirement。

不得直接繼續補洞。

若需求與本 Contract 矛盾，必須先指出矛盾並重新確認 Domain Requirement、authoritative owner 與 minimum correct boundary，不能以局部 workaround 取代 architecture decision。

## X. Definition of Done

必須同時符合：

1. requirement / root cause 明確
2. authoritative owner 明確
3. contract 明確
4. 無 duplicated owner
5. tests passing
6. Golden 無 regression
7. pipeline trace 可解釋
8. 無不必要 fallback / rescue / workaround
9. 正確 behavior 未被偷偷改變
10. architecture complexity 未不合理增加

Tests passing alone 不代表完成。

## Y. Governance Lock

Architecture baseline：

```text
ARCHITECTURE_VERSION = v0.5
ARCHITECTURE_STATUS = FINAL_LOCKED
ENTRY_POINT_CLARIFICATION = APPLIED
```

除非：

* 新的合法 domain requirement
* 已證實 architecture contradiction
* authoritative owner 設計本身錯誤
* contract 造成正確需求無法實作

不得因：

* 單一 bug
* 單一事件
* 單一網站
* 單一 regression
* 報告篇數不足
* 一次 production failure

修改 Architecture Contract。
