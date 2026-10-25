"""Subjects named by an EMIS timetable: found by EMIS id, then by name, else created."""

from app.modules.academic.application.schedule.ports.unit_of_work import (
    ScheduleUnitOfWork,
)
from app.modules.academic.domain.schedule.subject import LANGUAGES, Subject
from app.shared.contracts.emis import EmisSubject
from app.shared.ids import new_id


class SubjectResolver:
    """Resolves each EMIS subject once per import inside an open transaction."""

    def __init__(self, uow: ScheduleUnitOfWork) -> None:
        """Bind to the transaction; the cache lives as long as this object."""
        self._uow = uow
        self._known: dict[int, Subject] = {}

    async def resolve(self, emis: EmisSubject, *, divided: bool = False) -> Subject:
        """Return the subject; ``divided`` marks it as taught in halves (ACA-2)."""
        subject = self._known.get(emis.emis_subject_id)
        if subject is None:
            subject = await self._find(emis) or await self._create(emis)
            self._known[emis.emis_subject_id] = subject
        if divided and not subject.can_be_divided:
            subject.can_be_divided = True
            await self._uow.subjects.save(subject)
        return subject

    async def _find(self, emis: EmisSubject) -> Subject | None:
        found = await self._uow.subjects.get_by_emis_id(emis.emis_subject_id)
        if found is not None:
            return found
        names = _names(emis)
        wanted = {name.casefold() for name in names.values() if name}
        for name in dict.fromkeys(names.values()):
            for candidate in await self._uow.subjects.search(name):
                same = wanted & {n.strip().casefold() for n in candidate.name.values()}
                if same and candidate.emis_subject_id in (None, emis.emis_subject_id):
                    if candidate.emis_subject_id is None:
                        candidate.emis_subject_id = emis.emis_subject_id
                        await self._uow.subjects.save(candidate)
                    return candidate
        return None

    async def _create(self, emis: EmisSubject) -> Subject:
        subject = Subject(
            id=new_id(), name=_names(emis), emis_subject_id=emis.emis_subject_id
        )
        await self._uow.subjects.add(subject)
        return subject


def _names(emis: EmisSubject) -> dict[str, str]:
    given = {"uz": emis.name_uz, "ru": emis.name_ru, "en": emis.name_en}
    fallback = next((n.strip() for n in given.values() if n.strip()), "")
    fallback = fallback or f"Subject {emis.emis_subject_id}"
    return {lang: given[lang].strip() or fallback for lang in LANGUAGES}
