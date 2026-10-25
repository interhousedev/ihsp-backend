"""Offset cursors of the catalogue lists (`?cursor=` is opaque to clients)."""

from app.shared.pagination import decode_cursor, encode_cursor


def read_offset(cursor: str | None) -> int:
    """Where the page starts; 0 for the first page, a 422 for a broken cursor."""
    data = decode_cursor(cursor)
    if data is None:
        return 0
    offset = data.get("o")
    return offset if isinstance(offset, int) and offset >= 0 else 0


def next_cursor(offset: int, taken: int, has_more: bool) -> str | None:
    """The cursor of the page after `taken` rows from `offset`, or None at the end."""
    return encode_cursor({"o": offset + taken}) if has_more else None
