"""Use case: the curator or Administration approves or rejects a request."""

from uuid import UUID

from app.modules.academic.application.excuses.access import ExcuseAccess
from app.modules.academic.application.excuses.notices import ExcuseNotices
from app.modules.academic.application.excuses.ports import (
    DecisionTokens,
    ExcuseDirectory,
    ExcuseUowFactory,
)
from app.modules.academic.application.excuses.views import ExcusePresenter, ExcuseView
from app.modules.academic.application.excuses.work_offs import ExcuseWorkOffs
from app.modules.academic.domain.excuses.errors import ExcuseNotFoundError
from app.shared.actor import Actor
from app.shared.clock import Clock


class DecideExcuse:
    """Decide a pending request; an approval makes work-offs for past lessons."""

    def __init__(
        self,
        *,
        uow_factory: ExcuseUowFactory,
        clock: Clock,
        directory: ExcuseDirectory,
        access: ExcuseAccess,
        notices: ExcuseNotices,
        work_offs: ExcuseWorkOffs,
        tokens: DecisionTokens,
        presenter: ExcusePresenter,
    ) -> None:
        """Store the ports."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.directory = directory
        self.access = access
        self.notices = notices
        self.work_offs = work_offs
        self.tokens = tokens
        self.presenter = presenter

    async def execute(
        self,
        *,
        actor: Actor,
        excuse_id: UUID,
        approve: bool,
        comment: str | None = None,
    ) -> ExcuseView:
        """Approve or reject and tell the student.

        Raises:
            ExcuseNotFoundError: no such excuse, or it is not of the actor's students.
            ExcuseNotPendingError: it was already decided or withdrawn.
        """
        now = self.clock.now()
        async with self.uow_factory() as uow:
            found = await uow.excuses.get(excuse_id)
            if found is None:
                raise ExcuseNotFoundError()
            excuse = await self.access.staff_side(found, actor)
            if approve:
                excuse.approve(actor.user_id, comment, now)
            else:
                excuse.reject(actor.user_id, comment, now)
            await uow.excuses.save(excuse)
            if approve:
                people = await self.directory.people([excuse.student_id])
                person = people.get(excuse.student_id)
                await self.work_offs.for_excuse(
                    uow,
                    excuse,
                    locale=person.locale if person else "ru",
                    assigned_by=actor.user_id,
                )
            self.notices.decided(uow, excuse)
            await uow.commit()
            view = await self.presenter.detail(uow, excuse)
        await self.tokens.revoke(excuse.id)
        return view
