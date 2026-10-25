"""Add a subject that is not in EMIS, or link one to EMIS (ADM-7)."""

from app.modules.academic.application.schedule.common import UowFactory
from app.modules.academic.domain.schedule.errors import SubjectEmisIdTakenError
from app.modules.academic.domain.schedule.subject import Subject, clean_names
from app.shared.ids import new_id


class CreateSubject:
    """Create a subject with names in uz, ru and en."""

    def __init__(self, uow_factory: UowFactory) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory

    async def execute(
        self,
        *,
        name: dict[str, str],
        short_name: str | None = None,
        emis_subject_id: int | None = None,
        can_be_divided: bool = False,
    ) -> Subject:
        """Insert the subject; the EMIS id must be unused."""
        subject = Subject(
            id=new_id(),
            name=clean_names(name),
            short_name=(short_name or "").strip() or None,
            emis_subject_id=emis_subject_id,
            can_be_divided=can_be_divided,
        )
        async with self.uow_factory() as uow:
            if (
                emis_subject_id is not None
                and await uow.subjects.get_by_emis_id(emis_subject_id) is not None
            ):
                raise SubjectEmisIdTakenError(
                    params={"emis_subject_id": emis_subject_id}
                )
            await uow.subjects.add(subject)
            await uow.commit()
        return subject
