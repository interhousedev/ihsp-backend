"""Router of the onboarding tour (linked users only, buttons only)."""

from app.interfaces.bot.callbacks import OnboardingCb
from app.interfaces.bot.filters.is_linked import IsLinked
from app.interfaces.bot.routers.common.onboarding.handlers.show_step import show_step

from aiogram import Router


def build_router() -> Router:
    """Build the onboarding router."""
    router = Router(name="common.onboarding")
    router.callback_query.filter(IsLinked())
    router.callback_query.register(show_step, OnboardingCb.filter())
    return router
