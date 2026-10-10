"""Jobs `notebooks.sync_course_notebook(s)`: a student's course notebook (LMS-NB)."""

from dataclasses import dataclass
from functools import partial
from uuid import UUID

from app.modules.notebooks.application.notebook_state import sources_changed
from app.modules.notebooks.application.readers.base import ResolvedSource, clean_title
from app.modules.notebooks.application.readers.file_reader import has_text
from app.modules.notebooks.application.readers.registry import SourceReaders
from app.modules.notebooks.domain.entities import Notebook, Source
from app.modules.notebooks.domain.enums import SourceKind, SourceStatus
from app.modules.notebooks.domain.limits import AUTO_FANOUT_LIMIT, COURSE_SOURCE_LIMIT
from app.modules.notebooks.domain.source_input import LibraryItemInput
from app.modules.notebooks.ports.unit_of_work import NotebooksUnitOfWork, UowFactory
from app.shared.base_error import BaseError
from app.shared.clock import Clock
from app.shared.contracts.files import FilesApi
from app.shared.contracts.lms import LmsCourseMaterials, LmsSourceReader
from app.shared.ids import new_id
from app.shared.tasks import TaskKicker

import structlog

log = structlog.get_logger(__name__)

MATERIAL_MARK = "course_material"  # origin key of a source the sync owns
REVISED = (SourceStatus.PENDING, SourceStatus.PROCESSING)


@dataclass(frozen=True, slots=True)
class CourseSyncResult:
    """What one sync changed."""

    added: int = 0
    removed: int = 0
    refreshed: int = 0


@dataclass(slots=True)
class _Plan:
    """The sources the notebook should hold, in order, by duplicate key."""

    wanted: dict[str, ResolvedSource]


def is_material(source: Source) -> bool:
    """A source the sync owns: a material of the course (not the student's own)."""
    return source.ref_key is not None and bool((source.origin or {}).get(MATERIAL_MARK))


class SyncCourseNotebook:
    """Makes the sources of a student's course notebook the course materials.

    The materials are the steps' texts (flash cards included), the videos, the attached
    files and the linked library items of the live version. They are sources by
    reference: a step or a video is read (and chunked once for all students) at its
    revision, so a new revision marks the source outdated and it is read again. A
    student's own notes and texts are left alone. Safe to run twice and at once: the
    notebook row is locked for the write.
    """

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        clock: Clock,
        readers: SourceReaders,
        lms: LmsSourceReader | None,
        files: FilesApi,
        kicker: TaskKicker,
    ) -> None:
        """Store the collaborators (`lms` missing: the sync does nothing)."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.readers = readers
        self.lms = lms
        self.files = files
        self.kicker = kicker

    async def execute(
        self, notebook_id: UUID, materials: LmsCourseMaterials | None = None
    ) -> CourseSyncResult:
        """Bring the notebook in line with the course; return what changed.

        `materials` may be given by a caller that has just read them.
        """
        async with self.uow_factory() as uow:
            notebook = await uow.notebooks.get(notebook_id)
        if (
            self.lms is None
            or notebook is None
            or notebook.is_deleted
            or not notebook.is_course_student
            or notebook.course_id is None
        ):
            return CourseSyncResult()
        if materials is None:
            materials = await self.lms.course_materials(
                notebook.owner_id, notebook.course_id
            )
        plan = _Plan(wanted={})
        if materials is not None:  # None: not enrolled any more, nothing is wanted
            await self._plan(notebook, materials, plan)
        return await self._apply(notebook, plan)

    # - - - Steps - - -

    async def _plan(
        self, notebook: Notebook, materials: LmsCourseMaterials, plan: _Plan
    ) -> None:
        """Describe every material, best first, up to the course limit."""
        course = materials.course_id
        title = materials.course_title
        for step in materials.steps:
            self._want(
                plan,
                SourceKind.LMS_STEP,
                f"lms:{step.step_id}",
                clean_title(step.title, "Course step"),  # the notebook is the course
                {
                    "course_id": str(course),
                    "step_id": str(step.step_id),
                    "revision_id": step.revision_id,
                },
                "step",
                title,
            )
        for video in materials.videos:
            self._want(
                plan,
                SourceKind.LMS_STEP,
                f"lms-video:{video.step_id}:{video.block_id}",
                clean_title(video.title, "Video"),
                {
                    "course_id": str(course),
                    "step_id": str(video.step_id),
                    "block_id": video.block_id,
                    "revision_id": video.revision_id,
                },
                "video",
                title,
            )
        await self._plan_files(materials, plan, title)
        await self._plan_library(notebook, materials, plan, title)

    def _want(  # noqa: PLR0913 - the parts of one source row
        self,
        plan: _Plan,
        kind: SourceKind,
        key: str,
        title: str,
        ref: dict[str, object],
        what: str,
        course_title: str,
    ) -> None:
        if len(plan.wanted) >= COURSE_SOURCE_LIMIT:
            return
        plan.wanted[key] = ResolvedSource(
            kind=kind,
            title=title,
            ref=ref,
            ref_key=key,
            origin={MATERIAL_MARK: what, "course_title": course_title},
        )

    async def _plan_files(
        self, materials: LmsCourseMaterials, plan: _Plan, course_title: str
    ) -> None:
        """Attached files that are ready and have text (others: next sync)."""
        if not materials.files:
            return
        found = await self.files.get_many(list(materials.files))
        for file_id in materials.files:
            ref = found.get(file_id)
            if ref is None or not has_text(ref):
                continue
            self._want(
                plan,
                SourceKind.FILE,
                f"file:{file_id}",
                clean_title(ref.name, "File"),
                {"file_id": str(file_id), "content_type": ref.content_type},
                "file",
                course_title,
            )

    async def _plan_library(
        self,
        notebook: Notebook,
        materials: LmsCourseMaterials,
        plan: _Plan,
        course_title: str,
    ) -> None:
        """Linked library items the student may read (others are skipped)."""
        reader = self.readers.library_reader
        if reader is None:
            return
        for item_id in materials.library_items:
            if len(plan.wanted) >= COURSE_SOURCE_LIMIT:
                return
            try:
                resolved = await reader.resolve(
                    notebook.owner_id, LibraryItemInput(item_id=item_id)
                )
            except (BaseError, ValueError):
                continue  # no text, held back, too large or not readable: skip
            if resolved.ref_key is None:
                continue
            plan.wanted[resolved.ref_key] = ResolvedSource(
                kind=resolved.kind,
                title=resolved.title,
                ref=resolved.ref,
                ref_key=resolved.ref_key,
                origin={
                    **(resolved.origin or {}),
                    MATERIAL_MARK: "library",
                    "course_title": course_title,
                },
            )

    async def _apply(self, notebook: Notebook, plan: _Plan) -> CourseSyncResult:
        """Write the plan under the notebook's lock."""
        now = self.clock.now()
        async with self.uow_factory() as uow:
            locked = await uow.notebooks.get_for_update(notebook.id)
            if locked is None or locked.is_deleted:
                return CourseSyncResult()
            current = await uow.sources.list_for_notebook(notebook.id)
            gone = [
                s for s in current if is_material(s) and s.ref_key not in plan.wanted
            ]
            for source in gone:
                await uow.sources.delete(source.id)
            refreshed = await self._refresh(uow, current, plan)
            added = await self._add(uow, locked, current, plan)
            locked.auto_synced_at = now
            await sources_changed(uow, locked, now)
            await uow.commit()
        if added or gone or refreshed:
            log.info(
                "notebooks_course_synced",
                notebook_id=str(notebook.id),
                added=added,
                removed=len(gone),
                refreshed=refreshed,
            )
        return CourseSyncResult(added, len(gone), refreshed)

    async def _refresh(
        self, uow: NotebooksUnitOfWork, current: list[Source], plan: _Plan
    ) -> int:
        """Mark the steps and videos of a new revision outdated and read them again."""
        count = 0
        for source in current:
            wanted = plan.wanted.get(source.ref_key or "")
            if wanted is None or not is_material(source):
                continue
            revision = wanted.ref.get("revision_id")
            if revision is None or source.ref.get("revision_id") == revision:
                continue
            source.ref = {**source.ref, "revision_id": revision}
            source.title = wanted.title
            if source.status not in REVISED:
                source.status = SourceStatus.STALE
            source.updated_at = self.clock.now()
            await uow.sources.save(source)
            uow.after_commit(
                partial(
                    self.kicker.kick,
                    "notebooks.process_source",
                    source_id=str(source.id),
                )
            )
            count += 1
        return count

    async def _add(
        self,
        uow: NotebooksUnitOfWork,
        notebook: Notebook,
        current: list[Source],
        plan: _Plan,
    ) -> int:
        """Insert the materials that are not sources yet; kick their processing."""
        have = {s.ref_key for s in current if s.ref_key is not None}
        position = await uow.sources.next_position(notebook.id)
        now = self.clock.now()
        added = 0
        for key, resolved in plan.wanted.items():
            if key in have:
                continue
            source = Source(
                id=new_id(),
                notebook_id=notebook.id,
                owner_id=notebook.owner_id,
                kind=resolved.kind,
                title=resolved.title,
                position=position + added,
                created_at=now,
                updated_at=now,
                ref=resolved.ref,
                ref_key=resolved.ref_key,
                origin=resolved.origin,
                selected=True,
                status=SourceStatus.PENDING,
            )
            await uow.sources.add(source)
            added += 1
            uow.after_commit(
                partial(
                    self.kicker.kick,
                    "notebooks.process_source",
                    source_id=str(source.id),
                )
            )
        return added


class SyncCourseNotebooks:
    """Starts a sync of every student notebook of a course (a new revision)."""

    def __init__(self, *, uow_factory: UowFactory, kicker: TaskKicker) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.kicker = kicker

    async def execute(self, course_id: UUID) -> int:
        """Kick one sync per notebook; return how many."""
        async with self.uow_factory() as uow:
            ids = await uow.notebooks.course_student_ids(course_id, AUTO_FANOUT_LIMIT)
        for notebook_id in ids:
            await self.kicker.kick(
                "notebooks.sync_course_notebook", notebook_id=str(notebook_id)
            )
        if ids:
            log.info(
                "notebooks_course_fanout", course_id=str(course_id), notebooks=len(ids)
            )
        return len(ids)
