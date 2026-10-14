"""Decorators that count every model call in the usage ledger.

They wrap the LLM gateway, the web search gateway and the embedding gateway, so no
caller changes: the task comes from the call (`LlmTuning.task`, or the search and
embedding profile), the user from the request context (`usage_context`). Each call is
recorded when it ends, with its tokens and cost, or as a failure when it raises. The
decorators never raise on their own account: a recording error is logged and the call
keeps its result.
"""

from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.modules.ai.domain.usage import UNKNOWN_TASK, UsageEvent, counts_of, feature_of
from app.modules.ai.ports.usage import UsageSink
from app.shared.ai_tasks import AiTask
from app.shared.clock import Clock
from app.shared.contracts.ai import LlmGateway, LlmTuning
from app.shared.contracts.embeddings import EmbeddingBatch, EmbeddingGateway, EmbedKind
from app.shared.contracts.web_search import SearchCall, SearchReply, WebSearchGateway
from app.shared.usage_context import UsageActor, current_usage_actor

import structlog

log = structlog.get_logger(__name__)


class UsageRecorder:
    """Turns the end of a call into a ledger event (the actor is read at the start)."""

    def __init__(self, sink: UsageSink, clock: Clock) -> None:
        """Keep the sink and the clock."""
        self._sink = sink
        self._clock = clock

    def begin(self, *, model: str, task: str | None) -> "PendingCall":
        """Remember who and what a call is, before it runs."""
        return PendingCall(
            recorder=self,
            actor=current_usage_actor(),
            model=model,
            task=task or UNKNOWN_TASK,
        )

    async def note_free(self, *, task: str, model: str) -> None:
        """Record a request that was answered without a paid call (cost 0)."""
        await self.begin(model=model, task=task).finish({"cost_micro": 0})

    async def _write(
        self,
        pending: "PendingCall",
        usage: Mapping[str, Any] | None,
        *,
        error: str | None,
    ) -> None:
        try:
            counts = counts_of(usage)
            await self._sink.write(
                UsageEvent(
                    occurred_at=self._clock.now(),
                    user_id=pending.actor.user_id,
                    role=pending.actor.role,
                    task=pending.task,
                    feature=feature_of(pending.task),
                    model=_model_of(usage, pending.model),
                    input_tokens=counts.input_tokens,
                    output_tokens=counts.output_tokens,
                    cached_tokens=counts.cached_tokens,
                    reasoning_tokens=counts.reasoning_tokens,
                    cost_micro=counts.cost_micro,
                    success=error is None,
                    error=error,
                )
            )
        except Exception:
            log.exception("usage_record_failed", task=pending.task)


@dataclass(frozen=True, slots=True)
class PendingCall:
    """A call in progress: its actor, task and model, until `finish` records it."""

    recorder: UsageRecorder
    actor: UsageActor
    model: str
    task: str

    async def finish(
        self, usage: Mapping[str, Any] | None = None, *, error: str | None = None
    ) -> None:
        """Record the call: its usage on success, its error class on failure."""
        await self.recorder._write(self, usage, error=error)


def _model_of(usage: Mapping[str, Any] | None, requested: str) -> str:
    """The model that ran: a fallback gateway names it in the usage."""
    ran = usage.get("model") if usage else None
    return ran if isinstance(ran, str) and ran else requested


def _error_name(exc: BaseException) -> str:
    return type(exc).__name__[:64]


class RecordingLlmGateway:
    """Implements `LlmGateway` around the real one and records each call."""

    def __init__(self, inner: LlmGateway, recorder: UsageRecorder) -> None:
        """Keep the gateway to call and the recorder."""
        self._inner = inner
        self._recorder = recorder

    async def complete(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
        provider: dict[str, Any] | None = None,
        tuning: LlmTuning | None = None,
    ) -> dict[str, Any]:
        """Run `complete` and record it."""
        pending = self._recorder.begin(model=model, task=_task_of(tuning))
        try:
            result = await self._inner.complete(
                model=model,
                system=system,
                messages=messages,
                tools=tools,
                max_tokens=max_tokens,
                provider=provider,
                tuning=tuning,
            )
        except BaseException as exc:
            await pending.finish(error=_error_name(exc))
            raise
        await pending.finish(result.get("usage"))
        return result

    async def complete_json(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        schema_name: str,
        schema: dict[str, Any],
        max_tokens: int,
        provider: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
        tuning: LlmTuning | None = None,
    ) -> dict[str, Any]:
        """Run `complete_json` and record it."""
        pending = self._recorder.begin(model=model, task=_task_of(tuning))
        try:
            result = await self._inner.complete_json(
                model=model,
                system=system,
                messages=messages,
                schema_name=schema_name,
                schema=schema,
                max_tokens=max_tokens,
                provider=provider,
                timeout_seconds=timeout_seconds,
                tuning=tuning,
            )
        except BaseException as exc:
            await pending.finish(error=_error_name(exc))
            raise
        await pending.finish(result.get("usage"))
        return result

    def stream(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
        provider: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
        tuning: LlmTuning | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream through the gateway; the call is recorded when the stream ends."""
        pending = self._recorder.begin(model=model, task=_task_of(tuning))
        items = self._inner.stream(
            model=model,
            system=system,
            messages=messages,
            max_tokens=max_tokens,
            provider=provider,
            timeout_seconds=timeout_seconds,
            tuning=tuning,
        )
        return _recorded_stream(pending, items)


async def _recorded_stream(
    pending: PendingCall, items: AsyncIterator[dict[str, Any]]
) -> AsyncIterator[dict[str, Any]]:
    usage: Mapping[str, Any] | None = None
    try:
        async for item in items:
            if isinstance(item.get("usage"), dict):
                usage = item["usage"]
            yield item
    except BaseException as exc:
        await pending.finish(usage, error=_error_name(exc))
        raise
    await pending.finish(usage)


SEARCH_ENGINE = "exa"


class RecordingWebSearch:
    """Implements `WebSearchGateway` around the real one and records each search."""

    def __init__(self, inner: WebSearchGateway, recorder: UsageRecorder) -> None:
        """Keep the gateway to call and the recorder."""
        self._inner = inner
        self._recorder = recorder

    async def search(self, call: SearchCall) -> SearchReply:
        """Run the search and record its tokens and the provider's charge.

        The search engine (Exa) is the cost here, not the task's language model, so
        the event names the engine; its charge comes in `reply.cost_micro`.
        """
        pending = self._recorder.begin(
            model=SEARCH_ENGINE, task=call.profile.task.value
        )
        try:
            reply = await self._inner.search(call)
        except BaseException as exc:
            await pending.finish(error=_error_name(exc))
            raise
        charge = reply.cost_micro or reply.usage.get("cost_micro", 0)
        await pending.finish({**reply.usage, "cost_micro": charge})
        return reply


class RecordingEmbeddings:
    """Implements `EmbeddingGateway` around the real one and records each batch."""

    def __init__(self, inner: EmbeddingGateway, recorder: UsageRecorder) -> None:
        """Keep the gateway to call and the recorder."""
        self._inner = inner
        self._recorder = recorder

    @property
    def model(self) -> str:
        """The model id that made the vectors."""
        return self._inner.model

    @property
    def dims(self) -> int:
        """Size of every vector."""
        return self._inner.dims

    @property
    def batch_size(self) -> int:
        """Texts one request may carry."""
        return self._inner.batch_size

    async def embed(self, texts: Sequence[str], *, kind: EmbedKind) -> EmbeddingBatch:
        """Embed the texts and record the tokens and cost of the batch."""
        pending = self._recorder.begin(model=self.model, task=AiTask.EMBEDDING.value)
        try:
            batch = await self._inner.embed(texts, kind=kind)
        except BaseException as exc:
            await pending.finish(error=_error_name(exc))
            raise
        await pending.finish({"input": batch.tokens, "cost_micro": batch.cost_micro})
        return batch


def _task_of(tuning: LlmTuning | None) -> str | None:
    return tuning.task if tuning is not None else None
