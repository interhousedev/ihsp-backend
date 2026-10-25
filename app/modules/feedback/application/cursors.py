"""Opaque keyset cursors of the administrators' feedback list."""

import base64
from datetime import datetime
from uuid import UUID

from app.modules.feedback.domain.errors import FeedbackInvalidError
from app.modules.feedback.ports.feedback_repository import PageAfter


def encode_cursor(after: PageAfter) -> str:
    """URL-safe base64 of ``<iso created_at>|<id>``."""
    raw = f"{after.created_at.isoformat()}|{after.id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str | None) -> PageAfter | None:
    """Parse a cursor; a broken one raises FeedbackInvalidError(field=cursor)."""
    if not cursor:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        moment, ident = base64.urlsafe_b64decode(padded).decode().split("|")
        return PageAfter(created_at=datetime.fromisoformat(moment), id=UUID(ident))
    except ValueError as exc:  # binascii.Error and UnicodeDecodeError included
        raise FeedbackInvalidError(params={"field": "cursor"}) from exc
