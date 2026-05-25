# Session 6 — win-desktop-auto Skill 建立 + tg_3round.py timing 修正

**日期**：2026-05-25  
**承接自**：Session 5（tg_3round.py 3 輪端對端驗證）

---

## 本 Session 完成項目

### 1. tg_3round.py 輪間 timing 修正

**問題根因**：`poll_reply()` 用內容字串比對（`rep != prev`）辨識新回答，
但 VPS Claude API 回覆需 5-7 秒，輪間 sleep 2 秒不夠，R2 可能 poll 到 R1 的舊答案。

**修正**：改追蹤 `message_id`（VPS 已回傳單調遞增整數）：

```python
def poll_reply(prev_id, timeout=POLL_TIMEOUT):
    deadline = time.time() + timeout
    while time.time() < deadline:
        d = fetch_qa_latest()
        new_id = d.get("message_id", 0)
        rep = d.get("answer", "")
        if rep and new_id > prev_id:
            return rep, new_id
        time.sleep(POLL_INTERVAL)
    return None, prev_id
```

同時在 `main()` 啟動時先 fetch 基準 `prev_id`，避免 poll 到殘留舊答案。

**視窗標題精確化**：從寬鬆比對 `"吳博" in t` 改為精確比對 `"吳博-addwii-HCR" in t`，
避免同一台機器上有其他含「吳博」的視窗被誤選。

### 2. Windows 桌面自動化文件化

- `~/.claude/instructions/windows-desktop-automation.md`：完整三層技術棧文件，含踩坑紀錄、偵錯技巧、可複製最小範例
- `~/.claude/CLAUDE.md`：加入 `@instructions/windows-desktop-automation.md` 引用
- `line-gmail-bot/CLAUDE.md`：加入「Telegram Desktop 自動化」章節（指向全域文件）

### 3. win-desktop-auto Skill 建立（本 session 主線）

新 skill 路徑：`~/.claude/skills/win-desktop-auto/`

| 檔案 | 內容 |
|------|------|
| `SKILL.md` | Skill 定義、觸發詞、完整使用文件 |
| `scripts/win_auto_base.py` | 可 import 共用函式庫（find_hwnd / focus_window / set_clipboard_cjk / type_cjk） |
| `scripts/win_auto_template.py` | 使用者模板腳本（改 4 個常數即可用）|
| `references/tech-stack.md` | 三層技術棧快速索引 |
| `references/app-placeholders.md` | 已知應用視窗標題 + Edit placeholder 清單 |

#### win_auto_base.py QA 結果

- V1 EXISTS: PASS
- V2 HASH: PASS（SHA256: c1eee7cb368d0b333d0f1482d541b20475709e68d9021ae6def18118a9c65894）
- V3 SYNTAX: PASS
- V4 DYNAMIC: PASS（3 個 smoke test 全通過）
- V5 LINT: PASS（ruff clean）

QA NOTES（不影響 PASS）：

- `set_clipboard_cjk()` 的 tmp_path 預設 `C:/tmp/` 非所有機器都有 → 可改 `tempfile.gettempdir()`（待優化）
- `type_cjk()` 不自動呼叫 `focus_window()`，需呼叫方自行確保前景（設計決策）

#### win_auto_template.py QA 結果

- V1~V4: PASS
- V5 LINT: 初版 FAIL（`import os` 未使用）→ 小修豁免直接 Edit 刪除 → 重驗 PASS

---

## 踩坑紀錄

| 問題 | 根因 | 解法 |
|------|------|------|
| R2 poll 到 R1 舊答案 | 2s sleep < VPS 5-7s 回覆時間，內容比對誤命中 | 改用 `message_id > prev_id` 追蹤 |
| `import os` ruff F401 | Writer 在 `__main__` 區塊加了未使用的 import | 小修豁免（≤ 3 行）直接 Edit 刪除 |

---

## 架構現況（2026-05-25 Session 6）

```
~/.claude/skills/win-desktop-auto/   ← 新增 Skill
  ├── SKILL.md
  ├── scripts/
  │   ├── win_auto_base.py           ← 共用函式庫（QA PASS）
  │   └── win_auto_template.py       ← 使用者模板（QA PASS）
  └── references/
      ├── tech-stack.md
      └── app-placeholders.md

~/.claude/instructions/windows-desktop-automation.md  ← 全域技術文件

C:/tmp/tg_3round.py                  ← timing 修正（message_id 追蹤）
```

---

## 待辦（帶入下個 Session）

- [ ] **tg_3round.py timing 修正後驗證**：重跑 3 輪，確認 R2 不再 poll 到 R1 舊答案
- [ ] **LINE Bot 端到端驗證**：（a）含關鍵字 → Gmail（b）語意意圖 → Claude 分類
- [ ] **Telegram 防重複驗證**：連發 2-3 次確認問題主題不重複
- [ ] **win_auto_base.py 改進**（QA NOTES 建議）：`tmp_path` 改用 `tempfile.gettempdir()`
- [ ] **app-placeholders.md 補充**：驗證 LINE PC、WeChat 的 placeholder（⚠️ 未驗證）
- [ ] **per-user rate limit**（Phase 2 前必補）
- [ ] **Phase 2**：每日排程 LINE 推播（10 點業務摘要）
- [ ] **Phase 2**：Email 批次寄送（Gmail SMTP，100-200 封/批）
