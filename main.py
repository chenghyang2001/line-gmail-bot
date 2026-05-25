"""main.py — LINE × Telegram Webhook FastAPI server，接收訊息後查 Gmail 並推摘要"""
import json
import re
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncGenerator

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

import config
from services.claude_service import classify_message, generate_consumer_questions, summarize
from services.gmail_service import download_attachment, get_gmail_service, search_emails
from services.line_service import (
    extract_text_messages,
    push_message,
    verify_signature,
)
from services.pdf_parser import extract_text_from_bytes
from services.telegram_service import (
    extract_text_messages as tg_extract_messages,
    send_message as tg_send_message,
    verify_secret_token as tg_verify_secret,
)
from services.session_store import store as session_store

if TYPE_CHECKING:
    from services.session_store import QuestionSession

# 過短/純標點輸入時的固定提示，這類輸入不值得呼叫 Claude（省 token）
_SHORT_INPUT_HINT: str = "請輸入想查詢的內容，例：addwii 有什麼優惠？"

# Telegram 最近問過的消費者問題（全群組共用，最多保留 10 條）
_recent_tg_questions: list[str] = []


def _is_meaningful_input(text: str) -> bool:
    """判斷輸入是否有意義（非空、非極短、非純標點）。

    過短或純標點符號的輸入不值得呼叫 Claude，先擋下省 token。
    """
    stripped = text.strip()
    # 空字串或單字元，沒有判斷意圖的價值
    if len(stripped) < 2:
        return False
    # 不含任何文字/數字字元 → 純標點/符號
    # 註：str.isalnum() 對中日韓文字也回 True，故中文輸入不會被誤擋
    if not any(ch.isalnum() for ch in stripped):
        return False
    return True


def _is_generate_question(text: str) -> bool:
    """判斷訊息是否為「產生消費者問題」指令。

    觸發條件（三個條件全部成立才回 True）：
    1. 訊息包含「提出」或「產生」（動作詞）
    2. 訊息包含「問題」（目標詞）
    3. 訊息包含「addwii」或「消費者」或「使用者」（對象詞）

    範例可觸發：「幫我產生 3 個消費者問題」、「提出 addwii 使用者會問的問題」
    範例不觸發：「addwii 有什麼優惠」（無動作詞）、「產生報告」（無問題/對象詞）
    """
    normalized = text.strip().lower()
    has_action = "提出" in normalized or "產生" in normalized or "生成" in normalized or "列出" in normalized
    has_target = "問題" in normalized
    has_subject = "addwii" in normalized or "消費者" in normalized or "使用者" in normalized
    return has_action and has_target and has_subject


# 中文數字 1-5 對應阿拉伯數字，用於 _extract_count 解析口語輸入
_ZH_NUM: dict[str, int] = {"一": 1, "兩": 2, "二": 2, "三": 3, "四": 4, "五": 5}


def _extract_count(text: str) -> int:
    """從訊息中抽出數量，預設 1，上限 5。

    解析優先序：
    1. 阿拉伯數字（正規表達式抓第一個數字）
    2. 中文數字（只處理 一/兩/二/三/四/五）
    找不到數字 → 回傳 1；找到的數字超過 5 → clamp 到 5。

    範例：
    - 「產生 3 個消費者問題」 → 3
    - 「提出兩個問題」 → 2
    - 「產生消費者問題」 → 1（無數字，預設值）
    - 「產生 10 個問題」 → 5（超出上限，clamp）

    注意：不支援複合中文數字（如「二十」），二位數以上請改用阿拉伯數字（如「20」）。
    """
    # 優先嘗試阿拉伯數字
    match = re.search(r'(\d+)', text)
    if match:
        return max(1, min(5, int(match.group(1))))
    # fallback：掃描中文數字（_ZH_NUM 只含 1-5，不需 clamp）
    for ch, val in _ZH_NUM.items():
        if ch in text:
            return val
    return 1


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """啟動時驗證設定，確保環境齊全再接流量"""
    config.validate()
    print("[main] LINE × Telegram Gmail Bot 啟動，所有環境變數驗證通過")
    yield
    print("[main] 服務關閉")


app = FastAPI(title="LINE Gmail Bot", lifespan=lifespan)


@app.post("/line-webhook")
async def line_webhook(request: Request) -> JSONResponse:
    """
    接收 LINE webhook，驗簽後解析意圖，有關鍵字則查 Gmail 並推摘要；
    LINE 要求無論如何都要回 200，否則會重試打爆系統。
    """
    body_bytes: bytes = await request.body()
    signature: str = request.headers.get("X-Line-Signature", "")

    # 驗簽失敗依然回 200（LINE 規定），但記錄異常來源 IP 供 IDS 分析
    channel_secret = config.get("LINE_CHANNEL_SECRET") or ""
    if not verify_signature(body_bytes, signature, channel_secret):
        client_ip = request.client.host if request.client else "unknown"
        print(f"[main] invalid signature from {client_ip}")
        return JSONResponse({"status": "ok"})

    try:
        webhook_body: dict = json.loads(body_bytes.decode("utf-8"))
    except json.JSONDecodeError as exc:
        # 解析失敗也回 200，避免 LINE 認為我們掛了
        print(f"[main] webhook body JSON 解析失敗：{exc}")
        return JSONResponse(content={"status": "ok"}, status_code=200)

    # 空字串 fallback，讓 push_message 的空 to 防護機制處理（不硬編碼 prod User ID）
    line_user_id = config.get("LINE_USER_ID", "")
    line_access_token = config.get("LINE_CHANNEL_ACCESS_TOKEN")

    # fallback_user_id 確保個人對話或沒有 source 時仍有推送目的地
    messages: list[tuple[str, str]] = extract_text_messages(
        webhook_body, fallback_user_id=line_user_id
    )

    for text, reply_to in messages:
        try:
            # ① 長度守門員：空/極短/純標點 → 推固定簡短提示，不呼叫 Claude（省 token）
            if not _is_meaningful_input(text):
                push_message(line_access_token, reply_to, _SHORT_INPUT_HINT)
                continue

            # ★ NEW ② 產題模式：偵測「提出 N 個消費者問題」指令
            if _is_generate_question(text):
                count = _extract_count(text)
                result = generate_consumer_questions(
                    config.get("ANTHROPIC_API_KEY"), count
                )
                # LINE 單則訊息上限 5000 字元，預留 200 字給前綴與安全邊際
                safe_result = result[:4800]
                push_message(line_access_token, reply_to, f"🙋 消費者問題：\n\n{safe_result}")
                continue

            # ② 子字串快速比對：命中關鍵字 → 零額外 API 成本直接查 Gmail
            has_keyword = any(kw.lower() in text.lower() for kw in config.INTENT_KEYWORDS)
            if has_keyword:
                await gmail_search_and_reply(reply_to, line_access_token, text)
                continue

            # ③ 子字串沒命中 → Claude 語意分類器判斷意圖
            has_intent, friendly_reply = classify_message(
                config.get("ANTHROPIC_API_KEY"), text
            )
            if has_intent:
                await gmail_search_and_reply(reply_to, line_access_token, text)
            else:
                push_message(line_access_token, reply_to, friendly_reply)
        except Exception as exc:
            # 單一訊息處理失敗不可穿透 → LINE 規定 webhook 必須回 200，
            # 否則 LINE 會重試並可能停用 webhook。逐則獨立 catch，
            # 一則失敗不中斷其他訊息的處理
            print(f"[main] 處理訊息時發生未預期例外：{type(exc).__name__}: {exc}")
            continue

    # LINE 要求無論事件處理結果如何都回 200
    return JSONResponse(content={"status": "ok"}, status_code=200)


async def gmail_search_and_reply(to: str, access_token: str, query_hint: str) -> None:
    """查詢 Gmail 最新 addwii 活動信，有 PDF 則解析，整合摘要推送給使用者"""
    # to 為空字串代表沒有有效推送目的地，直接跳過避免呼叫 Gmail 又無法回覆
    if not to:
        print("[main] gmail_search_and_reply 略過：to 為空字串")
        return
    gmail_query = "subject:addwii (健康 OR 活動 OR 優惠)"

    try:
        service = get_gmail_service()
    except RuntimeError as exc:
        push_message(
            access_token,
            to,
            f"Gmail 服務未準備好：{exc}",
        )
        return

    try:
        emails = search_emails(service, gmail_query, max_results=5)
    except RuntimeError as exc:
        push_message(
            access_token,
            to,
            "查詢 Gmail 失敗，請稍後再試",
        )
        print(f"[main] Gmail 搜尋例外：{exc}")
        return

    if not emails:
        push_message(
            access_token,
            to,
            "目前無相關活動信件，請稍後再查詢",
        )
        return

    # 取最新一封（list 第一筆就是最新）
    latest = emails[0]
    subject: str = latest.get("subject", "（無標題）")
    body_text: str = latest.get("body", "")
    attachments: list[dict] = latest.get("attachments", [])

    pdf_text = ""
    # 找第一個 PDF 附件解析
    for att in attachments:
        mime_ok = "pdf" in att.get("mimeType", "").lower()
        name_ok = att["name"].lower().endswith(".pdf")
        if mime_ok or name_ok:
            try:
                pdf_bytes = download_attachment(
                    service, latest["id"], att["attachmentId"]
                )
                pdf_text = extract_text_from_bytes(pdf_bytes)
            except RuntimeError as exc:
                print(f"[main] PDF 附件下載失敗：{exc}")
            break

    combined = f"主旨：{subject}\n\n{body_text}"
    if pdf_text:
        combined += f"\n\n【PDF 內容】\n{pdf_text}"

    summary = summarize(
        config.get("ANTHROPIC_API_KEY"),
        combined,
        context_hint=query_hint,
    )

    push_message(
        access_token,
        to,
        f"📧 最新活動摘要：\n\n{summary}",
    )


async def _start_question_session(
    bot_token: str, chat_id: int | str, count: int
) -> None:
    """產生一個消費者問題並以 @addwii_sales_bot 前綴傳送到 Telegram 群組。

    永遠只生成 1 題（不使用 count 參數，避免 session 管理複雜度），
    直接傳訊息到群組，不進入一問一答 session 流程。

    若 generate_consumer_questions 失敗（回傳包含「暫時無法使用」、「失敗」），
    直接把整串訊息推給使用者（降級行為）。
    """
    # 永遠只生成 1 題，count 參數不使用（避免多題 session 管理）
    # 傳入最近 5 個問題給 Claude 參考，避免重複相似主題
    avoid = _recent_tg_questions[-5:] if _recent_tg_questions else None
    raw_result = generate_consumer_questions(
        config.get("ANTHROPIC_API_KEY"), 1, avoid_questions=avoid
    )

    # 偵測降級訊息：generate_consumer_questions 失敗時回傳固定的錯誤訊息
    if "失敗" in raw_result or "暫時無法使用" in raw_result:
        tg_send_message(bot_token, chat_id, raw_result)
        return

    # 解析問題清單：按行分割，過濾空行與純數字行號前綴（如「1. 」「2.」）
    lines = [line.strip() for line in raw_result.splitlines() if line.strip()]
    # 移除行首的「N. 」或「N.」編號前綴，還原純問題文字
    questions: list[str] = []
    for line in lines:
        # 移除開頭的「1. 」「2.」等編號（支援空白可有可無）
        clean = re.sub(r"^\d+[\.、．]\s*", "", line).strip()
        if clean:
            questions.append(clean)

    if not questions:
        # 解析結果為空（格式非預期）→ 降級推送原始內容
        tg_send_message(bot_token, chat_id, raw_result)
        return

    # 取第一題加上 @addwii_sales_bot 前綴直接傳出，不設 session（只問一題不等回應）
    question_text = questions[0]
    tg_send_message(
        bot_token,
        chat_id,
        f"@addwii_sales_bot {question_text}",
    )

    # 記錄到近期問題清單，避免下次重複
    _recent_tg_questions.append(question_text)
    if len(_recent_tg_questions) > 10:
        _recent_tg_questions.pop(0)
    print(f"[main] TG 問題已推送（歷史 {len(_recent_tg_questions)} 條）：{question_text[:80]}")


async def _handle_question_reply(
    bot_token: str,
    chat_id: int | str,
    reply_text: str,
    session: "QuestionSession",
) -> None:
    """處理使用者對消費者問題的回答，推進到下一題或結束 session。

    1. 記錄本次回答到 log（未來可串接 Google Sheets 或 DB）
    2. session.current_idx += 1（推進到下一題）
    3. 若 is_done → 清除 session，傳感謝訊息
    4. 否則 → 傳下一題，更新 session（刷新 last_active 防超時）

    只移動 idx，不呼叫 Claude（問題已事先生成），故無額外 API 成本。
    """
    # 記錄回答（log 用途，未來可改為寫入 DB / Sheets）
    print(
        f"[main] Telegram 問題回答 chat_id={chat_id} "
        f"Q[{session.current_idx}]：{reply_text[:80]}"
    )

    # 推進 idx
    session.current_idx += 1

    if session.is_done:
        # 所有問題已回答完畢，清除 session 並致謝
        session_store.clear(chat_id)
        tg_send_message(
            bot_token,
            chat_id,
            "感謝您的回饋！您的答案已記錄，對我們的產品改善非常有幫助。",
        )
    else:
        # 仍有問題未問，傳下一題並更新 session（刷新 last_active）
        total = len(session.questions)
        next_q = session.current_question
        session_store.set(chat_id, session)
        tg_send_message(
            bot_token,
            chat_id,
            f"問題 {session.current_idx + 1}/{total}：{next_q}",
        )


@app.post("/telegram-webhook")
async def telegram_webhook(request: Request) -> JSONResponse:
    """接收 Telegram webhook update，驗簽後處理訊息意圖。

    安全：驗 X-Telegram-Bot-Api-Secret-Token header。
    永遠回 200（Telegram 也有重試機制，回 4xx 會觸發重試打爆系統）。
    群組裡不推「請輸入查詢內容」提示（無意義輸入直接 continue，避免太吵）。
    """
    body_bytes: bytes = await request.body()
    secret_header = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    expected_secret = config.get("TELEGRAM_SECRET_TOKEN", "")

    if not tg_verify_secret(secret_header, expected_secret):
        client_ip = request.client.host if request.client else "unknown"
        print(f"[main] Telegram invalid secret from {client_ip}")
        return JSONResponse({"ok": True})

    try:
        update: dict = json.loads(body_bytes.decode("utf-8"))
    except json.JSONDecodeError as exc:
        print(f"[main] Telegram update JSON 解析失敗：{exc}")
        return JSONResponse({"ok": True})

    bot_token = config.get("TELEGRAM_BOT_TOKEN", "")
    if not bot_token:
        print("[main] TELEGRAM_BOT_TOKEN 未設定，略過 Telegram webhook")
        return JSONResponse({"ok": True})

    messages = tg_extract_messages(update)

    for text, chat_id in messages:
        try:
            # ① 長度守門員：空/極短/純標點 → 群組裡不推提示（太吵），直接略過
            if not _is_meaningful_input(text):
                continue

            # ② 消費者問題指令：「提出 N 個問題」→ 生成 1 題並以 @addwii_sales_bot 傳出
            if _is_generate_question(text):
                count = _extract_count(text)
                await _start_question_session(bot_token, chat_id, count)
                continue

            # ③ 子字串快速比對命中 → Gmail 查詢（零額外 Claude API 成本）
            has_keyword = any(kw.lower() in text.lower() for kw in config.INTENT_KEYWORDS)
            if has_keyword:
                await tg_gmail_search_and_reply(bot_token, chat_id, text)
                continue

            # ④ 子字串沒命中 → Claude 語意分類判斷意圖
            has_intent, friendly_reply = classify_message(
                config.get("ANTHROPIC_API_KEY"), text
            )
            if has_intent:
                await tg_gmail_search_and_reply(bot_token, chat_id, text)
            else:
                tg_send_message(bot_token, chat_id, friendly_reply)

        except Exception as exc:
            # 單則訊息處理失敗不穿透，確保 webhook 永遠回 200
            print(f"[main] Telegram 訊息處理例外：{type(exc).__name__}: {exc}")
            continue

    return JSONResponse({"ok": True})


async def tg_gmail_search_and_reply(
    bot_token: str, chat_id: int | str, query_hint: str
) -> None:
    """Telegram 版 Gmail 查詢 + 推送。

    邏輯與 gmail_search_and_reply 相同，推送管道改用 tg_send_message。
    chat_id 為空字串時略過（防呼叫 Gmail 卻無法回覆的浪費）。
    """
    if not chat_id and chat_id != 0:
        print("[main] tg_gmail_search_and_reply 略過：chat_id 為空")
        return

    gmail_query = "subject:addwii (健康 OR 活動 OR 優惠)"

    try:
        service = get_gmail_service()
    except RuntimeError as exc:
        tg_send_message(bot_token, chat_id, f"Gmail 服務未準備好：{exc}")
        return

    try:
        emails = search_emails(service, gmail_query, max_results=5)
    except RuntimeError as exc:
        tg_send_message(bot_token, chat_id, "查詢 Gmail 失敗，請稍後再試")
        print(f"[main] Telegram Gmail 搜尋例外：{exc}")
        return

    if not emails:
        tg_send_message(bot_token, chat_id, "目前無相關活動信件，請稍後再查詢")
        return

    latest = emails[0]
    subject: str = latest.get("subject", "（無標題）")
    body_text: str = latest.get("body", "")
    attachments: list[dict] = latest.get("attachments", [])

    pdf_text = ""
    for att in attachments:
        mime_ok = "pdf" in att.get("mimeType", "").lower()
        name_ok = att["name"].lower().endswith(".pdf")
        if mime_ok or name_ok:
            try:
                pdf_bytes = download_attachment(
                    service, latest["id"], att["attachmentId"]
                )
                pdf_text = extract_text_from_bytes(pdf_bytes)
            except RuntimeError as exc:
                print(f"[main] Telegram PDF 附件下載失敗：{exc}")
            break

    combined = f"主旨：{subject}\n\n{body_text}"
    if pdf_text:
        combined += f"\n\n【PDF 內容】\n{pdf_text}"

    summary = summarize(
        config.get("ANTHROPIC_API_KEY"),
        combined,
        context_hint=query_hint,
    )

    tg_send_message(bot_token, chat_id, f"最新活動摘要：\n\n{summary}")


@app.get("/health")
async def health() -> dict[str, str]:
    """健康檢查端點，供 reverse proxy / systemd 監控用"""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    load_dotenv()
    uvicorn.run("main:app", host="0.0.0.0", port=8091, reload=True)
