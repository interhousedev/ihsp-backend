"""Jobs `notebooks.provision_student_notebooks` and the backfill (NB-AUTO)."""

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from app.modules.notebooks.application.open_auto_notebook import OpenAutoNotebook
from app.modules.notebooks.domain.enums import NotebookOrigin
from app.modules.notebooks.domain.errors import (
    AutoNotebookLimitError,
    FeatureDisabledError,
    NotebookNotFoundError,
)
from app.modules.notebooks.ports.term_calendar import TermCalendar
from app.shared.actor import Actor, Role
from app.shared.base_error import BaseError
from app.shared.clock import Clock, local_today
from app.shared.contracts.academic import ScheduleQueries
from app.shared.contracts.identity import IdentityDirectory
from app.shared.tasks import TaskKicker

import structlog

log = structlog.get_logger(__name__)

NO_TERM_DAYS = 180  # the window around today when the calendar has no term


class ProvisionStudentNotebooks:
    """Creates and fills the subject notebooks of a student's current term.

    One notebook per subject the student has lessons in this term. Safe to run any
    number of times: a subject that already has its notebook is left alone (the sync
    job keeps it current), so it also serves the backfill and the daily check.
    """

    def __init__(
        self,
        *,
        schedule: ScheduleQueries,
        terms: TermCalendar | None,
        clock: Clock,
        open_auto: OpenAutoNotebook,
    ) -> None:
        """Store the collaborators (`terms` missing: the feature is off)."""
        self.schedule = schedule
        self.terms = terms
        self.clock = clock
        self.open_auto = open_auto

    async def execute(self, user_id: UUID) -> int:
        """Create the missing subject notebooks of the student; return how many."""
        if self.terms is None or await self.schedule.get_student(user_id) is None:
            return 0
        subjects = await self._subjects(user_id)
        actor = Actor(user_id=user_id, roles=frozenset({Role.STUDENT}))
        created = 0
        for subject_id in subjects:
            try:
                created += await self._ensure(actor, subject_id)
            except AutoNotebookLimitError:
                break
            except FeatureDisabledError:
                return created
            except BaseError as exc:  # one bad subject must not stop the others
                log.warning(
                    "notebooks_provision_failed",
                    user_id=str(user_id),
                    subject_id=str(subject_id),
                    error=exc.support_details,
                )
        if created:
            log.info("notebooks_provisioned", user_id=str(user_id), created=created)
        return created

    async def _subjects(self, user_id: UUID) -> list[UUID]:
        """The subjects of the student's lessons in the current term."""
        assert self.terms is not None
        today = local_today(self.clock)
        window = await self.terms.current_term_dates(today)
        start, end = window or (
            today - timedelta(days=NO_TERM_DAYS),
            today + timedelta(days=NO_TERM_DAYS),
        )
        lessons = await self.schedule.lessons_for_student(user_id, start, end)
        return list(dict.fromkeys(lesson.subject_id for lesson in lessons))

    async def _ensure(self, actor: Actor, subject_id: UUID) -> int:
        """1 when the notebook was created now, 0 when it was there."""
        try:
            await self.open_auto.execute(
                actor, NotebookOrigin.SUBJECT_AUTO, subject_id, create=False
            )
            return 0
        except NotebookNotFoundError:
            pass
        try:
            await self.open_auto.execute(actor, NotebookOrigin.SUBJECT_AUTO, subject_id)
        except NotebookNotFoundError:
            return 0  # no lessons of the subject for this student after all
        return 1


@dataclass(frozen=True, slots=True)
class BackfillResult:
    """What a backfill did: students visited and notebooks created."""

    students: int
    created: int


class BackfillSubjectNotebooks:
    """Provisions the subject notebooks of every student that is already there.

    `python -m app backfill-subject-notebooks` runs it in place; the daily job only
    queues one provisioning task per student, so it never holds a worker.
    """

    def __init__(
        self,
        *,
        identity: IdentityDirectory | None,
        provision: ProvisionStudentNotebooks,
        kicker: TaskKicker,
    ) -> None:
        """Store the collaborators."""
        self.identity = identity
        self.provision = provision
        self.kicker = kicker

    async def execute(self, *, inline: bool = False) -> BackfillResult:
        """Visit every student: do the work now (`inline`) or queue it."""
        if self.identity is None:
            return BackfillResult(0, 0)
        ids = await self.identity.user_ids_with_roles([Role.STUDENT])
        created = 0
        for user_id in ids:
            if inline:
                created += await self.provision.execute(user_id)
            else:
                await self.kicker.kick(
                    "notebooks.provision_student_notebooks", user_id=str(user_id)
                )
        return BackfillResult(len(ids), created)
