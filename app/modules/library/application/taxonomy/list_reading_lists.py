"""List the reading lists the caller may see (LIB-4)."""

from uuid import UUID

from app.modules.library.application.locale import resolve_locale
from app.modules.library.application.taxonomy.reading_list_builder import (
    ReadingListBuilder,
)
from app.modules.library.application.taxonomy.views import ReadingListCardView
from app.modules.library.domain.enums import ListStatus
from app.modules.library.domain.reading_list_policy import can_view_list
from app.modules.library.ports.directories import AcademicDirectory
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor, Role
from app.shared.contracts.identity import IdentityDirectory


class ListReadingLists:
    """`GET /v1/library/reading-lists?subject_id&mine&group_id&status`."""

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
        self,
        actor: Actor,
        *,
        subject_id: UUID | None = None,
        mine: bool = False,
        group_id: UUID | None = None,
        status: ListStatus | None = None,
        accept_language: str | None = None,
    ) -> list[ReadingListCardView]:
        """Lists matching the filters that the caller may open, newest change first."""
        locale = await resolve_locale(self.identity, actor, accept_language)
        own_group = (
            await self.academic.student_group_id(actor.user_id)
            if Role.STUDENT in actor.roles
            else None
        )
        async with self.uow_factory() as uow:
            found = await uow.lists.find(
                subject_id=subject_id,
                owner_id=actor.user_id if mine else None,
                group_id=group_id,
                status=status,
            )
            visible = [
                lst for lst in found if can_view_list(lst, actor, group_id=own_group)
            ]
            return await self.builder.cards_for(
                uow, visible, viewer=actor, locale=locale
            )
