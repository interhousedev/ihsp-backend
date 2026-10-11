"""HTTP contract of links, shares, lesson resources, reports and moderation."""

from collections.abc import Awaitable, Callable
from datetime import date

from app.shared.actor import Role
from tests.fakes.links.world import LinksWorld

from httpx import AsyncClient

Api = Callable[..., Awaitable[AsyncClient]]


async def test_create_and_list_links_have_the_contract_shape(
    world: LinksWorld, api: Api
) -> None:
    """SL-1, WEB-26: POST /v1/links and GET /v1/me/links."""
    ann = world.person("Ann")
    client = await api(ann)

    created = await client.post(
        "/v1/links", json={"kind": "url", "target_url": "https://example.org/a"}
    )
    listed = await client.get("/v1/me/links", params={"kind": "url", "limit": 10})

    assert created.status_code == 200
    body = created.json()
    assert set(body) == {
        "id", "slug", "kind", "url", "target_url", "file", "title", "lesson_id",
        "target_id", "share_mode", "hits", "created_at", "expires_at", "revoked_at",
        "disabled",
    }  # fmt: skip
    assert body["kind"] == "url"
    assert body["url"].endswith("/s/" + body["slug"])
    assert body["title"] == "Title of https://example.org/a"
    assert body["created_at"].endswith("Z") or "+00:00" in body["created_at"]
    assert listed.status_code == 200
    assert [i["id"] for i in listed.json()["items"]] == [body["id"]]
    assert listed.json()["next_cursor"] is None


async def test_file_link_embeds_the_file_item(world: LinksWorld, api: Api) -> None:
    """SL-3: LinkItem.file follows FileItem."""
    ann = world.person("Ann")
    file = world.files.add(ann.user_id, name="Lecture.pdf")
    client = await api(ann)

    response = await client.post(
        "/v1/links", json={"kind": "file", "file_id": str(file.id)}
    )

    item = response.json()["file"]
    assert item["id"] == str(file.id)
    assert item["name"] == "Lecture.pdf"
    assert item["status"] == "ready"
    assert {"used_by", "assistant_ready", "reject_reason", "expires_on"} <= set(item)
    assert len(response.json()["slug"]) == 8


async def test_blocked_url_is_a_422_problem(world: LinksWorld, api: Api) -> None:
    """SL-8: links/blocked-url as problem+json."""
    client = await api(world.person("Ann"))

    response = await client.post(
        "/v1/links", json={"kind": "url", "target_url": "https://blocked.example/x"}
    )

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["type"] == "links/blocked-url"
    assert response.json()["message_key"] == "links-blocked-url"


async def test_links_require_a_login(api: Api) -> None:
    """GEN: bearer tokens are required."""
    client = await api(None)

    response = await client.get("/v1/me/links")

    assert response.status_code == 401


async def test_delete_returns_204_and_revoke_returns_the_link(
    world: LinksWorld, api: Api
) -> None:
    """SL-7, SHR-6: DELETE /v1/links/{id} and POST /v1/links/{id}/revoke."""
    ann = world.person("Ann")
    client = await api(ann)
    link = (
        await client.post(
            "/v1/links", json={"kind": "url", "target_url": "https://example.org/a"}
        )
    ).json()
    chat = world.ai.add_chat(ann.user_id, [("user", "a")])
    share = (
        await client.post("/v1/shares", json={"kind": "chat", "target_id": str(chat)})
    ).json()

    deleted = await client.delete(f"/v1/links/{link['id']}")
    revoked = await client.post(f"/v1/links/{share['id']}/revoke")
    missing = await client.delete(f"/v1/links/{link['id']}/nope")

    assert deleted.status_code == 204 and deleted.content == b""
    assert revoked.status_code == 200
    assert revoked.json()["revoked_at"] is not None
    assert missing.status_code == 404


async def test_create_share_and_public_read(world: LinksWorld, api: Api) -> None:
    """SHR-1, SHR-2, UF-WEB-24, UF-PUB-01: share, then open without login."""
    ann = world.person("Ann")
    chat = world.ai.add_chat(ann.user_id, [("user", "q"), ("assistant", "a")])
    owner = await api(ann)
    anonymous = await api(None)

    share = await owner.post(
        "/v1/shares",
        json={"kind": "chat", "target_id": str(chat), "share_mode": "snapshot"},
    )
    public = await anonymous.get(f"/v1/public/shares/{share.json()['slug']}")

    assert share.status_code == 200
    assert share.json()["share_mode"] == "snapshot"
    assert share.json()["target_id"] == str(chat)  # the web finds a chat's share by it
    assert share.json()["url"].endswith("/ai/" + share.json()["slug"])
    assert public.status_code == 200
    body = public.json()
    assert body["kind"] == "chat"
    assert body["title"] == "Derivatives"
    assert body["author_first_name"] == "Ann"
    assert body["chat"]["messages"][0] == {
        "role": "user",
        "text": "q",
        "tool_notes": [],
    }
    assert body["flashcards"] is None


async def test_public_flashcard_share_shape(world: LinksWorld, api: Api) -> None:
    """SHR-5, UF-PUB-02."""
    ann = world.person("Ann")
    cards = world.flashcards.add_set(ann.user_id, [("hola", "hello")])
    share = await (await api(ann)).post(
        "/v1/shares", json={"kind": "flashcard_set", "target_id": str(cards)}
    )

    public = await (await api(None)).get(f"/v1/public/shares/{share.json()['slug']}")

    cards_json = public.json()["flashcards"]["cards"]
    assert [(c["front"], c["back"]) for c in cards_json] == [("hola", "hello")]
    assert public.json()["chat"] is None


async def test_share_of_an_admin_chat_is_403(world: LinksWorld, api: Api) -> None:
    """SHR-1: assistant for administration is never shared."""
    ann = world.person("Ann")
    chat = world.ai.add_chat(ann.user_id, [("user", "a")], admin=True)

    response = await (await api(ann)).post(
        "/v1/shares", json={"kind": "chat", "target_id": str(chat)}
    )

    assert response.status_code == 403
    assert response.json()["type"] == "links/share-not-allowed"


async def test_public_share_errors(world: LinksWorld, api: Api) -> None:
    """UF-PUB-01 1a/1b: 410 for revoked, 404 for unknown."""
    ann = world.person("Ann")
    chat = world.ai.add_chat(ann.user_id, [("user", "a")])
    owner = await api(ann)
    share = (
        await owner.post("/v1/shares", json={"kind": "chat", "target_id": str(chat)})
    ).json()
    await owner.post(f"/v1/links/{share['id']}/revoke")
    anonymous = await api(None)

    gone = await anonymous.get(f"/v1/public/shares/{share['slug']}")
    unknown = await anonymous.get("/v1/public/shares/c-00000000")

    assert gone.status_code == 410
    assert gone.json()["type"] == "links/gone"
    assert unknown.status_code == 404


async def test_report_returns_202(world: LinksWorld, api: Api) -> None:
    """UF-PUB-05: POST /v1/public/reports."""
    ann = world.person("Ann")
    link = (
        await (await api(ann)).post(
            "/v1/links", json={"kind": "url", "target_url": "https://example.org/a"}
        )
    ).json()
    anonymous = await api(None)

    ok = await anonymous.post(
        "/v1/public/reports",
        json={"slug": link["slug"], "reason": "phishing", "comment": "fake login"},
    )
    bad = await anonymous.post(
        "/v1/public/reports", json={"slug": link["slug"], "reason": "spam"}
    )

    assert ok.status_code == 202
    assert bad.status_code == 422
    assert bad.json()["type"] == "common/request-validation"
    assert world.uow.store.links[next(iter(world.uow.store.links))].reports == 1


async def test_lesson_resources_endpoints(world: LinksWorld, api: Api) -> None:
    """ACA-9, UF-WEB-07/08, UF-STF-08: list, add, hide, delete."""
    teacher = world.person("Galina", Role.TEACHER)
    student = world.person("Aleksey")
    lesson = world.schedule.add_lesson(
        teacher_id=teacher.user_id, students=[student.user_id]
    )
    path = f"/v1/lessons/{lesson.id}/resources"
    as_student, as_teacher = await api(student), await api(teacher)

    added = await as_student.post(
        path,
        json={
            "role": "attachment",
            "kind": "url",
            "target_url": "https://example.org/d",
        },
    )
    material = await as_teacher.post(
        path,
        json={"role": "material", "kind": "url", "target_url": "https://example.org/m"},
    )
    listing = await as_student.get(path)
    hidden = await as_teacher.post(
        f"{path}/{added.json()[0]['link_id']}/hide", json={"hidden": True}
    )
    student_forbidden = await as_student.post(
        path,
        json={"role": "material", "kind": "url", "target_url": "https://example.org/x"},
    )
    deleted = await as_student.delete(f"{path}/{added.json()[0]['link_id']}")

    item = added.json()[0]
    assert added.status_code == 200
    assert set(item) == {
        "link_id", "lesson_id", "role", "kind", "short_url", "title", "author",
        "hidden", "file", "created_at", "source",
    }  # fmt: skip
    assert item["author"] == {
        "id": str(student.user_id),
        "first_name": "Aleksey",
        "last_name": "ALEKSEY",
    }
    assert material.status_code == 200
    assert [r["role"] for r in listing.json()] == ["material", "attachment"]
    assert hidden.json()["hidden"] is True
    assert student_forbidden.status_code == 403
    assert student_forbidden.json()["type"] == "links/resource-forbidden"
    assert deleted.status_code == 204


async def test_admin_manages_resources_of_any_lesson(
    world: LinksWorld, api: Api
) -> None:
    """ACA-9, STF-6: Administration manages resources of another teacher's lesson."""
    teacher = world.person("Galina", Role.TEACHER)
    student = world.person("Aleksey")
    admin = world.person("Root", Role.ADMIN)
    lesson = world.schedule.add_lesson(
        teacher_id=teacher.user_id, students=[student.user_id]
    )
    path = f"/v1/lessons/{lesson.id}/resources"
    as_student, as_admin = await api(student), await api(admin)

    attachment = await as_student.post(
        path,
        json={
            "role": "attachment",
            "kind": "url",
            "target_url": "https://example.org/d",
        },
    )
    material = await as_admin.post(
        path,
        json={"role": "material", "kind": "url", "target_url": "https://example.org/m"},
    )
    listing = await as_admin.get(path)
    hidden = await as_admin.post(
        f"{path}/{attachment.json()[0]['link_id']}/hide", json={"hidden": True}
    )
    deleted = await as_admin.delete(f"{path}/{attachment.json()[0]['link_id']}")
    also = await as_admin.post(
        path,
        json={
            "role": "material",
            "kind": "url",
            "target_url": "https://example.org/n",
            "also_lesson_ids": [str(lesson.id)],
        },
    )

    assert material.status_code == 200
    assert [r["role"] for r in listing.json()] == ["material", "attachment"]
    assert hidden.status_code == 200 and hidden.json()["hidden"] is True
    assert deleted.status_code == 204
    assert also.status_code == 200


async def test_also_lesson_ids_creates_a_resource_per_lesson(
    world: LinksWorld, api: Api
) -> None:
    """UF-STF-04 step 3."""
    teacher = world.person("Galina", Role.TEACHER)
    first = world.schedule.add_lesson(teacher_id=teacher.user_id, group_names=("2TN1",))
    second = world.schedule.add_lesson(
        period=4,
        subject_id=first.subject_id,
        teacher_id=teacher.user_id,
        group_names=("2TN2",),
    )

    response = await (await api(teacher)).post(
        f"/v1/lessons/{first.id}/resources",
        json={
            "role": "material",
            "kind": "url",
            "target_url": "https://example.org/m",
            "also_lesson_ids": [str(second.id)],
        },
    )

    assert [r["lesson_id"] for r in response.json()] == [str(first.id), str(second.id)]


async def test_moderation_endpoints_are_admin_only_and_work(
    world: LinksWorld, api: Api
) -> None:
    """ADM-13, UF-ADM-10: queue, search, disable, dismiss."""
    ann, admin = world.person("Ann"), world.person("Root", Role.ADMIN)
    link = (
        await (await api(ann)).post(
            "/v1/links", json={"kind": "url", "target_url": "https://example.org/a"}
        )
    ).json()
    await (await api(None)).post(
        "/v1/public/reports", json={"slug": link["slug"], "reason": "malware"}
    )
    as_admin, as_student = await api(admin), await api(ann)

    forbidden = await as_student.get("/v1/admin/moderation/queue")
    queue = await as_admin.get("/v1/admin/moderation/queue")
    found = await as_admin.get(
        "/v1/admin/moderation/search", params={"q": link["slug"]}
    )
    disabled = await as_admin.post(
        f"/v1/admin/links/{link['id']}/disable", json={"reason": "malware"}
    )
    no_reason = await as_admin.post(
        f"/v1/admin/links/{link['id']}/disable", json={"reason": ""}
    )
    dismissed = await as_admin.post(f"/v1/admin/links/{link['id']}/dismiss-reports")

    assert forbidden.status_code == 403
    item = queue.json()["items"][0]
    assert set(item) == {
        "link",
        "owner",
        "reports",
        "last_reported_at",
        "disabled_reason",
    }
    assert item["reports"] == 1
    assert item["owner"]["first_name"] == "Ann"
    assert [i["link"]["id"] for i in found.json()] == [link["id"]]
    assert disabled.json()["link"]["disabled"] is True
    assert disabled.json()["disabled_reason"] == "malware"
    assert no_reason.status_code == 422
    assert dismissed.status_code == 200


async def test_room_resource_changes_are_visible_in_the_room_page(
    world: LinksWorld, api: Api
) -> None:
    """ROOM-8 end to end: add an attachment, the room page shows it."""
    teacher = world.person("Galina", Role.TEACHER)
    student = world.person("Aleksey")
    room = world.schedule.add_room("102", pin="483920")
    lesson = world.schedule.add_lesson(
        day=date(2026, 10, 6),
        teacher_id=teacher.user_id,
        room=room,
        students=[student.user_id],
    )
    anonymous = await api(None)
    assert (await anonymous.post("/r/102", data={"pin": "483920"})).status_code == 303
    before = await anonymous.get("/r/102")

    await (await api(student)).post(
        f"/v1/lessons/{lesson.id}/resources",
        json={
            "role": "attachment",
            "kind": "url",
            "target_url": "https://example.org/d",
        },
    )
    after = await anonymous.get("/r/102")

    assert "Aleksey - " not in before.text
    assert "Aleksey - " in after.text


async def test_artifact_share_is_public_and_revoked_is_404(
    world: LinksWorld, api: Api
) -> None:
    """A Studio output link is read without login; once revoked it is a 404."""
    ann = world.person("Ann")
    content = {"cards": [{"id": "1", "front": "hola", "back": "hello"}]}
    artifact = world.notebooks.add_artifact(ann.user_id, "flashcards", content)
    owner = await api(ann)
    share = (
        await owner.post(
            "/v1/shares", json={"kind": "artifact", "target_id": str(artifact)}
        )
    ).json()
    anonymous = await api(None)

    public = await anonymous.get(f"/v1/public/shares/{share['slug']}")

    assert share["slug"].startswith("a-")
    assert public.status_code == 200
    assert public.json()["kind"] == "artifact"
    assert public.json()["artifact"] == {
        "kind": "flashcards",
        "content": content,
        "options": {},
    }
    await owner.post(f"/v1/links/{share['id']}/revoke")
    revoked = await anonymous.get(f"/v1/public/shares/{share['slug']}")
    assert revoked.status_code == 404
