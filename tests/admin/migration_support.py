"""Shared fakes of the migration tests: a memory store and a recording unit of work."""

from dataclasses import replace
from types import SimpleNamespace
from typing import Any

from app.modules.admin.application.migration_service import MigrationService
from app.modules.admin.domain.migration import (
    MigrationState,
    RunnerRequest,
    RunnerStatus,
)
from app.shared.actor import Actor, Role
from app.shared.ids import new_id
from tests.fakes.clock import FixedClock

TOKEN = "ihsp-pair-v1." + "A" * 80
ADMIN = Actor(user_id=new_id(), roles=frozenset({Role.ADMIN}))
TEACHER = Actor(user_id=new_id(), roles=frozenset({Role.TEACHER}))


class MemoryStore:
    """In-memory `MigrationStore`."""

    def __init__(self, available: bool = True) -> None:
        self.is_available = available
        self.state: MigrationState | None = None
        self.status: RunnerStatus | None = None
        self.request: RunnerRequest | None = None
        self.command: tuple[str, str] | None = None

    def available(self) -> bool:
        return self.is_available

    def read_state(self) -> MigrationState | None:
        return self.state

    def write_state(self, state: MigrationState) -> None:
        self.state = state

    def clear_state(self) -> None:
        self.state = self.status = self.request = self.command = None

    def read_status(self) -> RunnerStatus | None:
        return self.status

    def queue_request(self, request: RunnerRequest) -> None:
        self.request = request

    def withdraw_request(self) -> None:
        self.request = None

    def queue_command(self, migration_id: str, action: str) -> None:
        self.command = (migration_id, action)

    def report(self, state: str, **fields: Any) -> None:
        """Act as the runner: write a status for the current migration."""
        assert self.state is not None
        base = RunnerStatus(
            id=self.state.id,
            state=state,
            step=None,
            steps_done=(),
            error=None,
            updated_at=self.state.updated_at,
        )
        self.status = replace(base, **fields)


class RecordingUow:
    """Async context manager that records the audit drafts it commits."""

    def __init__(self, sink: list[Any]) -> None:
        self.sink = sink
        self.pending: list[Any] = []

    async def __aenter__(self) -> "RecordingUow":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def audit(self, draft: Any) -> None:
        self.pending.append(draft)

    async def commit(self) -> None:
        self.sink.extend(self.pending)
        self.pending = []


class Rig:
    """A migration service with in-memory collaborators."""

    def __init__(self, *, available: bool = True) -> None:
        self.store = MemoryStore(available)
        self.clock = FixedClock()
        self.audits: list[Any] = []
        self.codes: list[str] = []
        self.good_code = "123456"
        self.ticks = 0.0

        async def step_up(actor: Actor, code: str) -> None:
            self.codes.append(code)
            if code != self.good_code:
                raise PermissionError("bad code")

        self.service = MigrationService(
            store=self.store,
            uow_factory=self._uow,  # type: ignore[arg-type]
            step_up=step_up,
            clock=self.clock,
            monotonic=lambda: self.ticks,
        )
        self.admin = SimpleNamespace(migration=self.service)

    def _uow(self) -> RecordingUow:
        return RecordingUow(self.audits)

    def tick(self) -> None:
        """Move past the one-second cache."""
        self.ticks += 5

    async def start(self, **overrides: Any) -> MigrationState:
        args: dict[str, Any] = {
            "target_host": "new.example.org",
            "target_port": 22,
            "pairing_token": TOKEN,
            "target_url": "https://new.example.org",
            "otp_code": self.good_code,
        }
        args.update(overrides)
        return await self.service.start(ADMIN, **args)
