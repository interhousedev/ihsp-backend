"""Server-to-server migration: start, report, roll back (admin only, step-up, audited).

The API never copies anything itself. It queues a request in the directory shared with
the host runner (``scripts/migrate_runner.sh``) and folds the runner's reports into the
state. Every phase but ``idle`` is maintenance mode. The pairing token goes only into
the 0600 request file: never into the state, the audit entry or a log.
"""

import time
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

from app.modules.admin.domain.errors import MigrationNotConfiguredError
from app.modules.admin.domain.migration import (
    MigrationEvent,
    MigrationPhase,
    MigrationState,
    RunnerRequest,
    in_maintenance,
    reconcile,
    transition,
    validate_target,
    validate_token,
)
from app.modules.admin.ports.migration_store import MigrationStore
from app.modules.admin.ports.unit_of_work import AdminUnitOfWork
from app.shared.actor import Actor, Role
from app.shared.base_error import ForbiddenError
from app.shared.clock import Clock
from app.shared.maintenance import MaintenanceInfo
from app.shared.notifications import AuditDraft

AUDIT_MIGRATION_STARTED = "admin.migration_started"
AUDIT_MIGRATION_ROLLBACK = "admin.migration_rollback"
STALE_QUEUE = timedelta(minutes=2)
_CACHE_SECONDS = 1.0


class MigrationService:
    """The migration state machine on top of the shared directory."""

    def __init__(
        self,
        *,
        store: MigrationStore,
        uow_factory: Callable[[], AdminUnitOfWork],
        step_up: Callable[[Actor, str], Awaitable[None]],
        clock: Clock,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        """Keep the collaborators; `step_up` raises when the code is wrong."""
        self.store = store
        self.uow_factory = uow_factory
        self.step_up = step_up
        self.clock = clock
        self.monotonic = monotonic
        self._cached: tuple[float, MigrationState | None] | None = None

    # -- maintenance gate (sync, hot path) -----------------------------------------

    def info(self) -> MaintenanceInfo:
        """Public facts for the banner and the write gate (cached about a second)."""
        state = self._current()
        if state is None or not in_maintenance(state.phase):
            return MaintenanceInfo(active=False)
        moved = state.phase is MigrationPhase.COMPLETED
        return MaintenanceInfo(
            active=True,
            since=state.requested_at,
            moved=moved,
            target_url=state.target_url if moved else None,
        )

    # -- admin use cases -----------------------------------------------------------

    async def status(self, actor: Actor) -> MigrationState | None:
        """The migration in progress (fresh from the files), or None when idle."""
        _require_admin(actor)
        self._cached = None
        return self._current()

    def configured(self) -> bool:
        """The deployment has the shared directory (runner may exist)."""
        return self.store.available()

    def is_stale(self, state: MigrationState) -> bool:
        """Queued so long that the host runner is probably not installed."""
        return (
            state.phase is MigrationPhase.QUEUED
            and self.clock.now() - state.requested_at > STALE_QUEUE
        )

    async def start(
        self,
        actor: Actor,
        *,
        target_host: str,
        target_port: int,
        pairing_token: str,
        target_url: str | None,
        otp_code: str,
        dry_run: bool = False,
    ) -> MigrationState:
        """Queue the migration to the target the token belongs to."""
        _require_admin(actor)
        self._require_configured()
        clean_url = validate_target(target_host, target_port, target_url)
        validate_token(pairing_token)
        current = self._current()
        phase = current.phase if current else MigrationPhase.IDLE
        transition(phase, MigrationEvent.START)
        await self.step_up(actor, otp_code)
        now = self.clock.now()
        state = MigrationState(
            id=uuid4().hex,
            phase=MigrationPhase.QUEUED,
            target_host=target_host,
            target_port=target_port,
            target_url=clean_url,
            requested_by=str(actor.user_id),
            requested_at=now,
            updated_at=now,
            dry_run=dry_run,
        )
        async with self.uow_factory() as uow:
            uow.audit(
                AuditDraft(
                    type=AUDIT_MIGRATION_STARTED,
                    actor_id=actor.user_id,
                    metadata={
                        "migration_id": state.id,
                        "target_host": target_host,
                        "target_port": target_port,
                    },
                )
            )
            await uow.commit()
        self.store.queue_request(
            RunnerRequest(
                id=state.id,
                target_host=target_host,
                target_port=target_port,
                pairing_token=pairing_token,
                requested_at=now,
                dry_run=dry_run,
            )
        )
        self._save(state)
        return state

    async def rollback(self, actor: Actor, *, otp_code: str) -> MigrationState | None:
        """Leave maintenance; a live run is cancelled, services restart."""
        _require_admin(actor)
        self._require_configured()
        current = self._current()
        phase = current.phase if current else MigrationPhase.IDLE
        target = transition(phase, MigrationEvent.ROLLBACK)
        assert current is not None
        await self.step_up(actor, otp_code)
        async with self.uow_factory() as uow:
            uow.audit(
                AuditDraft(
                    type=AUDIT_MIGRATION_ROLLBACK,
                    actor_id=actor.user_id,
                    metadata={"migration_id": current.id, "from": phase.value},
                )
            )
            await uow.commit()
        if target is MigrationPhase.IDLE:
            self.store.clear_state()
            self._cached = (self.monotonic(), None)
            return None
        self.store.queue_command(
            current.id, "resume" if phase is MigrationPhase.COMPLETED else "cancel"
        )
        state = replace(current, phase=target, updated_at=self.clock.now())
        self._save(state)
        return state

    # -- internals -----------------------------------------------------------------

    def _require_configured(self) -> None:
        if not self.store.available():
            raise MigrationNotConfiguredError()

    def _current(self) -> MigrationState | None:
        """The state with the runner's report folded in; cached about a second."""
        now = self.monotonic()
        if self._cached is not None and now - self._cached[0] < _CACHE_SECONDS:
            return self._cached[1]
        state = self.store.read_state()
        if state is not None:
            merged = reconcile(state, self.store.read_status())
            if merged.phase is MigrationPhase.IDLE:
                self.store.clear_state()
                state = None
            else:
                if merged != state:
                    self.store.write_state(merged)
                state = merged
        self._cached = (now, state)
        return state

    def _save(self, state: MigrationState) -> None:
        self.store.write_state(state)
        self._cached = (self.monotonic(), state)


def _require_admin(actor: Actor) -> None:
    if not actor.has(Role.ADMIN):
        raise ForbiddenError()
