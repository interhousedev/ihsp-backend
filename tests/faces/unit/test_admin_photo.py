"""GET /v1/admin/users/{id}/face-photo: admin only, 404 without a face."""

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.faces import router
from app.shared.actor import Actor
from app.shared.ids import new_id
from tests.conftest import HttpClientFactory
from tests.faces.conftest import FacesHarness, photo

from httpx import AsyncClient


async def client_as(
    http_client: HttpClientFactory, fh: FacesHarness, actor: Actor
) -> AsyncClient:
    """A client authenticated as the actor over the faces routes."""
    return await http_client(
        [router], overrides={get_actor: lambda: actor}, faces=fh.services
    )


async def test_admin_gets_face_photo(
    fh: FacesHarness, http_client: HttpClientFactory
) -> None:
    info = fh.directory.add_student("Ali Karimov")
    await fh.services.upload_my_face.execute(info.user_id, photo("a"))
    client = await client_as(http_client, fh, fh.admin)

    response = await client.get(f"/v1/admin/users/{info.user_id}/face-photo")

    assert response.status_code == 200
    assert response.json()["photo_url"].startswith("https://s3.test/")


async def test_teacher_is_forbidden(
    fh: FacesHarness, http_client: HttpClientFactory
) -> None:
    info = fh.directory.add_student("Ali Karimov")
    await fh.services.upload_my_face.execute(info.user_id, photo("a"))
    client = await client_as(http_client, fh, fh.curator)

    response = await client.get(f"/v1/admin/users/{info.user_id}/face-photo")

    assert response.status_code == 403


async def test_missing_face_is_404(
    fh: FacesHarness, http_client: HttpClientFactory
) -> None:
    client = await client_as(http_client, fh, fh.admin)

    response = await client.get(f"/v1/admin/users/{new_id()}/face-photo")

    assert response.status_code == 404
