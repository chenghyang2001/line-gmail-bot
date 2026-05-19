"""claude_service.py — Claude API 摘要封裝，primary Haiku + fallback Sonnet"""
import time

import anthropic

# 超過此長度截斷，避免單次呼叫燒太多 input token
_MAX_CONTENT_CHARS: int = 6000

# Model 策略：優先用 Haiku（便宜），全數 529 失敗後才升級 Sonnet
_MODEL_PRIMARY: str = "claude-haiku-4-5-20251001"   # 便宜，優先用
_MODEL_FALLBACK: str = "claude-sonnet-4-6"           # Haiku 掛掉時備援

_MAX_TOKENS: int = 800

# 重試設定：只在 API 過載（529）時重試，避免其他錯誤浪費 token
_MAX_RETRIES: int = 3
_RETRY_BASE_DELAY: float = 1.0  # 秒，指數退避：1s → 2s → 4s


def _call_model(client: anthropic.Anthropic, model: str, user_prompt: str) -> str:
    """對指定 model 發起一次 API 呼叫，成功回傳文字；任何錯誤都 re-raise

    獨立抽出讓 primary retry 迴圈與 fallback 一次性呼叫共用同一段 API 邏輯，
    避免重複程式碼導致維護困難。
    """
    message = client.messages.create(
        model=model,
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


def summarize(api_key: str, content: str, context_hint: str = "") -> str:
    """用 Haiku 產生繁體中文 100-200 字摘要，context_hint 可補充主題提示

    重試策略：
    1. 先用 _MODEL_PRIMARY（Haiku）走最多 3 次 retry（指數退避 1s/2s/4s）
    2. Primary 全部 529 失敗後，自動改用 _MODEL_FALLBACK（Sonnet）再試一次
    3. Fallback 也失敗 → 回傳固定錯誤訊息

    只在 HTTP 529（API 過載）時重試，其他錯誤（401/400 等）直接失敗，
    避免非過載錯誤浪費等待時間。
    """
    # 截斷超長內容，避免 input token 爆炸
    if len(content) > _MAX_CONTENT_CHARS:
        content = content[:_MAX_CONTENT_CHARS] + "\n\n[內容過長，已截斷]"

    user_prompt = content
    if context_hint:
        user_prompt = f"【查詢主題：{context_hint}】\n\n{content}"

    client = anthropic.Anthropic(api_key=api_key)

    # ── Phase 1：Primary（Haiku）+ 最多 3 次 retry ──────────────────────────
    all_primary_529: bool = False
    last_primary_exc: Exception | None = None

    for attempt in range(_MAX_RETRIES):
        try:
            return _call_model(client, _MODEL_PRIMARY, user_prompt)

        except anthropic.APIStatusError as exc:
            # 529 = API 過載（overloaded_error），值得重試
            if exc.status_code == 529:
                last_primary_exc = exc
                if attempt < _MAX_RETRIES - 1:
                    wait_sec = _RETRY_BASE_DELAY * (2 ** attempt)
                    print(
                        f"[claude_service] 第 {attempt + 1} 次重試，"
                        f"等待 {wait_sec:.0f}s...（API 過載 529）"
                    )
                    time.sleep(wait_sec)
                    continue
                # 已到最後一次，標記全數 529
                all_primary_529 = True
                break
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

    # ── Phase 2：Fallback（Sonnet）── 只在 Primary 全數 529 時觸發 ──────────
    if all_primary_529:
        print(
            f"[claude_service] Haiku 全數 529，改用 Sonnet fallback"
            f"（最後一次 primary 錯誤：{last_primary_exc}）"
        )
        try:
            return _call_model(client, _MODEL_FALLBACK, user_prompt)
        except anthropic.APIStatusError as exc:
            print(f"[claude_service] Sonnet fallback 失敗（APIStatusError）：{exc}")
        except anthropic.APIError as exc:
            print(f"[claude_service] Sonnet fallback 失敗（APIError）：{exc}")
        except Exception as exc:
            print(f"[claude_service] Sonnet fallback 未預期錯誤：{exc}")

    # Primary 重試耗盡（且 fallback 亦失敗），回傳固定錯誤訊息
    return "摘要服務暫時無法使用，請稍後再試"
