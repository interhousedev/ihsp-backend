"""ORM models of the ai module (schema ``ai``; flash cards are in their own module)."""

from app.modules.ai.infrastructure.orm.chat import Chat
from app.modules.ai.infrastructure.orm.chat_message import ChatMessage
from app.modules.ai.infrastructure.orm.project import Project, ProjectFile
from app.modules.ai.infrastructure.orm.prompt_version import PromptVersionRow
from app.modules.ai.infrastructure.orm.telegram_topic import TelegramTopicRow
from app.modules.ai.infrastructure.orm.usage_event import UsageEventRow
from app.modules.ai.infrastructure.orm.web_page import WebPageRow, WebQueryRow

__all__ = [
    "Chat",
    "ChatMessage",
    "Project",
    "ProjectFile",
    "PromptVersionRow",
    "TelegramTopicRow",
    "UsageEventRow",
    "WebPageRow",
    "WebQueryRow",
]
