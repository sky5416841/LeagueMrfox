# LeagueMrfox

英雄聯盟本地客戶端監控面板，透過 LCU (League Client Update) API 即時讀取遊戲資料，提供賽博龐克風格的終端介面。

## 功能

- **即時戰績查詢（最多 200 場）**：透過 SGP API 突破 LCU 本地 20 筆上限，直接向 Riot 伺服器拉取最近 200 場對局，顯示英雄、KDA、傷害、裝備、符文
- **分頁瀏覽**：可選每頁 10 / 20 / 50 / 100 / 200 筆，支援翻頁，偏移量正確傳遞
- **對局狀態標記**：自動識別「重開 (Remake)」、「投降勝」、「投降敗」，以不同顏色標示
- **10 人完整戰報**：點擊任意戰績卡片展開 Modal，顯示藍隊／紅隊全員數據
- **增幅裝置支援**：Arena / Mayhem 模式自動顯示增幅裝置圖示及稀有度邊框（銀色／金色／彩虹）
- **傷害雙條**：輸出傷害與承受傷害並排顯示，含相對進度條
- **牌位顯示**：單排／彈性排位段位即時讀取
- **自動接受配對**：偵測到配對時自動點擊接受
- **自動選角 (Auto-Pick)**：選角階段輪到行動時自動秒選並鎖定指定英雄

## 系統需求

- Windows 10 / 11
- Python 3.10+
- 英雄聯盟客戶端（執行中）
- Microsoft Edge 或 Google Chrome（用於顯示 UI）

## 安裝

```bash
git clone https://github.com/sky5416841/LeagueMrfox.git
cd LeagueMrfox
python -m venv .venv
.venv\Scripts\activate
pip install eel psutil requests websockets urllib3
```

## 啟動

確保英雄聯盟客戶端已開啟，然後執行：

```bash
python main.py
```

程式會自動偵測客戶端連接埠並啟動瀏覽器介面。

## 原理

本工具透過讀取本機的 `lockfile`（位於英雄聯盟安裝目錄）取得連接埠與密碼，再以 HTTPS + Basic Auth 存取 LCU API（`https://127.0.0.1:{port}`）。

### 200 場戰績的實作方式

LCU 本地 API 每次最多只能回傳約 20 筆戰績。本工具參考 [LeagueAkari](https://github.com/LeagueAkari/LeagueAkari) 的架構，改用 **SGP（Service Gateway Proxy）API** 直接向 Riot 後端伺服器查詢：

1. 啟動時從 `idToken` JWT payload 解析玩家所在伺服器（如 `TW2`）
2. 從 `/entitlements/v1/token` 取得 Bearer 認證 Token
3. 向對應區域的 SGP 端點發送請求：
   ```
   GET https://apse1-red.pp.sgp.pvp.net/match-history-query/v1/products/lol/player/{puuid}/SUMMARY
       ?startIndex=0&count=200
   Authorization: Bearer {entitlementToken}
   ```
4. SGP 無單次筆數限制，可一次取得任意數量。若 SGP 不可用，自動降級至 LCU + 本地 JSON 快取累加。

所有資料均在本機處理，不會上傳至任何第三方伺服器。

## 注意事項

- 本工具僅供個人學習與研究使用
- 請勿用於違反 Riot Games 服務條款的行為
- LCU API 為非官方 API，Riot 可能隨時更動介面

## 授權

MIT License
