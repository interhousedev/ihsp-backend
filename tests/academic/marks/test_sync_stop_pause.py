"""Stop and pause of an EMIS sync run: halted between students, status and resume."""

from uuid import UUID

from app.modules.academic.application.marks.ports.sync_control import SyncControl
from tests.academic.marks.conftest import Env
from tests.academic.marks.db import runs
from tests.academic.marks.test_sync_all import Maker, _crowd


class MemoryControl(SyncControl):
    """In-memory flags: stop after N checks, EMIS paused from the start, resume slot."""

    def __init__(self, *, stop_after: int | None = None, paused: bool = False) -> None:
        self.stop_after = stop_after
        self.paused = paused
        self.checks = 0
        self.cleared: list[UUID] = []
        self.resume: str | None = None

    async def request_run_stop(self, run_id: UUID) -> None:
        self.stop_after = 0

    async def run_stop_requested(self, run_id: UUID) -> bool:
        self.checks += 1
        return self.stop_after is not None and self.checks > self.stop_after

    async def clear_run_stop(self, run_id: UUID) -> None:
        self.cleared.append(run_id)

    async def request_student_stop(self, user_id: UUID) -> None:
        return None

    async def student_stop_requested(self, user_id: UUID) -> bool:
        return False

    async def clear_student_stop(self, user_id: UUID) -> None:
        return None

    async def emis_pause_seconds(self) -> float:
        return 600.0 if self.paused else 0.0

    async def set_resume(self, slot: str) -> None:
        self.resume = slot

    async def take_resume(self) -> str | None:
        slot, self.resume = self.resume, None
        return slot


async def test_stop_ends_the_run_stopped_and_clears_the_flag(
    env: Env, sessionmaker_in_tx: Maker
) -> None:
    """A stop flag set after two students: the run ends ``stopped``, rest skipped."""
    await _crowd(env, sessionmaker_in_tx, 9)
    control = MemoryControl(stop_after=2)

    run_id = await env.sync_all(control=control).execute("11:30")

    [run] = await runs(sessionmaker_in_tx)
    assert run.id == run_id
    assert run.status == "stopped"
    assert run.stats["ok"] == 2
    assert run.stats["skipped"] == 8
    assert control.cleared == [run_id]
    assert control.resume is None


async def test_emis_pause_ends_the_run_paused_and_leaves_a_resume_marker(
    env: Env, sessionmaker_in_tx: Maker
) -> None:
    """EMIS paused: no student is failed, the run is ``paused`` and resumes later."""
    await _crowd(env, sessionmaker_in_tx, 4)
    control = MemoryControl(paused=True)

    await env.sync_all(control=control).execute("20:00")

    [run] = await runs(sessionmaker_in_tx)
    assert run.status == "paused"
    assert run.stats["failed"] == 0
    assert run.stats["skipped"] == 5
    assert control.resume == "20:00"
