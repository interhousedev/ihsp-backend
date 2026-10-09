"""NB-AUTO: routes of the subject and lesson notebooks, their settings and copies."""

from uuid import UUID

from app.shared.actor import Actor
from app.shared.contracts.academic import LessonRef
from app.shared.ids import new_id
from tests.fakes.ai.contracts import make_lesson
from tests.fakes.notebooks.world import World
from tests.notebooks.unit.auto.conftest import student_file, teacher_file

import pytest
from httpx import AsyncClient, Response


@pytest.fixture
def physics(world: World, student: Actor) -> LessonRef:
    """A Physics lesson the student attends."""
    return world.schedule.attend(student.user_id, make_lesson(subject="Physics"))


def problem_type(response: Response) -> str:
    """The `type` of a problem+json response."""
    assert response.headers["content-type"].startswith("application/problem+json")
    return str(response.json()["type"])


async def test_posting_the_subject_creates_the_notebook_and_posting_again_returns_it(
    api: AsyncClient, world: World, physics: LessonRef
) -> None:
    """NB-AUTO: get-or-create answers 200 with the detail and the auto settings."""
    teacher_file(world, physics)
    url = f"/v1/notebooks/auto/subject/{physics.subject_id}"

    first = await api.post(url)
    again = await api.post(url)

    assert first.status_code == 200, first.text
    body = first.json()
    assert again.json()["id"] == body["id"]
    assert body["origin"] == "subject_auto"
    assert body["subject_id"] == str(physics.subject_id) and body["lesson_id"] is None
    assert body["title"] == "Physics" and body["source_count"] == 1
    assert body["auto"]["include_classmates"] is False
    assert body["auto"]["excluded_refs"] == []
    assert body["auto"]["synced_at"] is not None


async def test_getting_the_subject_only_looks(
    api: AsyncClient, world: World, physics: LessonRef
) -> None:
    """NB-AUTO: 404 until the student opens it; then the same notebook."""
    url = f"/v1/notebooks/auto/subject/{physics.subject_id}"

    missing = await api.get(url)
    created = await api.post(url)
    found = await api.get(url)

    assert missing.status_code == 404 and problem_type(missing) == "notebooks/not-found"
    assert found.status_code == 200 and found.json()["id"] == created.json()["id"]


async def test_the_lesson_notebook_is_listed_with_its_origin(
    api: AsyncClient, physics: LessonRef
) -> None:
    """NB-AUTO: the list tells auto notebooks from the student's own."""
    opened = await api.post(f"/v1/notebooks/auto/lesson/{physics.id}")
    manual = await api.post("/v1/notebooks", json={"title": "Mine"})

    listed = await api.get("/v1/notebooks")

    assert opened.status_code == 200 and opened.json()["origin"] == "lesson_auto"
    origins = {item["id"]: item["origin"] for item in listed.json()["items"]}
    assert origins == {
        opened.json()["id"]: "lesson_auto",
        manual.json()["id"]: "manual",
    }


async def test_a_subject_or_lesson_of_someone_else_is_not_found(
    api: AsyncClient, world: World, other_student: Actor
) -> None:
    """NB-AUTO: no lessons of the student's own means 404 for both routes."""
    foreign = world.schedule.attend(other_student.user_id, make_lesson())

    subject = await api.post(f"/v1/notebooks/auto/subject/{foreign.subject_id}")
    lesson = await api.post(f"/v1/notebooks/auto/lesson/{foreign.id}")
    nothing = await api.post(f"/v1/notebooks/auto/subject/{new_id()}")

    assert (subject.status_code, lesson.status_code, nothing.status_code) == (
        404,
        404,
        404,
    )


async def test_patching_the_auto_settings_switches_classmates_and_excludes_files(
    api: AsyncClient,
    world: World,
    student: Actor,
    other_student: Actor,
    physics: LessonRef,
) -> None:
    """NB-AUTO: toggle, exclude by source id and restore, all through one route."""
    world.schedule.attend(other_student.user_id, physics)
    teacher_file(world, physics, "Waves")
    student_file(world, physics, other_student, "Slides")
    opened = (await api.post(f"/v1/notebooks/auto/subject/{physics.subject_id}")).json()
    notebook_id = opened["id"]
    assert opened["source_count"] == 1

    on = await api.patch(
        f"/v1/notebooks/{notebook_id}/auto", json={"include_classmates": True}
    )
    sources = (await api.get(f"/v1/notebooks/{notebook_id}/sources")).json()
    classmate = next(s for s in sources if s["origin"].get("from_classmates"))
    off = await api.patch(
        f"/v1/notebooks/{notebook_id}/auto",
        json={"exclude_source_ids": [classmate["id"]]},
    )
    restored = await api.patch(
        f"/v1/notebooks/{notebook_id}/auto",
        json={"restore_refs": [off.json()["auto"]["excluded_refs"][0]["ref_key"]]},
    )

    assert on.status_code == 200 and on.json()["source_count"] == 2
    assert on.json()["auto"]["include_classmates"] is True
    assert off.json()["source_count"] == 1
    assert off.json()["auto"]["excluded_refs"][0]["title"] == "Slides"
    assert restored.json()["source_count"] == 2
    assert restored.json()["auto"]["excluded_refs"] == []


async def test_bad_auto_settings_are_a_422_and_a_manual_notebook_has_none(
    api: AsyncClient, physics: LessonRef
) -> None:
    """NB-AUTO: unknown keys fail validation; a manual notebook is refused."""
    opened = (await api.post(f"/v1/notebooks/auto/subject/{physics.subject_id}")).json()
    manual = (await api.post("/v1/notebooks", json={"title": "Mine"})).json()

    unknown = await api.patch(f"/v1/notebooks/{opened['id']}/auto", json={"title": "x"})
    bad = await api.patch(
        f"/v1/notebooks/{opened['id']}/auto", json={"include_classmates": "maybe"}
    )
    not_auto = await api.patch(
        f"/v1/notebooks/{manual['id']}/auto", json={"include_classmates": True}
    )

    assert (unknown.status_code, bad.status_code, not_auto.status_code) == (
        422,
        422,
        422,
    )
    assert problem_type(not_auto) == "notebooks/invalid-options"


async def test_lesson_sources_of_an_auto_notebook_are_read_only(
    api: AsyncClient, world: World, physics: LessonRef
) -> None:
    """NB-AUTO: adding or removing a material answers 409 `notebooks/auto-readonly`."""
    teacher_file(world, physics)
    opened = (await api.post(f"/v1/notebooks/auto/subject/{physics.subject_id}")).json()
    [source] = (await api.get(f"/v1/notebooks/{opened['id']}/sources")).json()

    added = await api.post(
        f"/v1/notebooks/{opened['id']}/sources",
        json={"items": [{"kind": "text", "title": "Pasted", "text": "Some text."}]},
    )
    removed = await api.delete(f"/v1/notebooks/{opened['id']}/sources/{source['id']}")

    assert added.status_code == 409 and problem_type(added) == "notebooks/auto-readonly"
    assert (
        removed.status_code == 409
        and problem_type(removed) == "notebooks/auto-readonly"
    )


async def test_copy_makes_an_editable_notebook_with_the_same_sources(
    api: AsyncClient, world: World, physics: LessonRef
) -> None:
    """NB-AUTO: POST /copy answers 201 and the copy takes edits."""
    teacher_file(world, physics)
    opened = (await api.post(f"/v1/notebooks/auto/subject/{physics.subject_id}")).json()

    copied = await api.post(f"/v1/notebooks/{opened['id']}/copy")

    assert copied.status_code == 201, copied.text
    body = copied.json()
    assert body["id"] != opened["id"] and body["origin"] == "manual"
    assert body["auto"] is None and body["title"] == "Physics (copy)"
    assert body["source_count"] == 1
    [source] = (await api.get(f"/v1/notebooks/{body['id']}/sources")).json()
    removed = await api.delete(f"/v1/notebooks/{body['id']}/sources/{source['id']}")
    assert removed.status_code == 204


async def test_the_copy_of_someone_elses_notebook_is_a_404(
    api: AsyncClient, current: dict[str, Actor], other_student: Actor
) -> None:
    """NB-AUTO: notebooks are private."""
    mine = (await api.post("/v1/notebooks", json={"title": "Mine"})).json()
    current["actor"] = other_student

    response = await api.post(f"/v1/notebooks/{mine['id']}/copy")

    assert response.status_code == 404
    assert UUID(mine["id"])
