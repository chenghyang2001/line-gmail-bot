# 摘要：私人 LINE AI 自動回覆代理人（計畫書）

> 來源檔案：`private_line_desktop_agent_plan.docx`（535 段、約 12,800 字）
> 摘要產生日期：2026-05-21

## 文件定位

- **標題**：私人 LINE AI 自動回覆代理人
- **副標**：`chat.txt 記憶庫 + LINE Desktop OCR + Ollama + pyautogui 可執行方案`

這是一份要交給 Claude Code 執行的**完整建置規格書**——含 11 個章節、專案結構、9 段核心程式碼、安裝步驟。目標是做一個桌面自動化代理人，**自動回覆「個人」LINE 訊息**。

## 核心構想

個人 LINE 沒有官方 webhook / Messaging API（那是 Official Account 才有的）。所以這份計畫繞過 API，改走**桌面自動化**路線：

```
截圖 LINE Desktop 聊天區 → OCR 辨識最新訊息 → 本機 LLM 產生回覆
→ 安全閘門檢查 → pyautogui 模擬鍵鼠貼上+Enter 送出
```

與 line-gmail-bot 的對比：line-gmail-bot 走官方 Messaging API + webhook（合法、穩定、有簽章驗證）；這份計畫因為「個人帳號沒 API」而改用 OCR + 模擬點擊——本質是「機器人假裝成人在操作 LINE 桌面程式」。

**記憶庫設計**：`chat.txt`（LINE 匯出的歷史對話）→ 解析成 `messages.jsonl` → 建 `style_profile.json`（模仿本人語氣）+ ChromaDB 向量庫（檢索相關歷史片段）。回覆時把「對方訊息 + 檢索到的歷史 + 語氣檔」一起餵給 LLM。

## 技術堆疊（全本機、零雲端）

| 元件 | 用途 |
|---|---|
| `pyautogui` + `pyperclip` | 截圖、模擬點擊、貼上、按 Enter |
| `pytesseract` (OCR) | 辨識畫面文字（`chi_tra+eng`）|
| Ollama + `qwen2.5:7b`（低規格用 3b）| 本機 LLM 產生回覆 |
| ChromaDB | 本機向量記憶庫 |
| `pydantic` / `orjson` / `python-dotenv` | 設定、序列化 |

全部跑在本機，不呼叫外部 API、不扣費。

## 安全設計（`safety_guard.py`）

這是文件最強調的部分：

- **高風險關鍵字黑名單**：錢、借錢、轉帳、密碼、驗證碼、身分證、合約、法律、醫療、分手、自殺等 → 命中就**不送出**，只寫 `blocked log`。
- **禁止回覆語句**：「我保證」「我答應」「我借你」等承諾性字眼。
- **`DRY_RUN` 模式**：預設只產生+記錄、不真的送出，校準測試通過才開 `AUTO_SEND`。
- 回覆字數上限 80 字。

## 硬性限制（文件自己劃的紅線）

不破解 LINE、不讀加密資料庫、不攔截封包、不登入他人帳號、不用 Official Account / Messaging API、`chat.txt` 只當記憶來源。

## 評估——三個值得留意的點

文件技術上可執行，但有幾個它**沒有充分處理**的風險：

1. **對方不知情**。Prompt 明寫「不要提到 AI」「不要提到讀過歷史對話」——意思是讓對方以為在跟真人聊天。這是**欺騙性互動**，跟「不破解 LINE」的自律紅線比起來，這條反而沒被當成問題。對方有沒有同意被 AI 代答，是比技術更該先想的事。

2. **ToS 風險**。雖然「不碰 API、不破解」，但用程式自動操作 LINE 桌面客戶端、自動代發訊息，通常仍違反 LINE 使用條款（自動化客戶端行為），帳號有被停權風險。文件把「合法性」窄化成「沒破解」，但 ToS 不只看破解。

3. **可靠性脆弱**。OCR + 固定螢幕座標的方案，只要 LINE 視窗移動、被遮、螢幕縮放改變、解析度不同，就會點錯地方、讀錯訊息——甚至可能把回覆貼到錯的聊天室。`calibrate.py` 校準工具有幫助，但這類方案本質不穩。
