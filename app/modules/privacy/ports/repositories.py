"""Ports: storage of erasure requests and exports."""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.privacy.domain.models import ErasureRequest, ErasureStatus, ExportJob


class ErasureRepository(Protocol):
    """Erasure requests."""

    async def add(self, request: ErasureRequest) -> None:
        """Insert a request."""
        ...

    async def get(self, request_id: UUID) -> ErasureRequest | None:
        """Return the request or None."""
        ...

    async def get_open(self, user_id: UUID) -> ErasureRequest | None:
        """The user's request in ``pending_review`` or ``approved``, newest first."""
        ...

    async def list(
        self, status: ErasureStatus | None, *, limit: int, offset: int
    ) -> Sequence[ErasureRequest]:
        """Requests newest first, optionally of one status."""
        ...

    async def save(self, request: ErasureRequest) -> None:
        """Write changes."""
        ...


class ExportRepository(Protocol):
    """Exports."""

    async def add(self, job: ExportJob) -> None:
        """Insert an export."""
        ...

    async def get(self, export_id: UUID) -> ExportJob | None:
        """Return the export or None."""
        ...

    async def latest_of(self, user_id: UUID) -> ExportJob | None:
        """The user's newest export that did not fail."""
        ...

    async def list_of(self, user_id: UUID, *, limit: int) -> Sequence[ExportJob]:
        """The user's exports, newest first."""
        ...

    async def expired(self, now: datetime, *, limit: int) -> Sequence[ExportJob]:
        """Exports with a stored archive whose ``expires_at`` has passed."""
        ...

    async def save(self, job: ExportJob) -> None:
        """Write changes."""
        ...
