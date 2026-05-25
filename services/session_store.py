"""session_store.py — in-memory Telegram 對話 session 管理

維護 chat_id → QuestionSession 映射。
session 超過 SESSION_TIMEOUT_SECONDS 無互動自動過期。

設計說明：
- 刻意選用 in-memory，不依賴 Redis/DB（單執行緒 uvicorn 夠用，重啟 session 自然消失符合預期）
- 全域單例 store 供 main.py import 使用，不透過 DI 注入（YAGNI 原則）
- 未來若需多進程，只需把 _store 替換成 Redis client，介面不變
"""
import time
from dataclasses import dataclass, field

SESSION_TIMEOUT_SECONDS: int = 600  # 10 分鐘無互動自動重設 session


@dataclass
class QuestionSession:
    """消費者問題一問一答 session 狀態。

    phase:
        "idle"   — 無進行中 session（預設狀態）
        "asking" — 正在問題流程中，逐題傳送並等待使用者回應

    questions: 已生成的問題清單（Claude 一次生成全部，逐一傳送，省 API 呼叫次數）
    current_idx: 目前問到第幾題（0-based；等於 len(questions) 代表問完）
    last_active: 最後活動的 unix timestamp，用於判斷 session 是否超時
    """

    phase: str = "idle"
    questions: list[str] = field(default_factory=list)
    current_idx: int = 0
    last_active: float = field(default_factory=time.time)

    @property
    def current_question(self) -> str:
        """回傳目前該問的問題文字，若無待問問題則回空字串。"""
        if self.current_idx < len(self.questions):
            return self.questions[self.current_idx]
        return ""

    @property
    def is_done(self) -> bool:
        """所有問題都已問完（current_idx 已超出 questions 範圍）。"""
        return self.current_idx >= len(self.questions)


class SessionStore:
    """thread-unsafe in-memory store。

    設計為單執行緒 uvicorn 使用，無需 lock。
    若未來改多 worker，需在 get/set/clear 加 asyncio.Lock 或改用 Redis。
    """

    def __init__(self) -> None:
        self._store: dict[str, QuestionSession] = {}

    def _key(self, chat_id: int | str) -> str:
        """統一以字串作為 dict key，避免 int/str chat_id 混用造成查無結果。"""
        return str(chat_id)

    def get(self, chat_id: int | str) -> QuestionSession:
        """取得 session。若不存在或已過期，清除舊記錄並回傳全新 idle session。

        過期 session 在此時惰性清除（lazy eviction），避免額外的定時清理任務。
        """
        key = self._key(chat_id)
        session = self._store.get(key)
        if session is None:
            return QuestionSession()
        if self._is_expired(session):
            # 過期 session 惰性清除，下次查詢時才刪除，節省一次主動掃描
            del self._store[key]
            return QuestionSession()
        return session

    def set(self, chat_id: int | str, session: QuestionSession) -> None:
        """存入 session，同時刷新 last_active（記錄最後互動時間以供過期判斷）。"""
        session.last_active = time.time()
        self._store[self._key(chat_id)] = session

    def clear(self, chat_id: int | str) -> None:
        """清除 session，使 chat_id 回到 idle 狀態（問題流程結束或使用者主動取消）。"""
        self._store.pop(self._key(chat_id), None)

    def _is_expired(self, session: QuestionSession) -> bool:
        """判斷 session 是否超過 SESSION_TIMEOUT_SECONDS 未活動。"""
        return (time.time() - session.last_active) > SESSION_TIMEOUT_SECONDS


# 全域單例，供 main.py 直接 import 使用
store = SessionStore()


if __name__ == "__main__":
    # 冒煙測試：只測 SessionStore 純邏輯（不依賴外部服務）
    print("=== SessionStore 冒煙測試 ===")

    s = SessionStore()

    # 案例 1（happy path）：get 不存在的 key → idle session，set 後可取回
    session = s.get(12345)
    assert session.phase == "idle", "新 session 應為 idle"
    assert session.is_done is True, "空問題列表的 is_done 應為 True"
    assert session.current_question == "", "空問題列表的 current_question 應為空字串"
    print("案例 1 通過：新 session 狀態正確")

    # 存入進行中 session
    session.phase = "asking"
    session.questions = ["問題A", "問題B", "問題C"]
    session.current_idx = 0
    s.set(12345, session)

    # 取回應保留 phase 和 questions
    session2 = s.get(12345)
    assert session2.phase == "asking", "取回 session 應為 asking"
    assert session2.current_question == "問題A", "current_question 應為第一題"
    assert session2.is_done is False, "尚有問題時 is_done 應為 False"
    print("案例 2 通過：set/get 資料完整性正確")

    # 案例 3（edge case）：clear 後 get 應回全新 idle session
    s.clear(12345)
    session3 = s.get(12345)
    assert session3.phase == "idle", "clear 後應回 idle session"
    print("案例 3 通過：clear 後 session 重置正確")

    # 案例 4（edge case）：模擬過期（手動設 last_active 超出 timeout）
    session4 = QuestionSession(phase="asking", questions=["Q1"])
    session4.last_active = time.time() - SESSION_TIMEOUT_SECONDS - 1  # 強制過期
    s._store["99999"] = session4  # 直接注入繞過 set 的 last_active 刷新
    retrieved = s.get("99999")
    assert retrieved.phase == "idle", "過期 session 應被清除並回傳 idle"
    assert "99999" not in s._store, "過期 session 應從 store 中移除"
    print("案例 4 通過：過期 session 惰性清除正確")

    print("\n所有冒煙測試通過")
