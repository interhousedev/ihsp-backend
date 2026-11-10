"""Use cases of the curator over an approved excuse: end it or revoke it."""

import datetime as dt
from uuid import UUID

from app.modules.academic.application.excuses.access import ExcuseAccess
from app.modules.academic.application.excuses.notices import ExcuseNotices
from app.modules.academic.application.excuses.ports import ExcuseUowFactory
from app.modules.academic.application.excuses.views import ExcusePresenter, ExcuseView
from app.modules.academic.domain.excuses.errors import ExcuseNotFoundError
from app.shared.actor import Actor
from app.shared.clock import Clock


class EndExcuse:
    """Set the last day of an approved excuse."""

    def __init__(
        self,
        *,
        uow_factory: ExcuseUowFactory,
        clock: Clock,
        access: ExcuseAccess,
        presenter: ExcusePresenter,
    ) -> None:
        """Store the ports."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.access = access
        self.presenter = presenter

    async def execute(
        self, *, actor: Actor, excuse_id: UUID, ends_on: dt.date
    ) -> ExcuseView:
        """Close the excuse on ``ends_on``.

        Raises:
            ExcuseNotFoundError: no such excuse of the actor's students.
            ExcuseNotApprovedError: the excuse is not approved.
            ExcuseInvalidError: ``ends_on`` is before the start.
        """
        async with self.uow_factory() as uow:
            found = await uow.excuses.get(excuse_id)
            if found is None:
                raise ExcuseNotFoundError()
            excuse = await self.access.staff_side(found, actor)
            excuse.end(ends_on, self.clock.now())
            await uow.excuses.save(excuse)
            await uow.commit()
            return await self.presenter.detail(uow, excuse)


class RevokeExcuse:
    """Take an approved excuse back; the attendance lock ends with it."""

    def __init__(
        self,
        *,
        uow_factory: ExcuseUowFactory,
        clock: Clock,
        access: ExcuseAccess,
        notices: ExcuseNotices,
        presenter: ExcusePresenter,
    ) -> None:
        """Store the ports."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.access = access
        self.notices = notices
        self.presenter = presenter

    async def execute(
        self, *, actor: Actor, excuse_id: UUID, comment: str | None = None
    ) -> ExcuseView:
        """Revoke and tell the student.

        Raises:
            ExcuseNotFoundError: no such excuse of the actor's students.
            ExcuseNotApprovedError: the excuse is not approved.
        """
        async with self.uow_factory() as uow:
            found = await uow.excuses.get(excuse_id)
            if found is None:
                raise ExcuseNotFoundError()
            excuse = await self.access.staff_side(found, actor)
            excuse.revoke(actor.user_id, comment, self.clock.now())
            await uow.excuses.save(excuse)
            self.notices.decided(uow, excuse)
            await uow.commit()
            return await self.presenter.detail(uow, excuse)
