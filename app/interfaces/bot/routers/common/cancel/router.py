"""Router for Cancel and label buttons; first in line, works in every state."""

from app.interfaces.bot.routers.common.cancel.handlers.cancel import cancel
from app.interfaces.bot.routers.common.cancel.handlers.none import none
from app.interfaces.bot.utilities.markup import NONE_DATA
from app.shared.contracts.callbacks import CancelCb

from aiogram import F, Router
from aiogram.filters import Command, StateFilter


def build_router() -> Router:
    """Build the cancel router."""
    router = Router(name="common.cancel")
    router.message.register(cancel, StateFilter("*"), Command("cancel"))
    router.callback_query.register(cancel, StateFilter("*"), CancelCb.filter())
    router.callback_query.register(none, StateFilter("*"), F.data == NONE_DATA)
    return router
