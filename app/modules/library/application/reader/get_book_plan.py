"""Read the textbook plan of a subject and year of study (LIB-11)."""

from uuid import UUID

from app.modules.library.application.reader.plan_rules import ensure_plan_reader
from app.modules.library.application.reader.views import BookPlanView
from app.modules.library.domain.access import can_view
from app.modules.library.ports.directories import AcademicDirectory
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor


class GetBookPlan:
    """`GET /v1/library/book-plans`: None when there is no plan or no visible book."""

    def __init__(self, *, uow_factory: UowFactory, academic: AcademicDirectory) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory
        self.academic = academic

    async def execute(
        self, actor: Actor, *, subject_id: UUID, year_of_study: int
    ) -> BookPlanView | None:
        """The plan with the title of its book (a book the caller cannot see: None)."""
        ensure_plan_reader(actor)
        async with self.uow_factory() as uow:
            plan = await uow.plans.get_plan(subject_id, year_of_study)
            if plan is None:
                return None
            item = await uow.items.get(plan.item_id)
        if item is None or not can_view(item, actor):
            return None
        return BookPlanView(
            subject_id=plan.subject_id,
            year_of_study=plan.year_of_study,
            item_id=plan.item_id,
            item_title=item.title,
            sections=plan.sections,
            updated_at=plan.updated_at,
        )
