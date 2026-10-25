"""AI-1: searching the saved chats by title."""

from uuid import UUID

from app.modules.ai.application.views import ChatItemView
from app.modules.ai.domain.assistant import Assistant
from app.shared.actor import Actor
from app.shared.pagination import Page
from tests.ai.conftest import AiHarness


async def titled(
    h: AiHarness,
    title: str,
    *,
    actor: Actor | None = None,
    assistant: Assistant = Assistant.STUDENT,
) -> UUID:
    """Create a chat with this title; each one is a minute newer than the last."""
    h.clock.advance(minutes=1)
    chat = await h.new_chat(actor, assistant)
    await h.services.rename_chat.execute(
        actor=actor or (h.student if assistant is Assistant.STUDENT else h.admin),
        chat_id=chat.id,
        title=title,
    )
    chat_id: UUID = chat.id
    return chat_id


async def search(
    h: AiHarness,
    q: str | None,
    *,
    actor: Actor | None = None,
    assistant: Assistant = Assistant.STUDENT,
    cursor: str | None = None,
    limit: int = 20,
) -> Page[ChatItemView]:
    """Run the list use case."""
    return await h.services.list_chats.execute(
        actor=actor or h.student,
        assistant=assistant,
        cursor=cursor,
        limit=limit,
        q=q,
    )


async def test_search_matches_part_of_a_title_in_any_case(h: AiHarness) -> None:
    """AI-1: a case-insensitive substring of the title; newest first."""
    first = await titled(h, "Photosynthesis basics")
    await titled(h, "Algebra homework")
    third = await titled(h, "Trip to the PHOTO studio")

    page = await search(h, "photo")
    upper = await search(h, "ALGEBRA HOME")

    assert [c.id for c in page.items] == [third, first]
    assert [c.title for c in upper.items] == ["Algebra homework"]
    assert (await search(h, "geometry")).items == []


async def test_search_works_for_cyrillic_titles(h: AiHarness) -> None:
    """AI-1: Russian titles match whatever the letter case."""
    chat_id = await titled(h, "Помощь по Биологии")

    page = await search(h, "биолог")

    assert [c.id for c in page.items] == [chat_id]


async def test_wildcard_characters_in_the_query_are_plain_text(h: AiHarness) -> None:
    """AI-1: `%`, `_` and a backslash match themselves, not everything."""
    percent = await titled(h, "100% sure")
    await titled(h, "1000 sure")
    underscore = await titled(h, "snake_case")
    await titled(h, "snakexcase")
    slash = await titled(h, "C:\\temp")

    assert [c.id for c in (await search(h, "%")).items] == [percent]
    assert [c.id for c in (await search(h, "e_c")).items] == [underscore]
    assert [c.id for c in (await search(h, "\\")).items] == [slash]


async def test_search_only_sees_own_chats_of_that_assistant(h: AiHarness) -> None:
    """AI-1: other users, the other assistant and deleted chats stay out."""
    mine = await titled(h, "Report on cells")
    await titled(h, "Report of Bobur", actor=h.other_student)
    await titled(h, "Report for the office", actor=h.admin, assistant=Assistant.ADMIN)
    gone = await titled(h, "Old report")
    await h.services.delete_chat.execute(actor=h.student, chat_id=gone)

    student = await search(h, "report")
    admin = await search(h, "report", actor=h.admin, assistant=Assistant.ADMIN)

    assert [c.id for c in student.items] == [mine]
    assert [c.title for c in admin.items] == ["Report for the office"]


async def test_search_pages_with_the_cursor(h: AiHarness) -> None:
    """AI-1: the cursor of a filtered list continues the same filtered list."""
    wanted = [await titled(h, f"Biology {n}") for n in range(5)]
    await titled(h, "Chemistry")

    first = await search(h, "biology", limit=2)
    second = await search(h, "biology", limit=2, cursor=first.next_cursor)
    third = await search(h, "biology", limit=2, cursor=second.next_cursor)

    assert [c.id for c in first.items] == [wanted[4], wanted[3]]
    assert [c.id for c in second.items] == [wanted[2], wanted[1]]
    assert [c.id for c in third.items] == [wanted[0]]
    assert third.next_cursor is None


async def test_a_blank_query_is_no_filter(h: AiHarness) -> None:
    """AI-1: `q` of spaces lists everything, like no `q`."""
    await titled(h, "One")
    await titled(h, "Two")

    assert len((await search(h, "   ")).items) == 2
    assert len((await search(h, None)).items) == 2


async def test_spaces_in_the_query_are_collapsed(h: AiHarness) -> None:
    """AI-1: titles keep single spaces, so the query is matched the same way."""
    await titled(h, "Cell   division notes")

    page = await search(h, "  cell    division ")

    assert [c.title for c in page.items] == ["Cell division notes"]
