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

### Shared production workflow

正式 application composition 的唯一 owner 為 `ReportApplication`，其唯一正式
invocation seam 為 `ReportApplication.run(...)`。Main、Streamlit 與 Automation
都必須呼叫同一個 application seam，不得各自重組 Search、Evidence、Scope、
Temporal、Event Identity、Category、Reportability 或 Delivery lifecycle。

`ReportApplication` 只負責 application orchestration，不重新推導任何 Domain
decision。其正式 path 為：

```text
RegionRegistry
→ SearchPlanner
→ SearchExecutor
→ CandidateNormalizer
→ Search execution gate
→ EvidenceService
→ ScopeClassifier
→ TemporalRule
→ Event Identity
→ Classifier
→ ReportWorkflow.run
→ later Ordering / Writer / Validation / Delivery
```

既有 shared downstream workflow 的具體實作邊界仍為
`src/weekly_report/report_workflow.py` 的 `ReportWorkflow` service，其公開
method 為 `ReportWorkflow.run`。它只負責 post-EventGroup / Category-result
downstream orchestration，不擁有 Search、Search execution、Evidence、Scope、
Temporal、Event Identity 或 Category authority。其既有 API 與 lower-level seam
必須保留。`build_report_workflow` 仍只是該 downstream service 的 dependency
factory；未來 `build_report_application` 才是完整 application composition root。
兩者都只負責 construction/injection，不得在 construction 時執行 lifecycle、
呼叫網路或作 Domain decision。

### Phase 2B-A mechanical execution contract

```text
FORMAL_APPLICATION_ORCHESTRATION_OWNER = ReportApplication
FORMAL_APPLICATION_INVOCATION_SEAM = ReportApplication.run
SEARCH_EXECUTION_COMPONENT = SearchExecutor
SEARCH_EXECUTION_DOMAIN_AUTHORITY = NO
SEARCH_EXECUTION_RESULT_AUTHORITY = MECHANICAL_ONLY
```

`SearchExecutor` 只接收 complete frozen `SearchPlan`、immutable provider
dispatch mapping 與 fixed transport/pacing configuration，依 frozen plan 順序
逐 item exact dispatch，每 item 最多一次，產生 `SearchAttemptResult` 與 immutable
attempt observations。它不得改寫 plan、選擇 query/market/language/provider、retry、
fallback、rescue、backfill、normalize Candidate，或決定 Evidence、Category、
Reportability。

Search 的唯一 executable provider vocabulary 為：

```text
google_news_rss
```

```text
PHASE_2B_REFERENCE_PROVIDER = Google News RSS
PROVIDER_TARGET_CANONICAL_ID = google_news_rss
DEFAULT_PROVIDER_TARGET = FORBIDDEN
MAX_PROVIDER_INVOCATIONS_PER_PLAN_ITEM = 1
HIDDEN_TRANSPORT_RETRY = FORBIDDEN
REDIRECT_FOLLOW_COUNT = 0
PAGINATION = ONE_PROVIDER_REQUEST_PAGE_ONLY
EXECUTION_CONCURRENCY = SEQUENTIAL
```

`default` 不得作為 executable provider target，也不得由 runtime hidden mapping
轉換為 `google_news_rss`。Provider dispatch semantic authority 維持 NO。

`SearchExecutionResult` 是 immutable mechanical aggregate，至少保存 plan identity、
ordered terminal attempt results、unattempted frozen items、safe infrastructure
failure provenance/state 與 immutable attempt observations。它不得包含 Evidence、
Category、Reportability 或 formal report outcome。每個 frozen plan item 必須恰有
一個 terminal result 或列在 unattempted items，並恰有一個對應的 attempt-stage
observation；foreign/duplicate/overlap 都必須 fail closed，兩者都依 frozen plan
order。每個 observation 的 market、intent、language/profile、query family 與
canonical provider 必須和 frozen plan item 完全一致；attempted observation 必須
和 terminal result 的 status/failure class 一致，成功結果的 raw count 必須符合
parsed result count，unattempted observation 必須是 zero raw results。`execution_complete` 與
`has_technical_failures` 必須由 validated records 推導；前者表示所有 items 已
terminal attempted 且沒有 infrastructure failure，後者表示任一 terminal result
為 `TECHNICAL_FAILURE`。因此完整 execution 仍可能含 technical failure。

Execution aggregate 內的 observation 固定是 attempt-stage snapshot，
`normalized_result_count` 必須為 `None`。Normalization 完成後的非負數量必須由
ReportApplication 建立新的 immutable projection，不得回頭 mutation execution
aggregate；`None` 表示未執行，0 表示已完成且輸出為零。

Item `TECHNICAL_FAILURE` 與 executor infrastructure failure 必須分開。Item failure
仍須繼續 remaining frozen items；infrastructure failure 或 incomplete execution
時，application execution gate 必須 fail closed。Gate 只消費 validated
`SearchExecutionResult`，不得消費 Debug observation；任何 technical failure、
infrastructure failure 或 incomplete execution 都禁止 formal artifact、PDF 與
Email。完整且無失敗的 `SUCCESS_ZERO_RESULTS` execution 是合法的 completed search，
可產生零 Candidate，不得 fallback、rescue、backfill 或 fabricate Candidate。

每個 provider item 只允許一個 request；不得 hidden transport retry。Redirect
follow count 固定為 0；redirect response 視為 safe technical failure。每 item
只取一頁 provider response；adaptive pagination 禁止；rate limit 是
`TECHNICAL_FAILURE`；execution concurrency 固定為 sequential。Malformed provider
row（缺 title、URL、required field、invalid type）使整個 item 成為
`TECHNICAL_FAILURE / INVALID_RESPONSE`，不得 salvage subset；合法空 response
才是 `SUCCESS_ZERO_RESULTS`。

`SearchObservation.normalized_result_count` 的 `None` 表示 normalization 尚未
執行，非負整數（包括 0）表示 normalization 已完成。Observation 由
SearchExecutor 產生；normalization observation projection 屬於
ReportApplication composition。Provider 不得直接寫 RunTrace，Debug 不具 decision
authority。

同一模組的 `build_report_workflow` 是 downstream dependency-composition boundary。它只負責
接收／建立 workflow dependencies，並把 proposal-only semantic dependencies 注入
各自的 authoritative owner；它不得決定 E&M semantics、推導 systems、擁有
Category／Taxonomy semantics，或加入 provider-specific business rules。Taxonomy
provider backend 維持 `DEFERRED`，MaiAgent 在 Taxonomy decision 中維持 `NONE`。

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

目前 selected mode 包含上述 19 個市場。`global` 是獨立的 configured target
mode，不等於 selected 19，也不等於 unrestricted worldwide exploratory
discovery。Global target set 可以包含 selected 19 以外的額外市場，但每個
target 必須是 V2 governed/supported、符合 `INTERNATIONAL_EXCLUDING_TAIWAN`
project geography 且不是 Taiwan。`GLOBAL_MODE_TAIWAN_BEHAVIOR =
EXCLUDE_DISCOVERY`；Taiwan 不得進入 global discovery target set。SearchPlanner
只消費 RegionRegistry 的 configured target set，不自行新增 Taiwan 或其他
未配置 target。RegionRegistry 不判定已 discovered Candidate 的 factual Scope，
也不得以 ScopeClassifier 修補 selected 或 global configuration。

Region Registry 為 `selected` 與 `global` 兩種 region mode 的 configured
discovery target configuration 唯一 source of truth，並負責 typed immutable
market/profile values，包括 language/profile references、locale hints 與
local discovery terminology references。它不得判定 Scope、Category、E&M
Taxonomy 或 Reportability。

## F. Search / Discovery

Search 只做 discovery。

Search 的唯一規劃 owner 是一個 `SearchPlanner`。SearchPlanner 負責
deterministic discovery planning、language/profile selection、bounded query
composition，以及消費 query-family configuration。不得按 intent 建立多個
互相獨立的 Search owner。

Taiwan 不得產生 selected 或 global Search plan items：

```text
TAIWAN_SELECTED_SEARCH_PLAN_ITEMS = FORBIDDEN
TAIWAN_GLOBAL_SEARCH_PLAN_ITEMS = FORBIDDEN
```

四個 discovery intent 使用一個 canonical typed machine representation：

```text
technology
major_incident
operations
procurement
```

其中 `major_incident` 是 canonical machine ID，`major incident` 是同一
semantic intent 的 human-readable display label。四組 ID/label 如下：

```text
technology     -> technology
major_incident -> major incident
operations     -> operations
procurement    -> procurement
```

不得以 whitespace replacement、case conversion 或各層自行 normalization
取代 canonical mapping。Search intent 不等於 Category；`procurement` intent
不得推導 `Category = PROCUREMENT`。

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

每個 enabled discovery plan item 都必須有 plan record、attempt record 與
terminal status。`ATTEMPTED` 不等於 `FOUND_CANDIDATE`，zero-result attempt
仍是一次合法 attempt。

SearchPlan 的 decision unit 是一個 immutable、可獨立 attempt 的 concrete
discovery request。每個 item 至少能識別 stable `plan_item_id`、market target
或 configured global target、canonical intent、language/profile、query
family、provider target，以及 concrete provider-compatible request/query。
完整 plan 必須在執行前產生並凍結；相同 configuration/version/input 必須產生
相同 plan contents、ordering 與 stable IDs。

Query family 是 SearchPlanner 管理的 bounded discovery composition template，
可引用 urban-rail anchor、intent/action、market/operator 與 optional
technical vocabulary。不得產生無界 Cartesian product；query count、ranking、
Top N 與 optimal weighting 延後至 coverage optimization。

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

Provider 只接收已規劃 request，執行 technical discovery call，回傳
normalized technical result/status。Provider-specific 行為僅限 transport、
request encoding、locale support 與 result-field extraction。Provider 不得
判定 EvidenceReady、Scope、Category、Taxonomy 或 Reportability，不得修改
frozen Search plan，不得以 alternate provider fallback 或 recovery backfill
取代失敗的 item。

每個 attempt 的 terminal status 只有以下三類：

```text
SUCCESS_WITH_RESULTS
SUCCESS_ZERO_RESULTS
TECHNICAL_FAILURE
```

`SUCCESS_ZERO_RESULTS` 是合法成功終態，不是 provider failure，也不自動表示
coverage failure。`TECHNICAL_FAILURE` 必須保存 attempt provenance 與 technical
failure class，不得製造 synthetic candidate。

一個 item 發生 `TECHNICAL_FAILURE` 時，執行必須繼續 already-frozen plan 的
remaining items；不得 retry failed item、建立 replacement query、switch
provider 作為 rescue、建立 backfill call 或 adaptive expansion。若執行在所有
required items attempt 前停止，run 必須標示 incomplete Search execution，不能
宣稱未執行的 item 已達 `PLANNED + ATTEMPTED`。

Search output boundary 固定為：

```text
provider result
→ acquisition input
→ Candidate Normalizer
→ CanonicalCandidate
→ Evidence
```

Candidate Normalizer 是獨立且既有的 owner，負責 candidate normalization 與
stable acquisition identity；SearchPlanner 或 provider 不得直接接管
CanonicalCandidate semantics。Search result title 與 snippet 只屬 discovery
metadata，不是 Evidence、Category、Taxonomy 或 Reportability evidence。

Candidate Normalizer 只能機械處理 exactly identical provider result records
或 exact URL duplicates，並保留 acquisition origins。不同 URL 不得依 similar
titles、overlapping snippets、publisher preference、inferred equivalent URLs
或 event interpretation 做 semantic merge；Event Identity / Dedup 仍是正式
event grouping owner。

Search observation records 至少包含 plan/item ID、market、canonical intent、
language/profile、query family、provider、planned/attempted status、terminal
status、raw result count、technical failure class 與 normalized result count。
它們加入既有 `RunTrace` 的 observation-only governance；provider、market、
language、intent、query-family contribution、exact-result overlap 與
EvidenceReady handoff count 只能是 projections，且 handoff count 必須消費
Evidence owner 的結果。Debug/Search telemetry 不得參與同一 run 的 query
expansion、provider substitution、candidate survival、Category、Taxonomy 或
Reportability decision。Adaptive query logic = DEFERRED。

Search runtime 的 implementation boundary 分階段固定如下：

* Phase 2A：typed Search contracts、canonical DiscoveryIntent、Region Registry
  runtime data seam、deterministic SearchPlanner、provider protocol declaration
  與 observation types；offline only。
* Phase 2B：concrete provider adapters、mechanical execution、failure/zero-result
  records、Candidate Normalizer runtime integration 與 shared workflow integration。
* Phase 2C：controlled/offline acceptance、reproducibility 與 measurable coverage
  baseline。
* Phase 3：measured coverage optimization、curated vocabulary、international
  synonyms、profile/query-family 與 provider/market tuning。

Search runtime 不得改寫既有 Evidence、Scope、Temporal、Event Dedup、Category、
E&M Taxonomy、Reportability、Writer、Validation 或 Delivery contracts。

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

### Category v4 Final Seal acceptance

Category live acceptance 使用固定 population：85 個 Golden fixtures，其中 52 個
fixtures 進入 Category，經 Event Identity 後形成 53 個 Event Groups。每一個
Event Group 在每一 round 只取得一個 live proposal。

Final Seal batch 必須在執行前固定如下：

```text
FINAL_SEAL_ROUNDS = 3
GROUPS_PER_ROUND = 53
TOTAL_PLANNED_LIVE_CALLS = 159
```

每一 round 必須個別同時符合：

```text
LIVE_CALL_COUNT = 53
HTTP_200_COUNT = 53
CLASSIFIER_ACCEPTED_COUNT = 53
CLASSIFIER_INVALID_COUNT = 0
CATEGORY_STATE_MISMATCH_COUNT = 0
PRIMARY_CATEGORY_MISMATCH_COUNT = 0
RESOLUTION_REASON_MISMATCH_COUNT = 0
EXACT_CATEGORY_MATCH_COUNT = 53
```

三個 round 必須全部通過。不得平均、majority vote、挑選最佳 round、替換失敗
call、重試單一 Event Group、移除失敗 case，或忽略 unresolved reason mismatch。
任一失敗表示該 frozen configuration 不可封存，且不得為了取得 PASS 追加 round。

執行前必須以 canonical deterministic serialization 建立 repository-controlled
configuration fingerprint。Fingerprint 至少涵蓋唯一 Category guidance、完整權威
response schema、機械投影的 provider schema、provider message construction version、
schema/provider/helper versions、53 個準備完成的 request payloads、53-group Golden
oracle mapping，以及 evaluation harness version。不得只使用 Git HEAD，也不得納入
timestamp、random value、cache、output 或無關 debug artifact。

同一 batch 的三個 round 必須使用相同 acceptance version 與 configuration
fingerprint。每一 round 必須明確指定 index 並獨立保存完整結果；harness 不得隱藏
迴圈執行多輪。

Final Seal deployment provenance 使用唯一版本化的
`category-deployment-snapshot-v1` content-addressed snapshot。Snapshot 必須來自
MaiAgent management UI / platform read-back；Repository 宣告值不能冒充 deployment
evidence。Snapshot 必須保存：

* 實際 provider identity、stable chatbot instance ID 與 exact model label；chatbot
  instance ID 是 deployment instance identity，不是 configuration revision。
* exact deployed role instruction content。Role content 是行為相關 deployment
  artifact，必須可稽核；可另外計算 hash，但 hash 不取代內容。
* exact deployed Structured Output JSON Schema content。Repository 的
  `_CATEGORY_RESPONSE_SCHEMA`、provider projection 或 schema version 不能代替
  平台 read-back。
* 可觀測的 answer mode、knowledge-base state、selected skills/tools、generation
  settings 與會影響 context、memory、history、system/tool context 或 conversation
  state 的 settings。只保存平台實際顯示的欄位和值，不推測 hidden defaults。
* explicit、排序穩定的 unavailable platform facts list。未暴露的 configuration
  revision、schema ID/version 或完整 generation parameter set 必須誠實列出，不能用
  `unknown`、`N/A`、`UNAVAILABLE`、chatbot ID 或 Repository version 代替。

若平台額外暴露 configuration revision、schema identity 或 schema version，可以作為
optional platform metadata；未暴露並不構成必須捏造的欄位。`RAG QA`、knowledge-base
attachment、skills/tools 與 context/memory toggles 的 read-back 只證明可觀測設定已被
凍結，不證明未揭露的 MaiAgent server-side state 不存在。`conversation=null` 也不單獨
證明所有 vector/global memory 已停用。

Snapshot 必須以 canonical deterministic serialization 建立唯一 deployment fingerprint：
JSON object key order 不影響 hash，selected skills/tools 與 unavailable fact identifiers
依 contract 排序；role free text 不 trim 或改寫，schema JSON 不重寫。capture timestamp、
screenshot filename、local path、operator note 等 audit metadata 不得進 fingerprint。
合法 snapshot 的 provenance status 是 `OBSERVED_AND_FROZEN`。Fingerprint 是
observation/freeze evidence，沒有 Category decision authority；它不宣稱 MaiAgent
未揭露的 server-side state 已被驗證。

Repository 無法驗證 hidden platform state 時，應記錄
`DEPLOYMENT_PROVENANCE_UNAVAILABLE` 或該 snapshot 的 explicit unavailable facts；不得
用 Repository schema/version 或假造 platform revision 通過 preflight。三個 round 之間不得
修改 deployment。三個 round 必須使用相同 acceptance version、repository configuration
fingerprint 與 deployment fingerprint；deployment snapshot malformed 時必須在 transport
前停止，不得自動修復、fallback 或 placeholder substitution。

Final Seal batch 失敗後必須停止並保留全部 evidence。只有通過 review 的通用變更
可以建立新的 acceptance version 與新的預先固定 batch；歷史失敗不得刪除或由後續
成功 round 取代。

## M. E&M Taxonomy

### Authority, decision unit, and input

Python E&M Taxonomy 是 E&M Taxonomy decision 的唯一 authoritative owner。
Decision unit 是完成 Evidence、Scope、Temporal 與 Event Identity／Dedup 後的一個
`EventGroup`，不是 Candidate，也不是已通過 Reportability 的 report item。

實作時應建立最小 immutable request，直接引用既有 authoritative typed values：

* 一個 `EventGroup`；
* 該 group member 對應的 `EventIdentityRecord` values，其中保留各自的
  `EvidenceResult.substantive_content` 與 source provenance，不合併來源正文；
* 同一 `event_id` 的 `CategoryResult`，只供 stage eligibility 驗證。

Request 不得複製、重寫或合成新的 authoritative evidence source。所有 record 必須對應
`EventGroup.member_candidate_ids`，並已具有 `EVIDENCE_READY`、`IN_SCOPE` 與
`DATE_VALID` upstream outcome。

只有 `CATEGORY_ASSIGNED` Event Group 進入 taxonomy evaluation。
`CATEGORY_UNRESOLVED` 或 upstream `NOT_EVALUATED` 對應 taxonomy
`NOT_EVALUATED`。Category primary ID、display label、subtype、classification reason
及 resolution reason 不得作 system evidence，不得決定、修復、覆寫或製造 systems。
Taxonomy 也不得修改 Category。

### Canonical registry

固定 registry 如下；machine ID 是 authoritative value，中文名稱只作 display metadata：

| Machine ID | Display label |
| --- | --- |
| `ROLLING_STOCK` | 電聯車 |
| `SIGNALLING` | 號誌 |
| `POWER_SUPPLY` | 供電 |
| `COMMUNICATIONS` | 通訊 |
| `AUTOMATIC_FARE_COLLECTION` | 自動收費 |
| `DEPOT_MAINTENANCE_EQUIPMENT` | 機廠維修設備 |
| `PLATFORM_SCREEN_DOORS` | 月臺門 |

Implementation 必須由 `src/weekly_report/contracts.py` 中的一個 `EMSystemId`
registry 及其 display-label mapping 作唯一 runtime source of truth。Classifier、
Selector、Writer、report formatter、tests 與 Golden validation 只能引用或驗證該
registry，不得各自保存另一份 runtime system list 或 mapping。

子系統、技術主題與設施不得自行升格。V1 的「垂直運輸設備」與「通風空調系統」
不是 V2 top-level system。電梯、電扶梯、通風空調等非七大系統事件仍可成報，但
不得硬映射至七大系統。

### Result and state model

Implementation 應建立 immutable `TaxonomyResult`，至少包含：

```text
event_id
taxonomy_state
systems
taxonomy_resolution_reason
support_spans
conflict_spans
provenance
```

合法 states 只有：

1. `TAXONOMY_EVALUATED`
   * taxonomy stage 已成功執行；
   * `systems` 是零個或多個 canonical `EMSystemId`；
   * `taxonomy_resolution_reason` 必須為 null。
2. `TAXONOMY_UNRESOLVED`
   * stage 已執行，但 authoritative evidence 不能形成可靠 system conclusion；
   * `systems` 必須為空；
   * reason 必須為 `INSUFFICIENT_SYSTEM_EVIDENCE` 或
     `CONFLICTING_SYSTEM_EVIDENCE`。
3. `NOT_EVALUATED`
   * taxonomy stage 未到達；
   * 不得攜帶 systems、resolution reason 或 taxonomy decision provenance。

`TAXONOMY_EVALUATED` 且 `systems = []` 表示已評估並確認沒有合理的七大系統映射。
它與 `TAXONOMY_UNRESOLVED` 及 `NOT_EVALUATED` 是三種不同語意。不得新增
`TAXONOMY_NOT_APPLICABLE` 來重複空的 evaluated result，也不得以空結果掩蓋
insufficient 或 conflicting evidence。

### Multi-label and determinism

Taxonomy 是 top-level system set，不設 primary、secondary、ranking 或權重。一個
Event Group 可以同時屬於多個 systems。每個 system 最多出現一次；serialized
`systems` 必須依 canonical registry table 順序排列，不得依 source、Candidate、
support span 或 helper output 順序。Candidate iteration order 與來源優先順序不得改變
semantic result。

跨系統整合事件應保存所有具有效 support 的 top-level systems。例如號誌與供電整合
事件輸出順序固定為 `SIGNALLING, POWER_SUPPLY`，不得選一個 primary system，也不得
以「系統整合」建立第八個 system。

### Support and provenance

每一個 assigned `EMSystemId` 必須至少具有一個 system-specific support span，內容至少
包含 `system_id`、`candidate_id`、`start` 與 `end`。Owner 必須驗證：

* candidate 屬於該 Event Group；
* span 位於該 candidate 的 authoritative `substantive_content` bounds 內；
* span text 與原始 authoritative content 完全一致；
* support 確實說明受影響、部署、採購、測試、規範或其他 event action 所涉及的 system
  function／object，而非只有孤立名詞。

Title、search snippet、query、URL token、publisher、Category、Reportability、Writer
output、synthetic quote、fuzzy reconstruction 或跨來源合成文字都不是 support。

`CONFLICTING_SYSTEM_EVIDENCE` 必須保存足以識別衝突來源的 source-preserving conflict
spans。`INSUFFICIENT_SYSTEM_EVIDENCE` 必須記錄已檢視的 Event Group member IDs 與
insufficiency diagnostic，但不得合成 support。Debug／RunTrace 可以觀察 provenance，
不得重新計算 taxonomy。

### Semantic proposal seam

Python E&M Taxonomy remains the sole authoritative owner. It may receive one
injected, narrow `Taxonomy Semantic Proposal Provider` dependency whose role is
`PROPOSAL_ONLY`:

```text
Python E&M Taxonomy owner
→ injected proposal provider
→ untrusted semantic proposal
→ Python validation + exact quote localization
→ TaxonomyResult or technical stage failure
```

The provider request is immutable and contains only the stable `event_id` and
the EventGroup members, deterministically ordered by `candidate_id`. Each
member contains its `candidate_id` and authoritative
`substantive_content`. Category controls reachability before this seam, but
Category label, subtype, and other Category values are not provider input.
Search/discovery metadata, title-only evidence, feed snippets, Reportability,
Writer text, Golden expected values, and synthetic or reconstructed evidence
are also excluded.

The provider may propose only `TAXONOMY_EVALUATED` or
`TAXONOMY_UNRESOLVED`. It must not propose `NOT_EVALUATED`, which is owned by
Python upstream reachability. An evaluated proposal contains zero or more
legal canonical system IDs, a null resolution reason, and one or more
system-specific support citations for every assigned system. An unresolved
proposal contains empty systems, one legal unresolved reason, and the required
reason-specific provenance. Systems are a set; provider order has no semantic
priority and Python serializes accepted systems in canonical registry order.

Each support or conflict citation contains a canonical `system_id`, a member
`candidate_id`, and an exact quote copied from that member's authoritative
`substantive_content`. The support location model is
`EXACT_TEXT_UNIQUE_RESOLUTION`: Python resolves a quote to `[start, end)` only
when it occurs exactly once in the named candidate content. Missing, repeated,
fuzzy, approximate, rewritten, paraphrased, synthetic, title/snippet, or
cross-source quotes are technical failures. Python must not choose among
repeated occurrences, guess offsets, search another candidate, or borrow an
EventGroup's evidence.

Before constructing `TaxonomyResult`, Python validates reachability and matching
`event_id`, exact EventGroup membership, sealed upstream member invariants,
legal states and IDs, duplicate systems, state/reason cardinality, unresolved
provenance, per-system support, candidate membership, exact quote occurrence,
span bounds and exact source slicing. Conflict provenance must contain at least
two distinct competing canonical hypotheses and only EventGroup members.
Insufficient provenance must identify all examined EventGroup member IDs and
contain a non-empty diagnostic. Python may parse typed enums, localize one
unique exact quote, build immutable structures, and canonicalize serialization
order. It must not add, remove, replace, guess, drop, synthesize, repair, or
convert semantic outcomes.

The provider performs the semantic interpretation of the bounded authoritative
evidence, but Python alone accepts or rejects the complete proposal and builds
the final `TaxonomyResult`. No second semantic judge is required. `TAXONOMY_EVALUATED`
with `systems = []` remains an explicit provider conclusion that no reasonable
seven-system mapping applies; Python must not infer it from a failed proposal.
`TAXONOMY_UNRESOLVED` with `INSUFFICIENT_SYSTEM_EVIDENCE` or
`CONFLICTING_SYSTEM_EVIDENCE` remains a legitimate domain result only when the
provider's authoritative-evidence interpretation supports that state.

Provider unavailability, provider exceptions, malformed responses, invalid
states or IDs, duplicate systems, missing or non-member support, invalid or
ambiguous quotes, invalid provenance, and every other proposal contract
violation are typed technical stage failures. They produce no `TaxonomyResult`
and do not authorize downstream Reportability, Writer, or Delivery processing
for that failed EventGroup. No `TAXONOMY_ERROR` state is added. Taxonomy-specific
retry, malformed-response retry, fallback, rescue, and backfill are prohibited;
no generic retry policy is currently reused by this seam.

The proposal provider is not a second classifier owner, Category authority,
Reportability authority, Writer role, MaiAgent role, runtime Golden lookup, or
keyword authority. Keywords and search terms such as SCADA, train, depot,
network, and cybersecurity may occur in evidence but do not determine
taxonomy by themselves.

### Contextual and subsystem rules

Contextual term 本身不自動建立 mapping。只有 authoritative event evidence 同時證明
event action 與 system function／object 的關係時，才可映射到 parent system：

* interlocking、ATP、ATO、ATS、CBTC 或列車控制可映射 `SIGNALLING`；
* traction power、traction substation、third rail 或 overhead power supply 可映射
  `POWER_SUPPLY`；
* radio、telecom、fiber/data transmission 或 passenger information system 可映射
  `COMMUNICATIONS`；
* fare gate、ticketing、validator 或 fare collection equipment 可映射
  `AUTOMATIC_FARE_COLLECTION`；
* platform screen/platform door system 可映射 `PLATFORM_SCREEN_DOORS`；
* wheel lathe、train washer、lifting／inspection／workshop maintenance equipment 等
  具體機廠維修功能可映射 `DEPOT_MAINTENANCE_EQUIPMENT`；
* propulsion、braking、bogie、wheelset、coupler、vehicle control 或其他明確車載車輛
  equipment 可映射 `ROLLING_STOCK`；車載 signalling 或 radio 仍依其 function 映射
  `SIGNALLING` 或 `COMMUNICATIONS`，並可在證據支持時形成 multi-label result。

以下限制固定：

* SCADA 不自動等於 `POWER_SUPPLY` 或 `COMMUNICATIONS`；必須由 evidence 證明其
  controlled／monitored system function。
* OCC／operations control center 不是 top-level system；只按 evidence 明確支持的
  signalling、communications、power 或其他七大 system functions 分類。
* cybersecurity 不是第八個 system；只有受保護、受攻擊、部署或稽核的 technical
  object 已被 evidence 證明屬於七大系統時才映射，否則是 evaluated empty result。
* depot location 本身不等於 `DEPOT_MAINTENANCE_EQUIPMENT`。
* generic train mention 本身不等於 `ROLLING_STOCK`。
* generic network mention 本身不等於 `COMMUNICATIONS`。
* platform／station／system／equipment 等泛稱本身不建立任何 mapping。

Subsystem 只能映射至 evidence-supported parent，不得成為新 top-level ID。若 evidence
合法支持多個 parents，保留全部 canonical IDs；若不足以判定 parent，回
`TAXONOMY_UNRESOLVED`，不得猜測或以 keyword default。

### Maintenance software and platforms

維修軟體／平台依 authoritative evidence 所證明的 monitored、diagnosed、inspected、
maintained 或 predicted technical object 及其 canonical parent 分類。Evidence 必須
同時支持軟體與該 object 的維修關係及 object 的 system 歸屬；不得從使用者、部署
地點、Category 或孤立零件名稱推定 parent。此 maintained-object precedence 不因
軟體具有維修用途而改歸 `DEPOT_MAINTENANCE_EQUIPMENT`。

只有 evidence 證明軟體本身構成、參與、控制、操作或協調具體 depot／workshop
maintenance equipment 的技術功能時，才支持 `DEPOT_MAINTENANCE_EQUIPMENT`；
僅管理 maintenance workflow 不足。若另有被維修 object 的 canonical parent 也具
system-specific support，依既有 multi-label 規則保留，不以 precedence 排除有效
support。維修、predictive maintenance、AI、analytics、depot、排程、work order 或
asset management 等名稱，以及機廠人員使用、機廠部署、分析維修資料、預測故障、
排程或工單管理本身，均不建立 system mapping，也不新增軟體／AI top-level system。

無法建立上述 mapping 時沿用既有 state semantics：確認沒有合理七系統映射才回
evaluated empty；無法可靠確定 parent 時回 `TAXONOMY_UNRESOLVED` /
`INSUFFICIENT_SYSTEM_EVIDENCE`，保留 member IDs 與 diagnostic；衝突仍依既有
conflicting-evidence 規則處理，不以 empty、keyword default 或補值取代。

### Downstream boundaries

E&M Taxonomy 只負責相關 top-level systems 與 taxonomy state，不負責 Candidate
survival、Category、Scope、Date、Event Identity、Reportability 或 Ordering。七大系統
不得作 Candidate survival gate。

Reportability 可以唯讀 consume finalized `TaxonomyResult` 作 system-relevance context，
但不得增刪 systems、填補 empty result、resolve unresolved taxonomy，或由
Reportability outcome 反推 taxonomy。`systems = []` 不自動表示 `NOT_REPORTABLE`；
non-empty systems 也不自動表示 `REPORTABLE`。Golden G17 的 empty／REPORTABLE 與
G85 的 AFC／NOT_REPORTABLE semantics 必須保留。

MaiAgent 在 Taxonomy decision 中沒有角色。Writer 只能由 finalized systems 的 machine
IDs 透過 authoritative registry 顯示 labels；不得新增、移除、替換、normalize、推測或
修復 taxonomy，也不得處理 `TAXONOMY_UNRESOLVED`。Taxonomy semantic proposal
provider 只能依本節的 proposal-only seam 提供未信任提案，由 Python owner 驗證；
不得建立第二個 semantic judge 或任何 MaiAgent Taxonomy role。

### Workflow integration and typed handoff

Production workflow 必須依序完成 Category，再完成 E&M Taxonomy，之後才可進入
Reportability／Ordering、MaiAgent Writer、Validation、Report Assembly 與 Delivery。
對每一個到達 Category→Taxonomy seam 的 EventGroup，workflow 一律呼叫：

```text
Taxonomy.evaluate(event_group, member_records, category_result)
```

workflow 不得複製 Category→Taxonomy reachability branch；`Taxonomy.evaluate` 是
該規則的唯一 owner。`CATEGORY_ASSIGNED` 進入一般 Taxonomy evaluation；
`CATEGORY_UNRESOLVED` 與 Category `NOT_EVALUATED` 由 owner 產生同 event_id 的
Taxonomy `NOT_EVALUATED`，provider 不得被呼叫，且該 EventGroup 在 Reportability
之前終止。

Workflow 使用一個最小 immutable typed handoff `EventDecisionRecord`，定義於
`src/weekly_report/contracts.py`，欄位只引用既有 typed values：

```text
event_group: EventGroup
member_records: tuple[EventIdentityRecord, ...]
category_result: CategoryResult
taxonomy_result: TaxonomyResult
```

它不得複製 systems、taxonomy state、provenance、Category identifiers、member IDs
或 evidence content。所有 values 必須為正確 typed values，event_id 必須一致，member
records 必須無重複且恰好對應 EventGroup membership；不得重新計算或修復 semantic
decision。`ReportWorkflow` 只在 `Taxonomy.evaluate` 成功返回 `TaxonomyResult`
後建構此 handoff。

只有 `TAXONOMY_EVALUATED` 的 handoff 可交給 Reportability。這包含 `systems = []`；
empty systems 不自動表示 `NOT_REPORTABLE`，non-empty systems 也不自動表示
`REPORTABLE`。`TAXONOMY_UNRESOLVED` 是保留 reason／provenance 的合法 terminal
domain outcome，不轉成 `NOT_REPORTABLE`，不進 Reportability、Writer 或 Delivery，
也不 retry、fallback、rescue、backfill 或 downstream repair。`NOT_EVALUATED` 是
合法 typed stage disposition，同樣不轉成 `NOT_REPORTABLE`，不進 Reportability、
Writer 或 Delivery，並可由 Debug 觀察。

`TaxonomyStageFailure` 是 technical execution failure，不是任何 domain outcome。
它不產生 `TaxonomyResult` 或 `EventDecisionRecord`。該 EventGroup 不得進入
Reportability 或 Writer。任一 EventGroup 發生此 failure 時，正式 run 採
`ABORT_FORMAL_REPORT_RUN`：不允許部分正式報告發布，不組裝成功 formal artifact，
不交付 PDF，也不寄送 Email。先前結果只能保留供 diagnostics；technical failure
不得轉為「零篇成功」。這是 population-level logical stage barrier，不要求 database
transaction：整批 Category／Taxonomy 完成且沒有 blocking technical failure 後，才可
進入 Reportability／Ordering 與後續 Writer progression。

Reportability 只 consumer-only read `EventDecisionRecord` 的 finalized
`TaxonomyResult`，其 domain contract 另行鎖定為 `SEPARATE_FUTURE_LOCK`；它不得
rerun、infer、alter 或 repair Taxonomy。Writer 為 `RENDER_ONLY`，只接收已通過
Category、`TAXONOMY_EVALUATED` 與 Reportability 的 event，system labels 必須來自
`EM_SYSTEM_DISPLAY_LABELS`。Writer 不得接收 unresolved、not-evaluated 或 technical
failure，也不得推導、修復、增刪 systems。Debug／Engineering Summary 僅
`OBSERVATION_ONLY`，可記錄 state、systems、provenance、failure event_id 與安全
diagnostic，但不得影響 production decision；Validation 不得成為第二個 E&M semantic
judge。

上述 workflow integration 不增加 domain owner、Taxonomy source of truth 或
reachability branch；workflow、Reportability、Writer、Validator 與 Debug 均不得
重新推導 systems。Retry、fallback、rescue 與 backfill 均為 `NO`。

### Golden contract requirements

未來 Taxonomy Golden／owner tests 至少必須涵蓋：

* 七個 canonical IDs 與唯一 display-label mapping；
* contract-relevant multi-label events、canonical ordering、authoritative set construction
  的 duplicate elimination、result-boundary duplicate rejection 與 source-order
  invariance，不要求所有數學組合；
* evaluated empty result、`NOT_EVALUATED`、insufficient unresolved 與 conflicting
  unresolved；
* subsystem-to-parent mapping 及 SCADA、OCC、cybersecurity contextual boundaries；
* depot location vs depot equipment、generic network vs communications、generic train
  vs rolling-stock evidence；
* Category independence、Reportability independence 與 Writer non-override；
* support candidate membership、bounds、exact text mapping、per-system coverage 及
  multi-source conflict provenance。

Golden expected outcome 不得為了配合 implementation 修改。既有中文 taxonomy values
是上述 registry 的 display labels；typed implementation 與 Golden validation 必須由唯一
registry 驗證其一對一 mapping，不得建立第二份 label list。

### Golden semantic projection and runtime acceptance

Golden Taxonomy 是 implementation-independent semantic projection。它權威鎖定
taxonomy stage 是否到達、taxonomy state、canonical systems、unresolved reason 與
reason-specific unresolved provenance；它不必為每一個 legacy positive fixture 固定唯一
的 positive support slice。不同 exact authoritative spans 可以支持同一 semantic outcome，
而且 fixture-level projection 可能涵蓋多個結果相同的 EventGroup。

這項 projection 不等同於 production 的 per-EventGroup `TaxonomyResult`。Python E&M
Taxonomy 仍是唯一 runtime decision owner；每一個正向 runtime `TaxonomyResult` 仍必須
具備每個 assigned system 的完整、system-specific、authoritative support，並通過
candidate membership、substantive-content bounds、exact text mapping 與 semantic
support 驗證。Golden 不得從 expected labels 合成 runtime support。

正式 E&M owner acceptance 必須同時通過：

1. runtime semantic result 與 Golden projection parity；以及
2. runtime `TaxonomyResult` 的完整 provenance 與 state invariants。

Golden semantic parity 單獨不足以通過 production acceptance。Category Classifier tests
不屬於 E&M Taxonomy runtime provenance validation。`TAXONOMY_UNRESOLVED` 的
member IDs、diagnostic 或 conflict spans 是 unresolved semantic result 的一部分，因而
在 Golden 中必須存在並依 reason 驗證；指定的 provenance fixtures 可以另外鎖定固定
positive support 或 conflict 邊界，但不得把該要求推廣成所有 legacy positive fixtures
都必須保存同一組 support spans。

若一個 fixture 涵蓋多個 EventGroup，fixture-level semantic expectation 只有在每個
resulting group 的 outcome 相同且 applicability 明確時才能共用。不得比較 systems
聯集、依 group ordinal 指派、或讓一個 group 的 support 支持另一個 group。若未來
不同 groups 需要不同 outcome，必須以 member identity 明確表達，而且只能保留一個
authoritative expected representation。

### V1 selective reuse boundary

V1 的低階 exact matching／negation helper、report-label projection pattern，以及
depot-location、generic-network、authoritative-empty、Writer non-override 等 test intent，
只有在符合本 contract 且不成為 decision authority 時才可選擇性重用。

不得移植 V1 九系統 registry、Candidate title/snippet keyword classifier、Selector
taxonomy fallback、taxonomy-based survival/procurement gate、postprocessor taxonomy
inference／repair、Writer prose normalization，或任何垂直運輸／通風空調 top-level
system。不得以 V1 compatibility path 建立第二個 V2 owner。

## N. Reportability / Ordering

### Authoritative owner and domain result

`src/weekly_report/reportability.py::Reportability` is the sole
authoritative Reportability owner. Its authoritative input is the immutable
`EventDecisionRecord` produced after Evidence, Scope, Date, Event Identity,
Category and E&M Taxonomy have completed. Reportability does not rerun,
infer, alter or repair any upstream decision.

The Reportability domain has exactly two states:

```text
REPORTABLE
NOT_REPORTABLE
```

There is no `REPORTABILITY_UNRESOLVED` state. `REPORTABLE` means that the
authoritative EventGroup evidence positively supports at least one accepted
substantive urban-rail reporting-value path. `NOT_REPORTABLE` means that
Reportability successfully evaluated the complete EventGroup, but the
supplied authoritative evidence does not positively support such value. Its
only domain reason is `LOW_REPORTABILITY_VALUE`. This is a semantic result,
not a technical failure or a claim that the event has no value in every
context.

Only `TAXONOMY_EVALUATED` EventDecisionRecords reach Reportability,
including `systems = []`. `TAXONOMY_UNRESOLVED` and `NOT_EVALUATED` remain
upstream terminal dispositions and do not receive a ReportabilityResult.
Empty taxonomy systems do not automatically reject an event, and non-empty
systems do not automatically approve one. Reportability may read finalized
Taxonomy context but may not add, remove, normalize, resolve or substitute
systems. Category and Taxonomy remain independent upstream owners.

Reportability value is established from the event's authoritative evidence,
not from discovery labels or a system proxy. Accepted value paths include
substantive technical research, testing, pilots or deployments; concrete
system renewal, integration or engineering intervention; consequential
safety, failure, service-impact or corrective investigation; concrete
service, fare, operating-practice, safety-governance or policy change;
substantive operational controversy; substantive normative action or formal
guidance; and procurement, demonstration or trial activity with concrete
engineering, system, test, update or operational significance. No path
requires novelty, a non-empty E&M taxonomy, a severity threshold or a
monetary threshold. Ordinary administrative, corporate, promotional,
workflow-only or unsupported events remain negative when the evidence does
not establish one of these paths. A Taipei reference alone cannot rescue a
low-value event.

Source quality and evidence readiness remain owned by EvidenceService.
Reportability uses only the complete authoritative substantive content of
the EventGroup members. It does not use title-only evidence, snippets,
discovery intent, search queries, keywords, unaccepted metadata, Golden
expected values or Writer text as decision authority.

### Semantic proposal seam

The current typed upstream fields do not encode all free-text concepts in the
Reportability value rules. Reportability therefore has one injected
`ReportabilitySemanticProposalProvider` dependency. This dependency executes
semantic interpretation under this contract and returns one untrusted,
proposal-only value. It is not an additional owner and cannot create a
`ReportabilityResult`, directly admit or drop an EventGroup, invoke Ordering
or Writer, or modify an upstream result. There is exactly one authoritative
Reportability owner, one injected proposal seam and zero additional
authoritative semantic owners. The concrete provider backend is deferred.

The execution boundary is:

```text
Reportability owner
→ bounded immutable request
→ one injected proposal provider
→ untrusted semantic proposal
→ Python structural validation + exact evidence resolution
→ ReportabilityResult or ReportabilityStageFailure
```

The provider request is the complete EventGroup population, deterministically
ordered by `candidate_id`:

```text
ReportabilitySemanticMember:
    candidate_id: str
    substantive_content: str

ReportabilitySemanticRequest:
    event_id: str
    members: tuple[ReportabilitySemanticMember, ...]
```

Each member must be a unique, exact EventGroup member and must contain the
complete unchanged `EvidenceResult.substantive_content`. The request must not
contain CategoryResult, TaxonomyResult, separate source metadata, temporal
facts, discovery metadata, an independent title, search snippets, search or
query keywords, ordering or ranking scores, Golden expected values or Writer
text. CategoryResult and TaxonomyResult remain Python-owner inputs for
reachability and upstream validation only. The provider must not fetch
external information.

The provider proposal is deliberately smaller than the production result:

```text
ReportabilitySemanticCitation:
    candidate_id: str
    exact_quote: str

ReportabilitySemanticProposal:
    event_id: str
    proposed_state: REPORTABLE | NOT_REPORTABLE
    examined_candidate_ids: tuple[str, ...]
    support_citations: tuple[ReportabilitySemanticCitation, ...]
    rationale: str
```

These are the complete proposal fields. The provider does not return a
ReportabilityResult, proposed reason, confidence score, ranking score or
other decision field. Python derives `reason = null` for `REPORTABLE` and
`reason = LOW_REPORTABILITY_VALUE` for `NOT_REPORTABLE`; this fixed mapping
does not repair or reinterpret the proposed state.

Both proposal states must match the current event identity and examine every
member exactly once. The rationale must be non-empty and grounded in the
supplied evidence. A `REPORTABLE` proposal requires at least one exact
positive citation that supports an accepted value path and must account for
relevant counterevidence. Non-essential factual conflicts do not invalidate
an independent positive value. A `NOT_REPORTABLE` proposal has no support
citation and explains why the complete supplied evidence does not positively
support an accepted path. It must not fabricate a negative citation proving
absence and must never stand in for provider inability or technical failure.

`REPORTABILITY_EVIDENCE_RESOLUTION` is
`EXACT_TEXT_UNIQUE_RESOLUTION`. Every provider quote must be non-empty,
unchanged, belong to a named EventGroup member, and occur exactly once in
that member's authoritative substantive content. Python resolves it to a
canonical `[start, end)` span and verifies candidate membership, bounds and
exact source slicing. Zero occurrences and repeated occurrences are invalid
proposals. Fuzzy matching, whitespace or quote repair, normalization,
offset guessing, arbitrary repeated-occurrence selection, cross-source
borrowing, synthetic merged evidence and title/snippet support are forbidden.

Python validates the current identity and prerequisites, complete request
membership, proposal fields and types, legal state, complete examined-member
IDs, rationale, positive/negative citation cardinality, candidate membership,
unique exact occurrences, bounds, source slicing, and the resulting
state/reason/provenance invariants before constructing the authoritative
result. It may canonicalize serialization order, but it must not salvage a
subset, change the proposed state, manufacture citations or turn an invalid
proposal into `NOT_REPORTABLE`.

Structural validation is not an independent semantic proof. Exact quote
existence and complete examined-member IDs do not prove that the provider's
semantic conclusion is correct. An accepted result explicitly relies on the
provider's interpretation after it passes the Python acceptance contract.
A structurally valid but semantically incorrect proposal is a defect at the
semantic execution boundary and must not be repaired downstream. No second
keyword judge, hidden model judge, confidence gate, score threshold,
provider-specific admission rule or runtime Golden lookup is allowed.

Provider unavailability, exceptions, timeouts, malformed responses, invalid
fields or state, missing or duplicate examined members, invalid candidate
IDs, missing positive support, absent or ambiguous quotes, invalid source
support and every other proposal violation produce one
`ReportabilityStageFailure`. The failure is owner-controlled, stable and
safe; raw payloads, exception strings, secrets and unsafe exception chains
must not escape. A failure produces no ReportabilityResult and is not
converted to `REPORTABLE`, `NOT_REPORTABLE`, `NOT_EVALUATED` or zero-event
success.

There is one proposal attempt per eligible EventGroup. Retry, alternate
provider, fallback, rescue, backfill, keyword backup, default state and
Writer rescue are prohibited. Any `ReportabilityStageFailure` triggers
`ABORT_FORMAL_REPORT_RUN`: all eligible Reportability decisions must finish
before Ordering or Writer begins, and no partial formal artifact, PDF or
Email may be produced. Earlier results may remain diagnostic evidence only.

MaiAgent has no Reportability role. A future backend, if selected, is merely
an infrastructure dependency behind this proposal protocol and must be
validated separately for semantic conformance and structural acceptance.

### Procurement and Golden governance boundary

Procurement reportability is based on substantive engineering, system, test,
update or operational significance supported by authoritative evidence.
USD 3M equivalent is not an eligibility threshold. Unknown amount, low
amount or unavailable reliable FX conversion does not automatically reject;
high amount does not automatically approve.

The current Golden corpus requires a separate explicit governance phase after
this contract checkpoint. The adjudicated findings are:

```text
G19 = CONFIRMED_STALE
G62 = CONFIRMED_STALE
G87 = CONFIRMED_STALE
G90 = CONFIRMED_STALE
G85 = CURRENT_CORRECT
```

G19, G62 and G87 do not reach Reportability because Taxonomy is unresolved;
their future expected Reportability projection must be `NOT_EVALUATED`.
G90's administrative office move does not establish substantive reporting
value. G85 remains `NOT_REPORTABLE`; no USD 3M rejection reason is invented
because that reason is not present in the fixture. Golden files are not
changed by this contract checkpoint and are never exposed to the provider.

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
TAXONOMY_EVALUATED
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
