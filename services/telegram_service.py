"""telegram_service.py — Telegram Bot API 服務模組

提供：
- verify_secret_token()：驗證 Telegram webhook secret header
- send_message()：推送訊息到 chat/group
- set_webhook()：設定 bot webhook URL
- extract_text_messages()：從 update dict 提取 (text, chat_id) 清單

使用 urllib（標準庫），不需額外安裝套件。
"""
import hmac
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/{method}"
TELEGRAM_MAX_LEN = 4096  # Telegram 單則訊息字元上限（超過會被 API 拒絕）


def verify_secret_token(header_token: str, expected_secret: str) -> bool:
    """驗證 X-Telegram-Bot-Api-Secret-Token header。

    未設定 expected_secret（空字串）時跳過驗證（開發環境適用）。
    使用 hmac.compare_digest 防時序攻擊，即使比對失敗也不洩漏長度資訊。

    Args:
        header_token: 請求 header 中的 token 值
        expected_secret: 設定 webhook 時指定的 secret，空字串表示停用驗簽

    Returns:
        True 代表驗簽通過或跳過驗簽，False 代表驗簽失敗。
    """
    # 未設定 secret 時開發環境跳過驗簽（設定後就必須帶 header）
    if not expected_secret:
        return True
    if not header_token:
        return False
    # compare_digest 防時序攻擊，兩邊都需要是同型別
    return hmac.compare_digest(header_token, expected_secret)


def send_message(bot_token: str, chat_id: int | str, text: str) -> bool:
    """傳送訊息到 Telegram chat 或群組。

    text 超過 TELEGRAM_MAX_LEN 時自動截斷（結尾補 '...' 提示截斷）。
    使用 urllib 標準庫（不需 requests 或 httpx）。
    失敗時 print 錯誤訊息並回傳 False，不 raise（避免穿透 webhook loop）。

    Args:
        bot_token: Telegram Bot API token
        chat_id: 目的地 chat_id（私聊為正整數，群組為負整數，頻道為 @username）
        text: 要傳送的訊息文字

    Returns:
        True 代表傳送成功，False 代表傳送失敗。
    """
    if not bot_token:
        print("[telegram_service] send_message 略過：bot_token 為空")
        return False
    if not text:
        print("[telegram_service] send_message 略過：text 為空")
        return False

    # 超過上限自動截斷，保留 '...' 尾綴提示使用者內容已截斷
    if len(text) > TELEGRAM_MAX_LEN:
        text = text[: TELEGRAM_MAX_LEN - 3] + "..."

    url = TELEGRAM_API_BASE.format(token=bot_token, method="sendMessage")
    payload = json.dumps(
        {"chat_id": chat_id, "text": text}
    ).encode("utf-8")

    try:
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if not result.get("ok"):
                print(
                    f"[telegram_service] sendMessage 失敗，"
                    f"Telegram 回應：{result}"
                )
                return False
        return True

    except urllib.error.HTTPError as exc:
        print(f"[telegram_service] sendMessage HTTP 錯誤：{exc.code} {exc.reason}")
        return False
    except urllib.error.URLError as exc:
        print(f"[telegram_service] sendMessage 網路錯誤：{exc.reason}")
        return False
    except Exception as exc:
        print(f"[telegram_service] sendMessage 未預期錯誤：{type(exc).__name__}: {exc}")
        return False


def set_webhook(
    bot_token: str, webhook_url: str, secret_token: str = ""
) -> dict[str, Any]:
    """設定 Telegram bot webhook URL。

    建議呼叫一次即可，通常在部署時執行，不需在 lifespan 裡每次啟動都跑。
    secret_token 設定後，Telegram 每個 update 都會帶 X-Telegram-Bot-Api-Secret-Token header。

    Args:
        bot_token: Telegram Bot API token
        webhook_url: HTTPS webhook 完整 URL（Telegram 要求 HTTPS）
        secret_token: 可選，webhook 驗簽 token（建議設定，防偽造請求）

    Returns:
        Telegram API 的 response dict

    Raises:
        RuntimeError: API 呼叫失敗時
    """
    url = TELEGRAM_API_BASE.format(token=bot_token, method="setWebhook")
    params: dict[str, Any] = {"url": webhook_url}
    if secret_token:
        params["secret_token"] = secret_token

    payload = json.dumps(params).encode("utf-8")

    try:
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        return result

    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"setWebhook HTTP 錯誤：{exc.code} {exc.reason}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"setWebhook 網路錯誤：{exc.reason}") from exc
    except Exception as exc:
        raise RuntimeError(
            f"setWebhook 未預期錯誤：{type(exc).__name__}: {exc}"
        ) from exc


def extract_text_messages(update: dict) -> list[tuple[str, int | str]]:
    """從 Telegram update 提取文字訊息。

    回傳 list[(text, chat_id)]。
    過濾規則（符合任一條件即略過）：
    - 非文字訊息（無 text 欄位）
    - bot 自身發送（from.is_bot == True，防止 bot 自迴圈）
    - 指令（text 以 '/' 開頭，如 /start、/help）

    同時處理 message 和 edited_message（使用者編輯訊息也觸發）。

    Args:
        update: Telegram webhook update dict

    Returns:
        [(text, chat_id)] 清單，chat_id 可能是負數（群組）或正數（私聊）
    """
    results: list[tuple[str, int | str]] = []

    # 同時嘗試 message 和 edited_message
    for key in ("message", "edited_message"):
        msg = update.get(key)
        if not isinstance(msg, dict):
            continue

        text = msg.get("text")
        if not isinstance(text, str) or not text:
            continue

        # 指令以 '/' 開頭，跳過（/start、/help 等不走意圖處理）
        if text.startswith("/"):
            continue

        # 過濾 bot 自身發送（防止 bot 回應自己觸發無限循環）
        sender = msg.get("from")
        if isinstance(sender, dict) and sender.get("is_bot"):
            continue

        # chat_id 可能是負數（群組）或正數（私聊）
        chat = msg.get("chat")
        if not isinstance(chat, dict):
            continue
        chat_id = chat.get("id")
        if chat_id is None:
            continue

        results.append((text, chat_id))

    return results


if __name__ == "__main__":
    # 冒煙測試：只測純函式（不需真實 Telegram API，不產生網路請求）
    print("=== verify_secret_token 冒煙測試 ===")

    # 案例 1（happy path）：token 與 secret 相符 → True
    result1 = verify_secret_token("my-secret", "my-secret")
    print(f"相符 token：{result1}")  # 預期 True
    assert result1 is True, "相符 token 應回 True"

    # 案例 2（edge case）：empty expected_secret → 跳過驗簽，回 True
    result2 = verify_secret_token("anything", "")
    print(f"空 expected_secret（跳過驗簽）：{result2}")  # 預期 True
    assert result2 is True, "空 expected_secret 應回 True（跳過驗簽）"

    # 案例 3（error case）：token 不符 → False
    result3 = verify_secret_token("wrong-token", "my-secret")
    print(f"不符 token：{result3}")  # 預期 False
    assert result3 is False, "不符 token 應回 False"

    print("\n=== extract_text_messages 冒煙測試 ===")

    # 案例 1（happy path）：正常私聊文字訊息
    update_normal = {
        "message": {
            "text": "addwii 有什麼優惠",
            "from": {"id": 123, "is_bot": False},
            "chat": {"id": 456},
        }
    }
    msgs1 = extract_text_messages(update_normal)
    print(f"正常訊息：{msgs1}")
    assert len(msgs1) == 1 and msgs1[0] == ("addwii 有什麼優惠", 456)

    # 案例 2（edge case）：bot 發送 → 過濾掉
    update_bot = {
        "message": {
            "text": "bot 回覆",
            "from": {"id": 999, "is_bot": True},
            "chat": {"id": 456},
        }
    }
    msgs2 = extract_text_messages(update_bot)
    print(f"bot 訊息（應過濾）：{msgs2}")
    assert msgs2 == [], "bot 訊息應被過濾"

    # 案例 3（edge case）：指令 /start → 過濾掉
    update_cmd = {
        "message": {
            "text": "/start",
            "from": {"id": 123, "is_bot": False},
            "chat": {"id": 456},
        }
    }
    msgs3 = extract_text_messages(update_cmd)
    print(f"指令 /start（應過濾）：{msgs3}")
    assert msgs3 == [], "/start 指令應被過濾"

    print("\n所有冒煙測試通過")
