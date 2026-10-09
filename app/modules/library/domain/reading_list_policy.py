"""Who sees and who changes a reading list (doc § 2.3). Pure rules; no I/O."""

from uuid import UUID

from app.modules.library.domain.access import is_librarian, is_signed_in
from app.modules.library.domain.enums import ListScope, ListStatus
from app.modules.library.domain.reading_list import ReadingList
from app.shared.actor import Actor, Role


def can_view_list(
    reading_list: ReadingList, actor: Actor | None, *, group_id: UUID | None
) -> bool:
    """May the actor open the list?

    The owner and librarians see every list. Everyone else sees published lists:
    teachers all of them, students the school and subject lists and the lists of
    their own group (`group_id`).
    """
    if actor is None:
        return False
    if is_librarian(actor) or reading_list.owner_id == actor.user_id:
        return True
    if reading_list.status is not ListStatus.PUBLISHED:
        return False
    if Role.TEACHER in actor.roles:
        return True
    if not is_signed_in(actor):
        return False
    if reading_list.scope is ListScope.GROUPS:
        return group_id is not None and group_id in reading_list.group_ids
    return True


def can_edit_list(reading_list: ReadingList, actor: Actor) -> bool:
    """Librarians and Administration edit any list; a teacher only their own."""
    if is_librarian(actor):
        return True
    return Role.TEACHER in actor.roles and reading_list.owner_id == actor.user_id


def needs_staff(scope: ListScope, subject_id: UUID | None) -> bool:
    """School lists and lists without a subject are written by librarians only."""
    return scope is ListScope.SCHOOL or subject_id is None
