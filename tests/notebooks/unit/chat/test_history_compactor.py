"""AI-EFF-2/3: the compactor summarises older turns once and reuses the summary."""

from typing import Any
from uuid import UUID

from app.modules.notebooks.application.history_compactor import HistoryCompactor
from app.modules.notebooks.application.llm import NotebookLlm
from app.modules.notebooks.domain.compaction import CompactSummary
from app.modules.notebooks.domain.entities import MessageContent, NotebookMessage
from app.modules.notebooks.domain.enums import MessageRole
from app.modules.notebooks.infrastructure.redis_compact_store import (
    RedisCompactStore,
)
from app.settings import Settings
from app.shared.ai_tasks import COMPACT_MODEL
from app.shared.contracts.ai import AiProviderError
from app.shared.ids import new_id
from tests.notebooks.unit.domain.pack_builder import NOW

from fakeredis.aioredis import FakeRedis

USER_ID = new_id()
NOTEBOOK_ID = new_id()


class Gateway:
    """Answers every `complete` with a numbered summary (or fails)."""

    def __init__(self, fail: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail = fail

    async def complete(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self.fail:
            raise AiProviderError()
        usage = {"input": 100, "output": 20, "cached": 0, "cost_micro": None}
        return {"text": f"summary {len(self.calls)}", "usage": usage}


class Store:
    """In-memory CompactStore."""

    def __init__(self) -> None:
        self.rows: dict[tuple[UUID, UUID], CompactSummary] = {}

    async def get(self, notebook_id: UUID, user_id: UUID) -> CompactSummary | None:
        return self.rows.get((notebook_id, user_id))

    async def put(
        self, notebook_id: UUID, user_id: UUID, summary: CompactSummary
    ) -> None:
        self.rows[(notebook_id, user_id)] = summary


def chat(count: int) -> list[NotebookMessage]:
    return [
        NotebookMessage(
            id=new_id(),
            notebook_id=NOTEBOOK_ID,
            user_id=USER_ID,
            seq=seq,
            role=MessageRole.USER if seq % 2 else MessageRole.ASSISTANT,
            content=MessageContent(text=f"message {seq}"),
            created_at=NOW,
        )
        for seq in range(1, count + 1)
    ]


def compactor(gateway: Gateway, store: Store) -> HistoryCompactor:
    settings = Settings(env="test")
    llm = NotebookLlm(gateway, settings)  # type: ignore[arg-type]
    return HistoryCompactor(llm, store, settings)


async def test_a_short_thread_is_sent_whole_without_a_model_call() -> None:
    """AI-EFF-3: nothing older than the window, nothing to summarise."""
    gateway = Gateway()

    window, summary = await compactor(gateway, Store()).apply(
        NOTEBOOK_ID, USER_ID, chat(4), limit=20
    )

    assert len(window) == 4 and summary is None and gateway.calls == []


async def test_older_turns_are_summarised_by_the_cheap_task_and_stored() -> None:
    """AI-EFF-2: CONTEXT_COMPACT on the cheapest model; the summary is cached."""
    gateway, store = Gateway(), Store()
    history = chat(30)

    window, summary = await compactor(gateway, store).apply(
        NOTEBOOK_ID, USER_ID, history, limit=4
    )

    assert [m.seq for m in window] == [27, 28, 29, 30]
    assert summary == "summary 1"
    call = gateway.calls[0]
    assert call["model"] == COMPACT_MODEL
    assert call["tuning"].task == "context_compact"
    assert "message 26" in call["messages"][0]["content"]
    assert "message 27" not in call["messages"][0]["content"]
    assert store.rows[(NOTEBOOK_ID, USER_ID)].upto_seq == 26


async def test_the_next_turn_reuses_the_summary() -> None:
    """AI-EFF-2: not recomputed each turn; the gap goes in full."""
    gateway, store = Gateway(), Store()
    service = compactor(gateway, store)
    history = chat(32)
    await service.apply(NOTEBOOK_ID, USER_ID, history[:30], limit=4)

    window, summary = await service.apply(NOTEBOOK_ID, USER_ID, history, limit=4)

    assert len(gateway.calls) == 1 and summary == "summary 1"
    assert [m.seq for m in window] == [27, 28, 29, 30, 31, 32]


async def test_a_failed_summary_keeps_the_answer_going() -> None:
    """AI-EFF-2: a provider error drops the summary, not the question."""
    window, summary = await compactor(Gateway(fail=True), Store()).apply(
        NOTEBOOK_ID, USER_ID, chat(30), limit=4
    )

    assert summary is None and [m.seq for m in window] == [27, 28, 29, 30]


async def test_the_redis_store_round_trips() -> None:
    """AI-EFF-2: the summary survives between processes."""
    store = RedisCompactStore(FakeRedis())
    summary = CompactSummary("s", upto_seq=4, upto_id=new_id())

    await store.put(NOTEBOOK_ID, USER_ID, summary)

    assert await store.get(NOTEBOOK_ID, USER_ID) == summary
    assert await store.get(NOTEBOOK_ID, new_id()) is None
