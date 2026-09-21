# V2 Search Language Profiles Contract

Status: authoritative subordinate Search Planner / Region Registry support
contract for the selected-market discovery configuration.

This document is governed by `docs/ARCHITECTURE_CONTRACT.md`. It defines
discovery-language coverage and bounded query vocabulary. It does not create
or change an Evidence, Scope, Date, Category, E&M Taxonomy, Reportability, or
other downstream owner.

## 1. Scope and authority

The authoritative selected-market registry is the 20-market list in the
Architecture Contract. `region_mode=selected` uses that registry;
`region_mode=global` remains a separate mode and may include additional
markets in the future. This document does not redefine global mode.

The profile list and mapping were recovered from repository evidence:

* V2 `docs/ARCHITECTURE_CONTRACT.md` supplies the locked selected-market
  registry and the four discovery intents.
* The V1 frozen reference `search_queries.py` supplies explicit `lang`
  metadata, `REGION_NEWS_QUERIES`, `REGION_QUERY_LANGUAGES`, and
  `SEARCH_LANGUAGE_MARKERS`.
* The V1 frozen reference `test_search_query_coverage.py` explicitly verifies
  the ten mature multilingual query codes `en`, `de`, `fr`, `es`, `it`, `pt`,
  `ru`, `ja`, `ko`, and `zh`.
* V1 `REGION_NEWS_QUERIES` adds the selected-market query codes `nl`, `sv`,
  `da`, and `no`.

V1 is evidence for discovery material only. V1 Scope, Evidence, Date,
selection, rescue, and fallback decisions are not imported into V2.

The 13 selected-market profiles are therefore:

```text
en, zh, ja, ko, de, fr, es, it, pt, nl, sv, da, no
```

The V1 `ru` profile remains available as non-selected/global reference
material, but is not one of the 13 profiles in this selected-market contract.

## 2. Search-only boundary

Search Planner may use these profiles for:

* query generation;
* local-language discovery coverage;
* synonym and transliteration expansion;
* provider query formulation; and
* bounded market-aware discovery.

Search language, a query term, a provider result, a publisher, or a market
profile **MUST NOT** formally decide:

```text
EVIDENCE_READY
IN_SCOPE
DATE_VALID
Category
E&M Taxonomy
REPORTABLE
```

A keyword appearing in this document is discovery vocabulary only. The same
Candidate must pass the shared downstream owners as every other Candidate.
Country-specific mapping is configuration, not country-specific Domain Rule
logic.

## 3. Selected markets and deterministic mapping

`en` is a secondary discovery fallback for non-English selected markets where
the table says `en`. It supplements, and does not replace, the primary local
profile. No Cartesian product of every language and every market is implied.

| Selected market | Primary profile(s) | Secondary applicable profile(s) | English fallback |
| --- | --- | --- | --- |
| Taiwan | `zh` | — | `en` |
| South Korea | `ko` | — | `en` |
| Hong Kong | `zh` | — | `en` |
| United Kingdom | `en` | — | — |
| Germany | `de` | — | `en` |
| Canada | `en` | `fr` | — |
| Netherlands | `nl` | — | `en` |
| Italy | `it` | — | `en` |
| Austria | `de` | — | `en` |
| Norway | `no` | — | `en` |
| Portugal | `pt` | — | `en` |
| Japan | `ja` | — | `en` |
| Singapore | `en` | — | — |
| Australia | `en` | — | — |
| France | `fr` | — | `en` |
| United States | `en` | — | — |
| Spain | `es` | — | `en` |
| Switzerland | `de` | `fr`, `it` | `en` |
| Sweden | `sv` | — | `en` |
| Denmark | `da` | — | `en` |

The profile-level market registry is:

| Profile ID | Display name | Language / script | Primary markets | Secondary applicable markets |
| --- | --- | --- | --- | --- |
| `en` | English | English / Latin | United Kingdom, Canada, Singapore, Australia, United States | Taiwan, South Korea, Hong Kong, Germany, Netherlands, Italy, Austria, Norway, Portugal, Japan, France, Spain, Switzerland, Sweden, Denmark |
| `zh` | Chinese | Traditional and Simplified Chinese / Han | Taiwan, Hong Kong | — |
| `ja` | Japanese | Japanese / Kanji and Kana | Japan | — |
| `ko` | Korean | Korean / Hangul | South Korea | — |
| `de` | German | German / Latin | Germany, Austria, Switzerland | — |
| `fr` | French | French / Latin | France | Canada, Switzerland |
| `es` | Spanish | Spanish / Latin | Spain | — |
| `it` | Italian | Italian / Latin | Italy | Switzerland |
| `pt` | Portuguese | Portuguese / Latin | Portugal | — |
| `nl` | Dutch | Dutch / Latin | Netherlands | — |
| `sv` | Swedish | Swedish / Latin | Sweden | — |
| `da` | Danish | Danish / Latin | Denmark | — |
| `no` | Norwegian | Norwegian / Latin | Norway | — |

`Switzerland → de, fr, it` is a bounded applicable mapping, not permission
to issue every profile for every query. `Singapore` remains English-primary
because the recovered project query material provides English Singapore
coverage but does not establish a separate Chinese, Malay, or Tamil profile.

## 4. Query composition and bounds

The future Search Planner should compose a bounded query from conceptual
groups:

```text
market anchor
+ urban-rail anchor
+ one discovery-intent group
+ optional technology/system term
+ optional location or operator term
```

The Planner **MAY** select one or more deterministic templates per enabled
intent and profile. It **MUST** enforce a configured query budget and stable
ordering. It **MUST NOT** generate an unbounded Cartesian product of markets,
languages, synonyms, systems, and intents.

Shared technical terms such as `CBTC`, `MRT`, `LRT`, `BIM`, `AFC`, `ATO`,
`ATP`, `IoT`, and `digital twin` may be reused across profiles where they are
normal discovery terms. Reuse does not make a term formal Scope evidence.

The groups below are conceptual vocabulary groups, not a downstream keyword
classifier. A future runtime representation must be derived from this one
contract rather than maintained as a divergent second registry.

## 5. Intent vocabulary groups

Every enabled profile covers all four Architecture Contract discovery intents:
`technology`, `major_incident`, `operations`, and `procurement`.

The terms are intentionally broad discovery seeds. The technology intent
preserves the highest priority of new technology, new material, and new
method, including trials, pilots, deployment, commissioning, upgrades,
modernization, innovation, automation, digitalization, new systems, and new
equipment.

### `en` — English

* `technology`: `urban_rail_terms=metro, subway, MRT, LRT, light rail, tram, tramway, streetcar, AGT, monorail, people mover`; `technology_terms=CBTC, signalling, communications, rolling stock, traction power, AFC, platform screen doors, predictive maintenance, digital twin, automation`; `new_material_terms=advanced material, composite, lightweight, fire-resistant, energy-storage material`; `new_method_terms=pilot, trial, testing, deployment, commissioning, upgrade, modernization, innovation, new system`.
* `major_incident`: `urban_rail_terms=metro, subway, LRT, tram, light rail`; `accident_terms=collision, derailment, fire, smoke, injury, fatality`; `disruption_terms=service suspension, shutdown, disruption, evacuation`; `technical_failure_terms=power failure, signal failure, system failure, infrastructure failure`; `safety_terms=safety investigation, technical incident, emergency response`.
* `operations`: `urban_rail_terms=metro, subway, tram, light rail`; `policy_terms=policy, regulation, approval, operating plan`; `dispute_terms=strike, union, lawsuit, dispute, arbitration, protest`; `opening_service_terms=line opening, service opening, passenger service, commissioning`; `fare_ticketing_terms=fare, ticketing, fare gate`; `operating_method_terms=operating hours, service change, line extension, capacity, management change`.
* `procurement`: `urban_rail_terms=metro, subway, tram, light rail, urban rail`; `tender_terms=tender, bid, request for proposal, framework agreement`; `procurement_terms=procurement, equipment procurement, system replacement`; `award_terms=award, awarded, contract award`; `contract_terms=contract, modernization contract, delivery milestones`.

### `zh` — Chinese

* `technology`: `urban_rail_terms=地鐵, 地铁, 捷運, MRT, 輕軌, 轻轨, 電車, 城市軌道, 單軌, 旅客捷運`; `technology_terms=號誌/信号, 通訊, 車輛/车辆, 電聯車, 供電, 自動收費, 月臺門/站台门, 數位孿生/数字孪生, 預測維護/预测维护`; `new_material_terms=新材料, 複合材料/复合材料, 輕量化材料/轻量化材料, 儲能材料`; `new_method_terms=試驗/试验, 試點/试点, 測試/测试, 部署, 導入, 啟用, 升級, 現代化, 創新, 新系統/新系统, 新設備/新设备`.
* `major_incident`: `urban_rail_terms=地鐵, 地铁, 捷運, 輕軌, 轻轨, 電車`; `accident_terms=碰撞, 撞擊, 脫軌/脱轨, 火災/火灾, 煙霧/烟雾, 傷亡/伤亡`; `disruption_terms=停駛/停驶, 中斷/中断, 疏散, 線路故障`; `technical_failure_terms=停電/停电, 號誌故障/信号故障, 系統故障/系统故障, 基礎設施故障/基础设施故障`; `safety_terms=安全事故, 技術事故/技术事故, 調查, 應變/应变`.
* `operations`: `urban_rail_terms=地鐵, 地铁, 捷運, MRT, 輕軌, 轻轨, 電車`; `policy_terms=政策, 規範/规范, 核准, 營運計畫/运营计划`; `dispute_terms=罷工/罢工, 勞資爭議/劳资争议, 合約爭議/合同争议, 仲裁, 抗議/抗议`; `opening_service_terms=通車, 开通, 開業, 開幕, 載客, 旅客服務/旅客服务`; `fare_ticketing_terms=票價/票价, 售票, 票務/票务, 閘門/闸门`; `operating_method_terms=班次, 運行時間/运行时间, 服務調整/服务调整, 路線延伸/路线延伸, 運能/运能, 管理變更/管理变更`.
* `procurement`: `urban_rail_terms=地鐵, 地铁, 捷運, MRT, 輕軌, 轻轨, 城市軌道`; `tender_terms=招標/招标, 投標/投标, 徵求提案/征求提案`; `procurement_terms=採購/采购, 設備採購/设备采购, 系統更新/系统更新`; `award_terms=決標/决标, 得標/得标, 授標/授标`; `contract_terms=合約/合同, 框架協議/框架协议, 現代化合約/现代化合同`.

### `ja` — Japanese

* `technology`: `urban_rail_terms=地下鉄, メトロ, 路面電車, 新交通システム, 都市鉄道, 軌道`; `technology_terms=信号, 車両, 通信, 電力, CBTC, 自動運転, 予測保全, デジタルツイン`; `new_material_terms=新材料, 複合材料, 軽量材料, 蓄電材料`; `new_method_terms=試験, 実証, 実証実験, 導入, 更新, 改修, 近代化, 自動化, 新システム, 新設備`.
* `major_incident`: `urban_rail_terms=地下鉄, メトロ, 路面電車, 都市鉄道`; `accident_terms=脱線, 衝突, 火災, 煙, 負傷, 死亡`; `disruption_terms=運休, 運転見合わせ, 避難, 輸送障害`; `technical_failure_terms=停電, 信号故障, システム障害, 設備故障`; `safety_terms=安全事故, 技術事故, 調査, 対策`.
* `operations`: `urban_rail_terms=地下鉄, メトロ, 路面電車, 都市鉄道`; `policy_terms=政策, 規則, 認可, 運行計画`; `dispute_terms=ストライキ, 労使紛争, 契約紛争, 仲裁, 抗議`; `opening_service_terms=開業, 開通, 営業運転開始, 旅客サービス`; `fare_ticketing_terms=運賃, 料金, 券売, チケット`; `operating_method_terms=運行時間, 路線延伸, 運行変更, 輸送力, 経営変更`.
* `procurement`: `urban_rail_terms=地下鉄, メトロ, 路面電車, 都市鉄道`; `tender_terms=入札, 公募, 提案依頼, 枠組み契約`; `procurement_terms=調達, 機器調達, システム更新`; `award_terms=落札, 契約締結, 発注`; `contract_terms=契約, 更新契約, 納入計画`.

### `ko` — Korean

* `technology`: `urban_rail_terms=지하철, 도시철도, 경전철, 트램, 모노레일, 신교통`; `technology_terms=신호, 차량, 통신, 전력, CBTC, 자동운전, 예지정비, 디지털 트윈`; `new_material_terms=신소재, 복합재료, 경량 소재, 에너지저장 소재`; `new_method_terms=시험, 실증, 시범, 도입, 개량, 현대화, 자동화, 디지털화, 신규 시스템, 신규 장비`.
* `major_incident`: `urban_rail_terms=지하철, 도시철도, 경전철, 트램`; `accident_terms=탈선, 충돌, 화재, 연기, 부상, 사망`; `disruption_terms=운행중단, 운행차질, 대피, 수송장애`; `technical_failure_terms=정전, 신호장애, 시스템 고장, 시설 고장`; `safety_terms=안전사고, 기술사고, 조사, 대응`.
* `operations`: `urban_rail_terms=지하철, 도시철도, 경전철, 트램`; `policy_terms=정책, 규정, 승인, 운행계획`; `dispute_terms=파업, 노사분쟁, 계약분쟁, 중재, 시위`; `opening_service_terms=개통, 영업운전 개시, 승객 서비스`; `fare_ticketing_terms=요금, 승차권, 발권, 개찰`; `operating_method_terms=운행시간, 노선연장, 서비스 변경, 수송능력, 운영 변경`.
* `procurement`: `urban_rail_terms=지하철, 도시철도, 경전철, 트램`; `tender_terms=입찰, 공고, 제안요청, 기본협약`; `procurement_terms=조달, 장비 조달, 시스템 교체`; `award_terms=낙찰, 계약 체결, 발주`; `contract_terms=계약, 현대화 계약, 납품 일정`.

### `de` — German

* `technology`: `urban_rail_terms=U-Bahn, Stadtbahn, Straßenbahn, Tram, urbaner Schienenverkehr`; `technology_terms=Signaltechnik, Fahrzeuge, Kommunikation, Energieversorgung, CBTC, Zustandsüberwachung, Digitalisierung`; `new_material_terms=neuer Werkstoff, Verbundwerkstoff, Leichtbau, Energiespeichermaterial`; `new_method_terms=Erprobung, Pilot, Testbetrieb, Einführung, Modernisierung, Automatisierung, neues System, neue Ausrüstung`.
* `major_incident`: `urban_rail_terms=U-Bahn, Stadtbahn, Straßenbahn, Tram`; `accident_terms=Entgleisung, Zusammenstoß, Kollision, Brand, Rauch, Verletzte, Todesopfer`; `disruption_terms=Betriebsunterbrechung, Streckensperrung, Evakuierung, Verkehrsstörung`; `technical_failure_terms=Stromausfall, Signalstörung, Systemausfall, Infrastrukturausfall`; `safety_terms=Sicherheitsunfall, technischer Vorfall, Untersuchung, Notfallmaßnahmen`.
* `operations`: `urban_rail_terms=U-Bahn, Stadtbahn, Straßenbahn, Tram`; `policy_terms=Politik, Regelung, Genehmigung, Betriebsplan`; `dispute_terms=Streik, Gewerkschaft, Vertragsstreit, Schiedsverfahren, Protest`; `opening_service_terms=Eröffnung, Inbetriebnahme, Fahrgastbetrieb, Linieneröffnung`; `fare_ticketing_terms=Tarif, Fahrkarte, Ticketing, Fahrgeldmanagement`; `operating_method_terms=Fahrplan, Betriebszeiten, Linienverlängerung, Kapazität, Betriebsänderung`.
* `procurement`: `urban_rail_terms=U-Bahn, Stadtbahn, Straßenbahn, Tram`; `tender_terms=Ausschreibung, Vergabe, Angebot, Aufforderung zur Angebotsabgabe, Rahmenvertrag`; `procurement_terms=Beschaffung, Ausrüstungsbeschaffung, Systemersatz`; `award_terms=Zuschlag, Auftragsvergabe, Auftragserteilung`; `contract_terms=Vertrag, Modernisierungsvertrag, Lieferplan`.

### `fr` — French

* `technology`: `urban_rail_terms=métro, tramway, tram, transport urbain sur rail, métro léger`; `technology_terms=signalisation, matériel roulant, communication, alimentation électrique, CBTC, maintenance prédictive, jumeau numérique`; `new_material_terms=nouveau matériau, matériau composite, matériau léger, matériau de stockage d'énergie`; `new_method_terms=essai, pilote, expérimentation, déploiement, mise en service, modernisation, automatisation, nouveau système, nouvel équipement`.
* `major_incident`: `urban_rail_terms=métro, tramway, transport urbain sur rail`; `accident_terms=déraillement, collision, incendie, fumée, blessé, décès`; `disruption_terms=interruption de service, arrêt du trafic, évacuation, perturbation`; `technical_failure_terms=panne électrique, panne de signalisation, défaillance du système, défaillance de l'infrastructure`; `safety_terms=incident technique, accident de sécurité, enquête, intervention`.
* `operations`: `urban_rail_terms=métro, tramway, transport urbain sur rail`; `policy_terms=politique, réglementation, autorisation, plan d'exploitation`; `dispute_terms=grève, conflit social, litige contractuel, arbitrage, protestation`; `opening_service_terms=ouverture de ligne, mise en service, service voyageurs`; `fare_ticketing_terms=tarif, billettique, titre de transport, valideur`; `operating_method_terms=horaires, extension de ligne, changement de service, capacité, changement de gestion`.
* `procurement`: `urban_rail_terms=métro, tramway, transport urbain sur rail`; `tender_terms=appel d'offres, soumission, demande de propositions, accord-cadre`; `procurement_terms=achat, approvisionnement, acquisition d'équipement, remplacement de système`; `award_terms=attribution, marché attribué, commande`; `contract_terms=contrat, contrat de modernisation, calendrier de livraison`.

### `es` — Spanish

* `technology`: `urban_rail_terms=metro, tranvía, tren ligero, ferrocarril urbano, transporte urbano sobre rail`; `technology_terms=señalización, material rodante, comunicaciones, energía de tracción, CBTC, mantenimiento predictivo, gemelo digital`; `new_material_terms=nuevo material, material compuesto, material ligero, material para almacenamiento de energía`; `new_method_terms=prueba, piloto, ensayo, despliegue, puesta en servicio, modernización, automatización, nuevo sistema, nuevo equipo`.
* `major_incident`: `urban_rail_terms=metro, tranvía, tren ligero`; `accident_terms=descarrilamiento, colisión, incendio, humo, heridos, fallecidos`; `disruption_terms=suspensión del servicio, interrupción, evacuación, perturbación`; `technical_failure_terms=fallo eléctrico, fallo de señalización, fallo del sistema, fallo de infraestructura`; `safety_terms=incidente técnico, accidente de seguridad, investigación, respuesta de emergencia`.
* `operations`: `urban_rail_terms=metro, tranvía, tren ligero`; `policy_terms=política, normativa, aprobación, plan operativo`; `dispute_terms=huelga, conflicto laboral, disputa contractual, arbitraje, protesta`; `opening_service_terms=apertura de línea, puesta en servicio, servicio de pasajeros`; `fare_ticketing_terms=tarifa, billetaje, billete, control de acceso`; `operating_method_terms=horario, ampliación de línea, cambio de servicio, capacidad, cambio de gestión`.
* `procurement`: `urban_rail_terms=metro, tranvía, tren ligero`; `tender_terms=licitación, concurso, solicitud de propuestas, acuerdo marco`; `procurement_terms=contratación, adquisición de equipos, sustitución del sistema`; `award_terms=adjudicación, contrato adjudicado, encargo`; `contract_terms=contrato, contrato de modernización, calendario de entrega`.

### `it` — Italian

* `technology`: `urban_rail_terms=metro, metropolitana, tram, ferrovia urbana, metropolitana leggera`; `technology_terms=segnalamento, materiale rotabile, comunicazioni, alimentazione, CBTC, manutenzione predittiva, gemello digitale`; `new_material_terms=nuovo materiale, materiale composito, materiale leggero, materiale per accumulo energetico`; `new_method_terms=prova, pilota, sperimentazione, implementazione, messa in servizio, ammodernamento, automazione, nuovo sistema, nuova apparecchiatura`.
* `major_incident`: `urban_rail_terms=metro, metropolitana, tram, ferrovia urbana`; `accident_terms=deragliamento, collisione, incendio, fumo, feriti, vittime`; `disruption_terms=sospensione del servizio, interruzione, evacuazione, disservizio`; `technical_failure_terms=guasto elettrico, guasto al segnalamento, guasto del sistema, guasto infrastrutturale`; `safety_terms=incidente tecnico, incidente di sicurezza, indagine, risposta di emergenza`.
* `operations`: `urban_rail_terms=metro, metropolitana, tram, ferrovia urbana`; `policy_terms=politica, normativa, autorizzazione, piano operativo`; `dispute_terms=sciopero, controversia sindacale, controversia contrattuale, arbitrato, protesta`; `opening_service_terms=apertura della linea, avvio del servizio, servizio passeggeri`; `fare_ticketing_terms=tariffa, bigliettazione, biglietto, tornello`; `operating_method_terms=orario, prolungamento della linea, modifica del servizio, capacità, cambio di gestione`.
* `procurement`: `urban_rail_terms=metro, metropolitana, tram, ferrovia urbana`; `tender_terms=appalto, gara, offerta, richiesta di proposta, accordo quadro`; `procurement_terms=approvvigionamento, acquisto di apparecchiature, sostituzione del sistema`; `award_terms=aggiudicazione, contratto assegnato, ordine`; `contract_terms=contratto, contratto di ammodernamento, programma di consegna`.

### `pt` — Portuguese

* `technology`: `urban_rail_terms=metro, metropolitana, tram, transporte ferroviário urbano, funicular`; `technology_terms=sinalização, material circulante, comunicações, energia de tração, CBTC, manutenção preditiva, gémeo digital`; `new_material_terms=novo material, material compósito, material leve, material para armazenamento de energia`; `new_method_terms=ensaio, piloto, teste, implementação, entrada em serviço, modernização, automação, novo sistema, novo equipamento`.
* `major_incident`: `urban_rail_terms=metro, metropolitana, tram, transporte ferroviário urbano`; `accident_terms=descarrilamento, colisão, incêndio, fumo, feridos, mortos`; `disruption_terms=suspensão do serviço, interrupção, evacuação, perturbação`; `technical_failure_terms=falha elétrica, falha de sinalização, falha do sistema, falha de infraestrutura`; `safety_terms=acidente técnico, incidente de segurança, investigação, resposta de emergência`.
* `operations`: `urban_rail_terms=metro, metropolitana, tram, transporte ferroviário urbano`; `policy_terms=política, regulamentação, autorização, plano operacional`; `dispute_terms=greve, conflito laboral, disputa contratual, arbitragem, protesto`; `opening_service_terms=abertura da linha, entrada em serviço, serviço de passageiros`; `fare_ticketing_terms=tarifa, bilhética, título de transporte, torniquete`; `operating_method_terms=horário, extensão da linha, alteração do serviço, capacidade, mudança de gestão`.
* `procurement`: `urban_rail_terms=metro, metropolitana, tram, transporte ferroviário urbano`; `tender_terms=concurso, licitação, proposta, pedido de propostas, acordo-quadro`; `procurement_terms=contratação, aquisição de equipamento, substituição do sistema`; `award_terms=adjudicação, contrato adjudicado, encomenda`; `contract_terms=contrato, contrato de modernização, calendário de entrega`.

### `nl` — Dutch

* `technology`: `urban_rail_terms=metro, tram, lightrail, stedelijk spoorvervoer`; `technology_terms=seintechniek, rollend materieel, communicatie, tractie-energie, CBTC, voorspellend onderhoud, digitale tweeling`; `new_material_terms=nieuw materiaal, composietmateriaal, lichtgewicht materiaal, energieopslagmateriaal`; `new_method_terms=proef, pilot, test, ingebruikname, implementatie, modernisering, automatisering, nieuw systeem, nieuwe apparatuur`.
* `major_incident`: `urban_rail_terms=metro, tram, lightrail, stedelijk spoorvervoer`; `accident_terms=ongeval, botsing, ontsporing, brand, rook, gewonden, doden`; `disruption_terms=dienstonderbreking, uitval, evacuatie, verstoring`; `technical_failure_terms=stroomstoring, seininstallatiestoring, systeemstoring, infrastructuurstoring`; `safety_terms=technisch incident, veiligheidsincident, onderzoek, noodrespons`.
* `operations`: `urban_rail_terms=metro, tram, lightrail`; `policy_terms=beleid, regelgeving, vergunning, exploitatieplan`; `dispute_terms=staking, arbeidsconflict, contractgeschil, arbitrage, protest`; `opening_service_terms=lijnopening, ingebruikname, reizigersdienst`; `fare_ticketing_terms=tarief, ticketing, kaartje, toegangspoort`; `operating_method_terms=dienstregeling, lijnverlenging, dienstwijziging, capaciteit, managementwijziging`.
* `procurement`: `urban_rail_terms=metro, tram, lightrail`; `tender_terms=aanbesteding, inschrijving, offerteaanvraag, raamovereenkomst`; `procurement_terms=inkoop, apparatuurinkoop, systeemvervanging`; `award_terms=gunning, gegund contract, opdracht`; `contract_terms=contract, moderniseringscontract, leveringsplanning`.

### `sv` — Swedish

* `technology`: `urban_rail_terms=tunnelbana, spårväg, stadsbana, lättbana`; `technology_terms=signalteknik, fordon, kommunikation, dragkraft, CBTC, tillståndsövervakning, digital tvilling`; `new_material_terms=nytt material, kompositmaterial, lättviktsmaterial, energilagringsmaterial`; `new_method_terms=prov, pilot, test, driftsättning, modernisering, automatisering, digitalisering, nytt system, ny utrustning`.
* `major_incident`: `urban_rail_terms=tunnelbana, spårväg, lättbana`; `accident_terms=olycka, kollision, urspårning, brand, rök, skadade, omkomna`; `disruption_terms=trafikstopp, driftstörning, evakuering, störning`; `technical_failure_terms=strömavbrott, signalfel, systemfel, infrastrukturfel`; `safety_terms=teknisk incident, säkerhetsincident, utredning, räddningsinsats`.
* `operations`: `urban_rail_terms=tunnelbana, spårväg, lättbana`; `policy_terms=policy, föreskrift, tillstånd, driftplan`; `dispute_terms=strejk, arbetskonflikt, avtalskonflikt, skiljeförfarande, protest`; `opening_service_terms=linjeöppning, trafikstart, passagerartrafik`; `fare_ticketing_terms=taxa, biljettering, biljett, spärr`; `operating_method_terms=tidtabell, linjeförlängning, trafikändring, kapacitet, ledningsändring`.
* `procurement`: `urban_rail_terms=tunnelbana, spårväg, lättbana`; `tender_terms=upphandling, anbud, offertförfrågan, ramavtal`; `procurement_terms=inköp, utrustningsinköp, systembyte`; `award_terms=kontraktstilldelning, tilldelat kontrakt, beställning`; `contract_terms=avtal, moderniseringsavtal, leveransplan`.

### `da` — Danish

* `technology`: `urban_rail_terms=metro, letbane, sporvogn, bybane`; `technology_terms=signalteknik, køretøjer, kommunikation, traktionsenergi, CBTC, tilstandsbaseret vedligehold, digital tvilling`; `new_material_terms=nyt materiale, kompositmateriale, letvægtsmateriale, energilagringsmateriale`; `new_method_terms=prøve, pilot, test, ibrugtagning, modernisering, automatisering, digitalisering, nyt system, nyt udstyr`.
* `major_incident`: `urban_rail_terms=metro, letbane, sporvogn, bybane`; `accident_terms=ulykke, kollision, afsporing, brand, røg, tilskadekomne, omkomne`; `disruption_terms=driftsforstyrrelse, driftsstop, evakuering, trafikforstyrrelse`; `technical_failure_terms=strømsvigt, signalfejl, systemfejl, infrastrukturfejl`; `safety_terms=teknisk hændelse, sikkerhedshændelse, undersøgelse, beredskab`.
* `operations`: `urban_rail_terms=metro, letbane, sporvogn, bybane`; `policy_terms=politik, regulering, godkendelse, driftsplan`; `dispute_terms=strejke, arbejdsstrid, kontraktstrid, voldgift, protest`; `opening_service_terms=linjeåbning, ibrugtagning, passagerdrift`; `fare_ticketing_terms=takst, billet, billetsystem, adgangskontrol`; `operating_method_terms=køreplan, linjeforlængelse, driftsændring, kapacitet, ledelsesændring`.
* `procurement`: `urban_rail_terms=metro, letbane, sporvogn, bybane`; `tender_terms=udbud, tilbud, anmodning om forslag, rammeaftale`; `procurement_terms=indkøb, udstyrsindkøb, systemudskiftning`; `award_terms=tildeling, tildelt kontrakt, ordre`; `contract_terms=kontrakt, moderniseringskontrakt, leveringsplan`.

### `no` — Norwegian

* `technology`: `urban_rail_terms=T-bane, trikk, bybane, light rail`; `technology_terms=signalteknikk, kjøretøy, kommunikasjon, trekkraft, CBTC, tilstandsbasert vedlikehold, digital tvilling`; `new_material_terms=nytt materiale, komposittmateriale, lettvektsmateriale, energilagringsmateriale`; `new_method_terms=prøve, pilot, test, idriftsettelse, modernisering, automatisering, digitalisering, nytt system, nytt utstyr`.
* `major_incident`: `urban_rail_terms=T-bane, trikk, bybane`; `accident_terms=ulykke, kollisjon, avsporing, brann, røyk, skadde, omkomne`; `disruption_terms=driftsstans, driftsforstyrrelse, evakuering, trafikkforstyrrelse`; `technical_failure_terms=strømbrudd, signalfeil, systemfeil, infrastrukturfeil`; `safety_terms=teknisk hendelse, sikkerhetshendelse, gransking, beredskap`.
* `operations`: `urban_rail_terms=T-bane, trikk, bybane`; `policy_terms=politikk, forskrift, godkjenning, driftsplan`; `dispute_terms=streik, arbeidskonflikt, kontraktstvist, voldgift, protest`; `opening_service_terms=linjeåpning, trafikkstart, passasjertrafikk`; `fare_ticketing_terms=takst, billett, billettering, adgangskontroll`; `operating_method_terms=rutetabell, linjeforlengelse, driftsendring, kapasitet, ledelsesendring`.
* `procurement`: `urban_rail_terms=T-bane, trikk, bybane`; `tender_terms=anbud, tilbud, forespørsel om forslag, rammeavtale`; `procurement_terms=anskaffelse, utstyrsanskaffelse, systemutskifting`; `award_terms=tildeling, tildelt kontrakt, bestilling`; `contract_terms=kontrakt, moderniseringskontrakt, leveringsplan`.

## 6. Intent and profile rules

Each profile **MUST** expose the four intent groups above, even when a
profile-specific implementation begins with a shared English technical term
or a market anchor. A missing local translation is a coverage limitation to
record and improve; it is not permission to create a downstream rule.

`major_incident` vocabulary **MUST** remain broad discovery vocabulary. It
must not encode formal severity, injury-count, casualty, or reportability
thresholds.

`operations` vocabulary **MUST NOT** become a Category classifier. The
`operations` intent is a retrieval lane only.

`procurement` vocabulary **MUST NOT** use vendor-specific or website-specific
rules and **MUST NOT** use USD 3M as an eligibility gate. USD 3M remains the
later importance signal defined by the Architecture Contract.

Urban-rail terms such as `railway`, `train`, `station`, `line`, `signal`, and
`rolling stock` **MAY** improve recall, but they **MUST NOT** create formal
Scope authority. A local-language term in a query has the same limitation.

## 7. Runtime and ownership guard

The Region Registry remains the only owner of selected-market configuration.
The Search Planner consumes the mapping conceptually as:

```text
Region Registry market
→ Search Planner profile selection
→ bounded discovery queries
```

There must not be a second Country Registry or a manually divergent hard-coded
Python registry. A future implementation **MAY** materialize this Markdown
contract into one runtime representation, but that representation must have a
single authoritative derivation path.

Search language profiles **MUST NOT** create language-specific Evidence,
Scope, Date, Category, E&M Taxonomy, or Reportability owners. Japanese,
French, German, Chinese, and every other Candidate **MUST** enter the same
downstream owner contracts.

Search **MUST NOT** fetch another source, reinterpret an Evidence rejection,
select an alternative source, or use a query keyword as a survival gate.

## 8. Maintenance and validation

When a profile or market mapping changes, the maintainer must update this
contract and the corresponding single runtime representation together in one
review. The change must preserve:

* exactly 20 selected markets unless the Architecture Contract changes;
* exactly 13 selected-market language profiles unless this contract is
  explicitly revised;
* all four discovery intents for every enabled profile;
* bounded query generation and deterministic ordering; and
* the Search-only boundary.

Validation must include profile-ID uniqueness, market coverage exactly once in
the selected registry, explicit primary/secondary/fallback mapping, intent
coverage, and absence of downstream Domain decisions in query data.

This document is configuration documentation, not executable Golden behavior.
Golden fixtures and Evidence contracts remain unchanged.
