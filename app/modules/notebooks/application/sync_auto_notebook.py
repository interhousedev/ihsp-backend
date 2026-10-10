"""Job `notebooks.sync_auto_notebook`: keep an auto notebook's sources current."""

from dataclasses import dataclass, replace
from datetime import date
from functools import partial
from uuid import UUID

from app.modules.notebooks.application.auto_targets import AutoTargets
from app.modules.notebooks.application.default_material_sources import (
    DefaultMaterialSources,
)
from app.modules.notebooks.application.notebook_state import sources_changed
from app.modules.notebooks.application.readers.base import ResolvedSource
from app.modules.notebooks.application.readers.registry import SourceReaders
from app.modules.notebooks.domain.auto_notebook import (
    AutoCandidate,
    rank_candidates,
)
from app.modules.notebooks.domain.default_materials import (
    DefaultMaterial,
    default_material_of,
    is_default_copy,
)
from app.modules.notebooks.domain.entities import AutoSettings, Notebook, Source
from app.modules.notebooks.domain.enums import NotebookOrigin, SourceKind, SourceStatus
from app.modules.notebooks.domain.errors import (
    SourceForbiddenError,
    SourceUnsupportedError,
)
from app.modules.notebooks.domain.source_input import LibraryItemInput
from app.modules.notebooks.ports.unit_of_work import NotebooksUnitOfWork, UowFactory
from app.settings import Settings
from app.shared.base_error import BaseError
from app.shared.clock import Clock
from app.shared.contracts.academic import LessonRef
from app.shared.contracts.library import LessonItemRefView, LibraryQueries
from app.shared.contracts.links import LinksApi, ResourceRef
from app.shared.ids import new_id
from app.shared.tasks import TaskKicker

import structlog

log = structlog.get_logger(__name__)

LESSON_ROLES = ("material", "attachment", "homework")
_EPOCH = date.min
BOOK_MARK = "lesson_book"  # origin key of a book the sync added for a lesson


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
    new: list[ResolvedSource]
    skipped: int = 0


def book_ident(item_id: object, page_from: int | None, page_to: int | None) -> str:
    """Names a book link of a lesson (item and asked-for pages), before it is read."""
    return f"{item_id}:{page_from or ''}:{page_to or ''}"


def is_lesson_book(source: Source) -> bool:
    """A book the sync added because a lesson follows it."""
    return source.kind is SourceKind.LIBRARY_ITEM and bool(
        (source.origin or {}).get(BOOK_MARK)
    )


def is_managed(source: Source) -> bool:
    """A source the sync owns.

    That is a lesson material, a book a lesson follows, or a copy of a default
    material of the subject. Notes, pasted texts and books the student added
    themselves are their own.
    """
    if source.ref_key is None:
        return False
    if source.kind is SourceKind.LESSON_RESOURCE or is_default_copy(source):
        return True
    return is_lesson_book(source)


class SyncAutoNotebook:
    """Adds new lesson materials, drops those the student may no longer see.

    The sources of a subject or lesson notebook are exactly the lesson materials of
    that subject (this term) or lesson that the student can see, minus the ones they
    excluded, plus classmates' files when switched on, plus the copies of the default
    materials of the subject (its EMIS id). Anything else in the notebook (notes,
    saved outputs) is left alone. Safe to run twice and from several places at once:
    the notebook row is locked for the write.
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
        defaults: DefaultMaterialSources,
        library: LibraryQueries | None = None,
    ) -> None:
        """Store the collaborators (`library` may be missing: no books then)."""
        self.library = library
        self.defaults = defaults
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
        defaults = await self._defaults_of(notebook, lessons)
        plan = await self._plan(notebook, existing, lessons, candidates, defaults)
        return await self._apply(notebook, plan)

    # - - - Steps - - -

    async def _defaults_of(
        self, notebook: Notebook, lessons: list[LessonRef]
    ) -> list[DefaultMaterial]:
        """The default materials of the notebook's subject (subject notebooks only).

        Only while the student still has lessons of the subject this term: otherwise
        the sync takes the copies out, as it does with the lesson materials.
        """
        if (
            notebook.origin is not NotebookOrigin.SUBJECT_AUTO
            or notebook.subject_id is None
            or not lessons
        ):
            return []
        edu_subject_id = await self.targets.emis_subject_id(notebook.subject_id)
        if edu_subject_id is None:
            return []
        async with self.uow_factory() as uow:
            return await uow.default_materials.list_for_subject(edu_subject_id)

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
        defaults: list[DefaultMaterial],
    ) -> _Plan:
        """Walk the wanted materials best first until the notebook is full.

        The default materials come first: they are kept whatever the room is.
        """
        settings = notebook.auto_settings
        assert settings is not None  # an auto notebook always has settings
        by_key = {item.ref_key: (item, resource) for item, resource in candidates}
        ranked = rank_candidates(
            [item for item, _ in candidates],
            include_classmates=settings.include_classmates,
            excluded=settings.excluded_keys,
        )
        stored = {s.ref_key for s in existing if is_managed(s)}
        room = self.settings.notebooks.max_sources - sum(
            1 for s in existing if not is_managed(s)
        )
        lesson_by_id = {lesson.id: lesson for lesson in lessons}
        plan = _Plan(keep=set(), new=[])
        await self._plan_defaults(notebook, existing, defaults, settings, plan)
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
            plan.new.append(resolved)
        await self._plan_books(notebook, existing, lessons, room, plan)
        return plan

    async def _plan_defaults(
        self,
        notebook: Notebook,
        existing: list[Source],
        defaults: list[DefaultMaterial],
        settings: AutoSettings,
        plan: _Plan,
    ) -> None:
        """Keep the copy of each default material, or make it; excluded ones stay out.

        A copy that is there is kept without reading its material again.
        """
        copies = {default_material_of(s): s for s in existing if is_default_copy(s)}
        for material in defaults:
            copy = copies.get(str(material.id))
            if copy is not None:
                if copy.ref_key and copy.ref_key not in settings.excluded_keys:
                    plan.keep.add(copy.ref_key)
                continue
            if len(plan.keep) >= self.settings.notebooks.max_sources:
                plan.skipped += 1  # the notebook is full
                continue
            resolved = await self.defaults.resolve(notebook.owner_id, material)
            if resolved is None:
                plan.skipped += 1  # not ready or not readable yet: a later sync
                continue
            if resolved.ref_key is None or resolved.ref_key in settings.excluded_keys:
                continue
            plan.keep.add(resolved.ref_key)
            plan.new.append(resolved)

    async def _plan_books(
        self,
        notebook: Notebook,
        existing: list[Source],
        lessons: list[LessonRef],
        room: int,
        plan: _Plan,
    ) -> None:
        """Add the library books the lessons follow, after the materials.

        A book already in the notebook is kept without reading it again; a new one
        is read once to check access and text. The student's exclusions win.
        """
        reader = self.readers.library_reader
        if self.library is None or reader is None or not lessons:
            return
        settings = notebook.auto_settings
        assert settings is not None
        stored = {
            str(s.origin[BOOK_MARK]): s.ref_key
            for s in existing
            if is_managed(s) and s.ref_key and s.origin and is_lesson_book(s)
        }
        by_lesson = await self.library.lesson_item_refs([x.id for x in lessons])
        # Newest lesson first: its books win when the notebook is full.
        order = {x.id: x.date for x in lessons}
        seen: set[str] = set()
        for lesson_id in sorted(
            by_lesson, key=lambda i: order.get(i, _EPOCH), reverse=True
        ):
            if lesson_id not in order:
                continue
            for link in by_lesson[lesson_id]:
                if len(plan.keep) >= room:
                    return
                ident = book_ident(link.item_id, link.page_from, link.page_to)
                if ident in seen:
                    continue
                seen.add(ident)
                await self._plan_book(notebook, link, ident, stored, settings, plan)

    async def _plan_book(
        self,
        notebook: Notebook,
        link: LessonItemRefView,
        ident: str,
        stored: dict[str, str],
        settings: AutoSettings,
        plan: _Plan,
    ) -> None:
        """Keep a stored book, or read a new one and queue it."""
        kept = stored.get(ident)
        if kept is not None:
            if kept not in settings.excluded_keys:
                plan.keep.add(kept)
            return
        reader = self.readers.library_reader
        assert reader is not None
        try:
            resolved = await reader.resolve(
                notebook.owner_id,
                LibraryItemInput(
                    item_id=link.item_id,
                    page_from=link.page_from,
                    page_to=link.page_to,
                ),
            )
        except (BaseError, ValueError):
            plan.skipped += 1  # no text yet, held back or too large: not now
            return
        key = resolved.ref_key
        if key is None or key in settings.excluded_keys:
            return
        resolved = replace(
            resolved, origin={**(resolved.origin or {}), BOOK_MARK: ident}
        )
        plan.keep.add(key)
        plan.new.append(resolved)

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
            gone = [s for s in current if is_managed(s) and s.ref_key not in plan.keep]
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
        for resolved in plan.new:
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
