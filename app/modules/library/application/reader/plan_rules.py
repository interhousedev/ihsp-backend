"""Who may keep a textbook plan, and which item a plan or a lesson link may name."""

from uuid import UUID

from app.modules.library.application.reader.access import load_visible_item
from app.modules.library.domain.access import is_librarian
from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import ItemKind
from app.modules.library.domain.errors import NotSupportedError
from app.modules.library.domain.reader_errors import SubjectNotFoundError
from app.modules.library.ports.directories import AcademicDirectory
from app.modules.library.ports.unit_of_work import LibraryUnitOfWork
from app.shared.actor import Actor, Role
from app.shared.base_error import ForbiddenError


def ensure_plan_reader(actor: Actor) -> None:
    """Teachers, librarians and Administration read plans; students do not."""
    if not actor.roles & {Role.TEACHER, Role.LIBRARIAN, Role.ADMIN}:
        raise ForbiddenError(params={"roles": ["teacher", "librarian", "admin"]})


async def ensure_plan_rights(
    academic: AcademicDirectory, actor: Actor, subject_id: UUID
) -> None:
    """Librarians and Administration; a teacher only for a subject they teach."""
    if not await academic.subject_names([subject_id], "en"):
        raise SubjectNotFoundError(params={"subject_id": str(subject_id)})
    if is_librarian(actor):
        return
    if Role.TEACHER in actor.roles and await academic.teacher_teaches_subject(
        actor.user_id, subject_id
    ):
        return
    raise ForbiddenError(params={"subject_id": str(subject_id)})


async def load_pageable_item(
    uow: LibraryUnitOfWork, actor: Actor, item_id: UUID
) -> Item:
    """A visible book or material with files; UniLibrary records have no pages."""
    item = await load_visible_item(uow, actor, item_id)
    if item.kind is ItemKind.EXTERNAL or not item.files:
        raise NotSupportedError(support_details=f"item {item_id} has no pages")
    return item
