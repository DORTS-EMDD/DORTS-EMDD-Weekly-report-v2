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

Category 的唯一權威規則位於 `docs/ARCHITECTURE_CONTRACT.md` 第 L 節。
Classifier 是唯一 Category owner；Search、Taxonomy、Selector 與 MaiAgent
不得決定或重新分類 Category。Subtype 不得形成新的 workflow lane。

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

MaiAgent Writer 只有一個 production responsibility：

> 正式週報撰稿。

MaiAgent Writer 不得搜尋、選題、Fetch、Dedup、補 Evidence、修改 Scope、修改 Temporal、修改 Event Identity、修改 Category、修改 Taxonomy、修改 Reportability、修改 Ordering、猜缺漏 metadata 或自行查外部背景資訊。

MaiAgent 平台另可提供一個 Generic Stateless Structured Helper，作為下列八個
proposal-only task 的執行 transport：

* `category_semantic_proposal`
* `evidence_metadata_extraction`
* `evidence_source_candidate_match`
* `taxonomy_semantic_proposal`
* `reportability_semantic_proposal`
* `validation_semantic_check`
* `scope_semantic_proposal`
* `event_identity_semantic_proposal`

這個 helper 不是 Domain owner、不寫正式週報、不取代任何 Python
authoritative owner，也不得搜尋、使用外部知識、補充 Evidence 或作
authoritative inference。相同 provider identity 不會合併 Domain owners；每個
task 都保留自己的 request type、完整 instructions、prompt/schema version、
response schema、local validator、post-processing、Domain result type 與
failure semantics，不得建立通用 semantic Domain service。Writer chatbot 與
Structured Helper chatbot 是兩個不同的 deployment identity；Structured
Helper 每次呼叫都必須以 `conversation = null`、空 attachments、完整
task-specific prompt 與對應 schema 自足執行。

Event Identity、Taxonomy、Reportability 與 Validator 可以使用 Helper 取得
bounded untrusted proposal；Classifier、EvidenceService、Event Identity、
Taxonomy、Reportability 與 Validator 仍各自是唯一 authoritative owner。Helper 不得建立 `TaxonomyResult`、
`ReportabilityResult` 或 `ValidationResult`、修改 owner state、略過 local
validation 或直接決定 workflow continuation。

八個 Structured Helper task 的共用設定鍵固定為：

```text
MAIAGENT_STRUCTURED_HELPER_CHATBOT_ID
```

這是唯一 authoritative production helper key；Category、metadata、Taxonomy
或 Reportability-specific chatbot key 不得成為平行 runtime truth。正式部署
使用一個 MaiAgent API family 與兩個 chatbot identities：Writer 與 Helper。
直接 GPT-OSS Gateway、Gemini 及其他第二 AI provider 不屬於 production
runtime，也不得作為 fallback。

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
* Traditional Chinese language
* event population and metadata integrity
* DORTS implication boundary

每個 Event 最多一次 semantic correction。

單一 Event FAIL 只表示已完成合法 semantic validation 後確認的內容或語言
無效；它只淘汰該 Event，不得拖垮其他 PASS Events。Configuration／
authentication 失敗與 invariant 違反必須中止整個正式 run。單一 Event 的
transport、schema、correlation 或 citation 技術失敗（RC-6）只使該 Event 成為
已揭露的 technical gap，不得當成內容 FAIL 或觸發 correction。

Transport retry 與 semantic correction 必須分開計算。

### RC-3～RC-31 修訂（2026-10-20～29）

完整條文見 `docs/ARCHITECTURE_CONTRACT.md` §A.1～§A.25 與 §N。

* RC-3：所有引用 seam 採 `EXACT_TEXT_ALL_OCCURRENCES`；同一字串重複出現不再
  使 Evidence、Scope、Category、Taxonomy、Reportability 或 Validation 失敗；
  Python 記錄全部出現位置、不選擇任一位置；Scope 端點必須位於建立該關係的
  引文脈絡內；Metadata 採欄位層級驗證。
* RC-4：Country／Region 由 EvidenceService 依版本化 `geographic_reference.json`
  對來源原文值做確定性解析（SOURCE_STATED／REFERENCE_MAPPED／NOT_STATED／
  UNRESOLVED）；不得用 Search market、query、publisher、TLD 或模型知識；
  Country 與 transit_system_name 不再是阻擋整份報告的必填欄位，報告顯示
  「來源未載明」或「未能確認」。
* RC-5：合法的事件層級資料不足（目前僅 `CONFLICTING_COUNTRY`）只排除該事件並
  揭露；invariant 違反仍中止整個 run。
* RC-6：所有 MaiAgent task 共用一個 transport policy：未取得可解析回應的暫時性
  故障（timeout、連線、HTTP 429／5xx、無法解析的 JSON）最多以相同請求重試一次；
  401／403／404 立即中止；可解析回應一律不重試。剩餘技術失敗是
  `TechnicalGap` execution disposition，不是任何 Domain state；含技術缺口的
  run 狀態為 `SUCCESS_WITH_TECHNICAL_GAPS`，不得標示為完整成功。
* RC-7（§A.2）：Validator 以確定性 Python 規則將 Writer 各欄位切分為具
  `unit_id` 的單元；`validation_semantic_check` helper 只回傳各欄位語言評估與
  各單元的評估及 Evidence 引文，不得回傳、切分或改寫 Writer 文字。Python 驗證
  每個單元恰被評估一次；單元整體受支持才可為 `SUPPORTED`。
* RC-8（§A.3）：Scope 提案的 action／target／system 改為標籤，必須位於建立該關係的
  引文內；noneligible 關係只針對焦點行動；發生於合格系統車站、月臺、列車等設施的
  事件可為 IN_SCOPE（報導價值由 Reportability 判定）；commuter／suburban／S-Bahn
  名稱不自動納入或排除，須來源支持其為都市軌道系統。
* RC-9（§A.4）：Python 將 Evidence 切成編號句子，Scope 與 Validator 只以句子 ID
  引用來源，不再重打原文；Scope 提案違反契約時為已揭露的技術缺口，不得當成
  OUT_OF_SCOPE；Validator 的一次改寫重驗已接上，Writer 會收到未通過的單元。
* RC-10（§N）：Reportability helper 必須收到契約的報導價值路徑；一般治安、醫療或
  個人事件僅造成短暫局部服務調整者不成報。
* RC-11（§A.5）：搜尋以報告期間為範圍；每個語言版本與 intent 以該語言詞彙的 OR
  群組查詢（449 → 207 次）；Google News 連結由 EvidenceService 解析為出版者文章，
  並核對 RSS 宣告的出版者網域，只有出版者頁面可成為 Evidence。
* RC-12（§A.6）：以 RSS 發布時間過濾期間外結果（缺時間者保留，日期有效性仍由
  Temporal 判定）；運具詞須出現在標題、只用具體意圖詞；新增專業軌道媒體查詢；
  搜尋計畫 207 → 122 次。
* RC-13（§A.7）：主文件判定不計 script／style 文字；唯一的 schema.org
  articleBody 可決定主文章；純 header 區塊屬主文件；文章內純連結區塊排除；
  AMP 頁改取同網域 canonical 文章。
* RC-14（§A.8）：英文搜尋運具詞改為明確詞組（metro line、metro station 等），
  不再用單字 metro／subway；跨語言重複仍由 Event Identity 單一負責合併。
* RC-15（§A.9）：Event Identity 以每個 run 一次的批次 helper 提案取得跨來源
  同事件群組（上限 60 筆）；成員以句子 ID 引用 subject／occurrence／lifecycle；
  Python 驗證後才轉為 SAME_EVENT 關係，交由既有分組規則；未提議者維持不合併；
  提案無效為已揭露的技術缺口，事件不排除但可能重複；取代原逐對 advisor。
* RC-16（§A.10）：Category、Taxonomy、Reportability 的 helper 請求以 Python 指定的
  短來源代號（M1、M2…）與句子 ID 呈現成員；引用改為來源代號＋句子 ID，不再抄寫
  原文或候選 ID；Category 提案違反契約時為已揭露的技術缺口，不得當成
  CATEGORY_UNRESOLVED。
* RC-17（§A.11）：Scope 事件焦點已確定時，關係引用句至少含一個端點，所有端點標籤
  須位於事件焦點範圍內；關係引用仍須在焦點內，不得跨事件借用；焦點未確定時沿用
  RC-8 規則；標籤仍須為原文，頁面標題不作 Evidence。
* RC-18（§A.12）：Event Identity 每個 run 只送一個請求，唯一上限是請求內容大小
  （66,000 字元），取消 60 筆上限；超過時先統一縮短各筆開頭摘錄，最後才依發布
  時間分批，並記錄 PROPOSAL_BATCH_SPLIT 診斷。
* RC-19（§A.13）：來源值整體查不到時，可依其所含的參照表名稱（皆指向同一地區、
  不含歧義名稱、拉丁字母需整詞相符）解析國家／地區；參照表升為 geo-reference-v2。
* RC-20（§A.14）：Event Identity 與 Writer 以 Scope 的候選事件焦點句為準（比較的是
  候選事件、Writer 只寫該事件）；韓日名稱用既有中文名或完整原文，不得混寫，
  Validator 以確定性規則擋下韓文與漢字黏連的詞；metadata 只擷取主要事件的單一值；
  合併成員的系統名稱不同時顯示 canonical 成員的值並保留診斷；Reportability 明列
  獎項／官員視察與發言／輕微路面擦撞等一般低價值類別。
* RC-21（§A.15）：同一紀錄可出現在多個 Event Identity 提案群組；每群只提出群內的
  SAME_EVENT 配對，由既有 complete-link 分組決定，未一起被提議的紀錄不會合併；
  同一群內重複列出的紀錄只使該群無效。提示詞要求同一事件放在單一群組，並說明不同
  城市、國家或系統的事件是不同事件。
* RC-22（§A.16）：同一事件只發生在一個國家／地區；提案配對兩端的 EvidenceService
  地區皆已確立且不同時，Event Identity 不採用該配對並記錄
  PROPOSAL_REGION_CONFLICT 診斷；同群其他配對照常，任一端未確立則不受影響。
* RC-23（§A.17，使用者核准）：每個仍有配對的提案群組，以同一 helper task、同一
  schema 與 prompt，只送該群成員再提案一次作為確認；配對須經批次提議、通過地區
  檢查且再次被提議才是 SAME_EVENT；確認只會移除、不會新增配對；確認失敗或無效
  為已揭露的技術缺口，該群不合併；每週約多 15 次呼叫。
* RC-24（§A.18）：Validator helper 改以短來源代號（M1…）加句子 ID 引用，不再抄寫
  候選 ID；提示詞明示 SUPPORTED 與 ANALYSIS 單元都須引用 Evidence 句子（ANALYSIS
  引用其事實前提），無法引用前提者為 UNSUPPORTED；標題為單行純文字，Writer 不得加
  符號或分類標籤前綴、不得提及請求或輸入（如「候選資料」），Validator 以確定性規則
  擋下含 emoji 或以括號／直線標籤開頭的標題，並把前綴交給那一次改寫。
* RC-25（§A.19）：Event Identity 確認請求標示 confirmation，helper 須把每筆紀錄恰好
  列一次（同事件者同群、其他各自單獨成群）；被遺漏的紀錄視為未決定，不合併並揭露為
  CONFIRMATION_INCOMPLETE 技術缺口，Python 不把遺漏當作同意；Reportability 低價值
  類別擴及政治人物、民間團體或評論者的聲明與批評，以及無新發生事項的專題、背景或評論
  文章。
* RC-26（§A.20）：正式報告記錄並顯示報告期間；寄件主旨為「捷運技術週報｜期間｜N 則」；
  Delivery 以持久寄送紀錄（僅存雜湊）擋下同一 artifact 或同一期間與收件目標的再次寄送；
  寄送失敗使 CLI 非零結束；GitHub Actions 每週排程與實際寄信皆須以 repository
  variable 或 dispatch 輸入明確啟用。
* RC-27（§A.21，使用者指示）：選題範圍為國內＋國際都市軌道新聞，臺灣列為 Search
  市場（zh-TW），事件仍依一般 Scope／Category／Reportability 規則判定；Reportability
  helper 須標示主要發生類型，獎項排名、視察與發言、背景專題由 Python 判為不成報；
  臺北捷運局啟示中只提出建議的單元屬 ANALYSIS（引用事件句子），只有陳述無依據事實者
  才是 UNSUPPORTED；啟示須具體、不得就臺灣事件聲稱捷運局自身角色或狀態；地理參照表
  v3 補韓日文國名與德文城市形容詞。Live 驗收後補充：Scope 明列各語言運具詞（捷運＝MRT
  等，台鐵／高鐵非都市軌道）；主要發生類型以本文新發生者為準；MaiAgent 回傳同一答案
  重複兩次的 content 時，僅在首尾為相同完整 JSON 物件時採用。
* RC-28（§A.22，使用者鎖定）：正式週報只收錄位於 Search Configuration 核定之 20 個
  國家／地區（含臺灣）的事件，selected／global 與所有入口一致；名單唯一來源為
  RegionRegistry（各市場 region_id）；由 ReportService 正式 metadata 投影依
  EvidenceService 確立的事件所在地判定，不得用搜尋市場、媒體、網址或模型常識；
  確立於非指定地區者以 NON_DESIGNATED_REGION 排除，所在地無法確立者以
  REGION_NOT_ESTABLISHED 排除並於報告揭露。辨識改善：metadata 地點改擷取來源所寫的城市
  （非街道、廣場、車站）；地理參照表 v4 補指定地區城市的韓日中文名稱與缺漏的都市軌道城市。
* RC-29（§A.23）：數字必須有來源依據。Writer 照來源原數字與量級詞書寫，或只用精確換算
  （crore＝千萬、million＝百萬、억＝億等），不得自行加上換算值、單位換算或合計，幣別只能
  與來源一樣具體（$、¥、Rs、元等共用符號照原文，不得改寫為來源未載明的美元、日圓、新臺幣）；Validator 在
  helper 呼叫前以確定性規則檢查標題、摘要、啟示中帶單位或幣別、≥10,000 或帶萬／億／兆的
  數字：須有 Evidence 以相同度量（長度、面積、百分比、百分點等，英里不換算）或至少同樣具體的
  幣別陳述該值，且四捨五入到 Writer 所寫最後一位後相等（不用相對容差）；數字相同但單位或幣別
  不同不算有依據。Evidence 每個數字只有一種讀法：「5,000」「1.234」這類分隔符後恰三位數者，
  依序由相鄰 CJK 寫法、來源自身確立的小數點、僅英文使用的量級詞、末位為 0 判定，否則視為
  無法判定、不作依據。不符者使用該事件唯一一次改寫，改寫後仍不符則該事件 FAIL；日期、件數等
  小數字不在確定性檢查範圍。
* RC-30（§A.24，僅觀測）：雲端 Run 40653585176 的 Event Identity 63 → 63 完全未合併，
  只有 1 個技術缺口、耗時 5.8 秒，符合整批請求失敗，但失敗類別未被記錄，根因未確認，
  Event Identity 規則不變。每個技術缺口改以 `stage:level:kind:failure_class` 簽章輸出到
  trace 與 run summary；Event Identity 的 level 標明失敗的是整批、某群、某次確認或確認中
  的某群，並輸出診斷原因分布。只做觀測，不含紀錄 ID 或來源文字，不參與任何決策。
* RC-31（§A.25）：確認不完整的根因已確認：確認請求附帶的回應 schema 要求每群至少 2 筆，
  與 RC-25「被分開的紀錄單獨成群」互相矛盾，helper 因此改以省略表達分開。確認請求改用允許
  單筆群組的 schema，「不得回傳單筆群組」只適用一般分群請求；省略仍 fail-closed、不以原提案
  代替確認。本期四組疑似重複的逐案根因因雲端回應未保留而未確認。每次執行另輸出觀測用
  `selection_audit.json`，逐候選列出各階段結果與最早終止階段及原因，不重算任何決策。PDF
  不顯示運輸系統與執行說明、來源改為一行連結；Email 內文改為分類標題索引並附 PDF；
  Markdown 保留全部欄位與執行說明。來源顯示名稱（使用者確認，修訂 §R）：EvidenceService
  已記錄出版者來源核對相符、且宣告的出版者網域對應 canonical 網址主機時，顯示該出版者名稱
  （如「來源：Impress Watch」，連到 canonical 網址）；否則顯示 hostname。唯一 owner 為
  ReportService 的 `source_display_for`，Validator 呼叫同一函式，PDF／Markdown／Email 只使用
  投影值；canonical 網址、Evidence 資格與來源判定不變。

## 13. Report / Delivery

```text
Final report count = Validation PASS count
```

0 篇仍正常產生正式 artifact。正式 artifact 必須揭露 technical gap、事件層級
排除與 Validation FAIL 的數量；有技術缺口的 0 篇不得呈現為「本期無符合正式
報導條件之事件」。

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

### Real E2E admission

昂貴 Real E2E dispatch 前，`FAILURE_EXPLAINABILITY` 必須通過 offline acceptance：
已完成階段的安全診斷須能在後續 application failure 或 process hard termination
後保留。所選 execution environment 的 runtime capacity fit 必須另外成立；
trace implementation 或 tests passing 單獨不授權 Real E2E。

## STATUS

```text
AGENTS_VERSION = concise-v1
ARCHITECTURE_CONTRACT = docs/ARCHITECTURE_CONTRACT.md
ARCHITECTURE_BASELINE = v0.5 FINAL_LOCKED
V1_STATUS = FROZEN_REFERENCE
ENTRY_POINT_CLARIFICATION = APPLIED
CONTRACT_REVISION = RC-3..RC-31 APPLIED (2026-10-29)
```
