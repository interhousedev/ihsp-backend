"""Cursor pagination."""

import base64
import json
from typing import Any, Generic, TypeVar

from app.shared.base_error import ValidationFailedError

from pydantic import BaseModel

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """A page of items with an opaque cursor for the next page."""

    items: list[T]
    next_cursor: str | None = None


def encode_cursor(data: dict[str, Any]) -> str:
    """Encode cursor data as URL-safe base64 JSON."""
    raw = json.dumps(data, separators=(",", ":"), default=str).encode()
    return base64.urlsafe_b64encode(raw).decode()


def decode_cursor(cursor: str | None) -> dict[str, Any] | None:
    """Decode a cursor; None for the first page; a broken cursor is a 422."""
    if not cursor:
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor.encode()))
    except ValueError as exc:
        raise _bad_cursor() from exc
    if not isinstance(data, dict):
        raise _bad_cursor()
    return data


def _bad_cursor() -> ValidationFailedError:
    return ValidationFailedError(
        params={"field": "cursor"}, support_details="malformed cursor"
    )
