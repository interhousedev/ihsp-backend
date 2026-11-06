"""MCP A2, A4, A6: content tools act for the caller, link, refuse foreign ids."""

from typing import Any
from uuid import UUID

from app.interfaces.mcp.constants import SCOPES_BY_SERVER
from app.shared.ids import new_id
from tests.mcp.conftest import World
from tests.mcp.helpers import call, data_of, text_of

import pytest

ALL = SCOPES_BY_SERVER["student"]
QUESTION = {
    "type": "single",
    "prompt": "2 + 2?",
    "options": [{"id": "x", "text": "4"}, {"id": "y", "text": "5"}],
    "correct": ["x"],
    "explanation": "Sum.",
}


def _set(world: World, owner: UUID) -> UUID:
    set_id = new_id()
    world.flashcards.sets[set_id] = {"id": set_id, "title": "S", "card_count": 0}
    world.flashcards.owners[set_id] = owner
    world.content_tools.sets[set_id] = owner
    return set_id


async def test_batch_edit_needs_the_delete_scope_only_for_deletes(world: World) -> None:
    """MCP A2: deletes without flashcards:delete fail before any change."""
    token, actor = world.connector_token("student", "flashcards:write")
    set_id = _set(world, actor.user_id)
    edit = {"id": str(new_id()), "front": "new"}

    async with world.session("student", token) as session:
        refused = await call(
            session,
            "batch_edit_flashcards",
            set_id=str(set_id),
            update=[edit],
            delete_ids=[str(new_id())],
        )
        allowed = await call(
            session, "batch_edit_flashcards", set_id=str(set_id), update=[edit]
        )

    assert refused.isError
    assert "flashcards:delete" in text_of(refused) or "scope" in text_of(refused)
    assert [name for name, _ in world.content_tools.calls] == ["batch_edit_cards"]
    links = data_of(allowed)["links"]
    assert str(set_id) in links["open"] and "study" in links["study"]


async def test_batch_with_the_delete_scope_passes_ids_and_is_bounded(
    world: World,
) -> None:
    """MCP A2: both scopes allow deletes; more than 100 operations do not run."""
    token, actor = world.connector_token(
        "student", "flashcards:write", "flashcards:delete"
    )
    set_id = _set(world, actor.user_id)
    gone = new_id()
    cards = [{"front": "f", "back": "b"}] * 101

    async with world.session("student", token) as session:
        ok = await call(
            session, "batch_edit_flashcards", set_id=str(set_id), delete_ids=[str(gone)]
        )
        too_many = await call(
            session, "batch_edit_flashcards", set_id=str(set_id), add=cards
        )
        nothing = await call(session, "batch_edit_flashcards", set_id=str(set_id))

    data_of(ok)
    assert too_many.isError and nothing.isError
    [(_, recorded)] = world.content_tools.calls
    assert recorded["delete_ids"] == [gone]


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("batch_edit_flashcards", {"add": [{"front": "f", "back": "b"}]}),
        ("delete_flashcards", {"card_ids": [str(UUID(int=1))]}),
    ],
)
async def test_someone_elses_set_is_not_found(
    world: World, tool: str, arguments: dict[str, Any]
) -> None:
    """Rule 2: a foreign set is refused like a missing one, by every card tool."""
    token, _ = world.connector_token("student", *ALL)
    theirs = _set(world, new_id())

    async with world.session("student", token) as session:
        foreign = await call(session, tool, set_id=str(theirs), **arguments)
        missing = await call(session, tool, set_id=str(new_id()), **arguments)

    assert foreign.isError
    assert text_of(foreign) == text_of(missing)
    assert world.content_tools.calls == []


async def test_add_flashcards_treats_a_foreign_set_as_missing(world: World) -> None:
    """Rule 2: no "belongs to another user" answer that confirms an id exists."""
    token, _ = world.connector_token("student", *ALL)
    theirs = _set(world, new_id())
    cards = [{"front": "f", "back": "b"}]

    async with world.session("student", token) as session:
        foreign = await call(session, "add_flashcards", set_id=str(theirs), cards=cards)
        missing = await call(
            session, "add_flashcards", set_id=str(new_id()), cards=cards
        )

    assert text_of(foreign) == text_of(missing)


async def test_settings_go_to_the_owner_and_need_a_value(world: World) -> None:
    """MCP A2: shuffle and daily counts; out of range is refused by the schema."""
    token, actor = world.connector_token("student", *ALL)
    set_id = _set(world, actor.user_id)

    async with world.session("student", token) as session:
        ok = await call(
            session,
            "update_flashcard_set",
            set_id=str(set_id),
            shuffle=True,
            new_per_day=5,
        )
        empty = await call(session, "update_flashcard_set", set_id=str(set_id))
        over = await call(
            session, "update_flashcard_set", set_id=str(set_id), new_per_day=201
        )

    assert "open" in data_of(ok)["links"]
    assert world.flashcards.settings == [
        (actor.user_id, set_id, True, 5, None),
    ]
    assert empty.isError and over.isError


async def test_flash_card_results_carry_links(world: World) -> None:
    """A4: list, get, create and add return our links, none from content."""
    token, actor = world.connector_token("student", *ALL)
    set_id = _set(world, actor.user_id)
    cards = [{"front": "f", "back": "b"}]

    async with world.session("student", token) as session:
        listed = await call(session, "list_flashcard_sets")
        got = await call(session, "get_flashcard_set", set_id=str(set_id))
        made = await call(session, "create_flashcard_set", title="T", cards=cards)
        added = await call(session, "add_flashcards", set_id=str(set_id), cards=cards)

    urls = world.settings.urls.sp
    for row in (
        data_of(listed)["sets"][0],
        data_of(got),
        data_of(made),
        data_of(added),
    ):
        assert row["links"]["open"].startswith(urls)


async def test_tests_create_read_edit_with_links(world: World) -> None:
    """MCP A2 (D1): a test goes through the backend and links to its notebook."""
    token, actor = world.connector_token("student", *ALL)

    async with world.session("student", token) as session:
        made = data_of(
            await call(session, "create_test", title="T", questions=[QUESTION])
        )
        listed = data_of(await call(session, "list_tests"))
        got = data_of(await call(session, "get_test", test_id=made["id"]))
        edited = await call(
            session,
            "batch_edit_test_questions",
            test_id=made["id"],
            update=[{"id": "q1", "prompt": "New?"}],
            delete_ids=["q2"],
        )
        empty = await call(session, "batch_edit_test_questions", test_id=made["id"])

    assert f"artifact={made['id']}" in made["links"]["open"]
    assert listed["tests"][0]["links"] == made["links"]
    assert got["questions"][0]["correct"] == ["x"]
    data_of(edited)
    assert empty.isError
    [(_, recorded)] = world.content_tools.calls
    assert recorded["update"] == [{"id": "q1", "prompt": "New?"}]
    assert recorded["delete_ids"] == ["q2"]
    assert actor.user_id == world.content_tools.tests[UUID(made["id"])]["owner"]


async def test_another_students_test_is_not_found(world: World) -> None:
    """Rule 2: same answer as a missing test, for read and write."""
    owner_token, _ = world.connector_token("student", *ALL)
    token, _ = world.connector_token("student", *ALL)
    async with world.session("student", owner_token) as session:
        made = data_of(
            await call(session, "create_test", title="T", questions=[QUESTION])
        )

    async with world.session("student", token) as session:
        foreign = await call(session, "get_test", test_id=made["id"])
        missing = await call(session, "get_test", test_id=str(new_id()))
        write = await call(
            session, "batch_edit_test_questions", test_id=made["id"], delete_ids=["q1"]
        )

    assert foreign.isError and write.isError
    assert text_of(foreign) == text_of(missing)
    assert world.content_tools.calls == []


async def test_knowledge_audience_comes_from_the_server(world: World) -> None:
    """A6: the client cannot name an audience; staff entries stay out of the answer."""
    token, _ = world.connector_token("student", "knowledge:read")
    world.content_tools.knowledge = {
        "student": [{"key": "k", "title": "T", "value": "v​", "tags": [], "score": 1}],
        "staff": [{"key": "staff-only", "title": "S", "value": "s", "tags": []}],
    }

    async with world.session("student", token) as session:
        listed = await session.list_tools()
        result = await call(session, "search_knowledge", query="rules")

    [tool] = [t for t in listed.tools if t.name == "search_knowledge"]
    assert "audience" not in tool.inputSchema["properties"]
    data = data_of(result)
    assert [hit["key"] for hit in data["hits"]] == ["k"]
    assert data["hits"][0]["value"] == "v"
    assert "hits[].value" in data["untrusted_fields"]
    assert world.content_tools.calls[0][1]["audience"] == "student"


async def test_notebook_tools_use_the_actor_and_label_third_party_text(
    world: World,
) -> None:
    """A4, D9: results link to the notebook; source text is cleaned and labelled."""
    token, actor = world.connector_token("student", *ALL)
    notebook_id = new_id()
    world.content_tools.notebooks[notebook_id] = actor.user_id
    nid = str(notebook_id)

    async with world.session("student", token) as session:
        listed = data_of(await call(session, "list_notebooks"))
        got = data_of(await call(session, "get_notebook", notebook_id=nid))
        found = data_of(
            await call(session, "search_notebooks", query="xy", notebook_id=nid)
        )
        page = data_of(
            await call(
                session,
                "read_notebook_source",
                notebook_id=nid,
                source_id=str(new_id()),
            )
        )
        outputs = data_of(await call(session, "list_notebook_outputs", notebook_id=nid))
        made = data_of(await call(session, "create_notebook", title="New"))
        added = data_of(
            await call(
                session,
                "add_notebook_sources",
                notebook_id=nid,
                texts=[{"title": "t", "text": "body"}],
            )
        )
        output = data_of(
            await call(
                session,
                "generate_notebook_output",
                notebook_id=nid,
                kind="quiz",
                options={"count": 5},
            )
        )

    assert nid in listed["notebooks"][0]["links"]["open"]
    for result in (got, page, outputs, added, output):
        assert nid in result["links"]["open"]
    assert made["links"]["open"].startswith(world.settings.urls.sp)
    assert found["passages"][0]["text"] == "passage"
    assert "text" in page["untrusted_fields"]
    assert output["status"] == "queued"


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("get_notebook", {}),
        ("search_notebooks", {"query": "xy"}),
        ("read_notebook_source", {"source_id": str(UUID(int=2))}),
        ("list_notebook_outputs", {}),
        ("add_notebook_sources", {"texts": [{"title": "t", "text": "b"}]}),
        ("generate_notebook_output", {"kind": "quiz"}),
    ],
)
async def test_a_notebook_of_someone_else_is_not_found(
    world: World, tool: str, arguments: dict[str, Any]
) -> None:
    """Rule 2: every notebook tool refuses a foreign id."""
    token, _ = world.connector_token("student", *ALL)
    theirs = new_id()
    world.content_tools.notebooks[theirs] = new_id()

    async with world.session("student", token) as session:
        result = await call(session, tool, notebook_id=str(theirs), **arguments)

    assert result.isError
    assert world.content_tools.calls == []


async def test_add_sources_takes_no_url_and_needs_something(world: World) -> None:
    """Security: no tool follows a URL it is given."""
    token, actor = world.connector_token("student", *ALL)
    notebook_id = new_id()
    world.content_tools.notebooks[notebook_id] = actor.user_id

    async with world.session("student", token) as session:
        listed = await session.list_tools()
        empty = await call(
            session, "add_notebook_sources", notebook_id=str(notebook_id)
        )

    [tool] = [t for t in listed.tools if t.name == "add_notebook_sources"]
    assert set(tool.inputSchema["properties"]) == {"notebook_id", "file_ids", "texts"}
    assert empty.isError


async def test_course_kinds_are_not_offered_to_students(world: World) -> None:
    """D9: only personal Studio kinds; a course kind fails the schema."""
    token, actor = world.connector_token("student", *ALL)
    notebook_id = new_id()
    world.content_tools.notebooks[notebook_id] = actor.user_id

    async with world.session("student", token) as session:
        result = await call(
            session,
            "generate_notebook_output",
            notebook_id=str(notebook_id),
            kind="course_plan",
        )

    assert result.isError
    assert world.content_tools.calls == []


async def test_library_tools_link_and_label(world: World) -> None:
    """A4: library results link to the library and label their text."""
    token, _ = world.connector_token("student", "library:read")
    item_id = new_id()
    world.content_tools.items[item_id] = {
        "id": item_id,
        "title": "Book​",
        "author_label": "A",
    }

    async with world.session("student", token) as session:
        found = data_of(await call(session, "search_library", query="book"))
        got = data_of(await call(session, "get_library_item", item_id=str(item_id)))
        text = data_of(await call(session, "read_library_text", item_id=str(item_id)))
        missing = await call(session, "get_library_item", item_id=str(new_id()))

    assert str(item_id) in found["items"][0]["links"]["open"]
    assert found["items"][0]["title"] == "Book"
    assert got["links"] == text["links"]
    assert "text" in text["untrusted_fields"]
    assert missing.isError
