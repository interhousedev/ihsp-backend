"""Login cues: EMIS logins an administrator pre-registered for students.

A cue lets a student pick their group and name instead of typing the EMIS login.
The login itself is stored encrypted and is never sent to a browser; only its last
two characters are kept in clear for the administrator's list.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

TAIL_LENGTH = 2
MASK = "••••"


def login_tail(login: str) -> str:
    """Return the last characters of the login that the admin list may show."""
    return login.strip()[-TAIL_LENGTH:]


def masked_login(tail: str) -> str:
    """Return the admin view of a login: everything hidden except the tail."""
    return f"{MASK}{tail}"


def first_name(full_name: str) -> str:
    """Return the given name of a "Surname Given Patronymic" name for public lists."""
    parts = full_name.split()
    return parts[1] if len(parts) > 1 else "".join(parts)


def short_names(full_names: list[str]) -> list[str]:
    """Return given names only; repeated ones are numbered so rows stay distinct."""
    names = [first_name(name) for name in full_names]
    seen: dict[str, int] = {}
    numbered = []
    for name in names:
        if names.count(name) == 1:
            numbered.append(name)
            continue
        seen[name] = seen.get(name, 0) + 1
        numbered.append(f"{name} ({seen[name]})")
    return numbered


@dataclass(frozen=True, slots=True)
class LoginCue:
    """One pre-registered (EMIS login, full name, group) triple."""

    id: UUID
    emis_login_enc: str
    login_tail: str
    full_name: str
    group_id: UUID
    created_at: datetime
    consumed_at: datetime | None = None
    consumed_by_user_id: UUID | None = None

    @property
    def consumed(self) -> bool:
        """True once a registration has claimed the cue."""
        return self.consumed_at is not None
