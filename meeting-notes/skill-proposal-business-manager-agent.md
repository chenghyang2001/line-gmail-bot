# 技能提案：業務主管 AI 代理人（Business Manager Agent）

**版本**：v0.1 草案
**日期**：2026-05-19
**依據**：2026-05-18 會議記錄 + line-gmail-bot 現有系統架構

---

## 一、背景與動機

本提案以現有 **LINE × Gmail 智慧查信機器人**為技術基礎，延伸開發「業務主管 AI 代理人」技能（Skill）。

現有系統已驗證以下核心流程：
> 使用者在 LINE 輸入意圖關鍵字 → 搜尋 Gmail 最新信件 → Claude AI 摘要 → LINE 推播回覆

此流程證明「**自然語言觸發 → 資料擷取 → AI 分析 → 通知推播**」技術路徑可行，可作為業務主管日常工作自動化的骨幹。

---

## 二、目標

建立一套 AI 代理人技能，協助業務主管處理以下日常工作：

1. **每日自動報告**：固定時間（如每天上午 10 點）自動分析業務數據並生成摘要，推播至 LINE
2. **Email 批次管理**：支援 100–200 封/批次的行銷郵件寄送，整合 Gmail SMTP 設定
3. **異常數據警示**：偵測業務數據中的異常值（如在線率低於 86%、數值超過合理上限），主動告警
4. **跨系統 Agent 協作**：支援跨電腦、跨服務的 Agent 任務委派與回報

---

## 三、現有系統流程（技術基礎）

```
使用者 LINE 訊息
      │
      ▼
LINE Webhook（FastAPI / VPS）
      │ 驗簽 + 意圖關鍵字比對
      ▼
Gmail API 搜尋信件
      │ 取最新相關信件 + PDF 附件解析
      ▼
Claude AI 摘要（Haiku 優先，Sonnet fallback）
      │ 100–200 字繁體中文摘要
      ▼
LINE Push Message 回覆使用者
```

**已驗證能力**：

- LINE Webhook 驗簽與訊息解析
- Gmail OAuth 授權與信件搜尋
- Claude API 整合（含 529 過載 retry + Haiku→Sonnet fallback）
- VPS 24/7 部署（systemd + Cloudflare Tunnel）

---

## 四、延伸技能設計（業務主管 Agent）

```
排程觸發 / LINE 指令觸發
      │
      ▼
業務主管 Agent（Skill）
      ├─ 每日報告模組：抓取業務數據 → AI 分析 → 推播 LINE
      ├─ Email 模組：讀取收件箱摘要 / 批次寄送行銷郵件
      ├─ 異常警示模組：數據超閾值時主動通知
      └─ Agent 協作模組：委派子任務給其他 Agent（跨機器）
```

---

## 五、預期成果

| 功能 | 預期效果 |
|---|---|
| 每日自動報告 | 業務主管每天 10 點在 LINE 收到前一日業務摘要，無需手動查詢 |
| Email 批次寄送 | 一鍵觸發 100–200 封行銷郵件，取代手動逐封寄送 |
| 異常數據警示 | 數據異常（如在線率 < 86%）時即時 LINE 通知，縮短反應時間 |
| AI 決策輔助 | 數據背後的「原因點」由 AI 分析呈現，主管只需審核與簽核 |

---

## 六、開發優先順序

1. **Phase 1（已完成）**：LINE + Gmail + Claude 核心串接
2. **Phase 2（下一步）**：每日排程報告 + Email 批次寄送模組
3. **Phase 3（後續）**：異常警示 + 跨 Agent 協作架構

---

## 七、技術注意事項

- Claude API：`claude-haiku-4-5-20251001` 對現有 API key 有 529 限制，已設 Sonnet fallback
- Gmail SMTP：需另外在 Google 帳號開通「低安全性應用程式存取」或 App Password
- VPS 部署：檔案複製需透過 `/tmp/` 中轉再 `sudo cp`（直接 scp 至 `/opt/` 無權限）
