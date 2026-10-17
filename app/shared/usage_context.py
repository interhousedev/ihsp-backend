"""Who a model call is made for, carried from the request or job to the gateway.

The AI gateways do not receive the actor, so the entry points set it here: the HTTP
dependency that authenticates a request (`get_actor`). A call outside a request (a
worker job, a scheduled task) has no actor and is recorded as a system call.
"""

from contextvars import ContextVar, Token
from dataclasses import dataclass
from uuid import UUID

from app.shared.actor import Actor, Role

ROLE_STUDENT = "student"
ROLE_TEACHER = "teacher"
ROLE_ADMIN = "admin"
ROLE_STAFF = "staff"
ROLE_SYSTEM = "system"


@dataclass(frozen=True, slots=True)
class UsageActor:
    """The user a call is made for and the role it is counted under."""

    user_id: UUID | None
    role: str


_current: ContextVar[UsageActor | None] = ContextVar("usage_actor", default=None)


def role_of(actor: Actor) -> str:
    """The role of the usage ledger: admin, teacher, student, else staff."""
    if actor.has(Role.ADMIN):
        return ROLE_ADMIN
    if actor.has(Role.TEACHER):
        return ROLE_TEACHER
    if actor.has(Role.STUDENT):
        return ROLE_STUDENT
    return ROLE_STAFF


def bind_usage_actor(actor: Actor) -> Token[UsageActor | None]:
    """Make `actor` the caller of the model calls made in this context."""
    return _current.set(UsageActor(actor.user_id, role_of(actor)))


def reset_usage_actor(token: Token[UsageActor | None]) -> None:
    """Undo a `bind_usage_actor`."""
    _current.reset(token)


def current_usage_actor() -> UsageActor:
    """The caller of the calls made now; a system call when nobody is bound."""
    return _current.get() or UsageActor(None, ROLE_SYSTEM)


def bind_usage_user(user_id: UUID, *, unlimited: bool) -> Token[UsageActor | None]:
    """Count the calls of a job for a user (staff when `unlimited`, else student)."""
    return _current.set(UsageActor(user_id, ROLE_STAFF if unlimited else ROLE_STUDENT))
