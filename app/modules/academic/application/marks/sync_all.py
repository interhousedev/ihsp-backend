"""Run the EMIS sync for every student (SYNC-1, SYNC-11)."""

import asyncio
from collections import Counter
from collections.abc import Awaitable, Callable
from uuid import UUID

from app.modules.academic.application.marks.ports.bell_sync import BellSync
from app.modules.academic.application.marks.ports.timetable_sync import TimetableSync
from app.modules.academic.application.marks.ports.unit_of_work import MarksUowFactory
from app.modules.academic.application.marks.sync_student import SyncStudent
from app.modules.academic.domain.marks.sync import SyncCounters, SyncMode
from app.shared.actor import Role
from app.shared.clock import Clock
from app.shared.contracts.identity import IdentityDirectory, UserStatus
from app.shared.notifications import NotificationDraft, NotificationType

import structlog

log = structlog.get_logger(__name__)

PROFILE_SLOT = "20:00"
BELL_ATTEMPTS = 3  # students tried until one EMIS link answers
TIMETABLE_ATTEMPTS = 3  # students of one group and half tried the same way
SPREAD_SECONDS = 1200.0
CONCURRENCY = 10
FAILURE_ALERT_RATIO = 0.2
_LOOKUP_CHUNK = 500


class SyncAll:
    """Creates a SyncRun, syncs the students in parallel and alerts on failures."""

    def __init__(
        self,
        *,
        uow_factory: MarksUowFactory,
        sync_student: SyncStudent,
        bell_sync: BellSync,
        timetable_sync: TimetableSync,
        identity: IdentityDirectory,
        clock: Clock,
        concurrency: int = CONCURRENCY,
        spread_seconds: float = SPREAD_SECONDS,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        """Store collaborators; tests pass ``spread_seconds=0``."""
        self._uow_factory = uow_factory
        self._sync_student = sync_student
        self._bell_sync = bell_sync
        self._timetable_sync = timetable_sync
        self._identity = identity
        self._clock = clock
        self._concurrency = concurrency
        self._spread_seconds = spread_seconds
        self._sleep = sleep

    async def execute(self, slot: str = "manual") -> UUID:
        """Run one sync run for the slot (11:30, 15:00, 20:00 or manual)."""
        async with self._uow_factory() as uow:
            run_id = await uow.sync_runs.create(self._clock.now())
            await uow.commit()
        user_ids = await self._candidates()
        counters = SyncCounters()
        tally: Counter[str] = Counter()
        mode: SyncMode = "profile" if slot == PROFILE_SLOT else "regular"
        try:
            if mode == "profile":
                await self._sync_bells(user_ids)
            await self._run_students(run_id, user_ids, mode, counters, tally)
            if mode == "profile":
                await self._sync_timetables(user_ids)
        except Exception:
            await self._finish(run_id, "failed", len(user_ids), counters, tally)
            raise
        await self._finish(run_id, "done", len(user_ids), counters, tally)
        return run_id

    async def _sync_bells(self, user_ids: list[UUID]) -> None:
        """Bells are the same for everyone: one working EMIS link is enough (ACA-4)."""
        for user_id in user_ids[:BELL_ATTEMPTS]:
            try:
                await self._bell_sync.execute(user_id)
            except Exception:
                log.warning("bell_sync_failed", user_id=str(user_id), exc_info=True)
            else:
                return

    async def _sync_timetables(self, user_ids: list[UUID]) -> None:
        """Refresh each group's timetable once per half (ACA-1, ACA-7).

        A student sees only their own half of a class taught in halves, so one student
        per group and subgroup (and one of those whose half is still unknown) is asked.
        A failing EMIS link makes the next student of that bucket try.
        """
        async with self._uow_factory() as uow:
            members = await uow.students.list_sync_members()
        wanted = set(user_ids)
        buckets: dict[tuple[UUID, int | None], list[UUID]] = {}
        for user_id, group_id, subgroup in members:
            if user_id in wanted:
                buckets.setdefault((group_id, subgroup), []).append(user_id)
        for (group_id, _), students in buckets.items():
            for user_id in students[:TIMETABLE_ATTEMPTS]:
                if await self._sync_timetable(group_id, user_id):
                    break

    async def _sync_timetable(self, group_id: UUID, user_id: UUID) -> bool:
        """Sync one group through one student; False if this link did not work."""
        try:
            outcome = await self._timetable_sync.execute(
                group_id=group_id, user_id=user_id, refresh_bells=False
            )
        except Exception:
            log.warning("timetable_sync_failed", user_id=str(user_id), exc_info=True)
            return False
        return outcome.status != "emis_unavailable"

    async def _candidates(self) -> list[UUID]:
        """Students with a finished backfill and a working EMIS link."""
        async with self._uow_factory() as uow:
            ids = await uow.students.list_sync_candidates()
        selected: list[UUID] = []
        for start in range(0, len(ids), _LOOKUP_CHUNK):
            chunk = ids[start : start + _LOOKUP_CHUNK]
            users = await self._identity.get_users(chunk)
            selected.extend(
                uid
                for uid in chunk
                if uid in users
                and users[uid].status == UserStatus.ACTIVE
                and users[uid].emis_status == "active"
            )
        return selected

    async def _run_students(
        self,
        run_id: UUID,
        user_ids: list[UUID],
        mode: SyncMode,
        counters: SyncCounters,
        tally: Counter[str],
    ) -> None:
        """Process students with bounded parallelism, spread over the window."""
        gate = asyncio.Semaphore(self._concurrency)
        total = max(len(user_ids), 1)

        async def worker(index: int, user_id: UUID) -> None:
            await self._sleep(index * self._spread_seconds / total)
            async with gate:
                await self._one(run_id, user_id, mode, counters, tally)

        await asyncio.gather(*(worker(i, uid) for i, uid in enumerate(user_ids)))

    async def _one(
        self,
        run_id: UUID,
        user_id: UUID,
        mode: SyncMode,
        counters: SyncCounters,
        tally: Counter[str],
    ) -> None:
        """Sync one student and count how it ended; never raises."""
        try:
            outcome = await self._sync_student.execute(
                user_id, run_id, mode=mode, counters=counters
            )
        except Exception:
            log.warning("student_sync_failed", user_id=str(user_id), exc_info=True)
            tally["failed"] += 1
            return
        tally["reauth" if outcome.status == "reauth" else "ok"] += 1

    async def _finish(
        self,
        run_id: UUID,
        status: str,
        total: int,
        counters: SyncCounters,
        tally: Counter[str],
    ) -> None:
        """Store the run summary; alert administrators on a failure spike."""
        stats = {
            "students_total": total,
            "ok": tally["ok"],
            "failed": tally["failed"],
            "reauth": tally["reauth"],
            "emis_requests": counters.emis_requests,
            "marks_new": counters.marks_new,
        }
        drafts: list[NotificationDraft] = []
        if total and tally["failed"] / total > FAILURE_ALERT_RATIO:
            admins = await self._identity.user_ids_with_roles([Role.ADMIN])
            drafts = [
                self._alert(run_id, admin, tally["failed"], total) for admin in admins
            ]
        async with self._uow_factory() as uow:
            await uow.sync_runs.finish(
                run_id, finished_at=self._clock.now(), status=status, stats=stats
            )
            uow.notify(*drafts)
            await uow.commit()

    @staticmethod
    def _alert(
        run_id: UUID, admin_id: UUID, failed: int, total: int
    ) -> NotificationDraft:
        return NotificationDraft(
            user_id=admin_id,
            type=NotificationType.SYNC_ALERT,
            payload={"run_id": str(run_id), "failed": failed, "total": total},
            dedupe_key=f"sync-alert:{run_id}:{admin_id}",
        )
