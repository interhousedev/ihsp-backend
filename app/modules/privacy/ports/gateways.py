"""Ports to other modules' data: the user's own uploaded files."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class OwnedFile:
    """An uploaded file of the user."""

    key: str
    name: str
    byte_size: int


class OwnedFiles(Protocol):
    """The files a user uploaded (ready ones)."""

    async def list_of(self, user_id: UUID) -> Sequence[OwnedFile]:
        """The user's files, oldest first."""
        ...
