"""The onboarding tour shown once an account is linked."""

from app.interfaces.bot.keyboards import onboarding
from app.interfaces.bot.urls import BotUrls
from app.interfaces.bot.utilities.html import escape
from app.shared.contracts.identity import UserRef
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext


def build_onboarding(
    user: UserRef, i18n: I18nContext, urls: BotUrls, step: str = "welcome"
) -> RenderedMessage:
    """One step of the tour; an unknown step gives the first one."""
    if step not in onboarding.STEPS:
        step = "welcome"
    text = i18n(
        f"onboarding-{step}",
        name=escape(user.first_name),
        login=escape(user.login or ""),
    )
    return RenderedMessage(
        text_html=text, buttons=onboarding.get(i18n, step, user.roles, urls)
    )
