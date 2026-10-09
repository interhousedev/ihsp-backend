"""The two assistants and who may use them."""

from enum import StrEnum

from app.shared.actor import Actor, Role


class Assistant(StrEnum):
    """Which assistant a chat belongs to."""

    STUDENT = "student"
    ADMIN = "admin"
    LMS_AUTHOR = "lms_author"  # course staff, inside one course workspace


# The author assistant has no global role: course staff may use it, checked per course.
ASSISTANT_ROLE: dict[Assistant, Role] = {
    Assistant.STUDENT: Role.STUDENT,
    Assistant.ADMIN: Role.ADMIN,
}


def default_assistant(actor: Actor) -> Assistant:
    """Return the assistant a caller means when they do not name one."""
    if actor.has(Role.STUDENT):
        return Assistant.STUDENT
    return Assistant.ADMIN
