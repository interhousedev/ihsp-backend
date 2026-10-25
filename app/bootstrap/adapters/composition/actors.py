"""Synthetic actors: the composition ports run use cases on behalf of a user id."""

from uuid import UUID

from app.shared.actor import Actor, Role


def student_actor(user_id: UUID) -> Actor:
    """Return an actor holding only the student role (read-only student pages)."""
    return Actor(user_id=user_id, roles=frozenset({Role.STUDENT}))


def teacher_actor(user_id: UUID) -> Actor:
    """Return an actor holding only the teacher role (read-only staff pages)."""
    return Actor(user_id=user_id, roles=frozenset({Role.TEACHER}))


def admin_actor(user_id: UUID) -> Actor:
    """Return an actor holding only the admin role (for admin-only use cases)."""
    return Actor(user_id=user_id, roles=frozenset({Role.ADMIN}))
