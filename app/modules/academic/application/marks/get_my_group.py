"""The caller's own group for every student: homeroom teacher, head student, members."""

from typing import Any
from uuid import UUID

from app.modules.academic.application.marks.ports.unit_of_work import MarksUowFactory
from app.modules.academic.domain.marks.errors import StudentNotFoundError
from app.shared.actor import Actor
from app.shared.contracts.identity import IdentityDirectory, UserRef


def _person(user: UserRef | None) -> dict[str, Any] | None:
    if user is None:
        return None
    return {"id": user.id, "first_name": user.first_name, "last_name": user.last_name}


class GetMyGroup:
    """Return the caller's group (any student of it may read this).

    The homeroom teacher is the group's curator, with the public contacts that are
    shown to students. The head student is shown by name only. Members are the
    active students of the group, sorted by name. Unassigned roles are null; a head
    student who has left the group is null too.
    """

    def __init__(
        self, *, uow_factory: MarksUowFactory, identity: IdentityDirectory
    ) -> None:
        """Store collaborators."""
        self._uow_factory = uow_factory
        self._identity = identity

    async def execute(self, actor: Actor) -> dict[str, Any]:
        """Return the group card and its members for the caller."""
        async with self._uow_factory() as uow:
            ctx = await uow.reader.student_context(actor.user_id)
            if ctx is None:
                raise StudentNotFoundError()
            group = await uow.reader.group_roles(ctx.group_id)
            if group is None:
                raise StudentNotFoundError()
        member_ids = list(group.student_ids)
        head_id = group.head_student_id if group.head_student_id in member_ids else None
        curator_id = group.curator_id
        wanted: set[UUID] = set(member_ids)
        if curator_id is not None:
            wanted.add(curator_id)
        users = await self._identity.get_users(sorted(wanted, key=str))

        members = sorted(
            (users[uid] for uid in member_ids if uid in users),
            key=lambda u: (u.last_name.casefold(), u.first_name.casefold()),
        )
        homeroom: dict[str, Any] | None = None
        if curator_id is not None and curator_id in users:
            prefs = await self._identity.get_preferences(curator_id)
            homeroom = _person(users[curator_id])
            if homeroom is not None:
                homeroom["contacts"] = prefs.contacts.model_dump(mode="json")

        return {
            "id": group.id,
            "name": group.name,
            "size": len(member_ids),
            "is_head_student": head_id == actor.user_id,
            "homeroom_teacher": homeroom,
            "head_student": _person(users[head_id]) if head_id in users else None,
            "members": [
                {
                    "id": user.id,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "is_head_student": user.id == head_id,
                    "is_me": user.id == actor.user_id,
                }
                for user in members
            ],
        }
