"""config.py — 從環境變數讀取並驗證所有服務設定，避免執行期才發現缺少 key"""
# 備份版本：VPS（/opt/line-gmail-bot/）— 使用前 cp config-vps.py config.py
import os

# 不在模組頂層讀 env var，validate() 通過後由呼叫方透過 config.get() 讀取

_REQUIRED_ENV_VARS: list[str] = [
    "LINE_CHANNEL_SECRET",
    "LINE_CHANNEL_ACCESS_TOKEN",
    "ANTHROPIC_API_KEY",
]

# 意圖偵測關鍵字（LINE 訊息含任一字即搜尋 Gmail）
INTENT_KEYWORDS: list[str] = ["優惠", "活動", "健康", "addwii", "Addwii", "韋德", "方案", "S0", "空氣", "推薦", "小空間"]

# 路徑常數（VPS 固定路徑 /opt/line-gmail-bot/）
DEFAULT_GMAIL_CREDENTIALS_PATH = "/opt/line-gmail-bot/credentials.json"
DEFAULT_GMAIL_TOKEN_PATH = "/opt/line-gmail-bot/token.json"


def validate() -> None:
    """啟動時驗證必要環境變數，缺少任何一個就 raise，防止空字串帶入 HMAC 邏輯"""
    missing = [k for k in _REQUIRED_ENV_VARS if not os.environ.get(k)]
    if missing:
        raise EnvironmentError(
            f"缺少必要環境變數：{', '.join(missing)}\n"
            "請確認 .env 已設定並由 systemd EnvironmentFile 載入"
        )


def get(key: str, default: str | None = None) -> str:
    """讀取環境變數（validate() 通過後才呼叫此函式）"""
    value = os.environ.get(key, default)
    if value is None:
        raise EnvironmentError(f"環境變數 {key!r} 未設定且無預設值")
    return value
