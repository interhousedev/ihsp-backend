"""Administrators' Langfuse project: host, public key and a write-only secret key.

The secret key goes to Vault first (`LANGFUSE_SECRET_ID`, the connector key store)
and the row follows; the API, the database and the audit log hold only `has_secret`
and the last four characters. Without a row the environment's `LANGFUSE__*` applies.
Every process picks a change up with its next routing read (at most 30 s).
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.modules.ai.application.routing import RouteService
from app.modules.ai.domain.connectors import (
    LANGFUSE_SECRET_ID,
    TracingConfig,
    valid_base_url,
)
from app.modules.ai.domain.errors import ConnectorInvalidError
from app.modules.ai.ports.connectors import ConnectorSecrets, ConnectorUnitOfWork
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.notifications import AuditDraft

AUDIT_TRACING_UPDATED = "admin.ai_tracing_updated"
AUDIT_TRACING_REMOVED = "admin.ai_tracing_removed"
_MIN_KEY_FOR_LAST4 = 8
_MAX_URL = 500
_MAX_KEY = 255


@dataclass(frozen=True, slots=True)
class TracingView:
    """The Langfuse project calls are traced to, without the secret key."""

    source: Literal["runtime", "env", "none"]
    host: str
    public_key: str | None
    has_secret: bool
    secret_last4: str | None
    env_configured: bool
    env_host: str
    capture_default: bool
    updated_at: datetime | None


class TracingAdmin:
    """Shows, sets and removes the runtime Langfuse project."""

    def __init__(
        self,
        uow_factory: Callable[[], ConnectorUnitOfWork],
        secrets: ConnectorSecrets,
        routing: RouteService,
        clock: Clock,
        *,
        env_host: str,
        env_configured: bool,
        capture_default: bool,
        allow_plain_local_urls: bool,
    ) -> None:
        """Keep the transaction factory, the key store, the router and the env."""
        self.uow_factory = uow_factory
        self.secrets = secrets
        self.routing = routing
        self.clock = clock
        self._env_host = env_host
        self._env_configured = env_configured
        self._capture = capture_default
        self._plain_local = allow_plain_local_urls

    async def get(self, actor: Actor) -> TracingView:
        """The stored project, else the environment's."""
        async with self.uow_factory() as uow:
            config = await uow.tracing.get()
        return self._view(config)

    async def put(
        self,
        actor: Actor,
        *,
        host: str,
        public_key: str,
        secret_key: str | None,
    ) -> TracingView:
        """Set the project; an empty `secret_key` keeps the stored one."""
        host = host.strip().rstrip("/")
        if len(host) > _MAX_URL or not valid_base_url(
            host, allow_plain_local=self._plain_local
        ):
            raise ConnectorInvalidError(params={"field": "host"})
        public_key = public_key.strip()
        if not public_key or len(public_key) > _MAX_KEY:
            raise ConnectorInvalidError(params={"field": "public_key"})
        secret_key = (secret_key or "").strip() or None
        if secret_key is not None and len(secret_key) > _MAX_KEY:
            raise ConnectorInvalidError(params={"field": "secret_key"})
        async with self.uow_factory() as uow:
            current = await uow.tracing.get()
            if secret_key is None and not (current and current.has_secret):
                raise ConnectorInvalidError(params={"field": "secret_key"})
            if secret_key is not None:
                await self.secrets.put(LANGFUSE_SECRET_ID, {"secret_key": secret_key})
            config = TracingConfig(
                host=host,
                public_key=public_key,
                has_secret=True,
                secret_last4=(
                    _last4(secret_key)
                    if secret_key is not None
                    else current.secret_last4 if current else None
                ),
                updated_at=self.clock.now(),
                updated_by=actor.user_id,
            )
            await uow.tracing.put(config)
            # the key never reaches the audit log
            uow.audit(
                AuditDraft(
                    type=AUDIT_TRACING_UPDATED,
                    actor_id=actor.user_id,
                    metadata={
                        "host": host,
                        "public_key": public_key,
                        "secret_changed": secret_key is not None,
                    },
                )
            )
            await uow.commit()
        await self._apply()
        return self._view(config)

    async def delete(self, actor: Actor) -> TracingView:
        """Remove the stored project and its key: the environment applies again."""
        async with self.uow_factory() as uow:
            current = await uow.tracing.get()
            if current is not None:
                if current.has_secret:
                    await self.secrets.delete(LANGFUSE_SECRET_ID)
                await uow.tracing.delete()
                uow.audit(
                    AuditDraft(
                        type=AUDIT_TRACING_REMOVED, actor_id=actor.user_id, metadata={}
                    )
                )
                await uow.commit()
        await self._apply()
        return self._view(None)

    async def _apply(self) -> None:
        """Drop the routing cache and read it again, so this process applies now."""
        self.routing.invalidate()
        await self.routing.snapshot()

    def _view(self, config: TracingConfig | None) -> TracingView:
        if config is not None:
            return TracingView(
                source="runtime",
                host=config.host,
                public_key=config.public_key,
                has_secret=config.has_secret,
                secret_last4=config.secret_last4,
                env_configured=self._env_configured,
                env_host=self._env_host,
                capture_default=self._capture,
                updated_at=config.updated_at,
            )
        return TracingView(
            source="env" if self._env_configured else "none",
            host=self._env_host,
            public_key=None,
            has_secret=False,
            secret_last4=None,
            env_configured=self._env_configured,
            env_host=self._env_host,
            capture_default=self._capture,
            updated_at=None,
        )


def _last4(secret: str) -> str | None:
    """The last four characters of a long enough key (a short key shows nothing)."""
    return secret[-4:] if len(secret) >= _MIN_KEY_FOR_LAST4 else None
