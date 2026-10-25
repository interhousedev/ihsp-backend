"""DELETE /v1/id/me/telegram/{id}: unlink an account (logs it out of the bot)."""

from dataclasses import dataclass

from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.audit_event import TELEGRAM_UNLINKED
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.base_error import NotFoundError


@dataclass(frozen=True, slots=True)
class UnlinkTelegramAccount:
    """Deletes one of the caller's links."""

    uow_factory: UowFactory

    async def execute(
        self, actor: Actor, telegram_user_id: int, ctx: RequestContext
    ) -> None:
        """Unlink the account or raise NotFoundError."""
        async with self.uow_factory() as uow:
            link = await uow.telegram_links.get(telegram_user_id)
            if link is None or link.user_id != actor.user_id:
                raise NotFoundError(params={"telegram_user_id": telegram_user_id})
            await uow.telegram_links.delete(telegram_user_id)
            uow.audit(
                make_audit(
                    TELEGRAM_UNLINKED,
                    user_id=actor.user_id,
                    ctx=ctx,
                    telegram_user_id=telegram_user_id,
                )
            )
            await uow.commit()
