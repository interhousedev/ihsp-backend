"""Langfuse tracing of the model calls.

The usage recorder opens a span when a call starts and ends it when the call ends.
Tracing is best effort: no method raises, and the SDK exports in a background thread,
so a Langfuse outage never delays or fails a request. Without keys no client exists.
The project comes only from Administration ("Pipelines" -> "Langfuse tracing").
Prompts and answers are sent only when the pipeline's content switch is on; the user
is an opaque salted hash, never an id, email or name. A task with `private_content`
never sends input, output or error text, whatever the switch says: its error becomes
a fixed code and the metadata is the task and the role only.
"""

import hashlib
from collections.abc import Mapping
from typing import Any, Protocol
from uuid import UUID

import structlog

log = structlog.get_logger(__name__)

PRIVATE_ERROR_CODE = "private_task_error"
"""What the span and the usage event say instead of an error text of a private task."""


class TraceSpan(Protocol):
    """One open span of a model call."""

    def end(
        self,
        *,
        model: str,
        usage: dict[str, int],
        error: str | None,
        output: Any | None,
    ) -> None:
        """Close the span with what the call used."""


class TraceBackend(Protocol):
    """What the tracer needs from a Langfuse client."""

    def start(
        self,
        *,
        name: str,
        model: str,
        user_id: str | None,
        session_id: str | None,
        input: Any | None,
        metadata: dict[str, Any],
    ) -> TraceSpan:
        """Open a generation span."""

    def flush(self) -> None:
        """Send what is buffered."""

    def shutdown(self) -> None:
        """Flush and stop the exporter."""


class TracingSource(Protocol):
    """Which tracer (if any) a task's call uses now."""

    def tracer_for(self, task: str | None) -> "LangfuseTracer | None":
        """The tracer of the task's call, or None to leave it untraced."""

    def capture_for(self, task: str | None) -> bool:
        """Whether the task's prompts and answers may be sent."""


class LangfuseTracer:
    """Opens spans on a backend and keeps privacy rules in one place.

    It is also a `TracingSource` that traces every task (the environment only).
    """

    def __init__(
        self, backend: TraceBackend, *, salt: str, capture_content: bool
    ) -> None:
        """Keep the backend, the salt of the user hash and the content switch."""
        self._backend = backend
        self._salt = salt
        self._capture = capture_content

    def tracer_for(self, task: str | None) -> "LangfuseTracer | None":
        """This tracer, for every task."""
        return self

    def capture_for(self, task: str | None) -> bool:
        """The tracer's own content switch."""
        return self._capture

    def opaque_user(self, user_id: UUID | None) -> str | None:
        """A salted hash of the user id: stable per user, not reversible."""
        if user_id is None:
            return None
        digest = hashlib.sha256(f"{self._salt}:{user_id}".encode()).hexdigest()
        return digest[:32]

    def begin(
        self,
        *,
        task: str,
        model: str,
        user_id: UUID | None,
        role: str,
        session_id: str | None,
        content: Any | None = None,
        private: bool = False,
        prompt_version: int | None = None,
        prompt_hash: str | None = None,
        capture: bool | None = None,
    ) -> "OpenSpan | None":
        """Open a span; None when the backend failed (the call goes on untraced).

        `capture` overrides the tracer's content switch for this call.
        """
        send = (self._capture if capture is None else capture) and not private
        try:
            span = self._backend.start(
                name=task,
                model=model,
                user_id=self.opaque_user(user_id),
                session_id=session_id,
                input=content if send else None,
                metadata={
                    "task": task,
                    "role": role,
                    "prompt_version": prompt_version,
                    "prompt_hash": prompt_hash,
                },
            )
            return OpenSpan(span, send, private=private)
        except Exception:
            log.warning("langfuse_start_failed", task=task, exc_info=True)
            return None

    def flush(self) -> None:
        """Send buffered spans; errors are logged, never raised."""
        try:
            self._backend.flush()
        except Exception:
            log.warning("langfuse_flush_failed", exc_info=True)

    def close(self) -> None:
        """Flush and stop the exporter at shutdown; never raises."""
        try:
            self._backend.shutdown()
        except Exception:
            log.warning("langfuse_shutdown_failed", exc_info=True)


class OpenSpan:
    """A span in progress."""

    def __init__(
        self, span: TraceSpan, capture_content: bool, *, private: bool = False
    ) -> None:
        """Keep the span, the content switch and whether the task is private."""
        self._span = span
        self._capture = capture_content
        self._private = private

    def end(
        self,
        *,
        model: str,
        usage: Mapping[str, Any] | None,
        error: str | None,
        output: Any | None = None,
    ) -> None:
        """Close the span; never raises."""
        try:
            self._span.end(
                model=model,
                usage=_usage_details(usage),
                error=PRIVATE_ERROR_CODE if self._private and error else error,
                output=output if self._capture and not self._private else None,
            )
        except Exception:
            log.warning("langfuse_end_failed", exc_info=True)


def _usage_details(usage: Mapping[str, Any] | None) -> dict[str, int]:
    """Token counts of a usage mapping, in Langfuse's names."""
    from app.modules.ai.domain.usage import counts_of

    counts = counts_of(usage)
    details = {
        "input": counts.input_tokens,
        "output": counts.output_tokens,
        "cache_read_input_tokens": counts.cached_tokens,
    }
    if counts.reasoning_tokens is not None:
        details["reasoning_tokens"] = counts.reasoning_tokens
    return details


class SdkBackend:
    """The real Langfuse SDK client."""

    def __init__(self, client: Any) -> None:
        """Keep the SDK client."""
        self._client = client

    def start(
        self,
        *,
        name: str,
        model: str,
        user_id: str | None,
        session_id: str | None,
        input: Any | None,
        metadata: dict[str, Any],
    ) -> TraceSpan:
        """Open a generation span carrying the user and the session."""
        from langfuse import propagate_attributes

        with propagate_attributes(
            user_id=user_id, session_id=session_id, trace_name=name
        ):
            observation = self._client.start_observation(
                name=name,
                as_type="generation",
                model=model,
                input=input,
                metadata=metadata,
            )
        return _SdkSpan(observation)

    def flush(self) -> None:
        """Send buffered spans."""
        self._client.flush()

    def shutdown(self) -> None:
        """Flush and stop."""
        self._client.shutdown()


class _SdkSpan:
    def __init__(self, observation: Any) -> None:
        self._observation = observation

    def end(
        self,
        *,
        model: str,
        usage: dict[str, int],
        error: str | None,
        output: Any | None,
    ) -> None:
        self._observation.update(
            model=model,
            usage_details=usage,
            output=output,
            level="ERROR" if error else None,
            status_message=error,
        )
        self._observation.end()


def make_langfuse_tracer(
    *, public_key: str, secret_key: str, host: str, capture_content: bool
) -> LangfuseTracer | None:
    """The tracer, or None (and no client at all) when a key is empty."""
    if not public_key.strip() or not secret_key.strip():
        return None
    try:
        from langfuse import Langfuse

        client = Langfuse(public_key=public_key, secret_key=secret_key, host=host)
    except Exception:
        log.warning("langfuse_init_failed", exc_info=True)
        return None
    return LangfuseTracer(
        SdkBackend(client), salt=secret_key, capture_content=capture_content
    )
