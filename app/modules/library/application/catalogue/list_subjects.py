"""Subjects that have library items, with counts (GET /library/subjects)."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.library.application.catalogue.common import anonymous_cards
from app.modules.library.application.locale import resolve_locale
from app.modules.library.domain.catalogue_search import viewer_from_actor
from app.modules.library.ports.directories import AcademicDirectory
from app.modules.library.ports.unit_of_work import UowFactory
from app.settings import LibrarySettings
from app.shared.actor import Actor
from app.shared.contracts.identity import IdentityDirectory


@dataclass(frozen=True, slots=True)
class SubjectCountView:
    """`LibrarySubject` of the TypeScript contract."""

    id: UUID
    name: str
    item_count: int


class ListSubjects:
    """Subject shelves for the home page and the subject filters."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        academic: AcademicDirectory,
        identity: IdentityDirectory,
        settings: LibrarySettings,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.academic = academic
        self.identity = identity
        self.settings = settings

    async def execute(
        self,
        actor: Actor | None,
        *,
        include_empty: bool = False,
        accept_language: str | None = None,
    ) -> list[SubjectCountView]:
        """Subjects with at least one visible item, or all of them."""
        locale = await resolve_locale(self.identity, actor, accept_language)
        viewer = viewer_from_actor(
            actor, anonymous_cards=anonymous_cards(self.settings)
        )
        async with self.uow_factory() as uow:
            counts = await uow.items.subject_counts(viewer)
        subjects = await self.academic.list_subjects(locale)
        views = [SubjectCountView(s.id, s.name, counts.get(s.id, 0)) for s in subjects]
        return views if include_empty else [v for v in views if v.item_count > 0]
