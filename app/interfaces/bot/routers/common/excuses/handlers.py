"""Approve or reject an excuse request from the curator's Telegram."""

from app.interfaces.bot.services import BotServices
from app.interfaces.bot.utilities.markup import web_app_button
from app.interfaces.bot.utilities.navigation import menu_button
from app.interfaces.bot.utilities.reply_edit import answer_callback, show
from app.modules.academic.domain.excuses.errors import (
    ExcuseNotFoundError,
    ExcuseNotPendingError,
)
from app.modules.academic.domain.excuses.excuse import ExcuseStatus
from app.shared.contracts.callbacks import ExcuseCb
from app.shared.contracts.identity import UserRef
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext

from aiogram.enums import ChatType
from aiogram.types import CallbackQuery, Message

_RESULT_KEYS = {
    ExcuseStatus.APPROVED: "excuse-bot-approved",
    ExcuseStatus.REJECTED: "excuse-bot-rejected",
}


def _in_private_chat(callback: CallbackQuery) -> bool:
    message = callback.message
    return isinstance(message, Message) and message.chat.type == ChatType.PRIVATE


async def decide(
    callback: CallbackQuery,
    callback_data: ExcuseCb,
    services: BotServices,
    i18n: I18nContext,
    user: UserRef | None = None,
) -> None:
    """Only the linked recipient, in a private chat, can use the token."""
    if user is None or not _in_private_chat(callback):
        await answer_callback(callback, i18n("excuse-bot-not-available"))
        return
    try:
        status = await services.decide_excuse_by_token.execute(
            user_id=user.id, token=callback_data.t, roles=user.roles
        )
    except ExcuseNotPendingError:
        await answer_callback(callback, i18n("excuse-bot-already-decided"))
        return
    except ExcuseNotFoundError:
        await answer_callback(callback, i18n("excuse-bot-not-available"))
        return
    await answer_callback(callback)
    await show(
        callback,
        RenderedMessage(
            text_html=i18n(_RESULT_KEYS.get(status, "excuse-bot-approved")),
            buttons=[
                [
                    web_app_button(
                        i18n("bot-btn-open-in-app"),
                        services.urls.page(user.roles, "excuses/"),
                    )
                ],
                [menu_button(i18n)],
            ],
        ),
    )
