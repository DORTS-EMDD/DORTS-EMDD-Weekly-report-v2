# 監控標準的目錄來源：選項草案 v1

狀態：**草案，未生效，未實作。** 需要使用者選擇來源（第 5 節 Q1～Q4），才能修訂契約與實作。
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
