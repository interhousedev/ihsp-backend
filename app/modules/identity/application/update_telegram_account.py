"""PATCH /v1/id/me/telegram/{id}: turn OTP delivery on or off for one account."""

from dataclasses import dataclass

from app.modules.identity.domain.telegram_link import TelegramLink
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.base_error import NotFoundError


@dataclass(frozen=True, slots=True)
class UpdateTelegramAccount:
    """Changes the OTP delivery flag of one of the caller's links (ID-21)."""

    uow_factory: UowFactory

    async def execute(
        self, actor: Actor, telegram_user_id: int, *, otp_delivery: bool
    ) -> TelegramLink:
        """Return the updated link."""
        async with self.uow_factory() as uow:
            link = await uow.telegram_links.get(telegram_user_id)
            if link is None or link.user_id != actor.user_id:
                raise NotFoundError(params={"telegram_user_id": telegram_user_id})
            link.otp_delivery = otp_delivery
            await uow.telegram_links.save(link)
            await uow.commit()
        return link
