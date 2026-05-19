"""claude_service.py — Claude Haiku API 摘要封裝，控制 token 成本的核心"""
import time

import anthropic

# 超過此長度截斷，避免單次呼叫燒太多 input token
_MAX_CONTENT_CHARS: int = 6000
# Haiku 4.5：最便宜的摘要模型
_MODEL: str = "claude-haiku-4-5-20251001"
_MAX_TOKENS: int = 800

# 重試設定：只在 API 過載（529）時重試，避免其他錯誤浪費 token
_MAX_RETRIES: int = 3
_RETRY_BASE_DELAY: float = 1.0  # 秒，指數退避：1s → 2s → 4s


def summarize(api_key: str, content: str, context_hint: str = "") -> str:
    """用 Haiku 產生繁體中文 100-200 字摘要，context_hint 可補充主題提示

    遇到 HTTP 529（API 過載）時自動指數退避重試，最多 3 次。
    其他 API 錯誤（401、429 rate-limit 以外的問題等）直接失敗，不浪費等待時間。
    """
    # 截斷超長內容，避免 input token 爆炸
    if len(content) > _MAX_CONTENT_CHARS:
        content = content[:_MAX_CONTENT_CHARS] + "\n\n[內容過長，已截斷]"

    user_prompt = content
    if context_hint:
        user_prompt = f"【查詢主題：{context_hint}】\n\n{content}"

    client = anthropic.Anthropic(api_key=api_key)

    last_exc: Exception | None = None

    for attempt in range(_MAX_RETRIES):
        try:
            message = client.messages.create(
                model=_MODEL,
                max_tokens=_MAX_TOKENS,
                system=(
                    "你是簡潔的行銷摘要助理，用繁體中文回覆，"
                    "摘要長度 100-200 字，重點條列，不加廢話。"
                ),
                messages=[{"role": "user", "content": user_prompt}],
            )
            # content 是 list[ContentBlock]，取第一個 text block
            block = message.content[0] if message.content else None
            if block and hasattr(block, "text"):
                return block.text.strip()
            return "[Claude 回傳空內容]"

        except anthropic.APIStatusError as exc:
            # 529 = API 過載（overloaded_error），值得重試
            if exc.status_code == 529:
                last_exc = exc
                if attempt < _MAX_RETRIES - 1:
                    wait_sec = _RETRY_BASE_DELAY * (2 ** attempt)
                    print(
                        f"[claude_service] 第 {attempt + 1} 次重試，"
                        f"等待 {wait_sec:.0f}s...（API 過載 529）"
                    )
                    time.sleep(wait_sec)
                    continue
                # 最後一次也失敗
                print(f"[claude_service] 重試 {_MAX_RETRIES} 次後仍失敗（529）：{exc}")
                return "摘要服務暫時無法使用，請稍後再試"
            # 非 529 的 API status 錯誤（如 401 未授權、400 格式錯誤）直接失敗
            print(f"[claude_service] API 狀態錯誤（不重試）：{exc}")
            return "摘要服務暫時無法使用，請稍後再試"

        except anthropic.APIError as exc:
            # 網路逾時、連線失敗等傳輸層錯誤，直接失敗不重試
            print(f"[claude_service] API 錯誤（不重試）：{exc}")
            return "摘要服務暫時無法使用，請稍後再試"

        except Exception as exc:
            print(f"[claude_service] 未預期錯誤：{exc}")
            return "摘要服務暫時無法使用，請稍後再試"

    # 理論上不會走到這裡，但防禦性加上 fallback
    print(f"[claude_service] 所有重試均耗盡：{last_exc}")
    return "摘要服務暫時無法使用，請稍後再試"
