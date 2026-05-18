"""line_service.py — LINE Messaging API 收發封裝，不依賴 line-bot-sdk（減少依賴）"""
import base64
import hashlib
import hmac
import json
import urllib.error
import urllib.request


def verify_signature(body: bytes, signature: str, channel_secret: str) -> bool:
    """HMAC-SHA256 驗簽，防止偽造 webhook 打爆系統"""
    mac = hmac.new(
        channel_secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).digest()
    expected = base64.b64encode(mac).decode("utf-8")
    # 用 hmac.compare_digest 防 timing attack
    return hmac.compare_digest(expected, signature)


def extract_text_messages(webhook_body: dict) -> list[str]:
    """從 LINE webhook payload 取出所有純文字訊息（過濾圖片、貼圖等非文字事件）"""
    texts: list[str] = []
    for event in webhook_body.get("events", []):
        if event.get("type") == "message":
            msg = event.get("message", {})
            if msg.get("type") == "text":
                text: str = msg.get("text", "").strip()
                if text:
                    texts.append(text)
    return texts


def push_message(access_token: str, to: str, text: str) -> bool:
    """LINE push message，回傳 True=成功；失敗 graceful log 不 crash"""
    url = "https://api.line.me/v2/bot/message/push"
    payload = json.dumps(
        {"to": to, "messages": [{"type": "text", "text": text}]}
    ).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as exc:
        print(f"[line_service] push_message 失敗 HTTP {exc.code}")
        return False
    except Exception as exc:
        print(f"[line_service] push_message 例外：{exc}")
        return False
