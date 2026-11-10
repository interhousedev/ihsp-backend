"""Give or don't give the offered MCP permissions (A7)."""

from app.interfaces.bot.services import BotServices
from app.interfaces.bot.utilities.navigation import menu_button
from app.interfaces.bot.utilities.reply_edit import answer_callback, show
from app.modules.identity.domain.scope_offer import DecideResult
from app.shared.contracts.callbacks import McpScopeCb
from app.shared.contracts.identity import UserRef
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext

from aiogram.enums import ChatType
from aiogram.types import CallbackQuery, Message

_TOASTS = {
    DecideResult.ALREADY_DECIDED: "mcp-offer-already-decided",
    DecideResult.EXPIRED: "mcp-offer-expired",
    DecideResult.NOT_AVAILABLE: "mcp-offer-not-available",
}
_DECISIONS = {"g": True, "n": False}


def _in_private_chat(callback: CallbackQuery) -> bool:
    message = callback.message
    return isinstance(message, Message) and message.chat.type == ChatType.PRIVATE


async def decide(
    callback: CallbackQuery,
    callback_data: McpScopeCb,
    services: BotServices,
    i18n: I18nContext,
    user: UserRef | None = None,
) -> None:
    """Only the linked owner, in a private chat, can decide; others learn nothing."""
    grant = _DECISIONS.get(callback_data.d)
    if user is None or grant is None or not _in_private_chat(callback):
        await answer_callback(callback, i18n(_TOASTS[DecideResult.NOT_AVAILABLE]))
        return
    decision = await services.decide_scope_offer.execute(
        callback_data.t, user.id, grant=grant
    )
    toast = _TOASTS.get(decision.result)
    if toast is not None:
        await answer_callback(callback, i18n(toast))
        return
    await answer_callback(callback)
    key = (
        "mcp-offer-granted"
        if decision.result == DecideResult.GRANTED
        else "mcp-offer-declined"
    )
    button = {"text": i18n("mcp-offer-btn-manage"), "url": services.urls.connectors}
    await show(
        callback,
        RenderedMessage(text_html=i18n(key), buttons=[[button], [menu_button(i18n)]]),
    )
