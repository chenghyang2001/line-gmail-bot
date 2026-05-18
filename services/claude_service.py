"""claude_service.py — Claude Haiku API 摘要封裝，控制 token 成本的核心"""
import anthropic

# 超過此長度截斷，避免單次呼叫燒太多 input token
_MAX_CONTENT_CHARS: int = 6000
# Haiku 4.5：最便宜的摘要模型
_MODEL: str = "claude-haiku-4-5-20251001"
_MAX_TOKENS: int = 800


def summarize(api_key: str, content: str, context_hint: str = "") -> str:
    """用 Haiku 產生繁體中文 100-200 字摘要，context_hint 可補充主題提示"""
    # 截斷超長內容，避免 input token 爆炸
    if len(content) > _MAX_CONTENT_CHARS:
        content = content[:_MAX_CONTENT_CHARS] + "\n\n[內容過長，已截斷]"

    user_prompt = content
    if context_hint:
        user_prompt = f"【查詢主題：{context_hint}】\n\n{content}"

    client = anthropic.Anthropic(api_key=api_key)

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
    except anthropic.APIError as exc:
        print(f"[claude_service] 錯誤：{exc}")
        return "摘要服務暫時無法使用，請稍後再試"
    except Exception as exc:
        print(f"[claude_service] 錯誤：{exc}")
        return "摘要服務暫時無法使用，請稍後再試"
