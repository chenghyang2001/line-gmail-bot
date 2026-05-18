"""pdf_parser.py — PDF bytes 轉純文字，限制頁數與字數避免吃掉過多 Claude token"""
from io import BytesIO

_MAX_PAGES: int = 5
_MAX_CHARS_PER_PAGE: int = 2000


def extract_text_from_bytes(pdf_bytes: bytes) -> str:
    """從 PDF bytes 擷取純文字（pypdf），失敗時 graceful 回傳空字串"""
    if not pdf_bytes:
        return ""

    try:
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(pdf_bytes))
        pages_text: list[str] = []

        for i, page in enumerate(reader.pages):
            if i >= _MAX_PAGES:
                break
            try:
                text: str = page.extract_text() or ""
                # 每頁截斷，避免大型 PDF 把 Claude prompt 撐爆
                pages_text.append(text[:_MAX_CHARS_PER_PAGE])
            except Exception as page_exc:
                # 單頁解析失敗不中斷整份 PDF
                print(f"[pdf_parser] 第 {i + 1} 頁解析失敗：{page_exc}")
                continue

        return "\n\n".join(pages_text).strip()

    except ImportError:
        print("[pdf_parser] pypdf 未安裝，無法解析 PDF")
        return ""
    except Exception as exc:
        # 任何 pypdf 例外都 graceful 降級，不讓主流程崩
        print(f"[pdf_parser] PDF 解析失敗：{exc}")
        return ""
