"""Port: storage of Studio outputs and the student's progress in them."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.notebooks.domain.entities import Artifact, ArtifactProgress
from app.modules.notebooks.domain.enums import ArtifactKind, ArtifactStatus


class ArtifactRepository(Protocol):
    """Outputs in `notebooks.artifacts`."""

    async def add(self, artifact: Artifact) -> None:
        """Insert a new output."""
        ...

    async def get(self, artifact_id: UUID) -> Artifact | None:
        """Return the output (soft-deleted ones too)."""
        ...

    async def get_for_update(self, artifact_id: UUID) -> Artifact | None:
        """Return the output and lock its row until the transaction ends."""
        ...

    async def save(self, artifact: Artifact) -> None:
        """Write the output's stored fields."""
        ...

    async def list_for_notebook(
        self,
        notebook_id: UUID,
        *,
        kind: ArtifactKind | None,
        status: ArtifactStatus | None,
    ) -> list[Artifact]:
        """Non-deleted outputs, newest first, without content."""
        ...

    async def count_live(self, notebook_id: UUID) -> int:
        """How many non-deleted outputs the notebook holds."""
        ...

    async def stuck_generating(
        self, started_before: datetime, limit: int
    ) -> list[Artifact]:
        """Outputs in `generating` that started before the cutoff."""
        ...

    async def stuck_queued(
        self, updated_before: datetime, limit: int
    ) -> list[Artifact]:
        """Outputs still `queued` that were not updated since the cutoff."""
        ...


class ProgressRepository(Protocol):
    """Progress in `notebooks.artifact_progress`."""

    async def get(self, artifact_id: UUID, user_id: UUID) -> ArtifactProgress | None:
        """Return the student's progress."""
        ...

    async def upsert(self, progress: ArtifactProgress) -> None:
        """Insert or replace the state."""
        ...

    async def delete_for_user(self, user_id: UUID) -> None:
        """Forget the user's progress everywhere (the account is deleted)."""
        ...
