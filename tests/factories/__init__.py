"""Factories for tests; every module adds tests/factories/<module>.py."""

from uuid import UUID

from app.shared.actor import Actor, Role
from app.shared.ids import new_id


def make_actor(*roles: Role, user_id: UUID | None = None, **kwargs: object) -> Actor:
    """Build an Actor with the given roles; other Actor fields via keywords."""
    return Actor(
        user_id=user_id or new_id(),
        roles=frozenset(roles),
        **kwargs,  # type: ignore[arg-type]
    )
