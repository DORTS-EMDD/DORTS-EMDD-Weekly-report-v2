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
修復 taxonomy，也不得處理 `TAXONOMY_UNRESOLVED`。任何未來 semantic helper 提案都
必須先經新的 architecture decision，且只能 proposal-only，由 Python owner 驗證；本
contract 未授權建立該 helper。

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

### V1 selective reuse boundary

V1 的低階 exact matching／negation helper、report-label projection pattern，以及
depot-location、generic-network、authoritative-empty、Writer non-override 等 test intent，
只有在符合本 contract 且不成為 decision authority 時才可選擇性重用。

不得移植 V1 九系統 registry、Candidate title/snippet keyword classifier、Selector
taxonomy fallback、taxonomy-based survival/procurement gate、postprocessor taxonomy
inference／repair、Writer prose normalization，或任何垂直運輸／通風空調 top-level
system。不得以 V1 compatibility path 建立第二個 V2 owner。

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
