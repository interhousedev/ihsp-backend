"""Use case: a teacher's temporary marks that are not in EMIS yet (TMP-3)."""

from collections.abc import Callable
from uuid import UUID

from app.modules.academic.application.classwork.ports.unit_of_work import (
    TemporaryMarkUnitOfWork,
)
from app.modules.academic.application.classwork.temporary_mark_views import (
    TemporaryMarkViews,
)
from app.modules.academic.domain.classwork.temporary_mark import TemporaryMarkView
from app.shared.actor import Actor, Role


class ListPendingTemporaryMarks:
    """The pending marks on the teacher's lessons, oldest lesson first."""

    def __init__(
        self,
        uow_factory: Callable[[], TemporaryMarkUnitOfWork],
        views: TemporaryMarkViews,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.views = views

    async def execute(
        self, actor: Actor, *, locale: str | None = None, teacher_id: UUID | None = None
    ) -> list[TemporaryMarkView]:
        """Return pending marks.

        A teacher always gets their own lessons' marks; Administration gets the
        given teacher's, or every teacher's when ``teacher_id`` is None.
        """
        if not actor.has(Role.ADMIN):
            teacher_id = actor.user_id
        locale = locale or await self.views.people.locale(actor.user_id)
        async with self.uow_factory() as uow:
            marks = await uow.temporary_marks.pending(teacher_id)
            return await self.views.build(uow, marks, locale)
