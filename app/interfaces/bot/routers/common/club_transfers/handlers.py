"""Accept or decline a club ownership offer from the recipient's Telegram."""

from app.interfaces.bot.services import BotServices
from app.interfaces.bot.utilities.markup import web_app_button
from app.interfaces.bot.utilities.navigation import menu_button
from app.interfaces.bot.utilities.reply_edit import answer_callback, show
from app.modules.activities.domain.access import PermissionDeniedError
from app.modules.activities.domain.errors import ActivitiesNotFoundError
from app.modules.activities.domain.ownership import TransferError
from app.shared.actor import Actor
from app.shared.contracts.callbacks import ClubTransferCb
from app.shared.contracts.identity import UserRef
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext
from app.shared.ids import b64_to_uuid

from aiogram.enums import ChatType
from aiogram.types import CallbackQuery, Message


def _in_private_chat(callback: CallbackQuery) -> bool:
    message = callback.message
    return isinstance(message, Message) and message.chat.type == ChatType.PRIVATE


async def decide(
    callback: CallbackQuery,
    callback_data: ClubTransferCb,
    services: BotServices,
    i18n: I18nContext,
    user: UserRef | None = None,
) -> None:
    """Only the linked recipient, in a private chat, can answer the offer."""
    if user is None or not _in_private_chat(callback):
        await answer_callback(callback, i18n("club-transfer-bot-not-available"))
        return
    actor = Actor(user_id=user.id, roles=user.roles)
    accept = callback_data.d == "a"
    try:
        transfer_id = b64_to_uuid(callback_data.t)
        if accept:
            await services.club_transfers.accept(actor, transfer_id)
        else:
            await services.club_transfers.decline(actor, transfer_id)
    except TransferError:
        await answer_callback(callback, i18n("club-transfer-bot-already-answered"))
        return
    except (ActivitiesNotFoundError, PermissionDeniedError, ValueError):
        await answer_callback(callback, i18n("club-transfer-bot-not-available"))
        return
    await answer_callback(callback)
    key = "club-transfer-bot-accepted" if accept else "club-transfer-bot-declined"
    await show(
        callback,
        RenderedMessage(
            text_html=i18n(key),
            buttons=[
                [
                    web_app_button(
                        i18n("bot-btn-open-in-app"),
                        services.urls.page(user.roles, "activities/"),
                    )
                ],
                [menu_button(i18n)],
            ],
        ),
    )
