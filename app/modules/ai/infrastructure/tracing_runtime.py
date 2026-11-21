"""Which Langfuse tracer a call uses, switched at runtime per pipeline.

The Langfuse project set by Administration (host and public key in
`ai.tracing_settings`, the secret key in Vault) replaces the environment's
(`LANGFUSE__*`); without it the environment's applies. Each pipeline's route can
switch tracing and content capture; with nothing set, admission (essays, applicant
profiles) is untraced and the rest is traced, content per `LANGFUSE__CAPTURE_CONTENT`.
The route service hands every fresh read (at most `AI__ROUTING_TTL_SECONDS` old) to
`apply`, so a change applies in every process without a restart.
"""

import asyncio
from collections.abc import Callable, Mapping

from app.modules.ai.domain.connectors import (
    LANGFUSE_SECRET_ID,
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
from app.settings import LangfuseSettings
from app.shared.ai_tasks import PIPELINE_OF, AiTask

import structlog
from pydantic import SecretStr

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
    """Implements `TracingSource` over the environment and the stored settings."""

    def __init__(
        self,
        env: LangfuseSettings,
        *,
        make: Callable[[LangfuseSettings], LangfuseTracer | None] = (
            make_langfuse_tracer
        ),
    ) -> None:
        """Build the environment's tracer (none without its keys)."""
        self._env = env
        self._make = make
        self._env_tracer = make(env)
        self._runtime_tracer: LangfuseTracer | None = None
        self._runtime_key: _ConfigKey | None = None
        self._routes: Mapping[Pipeline, PipelineRoute] = {}

    @property
    def capture_default(self) -> bool:
        """Content capture of a pipeline that set nothing."""
        return self._env.capture_content

    @property
    def env_configured(self) -> bool:
        """True when the environment holds both Langfuse keys."""
        return self._env.enabled

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
        return self._runtime_tracer or self._env_tracer

    def capture_for(self, task: str | None) -> bool:
        """The pipeline's content switch, else the environment's."""
        pipeline = _pipeline(task)
        route = self._routes.get(pipeline) if pipeline is not None else None
        if route is not None and route.capture_content is not None:
            return route.capture_content
        return self._env.capture_content

    async def apply(self, snapshot: RoutingSnapshot, secrets: ConnectorSecrets) -> None:
        """Take the stored switches; rebuild the client when the project changed."""
        self._routes = dict(snapshot.routes)
        key = _key(snapshot.tracing)
        if key == self._runtime_key:
            return
        tracer = None
        if key is not None and snapshot.tracing is not None:
            stored = await secrets.get(LANGFUSE_SECRET_ID)
            secret = stored.get("secret_key") if stored else None
            if isinstance(secret, str) and secret:
                tracer = self._make(
                    LangfuseSettings(
                        public_key=snapshot.tracing.public_key,
                        secret_key=SecretStr(secret),
                        host=snapshot.tracing.host,
                        capture_content=self._env.capture_content,
                    )
                )
            else:
                log.warning("langfuse_runtime_secret_missing")
        old, self._runtime_tracer, self._runtime_key = (
            self._runtime_tracer,
            tracer,
            key,
        )
        if old is not None:
            await asyncio.to_thread(old.close)

    async def close(self) -> None:
        """Flush and stop every client at shutdown; the SDK blocks, so off the loop."""
        for tracer in (self._runtime_tracer, self._env_tracer):
            if tracer is not None:
                await asyncio.to_thread(tracer.close)
