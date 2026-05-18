# gmail_service.py — Gmail API OAuth2 封裝，唯讀查詢
# 不啟動瀏覽器 flow（VPS 無頭環境用）
import base64
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

import config

# Gmail 唯讀 scope（最小權限原則）
_SCOPES: list[str] = ["https://www.googleapis.com/auth/gmail.readonly"]


def get_gmail_service() -> Any:
    """建立 Gmail API service。

    token 過期自動 refresh，無 token 時拋錯（不啟動 browser）。
    """
    token_path = Path(
        config.get("GMAIL_TOKEN_PATH", config.DEFAULT_GMAIL_TOKEN_PATH)
    )
    credentials_path = Path(
        config.get("GMAIL_CREDENTIALS_PATH", config.DEFAULT_GMAIL_CREDENTIALS_PATH)
    )

    if not credentials_path.exists():
        raise RuntimeError(
            f"credentials.json 不存在於 {credentials_path}，"
            "請先跑 python auth_gmail.py 完成 OAuth 授權"
        )

    if not token_path.exists():
        raise RuntimeError(
            "請先在本機跑 python auth_gmail.py 完成 OAuth，再把 token.json 複製到 VPS"
        )

    creds = Credentials.from_authorized_user_file(str(token_path), _SCOPES)

    # token 過期時自動用 refresh_token 換新，不需重新登入
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            # 把更新後的 token 存回檔案，避免下次又過期
            token_path.write_text(creds.to_json(), encoding="utf-8")
        except Exception as exc:
            raise RuntimeError(
                f"Gmail token refresh 失敗，需重新 OAuth：{exc}"
            ) from exc

    if not creds.valid:
        raise RuntimeError(
            "Gmail credentials 無效，請重新跑 auth_gmail.py 取得新 token"
        )

    service = build("gmail", "v1", credentials=creds)
    return service


def _decode_body(payload: dict) -> str:
    """遞迴取出 email 純文字 body，HTML 退而求其次"""
    mime_type: str = payload.get("mimeType", "")
    parts: list[dict] = payload.get("parts", [])

    if mime_type == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data + "==").decode(
                "utf-8", errors="replace"
            )

    if mime_type.startswith("multipart/"):
        # 優先 text/plain，其次 text/html
        for part in parts:
            if part.get("mimeType") == "text/plain":
                data = part.get("body", {}).get("data", "")
                if data:
                    return base64.urlsafe_b64decode(data + "==").decode(
                        "utf-8", errors="replace"
                    )
        for part in parts:
            if part.get("mimeType") == "text/html":
                data = part.get("body", {}).get("data", "")
                if data:
                    raw_html = base64.urlsafe_b64decode(data + "==").decode(
                        "utf-8", errors="replace"
                    )
                    # 簡單去掉 HTML 標籤（避免引入 bs4 額外依賴）
                    import re
                    return re.sub(r"<[^>]+>", "", raw_html)

    return ""


def _extract_attachments(payload: dict) -> list[dict]:
    """取出所有附件的 metadata（不下載 bytes）"""
    attachments: list[dict] = []
    parts: list[dict] = payload.get("parts", [])
    for part in parts:
        if part.get("filename") and part.get("body", {}).get("attachmentId"):
            attachments.append(
                {
                    "name": part["filename"],
                    "mimeType": part.get("mimeType", ""),
                    "attachmentId": part["body"]["attachmentId"],
                }
            )
    return attachments


def search_emails(service: Any, query: str, max_results: int = 5) -> list[dict]:
    """搜尋 Gmail 信件，回傳結構化清單（含 subject / body / attachments）"""
    try:
        result = (
            service.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )
    except HttpError as exc:
        raise RuntimeError(f"Gmail 搜尋失敗（query={query!r}）：{exc}") from exc

    messages: list[dict] = result.get("messages", [])
    if not messages:
        return []

    output: list[dict] = []
    for msg_stub in messages:
        try:
            msg = (
                service.users()
                .messages()
                .get(userId="me", id=msg_stub["id"], format="full")
                .execute()
            )
            headers: list[dict] = msg.get("payload", {}).get("headers", [])
            subject = next(
                (h["value"] for h in headers if h["name"].lower() == "subject"), ""
            )
            body = _decode_body(msg.get("payload", {}))
            attachments = _extract_attachments(msg.get("payload", {}))
            output.append(
                {
                    "id": msg_stub["id"],
                    "subject": subject,
                    "body": body,
                    "attachments": attachments,
                }
            )
        except HttpError as exc:
            # 單封信讀取失敗不中斷整批
            output.append(
                {
                    "id": msg_stub["id"],
                    "subject": "",
                    "body": f"[讀取失敗：{exc}]",
                    "attachments": [],
                }
            )

    return output


def download_attachment(service: Any, message_id: str, attachment_id: str) -> bytes:
    """下載附件並回傳原始 bytes（用於後續 PDF 解析）"""
    try:
        result = (
            service.users()
            .messages()
            .attachments()
            .get(userId="me", messageId=message_id, id=attachment_id)
            .execute()
        )
        data: str = result.get("data", "")
        return base64.urlsafe_b64decode(data + "==")
    except HttpError as exc:
        raise RuntimeError(
            f"附件下載失敗（message_id={message_id},"
            f" attachment_id={attachment_id}）：{exc}"
        ) from exc
