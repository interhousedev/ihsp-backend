"""The usage ledger: every model call is counted with its task, actor and usage."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.modules.ai.domain.usage import UsageEvent, counts_of, feature_of
from app.modules.ai.infrastructure.recording_gateways import (
    RecordingEmbeddings,
    RecordingLlmGateway,
    RecordingWebSearch,
    UsageRecorder,
)
from app.settings import Settings
from app.shared.actor import Role
from app.shared.ai_tasks import AiTask
from app.shared.base_error import BaseError
from app.shared.contracts.ai import LlmTuning
from app.shared.contracts.embeddings import EmbeddingBatch
from app.shared.contracts.web_search import SearchCall, SearchReply
from app.shared.usage_context import bind_usage_actor, reset_usage_actor
from tests.fakes.clock import FixedClock

import pytest


class Sink:
    """Keeps the events; raises when told to (a broken ledger)."""

    def __init__(self, broken: bool = False) -> None:
        self.events: list[UsageEvent] = []
        self.broken = broken

    async def write(self, event: UsageEvent) -> None:
        if self.broken:
            raise RuntimeError("ledger is down")
        self.events.append(event)


class Provider(BaseError):
    code = "ai/provider-error"
    status = 503


class Inner:
    """A language model stand-in with a fixed usage, or an error."""

    def __init__(
        self, usage: dict[str, Any] | None = None, error: Exception | None = None
    ) -> None:
        self.usage = usage or {
            "input": 120,
            "output": 30,
            "cached": 10,
            "cost_micro": 4200,
        }
        self.error = error

    async def complete(self, **_: Any) -> dict[str, Any]:
        if self.error:
            raise self.error
        return {"text": "ok", "tool_calls": [], "usage": self.usage}

    async def complete_json(self, **_: Any) -> dict[str, Any]:
        if self.error:
            raise self.error
        return {"data": {}, "text": "{}", "usage": self.usage}

    def stream(self, **_: Any) -> AsyncIterator[dict[str, Any]]:
        return self._stream()

    async def _stream(self) -> AsyncIterator[dict[str, Any]]:
        yield {"delta": "he"}
        yield {"delta": "llo"}
        yield {"usage": self.usage}


def recorder_for(sink: Sink) -> UsageRecorder:
    return UsageRecorder(sink, FixedClock(datetime(2026, 10, 10, 6, 0, tzinfo=UTC)))


CALL: dict[str, Any] = {
    "model": "anthropic/claude-haiku-5.5",
    "system": "s",
    "messages": [],
    "tools": [],
    "max_tokens": 10,
}


async def test_a_completion_is_counted_with_its_task_actor_and_usage(
    make_actor: Any,
) -> None:
    sink = Sink()
    student = make_actor(Role.STUDENT, user_id=uuid4())
    token = bind_usage_actor(student)
    try:
        gateway = RecordingLlmGateway(Inner(), recorder_for(sink))
        result = await gateway.complete(
            **CALL, tuning=LlmTuning(task=AiTask.STUDIO_QUIZ.value)
        )
    finally:
        reset_usage_actor(token)

    assert result["text"] == "ok"
    (event,) = sink.events
    assert event.task == "studio_quiz"
    assert event.feature == "studio"
    assert event.user_id == student.user_id
    assert event.role == "student"
    assert (event.input_tokens, event.output_tokens, event.cached_tokens) == (
        120,
        30,
        10,
    )
    assert event.cost_micro == 4200
    assert event.success is True
    assert event.error is None


async def test_a_failed_call_is_counted_and_its_error_still_reaches_the_caller() -> (
    None
):
    sink = Sink()
    gateway = RecordingLlmGateway(Inner(error=Provider()), recorder_for(sink))

    with pytest.raises(Provider):
        await gateway.complete_json(
            model="m",
            system="s",
            messages=[],
            schema_name="n",
            schema={},
            max_tokens=5,
            tuning=LlmTuning(task=AiTask.SOURCE_GUIDE.value),
        )

    (event,) = sink.events
    assert event.success is False
    assert event.error == "Provider"
    assert event.feature == "notebook_prep"
    assert event.input_tokens == 0


async def test_a_broken_ledger_never_breaks_the_call() -> None:
    gateway = RecordingLlmGateway(Inner(), recorder_for(Sink(broken=True)))

    result = await gateway.complete(
        **CALL, tuning=LlmTuning(task=AiTask.NOTEBOOK_CHAT.value)
    )

    assert result["text"] == "ok"


async def test_a_call_outside_a_request_is_a_system_call_without_a_task() -> None:
    sink = Sink()
    gateway = RecordingLlmGateway(Inner(), recorder_for(sink))

    await gateway.complete(**CALL, tuning=None)

    (event,) = sink.events
    assert event.user_id is None
    assert event.role == "system"
    assert event.task == "unknown"
    assert event.feature == "other"


async def test_a_stream_is_counted_once_when_it_ends() -> None:
    sink = Sink()
    gateway = RecordingLlmGateway(Inner(), recorder_for(sink))

    chunks = [
        item
        async for item in gateway.stream(
            model="m",
            system="s",
            messages=[],
            max_tokens=5,
            tuning=LlmTuning(task=AiTask.STUDENT_CHAT.value),
        )
    ]

    assert "".join(c.get("delta", "") for c in chunks) == "hello"
    (event,) = sink.events
    assert event.task == "student_chat"
    assert event.feature == "assistant"
    assert event.output_tokens == 30


async def test_a_web_search_and_an_embedding_are_counted_with_their_task() -> None:
    settings = Settings()
    sink = Sink()
    recorder = recorder_for(sink)

    class Search:
        async def search(self, call: SearchCall) -> SearchReply:
            return SearchReply(
                hits=(), usage={"input": 7, "output": 3, "cost_micro": 9}
            )

    class Vectors:
        model = "qwen/qwen3-embedding-4b"
        dims = 1024
        batch_size = 32

        async def embed(self, texts: Any, *, kind: Any) -> EmbeddingBatch:
            return EmbeddingBatch(
                vectors=[[0.0]] * len(texts), tokens=55, cost_micro=11
            )

    profile = settings.ai_profile(AiTask.WEB_SEARCH)
    await RecordingWebSearch(Search(), recorder).search(
        SearchCall(
            query="q", language="ru", max_results=5, explain=False, profile=profile
        )
    )
    await RecordingEmbeddings(Vectors(), recorder).embed(["a", "b"], kind="document")

    search_event, embed_event = sink.events
    assert search_event.task == "web_search"
    assert search_event.feature == "web_search"
    assert search_event.input_tokens == 7
    assert embed_event.task == "embedding"
    assert embed_event.feature == "embedding"
    assert embed_event.input_tokens == 55
    assert embed_event.model == "qwen/qwen3-embedding-4b"


async def test_an_exa_search_is_recorded_with_the_engine_and_its_charge() -> None:
    """Regression: Exa returns its charge in `cost_micro`, not in the usage dict."""
    sink = Sink()

    class Exa:
        async def search(self, call: SearchCall) -> SearchReply:
            return SearchReply(hits=(), usage={}, cost_micro=7000)

    await RecordingWebSearch(Exa(), recorder_for(sink)).search(
        SearchCall(
            query="q",
            language="ru",
            max_results=5,
            explain=False,
            profile=Settings().ai_profile(AiTask.WEB_SEARCH),
        )
    )

    (event,) = sink.events
    assert event.model == "exa"
    assert event.cost_micro == 7000


def test_provider_usage_numbers_are_read_defensively() -> None:
    assert counts_of(None).input_tokens == 0
    assert (
        counts_of({"input": "12", "output": None, "cost_micro": 5}).input_tokens == 12
    )
    assert counts_of({"input": -4}).input_tokens == 0
    assert counts_of({"reasoning": 7}).reasoning_tokens == 7
    assert counts_of({}).cost_micro is None


def test_every_task_has_a_product_feature() -> None:
    assert feature_of("student_chat_smart") == "assistant"
    assert feature_of("studio_infographic") == "studio"
    assert feature_of("lms_authoring") == "lms_author"
    assert feature_of("discover") == "web_search"
    assert feature_of("subject_translate") == "academic"
    assert feature_of("unknown") == "other"


async def test_an_answer_without_a_paid_call_is_a_free_event() -> None:
    sink = Sink()

    await recorder_for(sink).note_free(task="web_search", model="local")

    (event,) = sink.events
    assert (event.task, event.feature, event.model) == (
        "web_search",
        "web_search",
        "local",
    )
    assert event.cost_micro == 0
    assert event.input_tokens == 0 and event.success is True
