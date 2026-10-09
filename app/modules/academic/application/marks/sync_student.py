"""Sync one student's marks and (in profile mode) profile from EMIS (SYNC-1..9)."""

from uuid import UUID

from app.modules.academic.application.marks.apply_ratings import ApplyRatings
from app.modules.academic.application.marks.ports.unit_of_work import (
    MarksUowFactory,
)
from app.modules.academic.domain.marks.alerts import build_alerts
from app.modules.academic.domain.marks.sync import (
    FetchedRatings,
    StudentSyncState,
    SyncCounters,
    SyncMode,
    SyncOutcome,
    semesters_for,
)
from app.shared.clock import Clock, local_today
from app.shared.contracts.academic import AcademicEnrollment
from app.shared.contracts.emis import EmisAuthFailed, EmisSource
from app.shared.contracts.identity import (
    IdentityCommands,
    IdentityDirectory,
    UserStatus,
)
from app.shared.ids import new_id
from app.shared.notifications import NotificationDraft, NotificationType
from app.shared.tasks import TaskKicker

import structlog

log = structlog.get_logger(__name__)


class SyncStudent:
    """Fetches a student's EMIS data and writes marks, results and alerts."""

    def __init__(
        self,
        *,
        uow_factory: MarksUowFactory,
        emis: EmisSource,
        identity: IdentityDirectory,
        identity_commands: IdentityCommands,
        enrollment: AcademicEnrollment,
        apply: ApplyRatings,
        clock: Clock,
        kicker: TaskKicker,
        institution_id: int,
    ) -> None:
        """Store collaborators; ``institution_id`` is the lyceum's EMIS id."""
        self._uow_factory = uow_factory
        self._emis = emis
        self._identity = identity
        self._identity_commands = identity_commands
        self._enrollment = enrollment
        self._apply = apply
        self._clock = clock
        self._kicker = kicker
        self._institution_id = institution_id

    async def execute(
        self,
        user_id: UUID,
        run_id: UUID | None = None,
        *,
        mode: SyncMode = "regular",
        counters: SyncCounters | None = None,
    ) -> SyncOutcome:
        """Sync one student; EmisUnavailable and other errors are re-raised."""
        counters = counters if counters is not None else SyncCounters()
        state = await self._runnable_state(user_id)
        if state is None:
            return SyncOutcome(user_id, "skipped")
        try:
            return await self._sync(state, run_id or new_id(), mode, counters)
        except EmisAuthFailed:
            await self._record_reauth(user_id)
            return SyncOutcome(user_id, "reauth")
        except Exception as exc:
            await self._record_failure(user_id, exc)
            raise

    async def _runnable_state(self, user_id: UUID) -> StudentSyncState | None:
        """Return the state of an active student with a working EMIS link."""
        user = await self._identity.get_user(user_id)
        if user is None or user.status != UserStatus.ACTIVE:
            return None
        if user.emis_status != "active":
            return None
        state = await self._load_state(user_id)
        if state is None or state.status != "active":
            return None
        return state

    async def _load_state(self, user_id: UUID) -> StudentSyncState | None:
        async with self._uow_factory() as uow:
            return await uow.students.get_state(user_id)

    async def _sync(
        self,
        state: StudentSyncState,
        run_token: UUID,
        mode: SyncMode,
        counters: SyncCounters,
    ) -> SyncOutcome:
        """Refresh the profile if asked, fetch ratings, then write them."""
        effective: SyncMode = "backfill" if state.backfilled_at is None else mode
        if effective in ("backfill", "profile"):
            refreshed = await self._refresh_profile(
                state, counters, import_timetable=effective == "profile"
            )
            if refreshed is None:
                return SyncOutcome(state.user_id, "left")
            state = refreshed
        fetched = await self._fetch(state, effective, counters)
        await self._write(state, fetched, effective, run_token, counters)
        return SyncOutcome(state.user_id, "ok")

    async def _refresh_profile(
        self,
        state: StudentSyncState,
        counters: SyncCounters,
        *,
        import_timetable: bool,
    ) -> StudentSyncState | None:
        """Apply the EMIS profile and subjects (SYNC-3, SYNC-9); None if they left.

        The daily profile run also asks for the timetable of a group that has none
        (ACA-1); after a registration the backfill leaves that to its own task. The
        timetables of the other groups are refreshed by the run itself.
        """
        user_id = state.user_id
        counters.emis_requests += 1
        profile = await self._emis.profile(user_id)
        if profile.institution_id != self._institution_id:
            await self._enrollment.mark_left(user_id, reason="institution")
            return None
        ref = await self._enrollment.ensure_student(
            user_id=user_id,
            group_emis_id=profile.group_emis_id,
            group_name=profile.group_name,
            current_semester=profile.current_semester,
            curriculum_id=profile.curriculum_id,
        )
        await self._identity_commands.update_names(
            user_id,
            first_name=profile.first_name,
            last_name=profile.last_name,
            middle_name=profile.middle_name,
        )
        counters.emis_requests += 1
        subjects = await self._emis.subjects(user_id)
        await self._enrollment.sync_subjects(group_id=ref.group_id, subjects=subjects)
        if import_timetable and ref.needs_timetable:
            await self._kicker.kick(
                "academic.sync_group_timetable",
                user_id=str(user_id),
                group_id=str(ref.group_id),
            )
        async with self._uow_factory() as uow:
            await uow.students.touch_profile_synced(user_id, at=self._clock.now())
            await uow.commit()
        return await self._load_state(user_id)

    async def _fetch(
        self, state: StudentSyncState, mode: SyncMode, counters: SyncCounters
    ) -> list[FetchedRatings]:
        """Call EMIS once per subject and semester."""
        fetched: list[FetchedRatings] = []
        for subject in state.subjects:
            for semester in semesters_for(mode, state.current_semester):
                counters.emis_requests += 1
                ratings = await self._emis.ratings(
                    state.user_id, subject.emis_subject_id, semester
                )
                fetched.append(FetchedRatings(subject, ratings))
        return fetched

    async def _write(
        self,
        state: StudentSyncState,
        fetched: list[FetchedRatings],
        mode: SyncMode,
        run_token: UUID,
        counters: SyncCounters,
    ) -> None:
        """Write everything in one transaction; no alerts for a backfill (SYNC-4)."""
        prefs = await self._identity.get_preferences(state.user_id)
        async with self._uow_factory() as uow:
            await uow.students.lock(state.user_id)
            result = await self._apply.execute(uow, state, fetched, locale=prefs.locale)
            if mode != "backfill":
                uow.notify(
                    *build_alerts(
                        user_id=state.user_id,
                        run_token=run_token,
                        prefs=prefs,
                        added=result.added,
                        subject_changes=result.subject_changes,
                        gpa_changes=result.gpa_changes,
                    )
                )
            await uow.students.record_success(
                state.user_id, at=self._clock.now(), backfilled=mode == "backfill"
            )
            await uow.commit()
        counters.marks_new += len(result.added)

    async def _record_reauth(self, user_id: UUID) -> None:
        """EMIS rejected the credentials: count it and tell the student once a day."""
        day = local_today(self._clock).isoformat()
        async with self._uow_factory() as uow:
            await uow.students.record_failure(user_id, error="emis-auth-failed")
            uow.notify(
                NotificationDraft(
                    user_id=user_id,
                    type=NotificationType.EMIS_REAUTH,
                    payload={},
                    dedupe_key=f"emis-reauth:{user_id}:{day}",
                )
            )
            await uow.commit()

    async def _record_failure(self, user_id: UUID, exc: Exception) -> None:
        """Count a failed sync without hiding the original error."""
        try:
            async with self._uow_factory() as uow:
                await uow.students.record_failure(user_id, error=_describe(exc))
                await uow.commit()
        except Exception:
            log.exception("sync_failure_not_recorded", user_id=str(user_id))


def _describe(exc: Exception) -> str:
    """Short error text kept in students.sync_error."""
    code = getattr(exc, "code", None)
    text = f"{code}: {exc}" if code else f"{type(exc).__name__}: {exc}"
    return text[:500]
