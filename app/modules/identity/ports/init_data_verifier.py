"""Port: Telegram mini app initData verification."""

from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol


@dataclass(frozen=True, slots=True)
class InitDataUser:
    """The Telegram user named by verified initData."""

    id: int
    first_name: str
    last_name: str | None = None
    username: str | None = None
    language_code: str | None = None


class InitDataVerifier(Protocol):
    """Checks the HMAC signature and freshness of initData."""

    def verify(self, raw: str, *, max_age: timedelta) -> InitDataUser:
        """Return the user; raise UnauthorizedError for bad or old data."""
        ...
