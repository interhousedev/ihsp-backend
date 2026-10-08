"""Presigned download URLs (FILE-3): valid 60 seconds, PDF and images inline."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.modules.files.domain.errors import FileDeletedError, FileNotReadyError
from app.modules.files.domain.policy import PRESIGN_GET_SECONDS, inline_allowed
from app.modules.files.domain.status import FileStatus
from app.modules.files.domain.stored_file import StoredFile
from app.modules.files.ports.storage import ObjectStorage
from app.shared.clock import Clock

_DOWNLOADABLE = frozenset({FileStatus.PROCESSING, FileStatus.READY})


@dataclass(frozen=True, slots=True)
class DownloadUrl:
    """A short-lived URL and the moment it stops working."""

    url: str
    expires_at: datetime


class DownloadLinks:
    """Creates presigned GET URLs for files that passed the upload checks."""

    def __init__(self, storage: ObjectStorage, clock: Clock) -> None:
        """Store the storage and the clock."""
        self._storage = storage
        self._clock = clock

    async def url_for(self, file: StoredFile, *, inline: bool | None) -> DownloadUrl:
        """Return a download URL; ``inline`` None means as inline as allowed."""
        if file.status == FileStatus.DELETED:
            raise FileDeletedError()
        if file.status not in _DOWNLOADABLE:
            raise FileNotReadyError(params={"status": file.status.value})
        wanted = True if inline is None else inline
        url = await self._storage.presign_get(
            file.key,
            filename=file.name,
            inline=wanted and inline_allowed(file.content_type),
            content_type=file.content_type,
            expires=PRESIGN_GET_SECONDS,
        )
        expires_at = self._clock.now() + timedelta(seconds=PRESIGN_GET_SECONDS)
        return DownloadUrl(url=url, expires_at=expires_at)
