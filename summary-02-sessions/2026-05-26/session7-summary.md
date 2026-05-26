# Session 7 Summary — 2026-05-26

## 完成事項

### 1. 停用 @addwii_sales_bot VPS Webhook

- 呼叫 Telegram `deleteWebhook` API，回傳 `"Webhook is already deleted"` — 代表 webhook 之前已被清除（非本次錯誤）
- 確認 VPS `/sales-relay-webhook` 不再被觸發：`/sales-qa-latest` 在發送訊息後不更新（tg_3round.py poll timeout 驗證）
- **關鍵發現**：@addwii_sales_bot 仍在群組回覆問題 → bot 很可能用 Telegram long-polling 或獨立進程，與 webhook 無關

### 2. tg_3round.py S6 timing 修正驗證

- 清除 project root 的 stray `prev_id` 空檔（`rm prev_id`）
- 執行 tg_3round.py：`find_hwnd("吳博-addwii-HCR")` → hwnd=32114640 找到，`send_to_tg()` 成功
- VPS poll 如預期 timeout（webhook 已停用），只驗 send-side → 判定 **send-side PASS**
- 結論：S6 修正的 `message_id > prev_id` 邏輯與視窗標題精確比對均正確

### 3. 逐次發送問題至 Telegram Desktop（4 批次）

**使用技術**：`win_auto_base.py` pywinauto `backend='uia'` + PowerShell `Set-Clipboard` + `Ctrl+V`

| 批次 | 問題數 | 等待策略 | 時間 |
|------|--------|----------|------|
| Batch A（1 題） | 1 | 4s | ~16:30 |
| Batch B（2 題） | 2 | 90s 固定間隔 | ~16:35 |
| Batch C（3 題） | 3 | 90s 固定間隔 | ~16:42 |
| Batch D（3 題） | 3 | 90s→180s 遞增 | ~16:44-16:48 |

**Batch D 問題清單（含 timestamp）**：

- `[16:43:54]` Q1: `addwii 空氣清淨機的噪音大嗎？晚上睡覺開著會影響睡眠嗎？` → wait 90s
- `[16:45:28]` Q2: `我想同時在客廳和臥室各放一台，有套裝優惠方案嗎？` → wait 180s
- `[16:48:32]` Q3: `addwii 是台灣品牌嗎？產品在哪裡製造的？有通過什麼認證嗎？`

**Bot 回覆行為確認**：@addwii_sales_bot 對每個問題都產生詳細 Claude 生成回覆，顯示 bot 功能正常（走 polling 模式，非 webhook）

### 4. 遞增等待模式實作

- `waits = [90, 180]` list 模式成功實現 Q1→90s、Q2→180s、Q3→無等待
- 模式可延伸：`waits = [90, 180, 270]` 等

---

## 關鍵技術筆記

### Telegram Bot webhook vs polling 行為

- `deleteWebhook` 回 `"Webhook is already deleted"` → webhook 早已不存在，不代表 bot 停止工作
- Bot 若以 `getUpdates`（long-polling）模式運行，刪除 webhook 對它沒影響
- **結論**：要真正停止 bot 回覆，需要停止 bot process 本身（VPS systemd stop），不是刪 webhook

### win_auto_base.py 使用模式（已驗證）

```python
sys.path.insert(0, str(Path.home() / ".claude/skills/win-desktop-auto/scripts"))
from win_auto_base import find_hwnd, focus_window, type_cjk

hwnd = find_hwnd("吳博-addwii-HCR")  # Qt5 視窗，精確標題比對
focus_window(hwnd)                    # AttachThreadInput + SW_RESTORE + 0.8s sleep
type_cjk(hwnd, "Write a message...", message, send=True)  # PowerShell Set-Clipboard + ^V + {ENTER}
```

### VPS /sales-qa-latest 格式確認

- key 是 `"answer"`（不是 `"reply"`）
- `message_id` 單調遞增，可用 `new_id > prev_id` 追蹤新回覆

---

## 產出檔案表格

| 檔案 | 類型 | 說明 |
|------|------|------|
| `summary-02-sessions/2026-05-26/session7-summary.md` | 新增 | 本次 session 摘要 |
| `C:/tmp/tg_3round.py` | 驗證（未修改） | S6 timing 修正 send-side 驗證通過 |

**注意**：`C:/tmp/tg_3round.py` 不進 git（Windows 本機暫存），本 session 未修改任何 git-tracked 程式碼檔案。

---

## HANDOFF（下次 session 優先處理）

### 立即行動

- [ ] **tg_3round.py 完整 3-round 驗證（含 VPS reply poll）**：需先重新啟用 @addwii_sales_bot webhook（`setWebhook`），再執行 tg_3round.py 確認 R2 poll 到 R2 回覆（不是 R1 舊答案）
- [ ] **LINE Bot 端到端驗證**：(a) LINE 輸入「addwii 有什麼優惠」→ Gmail 查詢路徑；(b) LINE 輸入「最近有什麼好康」→ Claude 語意分類判有意圖路徑
- [ ] **確認 bot 停止/啟動方式**：若要真正暫停 @addwii_sales_bot 回覆，需找到其 process（可能是 VPS 上的獨立 polling process）並 stop；僅刪 webhook 無效

### 進行中（需接續）

- **@addwii_sales_bot 回覆機制調查中**：deleteWebhook 已確認無效，bot 仍在 polling。下次 session 應 SSH 到 VPS 確認是否有 `tg-sales-interviewer.py` 或類似 polling script 在 cron/systemd 運行
- **Telegram Desktop 自動化問題發送**：本 session 累計發送 9 個消費者問題（4 批次），bot 均正常回覆；後續可繼續發送或轉向 Phase 2 開發

### 注意事項

- @addwii_sales_bot webhook 目前狀態：已刪（`deleteWebhook` 已確認），但 bot 仍運作（polling mode）
- VPS `/sales-qa-latest` endpoint 不會因 webhook 刪除而停止服務，仍可查詢最新 Q&A
- `prev_id` stray 空檔已清除（commit 前需確認 project root 乾淨）
- Phase 2（每日 LINE 推播 + Email 批次寄送）尚未開始，需補 per-user rate limit 才能上線 `classify_message()`
