"""HTTP: default materials of subjects under /v1/admin/subject-materials (admins)."""

from collections.abc import Callable

from app.shared.actor import Actor, Role
from app.shared.ids import new_id
from tests.fakes.ai.contracts import make_file
from tests.fakes.notebooks.world import World
from tests.notebooks.unit.auto.conftest import PAGE

import pytest
from httpx import AsyncClient, Response

BASE = "/v1/admin/subject-materials"


def problem_type(response: Response) -> str:
    """The `type` of a problem+json response."""
    assert response.headers["content-type"].startswith("application/problem+json")
    return str(response.json()["type"])


@pytest.fixture
def admin(make_actor: Callable[..., Actor]) -> Actor:
    """An administrator."""
    return make_actor(Role.ADMIN)


async def test_only_an_admin_reaches_the_routes(api: AsyncClient) -> None:
    """A student (the default caller of the fixture) gets 403 on every route."""
    assert (await api.get(BASE)).status_code == 403
    assert (await api.get(f"{BASE}/101")).status_code == 403
    assert (await api.post(f"{BASE}/101", json={})).status_code == 403
    assert (await api.delete(f"{BASE}/101/{new_id()}")).status_code == 403


async def test_a_link_is_added_listed_and_grouped(
    api: AsyncClient, current: dict[str, Actor], admin: Actor
) -> None:
    """The admin's link is stored under its EMIS id and shows in both lists."""
    current["actor"] = admin

    created = await api.post(
        f"{BASE}/101",
        json={"kind": "link", "title": "Khan", "url": "https://khan.org/physics"},
    )
    listed = await api.get(f"{BASE}/101")
    grouped = await api.get(BASE)

    assert created.status_code == 201, created.text
    body = created.json()
    assert body["edu_subject_id"] == 101
    assert body["kind"] == "link"
    assert body["url"] == "https://khan.org/physics"
    assert body["file_id"] is None and body["library_item_id"] is None
    assert listed.json() == [body]
    assert grouped.json() == [{"edu_subject_id": 101, "materials": [body]}]


async def test_a_file_must_be_the_admins_own_upload(
    api: AsyncClient,
    current: dict[str, Actor],
    admin: Actor,
    student: Actor,
    world: World,
) -> None:
    """A file of a student is refused; the admin's own file is accepted."""
    current["actor"] = admin
    own = world.files.add_text(make_file(admin.user_id, name="Guide.pdf"), PAGE)
    theirs = world.files.add_text(make_file(student.user_id, name="mine.pdf"), PAGE)

    refused = await api.post(
        f"{BASE}/101", json={"kind": "file", "title": "Mine", "file_id": str(theirs.id)}
    )
    accepted = await api.post(
        f"{BASE}/101", json={"kind": "file", "title": "Guide", "file_id": str(own.id)}
    )

    assert refused.status_code == 422, refused.text
    assert problem_type(refused) == "notebooks/default-material-invalid"
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["file_id"] == str(own.id)


async def test_a_body_with_another_target_than_its_kind_is_unprocessable(
    api: AsyncClient, current: dict[str, Actor], admin: Actor
) -> None:
    """Exactly the target of the kind: a link with a file id fails the schema."""
    current["actor"] = admin

    response = await api.post(
        f"{BASE}/101",
        json={"kind": "link", "title": "x", "file_id": str(new_id())},
    )

    assert response.status_code == 422


async def test_a_repeat_is_a_conflict_and_removal_is_no_content(
    api: AsyncClient, current: dict[str, Actor], admin: Actor
) -> None:
    """The same link twice is a 409; removing it is 204, then it is not found."""
    current["actor"] = admin
    link = {"kind": "link", "title": "Khan", "url": "https://khan.org/physics"}
    created = await api.post(f"{BASE}/101", json=link)
    again = await api.post(f"{BASE}/101", json=link)

    removed = await api.delete(f"{BASE}/101/{created.json()['id']}")
    gone = await api.delete(f"{BASE}/101/{created.json()['id']}")

    assert problem_type(again) == "notebooks/default-material-exists"
    assert again.status_code == 409
    assert removed.status_code == 204
    assert gone.status_code == 404
    assert problem_type(gone) == "notebooks/default-material-not-found"
    assert (await api.get(f"{BASE}/101")).json() == []
