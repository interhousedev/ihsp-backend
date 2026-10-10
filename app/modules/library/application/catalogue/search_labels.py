"""Suggestions while a user types an author or a tag (any signed-in user)."""

from dataclasses import dataclass

from app.modules.library.domain.catalogue_labels import AUTHOR_SUGGESTIONS
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor

MAX_QUERY = 100


@dataclass(frozen=True, slots=True)
class TagSuggestionView:
    """A tag with the number of published items that carry it."""

    name: str
    item_count: int


class SearchAuthors:
    """`GET /v1/library/authors?q=`: fuzzy, Latin and Cyrillic alike."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the unit of work factory."""
        self.uow_factory = uow_factory

    async def execute(self, actor: Actor, text: str) -> list[str]:
        """Names of the existing authors that match what was typed, best first."""
        del actor
        async with self.uow_factory() as uow:
            found = await uow.labels.search_authors(
                text[:MAX_QUERY], limit=AUTHOR_SUGGESTIONS
            )
        return [author.name for author in found]


class SearchTags:
    """`GET /v1/library/tags?q=`: the tags that match, or the most used ones."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the unit of work factory."""
        self.uow_factory = uow_factory

    async def execute(
        self, actor: Actor | None, text: str, *, limit: int = AUTHOR_SUGGESTIONS
    ) -> list[TagSuggestionView]:
        """Existing tags that match what was typed (all by use when it is empty)."""
        del actor
        async with self.uow_factory() as uow:
            found = await uow.labels.search_tags(text[:MAX_QUERY], limit=limit)
        return [TagSuggestionView(f.tag.name, f.item_count) for f in found]
