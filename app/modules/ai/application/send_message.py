"""Use case: the user writes a message and the assistant answers (AI-2, AI-7)."""

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from app.modules.ai.application.assistant_profile import effective_tier, profile_for
from app.modules.ai.application.budget import BudgetService
from app.modules.ai.application.continue_turn import ContinueTurn
from app.modules.ai.application.locale import LocaleResolver
from app.modules.ai.application.owned_chat import ChatGuard
from app.modules.ai.application.pending_calls import supersede_pending
from app.modules.ai.application.turn_result import TurnResults
from app.modules.ai.application.views import TurnResultView
from app.modules.ai.domain.chat import (
    Attachment,
    Chat,
    ChatMessage,
    ChatTier,
    MessageContent,
    MessageRole,
    title_from_text,
)
from app.modules.ai.domain.errors import (
    AiLimitReachedError,
    AiSmartLimitReachedError,
    AttachmentInvalidError,
    ChatNotFoundError,
)
from app.modules.ai.ports.turn_lock import TurnLock
from app.modules.ai.ports.unit_of_work import AiUnitOfWork
from app.settings import Settings
from app.shared.actor import Actor
from app.shared.agent_steps import StepKind, StepRecorder, record_step, recording
from app.shared.clock import Clock
from app.shared.contracts.files import FilesApi
from app.shared.contracts.web_search import WebResult, WebSearchApi
from app.shared.ids import new_id
from app.shared.slash_commands import stored_text
from app.shared.web_citations import numbered
from app.shared.web_urls import normalise_web_url

CITED_TAIL = 200  # the latest messages of a chat whose cited pages are not new to it


class SendMessage:
    """Stores the message, supersedes pending approvals and runs the turn."""

    def __init__(
        self,
        *,
        uow_factory: Callable[[], AiUnitOfWork],
        guard: ChatGuard,
        files: FilesApi,
        continue_turn: ContinueTurn,
        budget: BudgetService,
        locks: TurnLock,
        locale: LocaleResolver,
        results: TurnResults,
        web: WebSearchApi,
        clock: Clock,
        settings: Settings,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.guard = guard
        self.files = files
        self.continue_turn = continue_turn
        self.budget = budget
        self.locks = locks
        self.locale = locale
        self.results = results
        self.web = web
        self.clock = clock
        self.settings = settings

    async def execute(
        self,
        *,
        actor: Actor,
        chat_id: UUID,
        text: str,
        file_ids: list[UUID],
        web_search: bool = False,
        command: str | None = None,
        args: str = "",
    ) -> TurnResultView:
        """Run the turn for a new user message.

        With `web_search` one search of the day is spent and its pages go with the
        message (nothing is stored when the search is refused or fails). A message on
        the smart tier counts one of the week's smart requests, given back when the
        message is not stored. A slash command (`command` + `args`, or `/name args`
        typed in `text`) is stored in its short form and expanded for the model; an
        unknown name raises `UnknownCommandError` before anything is stored.
        """
        text = stored_text(command, args, text)
        locale = await self.locale.locale_of(actor.user_id)
        async with self.locks.hold(chat_id):
            async with self.uow_factory() as uow:
                chat = await self.guard.owned(uow, actor, chat_id)
            await self.guard.admit_message(actor, chat)
            await self._require_budget(chat, text, locale)
            attachments = await self._attachments(actor, file_ids)
            smart = effective_tier(chat.assistant, chat.tier) is ChatTier.SMART
            if smart:
                await self._require_smart_quota(actor, chat)
            with recording(StepRecorder()):  # AI-STEPS of this answer
                try:
                    found = await self._search(actor, chat_id, text, locale, web_search)
                    changed = await self._append(chat, text, attachments, found)
                except BaseException:
                    if smart:
                        await self.budget.release_smart(actor.user_id)
                    raise
                _record_inputs(attachments, web_search, found)
                progress = await self.continue_turn.execute(
                    chat_id=chat_id, actor=actor, locale=locale, changed=changed
                )
        return await self.results.build(actor, locale, progress)

    async def _require_budget(self, chat: Chat, text: str, locale: str) -> None:
        """Refuse a message the user cannot afford, before anything is stored."""
        hit = await self.continue_turn.precheck(chat, text, locale)
        if hit is not None:
            raise AiLimitReachedError(params=hit.params())

    async def _require_smart_quota(self, actor: Actor, chat: Chat) -> None:
        """Count one smart request of the week, or refuse before anything is stored."""
        limit = await self.budget.smart_limit(actor)
        hit = await self.budget.reserve_smart(actor.user_id, limit)
        if hit is not None:
            raise AiSmartLimitReachedError(params=hit.params())

    async def _search(
        self, actor: Actor, chat_id: UUID, text: str, locale: str, wanted: bool
    ) -> list[WebResult]:
        """The numbered pages of the web search (none when it is off).

        The pages this chat already cited are not new to it.
        """
        if not wanted:
            return []
        outcome = await self.web.search(
            actor,
            query=text,
            locale=locale,
            kind="chat",
            known_urls=await self._cited_urls(chat_id),
        )
        return numbered(outcome.hits)

    async def _cited_urls(self, chat_id: UUID) -> frozenset[str]:
        """The normalised URLs of the pages the chat's earlier answers cited."""
        async with self.uow_factory() as uow:
            messages = await uow.messages.list_tail(chat_id, CITED_TAIL)
        urls: set[str] = set()
        for message in messages:
            for result in message.content.web:
                key = normalise_web_url(result.url)
                if key is not None:
                    urls.add(key)
        return frozenset(urls)

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
        self,
        chat: Chat,
        text: str,
        attachments: list[Attachment],
        web: list[WebResult],
    ) -> list[ChatMessage]:
        now = self.clock.now()
        async with self.uow_factory() as uow:
            locked = await uow.chats.get_for_update(chat.id)
            if locked is None:
                raise ChatNotFoundError()
            changed = await supersede_pending(uow, locked, now)
            seq = await uow.messages.last_seq(chat.id) + 1
            message = _user_message(chat.id, seq, text, attachments, web, now)
            await uow.messages.add(message)
            if seq == 1:
                locked.title = title_from_text(text) or locked.title
            locked.model = profile_for(
                locked.assistant, self.settings, locked.tier
            ).model
            locked.last_message_at = now
            await uow.chats.save(locked)
            await uow.commit()
        return [*changed, message]


def _record_inputs(
    attachments: list[Attachment], searched: bool, found: list[WebResult]
) -> None:
    """The steps before the model answers: the files it reads, the web search."""
    for item in attachments:
        record_step(
            StepKind.READ_FILE,
            "Reviewed uploaded file",
            target=item.name,
            ref=str(item.file_id),
        )
    if searched:
        record_step(
            StepKind.WEB_SEARCH, "Searched the web", target=f"{len(found)} results"
        )


def _user_message(
    chat_id: UUID,
    seq: int,
    text: str,
    attachments: list[Attachment],
    web: list[WebResult],
    now: datetime,
) -> ChatMessage:
    return ChatMessage(
        id=new_id(),
        chat_id=chat_id,
        seq=seq,
        role=MessageRole.USER,
        content=MessageContent(text=text, attachments=attachments, web=web),
        created_at=now,
        file_ids=[a.file_id for a in attachments],
    )
