"""LIB-4, LIB-2, LIB-16: topics, collections, reading lists and statistics over HTTP."""

from collections.abc import Awaitable, Callable
from uuid import UUID

from app.shared.actor import Actor
from app.shared.ids import new_id
from tests.fakes.library.academic import FakeAcademicDirectory

from httpx import AsyncClient

Api = Callable[[Actor | None], Awaitable[AsyncClient]]
NAMES = {"uz": "Mexanika", "ru": "Механика", "en": "Mechanics"}


async def test_anonymous_reads_topics_and_collections_but_not_lists(api: Api) -> None:
    """LIB-4: the tree and the shelves are public, reading lists need a login."""
    client = await api(None)

    assert (await client.get("/v1/library/topics")).json() == []
    assert (await client.get("/v1/library/collections")).json() == []
    assert (await client.get("/v1/library/reading-lists")).status_code == 401


async def test_librarian_manages_topics_students_do_not(
    api: Api, librarian: Actor, student: Actor, subject_id: UUID
) -> None:
    """LIB-2: topic CRUD is for librarians; the tree is in the reader language."""
    body = {"subject_id": str(subject_id), "name": NAMES}

    refused = await (await api(student)).post("/v1/manage/library/topics", json=body)
    created = await (await api(librarian)).post("/v1/manage/library/topics", json=body)
    topic_id = created.json()["id"]
    renamed = await (await api(librarian)).patch(
        f"/v1/manage/library/topics/{topic_id}", json={"year_of_study": 1}
    )
    tree = await (await api(None)).get(
        "/v1/library/topics", params={"subject_id": str(subject_id)}
    )
    deleted = await (await api(librarian)).delete(
        f"/v1/manage/library/topics/{topic_id}"
    )

    assert refused.status_code == 403
    assert created.status_code == 201 and created.json()["name"] == NAMES
    assert renamed.json()["year_of_study"] == 1
    assert [t["slug"] for t in tree.json()] == [created.json()["slug"]]
    assert tree.json()[0]["children"] == []
    assert deleted.status_code == 204


async def test_collection_lifecycle(api: Api, librarian: Actor) -> None:
    """LIB-4: a published collection is public; PATCH changes only what was sent."""
    client = await api(librarian)
    title = {"uz": "A", "ru": "Б", "en": "C"}

    created = await client.post(
        "/v1/manage/library/collections", json={"title": title, "published": False}
    )
    collection_id = created.json()["id"]
    hidden = await (await api(None)).get(f"/v1/library/collections/{collection_id}")
    patched = await client.patch(
        f"/v1/manage/library/collections/{collection_id}", json={"published": True}
    )
    shown = await (await api(None)).get(f"/v1/library/collections/{collection_id}")
    deleted = await client.delete(f"/v1/manage/library/collections/{collection_id}")

    assert created.status_code == 201 and created.json()["published"] is False
    assert hidden.status_code == 404
    assert patched.json()["title"] == title and patched.json()["published"] is True
    assert shown.status_code == 200 and shown.json()["items"] == []
    assert deleted.status_code == 204


async def test_reading_list_roundtrip_and_my_groups(
    api: Api,
    teacher: Actor,
    student: Actor,
    academic: FakeAcademicDirectory,
    subject_id: UUID,
) -> None:
    """LIB-4: a teacher builds a list for their group; the group's student reads it."""
    group = new_id()
    academic.teaches.add((teacher.user_id, subject_id))
    academic.group_names[group] = "2TN2"
    academic.teacher_group_ids[teacher.user_id] = [group]
    academic.groups[student.user_id] = group
    teacher_client, student_client = await api(teacher), await api(student)

    groups = await teacher_client.get("/v1/library/my-groups")
    created = await teacher_client.post(
        "/v1/library/reading-lists",
        json={
            "title": "Mechanics",
            "scope": "groups",
            "subject_id": str(subject_id),
            "group_ids": [str(group)],
            "term_half": 1,
            "status": "published",
        },
    )
    list_id = created.json()["id"]
    replaced = await teacher_client.put(
        f"/v1/library/reading-lists/{list_id}/items",
        json={
            "items": [
                {
                    "importance": "essential",
                    "url": "https://example.org/a",
                    "title": "Lecture",
                    "week_label": "Week 1",
                }
            ]
        },
    )
    seen = await student_client.get(f"/v1/library/reading-lists/{list_id}")
    listed = await student_client.get("/v1/library/reading-lists")
    forbidden = await student_client.patch(
        f"/v1/library/reading-lists/{list_id}", json={"title": "x"}
    )

    assert groups.json() == [{"id": str(group), "name": "2TN2"}]
    assert created.status_code == 201 and created.json()["term_half"] == 1
    assert replaced.json()["entries"][0]["url"] == "https://example.org/a"
    assert seen.json()["can_edit"] is False and seen.json()["entry_count"] == 1
    assert [c["id"] for c in listed.json()] == [list_id]
    assert forbidden.status_code == 403
    assert (await student_client.get("/v1/library/my-groups")).status_code == 403


async def test_statistics_endpoint(api: Api, librarian: Actor, student: Actor) -> None:
    """LIB-16: librarians get the contract's keys; students are refused."""
    ok = await (await api(librarian)).get("/v1/manage/library/stats")
    refused = await (await api(student)).get("/v1/manage/library/stats")

    assert ok.status_code == 200
    assert {"opens", "readers", "queue", "top_items", "items_by_status"} <= set(
        ok.json()
    )
    assert refused.status_code == 403
