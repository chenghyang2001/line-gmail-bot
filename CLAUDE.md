# CLAUDE.md — LINE × Gmail 智慧查信機器人

## 專案概述

FastAPI + LINE Messaging API + Gmail API + Claude Haiku 的 webhook 服務。
使用者在 LINE 輸入含意圖關鍵字的訊息 → 搜尋 Gmail 最新 addwii 活動信 → Claude 摘要 → LINE push 回覆。

部署在 Hostinger VPS（187.127.109.145），由 systemd 管理，透過 Cloudflare Tunnel 對外。

---

## 目錄結構

```
line-gmail-bot/
├── main.py                  # 進入點：FastAPI app + /line-webhook + /health
├── config.py                # 環境變數 validate() + get()（不在頂層讀 env）
├── config-local.py          # 本機版備份（切換用：cp config-local.py config.py）
├── config-vps.py            # VPS 版備份（切換用：cp config-vps.py config.py）
├── auth_gmail.py            # 一次性 Gmail OAuth 授權，產生 token.json
├── requirements.txt
├── .env.example
├── line-gmail-bot.service   # systemd 服務定義（VPS 用）
├── services/
│   ├── gmail_service.py     # get_gmail_service() / search_emails() / download_attachment()
│   ├── line_service.py      # verify_signature() / extract_text_messages() / push_message()
│   ├── claude_service.py    # summarize()（呼叫 claude-haiku-4-5-20251001）
│   └── pdf_parser.py        # extract_text_from_bytes()（max 5 頁 × 2000 字）
└── doc/                     # 設計文件 + 架構圖（.md + .png）
```

---

## 技術堆疊

| 元件 | 版本 / 說明 |
|---|---|
| Python | 3.10+（union type `str \| None` 語法） |
| FastAPI | ≥ 0.110.0 |
| uvicorn | ≥ 0.29.0（standard extra） |
| anthropic | ≥ 0.25.0（VPS 已升至 0.102.0，修 httpx 相容性） |
| google-api-python-client | ≥ 2.120.0 |
| pypdf | ≥ 4.0.0 |
| LINE Messaging API | push message + webhook 驗簽 |
| Claude model | `claude-haiku-4-5-20251001`，max_tokens=800 |

---

## 執行方式

```bash
# 確保已設定環境變數
source .env                   # 或由 systemd EnvironmentFile 載入

# 本機開發
python main.py
# 或
uvicorn main:app --host 0.0.0.0 --port 8091 --reload

# VPS 服務管理
systemctl status line-gmail-bot
systemctl restart line-gmail-bot
journalctl -u line-gmail-bot -f    # 即時 log
```

---

## 重要架構決策

### 1. 驗簽失敗也回 200

LINE 規定：webhook 回 4xx → LINE 停用 webhook。驗簽失敗只記錄 IP，一律回 `{"status":"ok"}` 200。

### 2. config.py 不在頂層讀 env

`config.validate()` 在 FastAPI lifespan 啟動時才執行，避免 import 時副作用。讀取一律透過 `config.get("KEY")`。

### 3. config-local.py / config-vps.py 備份機制

路徑常數因環境不同：
- 本機：`Path(__file__).parent / "credentials.json"`
- VPS：`"/opt/line-gmail-bot/credentials.json"`

切換方式：`cp config-local.py config.py` 或 `cp config-vps.py config.py`

### 4. INTENT_KEYWORDS 含語音識別補丁

語音輸入「addwii」可能被識別為「add韋德」，因此關鍵字清單包含「韋德」作為 fallback。

### 5. anthropic SDK 版本鎖定

VPS 原裝 0.28.0 與 httpx 0.28.1 不相容（`Client.__init__() got an unexpected keyword argument 'proxies'`）。已升至 0.102.0 修正。requirements.txt 設定 `anthropic>=0.25.0`，**VPS 部署後需確認版本 ≥ 0.102.0**：

```bash
pip show anthropic | grep Version
# 若 < 0.102.0：pip install --upgrade anthropic
```

---

## 機密管理規則

| 檔案 | 說明 | 位置 |
|---|---|---|
| `.env` | API 密鑰 | 本機專案目錄 / VPS `/opt/line-gmail-bot/` |
| `credentials.json` | Google OAuth 客戶端憑證 | 同上 |
| `token.json` | Gmail OAuth 存取 token | 同上，過期自動 refresh |

三個檔案均在 `.gitignore`，**絕對不進 git**。

---

## VPS 部署資訊

- IP：187.127.109.145（Hostinger KVM）
- 服務路徑：`/opt/line-gmail-bot/`
- 服務用戶：`linebot`（無登入 shell）
- systemd unit：`line-gmail-bot.service`
- port：8091
- Cloudflare Tunnel hostname：`linebot.chenghyang.uk`
- LINE Webhook URL：`https://linebot.chenghyang.uk/line-webhook`
- SSH：`ssh -i ~/.ssh/id_ed25519 claude@187.127.109.145`

---

## 常見問題

| 症狀 | 原因 | 解法 |
|---|---|---|
| 502 Bad Gateway | 服務未啟動 | `systemctl start line-gmail-bot` |
| 摘要服務暫時無法使用 | anthropic SDK 版本過舊 | `pip install --upgrade anthropic` |
| 回覆「請輸入查詢關鍵字」 | 語音輸入關鍵字未命中 | 檢查 INTENT_KEYWORDS，補充常見誤識別詞 |
| Gmail 服務未準備好 | token.json 不存在或路徑錯誤 | 確認 GMAIL_TOKEN_PATH，或重跑 `auth_gmail.py` |
