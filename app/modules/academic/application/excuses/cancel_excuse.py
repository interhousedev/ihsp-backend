"""Use case: the student withdraws a pending request."""

from uuid import UUID

from app.modules.academic.application.excuses.access import ExcuseAccess
from app.modules.academic.application.excuses.ports import (
    DecisionTokens,
    ExcuseUowFactory,
)
from app.modules.academic.application.excuses.views import ExcusePresenter, ExcuseView
from app.shared.actor import Actor
from app.shared.clock import Clock


class CancelExcuse:
    """Only the student's own pending request can be cancelled."""

    def __init__(
        self,
        *,
        uow_factory: ExcuseUowFactory,
        clock: Clock,
        access: ExcuseAccess,
        tokens: DecisionTokens,
        presenter: ExcusePresenter,
    ) -> None:
        """Store the ports."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.access = access
        self.tokens = tokens
        self.presenter = presenter

    async def execute(self, *, actor: Actor, excuse_id: UUID) -> ExcuseView:
        """Cancel the request.

        Raises:
            ExcuseNotFoundError: no such excuse of the caller.
            ExcuseNotPendingError: it was already decided.
        """
        async with self.uow_factory() as uow:
            excuse = self.access.student_side(await uow.excuses.get(excuse_id), actor)
            excuse.cancel(self.clock.now())
            await uow.excuses.save(excuse)
            await uow.commit()
            view = await self.presenter.detail(uow, excuse)
        await self.tokens.revoke(excuse.id)
        return view
