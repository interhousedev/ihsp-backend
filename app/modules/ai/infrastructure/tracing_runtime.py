"""Which Langfuse tracer a call uses, switched at runtime per pipeline.

The Langfuse project is set only by Administration (host and public key in
`ai.tracing_settings`, the secret key in Vault); without it nothing is traced. Each
pipeline's route can switch tracing and content capture; with nothing set, admission
(essays, applicant profiles) is untraced and the rest is traced without content.
The route service hands every fresh read (at most `AI__ROUTING_TTL_SECONDS` old) to
`apply`, so a change applies in every process without a restart.
"""

import asyncio
from collections.abc import Callable, Mapping

from app.modules.ai.domain.connectors import (
    LANGFUSE_SECRET_ID,
    TRACING_CAPTURE_DEFAULT,
    Pipeline,
    PipelineRoute,
    TracingConfig,
    default_tracing,
)
from app.modules.ai.infrastructure.langfuse_tracer import (
    LangfuseTracer,
    make_langfuse_tracer,
)
from app.modules.ai.ports.connectors import ConnectorSecrets, RoutingSnapshot
from app.shared.ai_tasks import PIPELINE_OF, AiTask

import structlog

log = structlog.get_logger(__name__)

_ConfigKey = tuple[str, str, str | None, object]


def _pipeline(task: str | None) -> Pipeline | None:
    try:
        return PIPELINE_OF.get(AiTask(task)) if task else None
    except ValueError:
        return None


def _key(config: TracingConfig | None) -> _ConfigKey | None:
    if config is None or not config.has_secret or not config.public_key:
        return None
    return (config.host, config.public_key, config.secret_last4, config.updated_at)


class TracingRuntime:
    """Implements `TracingSource` over the stored Langfuse project and switches."""

    def __init__(
        self,
        *,
        make: Callable[..., LangfuseTracer | None] = make_langfuse_tracer,
    ) -> None:
        """No tracer until the first routing read brings a stored project."""
        self._make = make
        self._tracer: LangfuseTracer | None = None
        self._key: _ConfigKey | None = None
        self._routes: Mapping[Pipeline, PipelineRoute] = {}

    def tracing_enabled(self, pipeline: Pipeline) -> bool:
        """Whether the pipeline's calls are traced now."""
        route = self._routes.get(pipeline)
        if route is not None and route.tracing_enabled is not None:
            return route.tracing_enabled
        return default_tracing(pipeline)

    def tracer_for(self, task: str | None) -> LangfuseTracer | None:
        """The active tracer, or None when the task's pipeline is untraced."""
        pipeline = _pipeline(task)
        if pipeline is not None and not self.tracing_enabled(pipeline):
            return None
        return self._tracer

    def capture_for(self, task: str | None) -> bool:
        """The pipeline's content switch, else off."""
        pipeline = _pipeline(task)
        route = self._routes.get(pipeline) if pipeline is not None else None
        if route is not None and route.capture_content is not None:
            return route.capture_content
        return TRACING_CAPTURE_DEFAULT

    async def apply(self, snapshot: RoutingSnapshot, secrets: ConnectorSecrets) -> None:
        """Take the stored switches; rebuild the client when the project changed."""
        self._routes = dict(snapshot.routes)
        key = _key(snapshot.tracing)
        if key == self._key:
            return
        tracer = None
        if key is not None and snapshot.tracing is not None:
            stored = await secrets.get(LANGFUSE_SECRET_ID)
            secret = stored.get("secret_key") if stored else None
            if isinstance(secret, str) and secret:
                tracer = self._make(
                    public_key=snapshot.tracing.public_key,
                    secret_key=secret,
                    host=snapshot.tracing.host,
                    capture_content=TRACING_CAPTURE_DEFAULT,
                )
            else:
                log.warning("langfuse_runtime_secret_missing")
        old, self._tracer, self._key = self._tracer, tracer, key
        if old is not None:
            await asyncio.to_thread(old.close)

    async def close(self) -> None:
        """Flush and stop the client at shutdown; the SDK blocks, so off the loop."""
        if self._tracer is not None:
            await asyncio.to_thread(self._tracer.close)
