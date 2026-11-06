"""MCP library and notebooks: the adapter over the modules' public APIs."""

from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

from app.bootstrap.adapters.mcp_content import McpContentAdapter, page_of_text
from app.bootstrap.container import Container
from app.interfaces.mcp.errors import McpFileNoTextError, McpNotFoundError
from app.modules.flashcards.wiring import FlashcardsServices
from app.modules.knowledge.wiring import KnowledgeServices
from app.modules.library.domain.enums import ItemKind
from app.modules.library.wiring import LibraryServices
from app.modules.library.wiring_bridge import BridgeServices
from app.modules.library.wiring_catalogue import CatalogueServices
from app.modules.notebooks.wiring import NotebooksServices
from app.shared.actor import Actor, Role
from app.shared.contracts.library import (
    LibraryFileRef,
    LibraryItemRef,
    LibrarySourceUnavailableError,
    LibraryText,
    UnavailableReason,
)
from app.shared.ids import new_id

import pytest

ACTOR = Actor(user_id=new_id(), roles=frozenset({Role.STUDENT}))
FILE_ID = new_id()


def _card(kind: ItemKind, title: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=new_id(),
        kind=kind,
        title=title,
        author_label="A",
        language="en",
        year_published=None,
        has_text=True,
        page_count=1,
        snippet=None,
        snippet_page=None,
    )


class FakeReader:
    def __init__(self, *, refuse: UnavailableReason | None = None) -> None:
        self.refuse = refuse
        self.text = "x" * 8001
        self.status = "ready"

    async def describe(self, item_id: UUID, actor: Actor) -> LibraryItemRef:
        assert actor is ACTOR
        if self.refuse:
            raise LibrarySourceUnavailableError(self.refuse, item_id=item_id)
        file = LibraryFileRef(FILE_ID, "pdf", 1, self.status, True)
        return LibraryItemRef(item_id, "book", "T", "A", 1, (file,))

    async def read_text(
        self, item_id: UUID, file_id: UUID, *, actor: Actor
    ) -> LibraryText:
        return LibraryText(item_id, file_id, "T", 1, 1, self.text, (0,))


def _adapter(**parts: Any) -> McpContentAdapter:
    return McpContentAdapter(cast(Container, SimpleNamespace(**parts)))


def _library(reader: FakeReader, *cards: SimpleNamespace) -> SimpleNamespace:
    async def execute(actor: Actor, query: Any) -> SimpleNamespace:
        assert actor is ACTOR
        return SimpleNamespace(items=list(cards))

    return SimpleNamespace(
        bridge=SimpleNamespace(source_reader=reader),
        catalogue=SimpleNamespace(list_items=SimpleNamespace(execute=execute)),
    )


async def test_search_never_returns_a_unilibrary_record() -> None:
    """Library: the external source stays out of every MCP answer."""
    library = _library(
        FakeReader(), _card(ItemKind.EXTERNAL, "Ext"), _card(ItemKind.BOOK, "Book")
    )

    rows = await _adapter(library=library).search_library(ACTOR, "q", limit=5)

    assert [row["title"] for row in rows] == ["Book"]


@pytest.mark.parametrize("reason", ["not_found", "unavailable", "not_supported"])
async def test_an_unusable_item_looks_like_a_missing_one(
    reason: UnavailableReason,
) -> None:
    """Rule 2: held, unpublished and external items are simply not found."""
    adapter = _adapter(library=_library(FakeReader(refuse=reason)))

    with pytest.raises(McpNotFoundError):
        await adapter.get_library_item(ACTOR, new_id())
    with pytest.raises(McpNotFoundError):
        await adapter.read_library_text(ACTOR, new_id(), page=1)


async def test_library_text_is_paged_and_a_scan_has_no_text() -> None:
    """Rule 4: 8 KB pages; a file without text is said plainly."""
    reader = FakeReader()
    adapter = _adapter(library=_library(reader))

    first = await adapter.read_library_text(ACTOR, new_id(), page=1)
    second = await adapter.read_library_text(ACTOR, new_id(), page=2)
    reader.status = "no_text"

    assert (first["pages"], len(first["text"]), len(second["text"])) == (2, 8000, 1)
    with pytest.raises(McpFileNoTextError):
        await adapter.read_library_text(ACTOR, new_id(), page=1)


def test_the_adapter_reads_services_the_modules_really_have() -> None:
    """Wiring: the names the adapter walks exist on the real services."""
    for owner, name in (
        (FlashcardsServices, "batch_edit_cards"),
        (FlashcardsServices, "public"),
        (NotebooksServices, "author_quiz"),
        (NotebooksServices, "public"),
        (NotebooksServices, "commands"),
        (KnowledgeServices, "public"),
        (LibraryServices, "catalogue"),
        (LibraryServices, "bridge"),
        (CatalogueServices, "list_items"),
        (BridgeServices, "source_reader"),
    ):
        assert name in owner.__dataclass_fields__, name


def test_a_page_past_the_end_is_empty() -> None:
    """Rule 4: paging never fails."""
    assert page_of_text("abc", 9) == {"page": 9, "pages": 1, "text": ""}


async def test_a_notebook_the_queries_do_not_open_is_not_found() -> None:
    """Sharing: `load_notebook` is closed to recipients, so a shared id is missing."""

    class Queries:
        async def get_notebook(self, user_id: UUID, notebook_id: UUID) -> None:
            return None

        async def search(self, *args: Any) -> list[dict[str, Any]]:
            raise AssertionError("no search on a closed notebook")

    adapter = _adapter(notebooks=SimpleNamespace(public=Queries()))

    with pytest.raises(McpNotFoundError):
        await adapter.get_notebook(ACTOR, new_id())
    with pytest.raises(McpNotFoundError):
        await adapter.search_notebooks(ACTOR, "q", notebook_id=new_id(), limit=3)
    with pytest.raises(McpNotFoundError):
        await adapter.list_notebook_outputs(ACTOR, new_id())
