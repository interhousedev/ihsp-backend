"""Profile photos over HTTP: Administration sets any user's, teachers set their own."""

from types import SimpleNamespace

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.admin_users import ROUTERS as ADMIN_ROUTERS
from app.interfaces.http.v1.me_photo import ROUTERS as ME_PHOTO_ROUTERS
from app.modules.identity.domain.photo import MAX_PHOTO_BYTES
from app.shared.actor import Actor, Role
from app.shared.base_error import UnauthorizedError
from app.shared.ids import new_id
from tests.conftest import HttpClientFactory
from tests.identity.http.conftest import Api
from tests.identity.support import World
from tests.identity.unit.test_user_photo import jpeg, png

import pytest
from httpx import Response


@pytest.fixture
async def photo_api(auth_world: World, http_client: HttpClientFactory) -> Api:
    """The Administration and the staff photo routers over the in-memory world."""
    holder: dict[str, Actor | None] = {"actor": None}

    def current_actor() -> Actor:
        actor = holder["actor"]
        if actor is None:
            raise UnauthorizedError(support_details="no test actor")
        return actor

    client = await http_client(
        [*ADMIN_ROUTERS, *ME_PHOTO_ROUTERS],
        {get_actor: current_actor},
        identity=SimpleNamespace(auth=auth_world.auth, token_verifier=None),
    )
    return Api(client=client, world=auth_world, holder=holder)


async def upload(
    api: Api,
    url: str,
    data: bytes,
    *,
    name: str = "me.png",
    declared: str = "image/png",
) -> Response:
    """PUT the data as a multipart ``file`` field."""
    return await api.client.put(url, files={"file": (name, data, declared)})


async def test_admin_sets_shows_and_removes_a_teachers_photo(photo_api: Api) -> None:
    api = photo_api
    await api.admin()
    teacher = await api.world.add_user(
        roles={Role.TEACHER}, login="t.eacher", recovery_email="t@example.org"
    )
    url = f"/v1/admin/users/{teacher.id}/photo"

    put = await upload(api, url, png())
    detail = await api.client.get(f"/v1/admin/users/{teacher.id}")
    listed = await api.client.get("/v1/admin/users", params={"query": "t.eacher"})
    teachers = await api.client.get("/v1/admin/teachers")
    deleted = await api.client.delete(url)
    deleted_again = await api.client.delete(url)
    after = await api.client.get(f"/v1/admin/users/{teacher.id}")

    assert put.status_code == 200
    link = put.json()["photo_url"]
    assert link and "inline" in link
    assert detail.json()["photo_url"] == listed.json()["items"][0]["photo_url"]
    assert teachers.json()["items"][0]["photo_url"] == detail.json()["photo_url"]
    assert deleted.status_code == deleted_again.status_code == 200
    assert deleted.json() == deleted_again.json() == {"photo_url": None}
    assert after.json()["photo_url"] is None
    assert api.world.user(teacher.id).photo_file_id is None


async def test_the_name_and_the_declared_type_do_not_matter(photo_api: Api) -> None:
    api = photo_api
    await api.admin()
    teacher = await api.world.add_user(roles={Role.TEACHER})
    url = f"/v1/admin/users/{teacher.id}/photo"

    jpeg_named_gif = await upload(api, url, jpeg(), name="x.gif", declared="image/gif")
    gif_named_png = await upload(api, url, b"GIF89a" + b"\x00" * 20)

    assert jpeg_named_gif.status_code == 200
    assert gif_named_png.status_code == 422
    assert gif_named_png.json()["type"] == "id/photo-type-not-allowed"
    assert api.world.user(teacher.id).photo_file_id is not None


async def test_a_photo_over_five_mebibytes_is_413_and_the_limit_itself_passes(
    photo_api: Api,
) -> None:
    api = photo_api
    await api.admin()
    teacher = await api.world.add_user(roles={Role.TEACHER})
    url = f"/v1/admin/users/{teacher.id}/photo"

    exact = await upload(api, url, png(MAX_PHOTO_BYTES))
    over = await upload(api, url, png(MAX_PHOTO_BYTES + 1))
    way_over = await upload(api, url, png(MAX_PHOTO_BYTES * 2))

    assert exact.status_code == 200
    assert over.status_code == way_over.status_code == 413
    assert over.json()["type"] == "id/photo-too-large"


async def test_an_empty_upload_is_422(photo_api: Api) -> None:
    api = photo_api
    await api.admin()
    teacher = await api.world.add_user(roles={Role.TEACHER})

    response = await upload(api, f"/v1/admin/users/{teacher.id}/photo", b"")

    assert response.status_code == 422
    assert response.json()["type"] == "id/photo-empty"


async def test_an_unknown_user_is_404(photo_api: Api) -> None:
    api = photo_api
    await api.admin()
    url = f"/v1/admin/users/{new_id()}/photo"

    put = await upload(api, url, png())
    delete = await api.client.delete(url)

    assert put.status_code == delete.status_code == 404
    assert put.json()["type"] == "id/user-not-found"


async def test_only_administration_sets_another_users_photo(photo_api: Api) -> None:
    api = photo_api
    teacher = await api.world.add_user(roles={Role.TEACHER})
    url = f"/v1/admin/users/{teacher.id}/photo"

    anonymous = await upload(api, url, png())
    api.login_as(teacher)
    own_teacher = await upload(api, url, png())
    deleted = await api.client.delete(url)

    assert anonymous.status_code == 401
    assert own_teacher.status_code == deleted.status_code == 403
    assert api.world.user(teacher.id).photo_file_id is None


async def test_a_teacher_sets_and_removes_their_own_photo(photo_api: Api) -> None:
    api = photo_api
    teacher = await api.world.add_user(roles={Role.TEACHER})
    other = await api.world.add_user(
        roles={Role.TEACHER}, login="o.ther", recovery_email="o@example.org"
    )
    api.login_as(teacher)

    put = await upload(api, "/v1/staff/me/photo", jpeg(), name="a.jpg")
    replaced = await upload(api, "/v1/staff/me/photo", png())
    stored = api.world.user(teacher.id).photo_file_id
    deleted = await api.client.delete("/v1/staff/me/photo")

    assert put.status_code == replaced.status_code == 200
    assert put.json()["photo_url"] and replaced.json()["photo_url"]
    assert stored is not None
    assert deleted.status_code == 200 and deleted.json() == {"photo_url": None}
    assert api.world.user(teacher.id).photo_file_id is None
    assert api.world.user(other.id).photo_file_id is None


async def test_the_staff_photo_routes_are_for_teachers_only(photo_api: Api) -> None:
    api = photo_api
    student = await api.world.add_user()

    anonymous = await upload(api, "/v1/staff/me/photo", png())
    api.login_as(student)
    put = await upload(api, "/v1/staff/me/photo", png())
    delete = await api.client.delete("/v1/staff/me/photo")

    assert anonymous.status_code == 401
    assert put.status_code == delete.status_code == 403
    assert api.world.user(student.id).photo_file_id is None


async def test_the_staff_route_refuses_what_the_admin_route_refuses(
    photo_api: Api,
) -> None:
    api = photo_api
    teacher = await api.world.add_user(roles={Role.TEACHER})
    api.login_as(teacher)

    text = await upload(api, "/v1/staff/me/photo", b"hello")
    big = await upload(api, "/v1/staff/me/photo", jpeg(MAX_PHOTO_BYTES + 1))

    assert text.status_code == 422 and big.status_code == 413
