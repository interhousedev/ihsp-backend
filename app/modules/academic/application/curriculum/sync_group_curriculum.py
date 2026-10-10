"""Store a group's EMIS curriculum, fill subject names and create missing terms."""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from app.modules.academic.application.schedule.common import UowFactory
from app.modules.academic.application.schedule.ports.unit_of_work import (
    ScheduleUnitOfWork,
)
from app.modules.academic.application.schedule.term_checks import check_term
from app.modules.academic.domain.curriculum.names import (
    fill_missing_names,
    first_names,
)
from app.modules.academic.domain.curriculum.records import (
    curriculum_from_emis,
    semester_subjects_from_emis,
)
from app.modules.academic.domain.curriculum.semesters import (
    SemesterTerm,
    term_for_semester,
)
from app.modules.academic.domain.schedule.errors import (
    CurriculumNoEmisStudentError,
    GroupNotFoundError,
    TermDatesInvalidError,
    TermDuplicateError,
    TermOverlapError,
)
from app.modules.academic.domain.schedule.term import Term
from app.shared.clock import Clock
from app.shared.contracts.emis import (
    EmisAuthFailed,
    EmisCredentialsMissing,
    EmisCurriculum,
    EmisName,
    EmisSource,
)
from app.shared.contracts.identity import IdentityDirectory, UserStatus
from app.shared.ids import new_id

import structlog

log = structlog.get_logger(__name__)

MAX_ATTEMPTS = 5  # students tried until one EMIS link answers

CurriculumStatus = Literal["synced", "no_student"]


@dataclass(frozen=True, slots=True)
class CurriculumSyncResult:
    """How a curriculum sync ended and what it stored."""

    status: CurriculumStatus
    group_id: UUID
    subjects: int = 0
    names_filled: int = 0
    terms_created: int = 0


class SyncGroupCurriculum:
    """Read a group's curriculum through one of its students' EMIS links.

    The curriculum belongs to the group, so any student with a working link answers
    for all of them. It is read once, when the group has none stored (`ensure`, from
    the first student's profile refresh); an existing one is refreshed only when
    Administration asks for it (`execute`). The stored curriculum is replaced;
    subject names are only filled where a language is empty; terms are created for
    semesters that no term covers.
    """

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        emis: EmisSource,
        identity: IdentityDirectory,
        clock: Clock,
    ) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory
        self.emis = emis
        self.identity = identity
        self.clock = clock

    async def ensure(self, group_id: UUID) -> CurriculumSyncResult | None:
        """Sync the group only if it has no stored curriculum; None when it has one."""
        async with self.uow_factory() as uow:
            if await uow.curricula.exists(group_id):
                return None
        try:
            return await self.execute(group_id)
        except CurriculumNoEmisStudentError:
            return CurriculumSyncResult("no_student", group_id)

    async def execute(self, group_id: UUID) -> CurriculumSyncResult:
        """Sync the group now, replacing the stored curriculum.

        Raises GroupNotFoundError for an unknown group, CurriculumNoEmisStudentError
        when no student of the group has a working EMIS login, and EmisUnavailable when
        EMIS cannot be read. Students without a working login are skipped on the way.
        """
        async with self.uow_factory() as uow:
            group = await uow.groups.get(group_id)
            if group is None:
                raise GroupNotFoundError()
            students = await uow.students.list_filtered(
                group_id=group_id, status="active"
            )
        source = await self._fetch(sorted(s.user_id for s in students))
        if source is None:
            log.info("curriculum_no_student", group_id=str(group_id))
            raise CurriculumNoEmisStudentError()
        async with self.uow_factory() as uow:
            subjects = await self._store(uow, group_id, source)
            filled = await self._fill_names(uow, source)
            await uow.commit()
        created = await self._create_terms(source)
        log.info(
            "curriculum_synced",
            group_id=str(group_id),
            emis_curriculum_id=source.emis_id,
            subjects=subjects,
            names_filled=filled,
            terms_created=created,
        )
        return CurriculumSyncResult("synced", group_id, subjects, filled, created)

    # - - - EMIS - - -

    async def _fetch(self, user_ids: list[UUID]) -> EmisCurriculum | None:
        """Ask up to MAX_ATTEMPTS students in turn; None when none can answer.

        A student whose EMIS login is rejected or not stored is skipped. An outage is
        not a student's fault: it propagates, and the group is not synced.
        """
        users = await self.identity.get_users(user_ids)
        usable = [
            uid
            for uid in user_ids
            if uid in users
            and users[uid].status == UserStatus.ACTIVE
            and users[uid].emis_status == "active"
        ]
        for user_id in usable[:MAX_ATTEMPTS]:
            try:
                return await self.emis.curriculum(user_id)
            except (EmisAuthFailed, EmisCredentialsMissing) as exc:
                log.warning(
                    "curriculum_student_skipped",
                    user_id=str(user_id),
                    reason=exc.code,
                )
        return None

    # - - - storing - - -

    async def _store(
        self, uow: ScheduleUnitOfWork, group_id: UUID, source: EmisCurriculum
    ) -> int:
        """Write the header and replace the semester subjects; return their count."""
        rows = semester_subjects_from_emis(source.semester_subjects)
        await uow.curricula.save(
            curriculum_from_emis(group_id, source, self.clock.now())
        )
        await uow.curricula.replace_subjects(group_id, rows)
        return len(rows)

    @staticmethod
    async def _fill_names(uow: ScheduleUnitOfWork, source: EmisCurriculum) -> int:
        """Fill empty languages of existing subjects; return how many subjects changed.

        A name that exists is never overwritten and no subject is created here.
        """
        offers: dict[int, list[EmisName]] = {}
        for item in source.subjects:
            offers.setdefault(item.emis_subject_id, []).append(item.name)
        for row in source.semester_subjects:
            offers.setdefault(row.emis_subject_id, []).append(row.name)
        known = await uow.subjects.get_by_emis_ids(offers)
        changed = 0
        for emis_id, subject in known.items():
            filled = fill_missing_names(subject.name, first_names(offers[emis_id]))
            if filled != subject.name:
                subject.name = filled
                await uow.subjects.save(subject)
                changed += 1
        return changed

    # - - - terms - - -

    async def _create_terms(self, source: EmisCurriculum) -> int:
        """Create a term for each semester that no term covers; return how many."""
        created = 0
        for item in sorted(source.semesters, key=lambda s: s.number):
            slot = term_for_semester(item.starts_on, item.ends_on, item.number)
            if await self._create_term(slot):
                created += 1
        return created

    async def _create_term(self, slot: SemesterTerm) -> bool:
        """Insert the term unless dates or year and half are taken; one transaction.

        A term that overlaps the semester is never touched: Administration may have
        edited it.
        """
        async with self.uow_factory() as uow:
            if await uow.terms.overlapping(
                slot.starts_on, slot.ends_on, exclude_id=None
            ):
                log.info("curriculum_term_exists", semester=slot.number)
                return False
            term = Term(
                id=new_id(),
                academic_year=slot.academic_year,
                half=slot.half,
                starts_on=slot.starts_on,
                ends_on=slot.ends_on,
            )
            try:
                await check_term(uow, term, exclude_id=None)
                await uow.terms.add(term)
            except (TermOverlapError, TermDuplicateError, TermDatesInvalidError) as exc:
                log.info(
                    "curriculum_term_skipped",
                    semester=slot.number,
                    academic_year=slot.academic_year,
                    half=slot.half,
                    reason=exc.code,
                )
                return False
            await uow.commit()
        log.info(
            "curriculum_term_created",
            term_id=str(term.id),
            academic_year=term.academic_year,
            half=term.half,
            starts_on=term.starts_on.isoformat(),
            ends_on=term.ends_on.isoformat(),
        )
        return True
