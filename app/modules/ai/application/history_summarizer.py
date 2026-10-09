"""Summaries of long chats (README AI-9; plan step 7)."""

from collections.abc import Callable

from app.modules.ai.application.budget import BudgetService
from app.modules.ai.domain.chat import Chat
from app.modules.ai.domain.errors import AiProviderError
from app.modules.ai.domain.history import SUMMARY_EVERY, WINDOW_MESSAGES
from app.modules.ai.domain.prompts import SUMMARY_SYSTEM_PROMPT
from app.modules.ai.domain.transcript import render_transcript
from app.modules.ai.ports.summary_store import StoredSummary, SummaryStore
from app.modules.ai.ports.unit_of_work import AiUnitOfWork
from app.settings import Settings
from app.shared.ai_tasks import AiTask
from app.shared.contracts.ai import LlmGateway

import structlog

log = structlog.get_logger(__name__)

SUMMARY_MAX_TOKENS = 400


class HistorySummarizer:
    """Keeps a short summary of everything older than the message window."""

    def __init__(
        self,
        uow_factory: Callable[[], AiUnitOfWork],
        store: SummaryStore,
        llm: LlmGateway,
        budget: BudgetService,
        settings: Settings,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.store = store
        self.llm = llm
        self.budget = budget
        self.settings = settings

    async def context(self, chat: Chat, last_seq: int) -> tuple[str | None, int]:
        """Return (summary, after_seq): messages after `after_seq` go in full."""
        if last_seq <= WINDOW_MESSAGES:
            return None, 0
        target = last_seq - WINDOW_MESSAGES
        stored = await self.store.get(chat.id)
        if stored is None or target - stored.upto_seq >= SUMMARY_EVERY:
            stored = await self._refresh(chat, stored, target) or stored
        if stored is None:
            return None, target
        return stored.text, stored.upto_seq

    async def _refresh(
        self, chat: Chat, previous: StoredSummary | None, target: int
    ) -> StoredSummary | None:
        after = previous.upto_seq if previous else 0
        async with self.uow_factory() as uow:
            fresh = await uow.messages.list_range(
                chat.id, after_seq=after, up_to_seq=target
            )
        transcript = render_transcript(previous.text if previous else None, fresh)
        text = await self._ask(chat, transcript)
        if not text:
            return None
        summary = StoredSummary(text=text, upto_seq=target)
        await self.store.put(chat.id, summary)
        return summary

    async def _ask(self, chat: Chat, transcript: str) -> str:
        task = self.settings.ai_profile(AiTask.CHAT_SUMMARY)
        max_tokens = task.output_tokens(SUMMARY_MAX_TOKENS)
        estimate = (len(transcript) // 3 + max_tokens) * task.budget_weight
        if await self.budget.check(chat.owner_id, chat.assistant, estimate):
            return ""
        try:
            response = await self.llm.complete(
                model=task.model,
                system=SUMMARY_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": transcript}],
                tools=[],
                max_tokens=max_tokens,
                provider=task.provider(),
                tuning=task.tuning,
            )
        except AiProviderError:
            log.warning("ai.summary_failed", chat_id=str(chat.id))
            return ""
        await self._count(chat, response, task.budget_weight)
        return str(response.get("text") or "").strip()

    async def _count(
        self, chat: Chat, response: dict[str, object], weight: int
    ) -> None:
        """Count the summary in the pool of the chat's assistant."""
        usage = response.get("usage")
        if isinstance(usage, dict):
            tokens = int(usage.get("input", 0)) + int(usage.get("output", 0))
            await self.budget.add(chat.owner_id, tokens * weight, chat.assistant)
