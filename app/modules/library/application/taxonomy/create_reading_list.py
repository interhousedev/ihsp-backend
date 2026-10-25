"""Create a reading list (LIB-4, LIB-2)."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.library.application.locale import resolve_locale
from app.modules.library.application.taxonomy.list_rules import (
    ensure_may_write,
    publication_notices,
)
from app.modules.library.application.taxonomy.reading_list_builder import (
    ReadingListBuilder,
)
from app.modules.library.application.taxonomy.views import ReadingListDetailView
from app.modules.library.domain.enums import ListScope, ListStatus
from app.modules.library.domain.reading_list import (
    ReadingList,
    clean_list_text,
    validate_audience,
    validate_term,
)
from app.modules.library.domain.taxonomy_audit import TaxonomyAuditType
from app.modules.library.domain.taxonomy_errors import ListInvalidError
from app.modules.library.ports.directories import AcademicDirectory
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.contracts.identity import IdentityDirectory
from app.shared.ids import new_id
from app.shared.notifications import AuditDraft


class CreateReadingList:
    """`POST /v1/library/reading-lists`: teachers (own subjects) and librarians."""

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
        *,
        title: str,
        scope: ListScope,
        description: str | None = None,
        subject_id: UUID | None = None,
        group_ids: Sequence[UUID] = (),
        year_of_study: int | None = None,
        academic_year: str | None = None,
        term_half: int | None = None,
        status: ListStatus = ListStatus.DRAFT,
        accept_language: str | None = None,
    ) -> ReadingListDetailView:
        """Store the list (no entries yet); a published list tells its groups."""
        if status is ListStatus.ARCHIVED:
            raise ListInvalidError(params={"field": "status"})
        clean_title, clean_text = clean_list_text(title, description)
        groups = validate_audience(scope, subject_id, group_ids)
        validate_term(year_of_study, academic_year, term_half)
        await ensure_may_write(
            self.academic, actor, scope=scope, subject_id=subject_id, group_ids=groups
        )
        now = self.clock.now()
        reading_list = ReadingList(
            id=new_id(),
            owner_id=actor.user_id,
            title=clean_title,
            scope=scope,
            status=status,
            created_at=now,
            updated_at=now,
            description=clean_text,
            subject_id=subject_id,
            group_ids=groups,
            year_of_study=year_of_study,
            academic_year=academic_year,
            term_half=term_half,
        )
        locale = await resolve_locale(self.identity, actor, accept_language)
        async with self.uow_factory() as uow:
            await uow.lists.add(reading_list)
            if status is ListStatus.PUBLISHED:
                names = await self.academic.subject_names(
                    [subject_id] if subject_id else [], locale
                )
                uow.notify(
                    *await publication_notices(
                        self.academic,
                        reading_list,
                        names.get(subject_id) if subject_id else None,
                    )
                )
            uow.audit(
                AuditDraft(
                    type=TaxonomyAuditType.LIST_UPDATE.value,
                    actor_id=actor.user_id,
                    metadata={
                        "list_id": str(reading_list.id),
                        "created": True,
                        "scope": scope.value,
                        "status": status.value,
                    },
                )
            )
            await uow.commit()
            return await self.builder.detail_for(
                uow, reading_list, viewer=actor, locale=locale
            )
