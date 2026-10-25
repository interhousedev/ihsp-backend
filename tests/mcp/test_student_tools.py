"""MCP-1, MCP-8, AI-5: the Students server reads and writes only the caller's data."""

from datetime import date
from uuid import UUID

from app.interfaces.mcp.constants import SCOPES_BY_SERVER
from tests.mcp.conftest import World
from tests.mcp.fakes import (
    LESSON_DATE,
    SUBJECT_ID,
    make_file,
    make_lesson,
    make_resource,
)
from tests.mcp.helpers import call, data_of, text_of

ALL = SCOPES_BY_SERVER["student"]


async def test_get_schedule_defaults_to_a_week_from_today(world: World) -> None:
    """MCP-8: lessons of the caller, local today + 6 days, without audience keys."""
    token, actor = world.connector_token("student", *ALL)
    lesson = make_lesson()
    world.schedule.lessons[lesson.id] = lesson
    world.schedule.audience.add((actor.user_id, lesson.id))

    async with world.session("student", token) as session:
        result = await call(session, "get_schedule")

    data = data_of(result)
    assert data["date_from"] == "2026-10-06"
    assert data["date_to"] == "2026-10-12"
    [row] = data["lessons"]
    assert row["id"] == str(lesson.id)
    assert row["date"] == LESSON_DATE.isoformat()
    assert row["subject_name"] == "Algebra"
    assert row["homework_text"] == "Exercises 1-5"
    assert "audience" not in row
    assert world.schedule.calls == [
        ("projected", (actor.user_id, date(2026, 10, 6), date(2026, 10, 12)))
    ]


async def test_get_schedule_does_not_show_other_students_lessons(world: World) -> None:
    """MCP-1: only the caller's own lessons."""
    token, _ = world.connector_token("student", *ALL)
    lesson = make_lesson()
    world.schedule.lessons[lesson.id] = lesson  # nobody's audience

    async with world.session("student", token) as session:
        result = await call(session, "get_schedule")

    assert data_of(result)["lessons"] == []


async def test_reversed_and_too_long_ranges_are_refused(world: World) -> None:
    """Dates are validated before any query runs."""
    token, _ = world.connector_token("student", *ALL)

    async with world.session("student", token) as session:
        reversed_range = await call(
            session, "get_schedule", date_from="2026-10-10", date_to="2026-10-01"
        )
        too_long = await call(
            session, "get_schedule", date_from="2026-01-01", date_to="2026-12-31"
        )

    assert reversed_range.isError
    assert "date_to is before date_from" in text_of(reversed_range)
    assert too_long.isError
    assert "at most 120 days" in text_of(too_long)
    assert world.schedule.calls == []


async def test_get_my_subjects_returns_the_standing(world: World) -> None:
    """MCP-8: subjects with marks, rating and absences."""
    token, actor = world.connector_token("student", *ALL)

    async with world.session("student", token) as session:
        result = await call(session, "get_my_subjects", semester=3)

    [subject] = data_of(result)["subjects"]
    assert subject["name"] == "Algebra"
    assert subject["semester_mark"] == 4.5
    assert subject["teacher_names"] == ["Aliev A."]
    assert world.marks.calls == [("subjects_summary", (actor.user_id, 3))]


async def test_get_subject_lessons_passes_the_filters(world: World) -> None:
    """MCP-8: lessons of one subject for the caller."""
    token, actor = world.connector_token("student", *ALL)
    world.classwork.lessons = [make_lesson()]

    async with world.session("student", token) as session:
        result = await call(
            session,
            "get_subject_lessons",
            subject_id=str(SUBJECT_ID),
            date_from="2026-09-01",
        )

    assert data_of(result)["lessons"][0]["topic"] == "Limits"
    assert world.classwork.calls == [
        ("subject_lessons", (actor.user_id, SUBJECT_ID, date(2026, 9, 1), None))
    ]


async def test_get_homework_returns_lesson_views_and_notes(world: World) -> None:
    """MCP-8: homework with done state and notes."""
    token, actor = world.connector_token("student", *ALL)
    world.classwork.homework_rows = [
        {"lesson": make_lesson(), "done_at": None, "note": "ask on Monday"}
    ]

    async with world.session("student", token) as session:
        result = await call(session, "get_homework", done=False)

    [row] = data_of(result)["homework"]
    assert row["note"] == "ask on Monday"
    assert row["lesson"]["homework_text"] == "Exercises 1-5"
    assert "audience" not in row["lesson"]
    assert world.classwork.calls == [("homework", (actor.user_id, None, None, False))]


async def test_get_marks_and_results(world: World) -> None:
    """MCP-8: marks and semester results of the caller."""
    token, actor = world.connector_token("student", *ALL)

    async with world.session("student", token) as session:
        marks = await call(session, "get_marks", subject_id=str(SUBJECT_ID))
        results = await call(session, "get_results", semester=3)

    [mark] = data_of(marks)["marks"]
    assert mark["value"] == 5
    assert mark["type"] == "lesson"
    assert data_of(results)["gpa"] == 4.6
    assert ("marks", (actor.user_id, SUBJECT_ID, None, None)) in world.marks.calls
    assert ("results", (actor.user_id, 3)) in world.marks.calls


async def test_get_attendance_lists_absences_with_lessons(world: World) -> None:
    """MCP-8 (new): own absences with their lessons."""
    token, _ = world.connector_token("student", *ALL)
    world.classwork.absence_rows = [{"lesson": make_lesson(), "excused": True}]

    async with world.session("student", token) as session:
        result = await call(session, "get_attendance")

    [row] = data_of(result)["absences"]
    assert row["excused"] is True
    assert row["lesson"]["subject_name"] == "Algebra"


async def test_lesson_materials_need_the_lesson_to_be_in_the_audience(
    world: World,
) -> None:
    """MCP-1: materials of other groups' lessons stay hidden."""
    token, actor = world.connector_token("student", *ALL)
    mine, other = make_lesson(), make_lesson()
    for lesson in (mine, other):
        world.schedule.lessons[lesson.id] = lesson
        world.links.resources[lesson.id] = [make_resource(lesson.id)]
    world.schedule.audience.add((actor.user_id, mine.id))

    async with world.session("student", token) as session:
        allowed = await call(session, "get_lesson_materials", lesson_id=str(mine.id))
        refused = await call(session, "get_lesson_materials", lesson_id=str(other.id))

    data = data_of(allowed)
    assert data["subject_name"] == "Algebra"
    [resource] = data["resources"]
    assert resource["title"] == "Lecture slides"
    assert resource["short_url"] == "https://s.ihsu.uz/abc"
    assert resource["role"] == "material"
    assert refused.isError


async def test_list_files_returns_own_files_without_their_text(world: World) -> None:
    """MCP-8: file ids, names and whether text can be read."""
    token, actor = world.connector_token("student", *ALL)
    mine = world.files.add(make_file(actor.user_id))
    world.files.add(make_file(UUID(int=99)))

    async with world.session("student", token) as session:
        result = await call(session, "list_files", limit=10)

    [row] = data_of(result)["files"]
    assert row["file_id"] == str(mine.id)
    assert row["has_text"] is True
    assert "text" not in row


async def test_read_file_pages_through_own_file(world: World) -> None:
    """MCP-8: read_file is paged."""
    token, actor = world.connector_token("student", *ALL)
    file = world.files.add(make_file(actor.user_id), pages=["one", "two"])

    async with world.session("student", token) as session:
        first = await call(session, "read_file", file_id=str(file.id))
        second = await call(session, "read_file", file_id=str(file.id), page=2)

    assert data_of(first)["text"] == "one"
    assert data_of(first)["pages"] == 2
    assert data_of(second)["text"] == "two"
    assert data_of(second)["page"] == 2


async def test_read_file_of_another_student_is_refused_and_audited(
    world: World,
) -> None:
    """UF-MCP-03: a file of someone else cannot be read, and the attempt is logged."""
    token, actor = world.connector_token("student", *ALL)
    file = world.files.add(make_file(UUID(int=99)))

    async with world.session("student", token) as session:
        result = await call(session, "read_file", file_id=str(file.id))

    assert result.isError
    assert "does not exist" in text_of(result)
    [event] = world.audit.of_type("mcp.denied")
    assert event.user_id == actor.user_id
    assert event.metadata is not None
    assert event.metadata["reason"] == "mcp/file-not-accessible"


async def test_read_file_of_a_lesson_in_the_audience_is_allowed(world: World) -> None:
    """AI-5: files attached to the student's lessons can be read with the lesson id."""
    token, actor = world.connector_token("student", *ALL)
    lesson = make_lesson()
    teacher_file = world.files.add(make_file(UUID(int=21)), pages=["slides"])
    world.links.resources[lesson.id] = [
        make_resource(lesson.id, kind="file", file_id=teacher_file.id)
    ]
    world.schedule.audience.add((actor.user_id, lesson.id))
    stranger = make_lesson()
    world.links.resources[stranger.id] = [
        make_resource(stranger.id, kind="file", file_id=teacher_file.id)
    ]

    async with world.session("student", token) as session:
        allowed = await call(
            session, "read_file", file_id=str(teacher_file.id), lesson_id=str(lesson.id)
        )
        wrong_lesson = await call(
            session,
            "read_file",
            file_id=str(teacher_file.id),
            lesson_id=str(stranger.id),
        )

    assert data_of(allowed)["text"] == "slides"
    assert wrong_lesson.isError


async def test_read_file_refuses_files_without_text_or_too_large(world: World) -> None:
    """AI-5, FILE-7: no text, or text over the assistant limit, is a clear error."""
    token, actor = world.connector_token("student", *ALL)
    no_text = world.files.add(make_file(actor.user_id, text_bytes=None))
    limit = world.settings.limits.ai_text_max_bytes
    huge = world.files.add(make_file(actor.user_id, text_bytes=limit + 1))
    processing = world.files.add(make_file(actor.user_id, status="processing"))

    async with world.session("student", token) as session:
        a = await call(session, "read_file", file_id=str(no_text.id))
        b = await call(session, "read_file", file_id=str(huge.id))
        c = await call(session, "read_file", file_id=str(processing.id))

    assert "no text" in text_of(a)
    assert f"{limit} bytes" in text_of(b)
    assert c.isError


async def test_search_files_searches_only_own_files(world: World) -> None:
    """MCP-8: the search runs for the caller's id."""
    token, actor = world.connector_token("student", *ALL)

    async with world.session("student", token) as session:
        result = await call(session, "search_files", query="limits", limit=5)

    assert data_of(result)["results"][0]["snippet"] == "limits"
    assert world.files.searches == [(actor.user_id, "limits", 5)]


async def test_flash_cards_list_and_get_are_limited_to_the_owner(world: World) -> None:
    """MCP-8: the caller sees only their sets."""
    token, actor = world.connector_token("student", *ALL)
    mine = await world.flashcards.create_set(
        actor.user_id, "Mine", [("a", "b")], source="manual"
    )
    theirs = await world.flashcards.create_set(
        UUID(int=99), "Theirs", [], source="manual"
    )

    async with world.session("student", token) as session:
        listed = await call(session, "list_flashcard_sets")
        got = await call(session, "get_flashcard_set", set_id=str(mine["id"]))
        refused = await call(session, "get_flashcard_set", set_id=str(theirs["id"]))

    assert [s["title"] for s in data_of(listed)["sets"]] == ["Mine"]
    assert data_of(got)["title"] == "Mine"
    assert refused.isError


async def test_create_flashcard_set_is_marked_as_made_via_mcp(world: World) -> None:
    """MCP-6, WEB-22: sets created by AI clients have source `mcp`."""
    token, actor = world.connector_token("student", *ALL)

    async with world.session("student", token) as session:
        result = await call(
            session,
            "create_flashcard_set",
            title="Derivatives",
            description="Week 3",
            cards=[
                {"front": "d/dx x^2", "back": "2x"},
                {"front": "d/dx c", "back": "0"},
            ],
        )

    assert data_of(result)["source"] == "mcp"
    [created] = world.flashcards.created
    assert created["owner_id"] == actor.user_id
    assert created["cards"] == [("d/dx x^2", "2x"), ("d/dx c", "0")]
    assert created["description"] == "Week 3"


async def test_create_flashcard_set_validates_the_cards(world: World) -> None:
    """Empty card lists and empty texts never reach the use case."""
    token, _ = world.connector_token("student", *ALL)

    async with world.session("student", token) as session:
        empty = await call(session, "create_flashcard_set", title="t", cards=[])
        blank = await call(
            session,
            "create_flashcard_set",
            title="t",
            cards=[{"front": "", "back": "x"}],
        )

    assert empty.isError
    assert blank.isError
    assert world.flashcards.created == []


async def test_add_flashcards_to_own_set_and_refuse_foreign_sets(world: World) -> None:
    """UF-MCP-03 3b: adding to someone else's set is refused and audited."""
    token, actor = world.connector_token("student", *ALL)
    mine = await world.flashcards.create_set(actor.user_id, "Mine", [], source="manual")
    theirs = await world.flashcards.create_set(
        UUID(int=99), "Theirs", [], source="manual"
    )
    cards = [{"front": "q", "back": "a"}]

    async with world.session("student", token) as session:
        ok = await call(session, "add_flashcards", set_id=str(mine["id"]), cards=cards)
        refused = await call(
            session, "add_flashcards", set_id=str(theirs["id"]), cards=cards
        )
        missing = await call(
            session, "add_flashcards", set_id=str(UUID(int=5)), cards=cards
        )

    assert data_of(ok)["added"] == 1
    assert world.flashcards.added == [(actor.user_id, mine["id"], [("q", "a")])]
    assert refused.isError
    assert "belongs to another user" in text_of(refused)
    assert missing.isError
    [event] = world.audit.of_type("mcp.denied")
    assert event.metadata is not None
    assert event.metadata["reason"] == "mcp/not-owner"


async def test_update_flashcard_changes_text_and_needs_a_field(world: World) -> None:
    """MCP-6: cards can be edited, with at least one field."""
    token, actor = world.connector_token("student", *ALL)
    card_id = UUID(int=77)

    async with world.session("student", token) as session:
        ok = await call(session, "update_flashcard", card_id=str(card_id), back="new")
        nothing = await call(session, "update_flashcard", card_id=str(card_id))

    assert data_of(ok)["back"] == "new"
    assert world.flashcards.updated == [(actor.user_id, card_id, None, "new")]
    assert nothing.isError
    assert "give front, back or both" in text_of(nothing)
