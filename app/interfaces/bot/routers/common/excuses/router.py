"""Router of the excuse buttons (before the guest router)."""

from app.interfaces.bot.routers.common.excuses.handlers import decide
from app.shared.contracts.callbacks import ExcuseCb

from aiogram import Router


def build_router() -> Router:
    """Build the router of the excuse request's buttons."""
    router = Router(name="common.excuses")
    router.callback_query.register(decide, ExcuseCb.filter())
    return router
