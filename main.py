"""main.py — LINE Webhook FastAPI server，接收 LINE 訊息後查 Gmail 並推摘要"""
import json
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

import config
from services.claude_service import summarize
from services.gmail_service import download_attachment, get_gmail_service, search_emails
from services.line_service import (
    extract_text_messages,
    push_message,
    verify_signature,
)
from services.pdf_parser import extract_text_from_bytes


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """啟動時驗證設定，確保環境齊全再接流量"""
    config.validate()
    print("[main] LINE Gmail Bot 啟動，所有環境變數驗證通過")
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

    texts: list[str] = extract_text_messages(webhook_body)

    line_user_id = config.get("LINE_USER_ID", "U8ca91ed1c30228e776d83179a1893fb0")
    line_access_token = config.get("LINE_CHANNEL_ACCESS_TOKEN")

    for text in texts:
        has_intent = any(kw.lower() in text.lower() for kw in config.INTENT_KEYWORDS)
        if has_intent:
            # 非同步查 Gmail 並推回結果
            await gmail_search_and_reply(line_user_id, line_access_token, text)
        else:
            push_message(
                line_access_token,
                line_user_id,
                "請輸入查詢關鍵字，例：addwii 有什麼優惠？",
            )

    # LINE 要求無論事件處理結果如何都回 200
    return JSONResponse(content={"status": "ok"}, status_code=200)


async def gmail_search_and_reply(to: str, access_token: str, query_hint: str) -> None:
    """查詢 Gmail 最新 addwii 活動信，有 PDF 則解析，整合摘要推送給使用者"""
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


@app.get("/health")
async def health() -> dict[str, str]:
    """健康檢查端點，供 reverse proxy / systemd 監控用"""
    return {"status": "ok"}
