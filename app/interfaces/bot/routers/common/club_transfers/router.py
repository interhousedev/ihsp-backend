"""Router of the club ownership buttons (before the guest router)."""

from app.interfaces.bot.routers.common.club_transfers.handlers import decide
from app.shared.contracts.callbacks import ClubTransferCb

from aiogram import Router


def build_router() -> Router:
    """Build the router of the ownership offer's buttons."""
    router = Router(name="common.club_transfers")
    router.callback_query.register(decide, ClubTransferCb.filter())
    return router
