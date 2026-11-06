"""McpContentTools over flash cards, notebooks, library and knowledge."""

from collections.abc import Sequence
from dataclasses import asdict
from typing import TYPE_CHECKING, Any, Final, cast
from uuid import UUID

from app.interfaces.mcp.errors import McpFileNoTextError, McpNotFoundError
from app.modules.flashcards.application.batch_edit_cards import CardChange
from app.modules.library.application.catalogue.list_items import ListItemsQuery
from app.modules.library.domain.enums import ItemKind
from app.shared.actor import Actor
from app.shared.contracts.library import (
    LibraryFileRef,
    LibraryItemRef,
    LibrarySourceUnavailableError,
)
from app.shared.contracts.mcp_content import McpContentTools
from app.shared.contracts.school_knowledge import Audience

if TYPE_CHECKING:
    from app.bootstrap.container import Container

TEXT_PAGE_CHARS: Final = 8000
SEARCHED_NOTEBOOKS: Final = 5
NOTEBOOK_LIST: Final = 50


def page_of_text(text: str, page: int) -> dict[str, Any]:
    """One bounded page; past the end gives empty text and the real page count."""
    pages = max(1, (len(text) + TEXT_PAGE_CHARS - 1) // TEXT_PAGE_CHARS)
    start = (page - 1) * TEXT_PAGE_CHARS
    return {"page": page, "pages": pages, "text": text[start : start + TEXT_PAGE_CHARS]}


def readable_file(ref: LibraryItemRef) -> LibraryFileRef | None:
    """The file to read: the primary one with text, else any with text."""
    ready = [file for file in ref.files if file.text_status == "ready"]
    return next((f for f in ready if f.is_primary), ready[0] if ready else None)


class McpContentAdapter:
    """Every call goes through a use case that checks the actor itself."""

    def __init__(self, container: "Container") -> None:
        """Keep the container; the modules are read when a tool runs."""
        self.container = container

    async def batch_edit_cards(
        self,
        user_id: UUID,
        set_id: UUID,
        *,
        add: Sequence[dict[str, Any]],
        update: Sequence[dict[str, Any]],
        delete_ids: Sequence[UUID],
    ) -> dict[str, Any]:
        """Apply the batch, then answer with the set like `get_set`."""
        flashcards = self.container.flashcards
        await flashcards.batch_edit_cards.execute(
            owner_id=user_id,
            set_id=set_id,
            add=[(card["front"], card["back"]) for card in add],
            update=[
                CardChange(
                    card_id=change["id"],
                    front=change.get("front"),
                    back=change.get("back"),
                )
                for change in update
            ],
            delete_ids=delete_ids,
        )
        found = await flashcards.public.get_set(set_id, user_id)
        if found is None:
            raise McpNotFoundError()
        return found

    async def list_tests(self, user_id: UUID, *, limit: int) -> list[dict[str, Any]]:
        """Quiz artifacts this user owns."""
        return await self.container.notebooks.author_quiz.list_tests(
            user_id, limit=limit
        )

    async def get_test(self, user_id: UUID, test_id: UUID) -> dict[str, Any]:
        """The owner's quiz with its answers."""
        return await self.container.notebooks.author_quiz.get_test(user_id, test_id)

    async def create_test(
        self,
        actor: Actor,
        *,
        notebook_id: UUID | None,
        title: str,
        questions: Sequence[dict[str, Any]],
    ) -> dict[str, Any]:
        """Create a quiz from given questions."""
        return await self.container.notebooks.author_quiz.create_test(
            actor, notebook_id=notebook_id, title=title, questions=questions
        )

    async def batch_edit_test_questions(
        self,
        user_id: UUID,
        test_id: UUID,
        *,
        add: Sequence[dict[str, Any]],
        update: Sequence[dict[str, Any]],
        delete_ids: Sequence[str],
    ) -> dict[str, Any]:
        """Apply all question changes in one transaction."""
        return await self.container.notebooks.author_quiz.edit_questions(
            user_id, test_id, add=add, update=update, delete_ids=delete_ids
        )

    async def search_knowledge(
        self, query: str, *, audience: str, limit: int
    ) -> list[dict[str, Any]]:
        """Knowledge hits for the audience."""
        hits = await self.container.knowledge.public.search(
            query, limit=limit, audience=cast(Audience, audience)
        )
        return [asdict(hit) for hit in hits]

    async def list_notebooks(self, actor: Actor) -> list[dict[str, Any]]:
        """The actor's listed notebooks."""
        return await self.container.notebooks.public.list_notebooks(
            actor.user_id, NOTEBOOK_LIST
        )

    async def get_notebook(self, actor: Actor, notebook_id: UUID) -> dict[str, Any]:
        """One readable notebook with its sources and outputs."""
        queries = self.container.notebooks.public
        found = await queries.get_notebook(actor.user_id, notebook_id)
        if found is None:
            raise McpNotFoundError()
        outputs = await queries.list_artifacts(actor.user_id, notebook_id)
        return {**found, "outputs": outputs}

    async def search_notebooks(
        self, actor: Actor, query: str, *, notebook_id: UUID | None, limit: int
    ) -> list[dict[str, Any]]:
        """Passages from one notebook, or the most recently opened ones."""
        queries = self.container.notebooks.public
        if notebook_id is not None:
            await self.get_notebook(actor, notebook_id)  # not found, not an empty list
            targets = [notebook_id]
        else:
            rows = await queries.list_notebooks(actor.user_id, SEARCHED_NOTEBOOKS)
            targets = [UUID(row["id"]) for row in rows]
        passages: list[dict[str, Any]] = []
        for target in targets:
            found = await queries.search(actor.user_id, target, query, limit)
            passages += [{**row, "notebook_id": str(target)} for row in found]
        return passages[:limit]

    async def read_notebook_source(
        self, actor: Actor, notebook_id: UUID, source_id: UUID, *, page: int
    ) -> dict[str, Any]:
        """One bounded page of a source's text."""
        return await self.container.notebooks.public.read_source_page(
            actor.user_id, notebook_id, source_id, page
        )

    async def list_notebook_outputs(
        self, actor: Actor, notebook_id: UUID
    ) -> list[dict[str, Any]]:
        """Studio artifacts of a readable notebook."""
        await self.get_notebook(actor, notebook_id)
        return await self.container.notebooks.public.list_artifacts(
            actor.user_id, notebook_id
        )

    async def create_notebook(self, actor: Actor, title: str) -> dict[str, Any]:
        """Create a personal notebook."""
        return await self.container.notebooks.commands.create_notebook(actor, title, [])

    async def add_notebook_sources(
        self,
        actor: Actor,
        notebook_id: UUID,
        *,
        file_ids: Sequence[UUID],
        texts: Sequence[dict[str, Any]],
    ) -> dict[str, Any]:
        """Add sources from the user's files and given text; no URL."""
        sources: list[dict[str, Any]] = [
            {"kind": "file", "file_id": file_id} for file_id in file_ids
        ]
        sources += [
            {"kind": "text", "title": item["title"], "text": item["text"]}
            for item in texts
        ]
        created = await self.container.notebooks.commands.add_sources(
            actor, notebook_id, sources
        )
        return {"notebook_id": str(notebook_id), "sources": created}

    async def generate_notebook_output(
        self,
        actor: Actor,
        notebook_id: UUID,
        *,
        kind: str,
        options: dict[str, Any],
        focus: str | None,
    ) -> dict[str, Any]:
        """Request an artifact under the normal budget."""
        return await self.container.notebooks.commands.request_artifact(
            actor, notebook_id, kind, options, focus
        )

    async def search_library(
        self, actor: Actor, query: str, *, limit: int
    ) -> list[dict[str, Any]]:
        """Visible items; UniLibrary records are dropped whatever the search returns."""
        page = await self.container.library.catalogue.list_items.execute(
            actor, ListItemsQuery(q=query, limit=limit * 2)
        )
        hosted = [card for card in page.items if card.kind is not ItemKind.EXTERNAL]
        return [
            {
                "id": card.id,
                "kind": card.kind.value,
                "title": card.title,
                "author_label": card.author_label,
                "language": card.language,
                "year_published": card.year_published,
                "has_text": card.has_text,
                "page_count": card.page_count,
                "snippet": card.snippet,
                "snippet_page": card.snippet_page,
            }
            for card in hosted[:limit]
        ]

    async def get_library_item(self, actor: Actor, item_id: UUID) -> dict[str, Any]:
        """A visible library item."""
        return asdict(await self._describe(actor, item_id))

    async def read_library_text(
        self, actor: Actor, item_id: UUID, *, page: int
    ) -> dict[str, Any]:
        """One bounded page of a visible item's text."""
        ref = await self._describe(actor, item_id)
        file = readable_file(ref)
        if file is None:
            raise McpFileNoTextError()
        reader = self.container.library.bridge.source_reader
        try:
            found = await reader.read_text(item_id, file.file_id, actor=actor)
        except LibrarySourceUnavailableError as error:
            raise _library_error(error) from error
        return {"id": item_id, "title": ref.title, **page_of_text(found.text, page)}

    async def _describe(self, actor: Actor, item_id: UUID) -> LibraryItemRef:
        reader = self.container.library.bridge.source_reader
        try:
            return await reader.describe(item_id, actor)
        except LibrarySourceUnavailableError as error:
            raise _library_error(error) from error


def _library_error(error: LibrarySourceUnavailableError) -> Exception:
    """No text is a fact of the file; anything else looks like a missing item."""
    return McpFileNoTextError() if error.reason == "no_text" else McpNotFoundError()


def build_content_tools(container: "Container") -> McpContentTools:
    """Build the backend of the content tools."""
    return McpContentAdapter(container)
