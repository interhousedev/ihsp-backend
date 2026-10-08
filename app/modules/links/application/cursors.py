"""Opaque cursors for link lists."""

from datetime import datetime
from uuid import UUID

from app.modules.links.ports.link_repository import ModerationCursor
from app.shared.base_error import ValidationFailedError
from app.shared.pagination import decode_cursor, encode_cursor


def encode_id_cursor(link_id: UUID) -> str:
    """Cursor after the given link (ids are time-ordered UUIDv7)."""
    return encode_cursor({"id": str(link_id)})


def decode_id_cursor(cursor: str | None) -> UUID | None:
    """Return the link id inside a cursor, or None for the first page."""
    try:
        data = decode_cursor(cursor)
        return UUID(data["id"]) if data else None
    except (ValueError, KeyError, TypeError) as error:
        raise ValidationFailedError(support_details="bad cursor") from error


def encode_moderation_cursor(cursor: ModerationCursor) -> str:
    """Cursor after an item of the moderation queue."""
    return encode_cursor(
        {
            "r": cursor.reports,
            "t": cursor.last_reported_at.isoformat(),
            "i": str(cursor.link_id),
        }
    )


def decode_moderation_cursor(cursor: str | None) -> ModerationCursor | None:
    """Return the queue position inside a cursor, or None for the first page."""
    try:
        data = decode_cursor(cursor)
        if not data:
            return None
        return ModerationCursor(
            reports=int(data["r"]),
            last_reported_at=datetime.fromisoformat(data["t"]),
            link_id=UUID(data["i"]),
        )
    except (ValueError, KeyError, TypeError) as error:
        raise ValidationFailedError(support_details="bad cursor") from error
