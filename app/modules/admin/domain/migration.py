"""Server-to-server migration: the phases, the runner's report and the rules.

The API process only queues a request and reports; the root-owned host runner
(`scripts/migrate_runner.sh`) does the work and writes its progress as a
:class:`RunnerStatus`. :func:`reconcile` folds that report into the API's own
:class:`MigrationState`, so the state machine lives here and nowhere else.
"""

import ipaddress
import re
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from urllib.parse import urlsplit

from app.modules.admin.domain.errors import (
    MigrationInvalidInputError,
    MigrationNotAllowedError,
)

# The runner's steps in order; the admin page shows them as a checklist.
STEPS: tuple[str, ...] = (
    "stop_services",
    "dump_postgres",
    "snapshot_redis",
    "copy_objects",
    "copy_config",
    "copy_vault",
    "copy_backups",
    "transfer",
    "verify",
)

TOKEN_PREFIX = "ihsp-pair-v1."
TOKEN_MIN = 64
TOKEN_MAX = 4096
_TOKEN_BODY = re.compile(r"^[A-Za-z0-9_\-=]+$")
_HOSTNAME = re.compile(
    r"^(?=.{1,253}$)([A-Za-z0-9]([A-Za-z0-9\-]{0,61}[A-Za-z0-9])?)"
    r"(\.[A-Za-z0-9]([A-Za-z0-9\-]{0,61}[A-Za-z0-9])?)*$"
)


class MigrationPhase(StrEnum):
    """Where the migration is; anything but ``idle`` means maintenance mode."""

    IDLE = "idle"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLING = "cancelling"


class MigrationEvent(StrEnum):
    """What can happen to a migration."""

    START = "start"
    RUNNER_STARTED = "runner_started"
    RUNNER_DONE = "runner_done"
    RUNNER_FAILED = "runner_failed"
    ROLLBACK = "rollback"
    RUNNER_CANCELLED = "runner_cancelled"


_TRANSITIONS: dict[tuple[MigrationPhase, MigrationEvent], MigrationPhase] = {
    (MigrationPhase.IDLE, MigrationEvent.START): MigrationPhase.QUEUED,
    (MigrationPhase.QUEUED, MigrationEvent.RUNNER_STARTED): MigrationPhase.RUNNING,
    (MigrationPhase.QUEUED, MigrationEvent.ROLLBACK): MigrationPhase.CANCELLING,
    (MigrationPhase.RUNNING, MigrationEvent.RUNNER_DONE): MigrationPhase.COMPLETED,
    (MigrationPhase.RUNNING, MigrationEvent.RUNNER_FAILED): MigrationPhase.FAILED,
    (MigrationPhase.RUNNING, MigrationEvent.ROLLBACK): MigrationPhase.CANCELLING,
    (MigrationPhase.COMPLETED, MigrationEvent.ROLLBACK): MigrationPhase.CANCELLING,
    (MigrationPhase.FAILED, MigrationEvent.ROLLBACK): MigrationPhase.IDLE,
    (MigrationPhase.CANCELLING, MigrationEvent.RUNNER_CANCELLED): MigrationPhase.IDLE,
    (MigrationPhase.CANCELLING, MigrationEvent.RUNNER_FAILED): MigrationPhase.IDLE,
}


def transition(phase: MigrationPhase, event: MigrationEvent) -> MigrationPhase:
    """The next phase, or :class:`MigrationNotAllowedError`."""
    try:
        return _TRANSITIONS[(phase, event)]
    except KeyError:
        raise MigrationNotAllowedError(
            params={"phase": phase.value, "event": event.value}
        ) from None


def in_maintenance(phase: MigrationPhase) -> bool:
    """Every phase but ``idle`` keeps the platform read-only."""
    return phase is not MigrationPhase.IDLE


@dataclass(frozen=True, slots=True)
class MigrationState:
    """What the API knows; written only by the API process."""

    id: str
    phase: MigrationPhase
    target_host: str
    target_port: int
    target_url: str | None
    requested_by: str
    requested_at: datetime
    updated_at: datetime
    step: str | None = None
    steps_done: tuple[str, ...] = ()
    error: str | None = None
    dry_run: bool = False


@dataclass(frozen=True, slots=True)
class RunnerStatus:
    """What the host runner reports (``status.json``); never holds a secret."""

    id: str
    state: str
    """``running``, ``completed``, ``failed`` or ``cancelled``."""
    step: str | None
    steps_done: tuple[str, ...]
    error: str | None
    updated_at: datetime
    dry_run: bool = False


@dataclass(frozen=True, slots=True)
class RunnerRequest:
    """The queued request the runner reads; the only place the token is stored."""

    id: str
    target_host: str
    target_port: int
    pairing_token: str
    requested_at: datetime
    dry_run: bool = False


def reconcile(state: MigrationState, status: RunnerStatus | None) -> MigrationState:
    """Fold the runner's report into the state (no report or another id: unchanged)."""
    if status is None or status.id != state.id:
        return state
    phase = _phase_after(state.phase, status)
    if phase is None:
        return state
    if phase is MigrationPhase.IDLE:
        return replace(state, phase=phase, step=None, updated_at=status.updated_at)
    failed = phase is MigrationPhase.FAILED
    return replace(
        state,
        phase=phase,
        step=status.step,
        steps_done=status.steps_done,
        error=status.error if failed else state.error,
        dry_run=status.dry_run,
        updated_at=status.updated_at,
    )


def _phase_after(phase: MigrationPhase, status: RunnerStatus) -> MigrationPhase | None:
    """The phase a report leads to, or None when it changes nothing."""
    reported = status.state
    if phase is MigrationPhase.QUEUED and reported in ("completed", "failed"):
        # Polled too late to see it run: the report implies it started.
        phase = transition(phase, MigrationEvent.RUNNER_STARTED)
    if reported == "running":
        if phase is MigrationPhase.QUEUED:
            return transition(phase, MigrationEvent.RUNNER_STARTED)
        return phase if phase is MigrationPhase.RUNNING else None
    if reported == "completed" and phase is MigrationPhase.RUNNING:
        return transition(phase, MigrationEvent.RUNNER_DONE)
    if reported == "failed" and phase in (
        MigrationPhase.RUNNING,
        MigrationPhase.CANCELLING,
    ):
        return transition(phase, MigrationEvent.RUNNER_FAILED)
    if reported == "cancelled" and phase is MigrationPhase.CANCELLING:
        return transition(phase, MigrationEvent.RUNNER_CANCELLED)
    return None


def validate_target(host: str, port: int, url: str | None) -> str | None:
    """Check the target host, SSH port and optional site URL; return the clean URL."""
    if not _valid_host(host):
        raise MigrationInvalidInputError(params={"field": "target_host"})
    if not 1 <= port <= 65535:
        raise MigrationInvalidInputError(params={"field": "target_port"})
    if url is None or not url.strip():
        return None
    parts = urlsplit(url.strip())
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.query:
        raise MigrationInvalidInputError(params={"field": "target_url"})
    return f"https://{parts.netloc}"


def validate_token(token: str) -> None:
    """The shape of a pairing token; its content is checked by the runner."""
    body = token[len(TOKEN_PREFIX) :]
    if (
        not token.startswith(TOKEN_PREFIX)
        or not TOKEN_MIN <= len(token) <= TOKEN_MAX
        or not _TOKEN_BODY.match(body)
    ):
        raise MigrationInvalidInputError(params={"field": "pairing_token"})


def _valid_host(host: str) -> bool:
    if host != host.strip() or host.startswith("-"):
        return False
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return bool(_HOSTNAME.match(host))
    return True
