"""Context compaction of notebook chats with a cheap model (AI-EFF-2, AI-EFF-3)."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.notebooks.application.llm import NotebookLlm
from app.modules.notebooks.domain.compaction import (
    COMPACT_SYSTEM_PROMPT,
    SUMMARY_MAX_TOKENS,
    CompactSummary,
    needs_refresh,
    plan,
    render_transcript,
    split_history,
)
from app.modules.notebooks.domain.entities import NotebookMessage
from app.modules.notebooks.ports.compact_store import CompactStore
from app.settings import Settings
from app.shared.ai_tasks import AiTask
from app.shared.contracts.ai import AiProviderError
from app.shared.limits import LimitsProvider

import structlog

log = structlog.get_logger(__name__)

type Compacted = tuple[list[NotebookMessage], str | None]


async def history_limit(limits: LimitsProvider) -> int:
    """The messages sent in full (`ai_chat_history_limit`, editable at runtime)."""
    return int((await limits.current()).ai_chat_history_limit)


def window_only(history: Sequence[NotebookMessage], limit: int) -> Compacted:
    """The last `limit` messages and no summary (a core built without compaction)."""
    return (list(history[-limit:]) if limit > 0 else []), None


class HistoryCompactor:
    """Keeps the newest turns in full and a cached summary of the older ones.

    The summary is written by `AiTask.CONTEXT_COMPACT` (the gateway records it in the
    usage ledger like every call) and stored per thread, so a turn usually reuses it.
    """

    def __init__(
        self, llm: NotebookLlm, store: CompactStore, settings: Settings
    ) -> None:
        """Store the collaborators."""
        self.llm = llm
        self.store = store
        self.settings = settings

    async def apply(
        self,
        notebook_id: UUID,
        user_id: UUID,
        history: Sequence[NotebookMessage],
        *,
        limit: int,
    ) -> Compacted:
        """Return (messages sent in full, summary of the older ones or None)."""
        max_chars = self.settings.ai.compact_history_chars
        older, window = split_history(history, limit=limit, max_chars=max_chars)
        if not older:
            return window, None
        base, fresh = plan(await self.store.get(notebook_id, user_id), older)
        if not needs_refresh(base, fresh):
            return ([*fresh, *window], base.text) if base else (window, None)
        text = await self._summarise(base.text if base else None, fresh)
        if not text:  # the model failed: keep what we had
            return ([*fresh, *window], base.text) if base else (window, None)
        last = older[-1]
        summary = CompactSummary(text=text, upto_seq=last.seq, upto_id=last.id)
        await self.store.put(notebook_id, user_id, summary)
        return window, text

    async def _summarise(
        self, previous: str | None, messages: Sequence[NotebookMessage]
    ) -> str:
        task = AiTask.CONTEXT_COMPACT
        try:
            completion = await self.llm.text(
                system=COMPACT_SYSTEM_PROMPT,
                messages=[
                    {"role": "user", "content": render_transcript(previous, messages)}
                ],
                max_tokens=self.llm.max_tokens(task, SUMMARY_MAX_TOKENS),
                task=task,
            )
        except AiProviderError:
            log.warning("notebooks.compact_failed")
            return ""
        return completion.text.strip()
