"""Matching a teacher named by EMIS to an existing teacher account (no duplicates)."""

from collections.abc import Iterable

from app.modules.identity.domain.user import User
from app.shared.text import slugify


def _key(value: str | None) -> str:
    """Names compare as lowercase Latin: ``Каландарова`` equals ``KALANDAROVA``."""
    return slugify(value or "")


def matching_teachers(
    teachers: Iterable[User],
    *,
    emis_teacher_id: int | None,
    first_name: str,
    last_name: str,
    middle_name: str | None,
) -> list[User]:
    """Return the accounts that can be this teacher, best guess first.

    Accounts linked to another EMIS teacher never match. If several accounts share
    the surname and name, a given patronymic narrows them; what is left may still
    be more than one, and then the caller must not guess.
    """
    wanted = (_key(last_name), _key(first_name))
    found = [
        teacher
        for teacher in teachers
        if (_key(teacher.last_name), _key(teacher.first_name)) == wanted
        and (teacher.emis_teacher_id in (None, emis_teacher_id))
    ]
    if len(found) > 1 and middle_name:
        narrowed = [t for t in found if _key(t.middle_name) == _key(middle_name)]
        found = narrowed or found
    return found
