"""Checks shared by the reading list use cases: who may write for which audience."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.library.domain.access import is_librarian
from app.modules.library.domain.enums import ListScope, ListStatus
from app.modules.library.domain.reading_list import ReadingList
from app.modules.library.domain.reading_list_policy import needs_staff
from app.modules.library.domain.taxonomy_errors import (
    ListForbiddenError,
    UnknownSubjectError,
)
from app.modules.library.ports.directories import AcademicDirectory
from app.shared.actor import Actor, Role
from app.shared.notifications import NotificationDraft, NotificationType


async def ensure_may_write(
    academic: AcademicDirectory,
    actor: Actor,
    *,
    scope: ListScope,
    subject_id: UUID | None,
    group_ids: Sequence[UUID],
) -> None:
    """Librarians write for anyone; a teacher for the subjects and groups they teach.

    School lists and lists without a subject are for librarians only.
    """
    if subject_id is not None and not await academic.subject_names([subject_id], "en"):
        raise UnknownSubjectError(params={"subject_id": str(subject_id)})
    if is_librarian(actor):
        return
    if Role.TEACHER not in actor.roles or needs_staff(scope, subject_id):
        raise ListForbiddenError(params={"scope": scope.value})
    if subject_id is not None and not await academic.teacher_teaches_subject(
        actor.user_id, subject_id
    ):
        raise ListForbiddenError(params={"subject_id": str(subject_id)})
    if scope is ListScope.GROUPS:
        own = {group.id for group in await academic.teacher_groups(actor.user_id)}
        if not set(group_ids) <= own:
            raise ListForbiddenError(params={"scope": scope.value})


async def publication_notices(
    academic: AcademicDirectory,
    reading_list: ReadingList,
    subject_name: str | None,
) -> list[NotificationDraft]:
    """One notice per student of the groups, when a list for groups is published."""
    if reading_list.scope is not ListScope.GROUPS:
        return []
    students = await academic.group_user_ids(reading_list.group_ids)
    return [
        NotificationDraft(
            user_id=student,
            type=NotificationType.LIBRARY_READING_LIST_NEW,
            payload={
                "list_id": str(reading_list.id),
                "title": reading_list.title,
                "subject": subject_name or "",
            },
            dedupe_key=f"library_reading_list_new:{student}:{reading_list.id}",
        )
        for student in dict.fromkeys(students)
    ]


def is_first_publication(before: ListStatus, after: ListStatus) -> bool:
    """A draft that becomes published (archived lists coming back stay quiet)."""
    return before is ListStatus.DRAFT and after is ListStatus.PUBLISHED
