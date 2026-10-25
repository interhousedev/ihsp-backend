"""Teachers and groups of a subject in the current term (admin EMIS pulls)."""

from dataclasses import dataclass, field
from uuid import UUID

from app.modules.academic.application.schedule.common import UowFactory, today
from app.modules.academic.domain import audience as audience_keys
from app.modules.academic.domain.schedule.errors import SubjectNotFoundError
from app.modules.academic.domain.schedule.term import pick_current_term
from app.shared.clock import Clock
from app.shared.contracts.identity import IdentityDirectory


@dataclass(frozen=True, slots=True)
class NamedRef:
    """An id and the name to show."""

    id: UUID
    name: str


@dataclass(frozen=True, slots=True)
class SubjectPeople:
    """Who teaches the subject and which groups have it, sorted by name."""

    teachers: list[NamedRef] = field(default_factory=list)
    groups: list[NamedRef] = field(default_factory=list)


class GetSubjectPeople:
    """Reads the timetable entries of the current term that carry the subject."""

    def __init__(
        self, uow_factory: UowFactory, identity: IdentityDirectory, clock: Clock
    ) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory
        self.identity = identity
        self.clock = clock

    async def execute(self, subject_id: UUID) -> SubjectPeople:
        """The subject's teachers and groups; empty lists without a term."""
        async with self.uow_factory() as uow:
            if await uow.subjects.get(subject_id) is None:
                raise SubjectNotFoundError(params={"subject_id": str(subject_id)})
            term = pick_current_term(await uow.terms.list_all(), today(self.clock))
            if term is None:
                return SubjectPeople()
            entries = [
                entry
                for entry in await uow.entries.list_for_term(term.id)
                if entry.subject_id == subject_id
            ]
            group_ids = set().union(
                *(audience_keys.group_ids(entry.audience) for entry in entries)
            )
            groups = await uow.groups.get_many(group_ids) if group_ids else {}
        teacher_ids = sorted({e.teacher_id for e in entries if e.teacher_id})
        users = await self.identity.get_users(teacher_ids) if teacher_ids else {}
        teachers = [
            NamedRef(uid, f"{user.last_name} {user.first_name}".strip())
            for uid, user in users.items()
        ]
        return SubjectPeople(
            teachers=sorted(teachers, key=lambda ref: ref.name),
            groups=sorted(
                (NamedRef(g.id, g.name) for g in groups.values()),
                key=lambda ref: ref.name,
            ),
        )
