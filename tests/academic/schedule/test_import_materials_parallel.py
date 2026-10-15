"""EMIS material downloads run in parallel, bounded, with the sequential result."""

import asyncio
from typing import Any
from uuid import UUID, uuid4

from app.modules.academic.application.schedule.import_materials import (
    ImportLessonMaterials,
)
from app.modules.academic.application.schedule.ports.lesson_urls import EmisMaterial
from app.shared import jobs
from app.shared.contracts.emis import EmisFile
from app.shared.contracts.files import FilePurpose, FileRef, FileScope
from app.shared.jobs import MemoryJobTracker, run_job


class SlowEmis:
    def __init__(self) -> None:
        self.active = 0
        self.peak = 0
        self.urls: list[str] = []

    async def download(self, user_id: UUID, url: str, *, max_bytes: int) -> EmisFile:
        self.active += 1
        self.peak = max(self.peak, self.active)
        self.urls.append(url)
        await asyncio.sleep(0.01)
        self.active -= 1
        if url.endswith("bad.pdf"):
            raise RuntimeError("EMIS down")
        return EmisFile(name="f.pdf", content_type="application/pdf", data=b"x")


class Files:
    async def store_bytes(self, *, name: str, **_: Any) -> FileRef:
        return FileRef(
            uuid4(), uuid4(), FileScope.SYSTEM, FilePurpose.LINK, name,
            "application/pdf", 1, "ready", None,
        )  # fmt: skip


class Links:
    def __init__(self, known: set[tuple[UUID, str]]) -> None:
        self.known = known
        self.files: list[tuple[UUID, str]] = []
        self.urls: list[tuple[UUID, str, str]] = []

    async def emis_sources(self, lesson_ids: Any) -> set[tuple[UUID, str]]:
        return set(self.known)

    async def import_lesson_files(self, items: Any) -> int:
        self.files += [(i.lesson_id, i.source_url) for i in items]
        return len(items)

    async def import_lesson_urls(self, items: Any) -> int:
        self.urls += [(i.lesson_id, i.url, i.title) for i in items]
        return len(items)


LESSON_A, LESSON_B = uuid4(), uuid4()


def materials() -> list[EmisMaterial]:
    items = [
        EmisMaterial(lesson, f"https://e/{n}.pdf", "T", "classwork")
        for n, lesson in enumerate([LESSON_B, LESSON_A] * 6)
    ]
    items.append(EmisMaterial(LESSON_A, "https://e/bad.pdf", "T", "homework"))
    items.append(EmisMaterial(LESSON_A, "https://e/v", "T", "video"))
    items.append(EmisMaterial(LESSON_B, "https://e/1.pdf", "T", "homework"))  # same URL
    return items


async def run(concurrency: int, known: set[tuple[UUID, str]]) -> tuple[Any, ...]:
    emis, links = SlowEmis(), Links(known)
    importer = ImportLessonMaterials(
        emis=emis, files=Files(), links=links,  # type: ignore[arg-type]
        max_bytes=100, concurrency=concurrency,
    )  # fmt: skip
    added = await importer.import_materials(uuid4(), materials())
    return added, links.files, links.urls, emis


async def test_parallel_matches_sequential_within_the_limit() -> None:
    sequential = await run(1, set())
    parallel = await run(4, set())
    assert sequential[:3] == parallel[:3]
    assert sequential[3].peak == 1
    assert 1 < parallel[3].peak <= 4
    assert parallel[3].urls.count("https://e/1.pdf") == 1  # each URL downloaded once


async def test_known_materials_are_not_downloaded() -> None:
    added, _, _, emis = await run(4, {(LESSON_A, "https://e/1.pdf")})
    assert "https://e/1.pdf" in emis.urls  # still needed by lesson B
    added, _, _, emis = await run(4, {(LESSON_B, "https://e/0.pdf")})
    assert "https://e/0.pdf" not in emis.urls


async def test_a_stop_request_ends_the_downloads(monkeypatch: Any) -> None:
    monkeypatch.setattr(jobs, "STOP_CHECK_SECONDS", 0.0)
    tracker = MemoryJobTracker()
    await tracker.flag_cancel("j")
    tracker.jobs.clear()
    async with run_job(tracker, "k", "L", job_id="j") as job:
        assert job is None  # flagged before start: never runs
    tracker.flags.clear()
    async with run_job(tracker, "k", "L", job_id="j2"):
        await tracker.flag_cancel("j2")
        _, files, _, emis = await run(2, set())
    assert emis.urls == [] and files == []
