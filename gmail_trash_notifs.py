"""
gmail_trash_notifs.py — 批次 trash Gmail 通知信

用法：
  PYTHONUTF8=1 python gmail_trash_notifs.py

功能：
1. 用 credentials.json (gmail.modify scope) 做 OAuth（首次會開瀏覽器）
2. 搜尋 from:calendar-notification@google.com subject:"吃足夠的鹽"
3. 將所有找到的 message 移至 TRASH
4. 回報刪除數量
"""

import sys
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# gmail.modify scope 允許讀取、修改（含 trash）信件
# 只申請 modify，不申請 send，最小權限原則
SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

# 搜尋條件：鎖定 Google Calendar 的「吃足夠的鹽」通知信
SEARCH_QUERY = 'from:calendar-notification@google.com subject:"吃足夠的鹽"'

# credentials.json / token 放在腳本同一目錄，避免硬編碼路徑
BASE_DIR = Path(__file__).parent
CREDENTIALS_PATH = BASE_DIR / "credentials.json"
# 使用獨立 token 檔，避免覆蓋現有 gmail.readonly 的 token.json
TOKEN_PATH = BASE_DIR / "token_modify.json"


def get_gmail_service():
    """建立並回傳 Gmail API service 物件，自動處理 OAuth 流程。"""
    creds = None

    # 若已有快取的 token，嘗試直接載入
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    # token 不存在或已過期時重新認證
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            # refresh_token 仍有效，靜默刷新，不開瀏覽器
            creds.refresh(Request())
        else:
            # 首次執行或 refresh_token 失效，必須開瀏覽器完整授權
            if not CREDENTIALS_PATH.exists():
                print(
                    f"錯誤：找不到 {CREDENTIALS_PATH}，請先從 Google Cloud Console 下載",
                    file=sys.stderr,
                )
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_PATH), SCOPES
            )
            creds = flow.run_local_server(port=0)

        # 將新 token 寫入快取，下次直接讀取
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")

    return build("gmail", "v1", credentials=creds)


def fetch_all_message_ids(service, query: str) -> list[str]:
    """
    搜尋符合 query 的所有信件 ID，自動翻頁拿完整結果。

    Gmail API 每次最多回傳 500 筆，超過時會有 nextPageToken。
    """
    message_ids = []
    page_token = None

    while True:
        kwargs = {
            "userId": "me",
            "q": query,
            "maxResults": 500,
        }
        if page_token:
            kwargs["pageToken"] = page_token

        try:
            response = service.users().messages().list(**kwargs).execute()
        except HttpError as e:
            # 搜尋階段失敗直接中止，不繼續執行
            print(f"錯誤：搜尋信件失敗 — {e}", file=sys.stderr)
            sys.exit(1)

        messages = response.get("messages", [])
        message_ids.extend(msg["id"] for msg in messages)

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return message_ids


def trash_messages(service, message_ids: list[str]) -> tuple[int, int]:
    """
    批次 trash 指定 message ID 清單。

    單封失敗（例如信件已被刪除）不中斷整個流程，印錯誤後繼續。
    回傳 (成功數, 失敗數)。
    """
    success_count = 0
    fail_count = 0

    for msg_id in message_ids:
        try:
            service.users().messages().trash(userId="me", id=msg_id).execute()
            success_count += 1
        except HttpError as e:
            # 單封失敗不中斷，記錄後繼續
            print(f"警告：trash 信件 {msg_id} 失敗 — {e}", file=sys.stderr)
            fail_count += 1

    return success_count, fail_count


def main():
    """主流程：搜尋 → trash → 回報結果。"""
    try:
        print("正在建立 Gmail API 連線...")
        service = get_gmail_service()

        print(f"搜尋條件：{SEARCH_QUERY}")
        message_ids = fetch_all_message_ids(service, SEARCH_QUERY)
        total_found = len(message_ids)
        print(f"找到 {total_found} 封符合的信件")

        if total_found == 0:
            print("沒有需要 trash 的信件，結束。")
            return

        print(f"開始 trash {total_found} 封信件...")
        success_count, fail_count = trash_messages(service, message_ids)

        # 最終 summary
        print(f"\n已 trash {success_count} 封，失敗 {fail_count} 封")

    except KeyboardInterrupt:
        print("\n使用者中斷執行", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"錯誤：未預期的例外 — {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
