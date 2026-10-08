"""Import an unknown group's timetable from EMIS (ACA-1, background task)."""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from app.modules.academic.application.schedule.bootstrap_entries import EntryImporter
from app.modules.academic.application.schedule.bootstrap_teachers import (
    TeacherResolver,
)
from app.modules.academic.application.schedule.common import UowFactory, today
from app.modules.academic.application.schedule.generate_lessons import (
    DEFAULT_DAYS,
    GenerateLessons,
)
from app.modules.academic.application.schedule.sync_class_hours import SyncClassHours
from app.modules.academic.domain.schedule.term import Term, pick_current_term
from app.shared.clock import Clock
from app.shared.contracts.emis import (
    EmisAuthFailed,
    EmisSource,
    EmisTimetableItem,
    EmisUnavailable,
)
from app.shared.contracts.identity import IdentityCommands
from app.shared.notifications import AuditDraft

import structlog

log = structlog.get_logger(__name__)

BootstrapStatus = Literal[
    "imported", "exists", "empty", "no_term", "no_group", "emis_unavailable"
]


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    """How an import ended and what it wrote."""

    status: BootstrapStatus
    entries: int = 0
    merged: int = 0
    skipped: int = 0
    teachers: int = 0
    lessons: int = 0


class BootstrapGroup:
    """Fill a group that has no timetable: entries, rooms, teachers and lessons.

    Idempotent: a group that already has entries in the current term is left alone,
    so a second student of the same group, a repeated task or a group Administration
    built by hand never gets duplicates. The group, its curriculum subjects and the
    student already exist (``AcademicEnrollment.ensure_student``/``sync_subjects``).
    """

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        emis: EmisSource,
        identity_commands: IdentityCommands,
        sync_class_hours: SyncClassHours,
        generate: GenerateLessons,
        clock: Clock,
    ) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory
        self.emis = emis
        self.identity_commands = identity_commands
        self.sync_class_hours = sync_class_hours
        self.generate = generate
        self.clock = clock

    async def execute(self, *, group_id: UUID, user_id: UUID) -> BootstrapResult:
        """Import the group's timetable through the student's EMIS link."""
        term = await self._term_without_timetable(group_id)
        if isinstance(term, BootstrapResult):
            return term
        items = await self._fetch(user_id)
        if items is None:
            return BootstrapResult("emis_unavailable")
        if not items:
            return BootstrapResult("empty")
        result = await self._import(term, group_id, items)
        if result.status != "imported":
            return result
        lessons = await self._generate(term)
        log.info("emis_group_bootstrapped", group_id=str(group_id), lessons=lessons)
        return BootstrapResult(
            "imported",
            result.entries,
            result.merged,
            result.skipped,
            result.teachers,
            lessons,
        )

    async def _term_without_timetable(self, group_id: UUID) -> Term | BootstrapResult:
        async with self.uow_factory() as uow:
            term = pick_current_term(await uow.terms.list_all(), today(self.clock))
            if term is None:
                return BootstrapResult("no_term")
            if await uow.entries.search(term.id, group_id=group_id):
                return BootstrapResult("exists")
        return term

    async def _fetch(self, user_id: UUID) -> list[EmisTimetableItem] | None:
        """Bells first (so lessons get EMIS times), then the timetable itself."""
        try:
            await self.sync_class_hours.execute(user_id)
        except (EmisAuthFailed, EmisUnavailable):
            log.warning("emis_bells_unavailable_for_bootstrap", user_id=str(user_id))
        try:
            return await self.emis.timetable(user_id)
        except (EmisAuthFailed, EmisUnavailable) as exc:
            log.warning("emis_timetable_unavailable", error=exc.support_details)
            return None

    async def _import(
        self, term: Term, group_id: UUID, items: list[EmisTimetableItem]
    ) -> BootstrapResult:
        async with self.uow_factory() as uow:
            await uow.lock_term(term.id)
            group = await uow.groups.get(group_id)
            if group is None:
                return BootstrapResult("no_group")
            if await uow.entries.search(term.id, group_id=group.id):
                return BootstrapResult("exists")  # a parallel import won the lock
            teachers = TeacherResolver(self.identity_commands)
            tally = await EntryImporter(
                uow, term=term, group=group, teachers=teachers, now=self.clock.now()
            ).run(items)
            uow.audit(
                AuditDraft(
                    type="group.timetable_imported",
                    metadata={
                        "group_id": str(group.id),
                        "term_id": str(term.id),
                        "entries": tally.entries,
                        "merged": tally.merged,
                        "skipped": tally.skipped,
                        "source": "emis",
                    },
                )
            )
            await uow.commit()
        return BootstrapResult(
            "imported", tally.entries, tally.merged, tally.skipped, teachers.count
        )

    async def _generate(self, term: Term) -> int:
        start = max(today(self.clock), term.starts_on)
        return await self.generate.execute(
            term_id=term.id, from_date=start, days=DEFAULT_DAYS
        )
