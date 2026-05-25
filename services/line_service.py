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


def extract_text_messages(
    webhook_body: dict, fallback_user_id: str = ""
) -> list[tuple[str, str]]:
    """從 LINE webhook payload 取出所有純文字訊息，同時保留回覆目的地。

    回傳 list[tuple[str, str]]，每個 tuple 為 (text, reply_to)。
    reply_to 規則：
      - source.type == "group" → groupId（群組訊息回到群組）
      - source.type == "room"  → roomId（LINE 多人聊天室，已於 2021 年廢棄，
                                 向下相容保留此分支，新 OA 不應再接收 room 事件）
      - source.type == "user" 或其他 → userId（私人對話）
      - 沒有 source → 使用 fallback_user_id

    只取 event.type == "message" 且 msg.type == "text" 的事件；
    text 為空字串者跳過，不加入結果。
    """
    results: list[tuple[str, str]] = []
    for event in webhook_body.get("events", []):
        if event.get("type") != "message":
            continue
        msg = event.get("message", {})
        if msg.get("type") != "text":
            continue
        text: str = msg.get("text", "").strip()
        if not text:
            continue

        # 根據 source.type 決定推送目的地
        source: dict = event.get("source", {})
        source_type: str = source.get("type", "")
        if source_type == "group":
            gid = source.get("groupId", "")
            if not gid:
                # groupId 缺失代表 LINE 回傳異常 payload，記錄以便追查
                print(
                    f"[line_service] 警告：group 事件缺少 groupId，"
                    f"fallback 到 {fallback_user_id!r}"
                )
            reply_to = gid or fallback_user_id
        elif source_type == "room":
            # room 類型為 LINE 已廢棄功能（2021），向下相容保留
            rid = source.get("roomId", "")
            if not rid:
                # roomId 缺失代表 LINE 回傳異常 payload，記錄以便追查
                print(
                    f"[line_service] 警告：room 事件缺少 roomId，"
                    f"fallback 到 {fallback_user_id!r}"
                )
            reply_to = rid or fallback_user_id
        else:
            # "user" 或其他未知類型，回到個人 userId
            reply_to = source.get("userId", fallback_user_id)

        results.append((text, reply_to))
    return results


def push_message(access_token: str, to: str, text: str) -> bool:
    """LINE push message，回傳 True=成功；失敗 graceful log 不 crash"""
    # to 為空字串代表上游邏輯未能取得推送目的地，直接略過避免打空 API
    if not to:
        print("[line_service] push_message 略過：to 為空字串")
        return False
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
