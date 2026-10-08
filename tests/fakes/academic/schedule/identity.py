"""Fake identity module: a directory and commands for the schedule tests."""

from collections.abc import Sequence
from typing import Any, Literal
from uuid import UUID

from app.shared.actor import Role
from app.shared.contracts.identity import UserRef, UserStatus
from app.shared.ids import new_id


def make_user(
    user_id: UUID | None = None,
    *,
    first_name: str = "Aliya",
    last_name: str = "Karimova",
    middle_name: str | None = None,
    roles: frozenset[Role] = frozenset({Role.STUDENT}),
    status: UserStatus = UserStatus.ACTIVE,
    locale: str = "en",
    login: str | None = "aliya.karimova",
    emis_status: Literal["active", "needs_reauth"] | None = "active",
) -> UserRef:
    """Build a UserRef with test defaults."""
    return UserRef(
        id=user_id or new_id(),
        login=login,
        first_name=first_name,
        last_name=last_name,
        middle_name=middle_name,
        roles=roles,
        status=status,
        locale=locale,
        emis_status=emis_status,
    )


class FakeIdentity:
    """In-memory IdentityDirectory (the parts the schedule uses)."""

    def __init__(self) -> None:
        """Start empty."""
        self.users: dict[UUID, UserRef] = {}

    def add(self, user: UserRef) -> UserRef:
        """Register a user."""
        self.users[user.id] = user
        return user

    async def get_user(self, user_id: UUID) -> UserRef | None:
        """Return the user or None."""
        return self.users.get(user_id)

    async def get_users(self, user_ids: Sequence[UUID]) -> dict[UUID, UserRef]:
        """Return the known users among the ids."""
        return {uid: self.users[uid] for uid in user_ids if uid in self.users}

    async def user_ids_with_roles(self, roles: Sequence[Role]) -> list[UUID]:
        """Return users holding any of the roles."""
        return [u.id for u in self.users.values() if set(roles) & set(u.roles)]


class FakeIdentityCommands:
    """Creates unregistered students in the fake directory and records the calls."""

    def __init__(self, directory: FakeIdentity) -> None:
        """Create users in the given directory."""
        self.directory = directory
        self.created: list[dict[str, Any]] = []
        self.teachers: list[dict[str, Any]] = []
        self._emis_teachers: dict[int, UserRef] = {}

    async def create_unregistered_student(
        self,
        *,
        first_name: str,
        last_name: str,
        middle_name: str | None,
        emis_student_id: int | None,
    ) -> UserRef:
        """Create a user with status unregistered."""
        user = make_user(
            first_name=first_name,
            last_name=last_name,
            middle_name=middle_name,
            status=UserStatus.UNREGISTERED,
            login=None,
            emis_status=None,
        )
        self.directory.add(user)
        self.created.append(
            {
                "user_id": user.id,
                "first_name": first_name,
                "last_name": last_name,
                "middle_name": middle_name,
                "emis_student_id": emis_student_id,
            }
        )
        return user

    async def ensure_teacher(
        self,
        *,
        emis_teacher_id: int | None,
        first_name: str,
        last_name: str,
        middle_name: str | None,
    ) -> UserRef:
        """Find a teacher by EMIS id or name, else create a pending one."""
        self.teachers.append(
            {"emis_teacher_id": emis_teacher_id, "last_name": last_name}
        )
        known = self._emis_teachers.get(emis_teacher_id) if emis_teacher_id else None
        if known is None:
            known = next(
                (
                    user
                    for user in self.directory.users.values()
                    if Role.TEACHER in user.roles
                    and (user.last_name.casefold(), user.first_name.casefold())
                    == (last_name.casefold(), first_name.casefold())
                ),
                None,
            )
        if known is None:
            known = make_user(
                first_name=first_name,
                last_name=last_name,
                middle_name=middle_name,
                roles=frozenset({Role.TEACHER}),
                status=UserStatus.PENDING_ACTIVATION,
                login=f"{last_name}.{first_name}".lower(),
                emis_status=None,
            )
            self.directory.add(known)
        if emis_teacher_id:
            self._emis_teachers[emis_teacher_id] = known
        return known
