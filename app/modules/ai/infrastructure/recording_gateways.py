"""Decorators that count every model call in the usage ledger.

They wrap the LLM gateway, the web search gateway and the embedding gateway, so no
caller changes: the task comes from the call (`LlmTuning.task`, or the search and
embedding profile), the user from the request context (`usage_context`). Each call is
recorded when it ends, with its tokens and cost, or as a failure when it raises. The
decorators never raise on their own account: a recording error is logged and the call
keeps its result.
"""

import time
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.modules.ai.application.request_context import current_request
from app.modules.ai.application.routing import current_route
from app.modules.ai.domain.prompt_registry import PromptRef, note_prompt
from app.modules.ai.domain.structured_check import schema_violation
from app.modules.ai.domain.trace_privacy import masks_content
from app.modules.ai.domain.usage import UNKNOWN_TASK, UsageEvent, counts_of, feature_of
from app.modules.ai.infrastructure.langfuse_tracer import (
    PRIVATE_ERROR_CODE,
    OpenSpan,
    TracingSource,
)
from app.modules.ai.ports.prompts import PromptRewriter
from app.modules.ai.ports.trace_privacy import TracingOptOut
from app.modules.ai.ports.usage import UsageSink
from app.shared.ai_tasks import TASK_SPECS, AiTask
from app.shared.clock import Clock
from app.shared.contracts.ai import LlmGateway, LlmTuning
from app.shared.contracts.embeddings import EmbeddingBatch, EmbeddingGateway, EmbedKind
from app.shared.contracts.web_search import SearchCall, SearchReply, WebSearchGateway
from app.shared.usage_context import (
    UsageActor,
    current_ai_session,
    current_ai_surface,
    current_usage_actor,
)

import structlog

log = structlog.get_logger(__name__)


def is_private_task(task: str | None) -> bool:
    """True when the task named so is declared `private_content` in its spec."""
    try:
        spec = TASK_SPECS.get(AiTask(task)) if task else None
    except ValueError:
        return False
    return bool(getattr(spec, "private_content", False))


class UsageRecorder:
    """Turns the end of a call into a ledger event (the actor is read at the start)."""

    def __init__(
        self,
        sink: UsageSink,
        clock: Clock,
        tracing: TracingSource | None = None,
        opt_out: TracingOptOut | None = None,
    ) -> None:
        """Keep the sink, the clock, the Langfuse source and the users' choice."""
        self._sink = sink
        self._clock = clock
        self._tracing = tracing
        self._opt_out = opt_out

    def use_opt_out(self, opt_out: TracingOptOut) -> None:
        """Read the users' `limit_ai_tracing` from here (wired after identity)."""
        self._opt_out = opt_out

    async def _limits_tracing(self, actor: UsageActor) -> bool:
        if actor.user_id is None or self._opt_out is None:
            return False
        return await self._opt_out.limits_tracing(actor.user_id)

    async def begin(
        self,
        *,
        model: str,
        task: str | None,
        content: Any | None = None,
        prompt: PromptRef | None = None,
    ) -> "PendingCall":
        """Remember who and what a call is, before it runs (and open its span)."""
        actor = current_usage_actor()
        name = task or UNKNOWN_TASK
        private = is_private_task(task)
        span = None
        # a pipeline with tracing off (admission by default) gets no tracer
        tracing = self._tracing
        tracer = tracing.tracer_for(task) if tracing is not None else None
        if tracer is not None and tracing is not None:
            surface = current_ai_surface()
            masked = masks_content(
                task, surface, limit_tracing=await self._limits_tracing(actor)
            )
            span = tracer.begin(
                task=name,
                model=model,
                user_id=actor.user_id,
                role=actor.role,
                session_id=current_ai_session(),
                surface=surface,
                content=None if masked else content,
                masked=masked,
                prompt_version=prompt.version if prompt else None,
                prompt_hash=prompt.hash if prompt else None,
                capture=tracing.capture_for(task),
            )
        request = current_request.get()
        route = current_route.get()
        return PendingCall(
            recorder=self,
            actor=actor,
            model=model,
            task=name,
            span=span,
            private=private,
            prompt=prompt,
            started=time.monotonic(),
            request_id=request.request_id if request else None,
            pipeline=request.pipeline if request else None,
            connector_id=route.connector_id if route else None,
            prompt_chars=_prompt_chars(content),
        )

    async def note_free(self, *, task: str, model: str) -> None:
        """Record a request that was answered without a paid call (cost 0)."""
        await (await self.begin(model=model, task=task)).finish({"cost_micro": 0})

    async def _write(
        self,
        pending: "PendingCall",
        usage: Mapping[str, Any] | None,
        *,
        error: str | None,
        output: Any | None = None,
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
                    error=PRIVATE_ERROR_CODE if pending.private and error else error,
                    prompt_version=pending.prompt.version if pending.prompt else None,
                    prompt_hash=pending.prompt.hash if pending.prompt else None,
                    latency_ms=round((time.monotonic() - pending.started) * 1000),
                    request_id=pending.request_id,
                    pipeline=pending.pipeline,
                    connector_id=pending.connector_id,
                    prompt_chars=pending.prompt_chars,
                    prompt_tokens_est=_tokens_est(pending.prompt_chars),
                    answer_chars=_answer_chars(output),
                    tool_calls=_tool_calls(output),
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
    span: OpenSpan | None = None
    private: bool = False
    prompt: PromptRef | None = None
    started: float = 0.0
    request_id: str | None = None
    pipeline: str | None = None
    connector_id: str | None = None
    prompt_chars: int | None = None

    async def finish(
        self,
        usage: Mapping[str, Any] | None = None,
        *,
        error: str | None = None,
        output: Any | None = None,
    ) -> None:
        """Record the call: its usage on success, its error class on failure."""
        if self.span is not None:
            self.span.end(
                model=_model_of(usage, self.model),
                usage=usage,
                error=error,
                output=None if self.private else output,
            )
        await self.recorder._write(self, usage, error=error, output=output)


def _prompt_chars(content: Any | None) -> int | None:
    """Characters of the system prompt and the messages of a completion call."""
    if not isinstance(content, dict):
        return None
    total = len(content.get("system") or "")
    for message in content.get("messages") or []:
        body = message.get("content") if isinstance(message, dict) else None
        if isinstance(body, str):
            total += len(body)
        elif isinstance(body, list):
            total += sum(
                len(part.get("text") or "") for part in body if isinstance(part, dict)
            )
    return total


def _tokens_est(chars: int | None) -> int | None:
    """The same ceil(chars / 4) heuristic as `estimate_tokens`, on a length."""
    return None if chars is None else -(-chars // 4)


def _answer_chars(output: Any | None) -> int | None:
    if not isinstance(output, dict) or not isinstance(output.get("text"), str):
        return None
    return len(output["text"])


def _tool_calls(output: Any | None) -> int:
    if not isinstance(output, dict):
        return 0
    calls = output.get("tool_calls") or []
    return len(calls) if isinstance(calls, list) else 0


def _model_of(usage: Mapping[str, Any] | None, requested: str) -> str:
    """The model that ran: a fallback gateway names it in the usage."""
    ran = usage.get("model") if usage else None
    return ran if isinstance(ran, str) and ran else requested


SCHEMA_INVALID_ERROR = "SchemaInvalid"


def _error_name(exc: BaseException) -> str:
    return type(exc).__name__[:64]


class RecordingLlmGateway:
    """Implements `LlmGateway` around the real one and records each call."""

    def __init__(
        self,
        inner: LlmGateway,
        recorder: UsageRecorder,
        prompts: PromptRewriter | None = None,
    ) -> None:
        """Keep the gateway to call, the recorder and the prompt rewriter."""
        self._inner = inner
        self._recorder = recorder
        self._prompts = prompts

    async def _prompt(
        self, tuning: LlmTuning | None, system: str
    ) -> tuple[str, PromptRef | None]:
        """The system prompt with the task's active prompt versions, and its ref."""
        task = _task_of(tuning)
        if self._prompts is None or task is None:
            return system, None
        try:
            system, ref = await self._prompts.rewrite(task, system)
        except Exception:
            log.exception("prompt_rewrite_failed", task=task)
            return system, None
        note_prompt(ref)
        return system, ref

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
        system, ref = await self._prompt(tuning, system)
        pending = await self._recorder.begin(
            model=model,
            task=_task_of(tuning),
            content={"system": system, "messages": messages},
            prompt=ref,
        )
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
        await pending.finish(result.get("usage"), output=result)
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
        system, ref = await self._prompt(tuning, system)
        pending = await self._recorder.begin(
            model=model,
            task=_task_of(tuning),
            content={"system": system, "messages": messages},
            prompt=ref,
        )
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
        if schema_violation(schema, result.get("data")) is not None:
            await pending.finish(
                result.get("usage"), error=SCHEMA_INVALID_ERROR, output=result
            )
        else:
            await pending.finish(result.get("usage"), output=result)
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
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream through the gateway; the call is recorded when the stream ends."""
        return self._stream(
            model=model,
            system=system,
            messages=messages,
            max_tokens=max_tokens,
            provider=provider,
            timeout_seconds=timeout_seconds,
            tuning=tuning,
            tools=tools,
        )

    async def _stream(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
        provider: dict[str, Any] | None,
        timeout_seconds: float | None,
        tuning: LlmTuning | None,
        tools: list[dict[str, Any]] | None,
    ) -> AsyncIterator[dict[str, Any]]:
        system, ref = await self._prompt(tuning, system)
        pending = await self._recorder.begin(
            model=model,
            task=_task_of(tuning),
            content={"system": system, "messages": messages},
            prompt=ref,
        )
        items = self._inner.stream(
            model=model,
            system=system,
            messages=messages,
            max_tokens=max_tokens,
            provider=provider,
            timeout_seconds=timeout_seconds,
            tuning=tuning,
            tools=tools,
        )
        async for item in _recorded_stream(pending, items):
            yield item


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
        pending = await self._recorder.begin(
            model=SEARCH_ENGINE, task=call.profile.task.value
        )
        try:
            reply = await self._inner.search(call)
        except BaseException as exc:
            await pending.finish(error=_error_name(exc))
            raise
        charge = reply.cost_micro or reply.usage.get("cost_micro", 0)
        await pending.finish(
            {
                **reply.usage,
                "cost_micro": charge,
                "model": reply.provider or SEARCH_ENGINE,
            }
        )
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
        pending = await self._recorder.begin(
            model=self.model, task=AiTask.EMBEDDING.value
        )
        try:
            batch = await self._inner.embed(texts, kind=kind)
        except BaseException as exc:
            await pending.finish(error=_error_name(exc))
            raise
        await pending.finish({"input": batch.tokens, "cost_micro": batch.cost_micro})
        return batch


def _task_of(tuning: LlmTuning | None) -> str | None:
    return tuning.task if tuning is not None else None
