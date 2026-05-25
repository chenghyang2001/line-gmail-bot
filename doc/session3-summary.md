# Session 3 — Telegram 潛在客戶代理 + 防重複出題

**日期**：2026-05-25  
**Commits**：`6a3a43d`（Telegram 整合）→ `f0e9539`（單題 + @prefix）→ `761a936`（防重複）

---

## 本 Session 完成項目

### 1. Telegram Bot 建立 + 整合

- 新 Bot：`@addwii_prospect_bot`（Token: `8621303721:AAGn4w…`）
- 新增 `services/telegram_service.py`（260 行）：verify_secret_token、send_message、set_webhook、extract_text_messages
- 新增 `services/session_store.py`（136 行）：QuestionSession dataclass + SessionStore（10 分鐘 idle 超時）
- `main.py` 新增 `/telegram-webhook` endpoint（FastAPI POST）
- Webhook 設定：`https://linebot.chenghyang.uk/telegram-webhook`
- 群組：吳博-addwii-HCR，chat_id = `-5186230345`

### 2. 單問題 + @addwii_sales_bot 前綴

- `n` 參數永遠強制為 1（原設計允許 1–5）
- 推送格式：`@addwii_sales_bot 問題文字`
- commit f0e9539

### 3. 防重複出題（本 session 最後任務）

- `_recent_tg_questions: list[str]`（全域，最多 10 條）
- `_start_question_session()` 每次傳 `avoid_questions = _recent_tg_questions[-5:]` 給 Claude
- `generate_consumer_questions()` 新增 `avoid_questions` 參數，注入 prompt 告知 Claude 避開相似主題
- QA：Writer PASS + QA PASS（SHA256 驗證）→ 部署 VPS → commit 761a936

---

## 踩坑紀錄

| 問題 | 原因 | 解法 |
|---|---|---|
| Bot 加入群組後 getUpdates 空白 | 預設 privacy mode（只收到 /commands） | BotFather `/setprivacy` → Disable |
| createChatInviteLink 失敗 | Bot 非群組管理員 | 用 Telegram UI 生成邀請連結 |
| createChatInviteLink 中文 name 失敗 | 不接受非 ASCII name 參數 | 移除 name 參數 |
| 兩題都是空氣清淨機相關 | Claude 每次無記憶，獨立生成 | 全域歷史清單 + avoid_questions 注入 |

---

## 架構現況（2026-05-25）

```
main.py 497 行
  ├── /line-webhook     — LINE Messaging API（三段式意圖）
  ├── /telegram-webhook — Telegram Bot API（產消費者問題）
  └── /health           — 健康檢查

services/
  ├── gmail_service.py    — Gmail 搜尋 + 附件下載
  ├── line_service.py     — LINE 驗簽 + push
  ├── claude_service.py   — summarize / classify_message / generate_consumer_questions（共用 _call_with_retry）
  ├── pdf_parser.py       — PDF 文字擷取
  ├── telegram_service.py — Telegram 驗簽 + send + webhook 設定
  └── session_store.py    — 一問一答 session 狀態（10 分鐘 TTL）
```

---

## 待辦（帶入下個 Session）

- [ ] 驗證防重複：群組連發 2-3 次「提出 1 個消費者問題」確認主題不重複
- [ ] LINE Bot 端到端：含關鍵字 / Claude 分類 雙路徑驗證
- [ ] per-user rate limit（Phase 2 前必補）
- [ ] Phase 2：每日排程報告模組（LINE 10 點推播）
- [ ] Phase 2：Email 批次寄送（Gmail SMTP，100-200 封/批）
