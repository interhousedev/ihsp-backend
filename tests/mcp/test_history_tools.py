"""MCP history tools: the owner's chats and notebooks, listed and read page by page."""

from app.interfaces.mcp.constants import SCOPES_BY_SERVER
from app.shared.ids import new_id
from tests.mcp.conftest import World
from tests.mcp.helpers import call, data_of

import pytest

ALL = SCOPES_BY_SERVER["student"]


async def test_list_chats_pages_through_the_owners_chats(world: World) -> None:
    """Only the caller's chats are listed; the cursor continues the list."""
    token, actor = world.connector_token("student", *ALL)
    for title in ("a", "b", "c"):
        world.history_tools.add_chat(actor.user_id, title, [])
    world.history_tools.add_chat(new_id(), "theirs", [])

    async with world.session("student", token) as session:
        first = data_of(await call(session, "list_chats", limit=2))
        rest = data_of(
            await call(session, "list_chats", limit=2, cursor=first["next_cursor"])
        )

    assert [c["title"] for c in first["chats"]] == ["a", "b"]
    assert [c["title"] for c in rest["chats"]] == ["c"]
    assert rest["next_cursor"] is None


async def test_get_chat_pages_the_history_and_labels_the_text(world: World) -> None:
    """Messages come by seq; titles and texts are marked as third-party text."""
    token, actor = world.connector_token("student", *ALL)
    chat_id = world.history_tools.add_chat(actor.user_id, "T", ["m1", "m2", "m3"])

    async with world.session("student", token) as session:
        first = data_of(await call(session, "get_chat", chat_id=str(chat_id), limit=2))
        rest = data_of(
            await call(
                session,
                "get_chat",
                chat_id=str(chat_id),
                limit=2,
                after_seq=first["next_after_seq"],
            )
        )

    assert [m["seq"] for m in first["messages"]] == [1, 2]
    assert [m["text"] for m in rest["messages"]] == ["m3"]
    assert rest["next_after_seq"] is None


async def test_empty_histories_are_fine(world: World) -> None:
    """A chat or a notebook with nothing in it gives empty lists, not an error."""
    token, actor = world.connector_token("student", *ALL)
    chat_id = world.history_tools.add_chat(actor.user_id, "T", [])
    notebook_id = world.history_tools.add_notebook(actor.user_id, "N")

    async with world.session("student", token) as session:
        chat = data_of(await call(session, "get_chat", chat_id=str(chat_id)))
        thread = data_of(
            await call(session, "get_notebook_chat", notebook_id=str(notebook_id))
        )
        notes = data_of(
            await call(session, "get_notebook_notes", notebook_id=str(notebook_id))
        )
        nobody = data_of(await call(session, "list_chats"))

    assert chat["messages"] == []
    assert thread["messages"] == []
    assert notes["notes"] == []
    assert chat["next_after_seq"] is None
    assert nobody["chats"][0]["title"] == "T"


async def test_list_notebooks_is_paged_and_links_to_the_notebook(
    world: World,
) -> None:
    """Notebooks come with the cursor and a link each."""
    token, actor = world.connector_token("student", *ALL)
    ids = [world.history_tools.add_notebook(actor.user_id, t) for t in "xy"]

    async with world.session("student", token) as session:
        first = data_of(await call(session, "list_notebooks", limit=1))
        rest = data_of(
            await call(session, "list_notebooks", cursor=first["next_cursor"])
        )

    assert str(ids[0]) in first["notebooks"][0]["links"]["open"]
    assert [n["title"] for n in rest["notebooks"]] == ["y"]
    assert rest["next_cursor"] is None


async def test_notebook_chat_and_notes_are_paged(world: World) -> None:
    """The thread pages by seq, the notes by offset."""
    token, actor = world.connector_token("student", *ALL)
    notebook_id = world.history_tools.add_notebook(
        actor.user_id, "N", ["q1", "q2"], ["n1", "n2", "n3"]
    )
    nid = str(notebook_id)

    async with world.session("student", token) as session:
        thread = data_of(
            await call(session, "get_notebook_chat", notebook_id=nid, limit=1)
        )
        notes = data_of(
            await call(session, "get_notebook_notes", notebook_id=nid, limit=2)
        )
        more = data_of(
            await call(
                session,
                "get_notebook_notes",
                notebook_id=nid,
                limit=2,
                offset=notes["next_offset"],
            )
        )

    assert thread["next_after_seq"] == 1
    assert [n["text"] for n in notes["notes"]] == ["n1", "n2"]
    assert [n["text"] for n in more["notes"]] == ["n3"]
    assert more["next_offset"] is None


@pytest.mark.parametrize(
    ("tool", "key"),
    [
        ("get_chat", "chat_id"),
        ("get_notebook_chat", "notebook_id"),
        ("get_notebook_notes", "notebook_id"),
    ],
)
async def test_someone_elses_or_unknown_id_is_not_found(
    world: World, tool: str, key: str
) -> None:
    """Another user's object answers like one that does not exist."""
    token, _ = world.connector_token("student", *ALL)
    theirs = world.history_tools.add_chat(new_id(), "T", ["secret"])
    notebook = world.history_tools.add_notebook(new_id(), "N", ["secret"], ["n"])

    async with world.session("student", token) as session:
        foreign = await call(
            session, tool, **{key: str(theirs if key == "chat_id" else notebook)}
        )
        unknown = await call(session, tool, **{key: str(new_id())})

    assert foreign.isError
    assert unknown.isError
    assert foreign.content == unknown.content
