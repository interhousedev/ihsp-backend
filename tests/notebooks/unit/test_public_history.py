"""NotebooksQueries.chat_page and notes_page: an owner's history, page by page (MCP)."""

from uuid import uuid4

from app.modules.notebooks.application.notebook_titles import NotebookTitles
from app.modules.notebooks.application.public_api import NotebooksQueriesImpl
from app.modules.notebooks.domain.enums import MessageRole, SourceKind
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_core import NotebooksCore
from app.shared.actor import Actor
from tests.factories.notebooks import make_message, make_notebook, make_source

import pytest


@pytest.fixture
def queries(
    uow_factory: UowFactory, core: NotebooksCore, titles: NotebookTitles
) -> NotebooksQueriesImpl:
    """The public queries over the SQL unit of work."""
    return NotebooksQueriesImpl(uow_factory, core.quota, titles)


async def test_chat_page_pages_the_owners_thread(
    uow_factory: UowFactory, queries: NotebooksQueriesImpl, student: Actor
) -> None:
    """Messages come oldest first; `next_after_seq` is set until the end."""
    notebook = await make_notebook(uow_factory, student.user_id, title="Cells")
    for number in range(1, 4):
        await make_message(
            uow_factory,
            notebook,
            role=MessageRole.USER if number % 2 else MessageRole.ASSISTANT,
            text=f"m{number}",
        )

    first = await queries.chat_page(student.user_id, notebook.id, after_seq=0, limit=2)
    assert first is not None
    assert [(m["seq"], m["role"], m["text"]) for m in first["messages"]] == [
        (1, "user", "m1"),
        (2, "assistant", "m2"),
    ]
    assert first["next_after_seq"] == 2
    assert first["title"] == "Cells"

    rest = await queries.chat_page(student.user_id, notebook.id, after_seq=2, limit=2)
    assert rest is not None
    assert [m["text"] for m in rest["messages"]] == ["m3"]
    assert rest["next_after_seq"] is None


async def test_empty_thread_is_fine(
    uow_factory: UowFactory, queries: NotebooksQueriesImpl, student: Actor
) -> None:
    """A notebook nobody chatted in gives an empty page."""
    notebook = await make_notebook(uow_factory, student.user_id)

    page = await queries.chat_page(student.user_id, notebook.id, after_seq=0, limit=5)

    assert page is not None
    assert page["messages"] == []
    assert page["next_after_seq"] is None


async def test_notes_page_lists_only_note_sources_in_pages(
    uow_factory: UowFactory, queries: NotebooksQueriesImpl, student: Actor
) -> None:
    """Notes are the `note` sources with their text; the offset pages them."""
    notebook = await make_notebook(uow_factory, student.user_id)
    await make_source(uow_factory, notebook, kind=SourceKind.TEXT, title="Pasted")
    for number in range(1, 4):
        await make_source(
            uow_factory,
            notebook,
            kind=SourceKind.NOTE,
            title=f"Note {number}",
            texts=(f"body {number}",),
            body_md=f"body {number}",
            position=number + 1,
        )

    first = await queries.notes_page(student.user_id, notebook.id, offset=0, limit=2)
    assert first is not None
    assert [n["title"] for n in first["notes"]] == ["Note 1", "Note 2"]
    assert first["notes"][0]["text"] == "body 1"
    assert first["next_offset"] == 2

    rest = await queries.notes_page(student.user_id, notebook.id, offset=2, limit=2)
    assert rest is not None
    assert [n["title"] for n in rest["notes"]] == ["Note 3"]
    assert rest["next_offset"] is None


async def test_foreign_and_unknown_notebooks_are_not_found(
    uow_factory: UowFactory,
    queries: NotebooksQueriesImpl,
    student: Actor,
    other_student: Actor,
) -> None:
    """Another user's notebook answers None, like an id that does not exist."""
    notebook = await make_notebook(uow_factory, other_student.user_id)
    await make_message(uow_factory, notebook, text="private")

    assert (
        await queries.chat_page(student.user_id, notebook.id, after_seq=0, limit=5)
    ) is None
    assert (
        await queries.notes_page(student.user_id, notebook.id, offset=0, limit=5)
    ) is None
    assert (
        await queries.chat_page(student.user_id, uuid4(), after_seq=0, limit=5)
    ) is None
