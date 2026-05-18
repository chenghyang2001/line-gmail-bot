# LINE × Gmail 智慧查信機器人 — 設計文件

## 一、原始需求與想法

**使用者情境**：想在 LINE 中直接詢問「addwii 有什麼優惠/方案？」，系統自動查詢 Gmail 中的 addwii 活動信件，用 AI 摘要後回傳到 LINE，不必手動開信箱。

**觸發場景**：
- 在 LINE 輸入「addwii 有什麼優惠？」
- 在 LINE 輸入「小空間要使用什麼方案？」
- 在 LINE 輸入包含任何 INTENT_KEYWORDS 的問題

---

## 二、方案比較與規劃過程

| 方案 | 優點 | 缺點 | 最終決定 |
|------|------|------|---------|
| n8n Cloud | 低程式碼、易維護 | 訂閱已取消，無法使用 | ❌ 排除 |
| Vercel Serverless | 免費、HTTPS 自動 | 10 秒 timeout 限制、無法跑 Gmail OAuth | ❌ 排除 |
| GitHub Pages | 完全免費 | 靜態網站，無法執行後端邏輯 | ❌ 排除 |
| **VPS FastAPI** | 完整 Python、無 timeout 限制、可跑 Gmail OAuth | 需管理 VPS、需設定 Cloudflare Tunnel | ✅ 採用 |

**選用理由**：VPS 方案提供完整 Python 執行環境，支援 Gmail OAuth 長效 token，Cloudflare Tunnel 提供 HTTPS，最符合需求。

---

## 三、系統架構

```
LINE App（使用者）
    │
    │ 輸入訊息（如：addwii 有什麼優惠）
    ▼
LINE Platform
    │
    │ POST Webhook（含 X-Line-Signature）
    ▼
Cloudflare Tunnel（linebot.chenghyang.uk）
    │
    │ HTTPS → HTTP 轉發
    ▼
VPS Hostinger（187.127.109.145）
    │
    ├── line-gmail-bot.service（systemd）
    │   └── uvicorn main:app --port 8091
    │
    │ POST /line-webhook
    ▼
FastAPI 主程式（main.py）
    │
    ├── 1. 驗簽：HMAC-SHA256（LINE_CHANNEL_SECRET）
    ├── 2. 解析訊息文字
    ├── 3. 意圖偵測（INTENT_KEYWORDS）
    │
    ├── 有意圖 → Gmail API 搜尋
    │           └── subject:addwii (健康 OR 活動 OR 優惠)
    │               │
    │               ├── 讀取 Email Body
    │               ├── 有 PDF 附件 → 下載 + 提取文字（PyPDF2）
    │               └── 呼叫 Claude Haiku API 摘要
    │
    └── 無意圖 → 回覆引導訊息
    │
    ▼
LINE Messaging API push（回覆使用者）
```

---

## 四、技術堆疊

| 元件 | 技術 |
|------|------|
| Web 框架 | FastAPI + uvicorn |
| LINE 整合 | LINE Messaging API（push + webhook 驗簽） |
| Gmail 查詢 | Google Gmail API v1（OAuth 2.0 Desktop flow） |
| PDF 解析 | PyPDF2（最多 5 頁，每頁 2000 字） |
| AI 摘要 | Claude Haiku（claude-haiku-4-5-20251001，max 800 tokens） |
| 部署環境 | Hostinger VPS Ubuntu，systemd 管理服務 |
| HTTPS | Cloudflare Tunnel（linebot.chenghyang.uk → localhost:8091） |
| 驗簽 | HMAC-SHA256 + `hmac.compare_digest`（timing-safe） |

---

## 五、意圖偵測關鍵字

```python
INTENT_KEYWORDS = [
    "優惠", "活動", "健康", "addwii", "Addwii",
    "韋德",   # 語音輸入「addwii」可能被識別為「add韋德」
    "方案", "S0",  # 涵蓋 S05/S07 產品型號
    "空氣", "推薦", "小空間"
]
```

---

## 六、部署流程摘要

1. 建立 `linebot` 系統用戶（無登入 shell）
2. 安裝 Python venv + 所有套件到 `/opt/line-gmail-bot/`
3. 本機執行 `auth_gmail.py` 完成 Gmail OAuth，產生 `token.json`
4. 上傳 `credentials.json` + `token.json` 到 VPS
5. 設定 `.env`（LINE 密鑰 + Anthropic API Key）
6. 安裝並啟動 `line-gmail-bot.service`（systemd）
7. 更新 Cloudflare Tunnel config，加入 `linebot.chenghyang.uk → 8091`
8. 新增 Cloudflare DNS CNAME 記錄
9. LINE Developers Console 設定 Webhook URL

---

## 七、已知限制與後續改進

| 項目 | 現狀 | 建議改進 |
|------|------|---------|
| Gmail token 過期 | token.json 需手動更新 | 加 auto-refresh 排程 |
| 搜尋範圍 | 固定查 subject:addwii | 改為從問句萃取搜尋關鍵字 |
| 回覆長度 | Claude max 800 tokens | 根據信件長短動態調整 |
| 語音識別誤差 | 靠關鍵字清單補救 | 改用語意比對（embedding） |

---

## 八、重要檔案

| 檔案 | 說明 |
|------|------|
| `main.py` | FastAPI 主程式，webhook 路由 |
| `config.py` | 環境變數管理 + INTENT_KEYWORDS |
| `services/gmail_service.py` | Gmail API 查詢與附件下載 |
| `services/line_service.py` | LINE 驗簽 + push 訊息 |
| `services/claude_service.py` | Claude Haiku 摘要呼叫 |
| `services/pdf_parser.py` | PDF 文字提取 |
| `auth_gmail.py` | 一次性 Gmail OAuth 授權 |
| `line-gmail-bot.service` | systemd 服務定義 |
