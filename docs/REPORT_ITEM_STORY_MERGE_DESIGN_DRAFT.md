# 同一路線同一期合併成一則：設計提案（草案，未實作）

狀態：**DRAFT — 待使用者核准**（2026-11-25）。本文件不改變任何 production 行為；核准前不得實作。

使用者規則（2026-11-16 決定，RC-67 記為 BLOCKED_ARCHITECTURE_EXPANSION）：

> 同一路線或計畫在同一期的預告、發生、恢復、後續報導合併成一則。

## 1. 本週三對重複的根因（Run 45558738725，離線重放）

以 selection audit 重放 Event Identity（`scripts/event_identity_replay.py` 加上「確認請求的摘錄比批次長」的修補，
重放結果與 live 完全一致）：

| 案例 | Event | 實際原因 |
|---|---|---|
| 聖水支線停駛 | A＝{06b9 톱스타뉴스, 6509 英文恢復通車}；B＝{7119, ba9a, c373, e99d} | 06b9–B 四筆 3/3 確認、06b9–6509 2/3（p1，以及 p2 同一次提名中第二個重疊群組），6509–B 只有 1/3。06b9 同時與 [6509] 和 [B] 相容，兩群合併不成立（6509–B 不是 SAME），complete-link 依 §A.15「穩定相容群組」放入 `_group_sort_key` 較小者，也就是候選 ID 字典序較小的 [6509]。結果由候選 ID 雜湊決定，不是由確認次數決定。符合契約，不是程式錯誤，但是任意的。 |
| 首爾依法運行 | 09dc（11/19「20일부터 준법운행 돌입」）、0ee9（11/20「오늘부터 준법투쟁」） | 批次提名六次都沒放在一起；只由 RC-79 Python 候選送確認，而該確認群組有 **48 筆**韓文紀錄（3 字視窗經傳遞閉包連成一大群：蔚山預算、大田電車、修能加班、光州 2 號線…），確認 1/3。 |
| 大邱全面檢查 | c2ac（全線，경향）、cbde（3 號線，뉴시스） | 批次確認三次都分開；Python 確認三次都同群，但「較早確認的判定為最終」以批次的分開為準。兩則的 formal metadata 系統名稱都是 3 號線。 |

此外：RC-79 本期 278 對候選，最大兩個確認群組 41 筆與 48 筆。大群組確認是 helper 變動的主要來源之一（另案可改為不做傳遞閉包）。

## 2. 建議：在 Reportability 之後新增「報導項目」一層，不改 Event Identity

```text
… → Event Dedup → Category → Taxonomy → Reportability → 【Report Item（新）】 → Ordering → Writer → Validation → Assembly
```

不改 Event Identity 的理由：

* Event Identity 定義的是**同一發生事項**（§K、RC-48 R1～R6、Golden ED01～ED29）。預告與開始、故障與恢復本來就是不同發生事項；
  若放寬 SAME_EVENT，Category 會在同一 Event Group 看到兩個主要動作（事故＋恢復營運），回 `NO_UNIQUE_PRINCIPAL_ACTION`，反而掉件；
  多個 Golden 預期也會被迫改變，違反「Golden 是領域事實」（RC-47）。
* 使用者規則是**報告呈現**的規則（一則涵蓋事件經過），RC-67 已判定它需要新的報告項目 owner。

新 owner：`ReportItemComposer`（名稱可調），唯一負責「哪些 Event 組成同一則報導項目」。它不改任何 Event 的
Category、Taxonomy、Reportability，不合併或拆分 Event Group，不救回任何被排除的 Event。

## 3. 分工

**Python（owner）**

1. 母體：只有 `REPORTABLE` 且會進正式報告的 Event（已通過 RC-28 地區規則）。被排除的 Event 一律不參與（不救回）。
   本週約 18 則，所以請求很小，不會出現 48 筆的大群組。
2. 候選配對（機械條件，全部成立才送 helper）：
   * 兩個 Event 的 EvidenceService 地區都已確立且相同；
   * 都在本期（建構上已成立）；
   * 兩個 Event 的成員之間至少有一對共有 RC-79 特徵詞（標題或 Scope 焦點句中、本次執行只出現於 2～3 筆紀錄的詞；
     同一個機制、同一個停用詞與運具詞排除表），不使用 72 小時限制（預告與發生可相隔數日）。
3. 依地區把候選配對連成小群組，每群一個請求；helper 回答後 Python 驗證：每個 Event 至多一群、引用句可解析、
   每個成員標示階段（`PREVIEW`／`OCCURRENCE`／`RESUMPTION`／`FOLLOW_UP`）。
4. 一致規則：同一請求獨立問三次，**至少兩次**放在同一則才合併（與 RC-52 同形，但是獨立計數）；
   complete-link：一則裡任兩個 Event 都必須達到 2/3，否則不合併、只記診斷（不依候選 ID 字典序選邊）。
5. 主事件（lead）：helper 標為 `OCCURRENCE` 的 Event；若有多個（Event Identity 漏合的同一發生事項），取成員來源數最多者，
   再相同取最早發布者。報導項目的**章節＝主事件的 Category**；成員 Category 不同時只記診斷（例：故障＋恢復通車列在事故）。
   排序以主事件的 Ordering key。
6. 觀測：selection audit 記錄每則的成員 Event、階段、三次回答（只含 ID）、未合併原因；run summary 分開列出
   Candidate、Event、報導項目三種數量；重放工具同樣可重現。

**模型（helper，提案）**

* 判斷同一群內哪些 Event 是**同一路線或同一計畫上、同一件事的經過**（預告→發生→恢復→後續），並以句子 ID 引用
  支持「同一件事」的句子（例：「20일부터」與「오늘부터」指同一場依法運行；「恢復通車」句指向的停駛）。
* 不決定章節、不決定是否成報、不改寫內容。

任務：新增第九個 Structured Helper task `report_item_story_proposal`（自己的 request type、prompt、schema、
本機驗證與失敗語意）。這需要修訂 AGENTS.md §11 的八個 task 清單，屬使用者核准事項。替代方案是沿用
`event_identity_semantic_proposal` 的第二種請求（比照 RC-59 的 Scope 第二種請求），但 owner 不同、語意也不同，不建議。

## 4. 如何避免誤併同一路線上的不同事件

* 提示詞明定：同一路線上不同日期或不同原因的兩次故障、兩次停駛、兩次事故是**兩則**；同一營運者的兩項不同技術或計畫是兩則；
  只有同一件事的預告、發生、恢復、後續才是一則。
* Python 條件：同地區、共有罕見特徵詞（不是只有營運者名稱或「지하철」這類常見詞），且三次中兩次同意；任一對未達成則整則不成立。
* 技術失敗或違約：該群不合併並揭露為技術缺口（fail-closed），各 Event 照常各自成則。
* Golden（核准後新增）：同線同週兩次不同故障 → 兩則；東京メトロ ぱとれーる 與 ポイントAI（同營運者、同期、不同技術）→ 兩則；
  依法運行預告＋開始 → 一則；故障＋恢復通車 → 一則（事故章節）。

## 5. Writer 與 Validator

* Writer 收到一則報導項目的所有成員 Event（各 Event 的焦點句與來源，依階段與日期排序），寫**一個標題、一段摘要**涵蓋經過
  （例：「11/19 停駛、11/20 恢復」），只寫 Evidence 支持的事實；不同成員的數字或日期互相矛盾時不寫該事實（§K）。
  RC-67 的「只寫 event_focus 那一件」改為「只寫本報導項目成員的那些事」，非成員的事件仍不得列舉。Writer 提示詞改版。
* Validator 以所有成員的 Evidence 為依據（來源代號 M1…Mn 涵蓋全部成員），規則不變；一則仍只有一次改寫。
* 報告：來源列出全部成員來源；`Final report count = Validation PASS 的報導項目數`；Email 主旨的則數同。

## 6. 對 RC-52「3 次中 2 次同意」的影響

* **Event Identity 不變**：SAME_EVENT 仍需 3 次中 2 次確認；Event Identity 的診斷照舊揭露漏合（例：聖水 A／B）。
* 報導項目層有自己的 2/3 規則，母體小（本週約 18 則），每週約 3 × 群組數（估 3～6 群）＝ 9～18 次 helper 呼叫。
* 報導項目層會在報告中吸收 Event Identity 漏合的同一發生事項（聖水 A／B），但它依的是使用者的報導規則，
  不是重新判定 SAME_EVENT；Event Identity 的漏合仍記在診斷，可另案處理（例如以確認次數而非候選 ID 決定 complete-link 的選邊，
  或 RC-79 不做傳遞閉包以避免 48 筆的確認群組）。

## 7. 以案例檢驗（預期）

| 案例 | 母體（REPORTABLE） | Python 候選 | 預期結果 |
|---|---|---|---|
| 聖水支線（本週） | A、B 皆 REPORTABLE、KR、事故 | 06b9–ba9a、06b9–e99d 共有特徵詞 | 一則，事故章節；A 含恢復通車句 |
| 依法運行（本週） | 09dc、0ee9 皆 REPORTABLE、KR、營運 | 09dc–0ee9 為 RC-79 候選 | 一則（#35＋#48）。4e6f「첫날 출근길 정상운행」為 NOT_REPORTABLE，不參與（見待決 D-B2） |
| 大邱檢查（本週） | c2ac、cbde 皆 REPORTABLE、KR、營運 | c2ac–cbde 為 RC-79 候選 | 一則（#52）；6ac4 市議會要求為 NOT_REPORTABLE，不參與 |
| ぱとれーる（10/27～29） | #11、#15 兩則皆成報、JP | ED29 的配對 | 一則 |
| ポイントAI（10/27～29） | #14、#16 兩則皆成報、JP | 共有「ポイントAI」 | 一則；與 ぱとれーる 不同計畫，維持兩則（只有「東京メトロ」相同，不是罕見特徵詞） |

以上為依規則推導的預期，尚未用 helper 量測；核准後先以本週與 10/27～29 的 audit 離線重建請求、以標註回答重放驗證，
付費量測需另經核准。

## 8. 待使用者決定

* D-B1：是否採「Reportability 之後新增報導項目 owner」（建議），而不改 Event Identity 的同一事件定義。
* D-B2：NOT_REPORTABLE 的後續報導（如依法運行第一天正常運行）是否可作為某則的補充成員；建議**否**（避免下游救回）。
* D-B3：新增第九個 helper task `report_item_story_proposal`（修訂 AGENTS.md §11）。
* D-B4：一則的章節取主事件（helper 標 `OCCURRENCE` 者）的 Category。
* D-B5：一致規則取三次中兩次（約 9～18 次呼叫／週）。
