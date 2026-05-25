# Session 4 — @addwii_sales_bot 雙 token 自主架構 + tg-sales-interviewer 重寫

**日期**：2026-05-25  
**Commits**：`a81f06a`（VPS 部署）→ `58078c5`（重寫 tg-sales-interviewer.py）

---

## 本 Session 完成項目

### 1. 啟用 @addwii_sales_bot 作為真實 webhook bot

- 使用同事提供的 token（`8957497395:AAFrTZKnwQs6QyPo8fCUrz8IShTM02lBi2s`）
- 設定 webhook → `https://linebot.chenghyang.uk/sales-relay-webhook`
- 此端點供**真人用戶**觸發使用（真人在群組 tag `@addwii_sales_bot` → Claude 回覆）

### 2. VPS 新增兩個 endpoint（main.py）

- **`/sales-relay-webhook`** (POST)：接收 Telegram 訊息 → Claude 生成業務回覆 → 以 `@addwii_sales_bot` 發到群組 → 儲存 Q&A
  - 安全性：`ADDWII_SALES_SECRET_TOKEN` 驗簽（可選）
  - `is_bot` 過濾防止 bot loop
  - 精確 regex `@addwii_sales_bot\b` 避免誤刪 email
  - 空回覆守門員
- **`/sales-qa-latest`** (GET)：回傳最近一筆 Q&A（供外部輪詢）
  - `SALES_POLL_TOKEN` header 驗簽（可選）

### 3. claude_service.py 新增業務回覆函式

- `_SYSTEM_SALES_REPLY`：業務助理 system prompt（S05/S10 規格+折扣）
- `generate_sales_reply(api_key, question)`：呼叫 Claude Haiku，API 失敗回預設道歉訊息

### 4. tg-sales-interviewer.py 重寫（核心突破）

**問題根因**：Telegram 硬性封鎖 bot-to-bot 訊息，`@addwii_prospect_bot` 發的訊息永遠不會觸發 `@addwii_sales_bot` 的 webhook，無論 privacy mode 設定。

**舊架構**（失敗）：

```
腳本發問 → VPS webhook（永遠不觸發）→ 輪詢 /sales-qa-latest（逾時 90s）
```

**新架構**（成功）：

```
腳本發問（@addwii_prospect_bot） → Claude 本機生成回覆 → 腳本發回覆（@addwii_sales_bot）
```

變更摘要：

- 移除：`SALES_QA_ENDPOINT`, `SALES_POLL_TOKEN`, `_poll_sales_endpoint()`
- 新增：`_SYSTEM_SALES_REPLY`, `_generate_sales_reply()`, `ADDWII_SALES_BOT_TOKEN` env
- 保留：`_generate_followup()`, `_send_tg_message()`, Markdown 輸出機制

### 5. 端到端驗證（3 輪，~4 秒/輪）

```
第 1 輪：「addwii 有什麼優惠」→ 詳細折扣方案說明
第 2 輪：Claude 生成「我家客廳約20坪，S10 的淨化速度和噪音表現如何？」→ 詳細規格
第 3 輪：Claude 生成「家裡長期開空調，還是經常開窗通風呢？」→ 環境建議
```

---

## 踩坑紀錄

| 問題 | 原因 | 解法 |
|---|---|---|
| `_poll_sales_endpoint()` 持續 HTTP 403 | Cloudflare Bot Fight Mode 封鎖 Python urllib 無 User-Agent | 加 `User-Agent: tg-sales-interviewer/1.0` header |
| `/sales-relay-webhook` 從未被觸發 | Telegram bot-to-bot 訊息封鎖（API 層級，無法繞過） | 改為腳本自主架構，不依賴 webhook 中轉 |
| Code reviewer MUST_FIX（上個 session） | regex `@\w+` 誤刪 email | 改 `@addwii_sales_bot\b` |
| Code reviewer MUST_FIX | 無 webhook 驗簽 | 加 `ADDWII_SALES_SECRET_TOKEN` 可選驗簽 |

---

## 架構現況（2026-05-25 Session 4）

```
main.py 621 行
  ├── /line-webhook        — LINE Messaging API（三段式意圖）
  ├── /telegram-webhook    — Telegram @addwii_prospect_bot（產消費者問題）
  ├── /sales-relay-webhook — Telegram @addwii_sales_bot（真人觸發版）
  ├── /sales-qa-latest     — 最新 Q&A 查詢端點
  └── /health              — 健康檢查

tg-sales-interviewer.py    — 自動化測試腳本（兩 bot token 自主）
  ├── @addwii_prospect_bot 發消費者問題
  ├── Claude 本機生成業務回覆
  ├── @addwii_sales_bot 發業務回覆
  └── 輸出 doc/tg-interview-*.md
```

---

## 待辦（帶入下個 Session）

- [ ] **LINE Bot 端到端驗證**：（a）含關鍵字「addwii 有什麼優惠」→ Gmail 查詢（b）語意相關「最近有什麼好康」→ Claude 分類有意圖
- [ ] **Haiku 4.5 監控**：VPS log 是否仍持續 fallback 到 Sonnet
- [ ] **per-user rate limit**（Phase 2 前必補）
- [ ] **Phase 2**：每日排程 LINE 推播（10 點業務摘要）
- [ ] **Phase 2**：Email 批次寄送（Gmail SMTP，100-200 封/批）
- [ ] **Telegram 防重複驗證**：連發 2-3 次「提出 1 個消費者問題」確認主題不重複
