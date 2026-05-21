"""claude_service.py — Claude API 封裝：摘要 + 意圖分類，primary Haiku + fallback Sonnet"""
import json
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

# 摘要用 system prompt：抽成常數方便與分類器 prompt 並列維護
_SYSTEM_SUMMARIZE: str = (
    "你是簡潔的行銷摘要助理，用繁體中文回覆，"
    "摘要長度 100-200 字，重點條列，不加廢話。"
)

# 安全網訊息：Claude 故障或回傳無法解析時，回給使用者的保底回覆
_SAFETY_NET_MSG: str = "請輸入查詢關鍵字，例：addwii 有什麼優惠？"

# 意圖分類器 system prompt：要求 Claude 只回傳 JSON，方便程式解析
_SYSTEM_CLASSIFY: str = (
    "你是意圖判斷器。\n"
    "這個 bot 的用途：幫使用者查 Gmail 裡最新的 addwii 健康活動、"
    "優惠、推薦相關信件並做摘要。\n"
    "你的任務：判斷使用者這句訊息是不是「想查 addwii 活動、優惠、健康相關信件」。\n"
    "輸出格式：只回傳一個 JSON 物件，格式為 "
    '{"intent": true 或 false, "reply": "字串"}。'
    "不要加 markdown 圍欄，不要任何多餘文字。\n"
    "intent 為 true 代表使用者想查（此時 reply 可給空字串）；"
    "intent 為 false 代表不是想查（此時 reply 放一句友善的繁體中文回覆，"
    "自然地引導使用者可以問「addwii 有什麼優惠」這類問題）。"
)


def _call_model(
    client: anthropic.Anthropic, model: str, system: str, user_prompt: str
) -> str:
    """對指定 model 發起一次 API 呼叫，成功回傳非空文字；任何錯誤或空回應都 re-raise

    system 改為參數傳入，讓摘要與意圖分類能共用同一段 API 呼叫邏輯，
    避免重複程式碼導致維護困難。
    """
    message = client.messages.create(
        model=model,
        max_tokens=_MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user_prompt}],
    )
    # content 是 list[ContentBlock]，取第一個 text block
    block = message.content[0] if message.content else None
    text = block.text.strip() if block and hasattr(block, "text") else ""
    # 空回應視為失敗：raise 讓 _call_with_retry / 呼叫端統一走降級訊息，
    # 不可把空字串或開發用字串當成功結果推給使用者
    if not text:
        raise RuntimeError("Claude 回傳空內容")
    return text


def _call_with_retry(
    client: anthropic.Anthropic, system: str, user_prompt: str
) -> str:
    """Haiku 優先 + 529 指數退避 retry（最多 3 次）+ 全數 529 後 Sonnet fallback。

    成功回傳 Claude 文字；任何情況的最終失敗（非 529 立即錯誤、或 529 耗盡且
    fallback 也失敗）一律 raise RuntimeError，由呼叫端決定要給使用者什麼訊息。

    只在 HTTP 529（API 過載）時重試，其他錯誤（401/400 等）直接失敗，
    避免非過載錯誤浪費等待時間。
    """
    # ── Phase 1：Primary（Haiku）+ 最多 3 次 retry ──────────────────────────
    all_primary_529: bool = False
    last_primary_exc: Exception | None = None

    for attempt in range(_MAX_RETRIES):
        try:
            return _call_model(client, _MODEL_PRIMARY, system, user_prompt)

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
            raise RuntimeError(f"Claude API 狀態錯誤：{exc}") from exc

        except anthropic.APIError as exc:
            # 網路逾時、連線失敗等傳輸層錯誤，直接失敗不重試
            print(f"[claude_service] API 錯誤（不重試）：{exc}")
            raise RuntimeError(f"Claude API 錯誤：{exc}") from exc

        except Exception as exc:
            print(f"[claude_service] 未預期錯誤：{exc}")
            raise RuntimeError(f"Claude 未預期錯誤：{exc}") from exc

    # ── Phase 2：Fallback（Sonnet）── 只在 Primary 全數 529 時觸發 ──────────
    if all_primary_529:
        print(
            f"[claude_service] Haiku 全數 529，改用 Sonnet fallback"
            f"（最後一次 primary 錯誤：{last_primary_exc}）"
        )
        try:
            return _call_model(client, _MODEL_FALLBACK, system, user_prompt)
        except anthropic.APIStatusError as exc:
            print(f"[claude_service] Sonnet fallback 失敗（APIStatusError）：{exc}")
        except anthropic.APIError as exc:
            print(f"[claude_service] Sonnet fallback 失敗（APIError）：{exc}")
        except Exception as exc:
            print(f"[claude_service] Sonnet fallback 未預期錯誤：{exc}")

    # Primary 重試耗盡（且 fallback 亦失敗），交由呼叫端處理 user-facing 訊息
    raise RuntimeError(
        f"Claude API 重試耗盡（最後一次 primary 錯誤：{last_primary_exc}）"
    )


def summarize(api_key: str, content: str, context_hint: str = "") -> str:
    """用 Haiku 產生繁體中文 100-200 字摘要，context_hint 可補充主題提示

    重試策略由 _call_with_retry 統一處理（Haiku retry + Sonnet fallback）。
    對外行為不變：所有失敗情況一律回傳固定錯誤訊息，不向上拋出例外。
    """
    # 截斷超長內容，避免 input token 爆炸
    if len(content) > _MAX_CONTENT_CHARS:
        content = content[:_MAX_CONTENT_CHARS] + "\n\n[內容過長，已截斷]"

    user_prompt = content
    if context_hint:
        user_prompt = f"【查詢主題：{context_hint}】\n\n{content}"

    client = anthropic.Anthropic(api_key=api_key)

    try:
        return _call_with_retry(client, _SYSTEM_SUMMARIZE, user_prompt)
    except RuntimeError:
        # 摘要場景失敗時給固定罐頭訊息，維持原有對外行為
        return "摘要服務暫時無法使用，請稍後再試"


def _coerce_bool(value: object) -> bool:
    """把 Claude 可能回傳的各種型別正規化為布林值。

    Claude 偶爾無視指示回傳字串型別的布林（如 "false"），
    而 bool("false") 會誤判為 True（非空字串皆 truthy），故字串需明確比對。
    """
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return bool(value)


def _parse_classify_result(raw: str) -> tuple[bool, str]:
    """解析 Claude 回傳的分類 JSON。容錯處理 markdown 圍欄。

    任何解析失敗 → 回傳 (False, _SAFETY_NET_MSG)，確保壞輸出不會讓 bot 沉默。
    """
    try:
        text = raw.strip()
        # Claude 偶爾無視指示加上 markdown 圍欄，先剝掉再解析
        if text.startswith("```"):
            # 去掉第一行（``` 或 ```json）與結尾的 ```
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        data = json.loads(text)
        intent = _coerce_bool(data["intent"])
        reply = str(data["reply"])

        # intent 為 false 但 reply 空字串 → 補上安全網訊息，避免推空訊息
        if not intent and not reply.strip():
            reply = _SAFETY_NET_MSG
        return (intent, reply)

    except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as exc:
        print(f"[claude_service] 分類結果解析失敗：{exc}")
        return (False, _SAFETY_NET_MSG)


def classify_message(api_key: str, text: str) -> tuple[bool, str]:
    """用 Claude 語意判斷使用者訊息是否想查 addwii 活動信。

    回傳 (has_intent, reply)：
    - has_intent=True：使用者想查 → 呼叫端應走 Gmail 查詢流程（reply 可忽略）
    - has_intent=False：reply 是要推給使用者的友善回覆字串

    Claude API 失敗、或回傳無法解析 → 降級回傳 (False, _SAFETY_NET_MSG)，
    確保 Claude 故障時 bot 仍能給使用者一個合理回覆。
    """
    # 防禦性截斷：避免異常超長輸入燒 input token
    if len(text) > _MAX_CONTENT_CHARS:
        text = text[:_MAX_CONTENT_CHARS]

    client = anthropic.Anthropic(api_key=api_key)

    try:
        raw = _call_with_retry(client, _SYSTEM_CLASSIFY, text)
    except RuntimeError:
        # Claude 整段失敗時走安全網，不讓 bot 沉默
        return (False, _SAFETY_NET_MSG)

    return _parse_classify_result(raw)


if __name__ == "__main__":
    # 冒煙測試：只測純函式（不需 API key，不呼叫真實 Claude API）
    print("=== _parse_classify_result 冒煙測試 ===")

    # 案例 1：正常 JSON（intent=true）
    case_normal = '{"intent": true, "reply": ""}'
    print(f"正常 JSON：{_parse_classify_result(case_normal)}")

    # 案例 2：含 markdown 圍欄的 JSON（intent=false）
    case_fenced = '```json\n{"intent": false, "reply": "你好，可以問我 addwii 有什麼優惠"}\n```'
    print(f"含圍欄 JSON：{_parse_classify_result(case_fenced)}")

    # 案例 3：壞 JSON（解析失敗應走安全網）
    case_broken = "這不是 JSON"
    print(f"壞 JSON：{_parse_classify_result(case_broken)}")

    # 案例 4：intent 為字串 "false"（修正 #1：不應誤判為 True）
    case_str_intent = '{"intent": "false", "reply": "測試回覆"}'
    print(f"字串 intent：{_parse_classify_result(case_str_intent)}")

    print("=== _coerce_bool 冒煙測試 ===")
    print(f'_coerce_bool("false")：{_coerce_bool("false")}')
    print(f'_coerce_bool("true")：{_coerce_bool("true")}')
    print(f"_coerce_bool(True)：{_coerce_bool(True)}")
    print(f"_coerce_bool(None)：{_coerce_bool(None)}")
    print(f"_coerce_bool(0)：{_coerce_bool(0)}")
