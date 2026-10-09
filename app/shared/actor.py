"""Who performs an action."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.shared.base_error import ForbiddenError


class Role(StrEnum):
    """Global roles stored in users.roles."""

    STUDENT = "student"
    TEACHER = "teacher"
    ADMIN = "admin"
    LMS_ADMIN = "lms_admin"
    LIBRARIAN = "librarian"


@dataclass(frozen=True, slots=True)
class Actor:
    """Authenticated caller of a use case."""

    user_id: UUID
    roles: frozenset[Role]
    session_id: UUID | None = None
    connector_id: UUID | None = None
    client_id: str | None = None
    amr: frozenset[str] = field(default_factory=frozenset)
    mfa_at: datetime | None = None
    scopes: frozenset[str] = field(default_factory=frozenset)

    def has(self, role: Role) -> bool:
        """Return True if the actor holds the role."""
        return role in self.roles

    def require(self, *roles: Role) -> None:
        """Raise ForbiddenError unless the actor holds one of the roles."""
        if not any(r in self.roles for r in roles):
            raise ForbiddenError(params={"roles": [r.value for r in roles]})


SYSTEM_USER_ID = UUID(int=0)
SYSTEM_ACTOR = Actor(user_id=SYSTEM_USER_ID, roles=frozenset(Role))
