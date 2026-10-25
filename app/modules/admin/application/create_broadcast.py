"""Create a broadcast draft (ADM-11, UF-ADM-08 step 1)."""

from collections.abc import Callable, Sequence
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
from app.modules.admin.domain.broadcast import Broadcast, CreatedVia
from app.modules.admin.ports.unit_of_work import AdminUnitOfWork
from app.shared.actor import Actor, Role
from app.shared.clock import Clock
from app.shared.ids import new_id


class CreateBroadcast:
    """Saves a new draft; the assistant can create drafts too, never send them."""

    def __init__(
        self,
        *,
        uow_factory: Callable[[], AdminUnitOfWork],
        presenter: BroadcastPresenter,
        clock: Clock,
    ) -> None:
        """Store the unit of work factory, the presenter and the clock."""
        self.uow_factory = uow_factory
        self.presenter = presenter
        self.clock = clock

    async def execute(
        self,
        actor: Actor,
        *,
        title: str,
        text: str,
        media_file_ids: Sequence[UUID],
        audience: Audience,
        created_via: CreatedVia = CreatedVia.UI,
    ) -> BroadcastView:
        """Validate the text, store the draft and return it."""
        actor.require(Role.ADMIN)
        clean_text = sanitize_telegram_html(text)
        ensure_fits(title, clean_text)
        broadcast = Broadcast(
            id=new_id(),
            author_id=actor.user_id,
            created_via=created_via,
            title=title.strip(),
            text=clean_text,
            audience=audience,
            media_file_ids=list(media_file_ids),
            created_at=self.clock.now(),
        )
        async with self.uow_factory() as uow:
            await uow.broadcasts.add(broadcast)
            await uow.commit()
            return (await self.presenter.present(uow, [broadcast]))[0]
