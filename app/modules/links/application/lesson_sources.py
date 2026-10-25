"""Lesson sources of a subject by group, and the "hide EMIS sources" group rule."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal
from uuid import UUID

from app.modules.links.application.resource_builder import ResourceBuilder
from app.modules.links.application.room_cache_invalidator import RoomCacheInvalidator
from app.modules.links.application.views import ResourceView
from app.modules.links.domain.errors import NotTeachingSubjectError
from app.modules.links.domain.link import LessonRole, Link
from app.modules.links.ports.link_repository import LinkRepository
from app.modules.links.ports.unit_of_work import UowFactory
from app.shared.clock import Clock
from app.shared.contracts.academic import LessonGroupIndex, LessonGroupRef
from app.shared.contracts.links import EMIS_AUTHOR_ID

Origin = Literal["emis", "all"]


@dataclass(frozen=True, slots=True)
class LessonSourceView:
    """One material of one lesson, seen from one of the lesson's groups."""

    resource: ResourceView
    group_id: UUID
    group_name: str
    date: date

    @property
    def title(self) -> str:
        """``DD.MM name``: the lesson date and the material's name."""
        return f"{self.date:%d.%m} {self.resource.title}"


@dataclass(frozen=True, slots=True)
class LessonSourcePage:
    """A page of lesson sources and how many there are in all."""

    items: list[LessonSourceView]
    total: int


def _is_source(link: Link, origin: Origin) -> bool:
    if link.lesson_role is not LessonRole.MATERIAL or link.is_disabled:
        return False
    return origin == "all" or link.owner_id == EMIS_AUTHOR_ID


class ListLessonSources:
    """Materials attached to the lessons of a subject, grouped by group, newest first.

    An admin sees every lesson (``teacher_id`` None); a teacher only their own.
    """

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        index: LessonGroupIndex,
        builder: ResourceBuilder,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.index = index
        self.builder = builder

    async def execute(
        self,
        subject_id: UUID,
        *,
        teacher_id: UUID | None,
        group_id: UUID | None,
        origin: Origin,
        limit: int,
        offset: int,
    ) -> LessonSourcePage:
        """Return one page; a teacher without lessons of the subject gets 403."""
        pairs = await self.index.lesson_groups(
            subject_id=subject_id, teacher_id=teacher_id
        )
        if teacher_id is not None and not pairs:
            raise NotTeachingSubjectError(params={"subject_id": str(subject_id)})
        if group_id is not None:
            pairs = [p for p in pairs if p.group_id == group_id]
            if teacher_id is not None and not pairs:
                raise NotTeachingSubjectError(params={"group_id": str(group_id)})
        by_lesson: dict[UUID, list[LessonGroupRef]] = {}
        for pair in pairs:
            by_lesson.setdefault(pair.lesson_id, []).append(pair)
        async with self.uow_factory() as uow:
            links = await uow.links.list_for_lessons(list(by_lesson))
        links = [link for link in links if _is_source(link, origin)]
        views = await self.builder.resources(links)
        rows = [
            LessonSourceView(view, p.group_id, p.group_name, p.date)
            for view in views
            if view.link.lesson_id is not None
            for p in by_lesson.get(view.link.lesson_id, [])
        ]
        rows.sort(key=lambda r: (r.date, r.resource.link.created_at), reverse=True)
        rows.sort(key=lambda r: (r.group_name, str(r.group_id)))
        return LessonSourcePage(rows[offset : offset + limit], len(rows))


@dataclass(frozen=True, slots=True)
class EmisHidingState:
    """Whether the rule is on, and how many resources the last change touched."""

    hidden: bool
    affected: int = 0


class EmisSourcesHiding:
    """A teacher hides (or shows again) the EMIS sources of a subject for a group.

    Turning the rule on hides every visible EMIS material of the teacher's lessons of
    the subject for the group and marks them ``hidden_by_rule``; turning it off shows
    only those again (a manual hide stays). New EMIS imports respect the rule.
    """

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        index: LessonGroupIndex,
        invalidator: RoomCacheInvalidator,
        clock: Clock,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.index = index
        self.invalidator = invalidator
        self.clock = clock

    async def _pairs(
        self, teacher_id: UUID, subject_id: UUID, group_id: UUID
    ) -> list[LessonGroupRef]:
        pairs = await self.index.lesson_groups(
            subject_id=subject_id, teacher_id=teacher_id
        )
        if not any(p.group_id == group_id for p in pairs):
            raise NotTeachingSubjectError(params={"group_id": str(group_id)})
        return pairs

    async def get(
        self, teacher_id: UUID, subject_id: UUID, group_id: UUID
    ) -> EmisHidingState:
        """Return whether the rule is on."""
        await self._pairs(teacher_id, subject_id, group_id)
        async with self.uow_factory() as uow:
            rules = await uow.links.hide_rules([teacher_id])
        return EmisHidingState((teacher_id, subject_id, group_id) in rules)

    async def set(
        self, teacher_id: UUID, subject_id: UUID, group_id: UUID, *, hidden: bool
    ) -> EmisHidingState:
        """Turn the rule on or off and hide or show the matching EMIS materials."""
        pairs = await self._pairs(teacher_id, subject_id, group_id)
        lessons = list(
            dict.fromkeys(p.lesson_id for p in pairs if p.group_id == group_id)
        )
        now = self.clock.now()
        changed: list[UUID] = []
        async with self.uow_factory() as uow:
            await uow.links.set_hide_rule(
                teacher_id, subject_id, group_id, on=hidden, now=now
            )
            rules = await uow.links.hide_rules([teacher_id])
            covered = {
                p.lesson_id
                for p in pairs
                if (teacher_id, subject_id, p.group_id) in rules
            }
            for link in await self._emis(uow.links, lessons):
                if hidden and not link.is_hidden:
                    link.hide(teacher_id, now, by_rule=True)
                elif not hidden and link.hidden_by_rule:
                    if link.lesson_id in covered:
                        continue  # another group of the lesson still hides it
                    link.unhide()
                else:
                    continue
                await uow.links.save(link)
                if link.lesson_id is not None:
                    changed.append(link.lesson_id)
            await uow.commit()
        await self.invalidator.lesson_ids(changed)
        return EmisHidingState(hidden, len(changed))

    @staticmethod
    async def _emis(repo: LinkRepository, lessons: Sequence[UUID]) -> list[Link]:
        if not lessons:
            return []
        return [
            link
            for link in await repo.list_for_lessons(lessons)
            if link.owner_id == EMIS_AUTHOR_ID
            and link.lesson_role is LessonRole.MATERIAL
        ]


class EmisImportHiding:
    """Tells the EMIS import which new materials start hidden, and by whom."""

    def __init__(self, index: LessonGroupIndex) -> None:
        """Store the lesson index."""
        self.index = index

    async def hidden_by(
        self, repo: LinkRepository, lesson_ids: Sequence[UUID]
    ) -> dict[UUID, UUID]:
        """Return lesson id -> teacher id for lessons a "hide EMIS" rule covers."""
        if not lesson_ids:
            return {}
        pairs = await self.index.lesson_groups(lesson_ids=list(lesson_ids))
        teachers = list({p.teacher_id for p in pairs if p.teacher_id is not None})
        rules = await repo.hide_rules(teachers)
        return {
            p.lesson_id: p.teacher_id
            for p in pairs
            if p.teacher_id is not None
            and (p.teacher_id, p.subject_id, p.group_id) in rules
        }
