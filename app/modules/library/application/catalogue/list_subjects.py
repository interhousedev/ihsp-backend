"""Subjects that have library items, with counts (GET /library/subjects)."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.library.application.cards import pick_name
from app.modules.library.application.catalogue.common import anonymous_cards
from app.modules.library.application.locale import resolve_locale
from app.modules.library.domain.catalogue_search import viewer_from_actor
from app.modules.library.domain.taxonomy_subjects import subject_descendants
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
    parent_id: UUID | None = None
    code: str | None = None


class ListSubjects:
    """Subject shelves for the home page and the subject filters."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        identity: IdentityDirectory,
        settings: LibrarySettings,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
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
            subjects = await uow.taxonomy.subjects(include_archived=False)
        views = [
            SubjectCountView(
                s.id,
                pick_name(s.name, locale),
                counts.get(s.id, 0)
                + sum(counts.get(d, 0) for d in subject_descendants(subjects, s.id)),
                s.parent_id,
                s.code,
            )
            for s in subjects
        ]
        return views if include_empty else [v for v in views if v.item_count > 0]
