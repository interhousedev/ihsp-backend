"""Use case: the user writes a message and the assistant answers (AI-2, AI-7)."""

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from app.modules.ai.application.assistant_profile import (
    profile_for,
    require_assistant_role,
)
from app.modules.ai.application.continue_turn import ContinueTurn
from app.modules.ai.application.locale import LocaleResolver
from app.modules.ai.application.pending_calls import supersede_pending
from app.modules.ai.application.turn_result import TurnResults
from app.modules.ai.application.views import TurnResultView
from app.modules.ai.domain.chat import (
    Attachment,
    Chat,
    ChatMessage,
    MessageContent,
    MessageRole,
    title_from_text,
)
from app.modules.ai.domain.errors import (
    AiLimitReachedError,
    AttachmentInvalidError,
    ChatNotFoundError,
)
from app.modules.ai.ports.turn_lock import TurnLock
from app.modules.ai.ports.unit_of_work import AiUnitOfWork
from app.settings import Settings
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.contracts.files import FilesApi
from app.shared.ids import new_id


class SendMessage:
    """Stores the message, supersedes pending approvals and runs the turn."""

    def __init__(
        self,
        *,
        uow_factory: Callable[[], AiUnitOfWork],
        files: FilesApi,
        continue_turn: ContinueTurn,
        locks: TurnLock,
        locale: LocaleResolver,
        results: TurnResults,
        clock: Clock,
        settings: Settings,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.files = files
        self.continue_turn = continue_turn
        self.locks = locks
        self.locale = locale
        self.results = results
        self.clock = clock
        self.settings = settings

    async def execute(
        self, *, actor: Actor, chat_id: UUID, text: str, file_ids: list[UUID]
    ) -> TurnResultView:
        """Run the turn for a new user message."""
        locale = await self.locale.locale_of(actor.user_id)
        async with self.locks.hold(chat_id):
            chat = await self._owned_chat(actor, chat_id)
            await self._require_budget(chat, text, locale)
            attachments = await self._attachments(actor, file_ids)
            changed = await self._append(chat, text, attachments)
            progress = await self.continue_turn.execute(
                chat_id=chat_id, actor=actor, locale=locale, changed=changed
            )
        return await self.results.build(actor.user_id, locale, progress)

    async def _owned_chat(self, actor: Actor, chat_id: UUID) -> Chat:
        async with self.uow_factory() as uow:
            chat = await uow.chats.get(chat_id)
        if chat is None or chat.deleted_at or chat.owner_id != actor.user_id:
            raise ChatNotFoundError()
        require_assistant_role(actor, chat.assistant)
        return chat

    async def _require_budget(self, chat: Chat, text: str, locale: str) -> None:
        """Refuse a message the user cannot afford, before anything is stored."""
        hit = await self.continue_turn.precheck(chat, text, locale)
        if hit is not None:
            raise AiLimitReachedError(
                params={"scope": hit.scope, "resets_at": hit.resets_at.isoformat()}
            )

    async def _attachments(
        self, actor: Actor, file_ids: list[UUID]
    ) -> list[Attachment]:
        if not file_ids:
            return []
        found = await self.files.get_many(file_ids)
        attachments: list[Attachment] = []
        for file_id in dict.fromkeys(file_ids):
            ref = found.get(file_id)
            if ref is None or ref.owner_id != actor.user_id or ref.status != "ready":
                raise AttachmentInvalidError(params={"file_id": str(file_id)})
            attachments.append(Attachment(file_id=file_id, name=ref.name))
        return attachments

    async def _append(
        self, chat: Chat, text: str, attachments: list[Attachment]
    ) -> list[ChatMessage]:
        now = self.clock.now()
        async with self.uow_factory() as uow:
            locked = await uow.chats.get_for_update(chat.id)
            if locked is None:
                raise ChatNotFoundError()
            changed = await supersede_pending(uow, locked, now)
            seq = await uow.messages.last_seq(chat.id) + 1
            message = _user_message(chat.id, seq, text, attachments, now)
            await uow.messages.add(message)
            if seq == 1:
                locked.title = title_from_text(text) or locked.title
            locked.model = profile_for(locked.assistant, self.settings).model
            locked.last_message_at = now
            await uow.chats.save(locked)
            await uow.commit()
        return [*changed, message]


def _user_message(
    chat_id: UUID, seq: int, text: str, attachments: list[Attachment], now: datetime
) -> ChatMessage:
    return ChatMessage(
        id=new_id(),
        chat_id=chat_id,
        seq=seq,
        role=MessageRole.USER,
        content=MessageContent(text=text, attachments=attachments),
        created_at=now,
        file_ids=[a.file_id for a in attachments],
    )
