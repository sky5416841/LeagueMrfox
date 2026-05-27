# LeagueMrfox

> 英雄聯盟 LCU 戰情終端 — Cyberpunk 風格桌面工具

[![Version](https://img.shields.io/badge/version-1.0-cyan)](#)
[![Platform](https://img.shields.io/badge/platform-Windows-blue)](#)
[![Python](https://img.shields.io/badge/python-3.11-green)](#)

---

## 功能

| 模組 | 說明 |
|------|------|
| **戰績** | 分頁瀏覽近 200 場戰紀錄，含 KDA、傷害、裝備、符文、時長；對局結束自動刷新 |
| **對戰** | 大廳 / 遊戲中自動掃描全場 10 人，顯示近 20 場勝率、KDA、即時段位 |
| **自動化** | 自動接受配對、自動選角、自動禁角（秒選 / 秒禁） |
| **英雄分析** | 統計個人拿手英雄與避雷英雄（≥3 場）、平均傷害 |
| **10 人雷達** | 進入遊戲後雙欄呈現敵我雙方戰力，含段位透視（單排 / 彈性） |

---

## 使用方式

### 直接執行（推薦）

從 [Releases](../../releases) 下載最新版 `LeagueMrfox.exe`，在**英雄聯盟客戶端開啟的狀態下**執行即可，無需安裝 Python。

### 從原始碼啟動

```bash
pip install eel requests psutil websockets urllib3
python main.py
```

> 需要 Python 3.11，並確保英雄聯盟客戶端正在執行。

---

## 自行打包

1. 將 `app.ico` 放入專案根目錄與 `web/` 資料夾
2. 執行：

```bash
pip install pyinstaller
build.bat
```

輸出：`dist\LeagueMrfox.exe`（單一執行檔，無黑視窗）

---

## 系統需求

- Windows 10 / 11
- 英雄聯盟客戶端（執行中）
- Microsoft Edge 或 Google Chrome

---

## 技術架構

- **後端**：Python 3.11 + [Eel](https://github.com/python-eel/Eel)
- **前端**：Vanilla JS + Tailwind CSS
- **通訊**：LCU API（本機 HTTPS + WebSocket 事件）
- **打包**：PyInstaller（`--onefile --noconsole`）

---

## 隱私聲明

本工具僅在本機與英雄聯盟客戶端通訊，**不會上傳、儲存或傳送任何玩家個人資料**。

---

## 注意事項

- 本工具僅供個人學習與研究使用
- 請勿用於違反 Riot Games 服務條款的行為
- LCU API 為非官方介面，Riot 可能隨時異動
