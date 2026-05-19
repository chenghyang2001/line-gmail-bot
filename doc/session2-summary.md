# Session 2 Summary — 2026-05-19

## 日期

2026-05-19

## 完成事項

### 1. 診斷並修復 LINE Bot「摘要服務暫時無法使用」錯誤

- 用戶在 LINE 輸入「addwii 有什麼優惠」，Bot 回應摘要服務失敗
- VPS log 顯示根本原因：`Claude API 錯誤：Error code: 529 - overloaded_error`（Claude Haiku 4.5 過載）

### 2. 第一輪修復：加入指數退避重試（commit a033c94）

- `services/claude_service.py` 加入重試機制：529 時等 1s → 2s → 4s，最多 3 次
- 部署後確認 retry log 正常顯示，但 Haiku 4.5 仍持續 529

### 3. 深度診斷：確認 Haiku 4.5 vs Sonnet 4.6 行為差異

- 直接從 VPS 測試各 model：
  - `claude-haiku-4-5-20251001` → 529 OverloadedError（持續）
  - `claude-haiku-4-5` → 529（同上）
  - `claude-sonnet-4-6` → **正常回應**
  - `claude-3-5-sonnet-20241022`, `claude-3-haiku-20240307` → 404 NotFoundError（已 EOL）
- 結論：此 API key 對 Haiku 4.5 有限制/過載，但 Sonnet 4.6 正常

### 4. 第二輪修復：加入 Haiku→Sonnet Fallback（commit e93b086）

- 重構 `claude_service.py`：
  - `_MODEL_PRIMARY = "claude-haiku-4-5-20251001"` 先試 3 次 retry
  - 全部 529 失敗 → `_MODEL_FALLBACK = "claude-sonnet-4-6"` 再試一次
  - 抽出 `_call_model()` 輔助函式，兩個 model 共用
- Writer → QA 流程（medium 複雜度，3 test case）：全數 PASS
- 部署 VPS，服務正常重啟

## 關鍵技術筆記

### Claude API Model 可用性（2026-05-19 實測）

| Model | 狀態 |
|---|---|
| `claude-haiku-4-5-20251001` | 529 OverloadedError（持續，此 API key 受限）|
| `claude-sonnet-4-6` | 正常 |
| `claude-3-5-sonnet-20241022` | 404 NotFoundError（EOL Feb 2026）|
| `claude-3-haiku-20240307` | 404 NotFoundError（EOL）|
| `claude-3-5-haiku-20241022` | 404 NotFoundError（EOL Feb 2026）|

### 529 vs 401 處理差異

- 529 Overloaded → 只在此情況 retry + fallback
- 401/400/其他 → 不 retry（浪費 quota + 等待時間）
- fallback 只在 `all_primary_529=True` 才觸發，非 529 錯誤直接失敗

### VPS 部署注意事項

- `sudo` 用戶 `claude` 沒有 `/opt/line-gmail-bot/services/` 寫入權限
- 正確流程：`scp → /tmp/` → `sudo cp` → `sudo chown linebot:linebot`

## 產出檔案

| 檔案 | 動作 | Commit |
|---|---|---|
| `services/claude_service.py` | 修改：加 retry（1s/2s/4s）+ Haiku→Sonnet fallback | a033c94, e93b086 |
| `doc/session2-summary.md` | 新增：本 session 摘要 | — |

## HANDOFF（下次 session 優先處理）

### 立即行動

- [ ] 測試 LINE Bot 是否正常回覆（Haiku fallback → Sonnet 摘要應正常顯示）
- [ ] 將 `*.stackdump` 加入 `.gitignore`（`bash.exe.stackdump` 和 `doc/bash.exe.stackdump` 一直未追蹤）
- [ ] 監控 Haiku 4.5 是否恢復可用（可在 VPS log 觀察是否出現 fallback log）

### 進行中（需接續）

- Haiku 4.5 過載問題尚未確認根本原因（API key tier 限制 vs 暫時性過載）；目前以 Sonnet fallback 繞過，功能正常但成本較高（約 4x）

### 注意事項

- VPS 上的 API key 對 `claude-haiku-4-5-20251001` 持續 529，若 Haiku 恢復可用，系統會自動回用 Haiku（無需手動操作）
- fallback 到 Sonnet 時每次 request 約貴 4x（$0.005 → $0.02）
- `claude-3-x` 系列 model 全部已 EOL，不要嘗試回退使用
