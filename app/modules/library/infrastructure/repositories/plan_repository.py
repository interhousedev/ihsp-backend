"""SQL repository of book plans and lesson links."""

from collections.abc import Sequence
from datetime import timedelta
from uuid import UUID

from app.modules.library.domain.book_plan import BookPlan, PlanSection
from app.modules.library.domain.enums import ItemStatus, Visibility
from app.modules.library.infrastructure.orm import BookPlan as PlanRow
from app.modules.library.infrastructure.orm import Item as ItemRow
from app.modules.library.infrastructure.orm import LessonItemRef as RefRow
from app.modules.library.ports.plan_repository import LessonItemRef
from app.shared.contracts.library import LessonItemRefView
from app.shared.ids import new_id

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession


def _plan_from(row: PlanRow) -> BookPlan:
    return BookPlan(
        id=row.id,
        subject_id=row.subject_id,
        year_of_study=row.year_of_study,
        item_id=row.item_id,
        sections=tuple(
            PlanSection(
                n=int(s["n"]),
                title=str(s["title"]),
                page_from=int(s["page_from"]),
                page_to=int(s["page_to"]),
                hours=float(s["hours"]),
            )
            for s in row.sections
        ),
        updated_at=row.updated_at,
    )


def _ref_from(row: RefRow) -> LessonItemRef:
    return LessonItemRef(
        lesson_id=row.lesson_id,
        item_id=row.item_id,
        section_label=row.section_label,
        page_from=row.page_from,
        page_to=row.page_to,
        set_by=row.set_by,
        updated_at=row.updated_at,
    )


class SqlPlanRepository:
    """Stores plans in `library.book_plans` and links in `library.lesson_item_refs`."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the unit of work's session."""
        self.session = session

    # - - - Plans - - -

    async def get_plan(self, subject_id: UUID, year_of_study: int) -> BookPlan | None:
        """The plan of the subject and year (the latest when several exist)."""
        row = (
            await self.session.execute(
                select(PlanRow)
                .where(
                    PlanRow.subject_id == subject_id,
                    PlanRow.year_of_study == year_of_study,
                )
                .order_by(PlanRow.updated_at.desc(), PlanRow.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return _plan_from(row) if row else None

    async def save_plan(self, plan: BookPlan) -> None:
        """Store the plan; any other book's plan of the same subject and year goes."""
        await self.session.execute(
            delete(PlanRow).where(
                PlanRow.subject_id == plan.subject_id,
                PlanRow.year_of_study == plan.year_of_study,
                PlanRow.item_id != plan.item_id,
            )
        )
        sections = [
            {
                "n": s.n,
                "title": s.title,
                "page_from": s.page_from,
                "page_to": s.page_to,
                "hours": s.hours,
            }
            for s in plan.sections
        ]
        statement = insert(PlanRow).values(
            id=new_id(),
            subject_id=plan.subject_id,
            year_of_study=plan.year_of_study,
            item_id=plan.item_id,
            sections=sections,
            created_at=plan.updated_at,
            updated_at=plan.updated_at,
        )
        await self.session.execute(
            statement.on_conflict_do_update(
                index_elements=[
                    PlanRow.subject_id,
                    PlanRow.year_of_study,
                    PlanRow.item_id,
                ],
                set_={"sections": sections, "updated_at": plan.updated_at},
            )
        )

    # - - - Lesson links - - -

    async def list_lesson_refs(self, lesson_id: UUID) -> list[LessonItemRef]:
        """The links of the lesson in the order the teacher set them."""
        return (await self.linked_lessons([lesson_id])).get(lesson_id, [])

    async def set_lesson_refs(
        self, lesson_id: UUID, refs: Sequence[LessonItemRef]
    ) -> None:
        """Replace all links of the lesson; the order of `refs` is kept.

        The table has no position column, so `created_at` carries the order: each
        link is one microsecond after the previous one.
        """
        await self.session.execute(delete(RefRow).where(RefRow.lesson_id == lesson_id))
        for index, ref in enumerate(refs):
            self.session.add(
                RefRow(
                    id=new_id(),
                    lesson_id=lesson_id,
                    item_id=ref.item_id,
                    section_label=ref.section_label,
                    page_from=ref.page_from,
                    page_to=ref.page_to,
                    set_by=ref.set_by,
                    created_at=ref.updated_at + timedelta(microseconds=index),
                    updated_at=ref.updated_at,
                )
            )
        await self.session.flush()

    async def lesson_refs(
        self, lesson_ids: Sequence[UUID]
    ) -> dict[UUID, list[LessonItemRefView]]:
        """Links with item titles for the lessons (lessons without links are absent).

        Only items that are listed (published and not hidden) appear.
        """
        if not lesson_ids:
            return {}
        rows = await self.session.execute(
            select(RefRow, ItemRow.title)
            .join(ItemRow, ItemRow.id == RefRow.item_id)
            .where(
                RefRow.lesson_id.in_(set(lesson_ids)),
                ItemRow.status == ItemStatus.PUBLISHED.value,
                ItemRow.visibility != Visibility.HIDDEN.value,
            )
            .order_by(RefRow.lesson_id, RefRow.created_at, RefRow.id)
        )
        views: dict[UUID, list[LessonItemRefView]] = {}
        for ref, title in rows.all():
            views.setdefault(ref.lesson_id, []).append(
                LessonItemRefView(
                    item_id=ref.item_id,
                    title=title,
                    section_label=ref.section_label,
                    page_from=ref.page_from,
                    page_to=ref.page_to,
                )
            )
        return views

    async def linked_lessons(
        self, lesson_ids: Sequence[UUID]
    ) -> dict[UUID, list[LessonItemRef]]:
        """The stored links of several lessons (lessons without links are absent)."""
        if not lesson_ids:
            return {}
        rows = await self.session.execute(
            select(RefRow)
            .where(RefRow.lesson_id.in_(set(lesson_ids)))
            .order_by(RefRow.lesson_id, RefRow.created_at, RefRow.id)
        )
        grouped: dict[UUID, list[LessonItemRef]] = {}
        for row in rows.scalars():
            grouped.setdefault(row.lesson_id, []).append(_ref_from(row))
        return grouped
