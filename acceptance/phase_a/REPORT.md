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
