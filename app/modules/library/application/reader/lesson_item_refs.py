"""Book links of a lesson: read them, set them, suggest the next section (LIB-11)."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.library.application.reader.lesson_access import (
    lesson_for_reader,
    lesson_for_teacher,
)
from app.modules.library.application.reader.plan_rules import load_pageable_item
from app.modules.library.application.reader.views import NextSectionView
from app.modules.library.domain.access import can_view
from app.modules.library.domain.book_plan import find_section, next_section
from app.modules.library.domain.reader_lesson_ref import LessonRefInput, validate_refs
from app.modules.library.ports.lesson_directory import LessonDirectory
from app.modules.library.ports.plan_repository import LessonItemRef
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.contracts.library import LessonItemRefView

HISTORY_LIMIT = 30


class GetLessonItemRefs:
    """`GET /v1/me/lessons/{lesson_id}/item-refs`: links the viewer may open."""

    def __init__(self, *, uow_factory: UowFactory, lessons: LessonDirectory) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory
        self.lessons = lessons

    async def execute(self, actor: Actor, lesson_id: UUID) -> list[LessonItemRefView]:
        """The links in the order the teacher set them, hidden books left out."""
        await lesson_for_reader(self.lessons, actor, lesson_id)
        async with self.uow_factory() as uow:
            found = await uow.plans.lesson_refs([lesson_id])
        return found.get(lesson_id, [])


class SetLessonItemRefs:
    """`PUT /v1/staff/lessons/{lesson_id}/item-refs`: never touches the topic."""

    def __init__(
        self, *, uow_factory: UowFactory, lessons: LessonDirectory, clock: Clock
    ) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory
        self.lessons = lessons
        self.clock = clock

    async def execute(
        self, actor: Actor, lesson_id: UUID, refs: Sequence[LessonRefInput]
    ) -> list[LessonItemRefView]:
        """Replace all links of the lesson (its teacher, or Administration)."""
        await lesson_for_teacher(self.lessons, actor, lesson_id)
        checked = validate_refs(refs)
        async with self.uow_factory() as uow:
            for ref in checked:
                await load_pageable_item(uow, actor, ref.item_id)
            now = self.clock.now()
            await uow.plans.set_lesson_refs(
                lesson_id,
                [
                    LessonItemRef(
                        lesson_id=lesson_id,
                        item_id=ref.item_id,
                        section_label=ref.section_label.strip(),
                        page_from=ref.page_from,
                        page_to=ref.page_to,
                        set_by=actor.user_id,
                        updated_at=now,
                    )
                    for ref in checked
                ],
            )
            await uow.commit()
            found = await uow.plans.lesson_refs([lesson_id])
        return found.get(lesson_id, [])


class SuggestNextSection:
    """`GET /v1/staff/library/book-plans/next?lesson_id`: the section after the last."""

    def __init__(self, *, uow_factory: UowFactory, lessons: LessonDirectory) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory
        self.lessons = lessons

    async def execute(self, actor: Actor, lesson_id: UUID) -> NextSectionView | None:
        """The next section of the plan, or None (no plan, or the book is done)."""
        lesson = await lesson_for_teacher(self.lessons, actor, lesson_id)
        if not lesson.years_of_study:
            return None
        earlier = await self.lessons.earlier_lessons(lesson_id, limit=HISTORY_LIMIT)
        async with self.uow_factory() as uow:
            plan = await uow.plans.get_plan(lesson.subject_id, lesson.years_of_study[0])
            if plan is None:
                return None
            item = await uow.items.get(plan.item_id)
            if item is None or not can_view(item, actor):
                return None
            linked = await uow.plans.linked_lessons(earlier)
        last: int | None = None
        for earlier_id in earlier:
            hits = [
                find_section(
                    plan.sections,
                    label=ref.section_label,
                    page_from=ref.page_from,
                    page_to=ref.page_to,
                )
                for ref in linked.get(earlier_id, [])
                if ref.item_id == plan.item_id
            ]
            known = [index for index in hits if index is not None]
            if known:
                last = max(known)
                break
        section = next_section(plan.sections, last=last)
        if section is None:
            return None
        return NextSectionView(item_id=item.id, item_title=item.title, section=section)
