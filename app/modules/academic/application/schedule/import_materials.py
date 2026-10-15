"""EMIS materials become stored files on the lessons (ACA-9).

A topic or homework file that EMIS links is downloaded through the student's EMIS
link, stored like an upload (type and size checks, text extraction for the AI and
the preview) and attached as a file resource named ``Classwork: <topic>`` or
``Homework: <topic>``. A video stays a link. When a download or the checks fail, the
address is attached as a link instead, so the student still reaches it.
"""

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

import structlog

log = structlog.get_logger(__name__)

PREFIXES: dict[MaterialKind, str] = {
    "classwork": "Classwork",
    "homework": "Homework",
    "video": "Video",
}
MAX_TOPIC_LENGTH = 200


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
    ) -> None:
        """Store the collaborators and the size limit of one file (LIMITS__)."""
        self.emis = emis
        self.files = files
        self.links = links
        self.max_bytes = max_bytes

    async def import_materials(
        self, user_id: UUID, items: Sequence[EmisMaterial]
    ) -> int:
        """Attach the materials not attached before; return how many are new."""
        lesson_ids = list(dict.fromkeys(item.lesson_id for item in items))
        known = await self.links.emis_sources(lesson_ids) if lesson_ids else set()
        stored: list[ImportedFile] = []
        fallback: list[ImportedUrl] = []
        downloads: dict[str, EmisFile | None] = {}
        for item in items:
            key = (item.lesson_id, item.url)
            if key in known:
                continue
            known.add(key)
            ref = None
            if item.kind != "video":
                ref = await self._store(user_id, item, downloads)
            if ref is None:
                fallback.append(
                    ImportedUrl(item.lesson_id, item.url, material_title(item))
                )
            else:
                stored.append(ImportedFile(item.lesson_id, item.url, ref.id))
        added = await self.links.import_lesson_files(stored) if stored else 0
        if fallback:
            added += await self.links.import_lesson_urls(fallback)
        return added

    async def purge(self, lesson_ids: Sequence[UUID]) -> int:
        """Delete the EMIS resources of the lessons and the files EMIS owns."""
        file_ids = await self.links.purge_emis_resources(lesson_ids)
        owned = await self.files.get_many(file_ids) if file_ids else {}
        for file_id, ref in owned.items():
            if ref.owner_id == EMIS_AUTHOR_ID:  # never a person's upload
                await self.files.delete_file(file_id)
        return len(file_ids)

    async def _store(
        self,
        user_id: UUID,
        item: EmisMaterial,
        downloads: dict[str, EmisFile | None],
    ) -> FileRef | None:
        if item.url not in downloads:
            downloads[item.url] = await self._download(user_id, item)
        file = downloads[item.url]
        if file is None:
            return None
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
