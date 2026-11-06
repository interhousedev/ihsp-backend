"""An offer of the MCP scopes of one release to one user (A7)."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from app.shared.ids import hash_token, random_token

OFFER_TTL = timedelta(days=14)
OFFER_TOKEN_BYTES = 16  # 128 bits, 22 characters: fits the 64 bytes of callback data
OFFER_STATUS_PENDING = "pending"
OFFER_STATUS_GRANTED = "granted"
OFFER_STATUS_DECLINED = "declined"
OFFER_STATUS_EXPIRED = "expired"


@dataclass(slots=True)
class ScopeOffer:
    """What was offered and the keys it applies to; the token is kept hashed."""

    id: UUID
    user_id: UUID
    release_id: str
    scopes: list[str]
    connector_ids: list[UUID]
    status: str
    token_hash: str
    expires_at: datetime
    decided_at: datetime | None = None
    created_at: datetime | None = field(default=None)


class DecideResult(StrEnum):
    """How a press of an offer's button ended."""

    GRANTED = "granted"
    DECLINED = "declined"
    ALREADY_DECIDED = "already_decided"
    EXPIRED = "expired"
    NOT_AVAILABLE = "not_available"


@dataclass(frozen=True, slots=True)
class ScopeDecision:
    """The result and the names of the keys that were widened."""

    result: DecideResult
    connector_names: tuple[str, ...] = ()


def new_offer_token() -> tuple[str, str]:
    """Return (token, hash) for a fresh offer."""
    token = random_token(OFFER_TOKEN_BYTES)
    return token, hash_offer_token(token)


def hash_offer_token(token: str) -> str:
    """The stored form of a token."""
    return hash_token(token)
