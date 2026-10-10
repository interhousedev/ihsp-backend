"""Global search sources: notebooks, lessons (topic, subject, date), marks, library."""

import datetime as dt

from app.shared.actor import Role
from app.shared.contracts.academic import MarkRef
from app.shared.ids import new_id
from tests.composition.conftest import World, actor_of
from tests.composition.fakes import make_lesson
from tests.composition.test_search import summary


def notebook(title: str, sources: list[str] | None = None) -> dict[str, object]:
    return {
        "id": new_id(),
        "title": title,
        "emoji": "🧪",
        "source_count": len(sources or []),
        "matched_sources": sources or [],
    }


def mark(subject_id: object, name: str, day: dt.date, value: int) -> MarkRef:
    return MarkRef(
        subject_id=subject_id,  # type: ignore[arg-type]
        subject_name=name,
        semester=1,
        type="current",
        value=value,
        date=day,
        lesson_id=None,
    )


async def test_notebooks_are_found_by_title_and_by_source_title(world: World) -> None:
    """'photosyn' finds the notebook named so and the one holding a matching source."""
    student = world.add_student()
    by_title = notebook("Photosynthesis basics")
    by_source = notebook("Biology 9", ["Photosynthesis.pdf"])
    world.sources.notebook_rows = [by_title, by_source, notebook("Algebra")]

    results = await world.composition.search_all.execute(actor_of(student), "photosyn")

    assert [n["id"] for n in results["notebooks"]] == [by_title["id"], by_source["id"]]
    assert results["notebooks"][1]["matched_sources"] == ["Photosynthesis.pdf"]


async def test_lessons_are_found_by_topic(world: World) -> None:
    """The lesson topic hit, as a timetable entry."""
    student = world.add_student()
    world.schedule.lessons = [make_lesson(topic="Photosynthesis in leaves")]

    results = await world.composition.search_all.execute(actor_of(student), "photosyn")

    assert [x["topic"] for x in results["lessons"]] == ["Photosynthesis in leaves"]


async def test_lessons_are_found_by_date(world: World) -> None:
    """A date typed as dd.mm.yyyy lists that day's lessons for a student."""
    student = world.add_student()
    on_day = make_lesson(topic="Limits", day=dt.date(2026, 10, 7))
    other = make_lesson(topic="Integrals", day=dt.date(2026, 10, 8))
    world.schedule.lessons = [on_day, other]

    results = await world.composition.search_all.execute(
        actor_of(student), "07.10.2026"
    )

    assert [x["id"] for x in results["lessons"]] == [on_day.id]


async def test_marks_come_from_the_subject_name_newest_first(world: World) -> None:
    """Typing a subject name gives its recent marks."""
    student = world.add_student()
    biology, physics = summary("Biology"), summary("Physics")
    world.marks.summaries = [biology, physics]
    world.marks.mark_rows = [
        mark(biology.subject_id, "Biology", dt.date(2026, 9, 10), 4),
        mark(biology.subject_id, "Biology", dt.date(2026, 10, 1), 5),
        mark(physics.subject_id, "Physics", dt.date(2026, 10, 2), 3),
    ]

    results = await world.composition.search_all.execute(actor_of(student), "biolog")

    assert [(m["subject"]["name"], m["value"]) for m in results["marks"]] == [
        ("Biology", 5),
        ("Biology", 4),
    ]


async def test_library_items_are_searched_for_the_actor(world: World) -> None:
    """Library hits come through the port with the caller's actor."""
    student = world.add_student()
    world.sources.library_rows = [
        {
            "id": new_id(),
            "slug": "bio",
            "title": "Biology textbook",
            "author_label": "A",
            "kind": "book",
        },
        {
            "id": new_id(),
            "slug": "chem",
            "title": "Chemistry",
            "author_label": "B",
            "kind": "book",
        },
    ]

    results = await world.composition.search_all.execute(actor_of(student), "biology")

    assert [i["title"] for i in results["library_items"]] == ["Biology textbook"]
    assert world.sources.library_actors[0].user_id == student.id


async def test_staff_do_not_get_student_only_groups(world: World) -> None:
    """Marks stay student-only; staff still search notebooks and the library."""
    teacher = world.add_user(Role.TEACHER)
    biology = summary("Biology")
    world.marks.summaries = [biology]
    world.marks.mark_rows = [
        mark(biology.subject_id, "Biology", dt.date(2026, 10, 1), 5)
    ]
    world.sources.notebook_rows = [notebook("Biology 9")]

    results = await world.composition.search_all.execute(actor_of(teacher), "biolog")

    assert results["marks"] == []
    assert results["subjects"] == []
    assert len(results["notebooks"]) == 1
