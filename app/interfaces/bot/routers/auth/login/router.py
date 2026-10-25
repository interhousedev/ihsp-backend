"""Router for Telegram accounts that are not linked to an IHSP account."""

from app.interfaces.bot.filters.is_linked import IsLinked
from app.interfaces.bot.routers.auth.login.handlers.show_login import show_login

from aiogram import Router


def register_filters(router: Router) -> None:
    """Only unlinked accounts reach these handlers."""
    router.message.filter(~IsLinked())
    router.callback_query.filter(~IsLinked())


def build_router() -> Router:
    """Build the login router."""
    router = Router(name="auth.login")
    register_filters(router)
    router.message.register(show_login)
    router.callback_query.register(show_login)
    return router
