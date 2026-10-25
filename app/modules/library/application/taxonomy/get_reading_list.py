"""Open one reading list with its entries and my read status (LIB-4)."""

from uuid import UUID

from app.modules.library.application.locale import resolve_locale
from app.modules.library.application.taxonomy.reading_list_builder import (
    ReadingListBuilder,
)
from app.modules.library.application.taxonomy.views import ReadingListDetailView
from app.modules.library.domain.errors import ListNotFoundError
from app.modules.library.domain.reading_list_policy import can_view_list
from app.modules.library.ports.directories import AcademicDirectory
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor, Role
from app.shared.contracts.identity import IdentityDirectory


class GetReadingList:
    """`GET /v1/library/reading-lists/{id}`: a list the caller may not see is 404."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        identity: IdentityDirectory,
        academic: AcademicDirectory,
        builder: ReadingListBuilder,
    ) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory
        self.identity = identity
        self.academic = academic
        self.builder = builder

    async def execute(
        self, actor: Actor, list_id: UUID, *, accept_language: str | None = None
    ) -> ReadingListDetailView:
        """The list, its visible entries as cards and the caller's read states."""
        locale = await resolve_locale(self.identity, actor, accept_language)
        own_group = (
            await self.academic.student_group_id(actor.user_id)
            if Role.STUDENT in actor.roles
            else None
        )
        async with self.uow_factory() as uow:
            reading_list = await uow.lists.get(list_id)
            if reading_list is None or not can_view_list(
                reading_list, actor, group_id=own_group
            ):
                raise ListNotFoundError(params={"list_id": str(list_id)})
            return await self.builder.detail_for(
                uow, reading_list, viewer=actor, locale=locale
            )
