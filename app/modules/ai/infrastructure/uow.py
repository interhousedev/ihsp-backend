"""SQL unit of work of the ai module."""

from app.modules.ai.infrastructure.repositories.chat_repository import (
    SqlChatRepository,
)
from app.modules.ai.infrastructure.repositories.message_repository import (
    SqlMessageRepository,
)
from app.modules.ai.infrastructure.repositories.web_page_repository import (
    SqlWebPageRepository,
)
from app.shared.db.uow import SqlUnitOfWork


class SqlAiUnitOfWork(SqlUnitOfWork):
    """One transaction over chats, messages and the stored web pages."""

    chats: SqlChatRepository
    messages: SqlMessageRepository
    web_pages: SqlWebPageRepository

    def _init_repos(self) -> None:
        """Create the repositories on the open session."""
        self.chats = SqlChatRepository(self.session)
        self.messages = SqlMessageRepository(self.session)
        self.web_pages = SqlWebPageRepository(self.session)
