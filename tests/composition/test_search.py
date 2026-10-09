"""WEB-4, UF-WEB-14: global search (GET /v1/me/search)."""

import datetime as dt
from typing import Any

from app.shared.actor import Role
from app.shared.contracts.academic import SubjectSummary
from app.shared.ids import new_id
from tests.composition.conftest import ClientFor, World, actor_of
from tests.composition.fakes import make_lesson, make_user


def summary(name: str) -> SubjectSummary:
    return SubjectSummary(
        subject_id=new_id(),
        name=name,
        teacher_names=(),
        semester_mark=None,
        emis_rating=None,
        absences=0,
        lessons_with_attendance=0,
    )


def file_item(name: str) -> dict[str, Any]:
    return {
        "id": new_id(),
        "name": name,
        "content_type": "application/pdf",
        "byte_size": 10,
        "purpose": "ai_upload",
        "status": "ready",
        "reject_reason": None,
        "text_bytes": 5,
        "assistant_ready": True,
        "created_at": dt.datetime(2026, 9, 20, 8, 0, tzinfo=dt.UTC),
        "expires_on": None,
        "used_by": [],
    }


async def test_subjects_are_matched_by_name_ignoring_case(world: World) -> None:
    """WEB-4: the student's subjects by name."""
    student = world.add_student()
    world.marks.summaries = [
        summary("Calculus"),
        summary("Physics"),
        summary("Discrete calculus"),
    ]

    results = await world.composition.search_all.execute(actor_of(student), "CALC")

    assert [s["name"] for s in results["subjects"]] == [
        "Calculus",
        "Discrete calculus",
    ]
    assert results["subjects"][0]["short_name"] == "Calculus"


async def test_lessons_are_found_by_topic_and_described_like_a_timetable_entry(
    world: World,
) -> None:
    """WEB-4: lessons by topic, as LessonItem."""
    student = world.add_student()
    teacher = world.add_user(Role.TEACHER, first_name="Nodira", last_name="Aliyeva")
    lesson = make_lesson(
        topic="Derivatives of polynomials",
        teacher_id=teacher.id,
        homework="Exercises 1-5",
        group_name="2TN2",
        subgroup=1,
    )
    other = make_lesson(topic="Integrals")
    world.schedule.lessons = [lesson, other]

    results = await world.composition.search_all.execute(
        actor_of(student), "derivative"
    )

    assert world.schedule.search_calls == [(student.id, "derivative", 5)]
    [item] = results["lessons"]
    assert item["id"] == lesson.id
    assert item["topic"] == "Derivatives of polynomials"
    assert item["teacher"] == {
        "id": teacher.id,
        "first_name": "Nodira",
        "last_name": "Aliyeva",
    }
    assert item["room"]["name"] == "102"
    assert item["has_homework"] is True
    [audience] = item["audience"]
    assert (audience["group_name"], audience["subgroup"]) == ("2TN2", 1)


async def test_homework_is_matched_by_text_newest_first(world: World) -> None:
    """WEB-4: homework text contains the query."""
    student = world.add_student()
    teacher = world.add_user(Role.TEACHER)
    old = make_lesson(
        day=dt.date(2026, 9, 10), homework="Read about limits", teacher_id=teacher.id
    )
    new = make_lesson(
        day=dt.date(2026, 10, 1),
        homework="Solve limits 1-4",
        homework_due=dt.date(2026, 10, 8),
        teacher_id=teacher.id,
    )
    unrelated = make_lesson(homework="Essay")
    done_at = dt.datetime(2026, 10, 2, 7, 0, tzinfo=dt.UTC)
    world.classwork.homework_entries = [
        {"lesson": old, "done_at": None, "note": None},
        {"lesson": new, "done_at": done_at, "note": "ask Nodira"},
        {"lesson": unrelated, "done_at": None, "note": None},
    ]

    results = await world.composition.search_all.execute(actor_of(student), "limits")

    first, second = results["homework"]
    assert (first["lesson_id"], second["lesson_id"]) == (new.id, old.id)
    assert first["text"] == "Solve limits 1-4"
    assert first["due_date"] == dt.date(2026, 10, 8)
    assert first["given_on"] == dt.date(2026, 10, 1)
    assert first["done_at"] == done_at
    assert first["note"] == "ask Nodira"
    assert first["teacher"]["id"] == teacher.id
    assert first["updated"] is False


async def test_files_come_from_the_file_search_port(world: World) -> None:
    """WEB-4: files by name and text."""
    student = world.add_student()
    world.files.found = [file_item("limits.pdf")]

    results = await world.composition.search_all.execute(actor_of(student), "limits")

    assert world.files.search_calls == [(student.id, "limits", 5)]
    assert [f["name"] for f in results["files"]] == ["limits.pdf"]


async def test_flash_card_sets_are_matched_by_title(world: World) -> None:
    """WEB-4: flash card sets by title."""
    student = world.add_student()
    kept = {
        "id": str(new_id()),
        "title": "Derivative rules",
        "description": None,
        "source": "manual",
        "card_count": 12,
    }
    skipped = {**kept, "id": str(new_id()), "title": "Vocabulary"}
    world.flashcards.sets = [kept, skipped]

    results = await world.composition.search_all.execute(actor_of(student), "deriv")

    [item] = results["flashcard_sets"]
    assert item["title"] == "Derivative rules"
    assert (item["card_count"], item["due_today"], item["new_today"]) == (12, 0, 0)


async def test_every_group_holds_at_most_five_results(world: World) -> None:
    """WEB-4: max 5 per group."""
    student = world.add_student()
    world.marks.summaries = [summary(f"Algebra {i}") for i in range(8)]
    world.schedule.lessons = [make_lesson(topic=f"Algebra {i}") for i in range(8)]
    world.classwork.homework_entries = [
        {"lesson": make_lesson(homework=f"Algebra {i}"), "done_at": None, "note": None}
        for i in range(8)
    ]
    world.files.found = [file_item(f"algebra{i}.pdf") for i in range(8)]
    world.flashcards.sets = [
        {"id": str(new_id()), "title": f"Algebra {i}", "card_count": 1}
        for i in range(8)
    ]

    results = await world.composition.search_all.execute(actor_of(student), "algebra")

    assert {key: len(items) for key, items in results.items()} == {
        "subjects": 5,
        "lessons": 5,
        "homework": 5,
        "files": 5,
        "flashcard_sets": 5,
    }


async def test_staff_search_only_lessons_and_files(world: World) -> None:
    """WEB-4: subjects, homework and flash cards belong to students."""
    teacher = world.add_user(Role.TEACHER)
    world.schedule.lessons = [make_lesson(topic="Derivatives")]
    world.marks.summaries = [summary("Derivatives")]
    world.flashcards.sets = [{"id": str(new_id()), "title": "Derivatives"}]

    results = await world.composition.search_all.execute(actor_of(teacher), "deriv")

    assert len(results["lessons"]) == 1
    assert results["subjects"] == []
    assert results["homework"] == []
    assert results["flashcard_sets"] == []
    assert world.flashcards.list_calls == 0


async def test_endpoint_returns_search_results_with_contract_fields(
    world: World, client_for: ClientFor
) -> None:
    """GET /v1/me/search?q: SearchResults with the five groups."""
    student = world.add_student()
    world.marks.summaries = [summary("Calculus")]
    world.files.found = [file_item("calculus.pdf")]
    client = await client_for(actor_of(student))

    response = await client.get("/v1/me/search", params={"q": "calc"})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"subjects", "lessons", "homework", "files", "flashcard_sets"}
    assert set(body["subjects"][0]) == {"id", "name", "short_name"}
    assert body["files"][0]["name"] == "calculus.pdf"


async def test_endpoint_serializes_every_group_with_the_contract_fields(
    world: World, client_for: ClientFor
) -> None:
    """GET /v1/me/search?q: LessonItem, HomeworkItem, FileItem, FlashcardSetItem."""
    student = world.add_student()
    teacher = world.add_user(Role.TEACHER, first_name="Nodira", last_name="Aliyeva")
    lesson = make_lesson(
        topic="Limits and continuity", homework="Limits 1-4", teacher_id=teacher.id
    )
    world.schedule.lessons = [lesson]
    world.classwork.homework_entries = [
        {"lesson": lesson, "done_at": None, "note": None}
    ]
    world.files.found = [file_item("limits.pdf")]
    world.flashcards.sets = [
        {"id": str(new_id()), "title": "Limits", "description": "Ch. 1", "source": "ai"}
    ]
    client = await client_for(actor_of(student))

    response = await client.get("/v1/me/search", params={"q": "limits"})

    assert response.status_code == 200
    body = response.json()
    assert set(body["lessons"][0]) == {
        "id",
        "date",
        "period",
        "starts_at",
        "ends_at",
        "subject",
        "teacher",
        "room",
        "audience",
        "status",
        "is_overridden",
        "changes",
        "topic",
        "kind",
        "topic_source",
        "has_homework",
        "attendance_submitted",
    }
    assert body["lessons"][0]["starts_at"].endswith("Z")
    assert set(body["homework"][0]) == {
        "lesson_id",
        "subject",
        "teacher",
        "text",
        "due_date",
        "given_on",
        "updated",
        "done_at",
        "note",
    }
    assert set(body["files"][0]) == set(file_item("x"))
    assert body["flashcard_sets"][0] == {
        "id": body["flashcard_sets"][0]["id"],
        "title": "Limits",
        "description": "Ch. 1",
        "source": "ai",
        "card_count": 0,
        "due_today": 0,
        "new_today": 0,
    }


async def test_a_one_character_query_is_refused(
    world: World, client_for: ClientFor
) -> None:
    """WEB-4: at least two characters."""
    student = world.add_student()
    client = await client_for(actor_of(student))

    response = await client.get("/v1/me/search", params={"q": "a"})

    assert response.status_code == 422
    assert world.files.search_calls == []


async def test_spaces_do_not_count_towards_the_minimum_length(
    world: World, client_for: ClientFor
) -> None:
    """WEB-4: "a " is one character."""
    student = world.add_student()
    client = await client_for(actor_of(student))

    response = await client.get("/v1/me/search", params={"q": "a "})

    assert response.status_code == 422
    assert response.json()["type"] == "common/validation"


async def test_search_works_for_any_logged_in_user(
    world: World, client_for: ClientFor
) -> None:
    """GET /v1/me/search is `bearer`, not student-only."""
    teacher = make_user(Role.TEACHER)
    world.identity.add(teacher)
    client = await client_for(actor_of(teacher))

    response = await client.get("/v1/me/search", params={"q": "limits"})

    assert response.status_code == 200


async def test_search_needs_a_login(client_for: ClientFor) -> None:
    """GET /v1/me/search without a token answers 401."""
    client = await client_for(None)

    response = await client.get("/v1/me/search", params={"q": "limits"})

    assert response.status_code == 401
