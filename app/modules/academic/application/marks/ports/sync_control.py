"""Control of running syncs: stop requests, the EMIS pause, and the resume marker."""

from typing import Protocol
from uuid import UUID


class SyncControl(Protocol):
    """Redis-backed flags that running syncs read between their steps."""

    async def request_run_stop(self, run_id: UUID) -> None:
        """Ask a running sync run to stop after the students in flight."""
        ...

    async def run_stop_requested(self, run_id: UUID) -> bool:
        """True once an administrator asked this run to stop."""
        ...

    async def clear_run_stop(self, run_id: UUID) -> None:
        """Forget the stop request of a finished run."""
        ...

    async def request_student_stop(self, user_id: UUID) -> None:
        """Ask a running student sync to stop before its next step."""
        ...

    async def student_stop_requested(self, user_id: UUID) -> bool:
        """True once an administrator asked this student sync to stop."""
        ...

    async def clear_student_stop(self, user_id: UUID) -> None:
        """Forget the stop request of a finished student sync."""
        ...

    async def emis_pause_seconds(self) -> float:
        """Seconds EMIS still wants us to rest; 0.0 when EMIS may be called."""
        ...

    async def set_resume(self, slot: str) -> None:
        """Remember that a paused run of ``slot`` must run again."""
        ...

    async def take_resume(self) -> str | None:
        """Return and forget the slot of the paused run, None when there is none."""
        ...
