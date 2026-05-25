"""tg-sales-interviewer.py — 自動化 Telegram 業務問答迴圈

從 VPS 讀取 bot token + API key，對 Telegram 群組發問，
等待 addwii_sales_bot 回覆，再用 Claude Haiku 產出跟進問題，
持續 N 輪並將對話記錄寫入 doc/tg-interview-YYYYMMDD-HHMMSS.md。
"""
import argparse
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import json
from datetime import datetime, timezone
from pathlib import Path

import anthropic

# ── 關鍵設定常數 ─────────────────────────────────────────────────────────────
VPS_SSH = "claude@187.127.109.145"
SSH_KEY = str(Path.home() / ".ssh" / "id_ed25519")
GROUP_CHAT_ID = -5186230345
SALES_BOT_USERNAME = "addwii_sales_bot"
POLL_INTERVAL = 3          # 輪詢間隔（秒）
MAX_WAIT = 90              # 最多等候秒數
MAX_ROUNDS = 3
TG_API_BASE = "https://api.telegram.org/bot{token}/{method}"
OUTPUT_DIR = Path(__file__).parent / "doc"

# 跟進問題產生用 system prompt
_SYSTEM_FOLLOWUP = (
    "你是對 addwii 空氣清淨機感興趣的潛在客戶，"
    "根據業務助理的最新回應，產出一個自然的跟進問題。"
    "繁體中文，25字以內，只輸出問題本身，不要加前置詞或說明。"
)


def _fetch_vps_env(key: str) -> str:
    """SSH 到 VPS 讀取 /opt/line-gmail-bot/.env 指定 key 的值。

    解析 KEY=value / KEY="value" / KEY='value' 三種格式。
    VPS env 在 .env 中統一管理，避免 key 散落在多處難以輪換。
    """
    try:
        result = subprocess.run(
            [
                "ssh", "-i", SSH_KEY,
                "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=10",
                VPS_SSH,
                f"sudo grep ^{key}= /opt/line-gmail-bot/.env",
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"無法從 VPS 讀取 {key}：SSH 連線逾時") from exc
    except OSError as exc:
        raise RuntimeError(f"無法從 VPS 讀取 {key}：{exc}") from exc

    if result.returncode != 0:
        raise RuntimeError(f"無法從 VPS 讀取 {key}（grep 找不到該 key）")

    line = result.stdout.strip()
    # 去掉 KEY= 前綴，再剝除單/雙引號
    value = line.split("=", 1)[1].strip().strip("\"'")
    if not value:
        raise RuntimeError(f"VPS 的 {key} 值為空")
    return value


def _send_tg_message(bot_token: str, chat_id: int, text: str) -> bool:
    """用 urllib 呼叫 Telegram sendMessage，避免引入 requests 依賴。

    Telegram 不允許空訊息，在呼叫前應先確認 text 非空。
    """
    url = TG_API_BASE.format(token=bot_token, method="sendMessage")
    payload = json.dumps({
        "chat_id": chat_id,
        "text": text,
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            resp_data = json.loads(resp.read().decode("utf-8"))
            return bool(resp_data.get("ok"))
    except urllib.error.HTTPError as exc:
        print(f"[tg] sendMessage HTTP 錯誤：{exc.code} {exc.reason}")
        return False
    except urllib.error.URLError as exc:
        print(f"[tg] sendMessage 連線失敗：{exc.reason}")
        return False


def _extract_tg_in_text(log_line: str) -> str | None:
    """從 journalctl 一行中提取 [TG-IN] 後的訊息文字。

    日誌格式範例：
      ... INFO ... [TG-IN] chat=-5186230345 from=addwii_sales_bot(bot=True): 謝謝您的詢問...
    提取冒號後的完整文字（去掉首尾空白）。
    """
    # 比對 from=<name>(bot=True): 後面的文字
    pattern = r"\[TG-IN\].*?from=\S+\(bot=True\):\s*(.+)"
    m = re.search(pattern, log_line)
    if m:
        return m.group(1).strip()
    return None


def _poll_vps_for_response(since_utc: str, timeout: int, interval: int) -> str | None:
    """SSH 輪詢 VPS journalctl，等 addwii_sales_bot(bot=True) 的 [TG-IN] 出現。

    since_utc：journalctl --since 的時間字串（UTC，格式 'YYYY-MM-DD HH:MM:SS'）。
    回傳訊息文字；超時後回 None。
    """
    elapsed = 0
    while elapsed < timeout:
        time.sleep(interval)
        elapsed += interval
        try:
            result = subprocess.run(
                [
                    "ssh", "-i", SSH_KEY,
                    "-o", "StrictHostKeyChecking=no",
                    "-o", "ConnectTimeout=10",
                    VPS_SSH,
                    f"sudo journalctl -u line-gmail-bot --since \"{since_utc}\""
                    " --no-pager 2>/dev/null"
                    f" | grep 'TG-IN.*{SALES_BOT_USERNAME}(bot=True)'"
                    " | tail -1",
                ],
                capture_output=True,
                text=True,
                timeout=20,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            # 單次 SSH 失敗不中止輪詢，繼續等下一個 interval
            print(f"[poll] SSH 暫時失敗：{exc}，繼續輪詢...")
            continue

        if result.stdout.strip():
            msg = _extract_tg_in_text(result.stdout.strip())
            if msg:
                return msg

    return None


def _generate_followup(
    client: anthropic.Anthropic,
    response: str,
    history: list[dict],
) -> str:
    """用 Claude Haiku 根據業務助理的最新回應產出跟進問題。

    max_tokens 設 150 即夠（問題最多 25 字，避免浪費 token）。
    API 失敗時 raise RuntimeError，由 main() 中的迴圈決定是否中止。
    """
    # 組合對話 context 給 Claude
    history_text = "\n".join(
        f"{'我' if h['role'] == 'user' else '業務助理'}：{h['content']}"
        for h in history
    )
    user_prompt = (
        f"對話記錄：\n{history_text}\n\n"
        f"業務助理最新回應：{response}\n\n"
        "請產出下一個跟進問題："
    )
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=150,
        system=_SYSTEM_FOLLOWUP,
        messages=[{"role": "user", "content": user_prompt}],
    )
    block = message.content[0] if message.content else None
    text = block.text.strip() if block and hasattr(block, "text") else ""
    if not text:
        raise RuntimeError("Claude 跟進問題產生失敗（回傳空內容）")
    return text


def _init_output_file(output_path: Path, rounds: int) -> None:
    """建立 Markdown 輸出檔案並寫入標頭。"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("# Telegram 業務問答記錄\n\n")
        f.write(
            f"**開始時間**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"**目標**: @{SALES_BOT_USERNAME} 跟進問答（共 {rounds} 輪）\n\n"
            "---\n\n"
        )


def _append_to_md(output_path: Path, text: str) -> None:
    """追加文字到 Markdown 輸出檔案（統一入口，方便測試替換）。"""
    with open(output_path, "a", encoding="utf-8") as f:
        f.write(text)
        f.flush()


def main(rounds: int = MAX_ROUNDS) -> Path:
    """主流程：讀 env → 迴圈問答 → 寫 md → 回傳輸出路徑。

    先嘗試從本機 os.environ 取 key，沒有才 SSH 到 VPS 讀取，
    節省不必要的網路往返（本機開發時不需 VPS 連線）。
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"tg-interview-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"

    # ── 1. 取得 API Keys ──────────────────────────────────────────────────────
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN") or _fetch_vps_env("TELEGRAM_BOT_TOKEN")
    api_key = os.environ.get("ANTHROPIC_API_KEY") or _fetch_vps_env("ANTHROPIC_API_KEY")

    client = anthropic.Anthropic(api_key=api_key)

    # ── 2. 初始化輸出檔案 ────────────────────────────────────────────────────
    _init_output_file(output_path, rounds)

    # ── 3. 問答迴圈 ──────────────────────────────────────────────────────────
    question = "addwii 有什麼優惠"  # 第一輪固定初始問題
    history: list[dict] = []
    last_response = ""

    for rnd in range(1, rounds + 1):
        if rnd > 1:
            # 第 2 輪起由 Claude 根據上輪回應產出跟進問題
            try:
                question = _generate_followup(client, last_response, history)
            except RuntimeError as exc:
                _append_to_md(output_path, f"\n**[錯誤] 跟進問題產生失敗：{exc}，終止迴圈**\n")
                print(f"[main] 跟進問題失敗，終止：{exc}")
                break

        ts = datetime.now().strftime("%H:%M:%S")
        full_msg = f"@{SALES_BOT_USERNAME} {question}"
        print(f"[Round {rnd}] 發送：{full_msg}")

        _append_to_md(
            output_path,
            f"## 第 {rnd} 輪\n\n"
            f"**[{ts}] 我的問題（發送至群組）：**\n> {full_msg}\n\n",
        )

        # 記錄發送時間（UTC）作為 journalctl --since 的基準
        since_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        if not _send_tg_message(bot_token, GROUP_CHAT_ID, full_msg):
            _append_to_md(output_path, "**[錯誤] 訊息發送失敗，終止迴圈**\n")
            print("[main] 訊息發送失敗，終止。")
            break

        # ── 等待 sales bot 回覆 ───────────────────────────────────────────
        response = _poll_vps_for_response(since_utc, MAX_WAIT, POLL_INTERVAL)

        ts_resp = datetime.now().strftime("%H:%M:%S")
        if response is None:
            _append_to_md(
                output_path,
                f"**[{ts_resp}] addwii業務助理 回應：**\n"
                f"> （逾時 {MAX_WAIT}s，未收到回應）\n\n---\n\n",
            )
            print(f"[main] 逾時未收到回應，終止。")
            break

        print(f"[Round {rnd}] 收到回應：{response[:80]}...")
        _append_to_md(
            output_path,
            f"**[{ts_resp}] addwii業務助理 回應：**\n> {response}\n\n---\n\n",
        )

        # 更新 history 供下一輪跟進問題參考
        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": response})
        last_response = response

    # ── 4. 結束記錄 ──────────────────────────────────────────────────────────
    _append_to_md(
        output_path,
        f"**結束時間**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
    )
    print(f"[main] 完成，輸出：{output_path}")
    return output_path


if __name__ == "__main__":
    # PYTHONUTF8=1 python tg-sales-interviewer.py  ← Windows 跑前加此前置
    parser = argparse.ArgumentParser(
        description="自動化 Telegram 業務問答迴圈，結果存入 doc/ 目錄"
    )
    parser.add_argument(
        "--rounds", type=int, default=MAX_ROUNDS,
        help=f"問答輪數（預設 {MAX_ROUNDS}）",
    )
    args = parser.parse_args()

    output_path = main(rounds=args.rounds)

    # 讀取並列印最終報告
    with open(output_path, encoding="utf-8") as f:
        print("\n" + "=" * 60)
        print(f.read())
