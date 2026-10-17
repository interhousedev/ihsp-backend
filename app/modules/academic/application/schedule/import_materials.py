"""EMIS materials become stored files on the lessons (ACA-9).

A topic or homework file that EMIS links is downloaded through the student's EMIS
link, stored like an upload (type and size checks, text extraction for the AI and
the preview) and attached as a file resource named ``Classwork: <topic>`` or
``Homework: <topic>``. A video stays a link. When a download or the checks fail, the
address is attached as a link instead, so the student still reaches it.
"""

import asyncio
import hashlib
import mimetypes
from collections.abc import Sequence
from pathlib import PurePosixPath
from urllib.parse import urlsplit
from uuid import UUID

from app.modules.academic.application.schedule.ports.lesson_urls import (
    EmisMaterial,
    MaterialKind,
)
from app.shared.contracts.emis import EmisFile, EmisSource
from app.shared.contracts.files import FilePurpose, FileRef, FilesApi, FileScope
from app.shared.contracts.links import (
    EMIS_AUTHOR_ID,
    ImportedFile,
    ImportedUrl,
    LinksApi,
)
from app.shared.jobs import job_progress, job_should_stop

import structlog

log = structlog.get_logger(__name__)

PREFIXES: dict[MaterialKind, str] = {
    "classwork": "Classwork",
    "homework": "Homework",
    "video": "Video",
}
MAX_TOPIC_LENGTH = 200
DOWNLOAD_CONCURRENCY = 6  # EMIS__DOWNLOAD_CONCURRENCY


def material_title(item: EmisMaterial) -> str:
    """``Homework: <topic>``, ``Classwork: <topic>`` or ``<topic> (video)``."""
    if item.kind == "video":
        return f"{item.name} (video)"
    return f"{PREFIXES[item.kind]}: {item.name}"


def file_name(item: EmisMaterial, file: EmisFile) -> str:
    """The title plus the extension of the downloaded file (path-safe)."""
    topic = item.name.replace("/", "-").replace("\\", "-").strip()
    title = f"{PREFIXES[item.kind]}: {topic[:MAX_TOPIC_LENGTH]}"
    return title + _extension(item.url, file)


def _extension(url: str, file: EmisFile) -> str:
    for candidate in (file.name, urlsplit(url).path):
        suffix = PurePosixPath(candidate).suffix.lower()
        if 1 < len(suffix) <= 11 and suffix[1:].isalnum():
            return suffix
    content_type = (file.content_type or "").split(";", 1)[0].strip()
    return mimetypes.guess_extension(content_type) or ""


class ImportLessonMaterials:
    """Downloads new EMIS materials into files; purges them for an admin re-sync."""

    def __init__(
        self,
        *,
        emis: EmisSource,
        files: FilesApi,
        links: LinksApi,
        max_bytes: int,
        concurrency: int = DOWNLOAD_CONCURRENCY,
    ) -> None:
        """Store the collaborators, the size limit of one file and the parallelism."""
        self.emis = emis
        self.files = files
        self.links = links
        self.max_bytes = max_bytes
        self.concurrency = max(concurrency, 1)

    async def import_materials(
        self, user_id: UUID, items: Sequence[EmisMaterial]
    ) -> int:
        """Attach the materials not attached before; return how many are new.

        Known (lesson, url) pairs are skipped before any download; the new files
        are downloaded in parallel (at most ``concurrency`` at a time, each URL
        once), then stored and attached in the order of ``items``. A job stop
        request ends the downloads early; what was fetched is still attached.
        """
        lesson_ids = list(dict.fromkeys(item.lesson_id for item in items))
        known = await self.links.emis_sources(lesson_ids) if lesson_ids else set()
        fresh: list[EmisMaterial] = []
        for item in items:
            key = (item.lesson_id, item.url)
            if key not in known:
                known.add(key)
                fresh.append(item)
        downloads = await self._download_all(user_id, fresh)
        stored: list[ImportedFile] = []
        by_hash: dict[str, FileRef] = {}  # same bytes from two URLs: one file
        fallback: list[ImportedUrl] = []
        for item in fresh:
            if item.kind != "video" and item.url not in downloads:
                continue  # stopped before its download: the next sync brings it
            file = downloads.get(item.url) if item.kind != "video" else None
            ref = await self._store(item, file, by_hash)
            if file is None or ref is None:
                fallback.append(
                    ImportedUrl(item.lesson_id, item.url, material_title(item))
                )
            else:
                title = file_name(item, file)  # the file may be shared: own name
                stored.append(ImportedFile(item.lesson_id, item.url, ref.id, title))
        added = await self.links.import_lesson_files(stored) if stored else 0
        if fallback:
            added += await self.links.import_lesson_urls(fallback)
        await job_progress(add={"files": len(stored), "links": len(fallback)})
        return added

    async def _download_all(
        self, user_id: UUID, items: Sequence[EmisMaterial]
    ) -> dict[str, EmisFile | None]:
        """Download each distinct file URL once, ``concurrency`` at a time."""
        firsts = {item.url: item for item in reversed(items) if item.kind != "video"}
        gate = asyncio.Semaphore(self.concurrency)
        downloads: dict[str, EmisFile | None] = {}

        async def one(item: EmisMaterial) -> None:
            async with gate:
                if await job_should_stop():
                    return
                downloads[item.url] = await self._download(user_id, item)

        await asyncio.gather(*(one(item) for item in reversed(firsts.values())))
        return downloads

    async def purge(self, lesson_ids: Sequence[UUID]) -> int:
        """Delete the EMIS resources of the lessons and the files EMIS owns.

        A file that other lessons' resources still use (same content) stays.
        """
        file_ids = list(
            dict.fromkeys(await self.links.purge_emis_resources(lesson_ids))
        )
        owned = await self.files.get_many(file_ids) if file_ids else {}
        emis = [i for i, ref in owned.items() if ref.owner_id == EMIS_AUTHOR_ID]
        in_use = await self.links.files_in_use(emis) if emis else set()
        for file_id in emis:  # never a person's upload
            if file_id not in in_use:
                await self.files.delete_file(file_id)
        return len(file_ids)

    async def lessons_with_materials(self, lesson_ids: Sequence[UUID]) -> set[UUID]:
        """The lessons that already have any resource attached."""
        if not lesson_ids:
            return set()
        found = await self.links.resources_for_lessons(lesson_ids)
        return {lesson_id for lesson_id, refs in found.items() if refs}

    async def _store(
        self, item: EmisMaterial, file: EmisFile | None, by_hash: dict[str, FileRef]
    ) -> FileRef | None:
        """Store the bytes, or reuse the EMIS file with the same content."""
        if file is None:
            return None
        digest = hashlib.sha256(file.data).hexdigest()
        if digest in by_hash:
            return by_hash[digest]
        ref = await self.files.find_by_content(
            owner_id=EMIS_AUTHOR_ID,
            scope=FileScope.SYSTEM,
            sha256=digest,
            byte_size=len(file.data),
        )
        if ref is None:
            ref = await self._store_new(item, file)
        if ref is not None:
            by_hash[digest] = ref
        return ref

    async def _store_new(self, item: EmisMaterial, file: EmisFile) -> FileRef | None:
        try:
            return await self.files.store_bytes(
                owner_id=EMIS_AUTHOR_ID,
                scope=FileScope.SYSTEM,
                purpose=FilePurpose.LINK,
                name=file_name(item, file),
                data=file.data,
            )
        except Exception as exc:  # type or size refused: keep the link instead
            log.warning(
                "emis_material_not_stored",
                lesson_id=str(item.lesson_id),
                error=type(exc).__name__,
            )
            return None

    async def _download(self, user_id: UUID, item: EmisMaterial) -> EmisFile | None:
        try:
            return await self.emis.download(user_id, item.url, max_bytes=self.max_bytes)
        except Exception as exc:  # EMIS down, refused, too large or a timeout
            log.warning(
                "emis_material_download_failed",
                lesson_id=str(item.lesson_id),
                error=type(exc).__name__,
            )
            return None
