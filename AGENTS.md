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

正式執行必須涵蓋五種 discovery intent：

* technology
* major incident
* operations
* procurement
* monitored_standards（RC-58：以監控標準清單的編號搜尋該批標準的動態；RC-59：只在每月檢查的那一期規劃；RC-60：另以官方標準目錄 provider 讀取已設定的目錄紀錄）

每個啟用 intent 都必須至少 `PLANNED + ATTEMPTED`。

搜尋最高 discovery priority：

> 新技術、新材料、新方式。

Search intent 不等於正式 Category；`monitored_standards` intent 不得推導 `NORMATIVE_CHANGE`，也不決定是否為監控標準更新。

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

`NORMATIVE_CHANGE` 事件只有在 Evidence 證明為監控標準清單（`src/weekly_report/monitored_standards.json`）
中某一標準本身的正式變動時才 REPORTABLE（RC-58）；其他規範變動為 NOT_REPORTABLE（`OUTSIDE_MONITORED_STANDARDS`）。
該事實由 ScopeClassifier 在每月檢查中判定，Reportability 只讀取（RC-59）。

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

### RC-3～RC-78 修訂（2026-10-20～11-20）

完整條文見 `docs/ARCHITECTURE_CONTRACT.md` §A.1～§A.47、§L、§N 與 §R。

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
* RC-32（§A.26，僅觀測）：Run 40817530617 的三組重複（維也納第 1,000 輛、光州 2 號線稽核、
  仁川 5G 品質體驗）以離線重建請求確認：決定性 Evidence 都在送給 helper 的摘錄中，屬 helper
  分群漏提或確認誤分，原因無法觀測，根因未確認，未修改任何規則、提示詞或 schema。Event
  Identity 另記錄每筆紀錄送出的句子 ID 與摘錄上限，於 selection audit 與 run summary 顯示，
  不含原文、不參與決策。
* RC-35（§A.27，澄清 §A.19）：RC-33、RC-34 為唯讀審查。確認回答改為「每個發生事項各一群、
  其餘紀錄各自單獨成群、不同發生事項不得同群」（提示詞 v6）；原寫法只容許一個同事件群組，
  同一提案群組內的第二個事件無法被確認。Python 驗證與判定邏輯、schema、呼叫次數與
  SAME_EVENT 規則都不變；確認仍只能移除配對，遺漏仍 fail-closed。Golden ED19 鎖定一個
  提案群組含兩個多筆事件。仁川、維也納、光州的重複根因仍未確認。
* RC-38（§A.28，使用者核准；RC-36、RC-37 為唯讀審查）：文章的發布、更新或報導日期不是
  事件發生時間，不作同一事件的依據；只有描述事件本身發生時間者才算。來源記載的發生日期
  不同，本身不代表不同事件；日期不一致未能由 Evidence 釐清時，只有其他 Evidence 足以
  確認是同一次發生（同一行為主體的同一具體行為，而非同主題、城市、系統或專案）才可確認
  同一事件，可能是同類的不同次發生者維持分開；helper 不得自選某來源日期作為已解決。
  提示詞 v7；Python、schema、TemporalRule 不變；Golden ED20、ED21。§K 衝突內容在
  production 未落實（只用 canonical 來源撰寫）另案處理。
* RC-40/41（使用者核准；RC-39 為唯讀審查；觀測見 §A.29，章節見 §R）：被拒絕的提案群組或確認群組
  （`DUPLICATE_MEMBERSHIP`、`CITATION_INVALID`）另記錄 `PROPOSAL_GROUP_REJECTED` 診斷，
  列出其成員候選 ID 與「群組代號｜原因」，selection audit 顯示；只觀測，§A.15 整群拒絕不變。
  正式報告章節由 ReportService 依 CategoryId 固定排序與命名：技術新知、事故及安全事件、
  營運動態、機電標案及採購動態、規範及標準動態，空章節不顯示；Markdown／PDF／Email 共用；
  Category 判定、§L 標籤與 Golden 不變。事故章節依嚴重度排序因無嚴重度 owner 且 §N 禁止，
  列為 BLOCKED_DOMAIN_RULE。
* RC-42（§A.30）：Event Identity 提案改為逐成員驗證：群組內重複列出的紀錄
  （`DUPLICATE_MEMBERSHIP`）或引用無法解析的紀錄（`CITATION_INVALID`）只淘汰該成員並揭露為
  技術缺口，同群其他成員照常進入確認；觀測診斷改名 `PROPOSAL_MEMBER_REJECTED`（selection
  audit v2）。紀錄依解析後的發布時間排序（原本按 RSS 字串的星期名稱排序，違反 §A.9／§A.12）；
  每筆摘錄在請求內重新編號為 S1…Sn，文件句子 ID 只作觀測。提示詞 v8 只補兩句既有規則：
  缺少或寫法不同的非識別細節不使紀錄成為不同事件（§K）；每個引用清單至少一句。同一事件定義、
  日期規則、兩種回答格式與 schema、SAME_EVENT 條件皆不變。離線試驗後未採用：擴大摘錄（造成
  10/23 國會發言與 10/21 開通誤合併）、批次逐筆完整放置（召回下降）。仁川「營運機構開通」與
  「部會同日體驗驗證活動」經使用者決定維持為不同事件（為標示或驗證里程碑而辦的活動自成
  一事件，§A.9 與 Golden ED19 不變）。原 Golden ED22、ED23（RC-47 原封不動移為回歸測試）；ED01–ED21 不變。
* RC-43（§A.31）：Scope 提示詞 v11 補兩句既有規則：裝在車輛、列車、軌道、車站等設施上的
  設備沿用該設施的系統歸屬，系統列車與維修、檢查本系統軌道的車輛（如夜間軌道內保守作業車）
  屬 FUNCTIONS_FOR 或 PART_OF，其上設備亦同；營運者非軌道資產（公車、渡輪、不動產）仍排除。
  焦點句陳述未發生或不會發生（如「今晚未預告施工」）時為 NEGATED，不得為 ASSERTED。
  Python 驗證、schema、正向條件不變。1904 年歷史事件經 5 次重放皆判為 FEATURE_OR_BACKGROUND，
  Reportability 不變；Event Identity 剩餘重複為批次提案召回的呼叫間變動，未修改；
  「批次提案兩次取聯集」屬機制決定，已於 RC-44 依證據決定採用。
* RC-44（§A.32）：每個 Event Identity 批次請求固定提案兩次，第二次為相同請求、紀錄反序並重新
  編號（批次代號加 `-n2`），兩次一律都送出。任一次提出的配對照常經地區檢查、確認與
  complete-link 分組；SAME_EVENT 定義不變。較早一次確認的判定為最終：之後的提案只把尚未被確認
  判定過的配對送確認，已被分開的配對不會再問。每次提案的失敗或違約各自揭露為技術缺口。每次執行
  多 1 次批次呼叫，另加新增配對群組的確認。Golden ED24；ED25 由 RC-47 原封不動移為回歸測試；ED01–ED23 不變。
* RC-45（§A.33）：Live Run 41018554355 檢討。每個合併都取決於單次 helper 判斷（同一批次請求三次
  提案召回 66%／85%／95%），Golden 與回歸測試只驗證 Python 對腳本答案的處理，無法預測 Live 品質。
  國會發言併入仁川開通的最早錯誤在 Scope：事件焦點選了文章回顧的背景句。Scope 提示詞 v12：
  候選事件是文件自身報導的新聞，不是回顧的背景；新聞是聲明或質詢時以聲明為事件，經某人宣布的
  發生事項仍以該事項為事件。觀測：確認接受配對時記錄 `PROPOSAL_CONFIRMED`，run summary 顯示
  各次提案確認的配對數（`event_identity_confirmed_pairs`）。RC-44 保留，若 Live 顯示第二次提案
  未確認任何配對即撤回（撤回條件已由 RC-47 修訂）。使用者決定（修訂 §A.9）：不同宣布者報導同一 occurrence 視為同一事件，
  須由 Authoritative Evidence 確認為同一發生事項；本身構成獨立 occurrence 的宣布行動、政策決策、
  檢查或實際活動仍分開；不得僅依相同主題或宣布者不同決定合併或分開。提示詞 v9 另列此規則，
  同一事件定義與日期規則不變；Golden ED26。
* RC-46（§A.34）：Event Identity 架構檢討。目前每個合併都取決於 helper 回答；production 從未
  產生事實比對所需的 occurrence 事實，§K 不授權新比對規則，§A.28 規定 Python 無 DISTINCT。
  已實作（僅觀測與測試工具）：Event Identity 記錄每次 helper 往返（只含 ID）、selection audit
  記錄 Evidence 雜湊；`scripts/event_identity_replay.py` 可依 audit 離線完全重現該次合併；
  `acceptance/event_identity/recorded_answers.json` 收錄兩次 Live 紀錄上的 11 份真實 helper 回答與
  人工標註，測試重算並鎖定結果（同一請求三次提案找到 40／52／58 of 61）。建議的權威機制：由
  EvidenceService 以既有 metadata 任務擷取每筆紀錄的 occurrence 類型與日期，Event Identity 以
  確定性規則判定，helper 只判斷同區塊內主體是否相同；需使用者決定 D1～D4。RC-44 為過渡措施，
  事實分區上線或 Live 顯示第二次提案未確認任何配對時撤回（撤回條件已由 RC-47 修訂）。
* RC-47（§A.35，使用者核准）：Golden 的預期結果必須是該案 Evidence 的領域事實；腳本化 helper
  缺陷而預期 fail-closed 結果、與自身 Evidence 領域事實相反的案例屬機制回歸測試。ED22、ED23、ED25
  與 ED24 為逐字相同的同一決定報導（ED24 鎖 [3]），其預期只來自腳本缺陷，已原封不動移至
  `tests/fixtures/event_identity_failure_path_cases.json`，由 `tests/test_event_identity_failure_paths.py`
  以同一 harness、owner 與斷言執行，並以 SHA-256 與預期結果鎖定，同時要求 Golden ED24 維持 [3]；
  Event Dedup Golden 改為 23 案，代號不重用。RC-44 只能連同仍使 ED24 為 [3] 的替代機制一起撤回。
  Event Identity D1～D4 草案（`docs/EVENT_IDENTITY_OCCURRENCE_RULES_DRAFT.md`）R1～R6 已確認，尚未
  寫入契約、尚未實作（RC-48 實作）。
* RC-48（§A.36，使用者確認 R1～R6）：Event Identity 內的 helper 輸出不得產生 DISTINCT；唯一的
  DISTINCT 依據是已確立地區衝突（RC-22），改記為 `DISTINCT_EVENT`（診斷 `DISTINCT_REGION`），並先於
  exact-source 與 exact-fact。exact-source 另須兩筆的 Scope 候選事件焦點相同（同一頁可報導多個事件）。
  同一事件的粒度、日期（不由刊登時間或時區推定、只比較雙方都寫的年月日）與跨語言主體（可用翻譯音譯、
  不可用 Evidence 外知識）寫入提示詞 v10，v9 各行逐字不變；Python 不比較名稱。請求組成、RC-44、確認
  皆不變；逐筆 signature 與依地區分組經量測否決。Golden ED27、ED28；ED01–ED26 結果不變。R7：提示詞
  v10 合併前須以標註語料量測（不同事件配對合併數須為 0），付費呼叫待使用者核准上限。
* RC-51（§A.37，使用者核准後已撤回，2026-11-03）：曾在 Scope 焦點句後加上同一 Evidence 的後續句作為 context，
  使用提示詞 v11，並以焦點檢查限制 occurrence 引用。使用者授權的成對量測（426 次呼叫，三份語料、各組三次）
  顯示同事件召回在每份語料都低於 RC-48；損失主要是更多配對未被提案、更多配對在確認時被分開，焦點檢查每次
  最多只移除 3 個配對，未發現 Python 缺陷。依使用者決定撤回，§A.14 與 RC-48 的請求、提示詞 v10 恢復有效。
  R7 量測中 v10 在三次之一合併了一個不同標註配對，R7 條件未達成，main 維持阻擋。
* RC-52（§A.38，使用者核准）：Event Identity 的提案程序（RC-44 兩次提案加各群確認）在相同請求上獨立執行三次；
  至少兩次確認的配對才是 SAME，只被一次確認者維持 UNCERTAIN，記為 `PROPOSAL_NOT_AGREED` 診斷。
  R1～R5、提示詞 v10、請求、complete-link 分組、fail-closed 處理皆不變；每次程序各自揭露技術缺口；批次代號加
  `-p2`、`-p3`，重放依各程序的往返記錄。helper 呼叫約為三倍。以記錄的九次 RC-48 回答作為三次程序，
  不同標註配對合併為 0，召回為 46/61、48/51、298/312；Golden 結果不變。
* RC-55（§A.39，使用者核准，取代 §A.20 的 Actions cache 寄送紀錄）：Run 41585675879 回報 Delivery FAILED 且未留
  紀錄，寄件備份卻有該信（備份不代表已取得最終 250）。正式郵件改為每位收件者一封，由 Delivery 唯一 owner 在獨立
  private repository 的交付紀錄中逐人記錄：寄出前以 compare-and-swap 寫入 ATTEMPTED，觀察到最終 250 才記 SENT，
  明確拒收或從未開始的交易記 NOT_SENT；ATTEMPTED 與 SENT 擋下再次寄送，ATTEMPTED 不會因時間過期。claim 屬於寫入
  它的那次執行（RunTrace run_id）；寫入衝突時重讀並依 claim ID 對帳。紀錄只存 HMAC 雜湊，不存地址。人工解除只能在
  手動執行中指名同期間、至少 24 小時前的 ATTEMPTED claim，全有或全無並留稽核；排程執行不得解除。無法讀寫紀錄、
  claim 未確認或寫入失敗時一律 fail-closed；未設定紀錄不得寄正式郵件。workflow 已接線（移除 Actions cache、
  傳入三個紀錄 secret 與兩個解除輸入，另有僅能手動執行的 `delivery-check` job 執行 L1～L3）；紀錄
  repository／token／金鑰已建立，live 驗證 L1～L3 已通過（L3：Run 41758040505）。
* RC-56（§A.40，使用者指示）：報告週期為 Asia/Taipei 的［週一 00:00，下週一 00:00），以週一至週日的日期顯示與
  傳遞；「上一周星期一到本周星期一」依此半開區間解讀，相鄰兩期不重疊也不漏日，週一（含排程前發布者）屬新的一週。
  唯一 owner 為 `production_runner.default_period`，依執行當下的臺北日期決定（原本用機器本地日期，GitHub runner
  為 UTC，週一 06:30 臺北仍是週日，會選到上上週）；所有入口共用，手動指定期間仍優先。排程為每週一 06:30
  Asia/Taipei（cron 加 timezone），仍由 WEEKLY_REPORT_SCHEDULE 與 LIVE_EMAIL_SEND 變數把關。訂閱名單由外部郵件
  清單（Google Group）擁有並自助加入、退出；V2 只知道 DEFAULT_RECIPIENTS 中設定的發送地址，不保存任何訂閱者
  地址；RC-55 對每個設定地址保證每期至多交付一次。上線閘門（原則不變）：目前程式產生的報告先寄給受控地址且
  附件未被標記後，才改寄清單；公務信箱須經使用者明確授權才屬受控地址；不補寄 Run 41585675879。閘門已於
  2026-11-04 滿足：Run 41765559889 經使用者授權寄至其公務信箱（SENT），使用者確認收到、PDF 可下載開啟且無附件
  警告；正式部署已改寄外部郵件清單，並啟用 WEEKLY_REPORT_SCHEDULE 與 LIVE_EMAIL_SEND。
* RC-57（§A.41，使用者核定 Domain Rule）：V2 必須主動搜尋符合既有 `NORMATIVE_CHANGE`（§L）定義的規範／標準
  變動。根因：基線的四個 discovery intent 對應原本四個 Category，4fdcd1b 新增 `NORMATIVE_CHANGE` 時未同時新增
  discovery intent，RC-12 又移除 operations 的 policy 詞，v7 計畫的 122 次查詢沒有任何規範詞。修正：由 SearchPlanner／
  RegionRegistry 新增第五個 discovery intent `normative`，13 個語言 profile 各有一般性的規範行動詞（新／修訂標準、
  法規修正、技術規格、正式指引、草案），不列任何標準編號、標準組織、主管機關或網站；計畫 122 → 155 次（normative
  33）。Search intent 不是 Category：結果照常走完 Evidence 至 Validation，Classifier 仍是唯一 Category owner，§L、
  §N 不變；符合者進入當週週報既有「規範及標準動態」章節，沒有時省略該章節；不另寄信、不另設排程、不保存標準
  版本狀態，Delivery（RC-55）、訂閱（RC-56）與報告週期不變；不搬 V1 watchlist。（產品範圍與搜尋詞已由 RC-58 修正。）
* RC-58（§A.42，使用者核定 Domain Rule，部分取代 RC-57）：標準更新監控的範圍是 V1 原始固定標準清單，共 27 個
  （4 類；本機 V1 快照 31 份副本完全相同，SHA-256 記於資料檔），唯一來源為 `src/weekly_report/monitored_standards.json`；
  只有 Evidence 證明「清單中某一標準本身」發生正式變動（新版或修訂、修正、勘誤、撤回、被取代、正式草案或徵詢）才算；
  其他標準、國家或地方法規、條例、一般指引即使屬 `NORMATIVE_CHANGE` 也不進「規範及標準動態」。RC-57 的根因：把需求讀成
  「主動搜尋所有規範變動」並使用泛用規範詞。修正：discovery intent 改為 `monitored_standards`，以 27 個編號為 OR 查詢
  （每個支援版本 3 次，由資料檔自動帶入搜尋設定）；計畫 185 次，其餘 122 次與 v7 相同。Category 不變；由 Reportability
  決定：`NORMATIVE_CHANGE` 事件沒有監控編號即 NOT_REPORTABLE（`OUTSIDE_MONITORED_STANDARDS`，不呼叫 helper），有則以同一
  helper task 的第二種請求問「哪一個標準本身變動」，Python 只接受有出現在引用句中的已提供編號，再走原本的價值判斷；引用、
  遵循、採購要求、建議、回顧都不算。G69–G74 的 Reportability 改為 NOT_REPORTABLE；新增 Golden MS01–MS09。Scope、RC-28、
  Delivery、訂閱、排程、報告週期不變，不新增狀態。未決 Domain 決定：監控標準的公告若未提及都市軌道或指定地區，仍會被 Scope
  或 RC-28 排除（BLOCKED_DOMAIN_RULE；已由 RC-59 解決）。
* RC-59（§A.43，使用者核定 Domain Rule）：
  * 週報每週執行；27 項監控標準每個日曆月檢查一次。唯一 owner 是 `monitored_standards.monitored_check_month`：
    報告期間（週一至週日）包含某月最後一天的那一期，檢查整個該月份；每個月恰好一期，只由期間決定，延遲、重試、
    手動重跑同一期答案相同，RC-55 仍擋下重寄，不需任何狀態。
    例：2026-11-30～12-06（12-07 寄出）檢查 11 月，2026-12-28～2027-01-03 檢查 12 月，其餘週不檢查。
  * 只有該期的 Search 計畫加入 63 次編號查詢，期間為整個月份，其他查詢仍為週期間；一般週計畫為 122 次。
  * 窄例外由 ScopeClassifier（唯一 Scope owner）負責：該期候選本文出現監控編號時，以 Scope helper 的第二種請求問
    「哪一個標準本身正式變動」；Python 只接受已提供且出現在引用句中的編號。成立者以 `MONITORED_STANDARD` 依據
    IN_SCOPE，不需都市軌道關係；TemporalRule 以檢查月份判斷日期；ReportService 對 Reportability 標明
    `monitored_standard` 的事件不套用 RC-28 地區規則。其他標準、法規、條例、採購規格、引用、建議與評論都不適用；
    此依據也只能進「規範及標準動態」。
  * Reportability 不再自行詢問，只讀取 Scope 事實。
  * Golden MS01–MS15。Delivery、訂閱、排程、報告週期不變；不新增第二封信或任何狀態。
  * 已知限制（2026-11-05，7 月回放 Run 41942587859）：月檢已正確執行（63 次、整月、0 失敗），但 IEC 61373:2026
    （2026-07-17 發行）未成為候選。最早失敗點是 Search 取回：Google News 在 7 月沒有任何提及 IEC 61373 的項目，
    標準發行只出現在標準組織或經銷商目錄。此限制適用全部 27 項；需另選非新聞的標準目錄來源（可能需授權或憑證），
    待使用者決定（BLOCKED_EXTERNAL_DECISION），程式未修改。（第一階段已由 RC-60 處理。）
* RC-60（§A.44，使用者核准）：每月檢查另以官方標準目錄讀取監控標準的正式紀錄。
  * Search：新增第二個 provider `standards_catalogue`，與 Google News 平行、互不補救；只負責產生 Candidate。
    每個已設定的紀錄每月一次請求，只在該來源網域內轉址，使用誠實的 user-agent，不模擬瀏覽器。
  * Evidence：由 EvidenceService 以官方紀錄自身欄位（編號、標題、日期、版次、狀態、說明）建立 Authoritative
    Evidence；source type 為 `official_standards_catalogue`，地區為「來源未載明」。
  * Scope、Temporal、Category、Taxonomy、Reportability、Delivery 都不變；不新增狀態。
  * 第一階段 10／27 項：IEC 9 項（61373、62271-100、62271-102、60947-1、60850、60754-1、60754-2、60076-11、62695）
    與 IEEE 1474.1。其餘 17 項仍只靠新聞：EN 9 項（官方 robots 禁止）、ASTM 2 項（CDN 對正式 client 回 403）、
    NFPA 70／130（無日期）、NFPA 258（2006 年撤回）、UIC 860-0（找不到紀錄）、IEC 60076（系列）、
    IEC 60332-1（2004 年拆分）。27 項清單不變。
  * 7 月盲測：IEC 61373:2026 由正式 production 自行發現並走完 Search→Evidence→Scope→Temporal→Category→
    Taxonomy→Reportability，進入「規範及標準動態」（6 次付費呼叫）。
  * 15 個月離線重放只產生這一筆。
* RC-61（§A.45，使用者核定 Domain Rule）：監控標準只有其發行單位本身的變動才算更新：
  * 發行單位：IEC 編號為 IEC；EN 編號為 CEN／CENELEC；NFPA、ASTM、IEEE、UIC 各自。
  * 其他標準組織發布的採用版都不算該標準的變動，也不算第二次更新；即使採用版有自己的編號、日期、修正或勘誤也一樣：
    * 國家採用，如 BS EN、DIN EN；
    * 區域採用，如 CENELEC 以 EN IEC 61373 採用 IEC 61373。
  * 根因：使用者 2026-11-05 的決定（Q3）只記在未生效的草案，契約、Scope 提示詞與 Golden MS09 仍寫「含國家採用」。
  * 修正：Scope 提示詞改為 v2，schema、Python 檢查與其他 owner 都不變。
  * Golden：MS09 的預期改為不是監控變動；新增 MS16（CENELEC 修正 EN 50122-2，成報）、MS17（BSI 採用版）、MS18（CENELEC 區域採用版）。
* RC-62（§A.46，使用者核定 Domain Rule）：監控編號採精確擁有：
  * 每個監控編號只擁有自己的編號。
  * 系列編號擁有哪些分部，只由 `monitored_standards.json` 的 `family_coverage` 明定，不得由前綴或編號推導。
  * 已單獨列出的分部（IEC 60076-11、EN 50122-2）擁有自己，上層編號不得再擁有。
  * 目前尚未定義任何系列，IEC 60076、IEC 60332-1、EN 50122、EN 50126 的涵蓋範圍待使用者決定；在此之前這四項只擁有本身編號，不會產生更新。
  * 根因：§A.42 的比對規則允許「分部」跟在編號後，等於由編號推導涵蓋範圍；Scope 的兩處判斷都用它，因此上層編號可能擁有分部。
  * Search、目錄紀錄、提示詞、其他 owner 皆不變。
  * Golden：新增 MS19（IEC 60076-5）、MS20（IEC 60332-1-2），兩者都不是監控變動。
  * 系列成員除「單一、明確擁有」外沒有機構或編號條件；設定的編號必須能以自己被找到，否則設定失敗。
  * 系列涵蓋現況（2026-11-06，說明文件，不是 production 狀態）：四項都沒有權威依據可定義系列，`families` 維持空的、fail-closed，不另設任何機制：
    * 發行單位的結構只有：IEC 60076 的約 20 個分部與全分部 SER 套組、IEC 60332-1 於 2004 年拆分、EN 50122 的 -1／-2／-3、EN 50126:1999 由 -1／-2 取代。
    * D1 不承認以上任一項為涵蓋（系列預設全涵蓋、編號、拆分或後繼）；repository 與 V1 字面都未記錄原意。
    * 最早根因：清單未載明這四項的產品範圍，只能由清單擁有者決定。
    * EN 兩項另受 CEN-CENELEC robots 限制（只靠新聞）。
    * Golden MS21（EN 50126-1）、MS22（EN 50122-1）只鎖定既有 D1 結果，補齊四項的鎖定。
    * 套組（2026-11-06 解決）：IEC 定義 SER（Series）為包含某標準全部官方出版品與 VAP（即全部分部）的組合包，不是標準。依 §A.42（只算標準本身的正式變動）與 D1，其新版不是該編號的變動。比對時帶 SER 的編號沒有擁有者，套組內的分部只透過自身擁有者監控。依據：IEC 官方 value-added products 頁的 SER 定義與「IEC 60332:2026 SER」紀錄。OC 沒有 IEC 定義，不特別處理，依一般精確擁有。Golden MS23、MS24。
  * 使用者決定：編號最後的「-四位數」可視為版次年份；先比對完整、明確設定的編號，只有完整編號沒有擁有者時才視為年份（如 IEC 61373-2010 即 IEC 61373）；去掉年份不會產生涵蓋，分部仍須有自己的擁有者；不設年份範圍或機構條件。
* RC-63（§L 邊界澄清，2026-11-06）：Category 只依 §L 既有定義，不新增類別：
  * 技術新知：研究、原型、試驗、測試或部署的對象必須是技術、方法或材料本身。動土、場地準備、施工進度、軌道或設備安裝、通車前或試運轉測試、驗收測試與檢查是建設與通車的步驟，不是技術新知。在路線上試行或部署一項技術仍是技術新知（G49、G64、G84）。
  * 營運動態：指客運服務本身，車站內非運輸的設施或服務（如診療亭）不算。
  * 採購事件：須是已發生的正式採購行動，預計或未來的招標、評選或決標不算。
  * 計畫與核准、路線或用地、拆遷安置、施工階段、通車前測試、運量統計或紀錄、排名、預告的通車或招標，五類都不涵蓋，為 CATEGORY_UNRESOLVED（NO_CATEGORY_DEFINING_ACTION），除非 Evidence 顯示另一個已列出的主要行動。
  * 根因：Run 42148605765 的分類提示詞只寫「pilots, experiments, applied technical tests」，未說明對象須是技術，也未說明建設步驟與統計沒有分類行動；技術新知 4 則全是建設步驟，另有拆遷計畫被分為採購、運量紀錄與車站診療亭被分為營運動態。
  * 修正：分類提示詞 v4（`_CATEGORY_GUIDANCE` 唯一來源），schema、Python 驗證與其他 owner 不變。
  * Golden：另立 `category_boundary_manifest.json`（G92～G96），不動已鎖定的 Category 母體與封存驗收。
  * RC-64（R7 量測）無效：語料取自 audit highlights，不是 Event Identity 實際輸入（`rc64_r7_measurement.json` 標為 INVALID）。
  * RC-65：Scope 提示詞 v13，事件焦點須含陳述發生事項的句子；分類提示詞 v5（營運治理只針對已營運的服務）；Golden G97、G98。
* RC-66（§A.47，2026-11-07 夜間離線檢討，無付費呼叫，未經 Live 驗收）：
  * Category 提示詞 v6：技術新知只有一個定義（對象是技術、方法或材料本身）；分類只適用於其定義列出的主要行動。
    * 訓練、演練，以及關於技術的會議、交流、展覽都不是技術新知；依既有規定的處分不是規範變動。
    * 已安裝系統的通車前或驗收測試仍是專案步驟。
    * 車上的非運輸服務不是營運動態。
    * subtype 須以英文字母開頭。
  * Category 提案違約時，技術缺口簽章寫出失敗的檢查（只作觀測）。Golden G99～G101。
  * Validator：以中黑點連接的數字沒有讀法，不作依據。
  * Scope 被拒提案的 ID 形狀記入 selection audit v3（不含原文，不參與決策）。
  * Event Identity 確認階段的一般問題已證明；R7 量測包已備妥（`acceptance/event_identity/RC66_R7_MEASUREMENT_PACKAGE.md`）。
  * 未決：
    * 演練的分類、仁川 L1、歷史回顧的 Domain Rule：BLOCKED_USER_DECISION。
    * 「広島市」名稱：未修。
  * Phase B 跨 run 稽核（REPORT §72，矩陣在 `acceptance/phase_b_audit/`）：
    * 確認階段的過度拆分有五種機制，R3 混合紀錄只是其一；R7 量測包已補對抗性設計。
    * Scope 缺口在同一 Evidence 上不重現（機率性）。
    * DATE_PROVENANCE_INVALID 依 host 而定、每次相同。
    * 契約 §L（RC-63 專案步驟無分類）與 §N（施工或通車屬報導價值路徑）互相矛盾，待使用者決定。
  * Phase C 輪替稽核（REPORT §73；決策彙整於 `acceptance/USER_DECISION_PACKAGE.md`）：
    * 依既有規則修正：geo-reference-v5、Writer v9（韓日文來源的共用幣別詞寫成符號）、Validator 讀出 미국 달러、Writer v10（保留的韓文原名以「」隔開）。
    * 新證據：主文件判定在 175 個網站中有 160 個每頁都失敗（含 Yonhap 與刻意搜尋的專業軌道媒體）；DPI 為整站失敗，至少 22% 的頁面有可見日期列。
* RC-67（§A.48，使用者決定 2026-11-16，解決 D1、D2）：
  * 根因：排程 Run 43791549550（11-09～11-15，main，分類提示詞 v3）12 則中 6 則不應成報或分類錯誤：
    演練被列為技術新知、經費申請被列為技術新知、通車延期被列為採購、工程進度與運量紀錄被列為營運動態；
    同一系統出現兩則內容重疊的項目（大邱 3 號線：演練＋障礙專題重述該演練）。
  * D1（使用者：依專業判斷，且確認不適合技術新知）：專案步驟一律無分類、不成報。§L RC-63 成立；
    另明列經費或預算申請與決定、成本增加、施工進度、通車日期的變更或預測（延期、新目標日期）。
    §N「路線、延伸段或車站的通車或施工」價值路徑只剩實際通車（`OPERATIONAL_CHANGE`）可達；
    Reportability 的 `CONSTRUCTION_MILESTONE`、`DELIVERY_TEST_OR_COMMISSIONING` 不再可達，保留以免改 schema。
  * D2（使用者：演練不列入週報）：演練、訓練、預演（含消防、疏散、救援演練）在任何 Category 下都沒有分類行動，
    回 `CATEGORY_UNRESOLVED`／`NO_CATEGORY_DEFINING_ACTION`；除非 Evidence 另報導一件真正的事故。
  * 分類提示詞 v7（`_CATEGORY_GUIDANCE` 唯一來源）；schema、Python 驗證與其他 owner 不變。
  * Writer 提示詞 v11：來源重述多件事（舊障礙、演練、其他工程步驟）時，標題、摘要、啟示只寫 event_focus 那一件，
    其他事件不得列舉、計數或摘要，即使當背景也不行。
  * Golden：G102 演練、G103 經費申請、G104 通車延期（皆 `NO_CATEGORY_DEFINING_ACTION`），置於 `category_boundary_manifest.json`。
  * 使用者另決定「同一路線／計畫同一期多則不同事件合併成一則」：需新的報告項目 owner（不屬 Event Identity，因不是同一發生事項），
    設計待下一階段（BLOCKED_ARCHITECTURE_EXPANSION，需另行核准設計）。
  * 分支清理（使用者決定）：保留 Claude 的 RC-63～RC-66（原 `release/report-quality-wip` 前段），其餘 CODEX 分支刪除；main 保留。
* RC-68（§A.49，2026-11-17，受控 Run 43995345298）：分類錯誤皆出自 Classifier 的 CATEGORY_ASSIGNED（章節依 CategoryId 固定投影）：
  * 羅馬新交付電車的界限與電磁相容測試列為技術新知：驗收測試只綁「路線、車站或機廠通車前」，已營運路網上新車的驗收未涵蓋。
  * 里昂 T10 未通車路線的號誌測試列為營運動態：來源提到施工影響既有路線，helper 把結果當成主要行動。
  * 東京 Metro 營運列車的軌道監測裝置、仁川全列車 5G Wi-Fi 列為營運動態：營運動態的「營運方式改變」「服務啟用」未限定；G101 與 RC-66 本已要求技術新知。
  * 貝加莫在 Evidence 階段（LINK_RESOLUTION）就掉件，未到 Category；適用通車前測試規則（G93、G100）。
  * 分類提示詞 v8（`_CATEGORY_GUIDANCE` 唯一來源；不新增類別或 Domain Rule）：
    * 新交付車輛或設備進入客運服務前的界限、相容、驗收、型式或認證測試是專案步驟，已營運路網亦同；新技術本身的試行仍是技術新知。
    * 技術投入使用即使改變維修、檢查方式或提供車上 Wi-Fi 等設施，仍是技術新知；新路線、延伸段或車隊開始載客仍是營運動態。
    * 依來源報導的事件分類，不依其結果；專案步驟對營運路線的影響不是另一個主要行動；服務變更本身是新聞（停駛或時刻公告）時才是。
  * Golden G105～G109（`category_boundary_manifest.json`）；schema、Python 驗證與其他 owner 不變；Live 驗收待受控 Run。
* RC-69（§A.50，2026-11-18，使用者核准，只作觀測）：Lyon T10、Sydney M1 的 Category 判定無法追溯（helper 提案、引用句、subtype 原值與送出的 action_facts 皆未保存）。
  * Classifier 在決策確定後於既有出口產生 `category_exchange` 紀錄：被接受者放在 `CategoryResult.provenance`，違約、helper 無效回應或技術失敗者附在同一個例外物件上；
    ReportApplication 只搬運（`category_gap_exchanges`），只有 selection audit（v4）讀取並投影到 `events[].category_exchange`。
  * 所有路徑共用一個 schema：語意請求指紋與版本、guidance 雜湊、各來源 `content_sha256`、action_facts、提案列舉值與 subtype 原值、引用句 ID、驗證結果（ACCEPTED／REJECTED／NO_PROPOSAL 與 predicate）。
  * 觀測失敗只顯示 PARTIAL／UNAVAILABLE，不改變 Category 結果、技術缺口、報告或結束碼。
  * 公開曝露（repository 與 artifact 為 public）：只放 ID、雜湊、白名單內的列舉值、版本識別字、通過 subtype 規則的 subtype 原值，
    以及通過規則的短 action_facts 值（目前只有城市；可能是來源文字的短片段，但不會是完整句子或文章本文）；
    不放完整句子、guidance 文字、provider 回應、chatbot ID、API base 或憑證；控制、格式（零寬、bidi）字元與非一般空白一律隱藏；
    不合規的值只留雜湊（請求輸入被隱藏時標 WITHHELD）。
  * 上限：builder 與 audit 共用同一個長度量法（緊湊 JSON），builder 上限 16,000－128，audit 上限 16,000，超過者整筆改為 UNAVAILABLE（SIZE_BOUND）；
    技術缺口沒有附帶紀錄時顯示 OBSERVATION_NOT_ATTACHED。
  * 重放術語：指紋與版本相同且未隱藏任何值，只算 input-equivalent semantic replay；模型識別與推論參數無法觀測，exact replay 目前不可達成；provider 非確定性仍存在。
  * 分類提示詞 v8、schema、Golden 預期與報告輸出皆不變。
* RC-70（§A.51，使用者決定 2026-11-19）：
  * 根因：Run 44429652572（07-01～11-19，55 則）事故章節 25 則中約 10 則是電車與汽車、卡車、巴士或行人的路口碰撞。
  * 決定：電車／輕軌與道路使用者的碰撞，只有 Evidence 報導列車出軌才成報；只有受傷、死亡、損壞、停駛或警方調查都不成報。
    營運者或主管機關因此採取的軌道安全措施，另依其他價值路徑判斷。
  * 決定：有人被列車撞擊或進入軌道（闖入、自殺或企圖自殺、從月臺跌落或跳下）屬人為因素，即使有死傷或停駛也不成報；
    只有 Evidence 明載原因在軌道系統本身才成報：設備失效（號誌或列車控制、月臺門或車門故障）或人員操作失誤（司機員、行控、站務）；不得推測原因。
    事故價值路徑的例示移除「track intrusion」。
  * Reportability 提示詞 v8；schema、Python 驗證與其他 owner 不變。
  * 只作觀測：`scripts/source_host_probe.py` 與手動 `source_probe` workflow 輸入，以 EvidenceService 自己的抓取與主文件判定
    列出專業軌道媒體（Railway Gazette、Railway PRO、Railway-News、Mass Transit、IRJ 等）的失敗原因與頁面 HTML；
    本期約 75 筆專業媒體候選全部在 Evidence 或 Temporal 階段掉件。不呼叫 MaiAgent、不參與決策。
* RC-71（§A.52，2026-11-19）：RC-70 的來源探測（Run 44450962940，只跑 `source_probe`）還原專業媒體頁面後，確認三種結構原因使主文件判定失敗，修正在 EvidenceService 的結構判定（`evidence_document.py`，只用結構關係，不用出版者、class 名稱、用語或文字相似度）：
  * 只有一篇主文章時，不包含它也不在它之內的集合是主文件之外的相關文件，不再使頁面成為清單；包含或位於文章內的集合仍計入。
  * 同一個 title、og:title 或 twitter:title 值重複出現只是同一事實，不是衝突；值不同仍為衝突。
  * 判定同層通用單元時，只含連結、表單與互動控制項的文字不是內文，文章內的訂閱表單或分享區塊不再是競爭的文件單元。
  * schema.org JSON-LD 區塊在 `<body>` 而非 `<head>` 時（Global Railway Review 三篇舊文章 `DATE_PROVENANCE_INVALID` 的原因）也會讀取；只有實體自己的資源身分指向本頁才產生日期事實，所以位置不是歸屬依據，排除區域（導覽、側欄、頁尾、留言）內的區塊仍忽略。
  * 使用者提議的「只含連結的區塊其 `<h1>` 不是文件標題」已試作：解決「You May Also Like」但不解決「Related」（區塊內還有每則連結旁的公司名稱），未採用；放寬「連結旁短標籤」的方向由使用者排除。
  * 使用者決定（2026-11-19）：多個 `<h1>` 競爭時，以出版者自己的結構化資料指定文件標題，條件全部成立才採用，否則維持 ambiguous：頁面上只有一個 JSON-LD `Article`／`NewsArticle` 實體；它宣告的所有資源身分（`@id`、`url`、`mainEntityOfPage`）都是本頁；它的 `headline` 只正規化空白後與頁面上「恰好一個」`<h1>` 的文字完全相同，且該 `<h1>` 是主要候選之一。成立時其他 `<h1>` 不競爭也不成為文件標題；只比對相等，不做模糊比對或相似度；集合與文章規則先判，列表頁仍是 ambiguous。已知限制：區塊內有非連結標籤時，短文字仍可能留在本文尾端。
  * `rail_trade_press` 的 `site:` 清單（使用者決定）：移除 Railway PRO、Railway Gazette、IRJ（該次 44 筆全部 `FETCH_TRANSPORT`）與兩個只轉址的網域 railtech.com（轉到 railwaygazette.com）、intelligenttransport.com（轉到 globalrailwayreview.com）；加入 railway.supply、railtechnologymagazine.com；不加 uktram.org。查詢刻意不加意圖詞（作為廣泛來源），契約 §A.6 原本「carrying the new-technology priority」的說法與模板不符，已改正；仍為 2 次請求。
  * 未改（外部）：Railway PRO、Railway Gazette、IRJ 對任何請求皆由 CDN 回 403，RSS 也是 403 或無全文，不繞過。
  * 探測現在傳入與 EvidenceService 相同的來源身分檢查，並列出各頁面日期相關標記；先前探測的「無日期事實」是探測本身的缺漏。
* RC-72（§A.53，使用者決定 2026-11-19）：Google News 六探針健康檢查改為「至少 4 個成功，且失敗的全部是
  `RATE_LIMIT`（HTTP 429）」才 PASS；任何非限流失敗（連線、逾時、無法解析、非 429 的 HTTP 錯誤）仍為 FAIL，
  不論成功幾個。未達標時等 45 分鐘（2,700 秒）整組 6 個重跑一次，第二次仍未達標才失敗並揭露兩次結果；沒有第三次。
  唯一 owner 為 `production_runner.GoogleNewsHealthCheck`（`run` 判一組、`run_gated` 加唯一一次重試），所有入口共用；
  只觀測可用性，不決定任何 Domain 結果。另新增手動的召回測試：workflow 輸入 `recall_periods`
  （`起:迄,起:迄`，最多 8 組）與 `recall_wait_first`，`recall-test` job 以 matrix 依序跑（`max-parallel: 1`、
  `fail-fast: false`），第一組之後每組先等 3,600 秒（`recall_wait_first` 時第一組也等），各組使用同一個正式 CLI 與
  RC-72 健康檢查；job 寫死 `LIVE_EMAIL_SEND=0` 且不傳入 SMTP、收件者與交付紀錄 secrets，不可能寄信；每組把報告
  Markdown 與全部候選（標題、出版者、最終階段、終止原因、分類）印到 log，artifact 名稱帶期間。Delivery、報告週期、
  排程與 production job 不變。
* RC-73（§A.54，使用者決定 2026-11-19）：`concurrency`（group `weekly-report-production`、`cancel-in-progress: false`）
  由 workflow 層移到 `production` 與 `recall-test` 兩個 job（同一 group），其餘 job（`source-probe`、`delivery-check`、離線閘門、
  召回計畫）不再排在長時間召回測試之後；兩者之間仍不重疊。不改任何 Domain 規則。
* RC-74（§A.55，使用者決定 2026-11-19）：TemporalRule 的來源日期事實接受英文月份（縮寫或全名）加可帶序數的日與四位數年
  （`Nov 12th 2026`、`November 12, 2026`、`12th November 2026`），只改解析；缺年、不存在的日、帶時間、純數字斜線寫法仍為
  `DATE_UNPARSEABLE`；日期歸屬、衝突與期間邊界（仍只收 ISO）不變。`rail_trade_press` 移除 railtechnologymagazine.com
  （頁面沒有任何日期標記）。輪播含自己那張卡片使主文件判定模糊，記為已知限制，不修。
* RC-75（§A.56，使用者決定 2026-11-19）：Scope 兩項。C：焦點已確定時，`target_system` 關係可引用焦點外、同一文件的句子，
  條件是 (a) 動作—目標關係成立且在焦點內，(b) 系統關係的目標標籤與該動作—目標關係的目標標籤相同（`target_reference`
  省略或相等），(c) 每個焦點外的引用句本身含該目標標籤，且引用句合起來含系統標籤；其餘關係與事件焦點本身不變，取代
  RC-17 對這一種關係的限制。(c) 是使用者當日加嚴的決定：(a)(b) 只比較同一提案的兩個關係，無法證明該句描述同一事件，
  加上 (c) 才保留 RC-17「不得借用另一事件」的保證，守護測試維持原預期（cargo monitors 案必須被擋下）；召回成本由
  E 補（以 Run 44462316932 的九筆形狀離線估計，只加 (a)(b) 可救回五筆，加 (c) 只救回一筆）。
  E：Scope 提案違反有明訂規則的契約條件時，送一次更正請求
  （`correction`：違約條件、違約欄位、規則文字、helper 自己被拒的提案），更正後仍違約才是技術缺口；不是 RC-6 傳輸重試，
  run summary 另計 `scope_correction_requests`／`scope_correction_accepted`，selection audit 記 `scope.correction`
  （只有條件、欄位名稱與結果）。Scope 提示詞 v13、schema 不變；月檢標準請求不更正。
* RC-76（§A.57，使用者決定 2026-11-19，修訂 RC-28 鎖定的名單）：指定國家／地區由 20 個增為 27 個，原則是技術先進國家；
  中國大陸不列入、香港保留；新增芬蘭、比利時、捷克、以色列、愛爾蘭、波蘭、紐西蘭。搜尋設定 `search-discovery-v11`：
  比利時 nl＋fr、捷克 cs、以色列 he＋en、波蘭 pl、愛爾蘭與紐西蘭 en；新增 `fi`、`cs`、`pl`、`he` 四個 profile（共 17 個，
  詞彙比照既有 profile，含七個技術概念）。芬蘭比照丹麥：binding 為 UNSUPPORTED、計畫中是公開的 coverage gap，召回測試後
  各送 1 次 FI:fi 與丹麥請求驗證，有版本就改 SUPPORTED。週計畫 140 → 196 次，補運具詞變化形後為 210 次（月檢多 87 次標準查詢，原 63）；健康檢查探針
  依慣例改為 (1, 10, 105, 110, 203, 210)，RC-72 規則不變；run summary 一律記錄 `search_rate_limit_failures`（含 0），
  429 明顯變多時先回報使用者再考慮查詢間隔。地理參照表 `geo-reference-v6` 補七國城市與系統的各語言名稱（與其他地名
  重名者不列）。測試另鎖定「中國大陸地點仍為 NON_DESIGNATED_REGION、香港為指定地區」。
  運具詞補變化形（使用者決定，標題必須含運具詞）：cs、pl、fi 各補同一詞的格變化，he 補 הרכבת הקלה、ברכבת הקלה、המטרו、
  הרכבת התחתית；特拉維夫線名（紅線、紫線、綠線）不加，因 he 運具詞組會佔滿 32 字查詢上限，且 הקו האדום 也是政治「紅線」慣用語
  （RC-14 同類）。另修 cs 得標詞（vítěz tendru、zakázku získala）與招標詞（tendr、soutěž）、he 驗票機（מתקף）與 חשמול、
  fi ajovirta。週計畫因此為 210 次，探針 (1, 10, 105, 110, 203, 210)。
* RC-77（§A.58，使用者決定 2026-11-19）：
  * 取捨原則：以對臺北捷運局的參考價值評星，★★★ 以上全收、★★ 收但只能在營運動態或事故章節、★ 不收；
    只作為召回標準答案的尺度，本身不新增 Reportability 或 Category 規則。
  * 標準答案 `acceptance/gold/recall_v1.json`：召回測試 Run 44468386445 的 17 則（期間、標題、星等、預期收／不收、
    預期章節；#15 併 #11、#16 併 #14），內容同專案文件「週報取捨規則與標準答案」。`scripts/recall_score.py`
    以任一次 selection audit（或召回測試 job log）比對，輸出收錄準確度、漏收、章節錯誤、誤收、重複數與標準答案外的
    新收錄；章節取自 ReportService 的 `FORMAL_REPORT_SECTIONS`，不重算任何決策。召回測試 log 另以 `AUDIT_B64` 行
    印出 gzip+base64 的 selection audit，無法下載 artifact 也能還原。
  * Reportability 低價值新增：沒有服務變更、沒有事故、沒有技術內容的日常營運報導（如惡劣天候下照常營運）為
    NOT_REPORTABLE；停駛、減班或改變服務、事故、安全措施仍依原價值路徑。提示詞 v9，schema 與 Python 不變。
  * 搜尋詞 `search-discovery-v12`：17 個語言的技術詞補 AI 類詞（AI；fr／es／it／pt 用 IA；de／no 用 KI；fi 用
    tekoäly；另加完整詞），fr、it 不用單獨的 AI（為一般用字）；「保守／維修」「遠端監測」「感測器」類一般詞只在不因此
    增加請求時補上（ko、es 無空間）。週計畫 210 → 221（en、zh、cs 各市場多一次技術請求），健康檢查探針隨之為
    (1, 10, 110, 115, 214, 221)，RC-72 規則不變。
  * 地名參照表 `geo-reference-v7`：Frankfurt 原列於 ambiguous_names（兩個 Frankfurt 都在德國），且缺形容詞
    Frankfurter；Kitchener（ION LRT）未收錄；西班牙只有 Vitoria-Gasteiz、沒有 Vitoria／Gasteiz。已補上並把 Frankfurt
    移出歧義名單；Waterloo、Victoria 仍為歧義；比對規則不變。
* RC-78（§A.59，使用者決定 2026-11-19、驗證 2026-11-20）：召回測試跑完後各送 1 次請求（不跟隨轉址）。`FI:fi` 回 302 轉到同一版本的
  `hl=fi-FI`，芬蘭版存在；`DK:da` 回 302 轉到挪威版，丹麥沒有 Google News 版本。芬蘭 binding 改為 SUPPORTED
  （`fi-FI`／`FI`／`FI:fi`），不再是 coverage gap；丹麥維持 UNSUPPORTED，是唯一的 coverage gap。`search-discovery-v13`：
  週計畫 221 → 231 次（芬蘭 10 次），月檢標準查詢 87 → 90 次；健康檢查探針 (1, 10, 115, 120, 224, 231)，RC-72 規則不變。
  正式執行不跟隨轉址，RC-76 其餘八個版本代碼未另行請求，首次正式執行即可看出是否回 200。

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

Automation retry 不得造成同一正式 artifact 重複成功寄送；RC-55（§A.39）以 private repository 的逐人交付紀錄
防止同一期間對同一收件者再次交付，ATTEMPTED 與 SENT 皆擋下再次寄送。

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
CONTRACT_REVISION = RC-3..RC-78 (2026-11-20; RC-78 Finland's Google News edition verified and searched, Denmark the only edition gap, search-discovery-v13; RC-77 recall gold answer and score tool, routine operations NOT_REPORTABLE (Reportability prompt v9), AI search terms search-discovery-v12 (221 weekly requests), geo-reference-v7 (Frankfurt, Kitchener, Vitoria); RC-76 designated regions 27 (CN out, HK in), search-discovery-v11, geo-reference-v6; RC-75 Scope system relation may leave the focus under three conditions, and one correction request per violated proposal; RC-74 named-month source dates and trade-press site list; RC-73 workflow concurrency moved to the production and recall-test jobs; RC-72 Google News health gate: at least 4 of 6 probes succeed with only RATE_LIMIT failures, otherwise one 45-minute wait and one full re-run, plus the email-free recall-test workflow; RC-71 principal-document detection: related collections outside the single article, repeated identical headline metadata and interactive widgets no longer make a page ambiguous, evidence_document.py only; RC-70 user decisions: a road collision is reportable only with a derailment, a person struck only with a stated rail equipment failure or staff operating error, Reportability prompt v8, observer-only source host probe; RC-69 observer-only Category exchange record, selection audit v4; RC-68 Category prompt v8: delivery acceptance tests, deployments and consequences; RC-67 user decisions D1/D2: project steps and drills have no Category, Category prompt v7, Writer v11; RC-66 offline review: Category prompt v6, numeric middle dot, Scope rejection observation, Event Identity R7 package; RC-64 measurement invalid; RC-65 Scope v13; none Live-accepted; RC-63 Category boundary clarification, prompt v4; RC-62 exact ownership of monitored identifiers, family coverage pending; RC-61 adoption by another body is not a monitored change; RC-60 official standards catalogue provider, phase 1 10/27; RC-59 monthly monitored-standards check with a narrow Scope/region basis; RC-57 normative discovery intent, superseded in part by RC-58 monitored standards; RC-51 reverted; RC-53 measured, not adopted; RC-54 observation only, no contract text; RC-55 wired and live-accepted (L1-L3 PASS); RC-56 reporting week, schedule and subscription applied; RC-56 go-live gate satisfied by controlled canary Run 41765559889)
```
