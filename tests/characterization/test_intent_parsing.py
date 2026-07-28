"""特徵測試（Characterization Test）— main.py 意圖解析三函式

⚠️ 這個檔案鎖住的是「現況」，不是「期望」。

一般單元測試驗證程式「應該」做什麼；特徵測試相反 —— 它把遺留系統
「現在實際」做什麼原封不動記錄下來，**包含意外行為與 bug 在內**。
目的是：在動一個看不懂的遺留系統之前，先讓它的既有行為變得
「可被偵測到改變」——任何非預期的行為漂移都會讓這裡的測試變紅。

因此，看到不合理的斷言時請**不要**「順手修正」。若確認某個行為該改，
正確流程是先改行為、再明確更新本檔的斷言，讓 diff 留下痕跡。

方法論定位：RECLAIM 方法論 C 階段（Characterize，特徵化）。
出處：Kindle 37《Spec-Driven Development for Legacy Code》演練產出。

待測目標（皆為 main.py 內的純函式，無外部 I/O）：
- main._is_meaningful_input  (main.py:42-55)
- main._is_generate_question (main.py:58-73)
- main._extract_count        (main.py:80-104)

執行方式（於專案根目錄）：
    python -m pytest tests/characterization/ -v
"""
import sys
from pathlib import Path

import pytest

# 本測試檔位於 <root>/tests/characterization/，而 main.py 在 <root>/。
# pytest 的 rootdir 自動插入只保證測試檔所在目錄，不含專案根目錄，
# 故手動把根目錄推到 sys.path 最前面，讓 `import main` 能成立。
# 用 __file__ 相對推導而非絕對路徑，確保跨機器（家用機／公司機）可攜。
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import main  # noqa: E402  — 必須等 sys.path 調整完才能 import


# ---------------------------------------------------------------------------
# 1. _is_meaningful_input — 過短／純標點輸入的攔截現況
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text, expected",
    [
        ("addwii 有什麼優惠", True),   # 正常長句
        ("優惠", True),                # 剛好 2 字元，通過門檻
        ("好", False),                 # 1 字元，len(strip()) < 2 被擋
        ("", False),                   # 空字串
        ("  a  ", False),              # strip 後只剩 1 字元
        ("？？？", False),             # 純標點，無任何 isalnum 字元
        ("!!", False),                 # 純符號
    ],
)
def test_鎖住_過短或純標點輸入被判為無意義(text: str, expected: bool) -> None:
    """現況：strip 後長度 < 2 或完全不含 isalnum 字元 → False，其餘 True。"""
    assert main._is_meaningful_input(text) is expected


def test_鎖住_中文不會被isalnum誤擋() -> None:
    """現況：str.isalnum() 對 CJK 文字回 True，所以純中文輸入判為有意義。

    這一條是「語言相依的實作細節」——若未來把判斷改成 ASCII-only 的
    正規表達式（例如 [A-Za-z0-9]），中文輸入會全部被誤擋，此測試會抓到。
    """
    assert main._is_meaningful_input("優惠") is True
    assert main._is_meaningful_input("消費者問題") is True


# ---------------------------------------------------------------------------
# 2. _extract_count — 數量解析現況（含本次演練的核心「意外行為」）
# ---------------------------------------------------------------------------

def test_鎖住_中文數字依dict迭代順序取第一個命中而非文意上的數字() -> None:
    """🔴 意外行為（本檔核心示範）：「產生兩三個問題」回 2，不是 3。

    現況成因（非刻意設計，是實作細節洩漏）：
    找不到阿拉伯數字時，`_extract_count` 會用
    `for ch, val in _ZH_NUM.items()` 依序掃描中文數字表，
    而 `_ZH_NUM = {"一":1, "兩":2, "二":2, "三":3, "四":4, "五":5}`
    中「兩」排在「三」前面，所以只要文字同時含這兩個字，
    永遠是先命中的「兩」勝出 → 回傳 2。

    也就是說：回傳值取決於 **dict 的字面宣告順序**（Python 3.7+ 保證
    插入順序），而不是這些字在使用者訊息裡出現的位置或語意。
    口語上「兩三個」通常是概數，人類多半理解成 2~3 個，
    程式卻硬取 2 —— 這既沒人設計過，也沒人驗證過。

    這裡刻意**不修正**它，而是把它鎖住。若未來有人重排 `_ZH_NUM`
    的鍵順序（例如改成由大到小、或改用 sorted），此測試會失敗並提醒他：
    「你改變了一個現有行為，請確認這是有意為之。」
    """
    assert main._extract_count("產生兩三個問題") == 2


@pytest.mark.parametrize(
    "text, expected",
    [
        ("產生 3 個消費者問題", 3),   # 阿拉伯數字，範圍內原樣回傳
        ("產生 10 個問題", 5),        # 超過上限 → min(5, n) clamp 到 5
        ("產生 0 個問題", 1),         # 低於下限 → max(1, n) clamp 到 1
        ("提出兩個問題", 2),          # 無阿拉伯數字 → fallback 中文數字表
        ("提出五個問題", 5),
        ("產生消費者問題", 1),        # 完全找不到數字 → 預設 1
    ],
)
def test_鎖住_數量解析與上下限clamp現況(text: str, expected: int) -> None:
    """現況：阿拉伯數字優先且 clamp 到 [1, 5]，其次中文數字表，都沒有則回 1。"""
    assert main._extract_count(text) == expected


def test_鎖住_阿拉伯數字優先於中文數字() -> None:
    """現況：正規表達式先跑，只要有任何阿拉伯數字就不會走中文數字 fallback。

    「產生 4 個問題但不要三個」中的「三」被完全忽略，因為 re.search 已先命中 4。
    """
    assert main._extract_count("產生 4 個問題但不要三個") == 4


def test_鎖住_只取第一個出現的阿拉伯數字() -> None:
    """現況：`re.search(r'(\\d+)', text)` 只抓**第一個**數字，後面的一律忽略。

    因此「產生 2 個問題給 3 位使用者」回 2，而非 3 或 5。
    """
    assert main._extract_count("產生 2 個問題給 3 位使用者") == 2


def test_鎖住_不支援複合中文數字() -> None:
    """現況：「二十」被拆看成含「二」→ 回 2，而非 20（再 clamp 成 5）。

    _ZH_NUM 只有單字鍵，沒有任何複合數字解析邏輯。
    這是已知限制（main.py docstring 有寫），照現況鎖住。
    """
    assert main._extract_count("產生二十個問題") == 2


# ---------------------------------------------------------------------------
# 3. _is_generate_question — 三條件 AND 的指令判斷現況
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text, expected",
    [
        ("幫我產生 3 個消費者問題", True),          # 動作+目標+對象 三者齊全
        ("提出 addwii 使用者會問的問題", True),
        ("列出使用者的問題", True),
        ("生成消費者問題", True),
        ("addwii 有什麼優惠", False),               # 缺動作詞、缺目標詞
        ("產生報告", False),                        # 缺目標詞、缺對象詞
        ("消費者問題", False),                      # 缺動作詞
        ("產生消費者清單", False),                  # 缺目標詞「問題」
        ("產生 3 個問題", False),                   # 缺對象詞
    ],
)
def test_鎖住_三條件必須同時成立才判為產生問題指令(text: str, expected: bool) -> None:
    """現況：動作詞 and 目標詞 and 對象詞，三者缺一即 False。"""
    assert main._is_generate_question(text) is expected


def test_鎖住_對象詞addwii大小寫不敏感但中文詞無此效果() -> None:
    """現況：比對前有 `text.strip().lower()`，所以 ADDWII / Addwii 都能命中。

    值得注意的不對稱：lower() 只對 ASCII 有意義，中文對象詞（消費者／使用者）
    根本沒有大小寫概念 —— 這個 normalize 實際上只服務 "addwii" 一個詞。
    """
    assert main._is_generate_question("產生 ADDWII 的問題") is True
    assert main._is_generate_question("  產生 Addwii 的問題  ") is True


def test_鎖住_子字串比對會誤判包含關鍵字的無關句子() -> None:
    """現況：全部用 `in` 子字串比對，沒有斷詞，所以語意上不相干的句子也可能觸發。

    「這個產生問題的使用者體驗很差」語意上是在抱怨 UX，不是要求產生問題，
    但因為同時含「產生」「問題」「使用者」三個子字串 → 被判為 True。
    這是子字串比對的固有誤判，非刻意設計，照現況鎖住。
    """
    assert main._is_generate_question("這個產生問題的使用者體驗很差") is True
