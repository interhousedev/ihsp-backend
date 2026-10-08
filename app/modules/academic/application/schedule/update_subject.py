"""Edit a subject or link it to its EMIS subject (ADM-7)."""

from uuid import UUID

from app.modules.academic.application.schedule.common import UowFactory
from app.modules.academic.application.schedule.ports.unit_of_work import (
    ScheduleUnitOfWork,
)
from app.modules.academic.application.schedule.unset import UNSET, Unset
from app.modules.academic.domain.schedule.errors import (
    SubjectEmisIdTakenError,
    SubjectNotFoundError,
)
from app.modules.academic.domain.schedule.subject import Subject, clean_names


class UpdateSubject:
    """Apply a partial change to a subject."""

    def __init__(self, uow_factory: UowFactory) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory

    async def execute(
        self,
        subject_id: UUID,
        *,
        name: dict[str, str] | None = None,
        short_name: str | None | Unset = UNSET,
        emis_subject_id: int | None | Unset = UNSET,
        can_be_divided: bool | None = None,
    ) -> Subject:
        """Change the fields that were sent; None clears short name or EMIS link."""
        async with self.uow_factory() as uow:
            subject = await uow.subjects.get(subject_id)
            if subject is None:
                raise SubjectNotFoundError()
            if name is not None:
                subject.name = clean_names(name)
            if not isinstance(short_name, Unset):
                subject.short_name = (short_name or "").strip() or None
            if not isinstance(emis_subject_id, Unset):
                await self._link(uow, subject, emis_subject_id)
            if can_be_divided is not None:
                subject.can_be_divided = can_be_divided
            await uow.subjects.save(subject)
            await uow.commit()
        return subject

    @staticmethod
    async def _link(
        uow: ScheduleUnitOfWork, subject: Subject, emis_subject_id: int | None
    ) -> None:
        """Set the EMIS link after checking nobody else has it."""
        if emis_subject_id is not None:
            other = await uow.subjects.get_by_emis_id(emis_subject_id)
            if other is not None and other.id != subject.id:
                raise SubjectEmisIdTakenError(
                    params={"emis_subject_id": emis_subject_id}
                )
        subject.emis_subject_id = emis_subject_id
