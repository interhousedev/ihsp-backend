"""One step of the onboarding tour."""

from app.interfaces.bot.callbacks import OnboardingCb
from app.interfaces.bot.screens.onboarding import build_onboarding
from app.interfaces.bot.services import BotServices
from app.interfaces.bot.utilities.reply_edit import show
from app.shared.contracts.identity import UserRef
from app.shared.i18n.core import I18nContext

from aiogram.types import CallbackQuery


async def show_step(
    query: CallbackQuery,
    callback_data: OnboardingCb,
    user: UserRef,
    services: BotServices,
    i18n: I18nContext,
) -> None:
    """Edit the tour message to the pressed step."""
    await show(query, build_onboarding(user, i18n, services.urls, callback_data.step))
