"""Save the textbook plan of a subject and year of study (LIB-11)."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.library.application.reader.plan_rules import (
    ensure_plan_rights,
    load_pageable_item,
)
from app.modules.library.application.reader.views import BookPlanView
from app.modules.library.domain.book_plan import (
    BookPlan,
    PlanSection,
    validate_sections,
)
from app.modules.library.domain.enums import ItemKind
from app.modules.library.ports.directories import AcademicDirectory
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.ids import new_id


class PutBookPlan:
    """`PUT /v1/library/book-plans`: one textbook per subject and year."""

    def __init__(
        self, *, uow_factory: UowFactory, clock: Clock, academic: AcademicDirectory
    ) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.academic = academic

    async def execute(
        self,
        actor: Actor,
        *,
        subject_id: UUID,
        year_of_study: int,
        item_id: UUID,
        sections: Sequence[PlanSection],
    ) -> BookPlanView:
        """Replace the plan; choosing another book replaces the former one."""
        await ensure_plan_rights(self.academic, actor, subject_id)
        async with self.uow_factory() as uow:
            item = await load_pageable_item(uow, actor, item_id)
            # Only a book has a trusted length; a material's page count may be a guess.
            length = item.page_count if item.kind is ItemKind.BOOK else None
            checked = validate_sections(sections, page_count=length)
            plan = BookPlan(
                id=new_id(),
                subject_id=subject_id,
                year_of_study=year_of_study,
                item_id=item_id,
                sections=tuple(checked),
                updated_at=self.clock.now(),
            )
            await uow.plans.save_plan(plan)
            await uow.commit()
        return BookPlanView(
            subject_id=subject_id,
            year_of_study=year_of_study,
            item_id=item_id,
            item_title=item.title,
            sections=plan.sections,
            updated_at=plan.updated_at,
        )
