# Phase A 真實整合驗收報告

- 執行日：2026-10-20
- HEAD：`ccec80b8871a910dc165c9e87b23fde9b0b2e304`（production code 未修改）
- 報告期間：2026-10-12 ～ 2026-10-18
- 樣本：[manifest.json](manifest.json)（20 筆）
- 預期結果：[expected_outcomes.json](expected_outcomes.json)（於執行前登錄）
- 原始紀錄：[runs/live1/summary.json](runs/live1/summary.json)、[runs/live1/trace.jsonl](runs/live1/trace.jsonl)
- 驗收腳本：[scripts/phase_a_acceptance.py](../../scripts/phase_a_acceptance.py)（test-only）

## 1. 三個問題的答案

| 問題 | 結論 | 依據 |
|---|---|---|
| V2 能取得國際捷運新聞原文嗎？ | **能（直接網址時）** | 發布者直接網址 18 筆中 16 筆取得 HTTP 200，中位數 1.1 秒。Google News 連結 2/2 只取得 Google 中介頁。 |
| 能產生 Evidence READY 嗎？ | **能，但比率過低：正向樣本 3/14**（目標 ≥10/14 → FAIL） | 9 個頁面因結構判定規則被誤拒；應拒絕的 3 個對照組全部正確拒絕。 |
| 能在合理時間內形成可信的正式報告嗎？ | **時間可以，報告不行** | 總耗時 144 秒，但唯一存活的事件缺少 country，**整個 run 中止，沒有任何 artifact**。Writer 與 Validator 未執行，factual grounding 品質無法量測。 |

## 2. 預算使用

| 項目 | 用量／上限 |
|---|---|
| 策展瀏覽頁面載入 | 59 / 80 |
| Evidence HTTP 請求 | 22 / 80 |
| MaiAgent 呼叫 | 19 / 160 |
| 時間 | 144 秒 / 2,700 秒 |
| Email | 0 封（`LIVE_EMAIL_SEND=0`，未設定收件人） |
| Search 網路請求 | 0（449 個 plan item 全部以離線 replay 回應） |

MaiAgent 請求合計約 186 KB、回應約 46 KB，約 6 萬 token，費用可忽略。

## 3. 各階段實測

| 階段 | 輸入 → 輸出 | 耗時 | MaiAgent 呼叫 |
|---|---|---:|---:|
| Search（replay） | 449 個 item → 20 筆 | 0.02 秒 | 0 |
| Evidence | 20 → READY 5 | 109.8 秒 | judge 6、metadata 5 |
| Scope | 5 → IN_SCOPE 1 | 24.3 秒 | 5 |
| Temporal | 1 → DATE_VALID 1 | 0 秒 | 0 |
| Event Identity | 1 → 1 個事件 | 0 秒 | 0 |
| Category | 1 → INCIDENT | 3.1 秒 | 1 |
| Taxonomy | 1 → 無七大系統 | 2.8 秒 | 1 |
| Reportability | 1 → REPORTABLE | 3.7 秒 | 1 |
| FormalMetadata | **FAILED：MISSING_COUNTRY → 整個 run 中止** | — | — |
| Writer、Validator、Assembly | 未到達 | — | — |

**MaiAgent 實測：**
- 18 次 HTTP 200，延遲中位數 3.2 秒、最大 6.7 秒。
- 1 次 45 秒 timeout。
- 1 次回應格式錯誤：回傳兩個 JSON 物件。

## 4. 逐筆結果（對照預期）

| Slot | Evidence | 之後的結果 | 與預期比較 |
|---|---|---|---|
| P01 溫州（66wz） | FETCH_TRANSPORT（10 秒 timeout） | — | 策展時已標示 AT_RISK；瀏覽器也無法連線 |
| P02 Hitachi S-bane（RG） | PRINCIPAL_DOCUMENT_AMBIGUOUS | — | **誤拒** |
| P03 埃及氫能電車 | PRINCIPAL_DOCUMENT_AMBIGUOUS | — | **誤拒** |
| P04 香港電車出軌（英） | READY | Scope：QUOTE_NOT_FOUND → OUT_OF_SCOPE；country 缺 | **誤判**（電車屬適用範圍） |
| P05 紐約地鐵槍擊 | READY | IN_SCOPE、DATE_VALID、INCIDENT、REPORTABLE → MISSING_COUNTRY | 預期 NOT_REPORTABLE |
| P06 Croydon 電車安全 | PRINCIPAL_DOCUMENT_AMBIGUOUS | — | **誤拒** |
| P07 St Louis MetroLink（全文） | PRINCIPAL_DOCUMENT_AMBIGUOUS | — | **誤拒** |
| P08 Chennai | PRINCIPAL_DOCUMENT_AMBIGUOUS | — | **誤拒** |
| P09 首爾 9 號線（韓） | SEMANTIC_MATCH：judge **timeout** 被當成內容拒絕 | — | **技術失敗被當成內容判斷** |
| P10 København O&M | PRINCIPAL_DOCUMENT_AMBIGUOUS | — | **誤拒** |
| P11 ADB Baku 號誌 | HTTP 403（擋 bot User-Agent） | — | 取得失敗 |
| P12 利雅得 94 列車（SPA） | SOURCE_PROVENANCE：canonical 指向首頁，且內容由 JS 渲染 | — | 策展時已標示 AT_RISK |
| P13 港北環支線 | PRINCIPAL_DOCUMENT_AMBIGUOUS | — | **誤拒** |
| P14 河內 5 條地鐵 | READY | Scope：QUOTE_NOT_UNIQUE → OUT_OF_SCOPE；metadata 無效 | **誤判** |
| C01、C02 Google News 連結 | SOURCE_PROVENANCE | — | 符合預期（R1 A/B：同一文章直接網址可以取得） |
| C03 Delft（期間外） | PRINCIPAL_DOCUMENT_AMBIGUOUS | 未到 Temporal | 對照組沒有發揮作用 |
| C04 Network Rail（幹線） | READY | OUT_OF_SCOPE（NON_ELIGIBLE） | **符合預期** |
| C05 香港電車出軌（中） | READY | Scope helper 回應格式錯誤 → OUT_OF_SCOPE | **技術失敗被當成內容判斷** |
| C06 列表頁 | PRINCIPAL_DOCUMENT_AMBIGUOUS | — | **符合預期** |

另外兩點：
- P04、C05、C04 都沒有任何 `source_date_facts`。香港政府新聞稿的日期寫在頁尾，格式是「Ends/Monday, October 12, 2026」。即使 Scope 通過，Temporal 也會把它們拒絕。
- C05 與 P04 的跨語言合併沒有被驗證到。

## 5. 根因（依 pipeline 先後排序，只列有實證者）

**RC-1　Google News 不透明連結（R1）：CONFIRMED（A/B 實證）**
- 同一篇 Railway Gazette 與 ADB 文章，直接網址可以取得原文，Google News 連結只得到 Google 的中介頁。
- 位置：discovery 來源策略。需要你裁決（Phase B）。

**RC-2　「多個 `<article>` → AMBIGUOUS」：實作違反既有契約**
- [evidence_document.py:987](../../src/weekly_report/evidence_document.py) 只要 `<main>` 內 `<article>` 超過 1 個，就判 AMBIGUOUS。
- 但 [EVIDENCE_STRUCTURAL_DOCUMENT.md §6](../../docs/EVIDENCE_STRUCTURAL_DOCUMENT.md) 明文規定：主文章加上可分離的相關文章仍然合格（第 136 行）；多個 `<article>` 不自動代表列表頁（第 406 行）。
- 影響：成功取得的發布者頁面中，8 篇正常文章被誤拒。Railway Gazette 與 Rail Business UK 頁面有 1 篇主文加 4 張「related」卡片；New Arab 用 `<article>` 包圖片。
- **修正不需要改契約**，屬於 EvidenceService 的結構判定。

**RC-3　Metadata「值必須在段落中恰好出現一次」：契約本身的規定**
- 契約〈Canonical exact occurrence resolution〉第 4 點寫明：出現超過一次就作廢整個 extraction。
- 實際文章通常只有 1 個本文段落，地名一定重複：河內文中「Hanoi」多次出現、「Vietnam」也是；紐約文中「New York」也重複。
- 結果：5 篇 READY 中 3 篇的 metadata 全部作廢。
- Scope 的 `QUOTE_NOT_UNIQUE`（P14）是同一類規則。
- **需要你裁決契約。**

**RC-4　Country 為必填，卻禁止由城市或世界知識推得：契約設計衝突**
- 紐約新聞全文不會出現「United States」；香港政府英文稿也不寫國家。
- 依現行契約，這類事件永遠無法成報。
- **需要你裁決**，例如：由 Python 維護、版本化的「系統／城市 → 國家」對照表，或讓 country 改為非必填，顯示「來源未載明」。

**RC-5　單一事件缺 metadata 就中止整個 run**
- `FormalMetadataFailure` 會往上拋出；整個 run 判為 APPLICATION_FAILURE，連 0 篇的 artifact 都沒有。
- 這與 AGENTS §12「單一 Event FAIL 只淘汰該 Event」及 §13「0 篇仍正常產生 artifact」的精神衝突。契約只寫「fail closed」，沒有說明粒度。
- **需要你釐清。**

**RC-6　MaiAgent 技術失敗被當成內容判斷**
- P09：judge 45 秒 timeout，結果變成 `SOURCE_PAGE_MISMATCH`。
- C05：Scope helper 回應格式錯誤，結果變成 `OUT_OF_SCOPE`。
- 依 AGENTS §12 的原則，技術失敗不應被當成內容 FAIL，但目前 Evidence 與 Scope 是默默拒絕。
- 是否允許 transport retry 需要你決定。

**RC-7　次要問題（列出但不優先處理）**
- 香港政府頁尾日期格式抽不到。
- User-Agent 被擋（ADB 403）。
- JS 渲染頁面（SPA）無法取得內容。
- canonical 指向首頁。
- 地鐵槍擊被判 REPORTABLE。
- Scope helper 引文與原文不一致（QUOTE_NOT_FOUND）。

## 6. 30 分鐘目標的實測參數

- 抓取：中位數 1.1 秒／頁。
- MaiAgent：中位數 3.2 秒／次。每個候選最多 3 次（約 10 秒），每個事件約 5 次（約 16 秒）。
- 一次 timeout 要 45 秒，約等於 14 次正常呼叫。
- 估算：循序執行時，約 100 個進入 judge 的候選加上約 30 個事件，就接近 30 分鐘。這仍只是推估，必須等 Phase B 量測每週候選數後才能確認。

## 6b. RC-2 修正（2026-10-20，離線驗證，未 commit）

**修改**
- [evidence_document.py](../../src/weekly_report/evidence_document.py)：只在原本「≥2 個頂層 `<article>` → AMBIGUOUS」的分支內，依結構關係排除兩類單元：
  - 整個單元是指向**其他資源**的超連結（被 `<a href>` 包住，或全部文字都屬於這類連結）。
  - 完全沒有文字內容的 `<article>`。
- 剩下恰好 1 個 → 作為主文件。剩 0 個且確實有被排除的連結單元 → 維持 AMBIGUOUS（列表頁）。其餘情況 → 維持 AMBIGUOUS。
- 不使用 class 名稱、片語、數量、位置或「取第一篇／最長篇」。

**測試**
- 新增 5 個 owner 測試。其中 2 個在舊碼上失敗、新碼通過；另外 3 個保護既有行為。
- 全套 913 passed；Golden 21 passed。

**封存頁面離線結果**

| 項目 | 修正前 | 修正後 |
|---|---:|---:|
| 結構通過、可進 Semantic Judge 的頁面 | 6 | 13 |
| 其中正向樣本 | 4 | 10（新增 P02、P03、P07、P08、P10、P13） |

- C03（期間外）現在能進入 Temporal，日期為 2026-10-06。
- C06 列表頁仍然正確地被判 AMBIGUOUS。

**仍未處理（不屬於 RC-2）**
- **RC-2b：** P06 被另一條規則 `duplicate_twitter_title_metadata` 判為 headline 衝突。
- **RC-2c：** 已修正（見下節）。
- 實際能否 READY 仍取決於 Semantic Judge，必須以 live 驗證。

## 6c. RC-2c 修正（2026-10-20，離線驗證，未 commit）

**修改**
- 只在沒有主 `<article>`、邊界退回 `<main>` 時生效。
- 排除「整段文字全部是指向其他資源的超連結」的最大區塊；這類區塊是對其他文件的引用（§8）。
- 遇到自己直接擁有非連結文字的元素就不再往下判斷，所以本文中的行內連結會保留。連到同一資源或頁內錨點（`#`）的連結也保留。

**測試**
- 新增 4 個 owner 測試。其中 1 個在停用此規則時失敗；另外 3 個是保護既有行為（行內連結、同資源連結、只有連結時不成立本文）。
- 全套 917 passed；Golden 21 passed。

**封存頁面離線結果**
- P03 本文從 4,200 字元降為 3,172 字元，其他新聞的標題全部移除。尾端只剩欄目、作者等標籤，不含其他事件的事實。
- C04 只移除兩個主題標籤連結。
- 其餘頁面的本文不變。各頁結構判定結果與 RC-2 後相同（13 個 ESTABLISHED；C06、P06 為 AMBIGUOUS）。

## 7. 判定

```text
PHASE_A_RESULT = FAIL（第一次真實整合）
EVIDENCE_ACQUISITION_DIRECT_URL = PASS（16/18）
FALSE_READY_ON_CONTROLS = 0（PASS）
POSITIVE_READY = 3/14（FAIL，目標 ≥10）
FINAL_REPORT = 未產生（run 中止於 FormalMetadata）
GROUNDING_QUALITY = 未量測（Writer／Validator 未到達）
RUNTIME = 144 秒（20 筆）
```


## 8. RC-3～RC-6 修訂後重新驗收（live2，2026-10-20）

- 原始紀錄：[runs/live2/summary.json](runs/live2/summary.json)
- 用量（不含 live1）：HTTP 22、MaiAgent 62、耗時 411 秒。Phase A 累計：HTTP 44/80、MaiAgent 81/160、時間 555/2700 秒。
- 未寄信；未執行任何 Search 網路請求。

| 指標 | live1 | live2 |
|---|---:|---:|
| Evidence READY（正向 14 筆） | 3 | 10 |
| 對照組錯放 | 0 | 0 |
| IN_SCOPE | 1 | 4 |
| REPORTABLE 事件 | 1 | 4 |
| Writer 完成 | 0（run 中止） | 4 |
| Validation PASS | 0 | 0（4 筆 Validator 技術缺口） |
| 正式 artifact | 無 | 有（0 篇＋執行說明；狀態 `SUCCESS_WITH_TECHNICAL_GAPS`） |

**目前最早的實際 blocker：Validator 語意檢查 helper 的輸出契約。**
- 2 件 `TEXT_COVERAGE_INVALID`：helper 重抄 Writer 文字時漏掉單元間的標點（，；。），無法逐字還原。
- 2 件重試後仍 `UNPARSEABLE_RESPONSE`：回應截斷、夾帶推理文字、輸出兩個 JSON。
- 這與先前已修正的 offset 問題同類：要求模型做逐字的機械性文字工作。

**次要 blocker：Scope 語意任務的偽陰性。**
- helper 自身判 UNCERTAIN：P04、P05、P10、C05。
- helper 輸出瑕疵：引文錯誤（P02、P13）、欄位矛盾（P09）、端點標籤重疊（C03）。
- 已沒有任何一筆是因為重複字串而被拒。

**Writer 品質人工稽核（4 篇，皆未經 Validator 通過）**
- 事實句全部可回溯原文。
- 沒有捏造臺北捷運現況；標題均為繁體中文。
- 兩點輕微瑕疵：
  - 河內篇以「業主」概括市府主席的發言，並保留英文 "turnkey"。
  - 埃及篇的「2026年」取自文章發布日期，原文該句未寫年份。


## 9. RC-7 修訂後重新驗收（live3，2026-10-20）

- 修訂內容：Validator 以確定性 Python 規則把 Writer 各欄位切成具 `unit_id` 的單元；helper 只回傳單元評估與引文（契約 §A.2、§Q）。
- 離線驗證：
  - 測試全數通過（969）；Golden 29 通過。
  - live2 的 4 篇 Writer 文稿切成 6～8 個單元，逐字還原全部成立。
- 原始紀錄：[runs/live3/summary.json](runs/live3/summary.json)
- 用量：HTTP 22、MaiAgent 65、耗時 337 秒。
- Phase A 累計：HTTP 66/80、MaiAgent 146/160、時間 892/2700 秒。剩餘 MaiAgent 14 次，不足以再跑一輪完整驗收。
- 未寄信；未執行任何 Search 網路請求；未 commit。

| 指標 | live2 | live3 |
|---|---:|---:|
| Evidence READY（正向 14 筆） | 10 | 10 |
| 對照組錯放（正式報告） | 0 | 0 |
| IN_SCOPE（含對照組） | 4 | 6 |
| REPORTABLE 事件 | 4 | 5 |
| Validator 回應可解析 | 2/4 | 5/5 |
| 單元覆蓋違規 | 2 | 0 |
| Validation PASS／FAIL／技術缺口 | 0／0／4 | 2／1／2 |
| 正式報告篇數 | 0 | **2** |

**Validator 結果逐筆**
- P05 紐約地鐵槍擊：PASS。
  - 事實可回溯原文。
  - 一處輕微失真：原文為 12:30 前不久，Writer 寫成「中午前」，Validator 判為 SUPPORTED。
- P08 清奈黃線：PASS。逐句核對原文，全部有據。
- P13 香港北環線支線：FAIL，判定正確。
  - 原文車站為 "The Loop"（河套），Writer 誤譯為「新田科技城」。
  - 未進行改寫重驗：production 未接 correction provider（契約為「得」）。
- P02 哥本哈根 S-Bane：技術缺口 `INVALID_CITATION`。
  - helper 抄錄原文時把 "Hitachi will supply" 寫成 "Hitachi Rail will supply"。
- P09 首爾 9 號線：技術缺口 `INVALID_CITATION`。
  - helper 抄錄韓文原文時把「다음」寫成中韓混雜的「下一」。

**結論：RC-7 已解決它要解決的問題。** 兩種失敗都已消失：漏抄標點造成的覆蓋失敗，以及回應過長造成的無法解析。Validator 回應大小由 13～23 KB 降至 7～13 KB。

**新的最早 blocker：Scope 結果在兩次執行間不穩定（超出本次核准範圍，未修改）。**
- 同一批 Evidence 原文，13 筆 Scope 判定中有 8 筆在 live2 與 live3 之間翻轉：
  - 由 IN 轉 OUT：P03、P07、P14。
  - 由 OUT 轉 IN：P02、P05、P09、P13、C03。
- live3 的拒絕原因皆為 helper 結構化提案未通過 Python 的嚴格檢查，屬 fail-closed：
  - P03：`ENDPOINT_ROLE_DISTINCTNESS`。
  - P07：`ACTION_TARGET_CONTAINMENT`。
  - P14：`TARGET_SYSTEM_CONTAINMENT`。
- 影響：哪些事件進入報告，主要取決於 helper 單次輸出的隨機性，而不是事件本身。

**次要問題：helper 逐字抄錄 Evidence 引文仍會出錯（超出核准範圍，未修改）。**
- 與 RC-7 前的 Writer 文字問題同類：要求模型逐字重打長句。
- 可比照 RC-7 的方向：由 Python 將 Evidence 切成具 ID 的句子，helper 只引用句子 ID。
- 此方向涉及 Evidence、Scope、Category、Taxonomy、Reportability、Validator 共用的引用契約，需另行裁決。

**與預期標記不符，待裁決：**
- P05 槍擊案：預期 `reportable: false`（一般治安事件、無機電面向），Reportability owner 判為 REPORTABLE。
- C03（荷蘭 Delft 電車 19 路，對照組）：本次判為 IN_SCOPE，最後因日期不在期間內而排除，未進入報告。

```text
VALIDATOR_PARSEABLE = 5/5
VALIDATOR_COVERAGE_VIOLATIONS = 0
VALIDATION = PASS 2 / FAIL 1（正確） / TECHNICAL_GAP 2（引文抄錄錯誤）
FINAL_REPORT = 2 篇，狀態 SUCCESS_WITH_TECHNICAL_GAPS，揭露 2 則技術缺口與 1 則驗證未通過
EARLIEST_BLOCKER = Scope 跨執行不穩定（8/13 翻轉）
PRODUCTION_READY = 否
```


## 10. RC-8 Scope 穩定性驗收（2026-10-20）

- 修訂：SC-1（端點改為標籤，須位於關係引文內）、SC-2（noneligible 只針對焦點行動）、D1（發生於合格系統設施內的事件）、D2（commuter／suburban／S-Bahn 名稱不自動納入或排除）。契約 §A.3、SCOPE_CONTRACT §6.2／§9；prompt v5、schema v2。
- 方法：以 live3 封存的 13 份 Scope 請求原文（逐字相同）重跑 3 輪，只呼叫 Scope helper。
- 原始紀錄：[runs/scope_stability/summary.json](runs/scope_stability/summary.json)
- 用量：MaiAgent 45/45（39 次＋6 次重試）、HTTP 0、277 秒；未寄信、未 commit。

| 樣本 | 預期 | R1 | R2 | R3 | 說明 |
|---|---|---|---|---|---|
| P03 埃及電車 | IN | IN | IN | IN | 穩定 |
| P07 聖路易輕軌 | IN | IN | IN | IN | 穩定 |
| P09 首爾 9 號線 | IN | IN | IN | IN | 穩定（SC-2 生效） |
| P04 香港電車出軌 | IN | OUT | IN | IN | R1 關係引文取自焦點外段落 |
| P08 清奈黃線 | IN | OUT | IN | IN | R1 標籤不在關係引文內 |
| C03 Delft 電車（對照，日期無效） | 未標 | OUT | IN | IN | R1 同一實體卻引用另一句 |
| P13 香港北環線支線 | 不確定 | OUT | IN | OUT | helper 語意判斷不一 |
| C04 Network Rail（對照） | OUT | 技術缺口 | OUT | OUT | 平台回應夾雜雜訊，重試後仍無法解析 |
| P14 河內五條地鐵 | IN | OUT | OUT | OUT | 穩定誤拒：同一實體卻引用另一句 |
| P05 紐約月臺槍擊 | IN | OUT | OUT | OUT | 穩定誤拒：helper 不認定月臺屬於地鐵 |
| P10 哥本哈根地鐵營運合約 | IN | OUT | OUT | OUT | 穩定誤拒：helper 未把合約連到系統 |
| C05 香港電車出軌（中文） | IN | OUT | OUT | OUT | 穩定誤拒：同上 |
| P02 S-Bane 郊區鐵路 | 不確定 | OUT | OUT | OUT | 符合 D2 |

- 翻轉：8/13 → 5/13；扣除 C04 技術缺口後為 4/13，其中 3 筆只在 R1 被機械性拒絕。
- 錯誤 IN_SCOPE：0。所有 IN 皆為合格模式（電車、輕軌、地鐵）；C04 鐵路氣象站、P02 郊區鐵路皆維持 OUT。
- 新的主要問題已由「隨機翻轉」轉為「穩定誤拒」（P05、P10、P14、C05），根因分兩類：
  - 目標即系統時，helper 常引用另一句只用代稱（"The five lines"）的文字，標籤不在引文內（P14、C03 R1）。
  - helper 對「合約／事故現場」與系統的關係過度保守，回 UNRESOLVED（P05、P10、C05）。
- 與 live3 的差異：P05 在 live3 以「A man PART_OF subway」這種語意錯誤的關係進入報告；v5 下穩定為 OUT。依 D1 它應為 IN_SCOPE，屬尚未達成的目標，不是被修好的行為。
- 核准預算已用完，上述兩類的 prompt 修正尚未實作、也未驗證。

```text
SCOPE_FLIPS = 8/13 → 5/13（4/13 不含技術缺口）
FALSE_IN_SCOPE = 0
STABLE_FALSE_NEGATIVES = P05, P10, P14, C05
TESTS = 975 passed；GOLDEN = 29 passed
PRODUCTION_READY = 否
```


## 11. RC-8 第二輪：穩定誤拒修正（2026-10-21）

- 修改（皆為一般規則，無單一新聞特例）：
  - Python：`target_system.target_reference`（選填）讓目標-系統引文可用同一事件內的代稱（"The five lines"、"This"）指涉目標；省略即代表目標標籤本身。代稱須位於該引文內，且兩段關係引文都須位於已確定的事件焦點內。系統即目標本身時不需再次出現。
  - Prompt v7：目標詞組本身已含系統（"five metro lines"、"電車"）時直接引用該詞組；車站、月臺、列車屬於系統（PART_OF）；合約／採購／授權事件的目標是合約涵蓋的工作或路線；營運者的公車不因營運者而成為都市軌道；ambiguity 只指「屬於哪個系統」的不確定，不含月臺或列車、時間、原因等細節。
  - 驗收腳本改為每次呼叫後即寫入結果（上一次執行因工作階段重啟中斷，未留下摘要）。
- 原始紀錄：[runs/scope_stability_v7/summary.json](runs/scope_stability_v7/summary.json)；中斷的 v6 執行（11 筆回應）已以現行 owner 離線重放。
- 用量：MaiAgent 約 39～40/40（中斷的 v6 約 12～13 次＋v7 27 次，含 2 次逾時重試、1 次無法解析重試）、HTTP 0；v7 耗時 174 秒。預算在第 2 輪剩 3 筆時用完。

| 樣本 | 預期 | v5（3 輪） | v7 R1 | v7 R2 |
|---|---|---|---|---|
| P05 紐約月臺槍擊 | IN | OUT×3 | IN | IN |
| C05 香港電車出軌（中文） | IN | OUT×3 | IN | IN |
| P14 河內五條地鐵 | IN | OUT×3 | IN | 未執行 |
| P10 哥本哈根營運合約 | IN | OUT×3 | OUT（引錯句子） | 未執行 |
| P04 香港電車出軌 | IN | 2/3 IN | IN | IN |
| P08 清奈黃線 | IN | 2/3 IN | IN | IN |
| P03 埃及電車 | IN | IN×3 | OUT（漏填代稱） | 技術缺口 |
| P07、P09 | IN | IN×3 | IN | IN |
| C03 Delft 電車 | 未標 | 2/3 IN | IN | IN |
| P13 香港北環線支線 | 不確定 | 1/3 IN | OUT（漏填代稱） | 未執行 |
| P02 S-Bane 郊區鐵路 | 不確定 | OUT×3 | OUT | OUT |
| C04 Network Rail（對照） | OUT | OUT（1 次技術缺口） | OUT | OUT |

- 正確率（排除預期「不確定」的 P02、P13）：v7 R1 為 9/11；R2 已執行的 8 筆皆正確，另有 1 筆技術缺口。v5 多數決為 7/11。
- 跨執行：兩輪都有結果的 10 筆中，內容判定翻轉 0 筆；P03 一輪 OUT、一輪技術缺口。P10、P13、P14 只有一輪，穩定性未量測。
- 錯誤 IN_SCOPE：0。C04 鐵路氣象站、P02 郊區鐵路維持 OUT。
- 仍未解決：
  - helper 在需要代稱時仍常漏填 `target_reference`（P03、P13），或引用錯誤句子（P10）。Python 依規則拒絕，沒有替模型補上。
  - Scope 提案若違反格式或引文規則（非傳輸錯誤），依 RC-6 仍以 OUT_OF_SCOPE 收場；在 RunTrace 可區分（OWNER_REJECTED），但正式報告不揭露為技術缺口。這與「技術失敗與合法 OUT_OF_SCOPE 必須分開」的要求有落差，需另行裁決。

```text
STABLE_FALSE_NEGATIVES_FIXED = P05, C05（兩輪）、P14（一輪）
STILL_FALSE_NEGATIVE = P10；P03 退步為隨機
FALSE_IN_SCOPE = 0
TESTS = 979 passed；GOLDEN = 29 passed
PRODUCTION_READY = 否
```


## 12. 共同根因修復（RC-9、RC-10，2026-10-21，離線驗證）

- Git checkpoint（分支 `v2/real-evidence-recovery`，未 push）：
  - `9c404cc`：RC-2～RC-8 與 Phase A 驗收紀錄。
  - `5032ebc`：RC-9、RC-10。
  - 兩者均在乾淨 worktree 驗證全部測試通過。未提交的僅剩先前既有、與本工作無關的 9 個 Golden 檔與 `__init__.py` 排序。
- RC-9（共同根因：模型重打來源文字會抄錯）：
  - Python 將 Evidence 切成編號句子；Scope 與 Validator 只以句子 ID 引用。
  - 在 13 筆真實原文上，切句逐字覆蓋全部文字。
  - Scope 提案違反契約 → 已揭露的技術缺口（不再偽裝成 OUT_OF_SCOPE）。
  - Validator 的一次改寫重驗已接上，Writer 會收到未通過單元的原文。
- RC-10：Reportability helper 原本沒有收到任何選題標準；現已帶入契約的報導價值路徑，並明定一般治安、個人事件不成報。
- Writer prompt v2：數字、時間照原文；不猜譯專有名詞；不留英文一般詞。
- 離線整合：以 live3 封存 HTML 與舊 MaiAgent 回應完整重放（無網路）。13 筆 Evidence READY 不變；13 筆舊格式 Scope 回應全數成為「技術缺口」並揭露，未被當成 OUT_OF_SCOPE。
- 測試 989 通過（乾淨 worktree）；Golden 29 通過。
- 尚未進行：新 prompt 的真實 MaiAgent 驗收（需預算核准）。
- 正式 Search 至報告的完整流程仍有已知阻礙：Google News RSS 連結從未被解析為出版者文章；Phase A 是以 manifest 直接提供出版者網址繞過。


## 13. 封存 Evidence 端到端驗收（e2e_archived1，2026-10-21）

**性質：封存 Evidence 的整合驗收，不是正式 Search 到報告的完整生產流程。**
- Search 以 manifest 重播。
- Evidence 使用 live3 封存的 HTML（真實網路 HTTP 0 次；22 次為重播計數）。
- MaiAgent 全部即時呼叫，使用 RC-9／RC-10 新 prompt。
- 用量：MaiAgent 62/100（含 1 次 Writer 逾時重試）、279 秒、未寄信。
- 原始紀錄：[runs/e2e_archived1/summary.json](runs/e2e_archived1/summary.json)、[final_report.md](runs/e2e_archived1/final_report.md)

**正式週報：3 篇，全部通過 Validation（0 FAIL、0 Validator 技術缺口）。** 報告揭露 4 則技術缺口。
- 營運動態：清奈捷運黃線首段營運（P08）。
- 採購事件：河內簽約興建五條捷運線（P14）。
- 規範變動：香港北環線支線核准（P13）。

**內容稽核（逐句對照封存原文）：**
- 事實全部可回溯原文。live3 的錯誤已消失：
  - 「The Loop」不再被誤譯為「新田科技城」。
  - 「turnkey」已譯為「統包」。
- 品質缺陷，已修正但尚未真實驗證：
  - 日期與數字保留英文寫法（「September 18」「October 11」「mid-2027」「25 474」）。這是 Writer v2 指示「照原文」的副作用；v3 改為照原值、以中文格式書寫。
  - 香港篇的「運輸系統：Hong Kong and Shenzhen」是城市組合，不是系統名稱。已補一般規則：只由地名或泛稱組成的值不得存為系統名稱。
- 可商榷（屬既有 owner 判定，未修改）：
  - 香港篇的國家／地區顯示「中國大陸」，因為原文標示「CHINA:」。
  - 香港篇的相關系統為「供電」，依據薄弱。
  - 香港篇的類別為「規範變動」。

**技術缺口 4 則（皆已揭露，未偽裝成新聞不合格）：**
- Scope：P05「shooting」、P09 韓文動作詞。helper 自行改寫的標籤不在其引用的句子內，屬標籤層級的改寫問題。
- Reportability：P10 引文抄錯。Reportability 尚未改用句子 ID。
- Taxonomy：P07 欄位組合錯誤（「已評估」卻附「未解決」理由）。prompt v2 已明列合法組合，尚未真實驗證。

**其他觀察：**
- 香港電車出軌（P04／C05）判定 IN_SCOPE，但因 Evidence 未取得發布日期而被 Temporal 排除。政府新聞稿的日期只寫在正文，未寫在網頁 metadata；屬日期擷取的缺口。
- 埃及氫能電車（P03）判為 CATEGORY_UNRESOLVED。
- 紐約月臺槍擊（P05）本次在 Scope 即成為技術缺口，因此 RC-10 對一般治安事件的效果尚未經真實驗證。
- 對照組：C03、C05 因日期無效排除；C04 OUT。正式報告未混入任何對照組事件。

```text
ARCHIVED_EVIDENCE_E2E = PASS（3 篇正式週報，0 Validation FAIL）
FULL_PRODUCTION_E2E = 未執行（Google News 連結未解析，詳見最終回報）
TESTS = 992 passed；GOLDEN = 29 passed
PRODUCTION_READY = 否
```


## 14. P1 正式 Search → Evidence 測量（2026-10-21）

- 範圍：
  - 正式 Search（search-discovery-v4，207 次 Google News RSS）。
  - 候選正規化。
  - 抽樣 102 筆經 Google News 連結解析與出版者頁面擷取（不含語意判定）。
- 用量：HTTP 513/520（RSS 207、連結解析 204、出版者頁面 102）、MaiAgent 0、714 秒、未寄信。
- 期間：2026-10-14～2026-10-20。
- 原始紀錄：[runs/p1_search/summary.json](runs/p1_search/summary.json)

| 指標 | 結果 |
|---|---|
| Search 請求 | 207（舊版 449）；196 有結果、11 零結果、0 技術失敗 |
| 原始結果 | 11,284 筆（每次請求平均 57.6 筆；40 次達 100 筆上限） |
| 原始結果落在期間內 | 39%（4,424）；61% 在期間外 |
| 正規化候選 | 6,192 筆，其中期間內 2,053 筆 |
| Google News 連結解析成功率 | 102/102（100%），出版者網域核對 102/102 一致 |
| 出版者頁面結果 | 41 筆通過結構檢查（40%）；擷取失敗 30（29%）；非單一主文件 27；來源不符 4 |
| 平均耗時 | Search 約 1.4 秒／次；每筆候選解析加擷取約 4 秒（不含 MaiAgent） |

**已解決：** Google News 連結解析。出版者文章頁已能取得並進入 Evidence 判定，不再停在 Google 轉址頁。

**未解決（新的最早 blocker）：搜尋精準度與候選量。**
- 期間運算子 `after:`／`before:` 對這類 OR 查詢大多無效：61% 的結果在期間外。
- 每週 2,000 筆以上期間內候選，遠超可處理量。以每筆約 16 秒（含 MaiAgent）估算，需約 9 小時、約 6,000 次 MaiAgent。
- 抽樣顯示大量無關結果。原因是「metro」一字同時命中：
  - 報紙 Metro、Metro Magazine；
  - 城市行政區 Città Metropolitana；
  - 美國的 metro area。
- 另有大量地方日常交通新聞，例如假日班次與罷工時刻。

**建議下一步（P1b，需另行核准預算）：**
- 以 RSS 自身的發布時間過濾期間外結果。這只限定搜尋範圍，日期是否有效仍由 Temporal 判定。
- 提高查詢精準度：
  - 加入專業軌道媒體來源軌，以技術與採購為主。
  - 地方版本只保留特定技術與事故詞彙。
- 以同一 207 次以內的請求重新量測。


## 15. P1b 搜尋精準度改善後重新量測（2026-10-21）

- 修改（RC-12，`search-discovery-v5`）：
  - 以 RSS 發布時間過濾期間外結果。
  - 運具詞須出現在標題。
  - 只用具體意圖詞。
  - 新增 2 次專業軌道媒體查詢。
- 用量：HTTP 443/450（另以剩餘額度 3 次擷取診斷頁面）、MaiAgent 0、450 秒、未寄信。期間同 P1。
- 原始紀錄：[runs/p1b_search/summary.json](runs/p1b_search/summary.json)

| 指標 | P1（v4） | P1b（v5） |
|---|---:|---:|
| Search 請求 | 207 | 122 |
| 供應者回傳筆數 | 11,284 | 5,757（期間過濾後保留 2,954） |
| 正規化候選 | 6,192 | **673** |
| 候選落在期間內（嚴格） | 2,053 | 610（63 筆在 ±1 天寬限內） |
| 連結解析成功率 | 100%（102） | 100%（107），出版者核對全數一致 |
| 抽樣通過結構檢查 | 40% | 31% |
| 執行時間 | 714 秒 | 450 秒 |

**期間過濾**：依 RSS 自身發布時間過濾，保留 2,954／5,757 筆（51%）；最終候選 91% 落在期間內。

**精準度**：
- 專業媒體軌 10 筆全部是都市軌道新聞，例如 Santiago 9 號線、Riyadh 94 列列車、København 營運合約。
- 韓、日、中文版本多為真實都市軌道新聞。
- 剩餘雜訊多由我的一個錯誤造成：`intitle:"people mover"` 實際等於「標題含 people」，帶入 219 筆無關新聞。已修正（多字詞改為一般引號詞組，不加 intitle）；尚未重新量測。
- 依候選標題離線估算，修正後約 **387 筆／週**：技術 177、營運 122、事故 60、採購 28。

**新的最早 blocker：Evidence 主文件判定誤拒真實新聞。**
- 抽樣中 80 筆標題相關的新聞，有 46 筆在結構檢查被拒：PRINCIPAL_DOCUMENT 33、SOURCE_PROVENANCE 13。
- 根因（以 3 個真實頁面確認）：
  - 新聞網站大量使用 `<article>` 標籤包住非文章區塊，例如記者欄、分享列、留言框，以及數十則約 30 字的相關新聞標題。主文件判定把它們視為多篇文章，因而判為 AMBIGUOUS。
  - 韓國常見新聞 CMS 其實以 `itemprop="articleBody"` 明確標出正文。
  - Google News 常連到 AMP 版。AMP 頁的 canonical 指向一般版網址，被判為來源不符。
- 建議修正（屬 Evidence 結構契約，需另行核准）：
  - 標題級短區塊不參與主文件競爭。
  - 採用 schema.org articleBody。
  - AMP 頁改取其 canonical 文章。
- 其他：Vietnam.vn 同一篇新聞有韓、日、法等多語版本，造成重複候選；Event Identity 可合併，但會增加處理成本。

```text
LINK_RESOLUTION = 100%（209/209，兩輪合計）
CANDIDATES_PER_WEEK = 673（P1b 實測）→ 約 387（修正 intitle 後估算）
EARLIEST_BLOCKER = Evidence 主文件判定（<article> 區塊與 AMP canonical）
P2_BUDGET = 待 Evidence 修正並重新量測後估算
```


## 16. P1c：主文件判定修正後重新量測（2026-10-21）

- 修改：RC-13（`1de91c4`）。
- 用量：HTTP 441/450（RSS 122、連結解析 210、出版者頁面 109，其中 AMP 轉取 canonical 4 次）、MaiAgent 0、457 秒、未寄信。期間同 P1。
- 原始紀錄：[runs/p1c_search/summary.json](runs/p1c_search/summary.json)

| 指標 | P1 | P1b | P1c |
|---|---:|---:|---:|
| Search 請求 | 207 | 122 | 122 |
| 正規化候選 | 6,192 | 673 | **671** |
| 候選落在期間內 | 33% | 91% | **95%** |
| 抽樣標題屬都市軌道 | — | 75% | **87%** |
| 連結解析成功率 | 100% | 100% | **100%** |
| 抽樣通過結構檢查 | 40% | 31% | **46%** |
| 期間內每週候選中，標題含運具詞 | — | — | 565／671（84%） |

**結果：**
- 結構檢查通過率由 31% 升至 46%。韓國 CMS 與 AMP 頁的主要誤拒已解決。
- 剩餘主文件失敗多為：
  - Vietnam.vn 同一新聞的多語版本；
  - 少數日本、台灣入口網站。
- 修正 `intitle:"people mover"` 後候選量並未如估算下降（671）：
  - 英文「metro」本身多義，例如 Metro.co.uk 的娛樂新聞、Denver metro 天氣、Metro Vancouver、Metro Inc. 股利。
  - Google 的 `intitle:` 也會比對 RSS 標題後附的出版者名稱。

**P2（正式 Search → 報告，單週）估算**（依 P1c 實測比例）：
- HTTP：
  - Search 122 次；
  - 連結解析約 1,340 次；
  - 出版者頁面約 700 次；
  - 合計約 2,200 次。
- MaiAgent，約 1,000 次：
  - 語意判定約 310 次；
  - 資料擷取約 220 次；
  - Scope 約 220 次；
  - 事件層級（Category、Taxonomy、Reportability）約 165 次；
  - Writer 與 Validator（含改寫）約 60 次；
  - 另加約 5% 重試。
- 時間：
  - 候選處理約 31 分鐘（每筆約 2.75 秒）；
  - MaiAgent 依序約 85 分鐘；
  - 合計約 2 小時。
- 建議上限：HTTP 2,500、MaiAgent 1,100、150 分鐘、不寄信。

**剩餘問題（不阻擋正確性，影響成本）：**
- 英文「metro」多義與出版者名稱造成的雜訊（估計約 100 筆／週）。
- Vietnam.vn 多語重複。
- 日本與台灣部分入口網站的主文件判定。
- 正文日期擷取缺口（香港政府新聞稿）。
- Reportability 尚未改用句子 ID。


## 17. P1d：英文運具詞修正後小額量測與 P2 重新估算（2026-10-21）

- 修改：RC-14（`ffa4e00`）。
  - 英文運具詞改為明確詞組（metro line、metro station、subway line／station、metro system）。
  - 單字只保留 tram、streetcar、LRT、MRT、monorail。
- 用量：HTTP 241/250、MaiAgent 0、197 秒、未寄信。期間同 P1。
- 原始紀錄：[runs/p1d_search/summary.json](runs/p1d_search/summary.json)

| 指標 | P1c | P1d |
|---|---:|---:|
| Search 請求 | 122 | 117 |
| 期間過濾後保留 | 1,640 | 513 |
| 正規化候選 | 671 | **369**（−45%） |
| 候選落在期間內 | 95% | 97% |
| 標題含運具詞 | 84% | 85% |
| 連結解析成功率 | 100% | 100%（40/40） |
| 抽樣通過結構檢查 | 46% | 48%（19/40） |

**跨語言重複（決定不另設去重）：**
- Vietnam.vn 同一新聞的多語版本仍有 46 筆。
- 這些在結構檢查即被拒，只花約 3 次 HTTP，不花任何 MaiAgent。
- 在 Evidence 前另設去重會成為 Event Identity 之外的第二個去重 owner（違反單一 owner 與「不得多階段去重」），故不增設。

**剩餘雜訊：**
- 義大利文「metro」也指「公尺」。
- 厄瓜多報紙名為 Metro。
- 同一事件被多家韓國媒體報導（例如蔚山電車車庫約 6 篇）。這屬 Event Identity 合併範圍，但每篇仍需 Evidence 與 Scope 的 MaiAgent 呼叫。

**P2（正式 Search → 報告，單週）重新估算：**

| 項目 | P1c 估算 | P1d 估算 |
|---|---:|---:|
| HTTP | 約 2,200 | **約 1,240**（Search 117、解析 740、擷取約 385） |
| MaiAgent | 約 1,000 | **約 630** |
| 時間 | 約 2 小時 | **約 70 分鐘**（候選處理約 16 分、MaiAgent 約 53 分） |

- MaiAgent 細項：
  - 語意判定約 175 次；
  - 資料擷取約 130 次；
  - Scope 約 130 次；
  - 事件層級約 120 次；
  - Writer 與 Validator 約 42 次；
  - 另加約 5% 重試。
- 建議上限：HTTP 1,500、MaiAgent 700、100 分鐘、不寄信。超過任一上限即中止，並保留已完成結果。


## 18. P2 正式全流程驗收（2026-10-14～20，未產出報告）

**性質：正式 Search 到報告的完整生產流程**（ProductionRunner 未修改；真實 Google News、真實出版者頁面、真實 MaiAgent；未寄信）。

- 結果：在 Writer 階段觸及 MaiAgent 上限 700 次而中止，**未產出正式週報**。
- 用量：
  - HTTP 1,400/1,500（RSS 117、連結解析 842、出版者頁面 441）；
  - MaiAgent 700/700（3 次逾時重試）；
  - 3,930 秒。
- 原始紀錄：[runs/p2_production/summary.json](runs/p2_production/summary.json)、[trace.jsonl](runs/p2_production/trace.jsonl)（逐行寫入，中止後完整保留）。

| 階段 | 輸入 → 輸出 | 主要淘汰原因 | 耗時 |
|---|---|---|---|
| Search | 117 → 562 筆 | — | 74 秒 |
| 正規化 | 562 → 421 候選 | — | — |
| Evidence | 421 → 160 READY | 來源頁不符 197、擷取失敗 50、內容不足 8、只有標題 5 | 41 分 |
| Scope | 160 → 73 IN_SCOPE | 未確立 35、排除運具 7、非都市軌道 6 | 13 分 |
| Temporal | 73 → 59 | 日期來源無效 9、期間外 5 | — |
| Event Identity | 59 → **59 事件**（完全未合併） | — | — |
| Category | 59 → 50 | 無分類行動 4、helper 回應無效 4 | 3 分 |
| Taxonomy／Reportability | → 47 REPORTABLE | — | 6 分 |
| Writer | 47 筆中完成 13 筆時觸及上限 | — | — |

- MaiAgent 用量：語意判定 199、資料擷取 161、Scope 170、Category 59、Taxonomy 50、Reportability 48、Writer 13。
- 估算 630 次，實際在 Writer 前已用 687 次。完成全部 Writer 與 Validator 約需再 110 次（合計約 810 次）。

**Reportability 選出的 47 則：**
- 多數是有價值的都市軌道事件，例如：
  - 東京 Metro 日比谷線列車通過車站；
  - 布拉格地鐵 D 線車站開挖；
  - 廈門兩條新線通車；
  - Santiago 9 號線合約；
  - 雅典 1 號線翻新列車；
  - 馬尼拉 LRT-1 回生電力實證；
  - 奧斯陸與蘇黎世電車碰撞；
  - 新北三鶯線電力故障；
  - 土魯斯潛盾機缺陷；
  - 馬德里電扶梯更新。
- 約 16 則是同一事件的重複報導：
  - 蔚山電車車庫 7 篇；
  - 梁山都市鐵路 5 篇；
  - 利馬 2 號線 3 篇；
  - 桃園綠線、東京日比谷線、名古屋演練、慰禮線各 2 篇。
- 少數價值存疑：大學入學考試日加開班次、市議員座談、市長專訪、防災演練、電車駕駛遭攻擊。

**根因與阻礙（依影響排序）：**
1. **Event Identity 實際上不做跨來源合併。**
   - production 組裝的 `EventIdentity()` 沒有語意顧問，只剩「事實欄位逐字相同」的確定性比對，跨媒體幾乎不可能成立。
   - 程式已有語意顧問介面，但不在 AGENTS §11 核准的 7 項 Structured Helper 任務中。
   - 啟用屬架構決策，需使用者核准；此外須限定比對範圍，避免兩兩比較成本暴增（59 筆即 1,711 對）。
2. **成本**：Evidence 階段占 41 分鐘與約 360 次 MaiAgent。重複事件也使 Writer 與 Validator 成本加倍。
3. **主文件邊界雜訊**：沒有 article 標記的頁面，正文會混入天氣小工具與網站選單文字。
4. **Reportability 對少數一般事件仍偏寬。**


## 19. RC-15 Event Identity 跨來源合併：小額 live 驗收（2026-10-21）

**性質：單一 owner 的 live 驗收**，不是完整生產流程。
- 輸入：P2 實際進入 Event Identity 的 59 筆紀錄（候選 ID 與正式 Evidence 正文，由 P2 封存請求離線重建）。
- 對象：未修改的 EventIdentity owner 與 production MaiAgent provider。
- 用量：MaiAgent 4/6、HTTP 0、呼叫合計約 70 秒、未寄信。
- 預期合併結果在呼叫前就已人工標註：[runs/rc15_event_identity/expected_labels.json](runs/rc15_event_identity/expected_labels.json)，共 7 組、45 對。
  - 不計分：2 組模糊情況（桃園綠線兩篇角度不同、蔚山車庫的社論）。
  - 必須分開：光州 2 號線不同進度、慰禮線其他報導、蔚山市議會聲明、首爾安全統計。

| 執行 | 程式版本 | 事件數（59 筆） | 正確合併（對） | 漏合併 | 錯誤合併 | 技術缺口 |
|---|---|---:|---:|---|---:|---|
| run1 | 候選 ID 版 | 42 | 45/45 | 0 | 0 | 單筆群組 1（改為不揭露的診斷後重播：0） |
| run2 | 候選 ID 版 | 59 | 0/45 | 全部 | 0 | 整份回應無效（抄錯 69 字元候選 ID） |
| run3 | **最終版** | 43 | 44/45 | 首爾 CNN 1 對 | 0 | 0 |
| run4 | **最終版** | 41 | 45/45 | 0 | 0 | 0（另把蔚山社論併入，屬不計分的模糊情況） |

- 原始紀錄：`runs/rc15_event_identity/run1..4_summary.json`。

**過程中修正的兩個共同根因：**
1. **helper 抄錯長 ID**（run2）：69 字元的候選 ID 少了一個字元，整份提案依契約失效。
   - 改法同 RC-9：Python 指定短的 `record_id`（R1…Rn）並負責對應回候選 ID，helper 不再抄寫任何 ID。
   - 失效時沒有誤合併，只揭露技術缺口，事件照常進入後續流程。
2. **單筆群組**（run1）：helper 偶爾列出只有一筆的群組。這不會造成任何合併，所以改為只記錄診斷，不列為技術缺口，避免報告誤稱「可能含重複事件」。

**其他實作調整：**
- 字元上限由 48,000 改為 66,000，讓 60 筆上限成為實際的限制。原本 59 筆會被切成 52＋7 兩批，跨批的重複無法合併。
- 刪除提案中的「日期不同即否決」規則。既有契約測試要求 `2026-09-15` 與 `15 September 2026` 這類寫法差異交由語意判斷，不得直接否決。

**結論：**
- 最終版兩次 live：59 筆 → 41～43 個事件，正確合併 44～45/45 對，錯誤合併 0。
- 失效時只會少合併，不會錯合併，並會揭露。
- 依 P2 估算，可減少約 16～18 個重複事件。對應的下游 Category、Taxonomy、Reportability、Writer、Validator 呼叫約 70～80 次。
- 尚未驗證：完整生產流程（P2 重跑）中的實際效果，以及合併後的多來源事件經 Writer、Validator 產生的報告內容。


## 20. P2 重跑中斷：根因與可續跑的執行紀錄（2026-10-21）

**中斷：** P2 重跑 15:47 啟動，34 分鐘後（Evidence 300/402）程序消失。
- 沒有 Python traceback，標準輸出與錯誤檔都是空的，shell 回報 exit 127。
- 同時段沒有休眠、當機或重開機事件。Windows 只記錄更新、防毒與群組原則活動。
- 結論：程序是被執行環境從外部終止，不是 production code 或測試腳本出錯。先前 Scope 穩定性驗收也曾以同樣方式遺失。
- 殘存紀錄：[runs/p2_rerun/trace.jsonl](runs/p2_rerun/trace.jsonl)。

**真正的浪費（最早根因）：** 驗收腳本只把結果放在記憶體。程序一被終止，所有已完成的工作都無法接續，也無法重播。
- 實測：重跑的 250 次 MaiAgent 中，有 162 次（65%）與第一次 P2 的請求逐位元完全相同。也就是同一請求付了兩次費用。
- 搜尋結果、Google News 連結解析與出版者頁面都沒有保存，所以不能從中斷點接續。

**修正（只改驗收工具，production pipeline 不變）：** `scripts/run_journal.py`
- 所有外部 I/O 依「請求內容」存檔：RSS、Google News 連結解析、出版者頁面（含確定性失敗）、MaiAgent 回應。
- 重新啟動時，所有 Python 階段照常重新執行，但已有的外部回應直接重播，只有沒見過的請求才實際呼叫。
- 為何可以重用 MaiAgent 回應：helper 與 Writer 都是無狀態、自足的呼叫（conversation = null）。對逐位元相同的請求，已記錄的回應就是該請求的有效回應；各 owner 仍會照常驗證。
- 暫時性失敗不記錄，下次會重新實際呼叫：逾時、429、5xx，以及非 200 的 MaiAgent 回應。
- 帳本（ledger）累計每次嘗試的實際用量，三項預算都是整輪上限，不會因為重新啟動而重置。
- 每次呼叫前先記帳；程序被強制終止時，最多只多付當下進行中的請求。
- 驗證：
  - 離線 dry-run 第二次執行時，HTTP 新增 0（RSS 117、連結 222、頁面 221 全部重播）。
  - 以 `Stop-Process -Force` 強制終止後續跑，只多付當下進行中的 2 次請求。
  - 新增 6 個 journal 單元測試；全套 1035 個測試通過。
- 已付費的結果移到永久位置：兩次 P2 的 774 個可解析 MaiAgent 回應已匯入 `acceptance/phase_a/journals/p2_round2/`。內含文章原文，所以不納入 Git。

**本輪預算帳本（上限 MaiAgent 800、HTTP 1,500、110 分鐘）：**
- MaiAgent 已用 255：250 次有紀錄，另保守加 5 次可能未記錄的逾時。
- HTTP 已用約 1,150：中斷的程序沒有留下計數，依 137 次語意判定推估約 320 個候選，每個約 3.1 次請求，再加 117 次 RSS。
- 時間已用 34 分鐘。
- 剩餘：MaiAgent 約 545、HTTP 約 350、時間約 76 分鐘。
- 下一次完整執行需要重新取得 RSS 與出版者頁面，約 1,350～1,450 次 HTTP，超過剩餘的 HTTP 額度。


## 21. P2 第二輪：首次完成正式 Search → 週報（2026-10-21～22）

**結果：** 產出正式週報 [runs/p2_round2/final_report.md](runs/p2_round2/final_report.md)，共 **22 則事件**，狀態 `SUCCESS_WITH_TECHNICAL_GAPS`；未寄信。
- 本輪總用量（含中斷的嘗試）：
  - MaiAgent 882/1,000；
  - HTTP 2,474/2,700；
  - 時間 103/170 分鐘。
- 最後一次續跑僅 6 分鐘、新增 64 次 MaiAgent；其餘全部由 journal 重播。
- 原始紀錄：
  - [summary.json](runs/p2_round2/summary.json)；
  - 各次嘗試的 trace；
  - 15 則版本的中間結果：[attempt5_report/](runs/p2_round2/attempt5_report/)。

**執行過程與修正（依發生順序）：**
1. **前兩次被執行環境中止**（約 10 分鐘，`^C`／主控台關閉）。
   - 原因：工具 shell 啟動的程序會隨工作階段一起被終止，`Start-Process` 也一樣。
   - 改用 WMI 在工作階段之外啟動，並由無主控台的 supervisor 執行。
   - supervisor 在程序異常結束時，會從 journal 自動續跑（`scripts/run_supervisor.py`）。
2. **Assembly 失敗（ValueError）**：25 則通過 Validation 的事件全部遺失。
   - 原因：Ordering 依日期排序，類別本來就會交錯；組裝時依類別分節，事件清單卻仍沿用原本順序，違反「分節攤平後順序必須一致」的不變量。
   - 修正：事件改依分節順序排列，各節內保留 Ordering 的穩定子序列（契約 §R）。已加回歸測試（修正前重現同一 ValueError）。
3. **Scope 請求無法重用**：請求內含整份 Evidence provenance（約 10 KB 擷取診斷，含每次不同的 `acquisition_elapsed_ms`）。
   - 契約只允許「同一文件的事實性 metadata」。
   - 修正：只送文件本身的標題。請求變小，而且可重現。
4. **Scope 有 33 筆 MaiAgent 連線失敗**（URLError／OSError，重試後仍失敗）。
   - 這些屬於暫時性失敗，journal 不記錄。續跑時只重新呼叫這 33 筆，報告由 15 則增為 22 則。

**漏斗（最終）：**

| 階段 | 數量 |
|---|---|
| Search → 正規化候選 | 517 → 392 |
| Evidence READY | 142 |
| Scope | IN 70、OUT 32、技術缺口 40 |
| 日期有效 | 54 |
| Event Identity | 54 → **34 事件** |
| Category 指定 | 27（未決 7） |
| REPORTABLE | 25 |
| Validation | PASS 22、FAIL 2、缺口 1 |

**合併效果（RC-15，1 次呼叫）：** 9 組多來源事件。
- 主要合併：蔚山車庫 12 → 1、梁山 3 → 1；東京日比谷線、名古屋演練、慰禮線、孟買 Alstom、首爾安全統計、光州議會質詢各 2 → 1。
- **1 組錯誤合併**：光州 2 號線「首列電聯車進場」被併入「市長稱 2035 年恐難達成」。
  - 結果：首列車進場事件消失。
  - 市長發言在報告中出現兩次：一次是該合併事件，一次是議會質詢事件。

**內容稽核（22 則）：**
- 全部為繁體中文，事實均有出處，類別分節合理，「臺北捷運局啟示」沒有捏造臺北現況。
- 有價值的技術事件包括：
  - 雅典 1 號線翻新列車；
  - 布達佩斯 Urbos 3；
  - 墨西哥城 9 號線火情；
  - 三鶯線供電異常；
  - 日比谷線自動運轉越站；
  - 布拉格 D 線開挖；
  - 孟買無人駕駛列車；
  - 聖地牙哥 9 號線合約；
  - 羅馬電車電纜採購。
- 問題：
  1. **本週最大事件（蔚山車庫遷移，12 來源）未列入**；瑞士電車延伸也未列入。
     - 原因是 Category helper 引文抄錯（12 篇韓文長文），以及抄錯 69 字元候選 ID。這與 RC-9、RC-15 已在他處修正的根因相同。
     - Category 把無效提案記為 `CATEGORY_UNRESOLVED` 領域狀態，而不是技術缺口，所以報告的技術缺口數沒有計入這兩則。
  2. 兩則標題夾雜韓文（「경남道長…」「울산市議會…」）；Validator 的語言檢查沒有攔下。
  3. 「國家／地區：未能確認」偏多，例如東京、名古屋、利馬、慕尼黑、蘇黎世。來源沒有明寫國名，而地名參照表沒有涵蓋這些城市或系統。
  4. 少數價值偏低：墨爾本設計獎、蘇黎世道路車輛擦撞。
  5. Scope 有 34 筆提案違反契約（多為標籤不在引文內），另有 6 筆無法解析，都列為已揭露的技術缺口。


## 22. RC-16 上線後以 journal 重驗同一週（2026-10-22）

**修改：** RC-16（`8b3b9c2`）。
- Category、Taxonomy、Reportability 改用 Python 指定的短來源代號（M1、M2…）與句子 ID 引用，helper 不再抄寫原文或候選 ID。
- Category 提案違反契約時，改為已揭露的技術缺口，不再當成 `CATEGORY_UNRESOLVED`。
- 1,037 個測試通過；Golden 預期結果未變。

**重驗方式：** 沿用本輪 journal。
- Evidence、Scope、Event Identity 與未變的 Writer／Validator 請求全部重播。
- 只有 Category、Taxonomy、Reportability 與受影響的事件實際呼叫。
- 用量：7 分鐘、MaiAgent **100 次**（Category 34、Taxonomy 29、Reportability 29、Writer 4、Validator 4）、HTTP 0（另有 3 次先前未記錄的暫時性請求）、未寄信。
- 本輪累計：MaiAgent 982/1,000、HTTP 2,477/2,700、110/170 分鐘。

**結果：** 正式週報 [runs/p2_round2/final_report.md](runs/p2_round2/final_report.md)，**25 則事件**（前版 22 則：[attempt6_report/](runs/p2_round2/attempt6_report/)）。

| 項目 | RC-16 前 | RC-16 後 |
|---|---:|---:|
| Category 無效回應 | 2（未揭露） | **0** |
| Taxonomy 提案違反 | 1 | **0** |
| Reportability 提案違反 | 0 | 0 |
| 通過 Validation 的事件 | 22 | **25** |
| 揭露的技術缺口 | 42 | 41（Scope 40、Validator 1） |

- **新增四則：**
  - 蔚山城市鐵道 1 號線車輛基地遷址（12 篇合併）；
  - 日內瓦電車 17 號線延伸至法國；
  - 伯恩至奧斯特蒙迪根電車線獲建設許可；
  - 里昂 T10 電車線銜接工程期間 T4／T2 調整。
- **刪除一則：** 光州議員質詢。Category 依證據判為 `RECOMMENDATION_WITHOUT_ADOPTED_ACTION`，屬合法領域判定；也消除了先前與市長發言重複的問題。

**剩餘問題：**
- 光州 2 號線「首列電聯車進場」仍被誤併入市長發言事件。Event Identity 請求未變，所以重播的是同一份提案。
- Scope 提案違反 34 筆、無法解析 6 筆，是目前最大的技術缺口來源。
- 「國家／地區：未能確認」仍偏多。
- PDF 與寄信尚未驗證。


## 23. Scope 技術缺口離線分析與 RC-17（2026-10-22，未實測）

**方法：** 以本輪 journal 重建 40 筆 Scope 缺口的請求，重播當時記錄的 helper 回應，未新增任何呼叫。34 筆違反契約的情況全部能逐筆重現。

**根因：**
1. **只引用單一句子**：24 筆端點不在關係引文內的違反中，有 18 筆其實是同一事件、跨相鄰兩句的正確關係（例如車站在一句、系統在下一句），helper 只引用了其中一句。
2. **驗收工具缺陷**：6 筆「無法解析」的回應，是完整提案後面接著模型的贅字。journal 把這類 HTTP 200 回應也存了下來，使 RC-6 的重試只是重播同一份錯誤回應。
3. **helper 自身錯誤（16 筆）**：標籤被改寫成詞形變化或同義詞（例如來源寫 `agredidos`、標籤寫 `agresión`）、系統名稱只出現在頁面標題、端點超出事件焦點範圍。

**修正（`4b70790`）：**
- **RC-17（§A.11）**：事件焦點已確定時，關係引用句至少要含一個端點，且所有端點都須位於事件焦點範圍內。
  - 「關係引用須在焦點內」的檢查會先執行，所以不會跨事件借用。
  - 焦點未確定時，沿用 RC-8 規則。
  - 標籤仍須為原文；頁面標題不作為 Evidence。
- **journal**：只保存並重播可解析的回應，讓 RC-6 的重試成為真正的重試。
- 測試：1,038 個通過。

**離線效果（同一週，不新增呼叫）：**

| 項目 | 修正前 | 修正後 |
|---|---:|---:|
| Scope 技術缺口 | 40 | **26**（6 筆待真實重試、20 筆 helper 違反） |
| IN_SCOPE | 70 | **81** |
| 進入 Event Identity 的紀錄 | 54 | **65** |

- 這 26 筆缺口包括：6 筆無法解析（待真實重試），以及 20 筆真正違反契約（6 筆改寫標籤、5 筆端點在焦點外、5 筆關係引用在焦點外、4 筆其他）。
- 65 筆超過 RC-15 每批 60 筆的上限，會分成兩批送出，跨批的重複事件無法合併。

**未實測：** 使用者決定暫不實測。新增 IN_SCOPE 事件的正式報告內容尚未驗證，下游呼叫預估約 85～95 次。


## 24. Event Identity 跨批次與正式週報品質（離線，2026-10-22）

**Event Identity（RC-18，`d1610bc`）：**
- **根因：** RC-15 每批最多 60 筆。本週 RC-17 之後有 65 筆，被切成 60＋5 兩批，但這 65 筆的總內容只有 56,175 字元，遠低於 66,000 字元的上限。真正限制模型的是請求內容大小，不是筆數。
  - 落在第二批的 5 筆，多半是第一批已有事件的其他報導：蔚山、梁山、利馬、光州電聯車、首爾 CNN、首爾安全統計。它們永遠無法與第一批合併。
- **修正：**
  - 取消筆數上限，只保留內容上限。
  - 超過上限時，先統一縮短每筆的開頭摘錄（6 句／900 字 → 4／600 → 3／450 → 2／300）。
  - 仍放不下才依發布時間分批，並記錄 `PROPOSAL_BATCH_SPLIT` 診斷。
- **離線驗證：** 本週 65 筆合成單一請求，86,691 bytes，與先前 live 驗證過的 59 筆請求（86,806 bytes）同一量級。
- **合併錯誤：** 先前認為的光州「錯誤合併」並非 helper 判斷錯誤。Herald 那篇同時報導了電聯車進場與市長發言，helper 引用的正是其中進場那一句。問題在下游：Writer 只寫了市長發言。
- **未驗證：** 65 筆單一請求的實際分群結果需要 live 呼叫（1～2 次）。

**國家／地區（RC-19，`1c19d9c`）：**
- 根因：來源值是線名或營運機構名（例如 `名古屋市交通局`、`桃園捷運綠線`），只做整值查表，所以查不到。
- 修正：整值查不到時，若值內包含的參照表名稱都指向同一地區，就據此解析；歧義名稱不算，拉丁字母須整詞相符。參照表升為 geo-reference-v2。
- 離線效果：142 筆 READY 中，無法辨識的值 57 → 19，依參照表解析 24 → 61。

**其他：** Writer 欄位前後的空白一律去除（例如原標題開頭的空格）。

**仍存在、但無法只靠離線修正的品質問題：**
1. **metadata 擷取把文中提到的所有系統、地點都列出**（例如梁山線與其轉乘的釜山 2 號線），導致欄位被判為衝突、不予採用。運輸系統約 7 則、國家約 36 筆 READY 因此無法確認。需改 metadata 提示詞並重新擷取，屬付費 live。
2. **合併事件的成員系統名稱不同**（例如韓文與英文寫法），依 §K 規定不可選用 canonical 成員的值。是否改為顯示 canonical 成員的值，需使用者決定契約。
3. **韓、日文專有名詞夾在中文標題中**（例如「경남道長」「울산市議會」）。Writer 規則是「無公認中文名時保留原文、不得猜譯」，因此是否強制中文化屬產品風格決策。
4. **少數價值偏低的事件**（墨爾本設計獎、蘇黎世道路車輛擦撞），屬 Reportability 判斷。
5. **Scope 仍有 20 筆 helper 違反契約**（改寫標籤、端點在焦點外），需改提示詞並重新判斷，屬付費 live。


## 25. 報告品質（RC-20）與 PDF／Email 交付準備（離線，2026-10-22）

**光州事件的根因：** Scope 已確認每篇報導各自的「候選事件」：Herald 是市長警告，Polinews 是電聯車進場。但 Event Identity 送的是文章開頭，helper 因此依 Herald 文中順帶提到的進場句子，把兩個不同的候選事件合併。Writer 再依 Herald 自己的事件撰寫市長警告，進場事件就此消失。

**修正（RC-20，`46fbdfd`）：**
- **Event Identity**：改送每筆紀錄經 Scope 驗證的事件焦點句；沒有焦點紀錄時才用文章開頭。離線檢查顯示 Herald 的摘錄已只剩市長警告；同一週 54 筆的請求也從約 87 KB 降到約 48 KB（不再夾帶網站選單等雜訊）。
- **Writer**：收到 canonical 成員的 `event_focus`，只撰寫該事件。
- **名稱與語言**：韓、日文名稱有既有中文名就用中文名，否則保留完整原文，不得在同一名稱內混寫。Validator 以確定性規則擋下韓文與漢字黏連的詞（例如「경남道長」「울산市議會」），不需 helper 呼叫，並把這些詞交給那一次改寫。
- **metadata**：每個欄位只擷取主要事件的單一值，不再列出文中所有提到的系統或地點。
- **系統名稱顯示**：合併成員的系統名稱不同時，顯示 canonical 成員自己的值（與報告引用的來源一致），衝突仍記錄為診斷。地點維持原規則（衝突時省略）。
- **Reportability**：明列一般低價值類別：
  - 獎項、排名、媒體讚譽；
  - 視察、訪談、議會質詢、官員發言，但未記錄具體決定、時程變更、測試結果、核准或安全措施者；
  - 輕微的路面車輛與電車擦撞（無人受傷、未出軌、無重大損壞或停駛）。
- **Scope 提示詞 v9**：標籤須逐字照抄來源（保留詞形變化），關係引文須包含所有含端點的句子。

**PDF／Email（`0e326e5`）：**
- **PDF**：把組裝好的報告內容逐行轉為 A4 PDF，依文字別嵌入 TrueType 字型（中、韓、日假名）。
  - 先前 V1 用的 reportlab 內建 CID 字型未嵌入，實測轉圖後是亂碼，因此不沿用。
  - 本週 25 則報告：8 頁、455 KB，以 PyMuPDF 轉圖檢查內容正確。
  - 找不到可用字型時直接失敗，不會寄出破損的 PDF。
- **Email**：Gmail 寄件附上 PDF；PDF 無法產生就不寄，並記為交付失敗。
- **`main.py --output-dir`**：輸出 Markdown、PDF 與執行摘要。
- **GitHub Actions**：安裝 `fonts-wqy-zenhei`；只要 CLI 有執行過，就上傳輸出檔保留 90 天（健康檢查失敗則不上傳）。
- **仍未完成**：
  - `LIVE_EMAIL_SEND` 仍為 0，尚未實際寄出任何信。
  - 正式排程（cron）尚未設定。
  - 寄件主旨仍是機械識別碼。

**目前 25 則報告中的不合格內容（依前次 live 結果）：**
1. 「경남道長…」「울산市議會…」兩則標題韓文與漢字混寫；其中市議會那則依新規則屬低價值。
2. 墨爾本 G Class 設計獎、蘇黎世路面車輛與電車擦撞：依新規則屬低價值。
3. 光州電聯車進場事件遺漏（錯誤合併所致）。
4. 國家／地區、運輸系統顯示「未能確認」偏多。RC-19 已在離線改善國家解析；運輸系統待新的 metadata 擷取。
5. 名古屋那則的來源網址是圖片頁（livedoor image_detail），屬 Evidence 取得的瑕疵，尚未處理。

**整合 live 驗收預估（同一週，以 journal 重播 Search、連結、頁面與語意判定）：**

| 項目 | 呼叫數 |
|---|---:|
| metadata 擷取 | 142 |
| Scope | 142 |
| Event Identity | 1～2 |
| Category | 約 40 |
| Taxonomy | 約 33 |
| Reportability | 約 33 |
| Writer 與改寫 | 約 33 |
| Validator | 約 35 |

- 合計約 460，加 5% 重試約 485 次。


## 26. 整合 live 驗收（RC-20～RC-22，2026-10-22）

**預算（本輪核准：MaiAgent 550、HTTP 50、90 分鐘，不寄信）：** 實際使用 MaiAgent 515 次、HTTP 7 次、約 40 分鐘，未寄信。Search、連結、頁面與 Evidence 判定由 journal 重播。

**執行經過：**
1. **第一次執行，Event Identity 72 → 72，沒有任何合併。**
   - 根因：helper 把 3 筆紀錄各放進兩個群組，都是把同一事件拆成兩群（例如蔚山 12 篇＋經由其中一篇連到的第 13 篇）。
   - RC-15 規定「同一紀錄出現兩次即整份回應無效」，因此其餘 14 個有效群組也一併作廢。
   - 已在 Category 階段停止，避免把預算花在未合併的事件上。
2. **RC-21（`b6ea1a7`）：**
   - 同一紀錄可出現在多個群組；每群只提出群內的同事件配對，由既有 complete-link 分組決定，未被一起提議的紀錄不會合併。
   - 同一群內重複列出的紀錄只使該群無效。
   - 提示詞 v2：要求同一事件只放一個群組，並說明不同城市、國家或系統的事件是不同事件。
3. **第二次執行，72 → 42，helper 仍把同類型但不同地點的事件合在一起：**
   - 大邱火災演練＋名古屋脫軌演練（韓國／日本）
   - 新北三鶯線供電異常＋胡志明市地鐵停電（臺灣／越南）
   - 奧斯陸電車與計程車相撞＋薩拉戈薩電車司機遭攻擊（奧斯陸國家未能確認／西班牙）
   - 大田電車延後＋光州市議會質詢（同為韓國）
   - 前兩組在報告組裝時會因國家衝突（RC-5）整則排除，連帶失去真實事件。已再次停止。
4. **RC-22（`e433281`）：**
   - 同一事件只發生在一個國家／地區。
   - 提案配對兩端的 EvidenceService 地區都已確立且不同時，Event Identity 不採用該配對，並記錄 `PROPOSAL_REGION_CONFLICT` 診斷；同群其他配對照常。
5. **第三次執行（重播第二次的 helper 回應）：**
   - Event Identity 72 → 44；大邱、胡志明市各自獨立，名古屋兩篇仍合併。
   - 正式週報 32 則，狀態 `SUCCESS_WITH_TECHNICAL_GAPS`。

**各階段：** Evidence 392 → 143 READY → Scope 85 IN → Temporal 72 → Event Identity 44 → Category 40（4 則無法分類）→ Reportability 39 → Writer 39 → Validator 通過 32、未通過 2、技術缺口 5。

**技術缺口 23：**
- Scope 18：標籤 7、焦點外 3、關係包含 6、其他 2。
- Validator 5：引文無效。

**與前一版 25 則報告相比的改善：**
- 合併：
  - 蔚山車輛基地 13 篇合為 1 則；
  - 利馬 3 篇、梁山 4 篇、名古屋 2 篇、孟買 2 篇、日比谷線 2 篇也各合為 1 則。
- 光州：電聯車進場（技術新知）與市長發言（營運動態）分別成報，進場事件不再遺漏。
- 語言：內文沒有任何韓文或日文，韓文地名、機構皆改用中文（蔚山、梁山、慰禮線、大田、光州）。
- 新增成報：胡志明市地鐵停電、新北三鶯線供電異常、大邱火災演練。

**品質稽核：仍不合格或有疑慮的內容：**
1. **錯誤合併仍有 2 組進入報告：**
   - **奧斯陸＋薩拉戈薩**：標題與摘要寫奧斯陸，但國家顯示「西班牙」、系統顯示「tranvía de Zaragoza」；薩拉戈薩事件因此消失。奧斯陸那篇的國家值未能解析，所以 RC-22 擋不到。
   - **大田＋光州**：同為韓國，RC-22 擋不到。光州市長發言那則內容正確，但一篇大田氫能電車報導（한겨레）被列為它的成員；大田另有一則由其他兩篇構成，因此沒有遺漏。
2. **梁山重複：** 「試運轉期間檢視」與「進入最後準備階段」兩則是同一件事（helper 漏列其中一篇）。
3. **低價值事件仍成報：**
   - 墨爾本電車設計獎：RC-20 明列獎項為不成報，helper 仍判 REPORTABLE；
   - 蘇黎世卡車擦撞電車：helper 以「車窗嚴重損壞」判可報；
   - 蔚山市議會委員會會議：屬議會討論、未記錄具體決定。
4. **Writer 格式與用語：**
   - 兩則標題前加了「🔹 [營運政策]」，PDF 中 🔹 顯示為空框；
   - 蘇黎世那則內文出現內部用語「候選資料」；
   - Validator 都沒有攔下。
5. **國家／地區「未能確認」4 則：** 日內瓦（跨境）、那不勒斯、華沙、蘇黎世。
6. **系統名稱以來源語言顯示：** 例如「부산지하철」「メトロ1号線」「新北メトロ（MRT）三鶯線」「Metro di Xiamen」，以及華沙來自韓文來源的「바르샤바 트램」。「도시철도 1호선」也沒寫出城市。
7. **廈門新線：** 實際開通是 9 月 16 日，因報導發布於本週而成報。這依現行日期契約以發布日為準，但內容並非本週事件。

**PDF／Email：**
- PDF：10 頁、455 KB，中、韓、日字型正確嵌入。
  - 只有 🔹 呈空框；
  - 「Sydney’s」的彎引號字寬過大。
- Email：仍未實際寄出（`LIVE_EMAIL_SEND` = 0）；正式排程未設定；寄件主旨仍是機械識別碼。

**需要使用者決定的事項：**
- **Event Identity 批次 helper 在 72 筆規模下會依「事件類型」而非「同一次發生」分群**：第二次回應 15 群中 4 群錯誤。RC-22 只擋得住國家已確立且不同的情況。可能做法：
  - **(a)** 對每個提議群組再做一次確認呼叫，每週約多 15 次；
  - **(b)** 依已確立的國家分批送出，同國以外不比對；
  - **(c)** 接受現況並在報告揭露。
- **系統名稱是否中文化顯示：** 目前依 RC-4 顯示來源原文值。


## 27. RC-23 群組確認的 live 重驗（2026-10-22）

**預算（核准：MaiAgent 100、HTTP 10、30 分鐘，不寄信）：**
- 實際用量：MaiAgent 61 次、HTTP 2 次、約 6 分鐘，未寄信。
- MaiAgent 明細：Event Identity 確認 13、Category 9、Taxonomy 9、Reportability 9、Writer 10、Validator 11。
- 其餘呼叫由 journal 重播，包括 Event Identity 批次提案本身。

**Event Identity：** 72 筆 → 51 則事件（前次 44 則），沒有技術缺口。
- **確認通過的群組：** 梁山 4、利馬 3、首爾受傷統計 2、日比谷線 2、光州電聯車進場 2、慰禮線 2、名古屋 2、孟買 2，以及蔚山 11 篇。
- **正確擋下的錯誤合併：**
  - 奧斯陸電車與計程車相撞 ≠ 薩拉戈薩電車司機遭攻擊：薩拉戈薩事件恢復成報。
  - 大田氫能電車報導 ≠ 光州市長發言：光州事件不再夾帶大田的來源。
  - 大邱 ≠ 名古屋、新北 ≠ 胡志明市：已由 RC-22 擋下。
- **過度拆分（helper 確認時漏列成員）：**
  - 蔚山 13 篇中有 2 篇（뉴시스、울산매일）未被列入確認群組，報告因此出現 3 則蔚山車輛基地事件。
  - CNN 首爾地鐵 2 篇未確認；這是同一則報導，但該事件本來就無法分類，不影響報告。
- **可討論的拆分：**
  - 光州市議員質詢與市長答詢（同一場會議、不同發言）；
  - 大田市民團體聲明與工程契約報導。

**正式週報：** 36 則（前次 32 則），狀態 `SUCCESS_WITH_TECHNICAL_GAPS`，PDF 11 頁。
- **新增：**
  - 薩拉戈薩事件（獨立成報）；
  - 大田市民團體聲明、大田氫能電車（兩則與既有大田事件高度相關）；
  - 蔚山車輛基地重複 2 則。
- **消失：** 奧斯陸電車相撞。拆開後成為獨立事件，但 Validator helper 回傳無效的句子引用，成為技術缺口。

**技術缺口 24：**
- Scope 18：與前次相同，由 journal 重播。
- Validator 6，都是引文無效。被排除的事件包括：
  - 日比谷線自動駕駛過站 300 公尺（3.4 萬人受影響）
  - 奧斯陸電車相撞（6 人送醫）
  - 里斯本地鐵全站關閉 24 小時
  - 馬德里電扶梯更新
  - 巴黎 T10 施工
  - 阪急在菲律賓的實證
- 這些都是有報導價值的事件，Validator 引文缺口已是遺漏重要事件的主因。

**仍不合格的內容：**
1. **重複事件：** 蔚山 ×3、梁山 ×2、大田 3 則高度相關。
2. **Writer 標題前綴：** 「🔹 [營運政策]」「🔹營運爭議｜」「🔹 重大事故｜」等共 4 則，PDF 中 🔹 顯示為空框，Validator 沒有攔下。
3. **低價值事件仍成報：** 墨爾本設計獎、蘇黎世擦撞、蔚山市議會委員會會議。
4. **國家／地區「未能確認」4 則，系統名稱以來源語言顯示：** 同 §26。

**建議下一步（依影響排序，皆可先離線處理）：**
1. **Validator 引文缺口：** 6 則有價值的事件因 helper 引用無效句子 ID 而遺漏，需先離線分析這些回應的錯誤型態。
2. **Writer 標題格式：** 在 Validator 以確定性規則檢查標題不得含分類標籤或符號前綴，並修正 Writer 指示。
3. **Event Identity 確認漏列成員：** 大群組（13 篇）確認時，helper 會漏掉成員。
4. **Reportability 未遵守 RC-20 低價值類別：** 例如墨爾本設計獎。


## 28. Validator 引文缺口與標題格式（RC-24，離線，2026-10-22）

**根因（以 journal 離線重播 §27 那次執行的 54 次 Validator 回應）：** 6 則有價值的事件（日比谷線過站、奧斯陸電車相撞、里斯本全站關閉、馬德里電扶梯、巴黎 T10、阪急菲律賓實證）因 `INVALID_CITATION` 遺漏。
- 5 則：「臺北捷運局啟示」單元被評為 ANALYSIS，卻沒有引用任何 Evidence 句子。
  - 契約 §N 規定 ANALYSIS 必須引用前提，Python 判為無效是正確的。
  - 但 helper 指示只寫「需有 Evidence 支持的事實前提」，沒說必須引用。全部 72 個 ANALYSIS 單元中，67 個有引用、5 個沒有。
- 1 則：helper 抄寫 64 字元的候選 ID 時打錯（前 12 字元相同）。

**修正（RC-24，`0dc6a4d`）：**
- Validator 請求改以短來源代號（M1…）加句子 ID 引用，與 RC-16 的 Category、Taxonomy、Reportability 一致，helper 不再抄寫候選 ID。
- Validator 提示詞 v4 明示：SUPPORTED 與 ANALYSIS 單元都必須引用至少一個句子（ANALYSIS 引用其事實前提）；無法引用前提的單元為 UNSUPPORTED。Python 規則不變。
- 標題格式：
  - Writer 提示詞 v5：標題為單行純文字，不得加 emoji、符號或分類標籤前綴，也不得提及請求或輸入（如「候選資料」）。
  - Validator 以確定性規則擋下含 emoji、或以括號／直線標籤開頭的標題，不需 helper 呼叫，並把前綴交給那一次改寫。
- 契約 §A.18；§N 的回應格式範例同步更新為 `source_ref` 加 `sentence_ids`。

**離線驗證：**
- 測試 1069 全過，Golden 未修改。
- 標題規則套用到兩次 live 報告的 75 個不同標題：正好擋下 4 個有前綴的標題，沒有誤判（含 ℃、連字號、拉丁名稱的標題都通過）。

**未驗證（需付費 live）：** helper 在新提示詞下是否確實引用 ANALYSIS 前提，以及 Writer 是否不再加標題前綴。重驗同一週預估：
- MaiAgent 約 110 次：Writer 44、Validator 44、改寫與重驗約 16，另加重試。
- HTTP 0，約 10 分鐘。
- 依使用者指示，本輪不實測。


## 29. 蔚山／大田重複的根因與自動交付（RC-25、RC-26，離線，2026-10-22）

**蔚山（Event Identity 問題）：**
- 依 journal 重播 RC-23 那次執行的確認回應：13 篇的確認回應把 11 篇放同一群、울산매일 單獨成群，뉴시스 則完全沒列出。
- 울산매일 是 10 月 14 日「市府內部決定遷移、市長指示說明與法律諮詢」，屬較早的另一次發生，依契約應分開。
- 뉴시스 報導的是 10 月 19 日同一場記者會，是真正的重複。
- **根因：** RC-23 要求 helper 把「不同事件」的紀錄直接省略，所以「遺漏」與「否決」無從區分。該次所有正確的否決（奧斯陸／薩拉戈薩、大田／光州、大邱／名古屋、CNN）也都是以省略表達。

**大田（不是 Event Identity 問題）：** 三篇是三件不同的事，Event Identity 分開是正確的；合併反而是錯誤合併：
- 10/15 ATN 揭露工程契約到 2029 年 2 月；
- 10/19 市民團體聲明；
- 10/20 한겨레 回顧 30 年歷程的專題。

重複感來自 Reportability 讓「無具體決定的聲明」與「無新發生事項的專題」成報。

**修正：**
- **RC-25（`f763f15`）：**
  - 確認請求標示 `confirmation`，helper 必須把每筆紀錄恰好列一次，不同事件者各自單獨成群。
  - 被遺漏的紀錄視為未決定：不合併，並揭露為 `CONFIRMATION_INCOMPLETE` 技術缺口（報告註明可能含重複），Python 不把遺漏當作同意。
  - Reportability 提示詞 v5：低價值類別擴及政治人物、民間團體、評論者的聲明與批評，以及無新發生事項的專題、背景、評論文章。
- **離線驗證：** 以同一週已記錄的批次與確認回應重算，得到同樣 51 則事件。沒有新增合併，原有的正確合併全部保留；先前以省略表達否決的 6 次確認則被揭露。實際能否消除 뉴시스 重複，需要 helper 在新提示詞下的回應。

**自動交付（RC-26，`5c4c754`）：**
- **報告期間：** 報告記錄並顯示「報告期間：2026-10-14～2026-10-20」，並納入 artifact 識別。
- **寄件主旨：** 「捷運技術週報｜2026-10-14～2026-10-20｜N 則」，報告與 artifact 識別改放在郵件標頭。
- **持久寄送紀錄：** 只存雜湊，同一 artifact 或同一期間與收件目標不會再寄第二次。原本只存在記憶體，自動化重新執行同一週會產生新 artifact 而再寄一次。
- **失敗可見：** 寄送 FAILED 時 CLI 以非零結束，排程不會顯示成功。
- **GitHub Actions：**
  - 每週一 01:00 UTC 排程，期間為前一週一至週日；
  - 須設 repository variable `WEEKLY_REPORT_SCHEDULE=enabled` 才會執行；
  - 實際寄信須 dispatch 勾選 `send_email`，或排程搭配 `LIVE_EMAIL_SEND=1`；
  - 寄送紀錄以 Actions cache 跨執行保存，執行不重疊，輸入只經由環境變數傳入 shell。

**測試：** 1079 全過，Golden 未修改。

**仍待 live 驗收的項目：**
- RC-24：Validator 是否確實引用 ANALYSIS 前提；Writer 是否不再加標題前綴。
- RC-25：確認回應是否完整列出每筆紀錄；Reportability 是否濾掉聲明與專題。
- 實際 Gmail 寄送（含 PDF 附件）：從未執行。


## 30. 整合 live 驗收與首次實際寄送（RC-24～RC-26，2026-10-22／28）

**預算（核准：MaiAgent 200、HTTP 10、40 分鐘）：**
- 實際用量：MaiAgent 174 次、HTTP 2 次、約 15 分鐘。
- MaiAgent 明細：Event Identity 13（批次 1、確認 12）、Category 4、Taxonomy 4、Reportability 44、Writer 52、Validator 57。
- 寄送步驟以 journal 副本離線重播，沒有任何 MaiAgent 或 HTTP 呼叫。

**正式週報：** 37 則（前次 36 則），狀態 `SUCCESS_WITH_TECHNICAL_GAPS`，標題下方顯示「報告期間：2026-10-14～2026-10-20」。

**RC-24 驗證結果：**
- Validator 引文無效：6 → 0。
- 日比谷線過站、奧斯陸電車相撞（metadata 正確）、馬德里電扶梯、巴黎 T10、墨西哥城 9 號線火警、孟買列車，都已成報。
- 標題前綴：4 → 0；「候選資料」等內部用語也未再出現。
- 新的副作用：ANALYSIS 改為必須引用前提後，聖地牙哥 9 號線合約、萬大中和線、里斯本全站關閉三則的「臺北捷運局啟示」被判無依據，改寫後仍未通過，列為驗證 FAIL。過去這類情況會成為引文技術缺口。
- 胡志明市停電、阪急菲律賓實證：MaiAgent 平台兩次回傳無法解析的內容，列為技術缺口。

**RC-25 驗證結果：**
- 蔚山：19 日記者會的 12 篇合為 1 則（뉴시스 已併入）；14 日市府內部決定另列 1 則，依契約屬另一次發生。
- 蔚山市議會委員會會議：已依新的低價值類別不成報。
- 光州：市議員質詢與市長答詢（同一場會議）合併；CNN 兩篇合併。
- 大田：
  - 市民團體聲明被併入 ATN 契約報導。依嚴格規則兩者是不同的發生，屬邊界合併，但內容以契約報導為主，讀者不受誤導。
  - 한겨레 專題仍成報，新的專題類別沒有擋下。
- 確認不完整 2 次，已揭露：
  - 慰禮線兩篇 정진철 報導因此未合併，報告出現 2 則相關項目；
  - 報告已註明「可能含重複報導的事件」。
- 梁山仍 2 則（知事試乘、最後準備階段）。
- 低價值仍成報：墨爾本設計獎（helper 以「採購策略」得獎為由）、蘇黎世擦撞（helper 以車窗損壞為由）。

**首次實際寄送（RC-26，使用者核准）：**
- 2026-10-28 以正式交付路徑寄出一次，結果為 `SENT`，收件者為 `.env` 的 DEFAULT_RECIPIENTS。
  - 主旨：「捷運技術週報｜2026-10-14～2026-10-20｜37 則」
  - 內文為正式週報全文，附 PDF。
- 寄送內容確認與稽核過的 `final_report.md` 逐字相同。
- 持久寄送紀錄 `journals/p2_round2/delivery_ledger.json` 有 1 筆，只存雜湊，不含收件地址；同一期間與收件目標再次執行會被判為 DUPLICATE。

**剩餘問題：**
1. 「臺北捷運局啟示」被判無依據而淘汰整則事件：本次 3 則。
2. MaiAgent 平台偶發無法解析的回應：本次 2 則。
3. Event Identity 確認仍偶有遺漏：本次 2 次，已揭露，但仍造成重複。
4. Reportability 未完全遵守低價值類別。
5. Scope 技術缺口 18 則，自 §26 以來未處理。
6. 國家／地區「未能確認」5 則；系統名稱以來源語言顯示。
7. GitHub Actions 尚未在雲端實際執行，未 push；排程與寄信變數也尚未設定。


## 31. 正式 PDF 審查後的離線品質修正（RC-27，2026-10-28）

依使用者對 2026-10-14～20 正式 PDF 的審查，以 journal 離線重播（可完全重現寄出的報告，共 715 次 helper 呼叫）逐項對照原始 Evidence。

**確認並修正：**
1. **國內新聞範圍：**
   - 臺灣新聞是在 Search 階段被排除（契約為 `INTERNATIONAL_EXCLUDING_TAIWAN`，RegionRegistry 禁止臺灣市場）。Scope、Category、Reportability 並無排除；三鶯線是經由日文報導進入報告。
   - 現已改為國內＋國際：臺灣列為 zh-TW 市場，search-discovery-v7，每週多 5 次 RSS 查詢。
2. **臺北捷運局啟示驗證：**
   - 聖地牙哥 9 號線、萬大中和線、里斯本三則被淘汰，根因是 RC-24 的提示詞。
   - 啟示中「只提出建議」的單元，前提寫在前一單元，因此被判為 UNSUPPORTED。
   - 已更正：建議型單元屬 ANALYSIS，引用事件句子；只有陳述無依據事實的單元才是 UNSUPPORTED。
3. **低價值事件：**
   - helper 自行套用政策時會找理由保留，例如墨爾本設計獎被說成「採購策略得獎」。
   - 現改由 helper 標示主要發生類型，Python 依契約將獎項排名、視察與發言、背景專題判為不成報。
4. **國家／地區：**
   - 韓日文來源以自身文字寫國名（如 폴란드），參照表沒有收錄。
   - geo-reference-v3 補齊所有地區的韓日文國名與德文城市形容詞。
   - 本週無法解析的值 15 → 12，沒有任何紀錄改變地區；華沙（波蘭）、蘇黎世（瑞士）將可正確顯示。
5. **啟示品質：** Writer 須依本事件的具體設備、方法、數據或合約條款提出建議；臺灣事件不得聲稱捷運局本身的角色或狀態。
6. **慰禮線重複：**
   - 兩篇報導是同一場 10/15 的會談，確認回應回傳空清單，違反 RC-25。
   - 提示詞已明示空清單不是有效的確認回應。

**屬合理的不同事件或分類：**
- 蔚山兩則：10/14 是市府內部決定加上市長指示，10/19 是正式記者會，依契約為兩次發生。
- 釜山罷工的「電聯車、月臺門」：罷工者是車輛重維修與月臺門檢修人員，來源有據。
- 布爾諾的「自動收費」：招標要求電車配備電子票證，來源有據。
- 日內瓦的「未能確認」：跨境路線同時對應法國與瑞士，屬真正的歧義，不予猜測。

**仍需 live 驗證：**
- Reportability 新類型分類是否正確濾掉低價值事件。
- 建議型啟示是否通過驗證。
- 確認回應是否不再回傳空清單。
- 臺灣市場的實際搜尋成果。
- 奧斯陸、那不勒斯的城市與系統名稱：metadata 擷取只取到路口或站名，改提示詞需重跑全部 143 次擷取，暫不處理。

**測試：** 1085 全過，Golden 29 全過且未修改；commit `acd0794`。


## 32. RC-27 整合 live 驗收（2026-10-28）

**預算（核准：MaiAgent 260、HTTP 80、45 分鐘，不寄信）：** 實際使用 MaiAgent 190、HTTP 52、約 19 分鐘，未寄信。
- 臺灣搜尋探測：HTTP 5（20 則結果）。
- 第一次整合執行：MaiAgent 164、HTTP 44，產出 35 則。
- 從 journal 續跑：MaiAgent 8、HTTP 3，補回 4 則技術缺口，產出 39 則。
- 修正後的抽樣驗證：MaiAgent 18。

**正式週報：** 39 則（基準 37 則），狀態 `SUCCESS_WITH_TECHNICAL_GAPS`，PDF 13 頁，標示報告期間。
- 驗證 FAIL：3 → 0。聖地牙哥 9 號線、萬大中和線、里斯本罷工因 RC-27 的啟示驗證更正而恢復。
- 臺灣新聞：三鶯線、萬大中和線，以及新增的桃園捷運綠線北機廠（臺灣搜尋所得）。
- 低價值：蔚山市議會、大田專題已改為不成報。
- 國家：華沙（波蘭）、蘇黎世（瑞士）已正確顯示。
- 重複：蔚山、慰禮線各只剩 1 則。
- 標題無前綴，啟示具體，例如：
  - 釜山大修每列車需 21 日；
  - 桃園北機廠以水泥拌合工法處理 90 萬立方公尺土壤；
  - 日比谷線自動停站失效時的人工介入。
- 臺灣事件的啟示未聲稱捷運局自身的角色或狀態。

**live 驗收中發現並修正（最早 owner）：**
1. **MaiAgent 平台回應格式：**
   - 平台會把同一答案放兩次（中間夾著 `,"status":"complete"}`），導致第一次執行有 4 則被判無法解析。
   - transport 解析器現在只接受「首尾為相同、非空完整 JSON 物件」的情形；不同、殘缺或空的物件仍判無法解析。
   - 以實際擷取的 live 回應驗證可正確解析。
2. **Scope：**
   - 系統名稱含「捷運」的事件一律被判模式 UNKNOWN（基隆捷運經費及機電統包決標、桃園綠線站體）。
   - 已明列各語言運具詞，台鐵、高鐵、JR 仍非都市軌道（v10）。
   - 抽樣 live 驗證：基隆、桃園 G14/G15 改判 IN；台南台鐵站、百貨開幕維持 OUT；東京、奧斯陸、里斯本、布拉格的對照組不變。
   - 桃園票價那則仍因關係未建立而 OUT。
3. **Reportability：**
   - 墨爾本設計獎被歸為「通車」、知事試乘被歸為「測試」。
   - 已明示主要發生類型以本文新發生者為準（v7）。
   - 抽樣 live 驗證：兩者改判不成報，其餘 6 則對照不變。

以上第 2、3 項須下一次完整執行才會反映在週報中（Scope 提示詞變更會重跑約 150 次 Scope 呼叫，本次預算不足）。

**仍存在：**
- 證據擷取無法辨識部分臺灣新聞網站的主文：公視、華視、大紀元、中央社日文版。基隆公視那篇因此被拒；蕃新聞版本可由上述 Scope 修正補回。
- 系統名稱以來源語言顯示（부산지하철、メトロ1号線）；那不勒斯標題保留「Napoli」。
- 國家或系統「未能確認」5 則：日內瓦跨境、那不勒斯、奧斯陸、名古屋系統、蘇黎世系統。
- Event Identity 確認仍有 2 次不完整（已揭露）。

**測試：** 1087 全過；Golden 29 全過且未修改。


## 33. 正式收錄國家資格（RC-28，離線，2026-10-28）

**問題：** GitHub Actions Run 40623936647（2026-10-21～27）的 32 則正式報導中，9 則位於非指定國家／地區（烏克蘭 3、中國大陸、泰國、印度、孟加拉、越南、秘魯）。

**Root cause：**
- Search 只決定查詢哪些 Google News 版本，而各版本會報導世界各地的新聞。
- EvidenceService 確立的事件所在地（RC-4）只用於顯示。
- 沒有任何 owner 把所在地與核定名單比對。

**修正（`7571b60`）：**
- **名單唯一來源：** RegionRegistry。每個市場新增 ISO `region_id`，`formal_region_ids` 為 20 個核定市場（含臺灣），selected／global 與所有入口一致。
- **判定 owner：** ReportService 正式 metadata 投影，在 Writer 之前執行。依據是成員 Evidence 確立的所在地，不使用搜尋市場、媒體、網址或模型常識。
  - 確立且屬指定地區：收錄。
  - 確立但不屬指定地區：`NON_DESIGNATED_REGION` 排除（範圍外，記錄於執行摘要與 trace）。
  - 無法確立：`REGION_NOT_ESTABLISHED` 排除，並於報告揭露。
- 新增 Golden R01–R07：以正式的地區名單執行正式投影。

**離線重新判定：**
- Run 40623936647 的 32 則：保留 16；排除非指定地區 9（正是上述 9 則）、所在地無法確立 7。這 7 則實際在指定國家（韓國、馬賽、洛杉磯、紐約、巴塞隆納、貝加莫、里昂），但來源 metadata 未能確立國家。
- 本機 journal 週（2026-10-14～20）以實際流程離線重播：39 → 24 則，保留的 24 則與原報告逐字相同且全屬指定地區；排除非指定 12、無法確立 3（日內瓦跨境、那不勒斯、奧斯陸）；未呼叫 MaiAgent。

**測試：** 1098 全過；Golden 29＋R01–R07 全過，既有 Golden 未修改。


## 34. RC-28 地理辨識（離線，2026-10-28）

逐一檢查 Run 40623936647 中 7 則「所在地無法確立」事件的出版者原文（以正式擷取與主文解析取得，未呼叫 MaiAgent）。

| 事件 | 原文主文 | 擷取值 | 根因 | 結果 |
|---|---|---|---|---|
| 紐約號誌更新 | 뉴욕 ×17 | 系統「뉴욕 지하철」 | 參照表缺韓文城市名 | 參照表 v4 後離線恢復（美國） |
| 里昂 T9 | Vaulx-en-Velin ×6、Villeurbanne、Lyon | 地點「Vaulx-en-Velin」 | 參照表缺此里昂都會區市鎮 | 參照表 v4 後離線恢復（法國） |
| 洛杉磯 D 線 | ロサンゼルス ×3、LA Metro ×4 | 「メトロDライン」「Wilshire/La Brea駅」 | 擷取取車站；參照表缺日文名 | 須 metadata v4 live 驗證 |
| 馬賽 T2 | Marseille ×3 | 「la place du 4-Septembre」 | 擷取取廣場 | 須 metadata v4 live 驗證 |
| 巴塞隆納 Diagonal | Barcelona ×3 | 「la Diagonal」 | 擷取取街道 | 須 metadata v4 live 驗證 |
| 貝加莫 T2 | Bergamo ×6 | 地點無、系統「T2」 | 擷取未給城市；參照表缺 Bergamo | 須 metadata v4 live 驗證 |
| 韓國全國地鐵 5G | 只有「정부」「과학기술정보통신부」「국회」 | 「전국 지하철」 | 原文未載明國家或城市 | 維持未確認（不得以部會或媒體推定） |

**修正（`0a98d12`，RC-28 規則不變）：**
- metadata 擷取的地點改為來源所寫的城市、市鎮或都會區（v4），只有原文未提城市時才回報街道、廣場、車站。
- 地理參照表 v4：補指定地區城市的韓、日、繁中名稱，以及缺漏的都市軌道城市，共 264 個名稱。排除同時是常用詞的名稱；任一名稱不跨兩地區。

**離線驗證：**
- 本機 journal 週 149 筆 READY 紀錄的地區判定與修正前完全相同。
- 雲端 32 則重新判定：保留 18、非指定 9、無法確立 5（修正前 16／9／7）。

**測試：** 1101 全過；Golden 29＋R01–R07 全過。


## 35. 正式報告品質根因：數字依據與事件合併（離線，2026-10-28）

資料來源為 Run 40623936647（2026-10-21～27，32 則）。出版者原文以正式擷取與主文解析取得；未呼叫 MaiAgent，未寄信。

### 數字依據（RC-29，§A.23）

**錯誤：** 達卡 L&T 訂單原文為「₹5,000 crore to ₹10,000 crore」，正確換算為 500億～1,000億；報告寫成「5,000億至1兆印度盧比」，差十倍。

**根因：**
- **最早階段在 Writer。** 指示只要求以「繁中報告寫法」呈現數字，沒有給精確量級換算，Writer 把 crore（千萬）當成億換算。
- **Validator 沒有擋下。** 數字是否有依據完全交給 helper 對整個單元的語意判斷；Python 只檢查引用結構，不比對數值。
- **同類風險。** 金額、量級、百分比、距離、面積、重量都有相同風險。

**修正：**
- **Writer（formal-report-writer-v7）：** 照來源原數字與量級詞書寫，或只用精確換算；不確定時保留原單位；不得自行加上換算值、單位換算或合計。
- **Validator：** 在 helper 呼叫前，以確定性規則檢查較大、帶量級詞或帶度量單位的數字是否與 Evidence 所載數值相符（`quantities.py`）。不符者使用該事件唯一一次改寫，改寫後仍不符則該事件 FAIL。

**離線驗證：**

| 資料 | 檢查數字 | 標記 | 備註 |
|---|---|---|---|
| 本機 journal 週 | 78 個區塊，94 個數字 | 0 | 無誤判 |
| 雲端 32 則 | 22 個數字 | 2 | 只有達卡的「5,000億」「1兆」；另有 5 則來源本機無法取得 |

**範圍限制：** 日期、件數等小數字不做確定性檢查，以免誤判；這部分仍由 helper 的單元依據判斷。

### 事件合併（Event Identity）

依出版者原文重新判定：

| 案例 | 原文 | 判定 | 雲端結果 |
|---|---|---|---|
| 基輔 A（Yahoo Japan）／B（Infoseek） | 同一則 Reuters 電文：10/26 飛彈攻擊，1 死 7 傷，地鐵站受損 | 同一事件 | 未合併（漏合併） |
| 基輔 C | 10/21～22 無人機與彈道飛彈攻擊，1 死 24 傷 | 不同事件 | 分開（正確） |
| 仁川 5G Wi-Fi 開通／科技部 10/21 體驗驗證 | 兩篇都是 10/21 實證事業完成、全車 5G 回程 Wi-Fi 開通，驗證活動即開通成果發表 | 同一事件 | 未合併（漏合併） |
| 韓國全國 5G Wi-Fi 政策（朝鮮 IT）／國會質詢（IT Daily） | 兩篇都是 10/23 國政監查中李勳基議員質詢、裴慶勳長官答覆的同一段 | 同一事件 | 未合併（漏合併） |
| 仁川開通 與 10/23 國會質詢 | 10/23 只是引用仁川成果 | 不同事件 | 分開（正確） |

**ROOT_CAUSE_UNCONFIRMED。** 雲端 artifact 只有報告與 run_summary，沒有 RunTrace、journal、分組提案或確認回應；報告每則只列一個來源網址。

（2026-10-28 更正）使用者提供的雲端 job log 顯示 EventIdentity `input_count=68`、`output_count=41`，即有 27 筆紀錄完成合併，批次提案並非整批無效；先前「整批提案無效」的推測不成立，撤回。`technical_gaps_eventidentity=1` 只表示某一請求（批次、某群或某次確認）有技術缺口，無法對應到這三組。可能原因仍包括：helper 未把這些紀錄提為同群、確認步驟未確認，或該技術缺口剛好落在相關群組；沒有具體提案與確認回應前無法區分。

**未修改 Event Identity。** 現有 Python 規則（complete-link、RC-22 地區、RC-23/25 確認）在這些案例沒有找到錯誤；沒有證據時不改規則。

**附帶觀察（未修改）：**
- **零寬字元。** Reuters 電文在不同轉載中嵌入位置不同的零寬字元（U+200B／U+200C／U+2060），Evidence 文字原樣保留；仁川開通一文也有。尚未證實與漏合併有關。
- **主文雜訊。** Infoseek 頁面的主文含頁尾排行榜文字（主文邊界問題）。
- **可能不成報。** 10/23 國會質詢一組本質上是政治人物質詢與官員答覆，依 RC-25/27 可能屬不成報類別，需以 Reportability 診斷確認。
- **RC-28 已排除部分事件。** 「韓國全國 5G Wi-Fi」一則在 RC-28 下已因所在地無法確立而排除；基輔各則因非指定地區而排除。這些只是附帶結果，不是合併問題的修正。

**測試：** 新增 `tests/test_numeric_grounding.py`（7 項）；全套 1108 全過；Golden 29＋R01–R07 全過，未修改。


## 36. RC-29 數字依據正確性修正（離線，2026-10-28）

**問題（使用者獨立檢查發現，已重現）：** `is_grounded()` 只比較數值，沒有約束單位與幣別。下列皆被錯誤判為有依據：
- Evidence「42 miles」對 Writer「42公里」
- 「30公里」對「30%」
- 「500億円」對「500億美元」

另外 5% 相對容差會放行不同的值，例如「1,040億円」對「1,000億日圓」、「20%」對「21%」。

**最早根因：** `quantities.py` 只把度量單位當作「是否要檢查」的旗標，沒有把單位或幣別存成數量的一部分，比對時只看數值。容差採相對 5%，而不是 Writer 所寫的精度。

**修改範圍（只限 `quantities.py`，Validator 呼叫方式不變）：**
- 每個數量帶有度量（長度、面積、體積、重量、百分比、百分點；英里自成一類）或可能的幣別集合。
  - Writer 寫了單位或幣別時，Evidence 必須以相同度量或相交幣別陳述該值。
  - 共用符號視為多種幣別：`$` 為任一元，`¥` 為日圓或人民幣，「元」為各種「元」。
  - 公制同度量可精確換算；英里不換算。
- 精度改為「Evidence 值四捨五入到 Writer 最後一位後相等」，取消相對容差。
- Evidence 多語言單位與幣別詞（含 `$5m`、`€1.2b`、`1160t`），範圍共用上界的量級與單位（「5,000～10,000億円」「5-10%」）。
- 「必須檢查」的範圍擴及帶單位或幣別的小數字。

**測試：** `tests/test_numeric_grounding.py` 共 37 項：
- 反向 10 項：單位、幣別或值不同；
- 正向 19 項：多語言金額、量級換算、公制換算、百分點、四捨五入、無單位數字。

**離線回歸（記錄的 Validator 請求，未呼叫 MaiAgent）：**

| 資料 | 區塊 | 檢查數字 | 標記 |
|---|---|---|---|
| 最新 journal 週 | 39 | 52 | 0 |
| 較早紀錄 | 54 | 60 | 0 |

較早紀錄修正前曾誤判「1,160噸」（來源寫「1160t」），已補上「t」並加為正向測試。

- **達卡實際來源：** 錯誤的「5,000億至1兆印度盧比」與「500億至1,000億美元」都不通過；「500億至1,000億印度盧比」通過。
- **雲端 32 則：** 報告檔已不在原下載位置，未能重跑。

**Event Identity 紀錄更正：** 見 §35，雲端 input_count=68、output_count=41，撤回「整批無效」推測，維持 ROOT_CAUSE_UNCONFIRMED，未修改 Event Identity。


## 37. RC-29 數字讀法歧義最終修正（離線，2026-10-28）

**反例（使用者獨立檢查發現，已重現）：**
- Evidence「₹5,000 crore」被同時讀成 5000 crore 與 5.000 crore，錯誤的 Writer「5,000萬印度盧比」因此通過；正確為 500億印度盧比。達卡實際來源同樣通過。
- 未標幣別的「5億元」支持了 Writer 自行指定的「新臺幣5億元」。
- 同類問題：「$1.93 billion」支持「19.3億美元」，「¥500 billion」支持「5,000億日圓」。

**最早根因：**
- **讀法：** Evidence 讀取為了不誤判小數，把每個「一個分隔符後恰三位數」的數字同時讀成千分位與小數兩種值，任一種相符即算有依據。模糊的讀法因此可以支持差 1,000 倍的錯誤金額。
- **幣別：** 比對只要求 Writer 與 Evidence 幣別集合相交；共用符號（$、¥、元）因此能支持來源未載明的具體幣別。

**修改（只限 `quantities.py`；Writer 指示與 Validator 改寫回饋各補一句）：**
- **每個 Evidence 數字只有一種讀法。** 自身可判定者直接讀：兩種分隔符、重複分隔符（含印度 lakh 分組 1,25,000）、分隔符後非三位數。「5,000」「1.234」類依序判定：
  1. 相鄰 CJK 文字或 CJK 量級；
  2. 來源自身確立的單一小數點；
  3. 僅英文使用的量級詞（billion、crore、lakh、bn…）；
  4. 末三位以 0 結尾者為千分位。

  仍無法判定者不作依據。空白只作千分位分組，不再把「20 2026」接成一個數字；㎡ 等 CJK 相容符號視為 CJK 文字。
- **幣別須至少同樣具體。** Evidence 的幣別集合必須包含於 Writer 的集合內。「元」涵蓋所有元類幣別（含美元、澳元、新臺幣元）。共用符號只支持同樣不具體的 Writer 寫法（$19.3億、19.3億元），不支持美元、日圓、新臺幣。
- **Writer（formal-report-writer-v8）：** 共用幣別符號照原文，不得改寫為來源未載明的幣別。Validator 改寫回饋同步說明。

**測試：** `tests/test_numeric_grounding.py` 共 66 項。

| 類別 | 項數 | 內容 |
|---|---|---|
| 讀法 | 15 | 英／德／法文件、未判定、末位 0、lakh、混合分隔符、小數逗號、CJK、英文量級詞 |
| 反向 | 17 | 新增模糊讀法 3、幣別未載明 4 |
| 正向 | 26 | 含「$19.3億」「19.3億元」「US$→美元」「新台幣→新臺幣」「Rs→盧比」 |

全套 1167 全過；Golden 29＋R01–R07 全過，未修改。

**離線回歸（記錄的 Validator 請求，未呼叫 MaiAgent）：**

| 資料 | 區塊 | 檢查數字 | 標記 |
|---|---|---|---|
| 最新 journal 週 | 39 | 52 | 0 |
| 較早紀錄 | 54 | 60 | 0 |

- 45 個 Evidence 來源共 1,610 個數字，無法判定 26 個：25 個是日期（2026.10.20 等，本來就不是數量），1 個是「61,517」。修正前因空白拼接與 ㎡ 未辨識，有 58 個。
- 雲端與品質抽查頁 3,081 個數字中，無法判定的只有 2 個日期（21.10.2026、26.10.2026）。
- 達卡實際來源：「500億印度盧比」通過，「5,000萬印度盧比」不通過。

**Event Identity：** 維持 ROOT_CAUSE_UNCONFIRMED，未修改。


## 38. Event Identity 完全未合併的根因調查（離線，2026-10-29）

**現象：**

| Run | 版本 | Event Identity | 技術缺口 | 耗時 |
|---|---|---|---|---|
| 40623936647 | 0b43a45 | 68 → 41 | 1 | 未記錄 |
| 40653585176 | 8f0df07 | 63 → 63（完全未合併） | 1 | 5,797 ms |

40653585176 的正式報告因此出現重複報導：京都醍醐站 4 篇、林茲 3 篇、Bergamo 3 篇、仁川 5G Wi-Fi 10 篇、大邱演練 6 篇。

**逐階段檢查：**
- **程式：** 兩次執行之間 `event_identity.py` 與其 provider 完全相同。期間的修改只有 RC-28（ReportService 國家資格、地理參照表 v4、metadata 提示詞 v4）與 RC-29（Validator／Writer 數字）。這些都不會產生 Event Identity 技術缺口，也不會使合併歸零。
- **輸入：** Search 122、Evidence 392 → 156 READY、Temporal 102 → 63 筆進入 Event Identity，規模與前次（68 筆）相當。Scope 有 18 個技術缺口，只會排除候選，不影響其餘紀錄合併。
- **時間：** 正常的 Event Identity 是一次批次請求（本機 journal：72 筆時請求 49,653 字元、提案回應 23 KB），之後每個提案群組再一次確認請求（本機 13 次）；長篇生成加上多次確認，不可能在 6 秒內完成。helper 逾時為 30 秒且重試一次，逾時約需 60 秒，可排除。
- **研判：** 零合併、恰好一個 Event Identity 缺口、5.8 秒，符合批次層級失敗。可能是快速的傳輸失敗（連線、HTTP 429／5xx 兩次，或其他狀態碼一次）、無法解析的回應（兩次），或簡短但 `SCHEMA_INVALID`／`UNKNOWN_RECORD` 的回應（§A.15 規定兩者使整份回應無效）。
- **缺少的權威觀測：** 失敗的是哪個請求、失敗類別為何。artifact 只有 `technical_gaps_eventidentity=1`，trace 只有輸入與輸出數，雲端 journal 未上傳。

**結論：**
- EARLIEST_ABNORMAL_STAGE = Event Identity（批次分組提案請求）。
- ROOT_CAUSE_VERDICT = ROOT_CAUSE_UNCONFIRMED。
- 未修改 Event Identity 規則、提示詞或契約。

**觀測補強（RC-30，§A.24，僅 Debug）：** 每個技術缺口輸出 `stage:level:kind:failure_class` 簽章。Event Identity 的 level 為 `BATCH`／`GROUP`／`CONFIRMATION`／`CONFIRMATION_GROUP`。

| 輸出位置 | 內容 |
|---|---|
| EventIdentity trace 快照 | 缺口簽章、診斷原因分布、合併／未合併群組數 |
| run summary | `technical_gap_signatures`（所有階段）、`event_identity_diagnostics` |

兩者都由同一個 EventIdentityRun 投影而來，不含紀錄 ID、候選 ID 或來源文字，不參與決策。

**測試：**
- 新增 `tests/test_event_identity_observability.py`（9 項）。
  - 正向：同一事件兩個來源合併；同站另一日的不同事件不合併。
  - 整批 `UNKNOWN_RECORD`、`SCHEMA_INVALID`、傳輸失敗：全部不合併，並記為 `BATCH` 缺口。
  - 某群引文無效：記為 `GROUP` 缺口，其他群照常合併。
  - 確認不完整與確認中某群無效：分別記為 `CONFIRMATION`、`CONFIRMATION_GROUP` 缺口。
  - 簽章不含 ID 或原文。
- `tests/test_execution_trace.py` 新增 1 項：同一簽章同時出現在 trace 與 run summary。
- 全套 1177 全過。

**下一次雲端執行須確認：** run summary 的 `technical_gap_signatures` 中 EventIdentity 項目的 level 與 failure_class。據此決定下一步：
- 傳輸或解析類：先查 helper 對大型請求的處理。
- `UNKNOWN_RECORD`／`SCHEMA_INVALID`：檢討 §A.15 整份回應無效規則的範圍。
- `CONFIRMATION*`：檢討確認步驟。


## 39. 確認不完整的根因、逐候選選題稽核與正式交付呈現（RC-31，離線，2026-10-29）

**雲端 Run 40797604176（2026-10-21～27，main a608b19）：**
- 正式報告 24 則；Event Identity 64 筆 → 44 則事件。
- 技術缺口 19：Scope 18、Event Identity 1。
- RC-30 簽章：`EventIdentity:CONFIRMATION:PROPOSAL_CONTRACT_VIOLATION:CONFIRMATION_INCOMPLETE=1`。
- 診斷：`PROPOSAL_REGION_CONFLICT=251`（配對）、`PROPOSAL_NOT_CONFIRMED=112`（配對）。

**P0 根因調查：**
- **確認請求自相矛盾（已確認）：**
  - RC-25 要求 helper 把分開的紀錄「單獨成群」。
  - 但確認請求附帶的權威回應 schema 是一般分群用的 `members.minItems = 2`，指令也無條件寫「不得回傳單筆群組」。
  - 只要有紀錄被分開，就不存在既符合 schema 又完整的回答。
- **離線重播證據：**
  - 方法：在 cbdb010（提示詞 v4）以 journal 副本完全離線重播 2026-10-14～20，沒有網路，也沒有 MaiAgent 呼叫。
  - 共 13 次確認，其中 3 次分開了紀錄：1 次用單筆群組表達，2 次直接省略被分開的紀錄，也就是記錄到的 2 個 `CONFIRMATION_INCOMPLETE`。
  - 被省略的紀錄都是 helper 判為不同事件者，例如梁山「最後準備階段」、大田背景專題；回傳的群組除那一次單筆外都至少 2 筆。
  - RC-23 的蔚山省略與 RC-25 的慰禮線空清單，型態相同。
- **其他檢查項目：**
  - schema 不只「允許」省略，實際上是禁止完整回答，迫使 helper 省略。
  - 回應是合法 JSON。
  - record ID 重新編號、依發布時間排序、資料量都不是必要條件：2 筆的確認同樣會發生。
- **省略的影響範圍：** 只影響被省略紀錄的配對；一起回傳的配對仍會確認。因此單一確認不完整本身不會使真正的重複無法合併。
- **本期四組重複：**
  - 雲端回應未保留，無法得知各組是未被提議、被確認分開，還是被省略，逐案根因維持 `ROOT_CAUSE_UNCONFIRMED`。
  - 251 個跨地區配對顯示雲端批次提案大量把不同國家的紀錄分在同一群；本機那一週為 0。
- **Evidence 判讀（四組皆應合併）：**
  - 東京 AI：同一則 10/27 發表。
  - Bergamo：同一則 10/26 測試時程公告；eventi.news 與 primabergamo 是同一篇。
  - 京都：Infoseek 是產經的轉載。
  - 仁川：同為 10/21 實證事業完成；biggo 的報導包含部長乘車體驗。

**P0 修正（Event Identity owner）：**
- 確認請求改用 `EVENT_IDENTITY_CONFIRMATION_RESPONSE_SCHEMA`（`minItems = 1`，`event-identity-semantic-confirmation-v1`）；一般分群請求的 schema 與版本不變。
- 「不得回傳單筆群組」只適用一般分群請求（`event-identity-grouping-v5`）。
- Python 驗證、省略 fail-closed、RC-22 地區檢查與分組規則都不變，不以原提案代替確認。
- 觀測（僅 Debug）：
  - 地區衝突與未確認配對的診斷註明提案群組與大小；
  - 未確認配對再分為 `SEPARATED`／`OMITTED`／`GROUP_INVALID`／`CONFIRMATION_FAILED`；
  - run summary 新增 `event_identity_unconfirmed`。
- 測試：
  - `tests/test_event_identity_rc31.py`（11 項）：請求契約；同事件換句話說合併；轉載合併；同系統不同日期分開；完整分割；省略 fail-closed；確認失敗；跨地區主題群不過度合併。
  - Event Dedup Golden 新增 ED16～ED18（完整分割、省略 fail-closed、轉載），既有 ED01～ED15 未修改。

**P1 `selection_audit.json`（僅觀測）：**
- 逐一列出每則正規化候選：
  - Evidence（狀態、拒絕原因與關卡、canonical URL）、地區；
  - Scope（狀態、診斷、事件焦點句 ID 與至多兩句摘錄）、Temporal；
  - Event Identity（事件、合併對象、未合併的提案配對與原因）；
  - Category、Taxonomy、Reportability、排序位置、正式 metadata（含運輸系統名稱）、Validation、是否入報；
  - 最早終止階段與記錄的原因。
- 由既有結果機械投影：不呼叫 MaiAgent、不重算決策；投影失敗只標 `unavailable`，不影響執行。
- 離線驗證：以 cbdb010 重播的 406 則候選全數涵蓋，大小約 0.6 MB；終止原因分布與各 owner 結果一致。

**P2 呈現（僅呈現，不改上游決策）：**
- **PDF：** 改由結構化 artifact 繪製；不顯示運輸系統與執行說明；來源為一行連結。
- **Markdown：** 保留運輸系統與執行說明；來源改為一行 `來源：[名稱](URL)`。
- **Email：** 內文改為分類標題索引，每個標題連到 canonical URL，並附 PDF；主旨不變。
- **不變：** `SUCCESS_WITH_TECHNICAL_GAPS` 判定、寄送識別與冪等。
- **來源名稱（使用者確認後修訂 §R）：**
  - 原契約 §R 規定來源顯示為 canonical hostname 並禁止候選出版者名稱，因此先停下；使用者確認新需求後修訂。
  - 規則：EvidenceService 已記錄出版者來源核對相符（`publisher_origin_check = MATCH`），且宣告的出版者網域對應 canonical 網址主機時，顯示 RSS 宣告的出版者名稱（如「來源：Impress Watch」）；否則顯示 hostname。連結目標仍是 canonical 網址。
  - 唯一 owner 為 ReportService 的 `source_display_for`；Validator 呼叫同一函式檢查，不再自行推導 hostname；PDF、Markdown、Email 只使用投影值。
  - 測試：正向（Impress Watch、上層網域、空白正規化）；反向與 fallback（核對不符、未宣告、無出版者紀錄、宣告網域不是 canonical 主機、canonical 移到他站、空白或過長名稱）；無效網址；三種呈現使用同一投影值；被竄改的名稱由 Validator 判為 metadata integrity 失敗。

**唯讀發現（未修改）：**
- **巴塞隆納對角大道歸【採購事件】：**
  - 來源只說招標將在兩至三週內啟動，尚未發生正式採購 action。依 §L，這不屬 `PROCUREMENT`。
  - Owner 為 Classifier；Category 指引未明說「宣布將招標」不是正式採購 action。
  - helper 回應未保留，根因未確認。
- **東京ポイントAI 標示「電聯車、號誌」：**
  - 設備裝在保守用車上，以影像辨識轉轍器開通狀態與障礙物並警示駕駛。
  - §M 未定義非客運的保守／工程車是否屬 `ROLLING_STOCK`（顯示為電聯車）。
  - 以攝影機辨識轉轍器狀態，而不參與聯鎖等號誌功能，是否構成 `SIGNALLING` 也屬邊界。
  - 這是 Taxonomy 規則缺口，需 Domain 決定，不在本次自行修改。
- **三鶯線／安坑輕軌標示「淡海輕軌」：** 運輸系統名稱來自 EvidenceService metadata 擷取，PDF 雖已不顯示，selection audit 仍可看到，需另案處理。

**測試：** 全套 1208 全過；Golden 測試 27 項全過（Event Dedup 18 案），既有案例未修改。

**下一次雲端執行須確認：**
- `technical_gap_signatures` 是否不再出現 `CONFIRMATION_INCOMPLETE`。
- `event_identity_unconfirmed` 的分布。
- `selection_audit.json` 中重複組的 `proposals_not_merged`：未出現代表批次未提議；`SEPARATED` 代表確認判為不同事件。
