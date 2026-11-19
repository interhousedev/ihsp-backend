"""Photo files of users: short-lived links and clean-up (files module behind it)."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from app.modules.identity.domain.user import User
from app.shared.base_error import BaseError
from app.shared.contracts.files import FilesApi

import structlog

log = structlog.get_logger(__name__)

PHOTO_URL_TTL_SECONDS = 3600
FACE_PHOTO_STEM = "face"


PhotoSourceName = Literal["upload", "face"]


@dataclass(frozen=True, slots=True)
class PhotoUrls:
    """Presigned GET links to the photos of users."""

    files: FilesApi
    ttl_seconds: int = PHOTO_URL_TTL_SECONDS

    async def source(self, file_id: UUID | None) -> PhotoSourceName | None:
        """Say whether the photo is an upload or a copy of the face (named `face.*`)."""
        if file_id is None:
            return None
        ref = await self.files.get(file_id)
        if ref is None:
            return None
        if ref.name.startswith(f"{FACE_PHOTO_STEM}."):
            return "face"
        return "upload"

    async def url(
        self, file_id: UUID | None, ttl_seconds: int | None = None
    ) -> str | None:
        """The link to one photo; None when there is none or the file is gone."""
        if file_id is None:
            return None
        try:
            return await self.files.download_url(
                file_id,
                inline=True,
                ttl_seconds=self.ttl_seconds if ttl_seconds is None else ttl_seconds,
            )
        except BaseError:
            log.warning("user_photo_unavailable", file_id=str(file_id))
            return None

    async def of_users(
        self, users: Iterable[User], ttl_seconds: int | None = None
    ) -> dict[UUID, str]:
        """Links by user id; users without a photo or with a lost file are left out."""
        urls: dict[UUID, str] = {}
        for user in users:
            url = await self.url(user.photo_file_id, ttl_seconds)
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
