"""Crypto-shredding of a closed account's essay data key."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.modules.admission.ports.essay_crypto import EssayCipher
from app.shared.personal_data import PersonalTable


class EssayKeyShredder:
    """An erase source that destroys the user's essay key; it owns no tables."""

    def __init__(self, cipher: EssayCipher) -> None:
        """Keep the cipher whose key store holds the per-student keys."""
        self._cipher = cipher

    def tables(self) -> Sequence[PersonalTable]:
        """No tables: the key lives in Vault."""
        return ()

    async def export(self, user_id: UUID) -> dict[str, list[dict[str, Any]]]:
        """Nothing to export: a data key is never handed out."""
        return {}

    async def erase(self, user_id: UUID) -> int:
        """Destroy the key, which makes every sealed essay blob unreadable."""
        await self._cipher.forget(user_id)
        return 0
