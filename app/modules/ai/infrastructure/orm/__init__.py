"""ORM models of the ai module (schema ``ai``; flash cards are in their own module)."""

from app.modules.ai.infrastructure.orm.chat import Chat
from app.modules.ai.infrastructure.orm.chat_message import ChatMessage

__all__ = ["Chat", "ChatMessage"]
