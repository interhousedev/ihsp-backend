"""Photo files of users: short-lived links and clean-up (files module behind it)."""

from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from app.modules.identity.domain.user import User
from app.shared.base_error import BaseError
from app.shared.contracts.files import FilesApi

import structlog

log = structlog.get_logger(__name__)

PHOTO_URL_TTL_SECONDS = 3600


@dataclass(frozen=True, slots=True)
class PhotoUrls:
    """Presigned GET links to the photos of users."""

    files: FilesApi
    ttl_seconds: int = PHOTO_URL_TTL_SECONDS

    async def url(self, file_id: UUID | None) -> str | None:
        """The link to one photo; None when there is none or the file is gone."""
        if file_id is None:
            return None
        try:
            return await self.files.download_url(
                file_id, inline=True, ttl_seconds=self.ttl_seconds
            )
        except BaseError:
            log.warning("user_photo_unavailable", file_id=str(file_id))
            return None

    async def of_users(self, users: Iterable[User]) -> dict[UUID, str]:
        """Links by user id; users without a photo or with a lost file are left out."""
        urls: dict[UUID, str] = {}
        for user in users:
            url = await self.url(user.photo_file_id)
            if url is not None:
                urls[user.id] = url
        return urls


async def delete_photo_file(files: FilesApi, file_id: UUID) -> None:
    """Delete a photo that is not used any more; a failure is only logged.

    The row already points elsewhere (or nowhere), so the request has succeeded; a
    file left behind is harmless and is also removed with the owner's other files.
    """
    try:
        await files.delete_file(file_id)
    except Exception:  # the user's change is committed; never fail the request
        log.warning("user_photo_cleanup_failed", file_id=str(file_id), exc_info=True)
