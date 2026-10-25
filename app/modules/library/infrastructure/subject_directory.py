"""`AcademicDirectory` whose subjects are the library's own tree.

The library keeps its subjects (a librarian-managed tree). Ids that only the academic
module knows (reading lists and book plans made before the tree existed) still
resolve through the wrapped directory, so nothing that points at them breaks.
"""

from collections.abc import Sequence
from uuid import UUID

from app.modules.library.application.cards import pick_name
from app.modules.library.ports.directories import (
    AcademicDirectory,
    GroupView,
    SubjectView,
)
from app.modules.library.ports.unit_of_work import UowFactory


class LibrarySubjectDirectory:
    """Library subjects first, academic subjects as the fallback for old ids."""

    def __init__(self, inner: AcademicDirectory, uow_factory: UowFactory) -> None:
        """Wrap the academic directory."""
        self.inner = inner
        self.uow_factory = uow_factory

    async def subject_names(
        self, subject_ids: Sequence[UUID], locale: str
    ) -> dict[UUID, str]:
        """Names in the locale; a library subject wins over an academic one."""
        wanted = set(subject_ids)
        if not wanted:
            return {}
        async with self.uow_factory() as uow:
            own = await uow.taxonomy.subject_names(list(wanted))
        names = {sid: pick_name(name, locale) for sid, name in own.items()}
        rest = wanted - names.keys()
        if rest:
            names.update(await self.inner.subject_names(list(rest), locale))
        return names

    async def list_subjects(self, locale: str) -> list[SubjectView]:
        """The active library subjects, sorted by name."""
        async with self.uow_factory() as uow:
            subjects = await uow.taxonomy.subjects(include_archived=False)
        views = [SubjectView(s.id, pick_name(s.name, locale)) for s in subjects]
        return sorted(views, key=lambda view: view.name.casefold())

    async def student_group_id(self, user_id: UUID) -> UUID | None:
        """The active group of a student, or None."""
        return await self.inner.student_group_id(user_id)

    async def student_cohort(self, user_id: UUID) -> str:
        """The year the student joined, or an empty string."""
        return await self.inner.student_cohort(user_id)

    async def teacher_teaches_subject(self, user_id: UUID, subject_id: UUID) -> bool:
        """True when the teacher has lessons of the subject.

        A library subject counts when an academic subject of the same name in any
        language is taught by the teacher (the two trees are kept apart).
        """
        if await self.inner.teacher_teaches_subject(user_id, subject_id):
            return True
        async with self.uow_factory() as uow:
            own = (await uow.taxonomy.subject_names([subject_id])).get(subject_id)
        if not own:
            return False
        for locale in ("uz", "ru", "en"):
            wanted = own.get(locale, "").strip().casefold()
            if not wanted:
                continue
            for academic in await self.inner.list_subjects(locale):
                if academic.name.strip().casefold() == wanted and (
                    await self.inner.teacher_teaches_subject(user_id, academic.id)
                ):
                    return True
        return False

    async def group_user_ids(self, group_ids: Sequence[UUID]) -> list[UUID]:
        """Active students of the groups."""
        return await self.inner.group_user_ids(group_ids)

    async def teacher_groups(self, user_id: UUID) -> list[GroupView]:
        """Groups a teacher curates or teaches."""
        return await self.inner.teacher_groups(user_id)

    async def all_groups(self) -> list[GroupView]:
        """Every active group."""
        return await self.inner.all_groups()

    async def current_academic_year(self) -> str | None:
        """The academic year of the current term."""
        return await self.inner.current_academic_year()
