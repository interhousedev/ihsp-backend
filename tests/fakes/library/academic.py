"""In-memory AcademicDirectory for the library tests."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.library.ports.directories import GroupView, SubjectView


class FakeAcademicDirectory:
    """Subjects, groups and cohorts configured by the test."""

    def __init__(self) -> None:
        """Start empty; fill `subjects`, `groups`, `cohorts`, `teaches`."""
        self.subjects: dict[UUID, str] = {}
        self.groups: dict[UUID, UUID] = {}  # student -> group
        self.cohorts: dict[UUID, str] = {}
        self.teaches: set[tuple[UUID, UUID]] = set()  # (teacher, subject)
        self.members: dict[UUID, list[UUID]] = {}  # group -> students
        self.group_names: dict[UUID, str] = {}
        self.teacher_group_ids: dict[UUID, list[UUID]] = {}
        self.academic_year: str | None = "2026-2027"

    def add_subject(self, subject_id: UUID, name: str) -> UUID:
        """Register a subject and return its id."""
        self.subjects[subject_id] = name
        return subject_id

    async def subject_names(
        self, subject_ids: Sequence[UUID], locale: str
    ) -> dict[UUID, str]:
        """Names of the known subjects (the locale is ignored)."""
        return {sid: self.subjects[sid] for sid in subject_ids if sid in self.subjects}

    async def list_subjects(self, locale: str) -> list[SubjectView]:
        """All subjects by name."""
        views = [SubjectView(id=sid, name=name) for sid, name in self.subjects.items()]
        return sorted(views, key=lambda view: view.name)

    async def student_group_id(self, user_id: UUID) -> UUID | None:
        """The group configured for the student."""
        return self.groups.get(user_id)

    async def student_cohort(self, user_id: UUID) -> str:
        """The configured cohort or an empty string."""
        return self.cohorts.get(user_id, "")

    async def teacher_teaches_subject(self, user_id: UUID, subject_id: UUID) -> bool:
        """True when the pair was configured."""
        return (user_id, subject_id) in self.teaches

    async def group_user_ids(self, group_ids: Sequence[UUID]) -> list[UUID]:
        """Students of the configured groups."""
        return [uid for gid in group_ids for uid in self.members.get(gid, [])]

    async def teacher_groups(self, user_id: UUID) -> list[GroupView]:
        """The groups configured for the teacher."""
        ids = self.teacher_group_ids.get(user_id, [])
        return [GroupView(id=gid, name=self.group_names.get(gid, "")) for gid in ids]

    async def all_groups(self) -> list[GroupView]:
        """Every configured group by name."""
        views = [GroupView(id=gid, name=name) for gid, name in self.group_names.items()]
        return sorted(views, key=lambda view: view.name)

    async def current_academic_year(self) -> str | None:
        """The configured academic year."""
        return self.academic_year
