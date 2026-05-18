"""auth_gmail.py — 一次性 OAuth browser flow，在本機跑一次後把 token.json 複製到 VPS"""
import sys
from pathlib import Path

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

_SCOPES: list[str] = ["https://www.googleapis.com/auth/gmail.readonly"]


def main() -> None:
    """在本機啟動 OAuth 流程，完成後把 token.json 存到 credentials.json 同目錄"""
    base_dir = Path.home() / "line-gmail-bot"
    credentials_path = base_dir / "credentials.json"
    token_path = base_dir / "token.json"

    if not credentials_path.exists():
        print(f"[auth_gmail] 找不到 credentials.json：{credentials_path}")
        print("請先從 Google Cloud Console 下載 OAuth 用戶端憑證（Desktop App 類型）")
        sys.exit(1)

    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), _SCOPES)
    creds: Credentials = flow.run_local_server(port=0)

    token_path.write_text(creds.to_json(), encoding="utf-8")
    print(f"[auth_gmail] token.json 已存至 {token_path}")
    print("請把此檔案複製到 VPS 的相同路徑後，再啟動 line-gmail-bot.service")


if __name__ == "__main__":
    main()
