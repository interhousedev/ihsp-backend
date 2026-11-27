"""HMAC-signed, event-bound QR check-in tokens."""

import hashlib
import hmac
from datetime import UTC, datetime
from uuid import UUID

from app.modules.activities.domain.errors import BadRequest
from app.modules.activities.domain.event import Event, check_in_window

__all__ = ["InvalidCheckInTokenError", "issue_token", "peek_event_id", "verify_token"]


class InvalidCheckInTokenError(BadRequest):
    """The token is tampered, expired or for another event."""


def _sign(secret: str, event_id: UUID, expires: int) -> str:
    msg = f"{event_id}.{expires}".encode()
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def issue_token(event: Event, secret: str, now: datetime) -> str:
    """A token that works until the check-in window closes."""
    expires = int(check_in_window(event)[1].timestamp())
    return f"{event.id}.{expires}.{_sign(secret, event.id, expires)}"


def _parse(token: str) -> tuple[UUID, int, str]:
    try:
        raw_id, raw_exp, sig = token.split(".")
        return UUID(raw_id), int(raw_exp), sig
    except ValueError as exc:
        raise InvalidCheckInTokenError() from exc


def peek_event_id(token: str) -> UUID:
    """The event a token claims; the signature is still unchecked."""
    return _parse(token)[0]


def verify_token(token: str, event_id: UUID, secret: str, now: datetime) -> UUID:
    """Return the event id or raise `InvalidCheckInTokenError`."""
    tok_event, expires, sig = _parse(token)
    good = hmac.compare_digest(sig, _sign(secret, tok_event, expires))
    if not good or tok_event != event_id or now.astimezone(UTC).timestamp() > expires:
        raise InvalidCheckInTokenError()
    return tok_event
