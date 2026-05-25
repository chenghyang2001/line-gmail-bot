# Session 5 — tg_3round.py 3 輪端對端驗證（pywinauto + VPS webhook）

**日期**：2026-05-25  
**目標**：用 tg_3round.py 自動化 Telegram Desktop，以真人身份發送訊息觸發 VPS `/sales-relay-webhook`，完成 3 輪業務問答迴圈

---

## 本 Session 完成項目

### 1. 核心突破：pywinauto UIAutomation backend

**問題根因**：Qt5 single-HWND rendering — `Qt51518QWindowIcon` 類別的 Telegram 視窗，所有 widget 由 GPU 繪製在單一 HWND 內，OS 層的鍵盤/滑鼠事件（SendInput、PostMessage）無法路由到邏輯輸入框。

**失敗的方案（全部嘗試過）**：

- `SendInput + KEYEVENTF_UNICODE`
- `win32api.SetCursorPos() + mouse_event(MOUSEEVENTF_LEFTDOWN)`
- `MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK`
- `PostMessage(hwnd, WM_LBUTTONDOWN, ...)`
- `EnumChildWindows`（Qt5 無 child HWND，回傳 0）

**成功方案**：pywinauto `backend='uia'` 透過 Windows Accessibility Tree 找到 Edit element：

```python
app = Application(backend='uia').connect(handle=hwnd)
win = app.window(handle=hwnd)
# Telegram 有兩個 'Write a message...' Edit element，取 found_index=0
edit = win.child_window(title='Write a message...', control_type='Edit', found_index=0)
edit.click_input()               # 觸發 Qt 內部 focus routing
edit.type_keys('^a{DEL}', pause=0.05)  # 清除
# CJK 文字用 PowerShell Set-Clipboard + Ctrl+V 貼入
edit.type_keys('^v', pause=0.05)
edit.type_keys('{ENTER}')
```

### 2. tg_3round.py 重寫（`C:/tmp/tg_3round.py`）

| 改動 | 說明 |
|------|------|
| 移除 | `KEYBDINPUT`, `_KU`, `KINPUT`, `KEYUP` 常數, `_sk()` 函式 |
| 新增 | `from pywinauto import Application` |
| 重寫 | `send_to_tg()` — 改用 pywinauto UIAutomation |
| 修復 | `poll_reply()` — `d.get("reply","")` → `d.get("answer","")` |

### 3. VPS `/sales-qa-latest` 回傳格式確認

```json
{
  "question": "...",
  "answer": "...",       ← 不是 "reply"
  "answered_at": "...",
  "message_id": 121
}
```

舊版 `poll_reply()` 讀 `d.get("reply","")` 永遠拿到空字串，導致 45 秒 timeout。
修正後改讀 `d.get("answer","")` 即可。

### 4. 3-Round 端對端驗證成功

```
Round 1: 我家客廳大約 25 坪，想買空氣清淨機，addwii 有什麼推薦型號？
         → VPS 回覆：推薦 S10（≤30坪，85折 NT$10,880）
         
Round 2: [Claude Haiku 生成] 請問S10濾網需要多久更換一次？費用大約多少？
         → VPS 回覆（timing 問題，見下）

Round 3: [Claude Haiku 生成] 請問濾網多久更換一次？更換成本大約是多少？
         → VPS 回覆：6-12個月更換，加購 9 折優惠
```

---

## 踩坑紀錄

| 問題 | 根因 | 解法 |
|------|------|------|
| SendInput 完全無效 | Qt5 single-HWND，無 child HWND | 改用 pywinauto UIAutomation backend |
| ElementAmbiguousError | Telegram 有 2 個同名 Edit element | `found_index=0` |
| SW_RESTORE 後 focus=False | 動畫未完成就呼叫 SetForegroundWindow | sleep 從 0.3s 改 0.8s |
| poll_reply 永遠 timeout | 讀 `"reply"` key 但 VPS 回傳 `"answer"` | 改讀 `"answer"` |
| R2 收到 R1 舊答案 | VPS Claude API 約 5-7 秒，2s sleep 不夠 | 待修：改用 message_id 或 answered_at 追蹤 |

---

## 已知問題（待修）

### 輪間 timing 問題

`prev` 只比對內容，無法區分「舊答案」與「新答案」。VPS Claude API 回覆需 5-7 秒，
而輪間只 sleep 2 秒，造成 R2 poll 到的可能是 R1 的舊答案。

**建議修法**：改追蹤 `message_id`（VPS 已回傳），下一輪 poll 等 `message_id > prev_id`。

```python
# 改進版 poll_reply
def poll_reply(prev_id, timeout=POLL_TIMEOUT):
    deadline = time.time() + timeout
    while time.time() < deadline:
        d = fetch_qa_latest()
        if d.get("message_id", 0) > prev_id:
            return d.get("answer",""), d["message_id"]
        time.sleep(POLL_INTERVAL)
    return None, prev_id
```

---

## 架構現況（2026-05-25 Session 5）

```
tg_3round.py（C:/tmp/）— Windows Telegram Desktop 自動化測試
  ├── pywinauto UIAutomation → Qt5 Edit widget
  ├── PowerShell Set-Clipboard → CJK 貼入
  ├── VPS /sales-relay-webhook → Claude 生成業務回覆
  └── VPS /sales-qa-latest (answer key) → 輪詢回覆
```

---

## 待辦（帶入下個 Session）

- [ ] **tg_3round.py 輪間 timing 修正**：改用 `message_id` 追蹤，避免 poll 到舊答案
- [ ] **LINE Bot 端到端驗證**：（a）含關鍵字 → Gmail（b）語意意圖 → Claude 分類
- [ ] **Telegram 防重複驗證**：連發 2-3 次確認問題主題不重複
- [ ] **per-user rate limit**（Phase 2 前必補）
- [ ] **Phase 2**：每日排程 LINE 推播（10 點業務摘要）
- [ ] **Phase 2**：Email 批次寄送（Gmail SMTP，100-200 封/批）
