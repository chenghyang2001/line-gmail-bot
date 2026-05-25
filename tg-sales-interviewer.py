"""tg-sales-interviewer.py — 自動化 Telegram 業務問答迴圈

用兩個 bot token（潛客 + 業務）模擬完整客戶對話：
- @addwii_prospect_bot 發出消費者問題
- Claude 生成業務回覆，以 @addwii_sales_bot 發到群組
- Claude 根據回覆產出跟進問題，持續 N 輪
- 對話記錄寫入 doc/tg-interview-YYYYMMDD-HHMMSS.md

注意：Telegram bot-to-bot 訊息封鎖（無論 privacy mode）導致 webhook 無法觸發，
因此業務回覆由本腳本直接生成，以 @addwii_sales_bot 身份發到群組。
"""
import argparse
import os
import time
import urllib.error
import urllib.request
import json
from datetime import datetime
from pathlib import Path

import anthropic

# ── 關鍵設定常數 ─────────────────────────────────────────────────────────────
GROUP_CHAT_ID = -5186230345
SALES_BOT_USERNAME = "addwii_sales_bot"
MAX_ROUNDS = 3
TG_API_BASE = "https://api.telegram.org/bot{token}/{method}"
OUTPUT_DIR = Path(__file__).parent / "doc"

# 跟進問題產生用 system prompt
_SYSTEM_FOLLOWUP = (
    "你是對 addwii 空氣清淨機感興趣的潛在客戶，"
    "根據業務助理的最新回應，產出一個自然的跟進問題。"
    "繁體中文，25字以內，只輸出問題本身，不要加前置詞或說明。"
)

# 業務助理回覆 system prompt（與 VPS claude_service.py 保持一致）
_SYSTEM_SALES_REPLY = (
    "你是 addwii 空氣清淨機品牌的專業業務助理，親切有禮。"
    "addwii 主打家用空氣清淨機：S05（適合 ≤15坪，約 NT$8,800）、S10（適合 ≤30坪，約 NT$12,800）。"
    "目前優惠：新品首批 85 折，加購濾網組合另享 9 折。HEPA 三層過濾，PM2.5 感應器即時顯示。"
    "請用繁體中文回答，150 字以內，語氣親切自然，並主動詢問客戶使用環境和需求。"
)


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


def _generate_sales_reply(client: anthropic.Anthropic, question: str) -> str:
    """用 Claude 根據 addwii 產品知識生成業務回覆。

    Telegram bot-to-bot 封鎖導致 @addwii_sales_bot webhook 無法被 @addwii_prospect_bot 觸發，
    因此業務回覆改由本腳本直接呼叫 Claude 生成（而非透過 VPS webhook）。
    max_tokens 設 300 足夠 150 字繁中回覆（~200 token）。
    API 失敗時 raise RuntimeError，由 main() 決定是否中止。
    """
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        system=_SYSTEM_SALES_REPLY,
        messages=[{"role": "user", "content": question[:1000]}],
    )
    block = message.content[0] if message.content else None
    text = block.text.strip() if block and hasattr(block, "text") else ""
    if not text:
        raise RuntimeError("Claude 業務回覆生成失敗（回傳空內容）")
    return text


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

    環境變數需求：
    - TELEGRAM_BOT_TOKEN：@addwii_prospect_bot token（發出消費者問題）
    - ADDWII_SALES_BOT_TOKEN：@addwii_sales_bot token（以此身份發業務回覆）
    - ANTHROPIC_API_KEY：Claude API 金鑰

    架構說明：Telegram bot-to-bot 訊息封鎖（即使 privacy mode 關閉），
    @addwii_prospect_bot 的訊息無法觸發 @addwii_sales_bot 的 webhook。
    因此業務回覆改由本腳本直接生成，以 @addwii_sales_bot 身份發到群組。
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"tg-interview-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"

    # ── 1. 取得 API Keys ──────────────────────────────────────────────────────
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        raise RuntimeError(
            "請設定環境變數 TELEGRAM_BOT_TOKEN（@addwii_prospect_bot）\n"
            "Windows Git Bash 執行範例：\n"
            "  PYTHONUTF8=1 TELEGRAM_BOT_TOKEN='8621...' "
            "ADDWII_SALES_BOT_TOKEN='8957...' "
            "ANTHROPIC_API_KEY='sk-ant-...' "
            "python tg-sales-interviewer.py"
        )
    sales_bot_token = os.environ.get("ADDWII_SALES_BOT_TOKEN")
    if not sales_bot_token:
        raise RuntimeError(
            "請設定環境變數 ADDWII_SALES_BOT_TOKEN（@addwii_sales_bot）\n"
            "Windows Git Bash 執行範例：\n"
            "  PYTHONUTF8=1 TELEGRAM_BOT_TOKEN='8621...' "
            "ADDWII_SALES_BOT_TOKEN='8957...' "
            "ANTHROPIC_API_KEY='sk-ant-...' "
            "python tg-sales-interviewer.py"
        )
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "請設定環境變數 ANTHROPIC_API_KEY\n"
            "Windows Git Bash 執行範例：\n"
            "  PYTHONUTF8=1 TELEGRAM_BOT_TOKEN='8621...' "
            "ADDWII_SALES_BOT_TOKEN='8957...' "
            "ANTHROPIC_API_KEY='sk-ant-...' "
            "python tg-sales-interviewer.py"
        )

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
        print(f"[Round {rnd}] 發送問題：{full_msg}")

        _append_to_md(
            output_path,
            f"## 第 {rnd} 輪\n\n"
            f"**[{ts}] 我的問題（發送至群組）：**\n> {full_msg}\n\n",
        )

        # ── 發出消費者問題（以 @addwii_prospect_bot 身份）─────────────────
        if not _send_tg_message(bot_token, GROUP_CHAT_ID, full_msg):
            _append_to_md(output_path, "**[錯誤] 問題訊息發送失敗，終止迴圈**\n")
            print("[main] 問題發送失敗，終止。")
            break

        # ── 生成業務回覆（Claude 本機直接呼叫）────────────────────────────
        # bot-to-bot 訊息無法觸發 VPS webhook，改由本腳本直接生成
        print(f"[Round {rnd}] 生成業務回覆中...")
        try:
            response = _generate_sales_reply(client, question)
        except RuntimeError as exc:
            ts_err = datetime.now().strftime("%H:%M:%S")
            _append_to_md(
                output_path,
                f"**[{ts_err}] addwii業務助理 回應：**\n"
                f"> （Claude API 失敗：{exc}）\n\n---\n\n",
            )
            print(f"[main] 業務回覆生成失敗：{exc}，終止。")
            break

        # ── 以 @addwii_sales_bot 身份發到群組 ────────────────────────────
        if not _send_tg_message(sales_bot_token, GROUP_CHAT_ID, response):
            # 發送失敗不中止，仍記錄回覆並繼續下一輪（群組通知是加分項，非必要）
            print("[main] @addwii_sales_bot 訊息發送失敗（仍繼續記錄回覆）")

        ts_resp = datetime.now().strftime("%H:%M:%S")
        print(f"[Round {rnd}] 收到回應：{response[:80]}...")
        _append_to_md(
            output_path,
            f"**[{ts_resp}] addwii業務助理 回應：**\n> {response}\n\n---\n\n",
        )

        # 更新 history 供下一輪跟進問題參考
        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": response})
        last_response = response

        # 輪間間隔（避免 Telegram rate limit 問題）
        if rnd < rounds:
            time.sleep(2)

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
