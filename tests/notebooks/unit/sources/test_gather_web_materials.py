"""Web materials of a web source: triage, quotas, attachment and the sharing rule."""

import dataclasses
from collections.abc import Sequence
from datetime import date
from typing import Any, cast
from uuid import UUID

from app.modules.files.domain.errors import QuotaExceededError
from app.modules.notebooks.application.gather_web_materials import (
    GatherWebMaterials,
    may_gather,
)
from app.modules.notebooks.domain.entities import Notebook, Source
from app.modules.notebooks.domain.enums import (
    NotebookOrigin,
    SourceKind,
    SourceStatus,
)
from app.modules.notebooks.domain.errors import SourceReadError
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.ports.web_materials import (
    DownloadedMaterial,
    MaterialCandidate,
)
from app.settings import Settings
from app.shared.actor import Actor
from app.shared.ai_tasks import AiTask
from app.shared.contracts.files import FilePurpose, FileRef, FilesApi, FileScope
from app.shared.limits import StaticLimits
from app.shared.wiring import ModuleDeps
from tests.factories.notebooks import make_source
from tests.fakes.clock import FixedClock
from tests.fakes.notebooks.files import FakeNotebookFiles
from tests.fakes.notebooks.world import World
from tests.fakes.tasks import FakeTaskKicker
from tests.notebooks.unit.sources.conftest import Build
from tests.notebooks.unit.sources.support import passages_of, stored

import pytest

PAGE = "https://bio.example.org/photosynthesis"
LECTURE = MaterialCandidate(
    "https://bio.example.org/lecture.pdf", "document", "Lecture 5", "full notes"
)
PRICES = MaterialCandidate(
    "https://bio.example.org/prices.pdf", "document", "Price list", "shop"
)
DIAGRAM = MaterialCandidate(
    "https://bio.example.org/chloroplast.png", "image", "Chloroplast", "figure 1"
)
LOGO = MaterialCandidate(
    "https://bio.example.org/banner.png", "image", "Banner", "header"
)
TYPES = {"document": "application/pdf", "image": "image/png"}
PROCESS = "notebooks.process_source"
EMBED = "notebooks.embed_passages"
GATHER = "notebooks.gather_web_materials"


class FakeMaterials:
    """Candidates of one page; downloads by URL, a URL may be refused."""

    def __init__(self, found: Sequence[MaterialCandidate]) -> None:
        self.found = list(found)
        self.refused: set[str] = set()
        self.downloads: list[str] = []

    async def candidates(self, page_url: str, limit: int) -> list[MaterialCandidate]:
        return self.found[:limit]

    async def download(self, url: str, max_bytes: int) -> DownloadedMaterial:
        self.downloads.append(url)
        if url in self.refused:
            raise SourceReadError("forbidden")
        kind = next(c.kind for c in self.found if c.url == url)
        return DownloadedMaterial(url, TYPES[kind], b"bytes of " + url.encode())


class FakeModel:
    """Keeps lectures and diagrams, rejects price lists and banners."""

    def __init__(self) -> None:
        self.calls: list[tuple[AiTask, str, int]] = []

    async def call(self, owner_id: UUID, **kwargs: Any) -> dict[str, Any]:
        task, user = kwargs["task"], kwargs["user"]
        self.calls.append((task, user, len(kwargs.get("attachments") or ())))
        if task is AiTask.MEDIA_DESCRIBE:
            return {"text": "A chloroplast with thylakoids and stroma labelled."}
        lines = [line for line in user.splitlines() if line[:1].isdigit()]
        keep = [
            i
            for i, line in enumerate(lines)
            if "Lecture" in line or "Chloroplast" in line
        ]
        return {"keep": keep}


class GatherFiles(FakeNotebookFiles):
    """Stored files are ready at once; documents get a text, a quota can be full."""

    def __init__(self) -> None:
        super().__init__()
        self.stored: list[FileRef] = []
        self.full = False

    async def store_bytes(
        self,
        *,
        owner_id: UUID,
        scope: FileScope,
        purpose: FilePurpose,
        name: str,
        data: bytes,
        expires_days: int | None = None,
    ) -> FileRef:
        if self.full:
            raise QuotaExceededError()
        document = name.endswith(".pdf")
        ref = FileRef(
            id=UUID(int=len(self.stored) + 1 + (owner_id.int % 10**6) * 1000),
            owner_id=owner_id,
            scope=scope,
            purpose=purpose,
            name=name,
            content_type="application/pdf" if document else "image/png",
            byte_size=len(data),
            status="ready",
            text_bytes=40 if document else None,
        )
        self.stored.append(ref)
        if document:
            self.add_text(ref, "Lecture five explains the light reactions in detail.")
        else:
            self.add(ref)
        return ref


class Counters:
    """An in-memory daily counter store."""

    def __init__(self) -> None:
        self.values: dict[tuple[UUID, date, str], int] = {}

    async def used(self, user_id: UUID, day: date, kind: str) -> int:
        return self.values.get((user_id, day, kind), 0)

    async def add(self, user_id: UUID, day: date, kind: str) -> int:
        key = (user_id, day, kind)
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    def total(self, kind: str) -> int:
        return sum(v for (_, _, k), v in self.values.items() if k == kind)


@pytest.fixture
def files() -> GatherFiles:
    """The owner's files."""
    return GatherFiles()


@pytest.fixture
def world(files: GatherFiles) -> World:
    """The source fakes with the gathering files."""
    return World(files=files)


@pytest.fixture
def model() -> FakeModel:
    """The triage and media model."""
    return FakeModel()


@pytest.fixture
def counters() -> Counters:
    """Daily counters."""
    return Counters()


def _gatherer(
    module_deps: ModuleDeps,
    uow_factory: UowFactory,
    clock: FixedClock,
    files: GatherFiles,
    materials: FakeMaterials,
    model: FakeModel,
    counters: Counters,
    kicker: FakeTaskKicker,
    **limits: int,
) -> GatherWebMaterials:
    settings: Settings = module_deps.settings
    if limits:
        settings = settings.model_copy(
            update={"limits": settings.limits.model_copy(update=limits)}
        )
    return GatherWebMaterials(
        uow_factory=uow_factory,
        clock=clock,
        settings=settings,
        files=cast(FilesApi, files),
        fetcher=materials,
        model=model,
        counters=counters,
        limits=StaticLimits(settings.limits),
        kicker=kicker,
        sleep=lambda seconds: _no_sleep(),
    )


async def _no_sleep() -> None:
    return None


async def _web_source(uow_factory: UowFactory, notebook: Notebook) -> Source:
    return await make_source(
        uow_factory,
        notebook,
        kind=SourceKind.URL,
        title="Photosynthesis",
        ref={"url": PAGE},
        ref_key=f"url:{PAGE}",
        texts=("Photosynthesis turns light into sugar.",),
    )


async def _sources(uow_factory: UowFactory, notebook_id: UUID) -> list[Source]:
    async with uow_factory() as uow:
        return list(await uow.sources.list_for_notebook(notebook_id))


@pytest.fixture
def run(
    module_deps: ModuleDeps,
    uow_factory: UowFactory,
    clock: FixedClock,
    files: GatherFiles,
    model: FakeModel,
    counters: Counters,
    kicker: FakeTaskKicker,
) -> Any:
    """Gather the materials of a source with candidates and limits."""

    async def go(
        source: Source, found: Sequence[MaterialCandidate], **limits: int
    ) -> tuple[Any, FakeMaterials]:
        materials = FakeMaterials(found)
        gatherer = _gatherer(
            module_deps,
            uow_factory,
            clock,
            files,
            materials,
            model,
            counters,
            kicker,
            **limits,
        )
        return await gatherer.execute(source.id), materials

    return go


# - - - Triage - - -


async def test_the_triage_keeps_substantive_files_and_rejects_the_rest(
    run: Any,
    uow_factory: UowFactory,
    notebook: Notebook,
    files: GatherFiles,
    model: FakeModel,
) -> None:
    """Lecture and diagram kept; price list never downloaded; banner looked at."""
    page = await _web_source(uow_factory, notebook)
    report, materials = await run(page, [LECTURE, PRICES, DIAGRAM, LOGO])

    assert (report.found, report.added) == (4, 2)
    assert PRICES.url not in materials.downloads
    assert LOGO.url in materials.downloads  # an image is judged by looking at it
    assert [ref.name for ref in files.stored] == ["lecture.pdf", "chloroplast.png"]
    image_calls = [c for c in model.calls if c[2] == 1]
    assert {c[0] for c in image_calls} == {
        AiTask.WEB_MATERIAL_TRIAGE,
        AiTask.MEDIA_DESCRIBE,
    }


async def test_a_refused_download_is_skipped(
    run: Any, uow_factory: UowFactory, notebook: Notebook
) -> None:
    """An SSRF refusal or a failed download keeps nothing and goes on."""
    page = await _web_source(uow_factory, notebook)
    materials_found = [LECTURE, DIAGRAM]
    report, materials = await run(page, materials_found)
    assert report.added == 2
    # A second run finds nothing new: the notebook already has both.
    report, _ = await run(page, materials_found)
    assert (report.found, report.added) == (0, 0)


# - - - Attachment and vectors - - -


async def test_kept_files_become_sources_of_the_owner_linked_to_the_page(
    run: Any,
    build: Build,
    uow_factory: UowFactory,
    notebook: Notebook,
    student: Actor,
    kicker: FakeTaskKicker,
) -> None:
    """File sources with the parent page; processing indexes them for search."""
    page = await _web_source(uow_factory, notebook)
    await run(page, [LECTURE, DIAGRAM])

    added = [s for s in await _sources(uow_factory, notebook.id) if s.id != page.id]
    assert len(added) == 2
    for source in added:
        assert source.kind is SourceKind.FILE
        assert source.owner_id == student.user_id
        assert source.ref["parent_source_id"] == str(page.id)
        assert (PROCESS, {"source_id": str(source.id)}) in kicker.calls
    image = next(s for s in added if s.ref["media"])
    assert "thylakoids" in (image.body_md or "")

    services = build()
    for source in added:
        await services.process_source.execute(source.id)
        ready = await stored(uow_factory, source.id)
        assert ready.status is SourceStatus.READY
        assert await passages_of(uow_factory, source.id)
        assert (EMBED, {"document_id": str(ready.document_id)}) in kicker.calls


# - - - Limits and quotas - - -


async def test_a_full_files_quota_stops_gathering(
    run: Any, uow_factory: UowFactory, notebook: Notebook, files: GatherFiles
) -> None:
    """Over the owner's storage quota nothing is stored or attached."""
    files.full = True
    page = await _web_source(uow_factory, notebook)
    report, _ = await run(page, [LECTURE, DIAGRAM])
    assert (report.added, report.stopped) == (0, "files_quota")
    assert len(await _sources(uow_factory, notebook.id)) == 1


async def test_the_daily_limits_are_respected(
    run: Any, uow_factory: UowFactory, notebook: Notebook, counters: Counters
) -> None:
    """One gathered file a day; 0 media reads skips images, documents go on."""
    page = await _web_source(uow_factory, notebook)
    second = dataclasses.replace(LECTURE, url="https://bio.example.org/lecture6.pdf")
    report, _ = await run(
        page,
        [DIAGRAM, LECTURE, second],
        nb_web_materials_per_day=1,
        nb_media_described_per_day=0,
    )
    assert (report.added, report.stopped) == (1, "limit")
    assert counters.total("web_materials") == 1
    assert counters.total("media_described") == 0


async def test_minus_one_means_no_cap(
    run: Any, uow_factory: UowFactory, notebook: Notebook
) -> None:
    """-1 lifts the daily caps."""
    page = await _web_source(uow_factory, notebook)
    report, _ = await run(
        page,
        [LECTURE, DIAGRAM],
        nb_web_materials_per_day=-1,
        nb_media_described_per_day=-1,
    )
    assert report.added == 2


# - - - Sharing rule - - -


@pytest.mark.parametrize(
    "origin",
    [
        NotebookOrigin.SUBJECT_AUTO,
        NotebookOrigin.LESSON_AUTO,
        NotebookOrigin.COURSE,
        NotebookOrigin.COURSE_STUDENT,
    ],
)
async def test_shared_and_auto_notebooks_never_gather(
    uow_factory: UowFactory, notebook: Notebook, origin: NotebookOrigin
) -> None:
    """Materials go only into the owner's own manual notebook."""
    page = await _web_source(uow_factory, notebook)
    assert may_gather(page, notebook)
    assert not may_gather(page, dataclasses.replace(notebook, origin=origin))
    foreign = dataclasses.replace(notebook, owner_id=UUID(int=7))
    assert not may_gather(page, foreign)


async def test_materials_stay_in_the_gathering_notebook(
    run: Any,
    uow_factory: UowFactory,
    notebook: Notebook,
    their_notebook: Notebook,
    student: Actor,
    files: GatherFiles,
) -> None:
    """Another user's notebook with the same page gets nothing from this run, and
    every stored file is the gathering owner's."""
    mine = await _web_source(uow_factory, notebook)
    theirs = await _web_source(uow_factory, their_notebook)
    await run(mine, [LECTURE])

    assert len(await _sources(uow_factory, their_notebook.id)) == 1
    assert {ref.owner_id for ref in files.stored} == {student.user_id}
    their_report, _ = await run(theirs, [LECTURE])
    assert their_report.added == 1
    their_files = [r for r in files.stored if r.owner_id != student.user_id]
    assert len(their_files) == 1  # their own download into their own files


async def test_a_gathered_source_does_not_gather_again(
    run: Any, uow_factory: UowFactory, notebook: Notebook
) -> None:
    """Only web pages gather; a material (or any other kind) never does."""
    page = await _web_source(uow_factory, notebook)
    await run(page, [LECTURE])
    material = next(
        s for s in await _sources(uow_factory, notebook.id) if s.id != page.id
    )
    report, materials = await run(material, [DIAGRAM])
    assert report.added == 0 and materials.downloads == []


async def test_a_ready_web_page_kicks_the_gathering(
    build: Build,
    uow_factory: UowFactory,
    notebook: Notebook,
    world: World,
    kicker: FakeTaskKicker,
) -> None:
    """`process_source` asks for the materials of a page once it is ready."""
    world.fetcher.add_page(PAGE, "Photosynthesis turns light into sugar.")
    page = await make_source(
        uow_factory,
        notebook,
        kind=SourceKind.URL,
        ref={"url": PAGE},
        texts=(),
        status=SourceStatus.PENDING,
    )
    await build().process_source.execute(page.id)
    assert (GATHER, {"source_id": str(page.id)}) in kicker.calls
    kicker.calls.clear()
    off = build(notebooks={"web_materials_enabled": False})
    other = dataclasses.replace(page)
    assert other.id == page.id
    async with uow_factory() as uow:
        current = await uow.sources.get_for_update(page.id)
        assert current is not None
        current.status = SourceStatus.STALE
        await uow.sources.save(current)
        await uow.commit()
    await off.process_source.execute(page.id)
    assert GATHER not in kicker.names()
