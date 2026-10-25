"""EMIS materials with the same bytes share one stored file (and its purge)."""

import hashlib
from collections.abc import Sequence
from typing import Any
from uuid import UUID, uuid4

from app.modules.academic.application.schedule.import_materials import (
    ImportLessonMaterials,
)
from app.modules.academic.application.schedule.ports.lesson_urls import EmisMaterial
from app.shared.contracts.emis import EmisFile
from app.shared.contracts.files import FilePurpose, FileRef, FileScope
from app.shared.contracts.links import EMIS_AUTHOR_ID


class Emis:
    def __init__(self, data: dict[str, bytes]) -> None:
        self.data = data

    async def download(self, user_id: UUID, url: str, *, max_bytes: int) -> EmisFile:
        return EmisFile(
            name="f.pdf", content_type="application/pdf", data=self.data[url]
        )


class Files:
    def __init__(self) -> None:
        self.rows: dict[UUID, tuple[FileRef, str]] = {}
        self.stored = 0
        self.deleted: list[UUID] = []

    async def find_by_content(
        self, *, owner_id: UUID, scope: FileScope, sha256: str, byte_size: int
    ) -> FileRef | None:
        for ref, digest in self.rows.values():
            if (ref.owner_id, ref.scope, digest, ref.byte_size) == (
                owner_id, scope, sha256, byte_size,
            ):  # fmt: skip
                return ref
        return None

    async def store_bytes(
        self, *, owner_id: UUID, scope: FileScope, name: str, data: bytes, **_: Any
    ) -> FileRef:
        self.stored += 1
        ref = FileRef(
            uuid4(), owner_id, scope, FilePurpose.LINK, name,
            "application/pdf", len(data), "ready", None,
        )  # fmt: skip
        self.rows[ref.id] = (ref, hashlib.sha256(data).hexdigest())
        return ref

    async def get_many(self, file_ids: Sequence[UUID]) -> dict[UUID, FileRef]:
        return {i: self.rows[i][0] for i in file_ids if i in self.rows}

    async def delete_file(self, file_id: UUID) -> None:
        self.deleted.append(file_id)
        self.rows.pop(file_id, None)


class Links:
    def __init__(self) -> None:
        self.resources: list[tuple[UUID, str, UUID]] = []

    async def emis_sources(self, lesson_ids: Any) -> set[tuple[UUID, str]]:
        return {(lesson, url) for lesson, url, _ in self.resources}

    async def import_lesson_files(self, items: Any) -> int:
        self.resources += [(i.lesson_id, i.source_url, i.file_id) for i in items]
        return len(items)

    async def import_lesson_urls(self, items: Any) -> int:
        return 0

    async def purge_emis_resources(self, lesson_ids: Sequence[UUID]) -> list[UUID]:
        gone = [r for r in self.resources if r[0] in lesson_ids]
        self.resources = [r for r in self.resources if r[0] not in lesson_ids]
        return [file_id for _, _, file_id in gone]

    async def files_in_use(self, file_ids: Sequence[UUID]) -> set[UUID]:
        return {f for _, _, f in self.resources if f in file_ids}


LESSON_A, LESSON_B = uuid4(), uuid4()


def importer(data: dict[str, bytes]) -> tuple[ImportLessonMaterials, Files, Links]:
    files, links = Files(), Links()
    uc = ImportLessonMaterials(
        emis=Emis(data), files=files, links=links,  # type: ignore[arg-type]
        max_bytes=100,
    )  # fmt: skip
    return uc, files, links


def item(lesson: UUID, url: str) -> EmisMaterial:
    return EmisMaterial(lesson, url, "T", "classwork")


async def test_identical_bytes_from_two_lessons_share_one_file() -> None:
    uc, files, links = importer(
        {"https://e/a.pdf": b"same", "https://e/b.pdf": b"same"}
    )
    await uc.import_materials(uuid4(), [item(LESSON_A, "https://e/a.pdf")])
    await uc.import_materials(uuid4(), [item(LESSON_B, "https://e/b.pdf")])
    assert files.stored == 1
    assert len(links.resources) == 2
    assert len({file_id for _, _, file_id in links.resources}) == 1


async def test_identical_bytes_in_one_run_share_one_file() -> None:
    uc, files, links = importer(
        {"https://e/a.pdf": b"same", "https://e/b.pdf": b"same"}
    )
    added = await uc.import_materials(
        uuid4(), [item(LESSON_A, "https://e/a.pdf"), item(LESSON_B, "https://e/b.pdf")]
    )
    assert (added, files.stored) == (2, 1)


async def test_different_bytes_are_two_files() -> None:
    uc, files, links = importer({"https://e/a.pdf": b"one", "https://e/b.pdf": b"two"})
    await uc.import_materials(
        uuid4(), [item(LESSON_A, "https://e/a.pdf"), item(LESSON_B, "https://e/b.pdf")]
    )
    assert files.stored == 2
    assert len({file_id for _, _, file_id in links.resources}) == 2


async def test_purge_keeps_a_shared_file_until_the_last_reference() -> None:
    uc, files, links = importer(
        {"https://e/a.pdf": b"same", "https://e/b.pdf": b"same"}
    )
    await uc.import_materials(
        uuid4(), [item(LESSON_A, "https://e/a.pdf"), item(LESSON_B, "https://e/b.pdf")]
    )
    (shared,) = {file_id for _, _, file_id in links.resources}
    assert files.rows[shared][0].owner_id == EMIS_AUTHOR_ID
    await uc.purge([LESSON_A])
    assert files.deleted == [] and shared in files.rows
    await uc.purge([LESSON_B])
    assert files.deleted == [shared]
