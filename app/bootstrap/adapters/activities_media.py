"""Adapters of club media: the files module as a store, the broker as a kicker."""

from uuid import UUID

from app.modules.activities.ports.gateways import StoredFile, UploadTicket
from app.shared.contracts.files import FilePurpose, FileRef, FilesApi, FileScope
from app.shared.tasks import TaskKicker

import httpx

_CHUNK = 1024 * 1024
_FETCH_TTL = 900


def _stored(ref: FileRef, sha256: str | None) -> StoredFile:
    return StoredFile(
        id=ref.id,
        owner_id=ref.owner_id,
        name=ref.name,
        content_type=ref.content_type,
        byte_size=ref.byte_size,
        status=ref.status,
        sha256=sha256,
    )


class FilesMediaStore:
    """Club media bytes live in the files module (scope CLUB, purpose CLUB_MEDIA)."""

    def __init__(self, files: FilesApi) -> None:
        """Bind the files module."""
        self._files = files

    async def request_upload(
        self,
        *,
        club_id: UUID,
        name: str,
        size: int,
        content_type: str,
        sha256_b64: str,
        max_bytes: int,
    ) -> UploadTicket:
        """Reserve a pending file owned by the club."""
        file_id, put = await self._files.request_upload(
            owner_id=club_id,
            scope=FileScope.CLUB,
            purpose=FilePurpose.CLUB_MEDIA,
            name=name,
            size=size,
            content_type=content_type,
            sha256_b64=sha256_b64,
            max_bytes=max_bytes,
        )
        return UploadTicket(file_id, put.url, put.method, dict(put.headers))

    async def complete(self, file_id: UUID) -> StoredFile:
        """Verify the uploaded object."""
        ref = await self._files.complete_upload(file_id)
        return _stored(ref, await self._files.sha256(file_id))

    async def info(self, file_id: UUID) -> StoredFile | None:
        """Metadata of any file."""
        ref = await self._files.get(file_id)
        return None if ref is None else _stored(ref, None)

    async def download_to(self, file_id: UUID, path: str) -> None:
        """Stream the file to disk through a short presigned URL."""
        url = await self._files.download_url(file_id, ttl_seconds=_FETCH_TTL)
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                with open(path, "wb") as out:
                    async for chunk in response.aiter_bytes(_CHUNK):
                        out.write(chunk)

    async def read_bytes(self, file_id: UUID) -> bytes:
        """Return the file content."""
        return await self._files.read_bytes(file_id)

    async def store_path(
        self, *, club_id: UUID, name: str, path: str, content_type: str
    ) -> UUID:
        """Store a derivative from disk, streamed; returns the file id."""
        ref = await self._files.store_path(
            owner_id=club_id,
            scope=FileScope.CLUB,
            purpose=FilePurpose.CLUB_MEDIA,
            name=name,
            path=path,
            content_type=content_type,
        )
        return ref.id

    async def download_url(self, file_id: UUID, *, ttl_seconds: int) -> str:
        """Return a presigned GET URL."""
        return await self._files.download_url(file_id, ttl_seconds=ttl_seconds)

    async def delete(self, file_id: UUID) -> None:
        """Delete the file for good; repeatable."""
        await self._files.delete_file(file_id)

    async def adopt(self, file_ids: list[UUID], club_id: UUID) -> None:
        """Give files to the club (a logo)."""
        await self._files.transfer_ownership(file_ids, club_id)


class BrokerMediaKicker:
    """Queues the processing task of a media item."""

    def __init__(self, kicker: TaskKicker) -> None:
        """Bind the task kicker."""
        self._kicker = kicker

    async def process(self, media_id: UUID) -> None:
        """Enqueue `activities.media.process`."""
        await self._kicker.kick("activities.media.process", media_id=str(media_id))
