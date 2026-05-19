# Session 3 Summary — 2026-05-19

## 日期

2026-05-19

## 完成事項

### 1. 音訊轉錄：2026-05-18 會議記錄

- 音檔：`標準錄音 5.mp3`（21MB，約 9 分鐘，口語中文）
- 工具：`faster_whisper` base model（`language="zh"`, `beam_size=5`）
- 轉錄後整理 10 項討論主題，含重要決策（AI 一人公司架構、每日報告排程、Email 批次寄送、跨機器 Agent 協作）
- 注意：部分詞彙由 Whisper 推測（「靠地靠」= Claude Code、「RT2」= RD2、「SNTP」= SMTP），已在文件加注說明

### 2. 建立 meeting-notes 資料夾並移至專案

- 建立 `C:\Users\B00332\workspace\line-gmail-bot\meeting-notes\` 資料夾
- 產出 `meeting_note_20260518.md`（10 項編號會議記錄）
- 文件位置：`meeting-notes/meeting_note_20260518.md`

### 3. 業務主管 AI 代理人技能提案文件

- 以 LINE × Gmail Bot 現有驗證流程為技術基礎
- 產出 `meeting-notes/skill-proposal-business-manager-agent.md`（7 節完整提案）
- 提案涵蓋：每日自動報告、Email 批次寄送（100-200 封/批）、異常數據警示（在線率 < 86%）、跨 Agent 協作架構
- Phase 開發路線圖：Phase 1（已完成）→ Phase 2（每日排程 + Email 批次）→ Phase 3（警示 + 協作）

### 4. .gitignore 補充 + 統一 commit

- 補充 `.gitignore`：新增 `*.stackdump` 排除 Windows crash dump（bash.exe.stackdump）
- Commit 657a9a3：三個檔案一次入庫（`.gitignore` / `meeting_note_20260518.md` / `skill-proposal-business-manager-agent.md`）
- Push 至 `origin/master` 完成

## 關鍵技術筆記

### faster_whisper 本地轉錄（口語中文）

- Base model 對口語中文覆蓋度夠，無需 large model
- 慣用參數：`language="zh"`, `beam_size=5`, `vad_filter=True`（可選）
- 轉錄結果有語義漂移，需人工核對專有名詞（Claude Code、SMTP、RD2 等）

### .gitignore 累積規則

```
*.stackdump        ← Windows Playwright/mmdc crash dump
.env               ← API 密鑰
credentials.json   ← Google OAuth 客戶端憑證
token.json         ← Gmail OAuth token
```

### 業務主管 Agent 技能設計原則

- 以現有「LINE → Webhook → Gmail → Claude → LINE reply」為骨幹，不重新發明輪子
- 新增模組用「夾層」方式插入，不破壞現有 webhook 結構
- 異常警示閾值：在線率 86%、感測器數值 389（超上限）

## 產出檔案

| 檔案 | 動作 | Commit |
|---|---|---|
| `meeting-notes/meeting_note_20260518.md` | 新增：音訊轉錄會議記錄（10 項） | 657a9a3 |
| `meeting-notes/skill-proposal-business-manager-agent.md` | 新增：業務主管 AI Agent 技能提案（7 節） | 657a9a3 |
| `.gitignore` | 修改：補充 `*.stackdump` | 657a9a3 |

## HANDOFF（下次 session 優先處理）

### 立即行動

- [ ] 測試 LINE Bot 是否正常回覆（發送含 addwii 關鍵字的訊息，確認 Haiku fallback → Sonnet 摘要正常推播）
- [ ] Phase 2 開發啟動：每日排程報告模組（固定 10 點推播業務摘要到 LINE）
- [ ] Email 批次寄送模組規格設計（Gmail SMTP App Password + 100-200 封/批）

### 進行中（需接續）

- 業務主管 AI Agent 技能提案已完成（`meeting-notes/skill-proposal-business-manager-agent.md`），Phase 2 實作尚未開始
- Haiku 4.5 over 529 狀態持續：VPS 上 `claude-haiku-4-5-20251001` 對此 API key 持續 529，系統以 Sonnet fallback 正常運作（成本約 4x）；Haiku 恢復後會自動回用

### 注意事項

- VPS 部署流程：`scp → /tmp/` → `sudo cp` → `sudo chown linebot:linebot`（直接 scp 到 `/opt/` 無權限）
- `claude-3-x` 系列全部 404 EOL（Feb 2026），不可嘗試
- 業務數據閾值出自 2026-05-18 會議：在線率基準 86%、感測器最大值 60、異常值 389
- 跨機器 Agent 協作（Phase 3）架構尚在研究中，目前「還沒架起來」
