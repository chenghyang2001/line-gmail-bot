# LINE × Gmail 智慧查信機器人

在 LINE 輸入關鍵字（如「addwii 有什麼優惠？」），系統自動搜尋 Gmail 最新活動信件，用 AI 摘要後推送回 LINE，不需要手動開信箱。

## 功能

- 關鍵字意圖偵測（優惠 / 活動 / 健康 / addwii / 方案 / 小空間…等）
- Gmail API 搜尋最新 addwii 相關信件
- 自動解析 PDF 附件（最多 5 頁）
- Claude Haiku AI 摘要（max 800 tokens）
- LINE Messaging API push 回覆

## 系統架構

```
LINE App → LINE Platform → Cloudflare Tunnel → VPS FastAPI → Gmail API
                                                           → Claude Haiku
                                                           → LINE push reply
```

詳細架構圖見 `doc/` 目錄（5 張 Mermaid PNG）。

## 技術堆疊

| 元件 | 技術 |
|---|---|
| Web 框架 | FastAPI + uvicorn |
| LINE 整合 | LINE Messaging API（Webhook + push） |
| Gmail 查詢 | Google Gmail API v1（OAuth 2.0） |
| PDF 解析 | pypdf（最多 5 頁，每頁 2000 字） |
| AI 摘要 | Claude Haiku（claude-haiku-4-5-20251001） |
| 部署 | Hostinger VPS + systemd + Cloudflare Tunnel |

## 快速開始

### 1. Clone + 安裝套件

```bash
git clone https://github.com/chenghyang2001/line-gmail-bot.git
cd line-gmail-bot
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 環境變數

```bash
cp .env.example .env
# 編輯 .env，填入真實 keys
```

需要的 key：
- `LINE_CHANNEL_SECRET` — LINE Developers Console
- `LINE_CHANNEL_ACCESS_TOKEN` — LINE Developers Console
- `LINE_USER_ID` — 接收推播的 LINE 使用者 ID
- `ANTHROPIC_API_KEY` — Anthropic Console
- `GMAIL_CREDENTIALS_PATH` — credentials.json 路徑
- `GMAIL_TOKEN_PATH` — token.json 路徑

### 3. Gmail OAuth 授權

```bash
# 將 credentials.json 放到專案目錄，然後執行：
python auth_gmail.py
# 瀏覽器登入 Google 帳號，產生 token.json
```

### 4. 切換 config 版本（本機 / VPS）

```bash
cp config-local.py config.py    # 本機開發
cp config-vps.py config.py      # 部署到 VPS
```

### 5. 執行

```bash
# 本機開發
source .env && python main.py

# 或用 uvicorn 指定 port
uvicorn main:app --host 0.0.0.0 --port 8091 --reload
```

## 目錄結構

```
line-gmail-bot/
├── main.py                  # FastAPI 主程式（webhook + health）
├── config.py                # 環境變數驗證與讀取
├── config-local.py          # 本機版備份（Path(__file__).parent 路徑）
├── config-vps.py            # VPS 版備份（/opt/line-gmail-bot/ 路徑）
├── auth_gmail.py            # 一次性 Gmail OAuth 授權
├── requirements.txt
├── .env.example             # 環境變數範本
├── line-gmail-bot.service   # systemd 服務設定（VPS 部署用）
├── services/
│   ├── gmail_service.py     # Gmail API 搜尋與附件下載
│   ├── line_service.py      # LINE 驗簽 + push 訊息
│   ├── claude_service.py    # Claude Haiku 摘要呼叫
│   └── pdf_parser.py        # PDF 文字提取
└── doc/
    ├── line-gmail-bot-design.md   # 系統架構設計文件
    ├── setup-new-machine.md       # 新電腦設定指南
    └── *.png                      # Mermaid 架構圖（5 張）
```

## 部署到 VPS

詳細步驟見 `doc/line-gmail-bot-design.md` 六、部署流程摘要。

重點：
1. 複製 `credentials.json` + `token.json` + `.env` 到 VPS `/opt/line-gmail-bot/`
2. 執行 `cp config-vps.py config.py`
3. 安裝 systemd 服務：`cp line-gmail-bot.service /etc/systemd/system/ && systemctl enable --now line-gmail-bot`
4. 更新 Cloudflare Tunnel 加入 `linebot.chenghyang.uk → localhost:8091`
5. LINE Developers Console 設定 Webhook URL：`https://linebot.chenghyang.uk/line-webhook`

## 意圖偵測關鍵字

```python
INTENT_KEYWORDS = [
    "優惠", "活動", "健康", "addwii", "Addwii",
    "韋德",    # 語音輸入「addwii」可能識別為此
    "方案", "S0",  # 涵蓋 S05/S07 產品型號
    "空氣", "推薦", "小空間"
]
```

## 注意事項

- `.env` / `credentials.json` / `token.json` 已加入 `.gitignore`，不會進 git
- LINE webhook **必須回 200**，即使驗簽失敗也不能回 4xx，否則 LINE 會停用 webhook
- Gmail token 過期會自動 refresh，不需要手動重新授權
