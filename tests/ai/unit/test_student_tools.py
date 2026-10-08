"""AI-5: the student assistant's read tools and the flash card writes."""

import datetime as dt
import json
from typing import Any

from app.modules.ai.domain.assistant import Assistant
from app.modules.ai.infrastructure.fake_llm import FakeLlmGateway
from app.modules.ai.infrastructure.gateway_factory import make_llm_gateway
from app.modules.ai.infrastructure.openrouter import OpenRouterGateway
from app.settings import Settings
from app.shared.contracts.academic import SubjectSummary
from app.shared.contracts.links import ResourceRef
from app.shared.ids import new_id
from tests.ai.conftest import AiHarness
from tests.fakes.ai.contracts import make_file, make_lesson
from tests.fakes.ai.llm import text_reply, tool_reply

import pytest
from pydantic import SecretStr


async def run_tool(
    h: AiHarness, name: str, arguments: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    """Let the model call one read tool; return the call status and the tool message."""
    chat = await h.new_chat()
    h.llm.push(tool_reply((name, arguments)), text_reply("done"))
    result = await h.say(chat.id, "go")
    sent = json.loads(h.llm.requests[-1]["messages"][-1]["content"])
    return result.new_messages[1].tool_calls[0].status, sent


async def test_subjects_summary_is_listed(h: AiHarness) -> None:
    """AI-5: get_my_subjects returns name, teachers, mark, rating and absences."""
    subject = SubjectSummary(new_id(), "Physics", ("Ms. Ivanova",), 4.5, 90, 2, 20)
    h.marks.summary = [subject]

    status, sent = await run_tool(h, "get_my_subjects", {})

    row = sent["untrusted_data"]["subjects"][0]
    assert status == "done"
    assert (row["name"], row["teachers"], row["semester_mark"]) == (
        "Physics",
        ["Ms. Ivanova"],
        4.5,
    )
    assert (row["emis_rating"], row["absences"]) == (90, 2)


async def test_schedule_lists_lessons_and_rejects_bad_ranges(h: AiHarness) -> None:
    """AI-5: get_schedule is limited to 62 days and must not be reversed."""
    h.schedule.lessons = [
        make_lesson(day=dt.date(2026, 10, 7)),
        make_lesson(day=dt.date(2027, 1, 1)),
    ]

    status, sent = await run_tool(
        h, "get_schedule", {"from": "2026-10-06", "to": "2026-10-08"}
    )
    bad_status, bad = await run_tool(
        h, "get_schedule", {"from": "2026-10-06", "to": "2027-03-01"}
    )
    rev_status, _ = await run_tool(
        h, "get_schedule", {"from": "2026-10-08", "to": "2026-10-06"}
    )

    assert status == "done" and len(sent["untrusted_data"]["items"]) == 1
    assert bad_status == "failed" and "62 days" in bad["error"]
    assert rev_status == "failed"


async def test_homework_marks_and_attendance_are_passed_through(h: AiHarness) -> None:
    """AI-5: filters reach the queries; rows carry lesson, mark and absence data."""
    lesson = make_lesson(homework="Exercise 5")
    h.classwork.homework_rows = [
        {
            "lesson": lesson,
            "done_at": dt.datetime(2026, 10, 6, tzinfo=dt.UTC),
            "note": "n",
        }
    ]
    h.classwork.absence_rows = [{"lesson": lesson, "excused": False}]

    _, homework = await run_tool(
        h, "get_homework", {"done": False, "from": "2026-10-01"}
    )
    _, absences = await run_tool(h, "get_attendance", {})
    _, marks = await run_tool(h, "get_marks", {"subject_id": str(lesson.subject_id)})

    row = homework["untrusted_data"]["items"][0]
    assert (row["homework"], row["note"], row["done_at"][:10]) == (
        "Exercise 5",
        "n",
        "2026-10-06",
    )
    assert (
        "homework",
        (h.student.user_id, dt.date(2026, 10, 1), None, False),
    ) in h.classwork.calls
    assert absences["untrusted_data"]["items"][0]["excused"] is False
    assert marks["untrusted_data"]["items"] == []


async def test_lesson_materials_only_for_lessons_the_student_attends(
    h: AiHarness,
) -> None:
    """AI-5: names, kinds and ids; refused outside the audience."""
    lesson = make_lesson()
    other = make_lesson()
    h.schedule.audience.add((h.student.user_id, lesson.id))
    file_id = new_id()
    h.links.items[lesson.id] = [
        ResourceRef(
            new_id(),
            lesson.id,
            "material",
            "file",
            "https://s.ihsu.uz/Ab3",
            "Slides",
            new_id(),
            "Bakhtiyor",
            False,
            file_id,
        )
    ]

    status, sent = await run_tool(
        h, "get_lesson_materials", {"lesson_id": str(lesson.id)}
    )
    denied, error = await run_tool(
        h, "get_lesson_materials", {"lesson_id": str(other.id)}
    )

    resource = sent["untrusted_data"]["resources"][0]
    assert status == "done" and resource["file_id"] == str(file_id)
    assert (resource["title"], resource["kind"], resource["url"]) == (
        "Slides",
        "file",
        "https://s.ihsu.uz/Ab3",
    )
    assert denied == "failed" and error["error"] == "lesson not found"


async def test_lesson_materials_need_the_links_module(h: AiHarness) -> None:
    """The links API is bound late; without it the tool says so instead of crashing."""
    h.services.bindings.links = None
    lesson = make_lesson()
    h.schedule.audience.add((h.student.user_id, lesson.id))

    status, error = await run_tool(
        h, "get_lesson_materials", {"lesson_id": str(lesson.id)}
    )

    assert status == "failed" and "unavailable" in error["error"]


async def test_files_and_flash_cards_are_read_for_the_owner_only(h: AiHarness) -> None:
    """AI-5: list_files, search_files, list_flashcard_sets, get_flashcard_set."""
    h.files.add(make_file(h.student.user_id, name="biology.pdf"))
    h.files.add(make_file(h.other_student.user_id, name="biology-secret.pdf"))
    mine = await h.flashcards.create_set(
        h.student.user_id, "Mine", [("a", "b")], source="manual"
    )
    theirs = await h.flashcards.create_set(
        h.other_student.user_id, "Theirs", [], source="manual"
    )

    _, listed = await run_tool(h, "list_files", {})
    _, found = await run_tool(h, "search_files", {"query": "bio"})
    _, sets = await run_tool(h, "list_flashcard_sets", {})
    _, one = await run_tool(h, "get_flashcard_set", {"set_id": str(mine["id"])})
    foreign_status, _ = await run_tool(
        h, "get_flashcard_set", {"set_id": str(theirs["id"])}
    )

    assert [i["name"] for i in listed["untrusted_data"]["items"]] == ["biology.pdf"]
    assert [i["name"] for i in found["untrusted_data"]["items"]] == ["biology.pdf"]
    assert [i["title"] for i in sets["untrusted_data"]["items"]] == ["Mine"]
    assert one["untrusted_data"]["title"] == "Mine"
    assert foreign_status == "failed"


async def test_add_flashcards_runs_after_approval(h: AiHarness) -> None:
    """AI-5: add_flashcards is a write; approval appends the cards."""
    existing = await h.flashcards.create_set(
        h.student.user_id, "Old", [("a", "b")], source="manual"
    )
    chat = await h.new_chat()
    args = {"set_id": str(existing["id"]), "cards": [{"front": "x", "back": "y"}]}
    h.llm.push(tool_reply(("add_flashcards", args)))
    proposed = await h.say(chat.id, "add one")
    call = proposed.new_messages[-1].tool_calls[0]
    h.llm.push(text_reply("Added."))

    result = await h.services.approve_tool_call.execute(
        actor=h.student, chat_id=chat.id, call_id=call.id
    )

    assert call.preview is not None and call.preview.title == "Add 1 cards to “Old”"
    assert call.preview.fields[0].value == "Old"
    assert h.flashcards.sets[existing["id"]]["card_count"] == 2
    assert result.new_messages[0].tool_calls[0].status == "done"


async def test_a_crashing_tool_does_not_break_the_turn(h: AiHarness) -> None:
    """One broken tool becomes a failed call; the model still answers."""

    async def broken(*_: object) -> list[SubjectSummary]:
        raise RuntimeError("database down")

    h.marks.subjects_summary = broken  # type: ignore[method-assign]

    status, sent = await run_tool(h, "get_my_subjects", {})

    assert status == "failed" and sent == {"error": "the tool crashed"}


async def test_pending_cards_are_expired_when_listing_chats(h: AiHarness) -> None:
    """AI-11: the list shows the corrected pending count after expiry."""
    chat = await h.new_chat()
    cards = {"title": "T", "cards": [{"front": "a", "back": "b"}]}
    h.llm.push(tool_reply(("create_flashcard_set", cards)))
    await h.say(chat.id, "cards")
    h.clock.advance(hours=25)

    page = await h.services.list_chats.execute(
        actor=h.student, assistant=Assistant.STUDENT, cursor=None, limit=20
    )

    assert page.items[0].pending_approvals == 0


def test_gateway_factory_picks_fake_or_openrouter() -> None:
    """OPENROUTER__MODE selects the gateway; real mode needs a key."""
    fake = Settings(env="test")
    real = fake.model_copy(
        update={
            "openrouter": fake.openrouter.model_copy(
                update={"mode": "real", "api_key": SecretStr("k")}
            )
        }
    )
    no_key = fake.model_copy(
        update={"openrouter": fake.openrouter.model_copy(update={"mode": "real"})}
    )

    assert isinstance(make_llm_gateway(fake), FakeLlmGateway)
    assert isinstance(make_llm_gateway(real), OpenRouterGateway)
    with pytest.raises(ValueError, match="OPENROUTER__API_KEY"):
        make_llm_gateway(no_key)
