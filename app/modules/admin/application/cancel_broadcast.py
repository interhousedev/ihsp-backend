"""Cancel a scheduled broadcast (UF-ADM-08 alternative 4a)."""

from collections.abc import Callable
from uuid import UUID

from app.modules.admin.application.broadcast_view import (
    BroadcastPresenter,
    BroadcastView,
)
from app.modules.admin.ports.unit_of_work import AdminUnitOfWork
from app.shared.actor import Actor, Role


class CancelBroadcast:
    """Stops a broadcast that has not started yet."""

    def __init__(
        self,
        *,
        uow_factory: Callable[[], AdminUnitOfWork],
        presenter: BroadcastPresenter,
    ) -> None:
        """Store the unit of work factory and the presenter."""
        self.uow_factory = uow_factory
        self.presenter = presenter

    async def execute(self, actor: Actor, broadcast_id: UUID) -> BroadcastView:
        """Cancel; anything but a scheduled broadcast is refused."""
        actor.require(Role.ADMIN)
        async with self.uow_factory() as uow:
            broadcast = await uow.broadcasts.get(broadcast_id, for_update=True)
            broadcast.cancel()
            await uow.broadcasts.save(broadcast)
            await uow.commit()
            return (await self.presenter.present(uow, [broadcast]))[0]
