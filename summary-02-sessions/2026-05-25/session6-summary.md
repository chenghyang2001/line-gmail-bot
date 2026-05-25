# Session 6 Summary — 2026-05-25

## 完成事項

### 1. tg_3round.py 輪間 timing 修正（C:/tmp/tg_3round.py）

**根因**：`poll_reply()` 用內容字串比對（`rep != prev`），但 VPS Claude API 回覆需 5-7 秒，
輪間 sleep 2 秒不夠，R2 可能 poll 到 R1 的舊答案。

**修正內容**：

- `poll_reply(prev_id)` — 改追蹤 `message_id`（VPS 回傳單調遞增整數），`new_id > prev_id` 才回傳
- `main()` 啟動時先 fetch 基準 `prev_id`，避免 poll 到殘留舊答案
- `find_hwnd()` 視窗標題從寬鬆 `"吳博" in t` 改為精確 `"吳博-addwii-HCR" in t`

### 2. Windows 桌面自動化三層技術棧文件化

**新增全域文件**：`~/.claude/instructions/windows-desktop-automation.md`

- 完整三層技術棧（pywin32 / ctypes / pywinauto UIAutomation）
- 為什麼其他方案（SendInput / Playwright / AutoHotkey / OCR / EnumChildWindows）全部失敗
- CJK 中文輸入必須透過 PowerShell Set-Clipboard + Ctrl+V
- 偵錯技巧：`print_control_identifiers()`、`rectangle()`
- 完整最小範例（可直接複製）

**更新**：`~/.claude/CLAUDE.md`、`line-gmail-bot/CLAUDE.md` 均加入 `@instructions/windows-desktop-automation.md` 引用。

### 3. win-desktop-auto Skill 建立（`~/.claude/skills/win-desktop-auto/`）

| 檔案 | 大小/行數 | QA 狀態 |
|------|---------|---------|
| `SKILL.md` | 主文件，含觸發詞、使用範例 | .md 豁免 |
| `scripts/win_auto_base.py` | 251 行，共用函式庫 | ✅ QA PASS（ruff clean） |
| `scripts/win_auto_template.py` | 199 行，使用者模板 | ✅ QA PASS（小修 import os 後） |
| `references/tech-stack.md` | 技術索引 | .md 豁免 |
| `references/app-placeholders.md` | 已知應用清單 | .md 豁免 |

**win_auto_base.py** 提供 4 個公開函式：

- `find_hwnd(title_contains, visible_only=True)` — EnumWindows 掃描
- `focus_window(hwnd, restore_sleep=0.8)` — AttachThreadInput + SetForegroundWindow
- `set_clipboard_cjk(text, tmp_path)` — PowerShell Set-Clipboard
- `type_cjk(hwnd, placeholder, text, send=True, clear_first=True)` — UIAutomation Edit 操作

**win_auto_template.py** 支援 4 個常數設定 + `--debug`/`--dry-run`/`--message`/`--no-send` 參數。

**SHA256**：

- `win_auto_base.py`: `c1eee7cb368d0b333d0f1482d541b20475709e68d9021ae6def18118a9c65894`
- `win_auto_template.py`: `94deb07b57db7b3eda72b98772c9b605645957aac5f7eedd5f5d0509881f0793`（修前）

### 4. Git Commits

| Commit | 內容 |
|--------|------|
| `ee88c0e` | 更新 CLAUDE.md：新增 Telegram Desktop 自動化技術棧參考 |
| `9a64995` | 新增 Session 6：win-desktop-auto Skill 建立 + tg_3round.py timing 修正 |

## 關鍵技術筆記

### Qt5/Electron 桌面自動化鐵律

- **SendInput / PostMessage 完全無效**：Qt5 單 HWND 架構，OS 鍵盤事件無法路由到內部 widget
- **唯一方案**：`pywinauto backend='uia'`（Windows UIAutomation，為無障礙功能強制實作）
- **HWND 位置無關性**：視窗移動/縮放/最大化 HWND 不變，UIAutomation 每次 call 重算 bounding rect
- **SW_RESTORE sleep 0.8s 鐵律**：Qt5 視窗動畫未完成前 SetForegroundWindow 無效，0.3s 不夠

### Writer-QA 鐵律執行結果

- `win_auto_template.py` 初版 ruff F401（`import os` 未使用）→ 小修豁免直接 Edit → 重驗 PASS
- QA NOTES（不影響 PASS）：`set_clipboard_cjk()` tmp_path 可改 `tempfile.gettempdir()` 提高跨機相容

## 產出檔案表格

| 檔案 | 路徑 | 動作 |
|------|------|------|
| windows-desktop-automation.md | `~/.claude/instructions/` | 新增 |
| win_auto_base.py | `~/.claude/skills/win-desktop-auto/scripts/` | 新增（QA PASS） |
| win_auto_template.py | `~/.claude/skills/win-desktop-auto/scripts/` | 新增（QA PASS） |
| tech-stack.md | `~/.claude/skills/win-desktop-auto/references/` | 新增 |
| app-placeholders.md | `~/.claude/skills/win-desktop-auto/references/` | 新增 |
| SKILL.md | `~/.claude/skills/win-desktop-auto/` | 新增 |
| tg_3round.py | `C:/tmp/` | 修改（message_id tracking） |
| session6-summary.md | `doc/` | 新增（session 工作摘要） |

---

## HANDOFF（下次 session 優先處理）

### 立即行動

- [ ] **tg_3round.py timing 修正後重跑驗證**：打開 Telegram Desktop 至 吳博-addwii-HCR 群組，執行 `PYTHONUTF8=1 python C:/tmp/tg_3round.py`，確認 R2 不再 poll 到 R1 舊答案，3/3 輪正確
- [ ] **LINE Bot 端到端驗證**：（a）傳含關鍵字訊息「addwii 有什麼優惠」→ 應走 Gmail 查詢路徑；（b）傳語意相關但無關鍵字「最近有什麼好康」→ 應由 Claude 語意分類判定有意圖
- [ ] **app-placeholders.md 補充**：找到 LINE PC 並用 `win_auto_template.py --debug` 驗證 Edit placeholder（目前 ⚠️ 未驗證）

### 進行中（需接續）

- **win-desktop-auto skill**：核心完成（5 個檔案，QA PASS，系統已識別）；待改進：`set_clipboard_cjk()` 的 `tmp_path` 可改用 `tempfile.gettempdir()` 提高跨機相容性（非緊急，QA NOTES 已記錄）
- **Phase 2 開發**：每日排程 LINE 推播（10 點業務摘要）+ Email 批次寄送（Gmail SMTP，100-200 封/批）— 尚未啟動

### 注意事項

- `C:/tmp/tg_3round.py` **不在任何 git repo**，換機器需手動複製（已在 hot-cache 記錄路徑）
- win-desktop-auto skill 的 `scripts/__pycache__` 和 `.ruff_cache` 需加入 `~/.claude/.gitignore`（若 ~/.claude 有 git）
- per-user rate limit 是 Phase 2 前必補（`classify_message()` Claude 呼叫目前無速率限制）
- VPS log 監控：確認 Haiku 4.5 是否仍持續 fallback Sonnet（529 OverloadedError 是否解除）
