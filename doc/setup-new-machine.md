# 新電腦設定指南

## git clone 之後差什麼

### ✅ Repo 裡已有（clone 就有）

| 檔案 | 說明 |
|---|---|
| `main.py` | FastAPI 主程式 |
| `config.py` / `config-local.py` / `config-vps.py` | 設定檔（local / VPS 兩種備份） |
| `services/*.py` | Gmail / LINE / Claude / PDF 服務 |
| `auth_gmail.py` | Gmail OAuth 授權腳本 |
| `requirements.txt` | Python 套件清單 |
| `.env.example` | 環境變數範本 |
| `line-gmail-bot.service` | systemd 服務設定（部署到 VPS 才用） |

---

### ❌ 不在 Repo（新電腦需要補的 3 樣東西）

#### 1. `.env`（API 密鑰）

複製現有的，或照 `.env.example` 填入真實值：

```
LINE_CHANNEL_SECRET=...
LINE_CHANNEL_ACCESS_TOKEN=...
LINE_USER_ID=...
ANTHROPIC_API_KEY=...
GMAIL_CREDENTIALS_PATH=./credentials.json
GMAIL_TOKEN_PATH=./token.json
```

> 本機用相對路徑 `./credentials.json`；VPS 用 `/opt/line-gmail-bot/credentials.json`

#### 2. `credentials.json`（Google Cloud OAuth 客戶端憑證）

從 Google Cloud Console 下載，或直接從現有機器複製：

```
現在這台：C:\Users\user\workspace\line-gmail-bot\credentials.json
              ↓ 複製到新電腦同目錄
新電腦：   <專案目錄>\credentials.json
```

這是固定的客戶端設定檔，不會過期，複製一次即可。

#### 3. `token.json`（Gmail OAuth 存取 Token）

| 方式 | 說明 |
|---|---|
| **直接複製** | 把現有 `token.json` 貼過去，有效期內直接用，過期會自動 refresh |
| **重新授權** | 執行 `python auth_gmail.py`，瀏覽器登入 Google 帳號，重新生成 |

---

## 完整設定流程

```bash
# 1. Clone
git clone https://github.com/chenghyang2001/line-gmail-bot.git
cd line-gmail-bot

# 2. 建虛擬環境 + 安裝套件
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 3. 建 .env
cp .env.example .env
# 編輯 .env，填入真實 keys（或直接從舊機器複製 .env）

# 4. 放入 credentials.json（從舊機器複製）

# 5a. 快速方式：複製 token.json（從舊機器複製）

# 5b. 乾淨方式：重新 Gmail 授權
python auth_gmail.py             # 瀏覽器跑 OAuth，產生 token.json

# 6. 切換成 local 版 config
cp config-local.py config.py

# 7. 試跑
python main.py
```

---

## 切換環境（local ↔ VPS）

```bash
# 切到本機模式
cp config-local.py config.py

# 切到 VPS 模式（部署 VPS 時用）
cp config-vps.py config.py
```

---

## 快速遷移小結

最快的辦法：從舊機器複製下列 3 個檔案到新電腦的專案目錄，其他全靠 git clone 搞定。

| 檔案 | 來源 |
|---|---|
| `.env` | 直接複製現有的 |
| `credentials.json` | 直接複製（或從 Google Cloud Console 重新下載） |
| `token.json` | 直接複製（或重跑 `auth_gmail.py` 重新授權） |
