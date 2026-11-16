"""Langfuse tracing of the model calls.

The usage recorder opens a span when a call starts and ends it when the call ends.
Tracing is best effort: no method raises, and the SDK exports in a background thread,
so a Langfuse outage never delays or fails a request. Without keys no client exists.
Prompts and answers are sent only with `LANGFUSE__CAPTURE_CONTENT`; the user is an
opaque salted hash, never an id, email or name. A task with `private_content` never
sends input, output or error text, whatever the switch says: its error becomes a
fixed code and the metadata is the task and the role only.
"""

import hashlib
from collections.abc import Mapping
from typing import Any, Protocol
from uuid import UUID

from app.settings import LangfuseSettings

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


class LangfuseTracer:
    """Opens spans on a backend and keeps privacy rules in one place."""

    def __init__(
        self, backend: TraceBackend, *, salt: str, capture_content: bool
    ) -> None:
        """Keep the backend, the salt of the user hash and the content switch."""
        self._backend = backend
        self._salt = salt
        self._capture = capture_content

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
    ) -> "OpenSpan | None":
        """Open a span; None when the backend failed (the call goes on untraced)."""
        try:
            span = self._backend.start(
                name=task,
                model=model,
                user_id=self.opaque_user(user_id),
                session_id=session_id,
                input=content if self._capture and not private else None,
                metadata={
                    "task": task,
                    "role": role,
                    "prompt_version": prompt_version,
                    "prompt_hash": prompt_hash,
                },
            )
            return OpenSpan(span, self._capture and not private, private=private)
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


def make_langfuse_tracer(settings: LangfuseSettings) -> LangfuseTracer | None:
    """The tracer, or None (and no client at all) when the keys are not set."""
    if not settings.enabled or settings.secret_key is None:
        return None
    try:
        from langfuse import Langfuse

        secret = settings.secret_key.get_secret_value()
        client = Langfuse(
            public_key=settings.public_key,
            secret_key=secret,
            host=settings.host,
        )
    except Exception:
        log.warning("langfuse_init_failed", exc_info=True)
        return None
    return LangfuseTracer(
        SdkBackend(client), salt=secret, capture_content=settings.capture_content
    )
