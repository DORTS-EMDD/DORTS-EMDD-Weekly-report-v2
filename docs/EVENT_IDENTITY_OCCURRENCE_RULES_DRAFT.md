# Event Identity Occurrence Rules — D1–D4 草案

```text
STATUS = DRAFT (Domain Rule draft, 2026-11-02)
BINDING = NO — 待使用者確認；確認前不得作為實作依據
PRODUCTION_CHANGE = NONE（Event Identity 判定邏輯、提示詞、schema、Golden 檔案皆未修改）
SUPERSEDES_ON_CONFIRMATION = §A.34 的 D1–D4 待決事項；將成為 Architecture Contract §A.35
```

## 0. 目的與範圍

§A.34 的結論是：目前每個 Live 合併都取決於 helper 的單次回答。
- 同一請求三次提案，召回率為 66%／85%／95%。
- 確認結果會隨請求中其他紀錄的組成而改變。
- Golden 只能驗證 Python 如何處理腳本化的回答。

本草案的目標：
- 「不同 occurrence」盡量由 Python 依每筆紀錄的事實，以確定性規則判定。這些事實已記錄、可重放。
- helper 只回答 Python 無法判定的問題：同一小組內，哪些紀錄報導同一主體的同一行為。

不在範圍：Category、Reportability、Temporal 期間有效性、Formal metadata、Writer、Validator。

## 1. 名詞

- **Record**：通過 Evidence、Scope、Temporal，進入 Event Identity 的候選（`EventIdentityRecord`）。
- **候選事件**：Scope candidate-event focus 句所描述的新聞（RC-20、RC-45：文件自身報導的新聞）。Event Identity 只比較候選事件，不得改用文件中的其他事件。
- **Occurrence**：一個具體的發生事項。可以是主體所遭遇的事（例如事故），也可以是行為者所做的事（例如決定、發言）；發生於一個時間或一段連續期間。
- **Occurrence signature**：每筆 record 的候選事件的 type、status、occurrence interval（§3、§4）。
- **Region**：EvidenceService 依 RC-4 確立的地區（RC-22），不變。

## 2. Owner 與資料流（修正 §A.34 的提議）

§A.34 曾提議由 EvidenceService，以既有的 `evidence_metadata_extraction` 任務取得 signature。草擬時查證後發現：
- metadata 擷取在 EvidenceService 內執行（`evidence_service.py` `_extract_metadata`），早於 Scope。
- 因此它無法知道 Scope 選定的候選事件。
- 但 signature 必須描述的正是這個候選事件。RC-45 已證明：焦點選錯，合併就錯。

因此改為：

- **Owner：EventIdentity**（Candidate-to-Candidate Event Equivalence 的唯一 owner）。
- **提案（helper）：**
  - 每筆 record 以既有 task `event_identity_semantic_proposal` 的第三種請求取得 signature 提案。前兩種是批次提案與確認；新請求有獨立的 schema 與 prompt version。
  - 請求內容是該 record 在 Event Identity 請求中送出的同一段焦點摘錄（§A.14、§A.30）。
  - 一筆紀錄一個請求，不與其他紀錄同送，結果只取決於該紀錄本身。
- **驗證與正規化（Python）**：見 §3.5、§4.3。
- **結果：`OccurrenceSignature`**
  - 只屬 EventIdentity，只供 Event Identity 判定與觀測。
  - 不寫入 `EventIdentityFacts`，不供其他 owner 使用。
- **不變的部分：**
  - EvidenceService、`EventIdentityFacts`、§K 的 formal-only 條文、exact-fact path。
  - AGENTS §11 的八個 helper task。
- **與 Temporal 的分工：**
  - occurrence interval 不影響日期有效性，TemporalRule 仍是期間有效性的唯一 owner。
  - Temporal 的判斷也不作為 Event Identity 的依據。

## 3. D2 — Occurrence type 與粒度

### 3.1 封閉清單（10 類 + OTHER）

**DAY_BOUND**：日期綁定、同類會反覆發生的事件。

| Type | 包含 | 不包含（歸屬） |
|---|---|---|
| `INCIDENT_OR_DISRUPTION` | 事故、碰撞、出軌、火災、冒煙、設備故障、人員傷亡、攻擊或犯罪、天災損害；計畫或非計畫的停駛、停站、封閉、減班；罷工或示威造成的服務影響 | 調查或稽核結果公布（FINDINGS_RELEASE）；事後採取的措施或決定（DECISION_OR_PLAN）；演練（ACTIVITY_OR_STATEMENT） |
| `ACTIVITY_OR_STATEMENT` | 由人舉辦或進行、本身即為新聞的活動或發言：演練、演習、典禮、視察或現場訪視、體驗或驗證乘車、展覽、會議、記者會、聽證、質詢、聲明、呼籲、批評、提議、訪談 | 發言內容所報導的、由他人完成的事項（依 §3.2(b) 取該事項的 type） |

**STEP**：專案或資產的階段行為，常經宣布而被報導。

| Type | 包含 | 不包含（歸屬） |
|---|---|---|
| `DECISION_OR_PLAN` | 決定、核准、通過、採用、撥款、計畫、政策、法規或標準發布；票價、時刻、營運規則變更；排程的設定、延後或取消 | — |
| `TENDER` | 招標、徵求建議書、資格預審公告、開標 | 決標（CONTRACT_AWARD） |
| `CONTRACT_AWARD` | 決標、選定得標者或優先協商對象、簽約、下單 | — |
| `DELIVERY` | 車輛或設備的製造里程碑、出廠、交付、運抵、移交 | — |
| `WORKS` | 施工、安裝、更新工程的開始或進度（動工、隧道貫通、鋪軌進度） | 完工（COMPLETION_OR_SERVICE_START） |
| `TEST_OR_TRIAL` | 不載客的測試、試運轉、試行、驗證試驗 | 載客試營運（COMPLETION_OR_SERVICE_START） |
| `COMPLETION_OR_SERVICE_START` | 完工、建置或安裝完成；路線、車站、出入口、服務或系統開始供使用；載客試營運 | — |
| `FINDINGS_RELEASE` | 調查報告、稽核、檢查或評鑑結果、研究、統計、排名或獎項結果的公布 | 事件報導中的初步原因（INCIDENT_OR_DISRUPTION） |

**`OTHER`**：不屬上列的 occurrence，或焦點未陳述任何 occurrence。

**粒度的決定與依據**

| 決定 | 依據 |
|---|---|
| 「建置完成」與「開始服務」為同一 type | ED26：議員宣布三家電信完成建置，與營運機構宣布開始服務，是同一事件 |
| 「載客試營運」屬 COMPLETION_OR_SERVICE_START，「不載客測試」屬 TEST_OR_TRIAL；兩者分開 | ED04、ED16／ED17 |
| 「決標」與「簽約」合為一類，不同步驟由 helper 依主體與步驟分開 | 兩者在報導中常混用 |
| 「事故」與「停駛」合為一類 | 同一事故常只被報導為停駛 |
| 活動與發言合為一類 | 兩者以日期與行為者區分，邊界（視察時發言）在報導中不穩定 |

### 3.2 決定 record 的 type（依序適用）

- **(a) 新聞 vs 前提**
  - 只計焦點以「已發生」、「正在發生」或「已排定將發生」報導的 occurrence。
  - 作為背景、目的、原因、過去經過或既成狀態提到的，是前提，不計。
  - 例：ED19 RIDE 的 "to check the upgraded Wi-Fi"，開通是前提。
- **(b) 宣布者規則（§A.33）**
  - 焦點透過某人的發言或宣布報導一個 occurrence 時，取該 occurrence 的 type。
  - 只有發言本身就是新聞時（呼籲、要求、批評、提問、提議、表示將檢討、會議），才是 ACTIVITY_OR_STATEMENT。
  - 由既不執行、也不決定該事項的人要求某事發生，屬發言。
- **(c) 已發生優先於預告**
  - 焦點同時報導已發生的一步與之後的預告時，取已發生的一步。
  - 例：「9 月交車，11 月起測試」中，11 月測試只是前瞻附記。
- **(d) 最新一步**：焦點報導同一主體的多個已發生步驟時，取最新的一步。
- **(e) 決定**
  - 焦點報導某機關作出決定、核准、通過、設定、延後或取消時，type 為 DECISION_OR_PLAN，不論決定的內容是什麼。
- **(f) 預告**
  - 焦點只報導某 occurrence 已排定或將發生時，type 為該 occurrence 的 type，status 為 PLANNED。
  - 例：ED16「11 月上旬開始測試」是 PLANNED TEST_OR_TRIAL。
- **(g) 兩個新聞**
  - 焦點以新聞報導兩個不同 type 的 occurrence，而依 (a)–(e) 兩者都不是前提或附記時，記錄兩個 type。
  - 例：同一段同時寫「三家電信服務首度全面開通」與「部會舉辦品質體驗活動」。
  - 最多兩個；三個以上時，type 視為未確立（§3.4）。

**Status**：`OCCURRED`（已開始，含進行中與已完成）或 `PLANNED`。

### 3.3 Type 相容

- 相同 type 相容。
- `DECISION_OR_PLAN` 與任何 status 為 PLANNED 的 type 相容。同一計畫常被報導為「決定」，也常被報導為「將發生的事項」。
- 其餘不同 type 不相容。
- 兩筆 record 的 type 集合中，只要有任一配對相容，即為相容。

### 3.4 未確立

下列情況中，type 不作 DISTINCT 依據：
- signature 請求技術失敗（RC-6）；
- 提案違反契約；
- type 為 OTHER；
- 三個以上新聞 type。

原則與地區相同：缺少事實不構成 DISTINCT。這類 record 與同地區所有可比較的 record 一起交給 helper，即今日的行為。

技術失敗揭露為 EventIdentity TechnicalGap；record 不排除。

### 3.5 Python 驗證

- type 必須在清單內；status 必須是 `OCCURRED` 或 `PLANNED`；最多兩項。
- 每項至少引用一個焦點句 ID，且必須是該 record 送出的句子。
- 違反時，整個 type 欄位未確立（欄位層級驗證，RC-3）。
- Python 不判斷 type 在語意上是否正確；語意品質以真實回答語料量測（§8）。

## 4. D3 — Occurrence date，以及不同日期但同一 occurrence

### 4.1 什麼是 occurrence date

Interval 是 occurrence 本身發生、或排定發生的時間：

- **一次性的行為或事情**：發生日。
- **跨日的 occurrence**：
  - Evidence 陳述的起訖期間；只陳述起日者，取起日。
  - 「24 日仍封閉」這類陳述某日仍在持續的狀態，不是 occurrence date；起日未陳述時為 NOT_STATED。
- **PLANNED**：排定的日期或期間。
- **DECISION_OR_PLAN**：作出決定的日期。決定內容的生效日或實施日不是。
- **ACTIVITY_OR_STATEMENT**：活動舉行或發言的日期。
- **其他 type**：
  - 發言者「表示」或「宣布」的日期不是 occurrence date。
  - 例：「21 日表示已開始服務」，21 日是發言日，開始服務的日期為 NOT_STATED。
- **永不採用**：刊登、更新、byline、dateline、報導時間（RC-38、ED09）。

### 4.2 Precision

| Precision | Interval |
|---|---|
| `DAY` | [d, d] |
| `SPAN` | [起日, 訖日] |
| `PART_OF_MONTH` | 上旬（初、早期）1–10；中旬 11–20；下旬 21–月底 |
| `MONTH` | 整月 |
| `NOT_STATED` | 無（只有年份，或「近日」、「今秋」等） |

### 4.3 正規化（Python，確定性）

- helper 只引用日期詞：須與焦點句中的文字完全相同（EXACT_TEXT_ALL_OCCURRENCES），helper 不提供正規化值。
- Python 依兩項輸入正規化：
  - 版本化的日期詞參照表：各語言的月份、星期、相對日（昨天、어제、gestern）、旬，做法同 `geographic_reference.json`；
  - 該 record 的 discovery 發布時間（RC-42 已解析）。
- 規則：

| 寫法 | OCCURRED | PLANNED |
|---|---|---|
| 無年份 | 取最接近發布日的年份 | 同左 |
| 只有日（「20일」「20日」「지난 20일」） | 發布日當天或之前、最近的該日 | 發布日當天或之後、最近的該日 |
| 星期、相對日 | 發布日當天或之前 | 發布日當天或之後 |

- 無法正規化（未知語言或寫法）時為 NOT_STATED。後果只是失去日期 DISTINCT 的能力，不會造成合併或排除。

### 4.4 相容性

`gap` = 較晚 interval 的起日 − 較早 interval 的訖日（天數；重疊時 ≤ 0）。

- **Rule D3-1（唯一的日期 DISTINCT）**：同時符合下列條件時為 `DISTINCT_EVENT`，basis 為 OCCURRENCE_DATE：
  - 兩筆 record 都只有一個 type，且 type 相同；
  - 該 type 是 DAY_BOUND（INCIDENT_OR_DISRUPTION 或 ACTIVITY_OR_STATEMENT）；
  - 兩者 interval 皆已確立；
  - `gap ≥ 2`。
- **Rule D3-2**：
  - 其他情形，日期一律不構成 DISTINCT。
  - 陳述的日期不重疊時，適用 RC-38：只有其他 Evidence 足以確認是同一行為者的同一具體行為，才可為 SAME；helper 不得自選某一來源的日期作為正確。這包含 STEP type 的任何差距，以及 DAY_BOUND 差 1 天。

**不同日期但同一 occurrence 的成因與處理**

| 成因 | 典型差距 | 處理 |
|---|---|---|
| 公布日與報導日（光州稽核 25／26 日） | 1 天 | STEP 不以日期分開；RC-38（ED21） |
| 時區、相對日解析 | ≤ 1 天 | 任何 type 都不分開 |
| 宣布日與行為日 | 不定 | 宣布日不是 occurrence date；STEP 不以日期分開 |
| 決定日與生效日 | 不定 | 生效日不是 occurrence date |
| 跨日 occurrence | 不定 | 以起訖期間表示；持續狀態日不計 |
| 預告與實際 | 不定 | STEP 不分開；DAY_BOUND 不同天者是不同事件（預告 30 日罷工 vs 24 日罷工） |
| DAY_BOUND 來源日期錯誤 ≥ 2 天 | ≥ 2 天 | 分開（fail-closed：可能重複，不會誤合併） |

**為何 DAY_BOUND 以 2 天為界**
- 同類事件會反覆發生：ED06；巴黎 22 日與 24 日示威；ED19 體驗活動 21 日與國會發言 23 日。
- 同一 occurrence 在不同來源間的日期差異，最多 1 天：時區、相對日、公布與報導。
- 跨日事件以期間表示，不會因此被分開。

**為何 STEP 不以日期分開**
- STEP 常經宣布而被報導，記載的日期常是宣布日或生效日。差距不代表不同 occurrence。
- 不同的 STEP 由主體與步驟分開，這部分由 helper 判斷。

## 5. D1 — 關係：SAME／DISTINCT／證據不足

### 5.1 三種關係（沿用 `EventIdentityRelation`）

- **`SAME_EVENT`**：合併的唯一依據。
- **`DISTINCT_EVENT`**：
  - 只能由 Python 依已確立的事實產生。
  - 為最終判定：不送 helper，helper 的 SAME 也不得覆蓋。
- **`UNCERTAIN`**（證據不足）：
  - 既不能確立 SAME，也不能確立 DISTINCT，不合併。
  - 是合法的領域結果，不是技術缺口；只有因技術失敗造成時才揭露為缺口。
  - 下游不得救回。
- helper 不提出 DISTINCT（§A.9，不變）。helper 的「分開」只代表沒有確認為 SAME，即 UNCERTAIN。

### 5.2 DISTINCT 依據（窮舉）

| Basis | 條件 |
|---|---|
| `REGION` | 兩者地區皆已確立且不同（RC-22；行為不變，改以 DISTINCT 記錄） |
| `OCCURRENCE_TYPE` | 兩者 type 皆已確立且不相容（§3.3） |
| `OCCURRENCE_DATE` | Rule D3-1 |

其他都不是 DISTINCT 依據：相同主題、城市、系統或專案；宣布者不同；刊登日；標題；出版者；URL；helper 的回答。

### 5.3 判定順序（每一配對）

1. exact-source：Evidence 全文相同 → SAME。不變；相同文字就是同一篇報導，即使兩次 Scope 焦點不同。
2. 任一 DISTINCT 依據成立 → DISTINCT。
3. exact-fact path（不變；production 從未觸發）→ SAME。
4. helper path（§6）→ SAME。
5. 其餘 → UNCERTAIN。

之後由 complete-link 分組，不變（ED10）。

### 5.4 揭露與觀測

- **selection audit**：
  - 每筆 record 的 signature：type、status、interval、precision、引用句 ID、日期詞所在句 ID（不含原文）；
  - 每筆 record 所在的 helper 請求。
- **run summary**：DISTINCT 依據的分布、signature 未確立的筆數。
- **TechnicalGap**（不變）：signature、提案或確認的技術失敗（RC-6）。record 不排除，報告揭露可能有重複。
- UNCERTAIN 不揭露為缺口。

## 6. D4 — 主體識別（含跨語言）與 helper 的角色

### 6.1 helper 只回答一件事

在一個請求內：哪些 record 報導同一 occurrence，即同一主體的同一行為或步驟；若是行為者的行為，還須是同一行為者。

- type 與日期是否相容由 Python 先決定，helper 不重判。
- helper 對已判 DISTINCT 的配對提出 SAME 時，Python 捨棄並記錄，一如 RC-22 對地區衝突的處理。

### 6.2 請求組成（取代 run-wide 批次提案）

**組成**
- 每個請求只含彼此沒有 DISTINCT 依據、且至少共有一個相容 type 的 record。type 未確立者可加入同地區的任何請求。
- 每對可比較的 record，至少一起出現在一個請求中。
- 不再有全 run 一次的批次提案；RC-44 第二次提案撤回。

**內容（不變）**
- 送出：焦點摘錄句（請求內重新編號 S1…）、record 代號。
- 不送：標題、URL、出版者、country、`transit_system_name`、Python 的 signature。
- 大小上限與分批規則不變（RC-18）。

**SAME 的條件**
1. 該請求提案為同群；
2. 沒有任何 DISTINCT 依據；
3. 以只含該群成員的請求再確認一次（RC-23、RC-25、RC-35，不變）；
4. 通過 complete-link 分組。

### 6.3 主體相同的判準（跨語言）

主體是具體實體：
- 路線或系統、車輛或車隊、設施（車站、出入口、機廠）、專案或合約標包；
- DECISION_OR_PLAN 與 ACTIVITY_OR_STATEMENT 另含行為者（機關或個人）。

| 可作為同一主體的依據 | 不可作為依據 |
|---|---|
| 同一名稱的翻譯、音譯、羅馬拼音、文字變體（繁簡、漢字與假名、韓文與漢字） | Evidence 以外的知識：誰營運哪條線、某線位於哪個城市、兩個不同名稱指同一實體（翻譯與音譯除外） |
| 同一筆紀錄自己展開、或自己連結到該名稱的簡稱或描述 | 相同城市、國家、系統、主題或專案 |
| 兩筆紀錄都陳述且相符的具體細節：數量（358 量）、具名地點（運延站～仁川市廳站）、具名當事人、時間 | 標題、出版者、URL、刊登時間 |
| — | 用另一筆紀錄的內容，補足本筆紀錄沒寫的事 |

**證據不足**：一筆紀錄只以通稱指稱主體（「地下鐵」、未寫城市的「2 號線」），又沒有相符的具體細節時，不同群（UNCERTAIN）。

### 6.4 Python 不做的事

- Python 不比較名稱、別名、拼寫或地點。
- country、`transit_system_name`、location 仍是 formal-only（§K 不變）。

## 7. 對既有規則與 Golden 的影響

### 7.1 確認後須修訂的契約條文

| 條文 | 修訂 |
|---|---|
| §A.28 | 「Python has no DISTINCT relation」改為 §5.2 的三種依據。其餘 RC-38 規則（刊登日、日期不一致時的 SAME 條件、helper 不選日期）保留，併入 Rule D3-2 |
| §K | 「No change … except the RC-15 semantic proposal path」加上 §A.35；formal-only 條文不變 |
| §A.9 | run-wide 批次提案改為 §6.2 的請求組成；helper 不提 DISTINCT、驗證、確認、技術缺口等規則不變 |
| §A.16（RC-22） | 行為不變，改以 DISTINCT 依據 REGION 記錄 |
| §A.32（RC-44） | 撤回。ED24、ED25 是 RC-44 的機制案例，隨之退役；其領域結果由新案例重新鎖定（§7.3）。退役屬 Golden 變更，須在實作時另經使用者核准 |
| §A.33 | 宣布者規則成為 §3.2(b) |
| 新增 §A.35 | 本草案 |

TEMPORAL_CONTRACT 與 AGENTS §11 的 task 清單不變。

### 7.2 ED01–ED26

- **不帶 signature 的既有案例**：type 未確立，等同今日的單一請求。ED01–ED23 與 ED26 的腳本與預期結果全部不變。
- **ED24、ED25**：見 §7.1。
- **以真實事實補上 signature 後**，預期結果仍成立：
  - ED19：LAUNCH 與 RIDE 的 type 不相容；RIDE（21 日）與 COUNCIL（23 日）gap 為 2。
  - ED26：OPERATOR 與 LAWMAKER 同 type（宣布者規則，完成日 NOT_STATED）；RIDE（21 日）與 CALL（23 日）gap 為 2。
  - ED16、ED17：OPEN 與 PLANNED TEST 不相容。
  - ED20、ED21：FINDINGS_RELEASE 不以日期分開；兩案結果都由 helper 依 RC-38 決定，不變。

### 7.3 新 Golden（確認後新增）

Golden 只能鎖定 Python 的行為：驗證、正規化、DISTINCT、請求組成、判定順序。helper 的語意判斷（type 是否選對、主體是否相同）由真實回答語料量測（§8），不以 Golden 鎖定。

**Signature 層 OS01–OS10**（腳本化 helper 回答）

| 案例 | 輸入 | 預期 |
|---|---|---|
| OS01 | 「어제(20일)」，發布 10-21 | DAY 10-20 |
| OS02 | 「Am Dienstagabend」，發布週三 10-28 | DAY 10-27 |
| OS03 | 「dai primi giorni di novembre」，PLANNED | PART_OF_MONTH 11-01..11-10 |
| OS04 | 「지난 20일부터 다음 달 27일까지」 | SPAN 10-20..11-27 |
| OS05 | 「12月30日」，發布 2027-01-03 | DAY 2026-12-30 |
| OS06 | 日期詞不在引用句中 | NOT_STATED |
| OS07 | 參照表沒有的寫法 | NOT_STATED |
| OS08 | type 不在清單內，或三個以上 | type 未確立 |
| OS09 | 引用句不在送出的焦點句中 | type 未確立 |
| OS10 | 兩個 type（混合焦點） | 兩者都保留 |

**關係層 ED27–ED39**（腳本化 signature 與 helper 回答；文字以已標註的 Live 紀錄為模型改寫成英文）

| 案例 | 鎖定的規則 | 預期 |
|---|---|---|
| ED27 仁川開通，韓日英多語，議員宣布完成建置 | 宣布者規則；STEP 日期 21 日與 NOT_STATED 相容 | 1 個事件 |
| ED28 開通／部會體驗活動／國會發言 | type 與日期 DISTINCT；斷言沒有請求同時含開通與單一 type 的體驗紀錄；腳本讓 helper 錯誤合併，被 Python 捨棄 | 3 個事件 |
| ED29 混合焦點（同段寫開通與部會活動） | 兩個 type，不以 type 分開；由腳本答案決定 | 依答案 |
| ED30 巴黎示威 22 日 vs 24 日（PLANNED INCIDENT_OR_DISRUPTION） | helper 提 SAME，DISTINCT 優先 | 1 + 1 |
| ED31 相鄰日事故：當地 25 日 23:40 vs 外電 26 日，細節相同 | 差 1 天不 DISTINCT；helper SAME 並確認 | 2 合 1 |
| ED31b 相鄰日的兩起不同事故 | helper 分開 | 1 + 1 |
| ED32 跨日停駛：起日 25 日 vs「27 日仍停駛」 | 後者 NOT_STATED，不 DISTINCT | 2 合 1 |
| ED33 大邱演練：SPAN 10-20..11-27 與 DAY 10-20 共 7 筆 | 重疊相容 | 1 個事件 |
| ED34 決定日 20 日 vs「23 日公布」 | STEP 不以日期分開；RC-38 | 依答案（有相同具體細節時 2 合 1） |
| ED35「董事會核准 12/15 開通」vs「12/15 將開通」 | DECISION 與 PLANNED 相容；斷言兩者在同一請求 | 依答案 |
| ED36 同專案同日的招標 vs 決標 | helper 提 SAME，type DISTINCT 優先 | 1 + 1 |
| ED37 名稱不是 identity：同 `transit_system_name`、同日、同 type，helper 未提 SAME；異文字名稱，helper SAME 並確認 | Python 不比較名稱 | 1 + 1；2 合 1 |
| ED38 signature 技術失敗 | 該 record 加入同地區的請求；揭露 TechnicalGap；全文相同的副本仍合併 | 依案例 |
| ED39 全文相同但 Scope 焦點不同，signature 不相容 | exact-source 優先於 DISTINCT | 2 合 1 |

- ED24 的領域結果（同一決定的三篇報導合併）由 ED34 重新鎖定。
- ED25 的原則（之後的提案不得重開已確認的分開）在沒有第二次提案後已不適用。
- 「確認只能移除配對、遺漏者不合併」仍由 ED17 鎖定。

## 8. 實作與驗收順序（本次未授權，僅供確認）

1. 實作 signature 請求、驗證、日期正規化與參照表、DISTINCT、請求組成，並新增 OS 與 ED 案例。既有 Golden 不改；ED24、ED25 待核准。
2. 離線量測，需另行核准並設上限的付費 helper 呼叫：
   - 兩次 Live 的已標註紀錄 50 筆，各擷取 signature 3 次：約 150 次；
   - 區塊提案與確認：約 40 次。
3. 通過條件：
   - 已標註為不同事件的配對，最終被合併：0。
   - 已標註為同一事件的配對，被 Python DISTINCT 分開：0。例外是兩筆的 Scope 焦點確實報導不同 occurrence，須逐筆說明。
   - 同一 record 三次擷取的 type 集合相同：≥ 95%。
   - DAY_BOUND record 三次擷取的 interval 相同：≥ 95%。
   - 依記錄的回答離線重放，完全重現結果。
4. 通過後，以同一變更撤回 RC-44 與 run-wide 提案。

**呼叫量**

| 項目 | 今日 | 草案 |
|---|---|---|
| signature 請求 | 0 | 每筆 Event Identity record 一次（已觀察到 35–101 筆） |
| 批次提案 | 2 | 0 |
| 區塊提案 | 0 | 約與今日確認數同量級 |
| 確認 | 約 15 | 約 15 |
| 合計 | 約 17 | 約 60–140（都是短請求） |

signature 不併批送出。併批會讓一筆紀錄的結果受同請求其他紀錄影響，這正是本草案要消除的問題。

## 9. 已知限制

- signature 的語意與主體判斷仍由 helper 決定。本草案的作用：
  - 把它們變成逐筆、逐小組、有記錄、可重放的判斷；
  - 讓 Python 依事實排除不可能的配對。
  - 但不保證 Live 沒有重複或誤合併。
- signature 沿用 Scope 的焦點，RC-45 類型的焦點錯誤會延續；修正屬 Scope。
- 混合焦點的 record 不受 type DISTINCT 保護，與今日相同。
- DAY_BOUND 的來源日期錯誤 ≥ 2 天會造成重複（fail-closed）。
- exact-fact path 與 signature 的目的部分重疊。前者在 production 從未觸發；是否退役另案處理，不屬 D1–D4。

## 10. 歷史案例：依草案人工套用

以下是依草案規則，人工套用於已記錄焦點句的結果，不是 helper 實測。

**Run 40999869397 與 41018554355**

| 標註 | 筆數 | 人工 signature | 結果 |
|---|---|---|---|
| 仁川開通 10-21 | 8＋2 | COMPLETION_OR_SERVICE_START；21 日或 NOT_STATED（「21일 밝혔다」是發言日）；議員宣布完成建置者依 (b) | 同一請求 |
| 部會體驗活動 10-21 | 4 | `1cd92dac`、`15710f61`：ACTIVITY；`a071ba69`、`9ce03b4d`：混合（開通＋活動） | 單一 type 者與開通 DISTINCT；混合者兩邊都比較，與今日相同 |
| 國會發言 10-23 | 1＋1 | ACTIVITY_OR_STATEMENT 23 日 | 與開通 type DISTINCT；與單一 type 的活動 gap 2 DISTINCT；`856a50d5` 取決於 Scope 焦點（v12 後為發言） |
| 大邱演練 10-20 | 7 | ACTIVITY；DAY 10-20 或 SPAN 10-20..11-27 | 同一請求 |
| 大邱明德站出入口 10-30 | 2 | PLANNED COMPLETION_OR_SERVICE_START 30 日；說明文字中的區長安全檢查依 (a)／(g) | 相容 |
| 京都行動電源火災 10-26 | 4 | INCIDENT 26 日 | 同一請求 |
| 基輔攻擊 10-26 | 2 | INCIDENT 26 日 | 同一請求 |
| 林茲 vs 德勒斯登電車與貨車相撞 | 2＋1 | INCIDENT；21 日 vs「週二晚間」→ 10-27 | REGION 與 DATE DISTINCT |
| 巴黎示威 22 vs 24 | 1＋1 | PLANNED INCIDENT_OR_DISRUPTION；「Oppdatert」是更新日，不採用 | DATE DISTINCT |
| 貝加莫 T2 測試 | 2 | PLANNED TEST_OR_TRIAL 11 月上旬（`ff849210`） | 相容 |
| 河內合約、基多延伸 | 1、1 | CONTRACT_AWARD 10-15；— | 單筆 |

**Run 40817530617**

| 標註 | 人工 signature | 結果 |
|---|---|---|
| 光州 2 號線稽核 25／26 日 | FINDINGS_RELEASE | 不以日期分開；RC-38（ED21） |

人工套用的結果：
- 沒有已標註為同一事件的配對被 DISTINCT 分開。
- 開通 vs 單一 type 的活動、開通 vs 發言、活動 vs 發言（23 日）、巴黎 22 vs 24、林茲 vs 德勒斯登，都由 Python 確定性分開。
- 這些都是過去 helper 曾錯誤提出的配對類型。

## 11. 請使用者確認

1. Owner 改為 EventIdentity，每筆紀錄一個 signature 請求（§2；修正 §A.34 的 EvidenceService 提議）。
2. Type 清單與粒度、§3.2 的決定順序、相容規則、混合焦點保留兩個 type（§3）。
3. 日期規則：只有 DAY_BOUND 且相差 ≥ 2 天才以日期分開；STEP 永不以日期分開；跨日、預告、決定日與生效日的處理（§4）。
4. 三種關係、三種 DISTINCT 依據、判定順序；exact-source 優先於 DISTINCT（§5）。
5. 主體判準：可用翻譯與音譯，不可用 Evidence 以外的知識；只有通稱時為證據不足（§6.3）。
6. 實作時撤回 RC-44、退役 ED24／ED25（§7.1）。
7. Event Identity 呼叫數由約 17 增為約 60–140（§8）。
