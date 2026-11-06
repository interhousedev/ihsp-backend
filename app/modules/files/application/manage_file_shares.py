"""Use case: share a file by link or with named people (FILE-SHARE).

The owner's routes (`/v1/files/{id}...`) stay closed to recipients: they read only
through the routes here, so a grant cannot rename, delete or list anything.
"""

from dataclasses import dataclass
from uuid import UUID

from app.modules.files.application.access import require_owner_editable
from app.modules.files.application.download_links import DownloadLinks, DownloadUrl
from app.modules.files.domain.errors import (
    FileShareLimitError,
    FileShareSelfError,
    StoredFileNotFoundError,
)
from app.modules.files.domain.sharing import (
    MAX_FILE_SHARES,
    FileShare,
    FileShareVia,
    hash_token,
    new_token,
)
from app.modules.files.domain.status import FileStatus
from app.modules.files.domain.stored_file import StoredFile
from app.modules.files.ports.unit_of_work import FilesUnitOfWork, UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.contracts.files import FileScope
from app.shared.rate_limit import RateLimiter

JOIN_PER_MINUTE = 10
WINDOW_SECONDS = 60
_SHAREABLE_SCOPES = frozenset({FileScope.STUDENT, FileScope.STAFF})


@dataclass(frozen=True, slots=True)
class FileShareState:
    """Whether a link works and who has access."""

    link_active: bool
    people: list[FileShare]


def _open(file: StoredFile | None) -> bool:
    """A grant lasts only as long as the file is a ready personal file."""
    return (
        file is not None
        and file.status == FileStatus.READY
        and file.scope in _SHAREABLE_SCOPES
    )


class ManageFileShares:
    """Reads and changes who may download a file; every change works at once."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        clock: Clock,
        links: DownloadLinks,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        """Store the collaborators (no limiter: joining is not rate limited)."""
        self._uow_factory = uow_factory
        self._clock = clock
        self._links = links
        self._rate_limiter = rate_limiter

    async def _owned(
        self, uow: FilesUnitOfWork, actor: Actor, file_id: UUID
    ) -> StoredFile:
        return require_owner_editable(await uow.files.get(file_id), actor)

    async def state(self, actor: Actor, file_id: UUID) -> FileShareState:
        """Return the link state and the people with access (the owner only)."""
        async with self._uow_factory() as uow:
            await self._owned(uow, actor, file_id)
            return FileShareState(
                await uow.shares.link_exists(file_id),
                await uow.shares.list_active(file_id),
            )

    async def create_link(self, actor: Actor, file_id: UUID) -> str:
        """Create the link or replace its token; the token is shown this once."""
        token = new_token()
        async with self._uow_factory() as uow:
            await self._owned(uow, actor, file_id)
            await uow.shares.set_link(file_id, hash_token(token), self._clock.now())
            await uow.commit()
        return token

    async def delete_link(self, actor: Actor, file_id: UUID) -> None:
        """Turn the link off and remove the people who joined through it."""
        async with self._uow_factory() as uow:
            await self._owned(uow, actor, file_id)
            await uow.shares.delete_link(file_id)
            await uow.shares.delete_via(file_id, FileShareVia.LINK)
            await uow.commit()

    async def add_person(self, actor: Actor, file_id: UUID, user_id: UUID) -> None:
        """Give a person access (the HTTP edge checks that the account is active).

        Raises:
            FileShareSelfError: The owner shares with themselves.
            FileShareLimitError: The file already has 50 people.
        """
        if user_id == actor.user_id:
            raise FileShareSelfError()
        async with self._uow_factory() as uow:
            await self._owned(uow, actor, file_id)
            row = await uow.shares.find(file_id, user_id)
            is_live = row is not None and row.revoked_at is None
            people = await uow.shares.list_active(file_id)
            if not is_live and len(people) >= MAX_FILE_SHARES:
                raise FileShareLimitError(params={"limit": MAX_FILE_SHARES})
            await uow.shares.put(
                FileShare(file_id, user_id, FileShareVia.DIRECT, self._clock.now())
            )
            await uow.commit()

    async def remove_person(self, actor: Actor, file_id: UUID, user_id: UUID) -> None:
        """Revoke at once and keep the person out of the link."""
        now = self._clock.now()
        async with self._uow_factory() as uow:
            await self._owned(uow, actor, file_id)
            await uow.shares.put(
                FileShare(file_id, user_id, FileShareVia.DIRECT, now, now)
            )
            await uow.commit()

    async def join(self, actor: Actor, token: str) -> StoredFile:
        """Turn a link into the caller's own grant.

        Raises:
            StoredFileNotFoundError: Unknown token, a link that was turned off, a
                file that is gone or a person the owner removed: all look the same.
            RateLimitedError: More than 10 tries in a minute.
        """
        if self._rate_limiter is not None:
            await self._rate_limiter.hit(
                f"file-share-join:{actor.user_id}",
                limit=JOIN_PER_MINUTE,
                window_seconds=WINDOW_SECONDS,
            )
        async with self._uow_factory() as uow:
            file_id = await uow.shares.file_of_token(hash_token(token))
            file = None if file_id is None else await uow.files.get(file_id)
            if file is None or not _open(file):
                raise StoredFileNotFoundError()
            if file.is_owned_by(actor.user_id):
                return file
            row = await uow.shares.find(file.id, actor.user_id)
            if row is not None and row.revoked_at is not None:
                raise StoredFileNotFoundError()
            if row is None:
                await uow.shares.put(
                    FileShare(
                        file.id, actor.user_id, FileShareVia.LINK, self._clock.now()
                    )
                )
                await uow.commit()
            return file

    async def leave(self, actor: Actor, file_id: UUID) -> None:
        """The recipient drops the file; a new link can bring them back."""
        async with self._uow_factory() as uow:
            await self._granted(uow, actor, file_id)
            await uow.shares.delete(file_id, actor.user_id)
            await uow.commit()

    async def _granted(
        self, uow: FilesUnitOfWork, actor: Actor, file_id: UUID
    ) -> StoredFile:
        """The file if the caller has a live grant on a file that is still open."""
        row = await uow.shares.find(file_id, actor.user_id)
        file = await uow.files.get(file_id)
        if row is None or row.revoked_at is not None or file is None or not _open(file):
            raise StoredFileNotFoundError()
        return file

    async def download_url(
        self, actor: Actor, file_id: UUID, inline: bool | None = None
    ) -> DownloadUrl:
        """A presigned URL for a recipient (60 seconds, like every download)."""
        async with self._uow_factory() as uow:
            file = await self._granted(uow, actor, file_id)
        return await self._links.url_for(file, inline=inline)

    async def list_shared(self, actor: Actor) -> list[StoredFile]:
        """Files shared with the caller that are still open."""
        async with self._uow_factory() as uow:
            ids = await uow.shares.files_of(actor.user_id)
            found = [await uow.files.get(file_id) for file_id in ids]
        return [file for file in found if file is not None and _open(file)]
