"""OAuth / MCP scopes that limit what a connector may do in the LMS.

A browser session carries no scopes and is limited by roles and course permissions
only. A connector or an OAuth client carries scopes, and every LMS use case checks
them next to the roles: the scopes can only narrow what the user may do.
"""

from collections.abc import Collection
from typing import Final

COURSES_READ: Final = "lms.courses.read"
COURSES_WRITE: Final = "lms.courses.write"  # course metadata
COURSES_DELETE: Final = "lms.courses.delete"
MODULES_WRITE: Final = "lms.modules.write"  # modules, lessons and steps only

LMS_SCOPES: Final = (COURSES_READ, COURSES_WRITE, COURSES_DELETE, MODULES_WRITE)

# Scopes issued before the split keep working with the meaning they had.
LEGACY_ALIASES: Final[dict[str, tuple[str, ...]]] = {
    "courses:read": (COURSES_READ,),
    "courses:draft": (MODULES_WRITE,),
}


def effective_scopes(scopes: Collection[str]) -> frozenset[str]:
    """The scopes plus what their legacy names stand for."""
    result = set(scopes)
    for old, new in LEGACY_ALIASES.items():
        if old in result:
            result.update(new)
    return frozenset(result)


def scope_allows(scopes: Collection[str], needed: str) -> bool:
    """True for an unscoped caller, or when the scope (or its alias) is granted."""
    return not scopes or needed in effective_scopes(scopes)


def scope_allows_read(scopes: Collection[str]) -> bool:
    """Reading is open to every LMS scope: a module editor must see the outline."""
    if not scopes:
        return True
    return bool(effective_scopes(scopes) & set(LMS_SCOPES))
