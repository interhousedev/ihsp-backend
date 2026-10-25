"""Edit a draft or scheduled broadcast (UF-ADM-08 alternative 4a)."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from uuid import UUID

from app.modules.admin.application.broadcast_text import (
    ensure_fits,
    sanitize_telegram_html,
)
from app.modules.admin.application.broadcast_view import (
    BroadcastPresenter,
    BroadcastView,
)
from app.modules.admin.domain.audience import Audience
from app.modules.admin.ports.unit_of_work import AdminUnitOfWork
from app.shared.actor import Actor, Role


@dataclass(frozen=True, slots=True)
class BroadcastPatch:
    """Fields to change; None means "leave as it is"."""

    title: str | None = None
    text: str | None = None
    media_file_ids: Sequence[UUID] | None = None
    audience: Audience | None = None


class UpdateBroadcast:
    """Applies a partial edit to a broadcast that has not started."""

    def __init__(
        self,
        *,
        uow_factory: Callable[[], AdminUnitOfWork],
        presenter: BroadcastPresenter,
    ) -> None:
        """Store the unit of work factory and the presenter."""
        self.uow_factory = uow_factory
        self.presenter = presenter

    async def execute(
        self, actor: Actor, broadcast_id: UUID, patch: BroadcastPatch
    ) -> BroadcastView:
        """Change the given fields; sending and finished broadcasts are refused."""
        actor.require(Role.ADMIN)
        async with self.uow_factory() as uow:
            broadcast = await uow.broadcasts.get(broadcast_id, for_update=True)
            broadcast.ensure_editable()
            if patch.title is not None:
                broadcast.title = patch.title.strip()
            if patch.text is not None:
                broadcast.text = sanitize_telegram_html(patch.text)
            if patch.media_file_ids is not None:
                broadcast.media_file_ids = list(patch.media_file_ids)
            if patch.audience is not None:
                broadcast.audience = patch.audience
            ensure_fits(broadcast.title, broadcast.text)
            await uow.broadcasts.save(broadcast)
            await uow.commit()
            return (await self.presenter.present(uow, [broadcast]))[0]
