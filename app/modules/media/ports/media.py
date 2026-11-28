"""Ports of the media module."""

from typing import Any, Protocol
from uuid import UUID

from app.modules.media.domain.media_job import MediaJob
from app.modules.media.domain.narration import Segment
from app.shared.actor import Actor


class StaleMediaJobError(Exception):
    """Another worker saved the job first (optimistic version mismatch)."""


class MediaJobStore(Protocol):
    """Persistence of media jobs."""

    async def add(self, job: MediaJob) -> None:
        """Insert a new job."""
        ...

    async def get(self, job_id: UUID) -> MediaJob | None:
        """The job or None."""
        ...

    async def save(self, job: MediaJob) -> None:
        """Save with the optimistic `version`; raises StaleMediaJobError on a clash."""
        ...

    async def list_by_owner(
        self, owner_id: UUID, *, limit: int, offset: int
    ) -> tuple[list[MediaJob], int]:
        """The owner's jobs, newest first, and the total count."""
        ...

    async def find_done(self, owner_id: UUID, script_hash: str) -> list[MediaJob]:
        """DONE jobs of the owner with this content hash (any destination)."""
        ...


class MediaFiles(Protocol):
    """Stores result files (private to the owner)."""

    async def put(
        self, *, owner_id: UUID, name: str, content: bytes, mime: str
    ) -> UUID:
        """Store the bytes and return the file id."""
        ...


class VideoRenderer(Protocol):
    """Renders the aligned script and the voice track to an mp4."""

    async def render(
        self,
        *,
        composition_hash: str,
        fmt: str,
        length_s: int,
        segments: tuple[Segment, ...],
        audio: bytes | None = None,
    ) -> bytes:
        """The mp4 bytes."""
        ...


class OwnerAccess(Protocol):
    """Revalidates the owner's right to the destination before a paid step."""

    async def actor_for(
        self, owner_id: UUID, subject_id: UUID, group_id: UUID | None
    ) -> Actor | None:
        """The owner as an actor, or None when the role or assignment is gone."""
        ...


class MediaKicker(Protocol):
    """Starts a media task on a queue."""

    async def kick(self, task: str, *args: Any, queue: str = "default") -> None:
        """Enqueue the task."""
        ...


class MediaLimits(Protocol):
    """Weekly media allowance."""

    media_jobs_per_week: int

    async def used_this_week(self, owner_id: UUID) -> int:
        """Jobs the owner started in the last 7 days."""
        ...
