# Session 4 — 意圖未命中改走 Claude 語意分類 + VPS 部署

**日期**：2026-05-21
**專案**：line-gmail-bot（LINE × Gmail 智慧查信機器人）

---

## 完成事項

### 功能開發：意圖未命中改走 Claude 語意分類

- **需求**：原本使用者訊息沒命中 `INTENT_KEYWORDS` 子字串比對時，bot 推固定罐頭訊息。改為呼叫 Claude 做語意意圖判斷。
- **方向確認**（AskUserQuestion）：使用者選「智慧意圖判斷」（Claude 語意判斷是否想查 addwii 活動信）+「空/極短先擋掉」（守門員省 token）。
- **新流程（三段式）**：① `_is_meaningful_input()` 長度守門員（空/單字元/純標點 → 推固定提示，不呼叫 Claude）② 子字串快速比對命中 → 直接查 Gmail（零額外 API 成本）③ 沒命中 → `classify_message()` 用 Claude 判斷意圖。
- **`claude_service.py` 重構**：抽出共用 `_call_with_retry()`（Haiku→Sonnet retry/fallback），`summarize()` 與新 `classify_message()` 共用；`_call_model()` 新增 `system` 參數；新增 `_parse_classify_result()`（解析 Claude JSON、容錯 markdown 圍欄、失敗降級安全網）。
- **`main.py` 改寫**：新增 `_is_meaningful_input()`、webhook 迴圈改三段式、刪除改動前就存在的 dead `import os`。
- **CLAUDE.md**：新增「架構決策 6：意圖未命中改走 Claude 語意分類」。

### 三 agent 鐵律全程

- writer → QA → reviewer sequential，全程跑完。
- QA 抓到 1 個 FAIL：`main.py` 未使用的 `import os`（F401）→ 修掉。
- Reviewer 抓到 1 個 MUST_FIX：webhook 事件迴圈未包 try/except，`gmail_search_and_reply` 內非 `RuntimeError` 例外（如 PDF 附件 `att["name"]` 的 `KeyError`）會穿透導致回 500 → 違反「LINE webhook 必須回 200」鐵律。修法：每則 text 各自包 `try/except Exception`。
- 追加修 2 個 NICE_TO_HAVE：#1 新增 `_coerce_bool()` 修 Claude 回字串 `"false"` 被 `bool()` 誤判成 `True` 的分類錯誤；#2 `_call_model()` 空回應改 `raise RuntimeError`，不再回傳開發用字串。

### VPS 部署

- 部署 `main.py` + `claude_service.py` 到 VPS 187.127.109.145（`/opt/line-gmail-bot/`）。
- 流程：scp → /tmp → sudo cp → chown linebot:linebot，每段比對 SHA256。
- 備份：`/tmp/lgb-backup-20260521-023552`（本 session 內可回滾）。
- 重啟服務 `active`、`Application startup complete`、health 端點 `{"status":"ok"}`。
- anthropic SDK 0.102.0（≥ 0.102.0，無需升級）。

### kerwin 文件處理

- 從 `kerwin/private_line_desktop_agent_plan.docx`（535 段、約 12,800 字）擷取文字並摘要。
- 該文件是「私人 LINE AI 自動回覆代理人」計畫書：OCR LINE Desktop 畫面 + Ollama 本機 LLM + pyautogui 模擬鍵鼠送出。
- 摘要存成 `kerwin/private_line_desktop_agent_plan_summary.md`，附三點風險評估（對方不知情/ToS/OCR 脆弱）。
- 把整個 `kerwin/` 目錄（4 檔，含 1.6MB .pptx）一起 commit。

---

## 關鍵技術筆記

- **`_call_with_retry` 設計原則**：抽出共用 retry 後，最終失敗一律 `raise RuntimeError`，由呼叫端決定 user-facing 訊息（`summarize` 回「摘要服務暫時無法使用」、`classify_message` 回安全網）。不在共用層回固定字串。
- **LINE webhook 回 200 鐵律**：webhook 任何分支都必須回 200，否則 LINE 會重試並停用 webhook。新增 Claude 呼叫讓迴圈更複雜，反而暴露原本就裸露的迴圈韌性缺口。
- **sub-agent 崩潰處理**：本 session 有 2 個 code-writer subagent 在輸出最終 Manifest 時 tool call parse error，但檔案編輯已完成。處理方式：不重派 writer（避免重複套 edit），改由主 Claude 讀檔驗證 + 代構 Manifest 交給獨立 QA 驗 SHA256。驗證了「QA 必須獨立」鐵律的價值。
- **`bool("false")` 陷阱**：Python 非空字串皆 truthy，`bool("false")` 是 `True`。容錯解析函式必須對字串明確比對白名單。
- **docx 文字擷取**：docx 是 zip + XML，用 `zipfile` + `ElementTree` 解 `word/document.xml` 的 `w:t`/`w:p` 即可，不需 python-docx。

---

## 產出檔案

| 檔案 | 變更 | 備註 |
|---|---|---|
| `main.py` | 修改 | 三段式 webhook、`_is_meaningful_input`；VPS 已部署 |
| `services/claude_service.py` | 修改 | `_call_with_retry` 重構、`classify_message`、`_coerce_bool`；VPS 已部署 |
| `CLAUDE.md` | 修改 | 新增架構決策 6 + 常見問題更新 |
| `kerwin/`（4 檔） | 新增 | LINE OA 簡報、聊天記錄說明、私人 LINE 代理人計畫書 + 摘要 |
| `summary-02-sessions/2026-05-21/session4-summary.md` | 新增 | 本檔 |

**commit**：`3739fd2`（意圖分類功能）、`7f0e180`（kerwin 文件）

---

## HANDOFF（下次 session 優先處理）

### 立即行動

- [ ] **LINE Bot 功能端到端驗證**：在 LINE 發送兩種訊息確認新功能 —（a）含關鍵字「addwii 有什麼優惠」應走 Gmail 查詢（b）不含關鍵字但語意相關「最近有什麼好康」應由 Claude 判定有意圖。
- [ ] **觀察 VPS log**：`sudo journalctl -u line-gmail-bot -f` 看 Claude 呼叫是否一直 fallback 到 Sonnet（Haiku 529 監控）。
- [ ] **回覆 kerwin docx 計畫**：若需給對方回饋，建議補「告知對方是 AI 代答」+ 評估 LINE ToS 風險。

### 進行中（需接續）

- Phase 2 開發（MEMORY.md 既有 HANDOFF）：每日排程報告模組（固定 10 點推播業務摘要）、Email 批次寄送模組（Gmail SMTP App Password，100-200 封/批）。
- `doc/setup-new-machine.md` VPS 部署細節較舊，需補最新步驟。

### 注意事項

- **第三段 Claude 呼叫無 per-user rate limit**：目前單一固定使用者風險可接受，但 Phase 2 開放多使用者前必須補速率限制（reviewer 架構觀察）。
- **prompt injection 面**：使用者可操控 `classify_message` 的 `reply` 內容，但 bot 只推給固定 `line_user_id`、不群發，實務風險低。
- **VPS 回滾點**：`/tmp/lgb-backup-20260521-023552`（重開機後消失，只在本 session 後短期有效）。
- 未修的 NICE_TO_HAVE（broad except log 加類型名、client 複用、emoji-only 輸入）留作參考，非阻斷。
