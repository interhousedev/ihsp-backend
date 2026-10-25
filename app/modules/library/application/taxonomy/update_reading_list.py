"""Change a reading list: texts, audience, term, status (LIB-4)."""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from app.modules.library.application.locale import resolve_locale
from app.modules.library.application.taxonomy.list_rules import (
    ensure_may_write,
    is_first_publication,
    publication_notices,
)
from app.modules.library.application.taxonomy.reading_list_builder import (
    ReadingListBuilder,
)
from app.modules.library.application.taxonomy.views import ReadingListDetailView
from app.modules.library.domain.enums import ListScope, ListStatus
from app.modules.library.domain.errors import ListNotFoundError
from app.modules.library.domain.reading_list import (
    ReadingList,
    clean_list_text,
    validate_audience,
    validate_term,
)
from app.modules.library.domain.reading_list_policy import (
    can_edit_list,
    can_view_list,
)
from app.modules.library.domain.taxonomy_audit import TaxonomyAuditType
from app.modules.library.domain.taxonomy_errors import ListForbiddenError
from app.modules.library.domain.taxonomy_unset import UNSET, Unset
from app.modules.library.ports.directories import AcademicDirectory
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.contracts.identity import IdentityDirectory
from app.shared.notifications import AuditDraft


@dataclass(frozen=True, slots=True)
class ListChanges:
    """What a PATCH sent; fields left at `UNSET` stay as they are."""

    title: str | Unset = UNSET
    description: str | None | Unset = UNSET
    scope: ListScope | Unset = UNSET
    subject_id: UUID | None | Unset = UNSET
    group_ids: Sequence[UUID] | Unset = UNSET
    year_of_study: int | None | Unset = UNSET
    academic_year: str | None | Unset = UNSET
    term_half: int | None | Unset = UNSET
    status: ListStatus | Unset = UNSET


def _set[T](current: T, new: T | Unset) -> T:
    return current if isinstance(new, Unset) else new


def apply_changes(lst: ReadingList, changes: ListChanges) -> None:
    """Copy the sent fields onto the list, then check the whole list again."""
    lst.title, lst.description = clean_list_text(
        _set(lst.title, changes.title), _set(lst.description, changes.description)
    )
    lst.scope = _set(lst.scope, changes.scope)
    lst.subject_id = _set(lst.subject_id, changes.subject_id)
    lst.year_of_study = _set(lst.year_of_study, changes.year_of_study)
    lst.academic_year = _set(lst.academic_year, changes.academic_year)
    lst.term_half = _set(lst.term_half, changes.term_half)
    lst.status = _set(lst.status, changes.status)
    lst.group_ids = validate_audience(
        lst.scope, lst.subject_id, _set(lst.group_ids, changes.group_ids)
    )
    validate_term(lst.year_of_study, lst.academic_year, lst.term_half)


class UpdateReadingList:
    """`PATCH /v1/library/reading-lists/{id}`: only the fields that were sent."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        clock: Clock,
        identity: IdentityDirectory,
        academic: AcademicDirectory,
        builder: ReadingListBuilder,
    ) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.identity = identity
        self.academic = academic
        self.builder = builder

    async def execute(
        self,
        actor: Actor,
        list_id: UUID,
        changes: ListChanges,
        *,
        accept_language: str | None = None,
    ) -> ReadingListDetailView:
        """Apply the given changes; the first publication tells the groups."""
        locale = await resolve_locale(self.identity, actor, accept_language)
        async with self.uow_factory() as uow:
            lst = await uow.lists.get(list_id, lock=True)
            if lst is None or not can_view_list(lst, actor, group_id=None):
                raise ListNotFoundError(params={"list_id": str(list_id)})
            if not can_edit_list(lst, actor):
                raise ListForbiddenError(params={"list_id": str(list_id)})
            before = lst.status
            apply_changes(lst, changes)
            await ensure_may_write(
                self.academic,
                actor,
                scope=lst.scope,
                subject_id=lst.subject_id,
                group_ids=lst.group_ids,
            )
            lst.updated_at = self.clock.now()
            await uow.lists.save(lst)
            if is_first_publication(before, lst.status):
                names = await self.academic.subject_names(
                    [lst.subject_id] if lst.subject_id else [], locale
                )
                uow.notify(
                    *await publication_notices(
                        self.academic,
                        lst,
                        names.get(lst.subject_id) if lst.subject_id else None,
                    )
                )
            uow.audit(
                AuditDraft(
                    type=TaxonomyAuditType.LIST_UPDATE.value,
                    actor_id=actor.user_id,
                    metadata={"list_id": str(lst.id), "status": lst.status.value},
                )
            )
            await uow.commit()
            return await self.builder.detail_for(uow, lst, viewer=actor, locale=locale)
