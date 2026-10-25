"""Messages of the feedback flow, and the summary of the report being made."""

from typing import Any

from app.interfaces.bot.keyboards import cancel
from app.interfaces.bot.routers.common.feedback import keyboards
from app.interfaces.bot.routers.common.feedback.rules import (
    AREA_LABELS,
    KIND_LABELS,
    MAX_FILES,
)
from app.interfaces.bot.utilities.html import escape
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext


def ask(i18n: I18nContext, key: str, **params: Any) -> RenderedMessage:
    """A message of a text step: the text and Cancel."""
    return RenderedMessage(text_html=i18n(key, **params), buttons=cancel.get(i18n))


def attaching(i18n: I18nContext, key: str, **params: Any) -> RenderedMessage:
    """A message of the attachments step: the text and Done, Skip, Cancel."""
    return RenderedMessage(
        text_html=i18n(key, limit=MAX_FILES, **params),
        buttons=keyboards.attachments(i18n),
    )


def summary(data: dict[str, Any], i18n: I18nContext) -> RenderedMessage:
    """What will be sent, with Send and Cancel."""
    text = i18n(
        "bot-feedback-summary",
        kind=i18n(KIND_LABELS[data["kind"]]),
        area=i18n(AREA_LABELS[data["area"]]),
        title=escape(data["title"]),
        description=escape(data["description"]),
        files=len(data.get("files", [])),
    )
    return RenderedMessage(text_html=text, buttons=keyboards.summary(i18n))
