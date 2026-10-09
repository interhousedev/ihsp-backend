"""Job `notebooks.sync_auto_notebook`: keep an auto notebook's sources current."""

from dataclasses import dataclass
from functools import partial
from uuid import UUID

from app.modules.notebooks.application.auto_targets import AutoTargets
from app.modules.notebooks.application.notebook_state import sources_changed
from app.modules.notebooks.application.readers.base import ResolvedSource
from app.modules.notebooks.application.readers.registry import SourceReaders
from app.modules.notebooks.domain.auto_notebook import (
    AutoCandidate,
    rank_candidates,
)
from app.modules.notebooks.domain.entities import Notebook, Source
from app.modules.notebooks.domain.enums import SourceKind, SourceStatus
from app.modules.notebooks.domain.errors import (
    SourceForbiddenError,
    SourceUnsupportedError,
)
from app.modules.notebooks.ports.unit_of_work import NotebooksUnitOfWork, UowFactory
from app.settings import Settings
from app.shared.clock import Clock
from app.shared.contracts.academic import LessonRef
from app.shared.contracts.links import LinksApi, ResourceRef
from app.shared.ids import new_id
from app.shared.tasks import TaskKicker

import structlog

log = structlog.get_logger(__name__)

LESSON_ROLES = ("material", "attachment")


@dataclass(frozen=True, slots=True)
class AutoSyncResult:
    """What one sync changed."""

    added: int = 0
    removed: int = 0
    skipped: int = 0  # materials without readable text yet (picked up next time)


@dataclass(slots=True)
class _Plan:
    """What the notebook should hold: kept keys, and the new sources to describe."""

    keep: set[str]
    new: list[tuple[AutoCandidate, ResolvedSource]]
    skipped: int = 0


def _is_managed(source: Source) -> bool:
    """A source the sync owns: a lesson material (notes are the student's own)."""
    return source.kind is SourceKind.LESSON_RESOURCE and source.ref_key is not None


class SyncAutoNotebook:
    """Adds new lesson materials, drops those the student may no longer see.

    The sources of a subject or lesson notebook are exactly the lesson materials of
    that subject (this term) or lesson that the student can see, minus the ones they
    excluded, plus classmates' files when switched on. Anything else in the
    notebook (notes, saved outputs) is left alone. Safe to run twice and from
    several places at once: the notebook row is locked for the write.
    """

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        clock: Clock,
        settings: Settings,
        readers: SourceReaders,
        links: LinksApi,
        targets: AutoTargets,
        kicker: TaskKicker,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.settings = settings
        self.readers = readers
        self.links = links
        self.targets = targets
        self.kicker = kicker

    async def execute(self, notebook_id: UUID) -> AutoSyncResult:
        """Bring the notebook in line with the materials; return what changed."""
        async with self.uow_factory() as uow:
            notebook = await uow.notebooks.get(notebook_id)
            if notebook is None or notebook.is_deleted or not notebook.is_auto:
                return AutoSyncResult()
            existing = await uow.sources.list_for_notebook(notebook_id)
        lessons = await self.targets.lessons_of(notebook)
        candidates = await self._candidates(notebook, lessons)
        plan = await self._plan(notebook, existing, lessons, candidates)
        return await self._apply(notebook, plan)

    # - - - Steps - - -

    async def _candidates(
        self, notebook: Notebook, lessons: list[LessonRef]
    ) -> list[tuple[AutoCandidate, ResourceRef]]:
        """The materials of the lessons that are listed (not hidden, not revoked)."""
        found = await self.links.resources_for_lessons([x.id for x in lessons])
        dates = {lesson.id: lesson.date for lesson in lessons}
        return [
            (
                AutoCandidate(
                    link_id=resource.link_id,
                    lesson_id=resource.lesson_id,
                    lesson_date=dates[resource.lesson_id],
                    role=resource.role,
                    own=resource.author_id == notebook.owner_id,
                ),
                resource,
            )
            for resources in found.values()
            for resource in resources
            if resource.role in LESSON_ROLES
            and not resource.hidden
            and resource.lesson_id in dates
        ]

    async def _plan(
        self,
        notebook: Notebook,
        existing: list[Source],
        lessons: list[LessonRef],
        candidates: list[tuple[AutoCandidate, ResourceRef]],
    ) -> _Plan:
        """Walk the wanted materials best first until the notebook is full."""
        settings = notebook.auto_settings
        assert settings is not None  # an auto notebook always has settings
        by_key = {item.ref_key: (item, resource) for item, resource in candidates}
        ranked = rank_candidates(
            [item for item, _ in candidates],
            include_classmates=settings.include_classmates,
            excluded=settings.excluded_keys,
        )
        stored = {s.ref_key for s in existing if _is_managed(s)}
        room = self.settings.notebooks.max_sources - sum(
            1 for s in existing if not _is_managed(s)
        )
        lesson_by_id = {lesson.id: lesson for lesson in lessons}
        plan = _Plan(keep=set(), new=[])
        for item in ranked:
            if len(plan.keep) >= room:
                break
            if item.ref_key in stored:
                plan.keep.add(item.ref_key)
                continue
            resource = by_key[item.ref_key][1]
            resolved = await self._describe(item, resource, lesson_by_id)
            if resolved is None:
                plan.skipped += 1
                continue
            plan.keep.add(item.ref_key)
            plan.new.append((item, resolved))
        return plan

    async def _describe(
        self,
        item: AutoCandidate,
        resource: ResourceRef,
        lessons: dict[UUID, LessonRef],
    ) -> ResolvedSource | None:
        """The new source of a material, or None while it has no readable text."""
        try:
            return await self.readers.lesson_reader.describe(
                resource,
                lessons[item.lesson_id],
                from_classmates=item.from_classmates,
            )
        except (SourceUnsupportedError, SourceForbiddenError):
            return None

    async def _apply(self, notebook: Notebook, plan: _Plan) -> AutoSyncResult:
        """Write the plan under the notebook's lock."""
        now = self.clock.now()
        async with self.uow_factory() as uow:
            locked = await uow.notebooks.get_for_update(notebook.id)
            if (
                locked is None
                or locked.is_deleted
                or locked.auto_settings != notebook.auto_settings
            ):
                return AutoSyncResult()  # settings changed: that writer syncs itself
            current = await uow.sources.list_for_notebook(notebook.id)
            gone = [s for s in current if _is_managed(s) and s.ref_key not in plan.keep]
            for source in gone:
                await uow.sources.delete(source.id)
            fresh = await self._add(uow, locked, current, plan)
            locked.auto_synced_at = now
            await sources_changed(uow, locked, now)
            await uow.commit()
        log.info(
            "notebooks_auto_synced",
            notebook_id=str(notebook.id),
            origin=notebook.origin.value,
            added=len(fresh),
            removed=len(gone),
            skipped=plan.skipped,
        )
        return AutoSyncResult(len(fresh), len(gone), plan.skipped)

    async def _add(
        self,
        uow: NotebooksUnitOfWork,
        notebook: Notebook,
        current: list[Source],
        plan: _Plan,
    ) -> list[Source]:
        """Insert the materials that are not sources yet; kick their processing."""
        have = {s.ref_key for s in current if s.ref_key is not None}
        position = await uow.sources.next_position(notebook.id)
        now = self.clock.now()
        added: list[Source] = []
        for _item, resolved in plan.new:
            if resolved.ref_key in have:
                continue
            source = Source(
                id=new_id(),
                notebook_id=notebook.id,
                owner_id=notebook.owner_id,
                kind=resolved.kind,
                title=resolved.title,
                position=position + len(added),
                created_at=now,
                updated_at=now,
                ref=resolved.ref,
                ref_key=resolved.ref_key,
                origin=resolved.origin,
                selected=True,
                status=SourceStatus.PENDING,
            )
            await uow.sources.add(source)
            added.append(source)
            uow.after_commit(
                partial(
                    self.kicker.kick,
                    "notebooks.process_source",
                    source_id=str(source.id),
                )
            )
        return added
