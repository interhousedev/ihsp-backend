"""Telegram notice that the assistant answered while the user was away."""

from app.modules.notify.application.renderers.described import DescribedRenderer
from app.shared.notifications import NotificationType


class ChatAnswerReadyRenderer(DescribedRenderer):
    """The question and a button to the chat in the student app."""

    notification_type = NotificationType.CHAT_ANSWER_READY
    link_button_key = "notify-btn-open-chat"
