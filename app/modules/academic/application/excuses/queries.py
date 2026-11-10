"""Read use cases: lists, detail and templates of excuses."""

from uuid import UUID

from app.modules.academic.application.excuses.access import ExcuseAccess
from app.modules.academic.application.excuses.ports import (
    ExcuseDirectory,
    ExcuseUowFactory,
)
from app.modules.academic.application.excuses.views import ExcusePresenter, ExcuseView
from app.modules.academic.domain.excuses.errors import ExcuseNotFoundError
from app.modules.academic.domain.excuses.excuse import ExcuseStatus, ExcuseTemplate
from app.shared.actor import Actor, Role
from app.shared.pagination import decode_cursor, encode_cursor

PAGE_SIZE = 50


class ListExcuses:
    """The caller's own excuses, or those of the students they curate."""

    def __init__(
        self,
        *,
        uow_factory: ExcuseUowFactory,
        directory: ExcuseDirectory,
        presenter: ExcusePresenter,
    ) -> None:
        """Store the ports."""
        self.uow_factory = uow_factory
        self.directory = directory
        self.presenter = presenter

    async def mine(
        self, *, actor: Actor, status: ExcuseStatus | None, cursor: str | None
    ) -> tuple[list[ExcuseView], str | None]:
        """Excuses of the caller as a student."""
        return await self._page([actor.user_id], status, cursor)

    async def staff(
        self,
        *,
        actor: Actor,
        status: ExcuseStatus | None,
        student_id: UUID | None,
        cursor: str | None,
    ) -> tuple[list[ExcuseView], str | None]:
        """Administration sees every student; a curator the students of their groups."""
        if actor.has(Role.ADMIN):
            return await self._page(
                None if student_id is None else [student_id], status, cursor
            )
        curated = await self.directory.curated_student_ids(actor.user_id)
        if student_id is not None:
            curated = [s for s in curated if s == student_id]
        return await self._page(curated, status, cursor)

    async def _page(
        self,
        student_ids: list[UUID] | None,
        status: ExcuseStatus | None,
        cursor: str | None,
    ) -> tuple[list[ExcuseView], str | None]:
        if student_ids is not None and not student_ids:
            return [], None
        data = decode_cursor(cursor)
        offset = int(data["o"]) if data and "o" in data else 0
        async with self.uow_factory() as uow:
            rows = await uow.excuses.search(
                student_ids=student_ids,
                status=status,
                offset=max(offset, 0),
                limit=PAGE_SIZE + 1,
            )
            views = await self.presenter.items(uow, rows[:PAGE_SIZE])
        more = len(rows) > PAGE_SIZE
        return views, encode_cursor({"o": offset + PAGE_SIZE}) if more else None


class GetExcuse:
    """One excuse with its thread."""

    def __init__(
        self,
        *,
        uow_factory: ExcuseUowFactory,
        access: ExcuseAccess,
        presenter: ExcusePresenter,
    ) -> None:
        """Store the ports."""
        self.uow_factory = uow_factory
        self.access = access
        self.presenter = presenter

    async def execute(self, *, actor: Actor, excuse_id: UUID) -> ExcuseView:
        """Return the excuse for its student, curator or Administration.

        Raises:
            ExcuseNotFoundError: no such excuse, or it is a stranger's.
        """
        async with self.uow_factory() as uow:
            found = await uow.excuses.get(excuse_id)
            if found is None:
                raise ExcuseNotFoundError()
            excuse = await self.access.either_side(found, actor)
            return await self.presenter.detail(uow, excuse)


class ListExcuseTemplates:
    """Active reason templates for the request form."""

    def __init__(self, *, uow_factory: ExcuseUowFactory) -> None:
        """Store the transaction factory."""
        self.uow_factory = uow_factory

    async def execute(self) -> list[ExcuseTemplate]:
        """Active templates in display order."""
        async with self.uow_factory() as uow:
            return await uow.excuses.templates(active_only=True)
