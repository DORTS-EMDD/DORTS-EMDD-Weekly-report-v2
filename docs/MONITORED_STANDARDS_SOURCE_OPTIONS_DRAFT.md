# 監控標準的目錄來源：選項草案 v1

狀態：**草案，未生效，未實作。**
- 使用者已選 Q1＝選項 A、同意 Q2 可行性檢查（2026-11-05）。
- Q3 已定：國家採用不算同一標準的第二次更新；只有被監控的編號本身是 EN 或國家標準時，才依該編號自身的 lifecycle 判斷。
- 可行性檢查結果見第 7 節；仍需使用者決定第 8 節各項，才能修訂契約與實作。
本草案不修改程式、提示詞、Golden、Search 設定或契約。背景見 `docs/ARCHITECTURE_CONTRACT.md` §A.43「Known discovery limit」與 acceptance REPORT §63。

## 1. 問題

- 2026 年 7 月回放（Run 41942587859）的月檢已正確執行：63 次編號查詢、整個 7 月、0 失敗。
- 但 IEC 61373:2026（第 3 版，2026-07-17 發行，取代 2010 年版）沒有成為候選。
- 最早失敗點是 Search 取回：Google News 在 7 月沒有任何提及 IEC 61373 的項目。不限日期時，也只有引用該標準的產品新聞。
- 標準的正式變動發布在標準組織或經銷商的目錄，不在新聞。只靠新聞，27 項都只能偶然被發現。

27 項依發行單位分布：

| 發行單位 | 數量 | 編號 |
| --- | ---: | --- |
| IEC | 11 | 61373、62271-100、62271-102、60947-1、60850、60754-1、60754-2、60332-1、60076、60076-11、62695 |
| CENELEC | 8 | EN 50126、50128、50129、50122、50122-2、50327、50328、50329 |
| CEN | 1 | EN 13674-1 |
| NFPA | 3 | 130、258、70 |
| ASTM | 2 | E119、E662 |
| IEEE | 1 | 1474.1 |
| UIC | 1 | 860-0 |

## 2. 不論選哪個來源都不變的部分

- 監控清單仍只有 `monitored_standards.json` 的 27 項；每月檢查一次（RC-59 的月份規則）。
- 新來源只負責「發現」。判定照舊：
  - Evidence 確認來源頁面；
  - Scope 以 `MONITORED_STANDARD` 依據確認「該標準本身正式變動」，Python 驗證編號與引用句；
  - TemporalRule 以檢查月份判斷日期；
  - Reportability 與報告章節照舊，仍只有一份週報、一封信、同一個 Google Group。
- 需要修訂的契約：
  - §C Phase 2B-A：provider 不再只有 `google_news_rss`。
  - Evidence（§H）：標準目錄紀錄可作為 Authoritative Evidence，條件須明定。
  - 報告來源連結可指向目錄頁。
- 不寫死任何標準、網址或文章；來源設定是依發行單位的資料，不是依單一標準。

## 3. 選項

### A. 各發行單位的公開目錄紀錄（每月直接查）

每月對 27 項各讀一次發行單位（或其國家會員鏡像）的公開目錄紀錄，看發行、修正、撤回、被取代或草案階段的日期是否落在檢查月份。不需要搜尋引擎。

- 優點：
  - 最權威，直接就是正式紀錄；
  - 免費、連結公開；
  - 也能看到草案與徵詢階段；
  - 每月約 27 次請求，與新聞無關，不會有新聞雜訊。
- 缺點與風險：
  - 依發行單位約需 5～6 種頁面格式（IEC、CEN／CENELEC、NFPA、ASTM、IEEE、UIC）；網站改版就要維護。
  - 部分網站有前端渲染或防爬限制：IEC webstore 的「Just Published」是前端渲染；ANSI webstore 對自動請求回 403。
  - 各網站使用條款需逐一確認。
  - 國家會員網站（如 genorma.com、iss.rs、dps.gov.al 使用同一格式 `project/show/<機構>:proj:<編號>`）公開鏡像 IEC、CEN、CENELEC 的專案資料。若可用，一種格式就能涵蓋 20 項，但要先確認其權威性與使用條款。
- 前置工作：每個發行單位先做一次可行性檢查（約 27 次請求，各一個標準頁），需要你同意後才抓取。

### B. 免費的標準異動通知信（專用信箱）

用一個專用信箱訂閱免費的標準追蹤通知，月檢時讀取該信箱，把通知中的標準與連結當作「發現」，再照常抓取公開頁面作為 Evidence。可用的服務例如：

- [ASTM Standards Tracker](https://store.astm.org/products-services/tracker-services.html)：新版、更新、修正、撤回、被取代時寄信；
- [Techstreet Tracker](https://www.ecmweb.com/construction/article/20888004/techstreet-offers-free-standards-tracking-on-its-web-site)：涵蓋 IEC、NFPA、IEEE、BSI、ISO 等；
- [SAI Global StandardsWatch](https://bca.saiglobal.com/en-au/standardswatch/)；
- [EVS 監測](https://www.evs.ee/en/monitoring)（愛沙尼亞國家標準組織，涵蓋 EN 與 IEC 採用）。

評估：

- 優點：由服務商維護、涵蓋面廣、不需爬網站。
- 缺點與風險：
  - 需要新的信箱讀取憑證（新 Secret），由你建立；
  - 各家信件格式不同，要分別解析；
  - 通知可能延遲到下個月；
  - 服務條款可能限個人使用，需確認；
  - 通知信本身不能當 Evidence，仍需抓公開頁面。

### C. 付費標準管理服務的 API

例如 Accuris／Techstreet Enterprise、[BSI 標準訂閱（BSOL）](https://bsigroup.com/en-HK/Our-services/Standards-subscription-services)、Perinorm 等，以一個 API 取得 27 項的版本與異動紀錄。

- 優點：
  - 單一來源涵蓋全部發行單位；
  - 有正式狀態（現行、撤回、被取代）與歷史；
  - 最少自行維護。
- 缺點與風險：
  - 授權費與合約；
  - API 憑證；
  - 內容多在登入後，報告的來源連結需改指發行單位的公開頁；
  - 草案階段不一定涵蓋。
- 適合條件：貴單位已有或願意採購標準訂閱。

### D. 付費網路搜尋 API

以一般網路搜尋找目錄或經銷商頁面。

- 不建議：
  - [Bing Search API 已於 2025-08-11 停止](https://mc.merill.net/message/AZ492574)；
  - [Google Custom Search JSON API 已不接受新客戶，2027-01-01 停止](https://brave.com/learn/google-api-shutdown/)；
  - 其他搜尋 API 的結果多為經銷商頁面（次級來源），日期篩選不可靠。
- 無金鑰的 Bing RSS 雖然找得到，但條款只允許個人非商業的 RSS 閱讀，不能用。

### E. 維持現狀

只靠新聞與專業媒體。不需任何設定，但 27 項大多數的正式變動仍會漏掉，例如 IEC 61373:2026。

## 4. 建議

採用選項 A，並分兩步：

1. 先取得你的同意，對每個發行單位做一次可行性檢查（約 27 次公開頁請求）。確認哪些目錄頁可直接讀到發行、撤回、取代或草案日期，以及使用條款。
2. 依結果實作一個以發行單位為鍵的目錄來源。
   - 若國家會員鏡像可用且具權威，IEC、CEN、CENELEC 的 20 項只需一種格式；NFPA、ASTM、IEEE、UIC 的 7 項各自一種。
   - 某發行單位的頁面讀不到時，該單位改用選項 B 的通知信，或在你同意下改用選項 C。

不建議 D；E 只適合暫時接受。

## 5. 需要你決定的事

- Q1：採用哪個選項（A、B、C、組合或 E）。
- Q2：若選 A，是否同意先做約 27 次公開目錄頁的可行性檢查。
- Q3：國家採用（例如 BS EN IEC 61373:2026，2026-09-30）是否另算一次標準更新，或只算發行單位的原版發行。
- Q4：若選 B 或 C，由你建立信箱或訂閱，並提供讀取憑證（以 Secret 設定；不經由對話傳送）。

## 6. 參考

- 事件本身：[en-standard.eu：IEC 61373:2026](https://www.en-standard.eu/iec-61373-2026-railway-applications-rolling-stock-equipment-shock-and-vibration-tests/)、[ANSI webstore](https://webstore.ansi.org/standards/iec/iec61373eden2026)、[IEC 預覽 PDF](https://www.technickenormy.cz/publicdoc/iec_previews/4280856.pdf)、[BSI](https://knowledge.bsigroup.com/products/railway-applications-rolling-stock-equipment-shock-and-vibration-tests-3)。
- 國家會員鏡像的格式例：[genorma.com EN 50126-1:2017/A1:2024](https://genorma.com/en/project/show/cenelec:proj:72022)、[iss.rs IEC 專案 15639](https://iss.rs/en/project/show/iec:proj:15639)。
- IEC Just Published：[webstore.iec.ch/justpublished](https://webstore.iec.ch/justpublished)。

## 7. 選項 A 可行性檢查結果（2026-11-05）

做法：
- 共 32 次公開頁請求：robots.txt 12、目錄紀錄 16、使用條款 4。另以網路搜尋找出各機構的網址格式；網路搜尋不對出版者發請求。
- 未登入、未執行 JavaScript、未使用 API 金鑰。
- 「直接可用」的條件：發行單位官方頁、公開、伺服器端已含 lifecycle 資料、robots 不禁止、可穩定定位。
- 使用條款：四個機構的條款頁都未能讀到（網址 404 或為前端渲染），因此未確認；上線前需人工確認。

### 7.1 各發行單位

| 發行單位（數量） | 官方來源 | robots | 不需 JS／登入 | lifecycle 證據 | 定位方式 | 判定 |
| --- | --- | --- | --- | --- | --- | --- |
| IEC（11） | webstore.iec.ch 出版品頁 | 檔案為空，無限制 | 是。頁面內嵌整個標準家族的 lifecycle 資料 | 每一版、修正、勘誤的編號、版次、發行日期與狀態（PUBLISHED／REVISED／WITHDRAWN） | 每個標準一個永久的出版品 id（資料，一次建立）；任一版的頁面都含整個家族 | **直接可用**（IEC 61373 已驗證） |
| ASTM（2） | store.astm.org | 允許 | 是 | 「Active」與「Last Updated」日期 | 由編號決定：`astm.org/Standards/<編號>.htm` 轉址到現行版 | **直接可用**（E119、E662 已驗證） |
| IEEE（1） | standards.ieee.org/ieee/<編號>/<id>/ | 允許 `/ieee/` | 是 | 狀態、「Superseded by」、Published 與 Board Approval 日期 | 每版一個 id；可沿「Superseded by」找到現行版；搜尋頁需 JS | **直接可用**（頁面格式已驗證） |
| NFPA（3） | nfpa.org/<編號>（轉址到 docinfo 頁） | 允許該路徑 | 部分。頁面內嵌狀態、現行版年、下一版年與歷年版本 | 只有版本年份；發行與草案日期的值不在 HTML 內 | 由編號決定 | **有條件**：缺少日期，無法判斷變動發生在哪個月；要再取日期資料，或比較上次的版本年（需要保存狀態） |
| CENELEC（8）＋CEN（1） | standards.cencenelec.eu | **`Disallow: /`，禁止自動存取** | — | — | — | **官方來源不可用** |
| 同上（9），替代來源 | genorma.com（「與 BDS 等國家標準組織合作」的銷售平台） | 允許全部 | 是 | ISO 階段代碼（含 40.xx 徵詢、60.60 發布、99.60 撤回）、日期、「REVISED BY」 | 每版一個網址；搜尋是 POST 加 CSRF；條款未禁止，但屬次級來源 | **有條件**：需要你接受次級來源，或改取得官方授權 |
| UIC（1） | shop.uic.org | robots 讀取失敗 | 搜尋頁未見結果 | 找不到 860-0 的紀錄；網路搜尋也找不到現行版或對應的 IRS | 無 | **不可行**：需要你確認 |

### 7.2 檢查中發現的 lifecycle 事實（都不在新聞裡）

- IEC 61373:2026 第 3 版：2026-07-17 發行，與官方頁一致。
- EN 50129:2026：2026-05-15 發布（stage 60.60）。
- EN 50128:2011 已被 EN 50716:2023 取代（REVISED BY），stage 99.60。
- ASTM E119-26：2026-01-29 更新；E662-21ae01 自 2021-09-16 未再更新。
- NFPA 130 與 NFPA 70：現行版 2026，下一版 2029。
- **NFPA 258 已於 2006 年撤回**，NFPA 的說明是相關內容已併入 ASTM E662。
- IEEE 1474.1：1999 版已被 2004 版取代；轉售商顯示現行版為 2025 版，官方頁的版本鏈尚未逐一確認。

### 7.3 覆蓋數

- 直接可用：**14 / 27**（IEC 11、ASTM 2、IEEE 1）。
- 有條件：**11**（EN 9 需接受次級來源或取得授權；NFPA 70、130 缺日期）。
- 不可行或需處理清單：**2**（UIC 860-0 找不到；NFPA 258 已撤回）。
- 少數共同來源：IEC 一個網站就涵蓋 11 項；加上 ASTM、IEEE，3 個官方網站可涵蓋 14 項。若接受 genorma，4 個網站可涵蓋 23 項。

### 7.4 建議的 production 架構

不是為每個標準寫程式，而是一個以資料驅動的「標準目錄」來源：

- **資料**：`monitored_standards.json` 為每個編號加上目錄來源與定位，例如 IEC 的永久出版品 id、ASTM 的編號網址、IEEE 的版本頁 id。仍是唯一的清單；不另建第二份。
- **Search（discovery owner）**：新增一個 provider，只在每月檢查那一期，對每個編號讀一次目錄頁。
  - 依來源類型解析頁面內的結構化 lifecycle 資料，目前需要三種：IEC 內嵌資料、ASTM 狀態與日期、IEEE 狀態與取代關係。
  - 日期落在檢查月份的條目，就產生 Candidate。
  - 不需搜尋引擎，也不需保存狀態，因為每個條目都有自己的日期。
- **Evidence**：EvidenceService 驗證該目錄頁是發行單位官方紀錄，並以頁面中的條目作為 Authoritative Evidence。
- **Scope**：沿用 RC-59 的 `MONITORED_STANDARD` 依據。目錄條目已經是結構化的正式紀錄，是否仍需 helper 判斷，實作時再定。
- **其餘不變**：TemporalRule 用檢查月份；Reportability、地區例外、報告章節、Delivery 都不變。新聞的編號查詢可保留，作為補充發現。
- **需修訂契約**：§C Phase 2B-A 的 provider 清單，以及 §H 允許官方目錄紀錄作為 Evidence。

## 8. 仍需使用者決定（阻擋項）

1. 是否核准新增「標準目錄」provider 與上述契約修訂，並先實作直接可用的 14 項：IEC 11、ASTM 2、IEEE 1。
2. EN 9 項：官方網站禁止自動存取。可選擇：
   - 接受 genorma.com 作為次級來源；
   - 改由國家標準組織或 CEN-CENELEC 取得授權或訂閱；
   - 暫時只靠新聞。
3. NFPA 70、130：官方頁沒有日期。可選擇：
   - 接受比較版本年份（需要保存上次的版本年，屬新增狀態）；
   - 改用 NFPA 的通知；
   - 暫時只靠新聞。
4. UIC 860-0：找不到可定位的現行紀錄，請確認是否仍有效，或已改為其他 UIC／IRS 文件。
5. NFPA 258 已於 2006 年撤回：是否從監控清單移除，或保留但註明已撤回。
6. EN 50128 已被 EN 50716:2023 取代：是否改為監控 EN 50716，或維持原清單。
7. 上線前由人工確認 IEC、ASTM、IEEE 的網站使用條款，本次未能讀到。
8. IEC 的草案階段（CDV、FDIS）不在 webstore 頁面上；若要偵測 IEC 的正式草案，需另查 IEC 專案頁，本次未檢查。
