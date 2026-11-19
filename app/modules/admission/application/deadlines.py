"""Deadlines, milestones, reminder preferences and the reminder job (§12, §13)."""

from __future__ import annotations

import dataclasses
import datetime as dt
from dataclasses import dataclass
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.domain.documents import (
    REMINDER_CATCH_UP,
    REMINDER_CHANNELS,
    REMINDER_OFFSETS,
    Deadline,
    DeadlineStatus,
    Milestone,
    ReminderPrefs,
    ReminderRecord,
    confirmed_instant,
    reminder_key,
    shift_out_of_quiet,
)
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    InvalidTransitionError,
)
from app.modules.admission.domain.institution_brand import InstitutionBrand
from app.modules.admission.domain.permissions import Permission
from app.modules.admission.ports.unit_of_work import AdmissionUnitOfWork, UowFactory
from app.shared.actor import Role
from app.shared.clock import Clock
from app.shared.ids import new_id
from app.shared.notifications import NotificationDraft, NotificationType

_HORIZON = dt.timedelta(days=max(REMINDER_OFFSETS) + 1)


@dataclass(frozen=True, slots=True)
class DeadlineItem:
    """A student's milestone with the institution it belongs to."""

    milestone: Milestone
    institution_id: UUID
    brand: InstitutionBrand


@dataclass(frozen=True, slots=True)
class DeadlineInput:
    """Editable fields of a deadline; `None` keeps a value unless in `clear`."""

    status: DeadlineStatus | None = None
    precision: str | None = None
    source_text: str | None = None
    source_tz: str | None = None
    local_date: dt.date | None = None
    cutoff_time: dt.time | None = None
    instant_utc: dt.datetime | None = None
    binding: bool | None = None
    applies_to: str | None = None
    clear: frozenset[str] = frozenset()

    @classmethod
    def from_patch(cls, patch: dict[str, object]) -> DeadlineInput:
        """Build from a set-fields-only patch; an explicit null clears a nullable."""
        clear = frozenset(k for k, v in patch.items() if v is None and k in _NULLABLE)
        return cls(**patch, clear=clear)  # type: ignore[arg-type]


def _can_manage(ctx: AdmissionContext) -> bool:
    if Role.ADMIN in ctx.actor.roles:
        return True
    return any(
        Permission.DEADLINES_MANAGE in a.role.effective_permissions
        for a in ctx.assignments
    )


class DeadlineService:
    """Staff-maintained deadlines and the student's reminders."""

    def __init__(
        self, uow_factory: UowFactory, access: AccessPolicy, clock: Clock
    ) -> None:
        """Keep the collaborators."""
        self._uow = uow_factory
        self._access = access
        self._clock = clock

    def _need_manage(self, ctx: AdmissionContext) -> None:
        if not _can_manage(ctx):
            raise AdmissionForbiddenError(
                params={"permission": Permission.DEADLINES_MANAGE.value}
            )

    # -- staff -----------------------------------------------------------

    async def listing(
        self,
        ctx: AdmissionContext,
        *,
        institution_id: UUID | None = None,
        cycle: int | None = None,
    ) -> list[Deadline]:
        """List live deadlines."""
        self._need_manage(ctx)
        async with self._uow() as uow:
            return await uow.deadlines.current(
                institution_id=institution_id, cycle=cycle
            )

    async def institution_brands(
        self, ctx: AdmissionContext, ids: set[UUID]
    ) -> dict[UUID, InstitutionBrand]:
        """Return the university names and logos of the given ids."""
        self._need_manage(ctx)
        async with self._uow() as uow:
            return await uow.deadlines.institution_brands(ids)

    async def create(
        self,
        ctx: AdmissionContext,
        *,
        institution_id: UUID,
        cycle: int,
        round: str,
        data: DeadlineInput,
        program_id: UUID | None = None,
    ) -> Deadline:
        """Add the first version of a deadline."""
        self._need_manage(ctx)
        deadline = Deadline(
            id=new_id(),
            institution_id=institution_id,
            cycle=cycle,
            round=round,
            program_id=program_id,
        )
        _apply(deadline, data)
        async with self._uow() as uow:
            saved = await uow.deadlines.add(deadline)
            await uow.commit()
        return saved

    async def edit(
        self, ctx: AdmissionContext, deadline_id: UUID, data: DeadlineInput
    ) -> Deadline:
        """Add a new version, supersede the old one and move the milestones."""
        self._need_manage(ctx)
        async with self._uow() as uow:
            new = await self._new_version(uow, deadline_id, data)
            await uow.commit()
        return new

    async def _new_version(
        self, uow: AdmissionUnitOfWork, deadline_id: UUID, data: DeadlineInput
    ) -> Deadline:
        old = await uow.deadlines.get(deadline_id)
        if old is None:
            raise AdmissionNotFoundError()
        if old.superseded_by is not None:
            raise InvalidTransitionError(params={"status": "superseded"})
        new = dataclasses.replace(
            old, id=new_id(), version=old.version + 1, superseded_by=None
        )
        _apply(new, data)
        await uow.deadlines.add(new)
        await uow.deadlines.supersede(old.id, new.id)
        await self._move_milestones(uow, old, new)
        return new

    async def remove(self, ctx: AdmissionContext, deadline_id: UUID) -> None:
        """Retire a deadline: reminders stop and it leaves the live list.

        The last version is `unknown` and points at itself, so no version of the
        deadline is live; milestones keep it as their undated reference. All of it
        happens in one unit of work.
        """
        self._need_manage(ctx)
        async with self._uow() as uow:
            retired = await self._new_version(
                uow, deadline_id, DeadlineInput(status="unknown")
            )
            await uow.deadlines.supersede(retired.id, retired.id)
            await uow.commit()

    async def _move_milestones(
        self, uow: AdmissionUnitOfWork, old: Deadline, new: Deadline
    ) -> None:
        affected = await uow.deadlines.milestones_of_deadline(old.id)
        if not affected:
            return
        await uow.deadlines.supersede_reminders([a.milestone.id for a in affected])
        due = confirmed_instant(new) if new.status == "confirmed" else None
        names = await uow.deadlines.institution_names([new.institution_id])
        for item in affected:
            ms = item.milestone
            ms.deadline_id = new.id
            ms.deadline_version = new.version
            ms.due_utc = due
            ms.predicted = new.status == "predicted"
            await uow.deadlines.save_milestone(ms)
        for student_id in dict.fromkeys(a.student_id for a in affected):
            uow.notify(
                NotificationDraft(
                    user_id=student_id,
                    type=NotificationType.DEADLINE_CHANGED,
                    payload={
                        "institution": names.get(new.institution_id, ""),
                        "due_utc": due.isoformat() if due else "",
                    },
                    dedupe_key=f"deadline:{new.id}:changed:{student_id}",
                )
            )

    # -- student ---------------------------------------------------------

    async def mine(
        self, ctx: AdmissionContext, student_id: UUID | None = None
    ) -> list[DeadlineItem]:
        """Return the milestones of the student's list with institution brands."""
        target = student_id or ctx.user_id
        await self._access.require(ctx, target, Permission.LIST_READ)
        async with self._uow() as uow:
            entries = await uow.shortlist.entries(target)
            by_entry = {e.id: e.institution_id for e in entries}
            milestones = await uow.deadlines.milestones_of_entries(list(by_entry))
            brands = await uow.deadlines.institution_brands(set(by_entry.values()))
        items = [
            DeadlineItem(
                m,
                by_entry[m.list_entry_id],
                brands.get(by_entry[m.list_entry_id], InstitutionBrand("")),
            )
            for m in milestones
        ]
        return sorted(
            items, key=lambda i: (i.milestone.due_utc is None, i.milestone.due_utc)
        )

    async def get_prefs(
        self, ctx: AdmissionContext, student_id: UUID | None = None
    ) -> ReminderPrefs:
        """Return the preferences, or the defaults."""
        target = student_id or ctx.user_id
        await self._access.require(ctx, target, Permission.LIST_READ)
        async with self._uow() as uow:
            return await uow.deadlines.prefs(target) or ReminderPrefs(target)

    async def set_prefs(
        self,
        ctx: AdmissionContext,
        *,
        offsets_days: list[int],
        channels: list[str],
        quiet_from: dt.time,
        quiet_to: dt.time,
    ) -> ReminderPrefs:
        """Replace the caller's preferences; offsets and channels are validated."""
        await self._access.require(ctx, ctx.user_id, Permission.LIST_READ)
        if not set(offsets_days) <= set(REMINDER_OFFSETS) or not set(channels) <= set(
            REMINDER_CHANNELS
        ):
            raise InvalidTransitionError(params={"status": "invalid_prefs"})
        async with self._uow() as uow:
            current = await uow.deadlines.prefs(ctx.user_id)
            prefs = current or ReminderPrefs(ctx.user_id)
            lock = current.lock_version if current else None
            prefs.offsets_days = tuple(sorted(set(offsets_days), reverse=True))
            prefs.channels = tuple(dict.fromkeys(channels))
            prefs.quiet_from = quiet_from
            prefs.quiet_to = quiet_to
            saved = await uow.deadlines.save_prefs(prefs, lock)
            await uow.commit()
        return saved

    # -- job -------------------------------------------------------------

    async def run_reminders(self) -> int:
        """Queue due reminders through the notify outbox; return how many."""
        now = self._clock.now()
        queued = 0
        async with self._uow() as uow:
            due = await uow.deadlines.due_between(
                now - REMINDER_CATCH_UP, now + _HORIZON
            )
            names = await uow.deadlines.institution_names(
                {d.institution_id for d in due}
            )
            prefs_cache: dict[UUID, ReminderPrefs] = {}
            for item in due:
                ms = item.milestone
                if ms.predicted or ms.due_utc is None or ms.deadline_version is None:
                    continue
                if item.student_id not in prefs_cache:
                    prefs_cache[item.student_id] = await uow.deadlines.prefs(
                        item.student_id
                    ) or ReminderPrefs(item.student_id)
                prefs = prefs_cache[item.student_id]
                for offset in prefs.offsets_days:
                    fire = ms.due_utc - dt.timedelta(days=offset)
                    if not now - REMINDER_CATCH_UP < fire <= now:
                        continue
                    key = reminder_key(ms.id, ms.deadline_version, offset)
                    when = shift_out_of_quiet(now, prefs.quiet_from, prefs.quiet_to)
                    fresh = await uow.deadlines.add_reminder(
                        ReminderRecord(
                            id=new_id(),
                            student_id=item.student_id,
                            milestone_id=ms.id,
                            schedule_version=ms.deadline_version,
                            offset_days=offset,
                            dedupe_key=key,
                            scheduled_at=when,
                        )
                    )
                    if not fresh:
                        continue
                    uow.notify(
                        NotificationDraft(
                            user_id=item.student_id,
                            type=NotificationType.ADMISSION_DEADLINE_REMINDER,
                            payload={
                                "institution": names.get(item.institution_id, ""),
                                "days": str(offset),
                                "due_utc": ms.due_utc.isoformat(),
                            },
                            dedupe_key=key,
                            scheduled_at=when if when > now else None,
                        )
                    )
                    queued += 1
            await uow.commit()
        return queued


_NULLABLE = frozenset({"source_text", "local_date"})


def _apply(deadline: Deadline, data: DeadlineInput) -> None:
    for name in (
        "status",
        "precision",
        "source_text",
        "source_tz",
        "local_date",
        "cutoff_time",
        "instant_utc",
        "binding",
        "applies_to",
    ):
        value = getattr(data, name)
        if value is not None:
            setattr(deadline, name, value)
        elif name in data.clear:
            setattr(deadline, name, None)
