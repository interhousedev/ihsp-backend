"""How an uploader is shown to other users (LIB-13): "Aziza K., 2025" or a full name."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.library.ports.directories import AcademicDirectory
from app.shared.actor import Role
from app.shared.contracts.identity import IdentityDirectory

UNKNOWN_NAME = "Library user"
GROWN_UP_ROLES = frozenset({Role.TEACHER, Role.ADMIN})


@dataclass(frozen=True, slots=True)
class Attribution:
    """The name and cohort stored with a material at upload time."""

    name: str
    cohort: str = ""

    @property
    def label(self) -> str:
        """`author_label` of the card: the name, then the cohort after a comma."""
        return f"{self.name}, {self.cohort}" if self.cohort else self.name


def short_name(first_name: str, last_name: str) -> str:
    """First name and the initial of the last name: `Aziza K.`."""
    initial = last_name.strip()[:1].upper()
    return f"{first_name.strip()} {initial}." if initial else first_name.strip()


def full_name(first_name: str, last_name: str) -> str:
    """First and last name."""
    return f"{first_name.strip()} {last_name.strip()}".strip()


async def attribute(
    identity: IdentityDirectory,
    academic: AcademicDirectory,
    user_id: UUID,
    roles: frozenset[Role],
) -> Attribution:
    """Students by first name, initial and cohort; teachers and staff by full name."""
    user = await identity.get_user(user_id)
    if user is None:
        return Attribution(UNKNOWN_NAME)
    if Role.STUDENT not in roles or roles & GROWN_UP_ROLES:
        return Attribution(full_name(user.first_name, user.last_name))
    cohort = await academic.student_cohort(user_id)
    return Attribution(short_name(user.first_name, user.last_name), cohort)
