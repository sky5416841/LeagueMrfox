# LeagueMrfox

英雄聯盟本地客戶端監控面板，透過 LCU (League Client Update) API 即時讀取遊戲資料，提供賽博龐克風格的終端介面。

## 功能

- **即時戰績查詢**：讀取最近最多 200 場對局，顯示英雄、KDA、傷害、裝備、符文
- **10 人完整戰報**：點擊任意戰績卡片展開 Modal，顯示藍隊／紅隊全員數據
- **增幅裝置支援**：Arena (大亂鬥 Mayhem) 模式自動顯示增幅裝置圖示及稀有度邊框
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

本工具透過讀取本機的 `lockfile`（位於英雄聯盟安裝目錄）取得連接埠與密碼，再以 HTTPS + Basic Auth 存取 LCU API（`https://127.0.0.1:{port}`）。所有資料均在本機處理，不會上傳至任何伺服器。

## 注意事項

- 本工具僅供個人學習與研究使用
- 請勿用於違反 Riot Games 服務條款的行為
- LCU API 為非官方 API，Riot 可能隨時更動介面

## 授權

MIT License
