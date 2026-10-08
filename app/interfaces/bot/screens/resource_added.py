"""Confirmation after a resource was attached to a lesson (UF-BOT-09)."""

from app.interfaces.bot.keyboards import open_lesson
from app.interfaces.bot.urls import BotUrls
from app.interfaces.bot.utilities.html import escape
from app.interfaces.bot.utilities.markup import web_app_button
from app.shared.contracts.links import ResourceRef
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext


def build_resource_added(
    resource: ResourceRef, i18n: I18nContext, urls: BotUrls
) -> RenderedMessage:
    """Show the short link and Open lesson."""
    return RenderedMessage(
        text_html=i18n(
            "bot-resource-added",
            title=escape(resource.title),
            url=escape(resource.short_url),
        ),
        buttons=open_lesson.get(i18n, urls.staff_lesson(resource.lesson_id)),
    )


def build_resource_refused(
    i18n: I18nContext, text: str, urls: BotUrls
) -> RenderedMessage:
    """Refuse a file (too large or not allowed) and point to the staff portal."""
    return RenderedMessage(
        text_html=text,
        buttons=[[web_app_button(i18n("bot-btn-staff-portal"), urls.staff)]],
    )
