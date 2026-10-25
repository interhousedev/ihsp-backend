"""Paging of extracted text for the assistant: pages of up to 8 KB of UTF-8."""

from app.modules.files.domain.errors import TextPageNotFoundError

PAGE_BYTES = 8192
_WHITESPACE = (b" ", b"\n", b"\t", b"\r")
_CONTINUATION_MASK = 0xC0
_CONTINUATION = 0x80


def _char_boundary(data: bytes, cut: int, floor: int) -> int:
    """Move ``cut`` back to the start of a UTF-8 character (never below floor)."""
    while cut > floor and data[cut] & _CONTINUATION_MASK == _CONTINUATION:
        cut -= 1
    return cut


def _last_whitespace(data: bytes, start: int, end: int) -> int:
    """Return the index of the last whitespace byte in data[start:end], or -1."""
    return max(data.rfind(ws, start, end) for ws in _WHITESPACE)


def _next_cut(data: bytes, pos: int, limit: int) -> int:
    """Return the end of the page that starts at ``pos``."""
    end = pos + limit
    if end >= len(data):
        return len(data)
    end = _char_boundary(data, end, pos + 1)
    space = _last_whitespace(data, pos, end)
    return space + 1 if space > pos else end


def split_pages(text: str, limit: int = PAGE_BYTES) -> list[str]:
    """Split text into pages of at most ``limit`` UTF-8 bytes.

    A page ends after the last whitespace before the limit; a page without any
    whitespace is cut at a character boundary. Joining the pages gives the text.
    """
    data = text.encode()
    if not data:
        return [""]
    pages: list[str] = []
    pos = 0
    while pos < len(data):
        cut = _next_cut(data, pos, limit)
        pages.append(data[pos:cut].decode())
        pos = cut
    return pages


def get_page(pages: list[str], page: int) -> str:
    """Return the 1-based page or raise TextPageNotFoundError."""
    if page < 1 or page > len(pages):
        raise TextPageNotFoundError(params={"page": page, "pages": len(pages)})
    return pages[page - 1]
