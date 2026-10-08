"""Port: revoke everything a user holds (used by reclaim and deletion, B2)."""

from typing import Protocol
from uuid import UUID


class AccountRevoker(Protocol):
    """Logs a user out everywhere."""

    async def revoke_everything(
        self, user_id: UUID, *, keep_telegram: bool = False
    ) -> None:
        """Bump the epoch; revoke Hydra sessions, sessions and connectors.

        Telegram links are deleted unless ``keep_telegram``.
        """
        ...
