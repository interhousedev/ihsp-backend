"""Buttons of the feedback flow; every step keeps Cancel (BOT-4)."""

from app.interfaces.bot.keyboards import cancel
from app.interfaces.bot.routers.common.feedback.callbacks import (
    FeedbackAreaCb,
    FeedbackKindCb,
    FeedbackStepCb,
)
from app.interfaces.bot.routers.common.feedback.rules import AREA_LABELS, KIND_LABELS
from app.interfaces.bot.utilities.markup import Rows, cb_button, pairs
from app.shared.contracts.callbacks import CancelCb
from app.shared.i18n.core import I18nContext


def kinds(i18n: I18nContext) -> Rows:
    """Idea, Bug, Other, then Cancel."""
    row = [
        cb_button(i18n(label), FeedbackKindCb(kind=kind))
        for kind, label in KIND_LABELS.items()
    ]
    return [row, *cancel.get(i18n)]


def areas(i18n: I18nContext) -> Rows:
    """The areas, two per row, then Cancel."""
    buttons = [
        cb_button(i18n(label), FeedbackAreaCb(area=area))
        for area, label in AREA_LABELS.items()
    ]
    return [*pairs(buttons), *cancel.get(i18n)]


def attachments(i18n: I18nContext) -> Rows:
    """Done (keep the files sent so far) or Skip (no files), then Cancel."""
    row = [
        cb_button(i18n("bot-btn-done"), FeedbackStepCb(action="done")),
        cb_button(i18n("bot-btn-skip"), FeedbackStepCb(action="skip")),
    ]
    return [row, *cancel.get(i18n)]


def summary(i18n: I18nContext) -> Rows:
    """Send the report or Cancel it."""
    row = [
        cb_button(i18n("bot-btn-send"), FeedbackStepCb(action="send")),
        cb_button(i18n("bot-btn-cancel"), CancelCb()),
    ]
    return [row]
