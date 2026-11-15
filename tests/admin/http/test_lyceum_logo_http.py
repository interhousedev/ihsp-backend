"""Lyceum logo: PUT/DELETE /v1/admin/settings/lyceum-logo and the public reads."""

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.admin_settings import ROUTERS as ADMIN_ROUTERS
from app.interfaces.http.v1.public_config import ROUTERS as PUBLIC_ROUTERS
from tests.admin.conftest import Stack
from tests.conftest import HttpClientFactory

import pytest
from httpx import AsyncClient

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
URL = "/v1/admin/settings/lyceum-logo"


@pytest.fixture
async def client(stack: Stack, http_client: HttpClientFactory) -> AsyncClient:
    return await http_client(
        [*ADMIN_ROUTERS, *PUBLIC_ROUTERS],
        overrides={get_actor: lambda: stack.actor},
        admin=stack.admin,
    )


def _file(data: bytes, content_type: str = "image/png") -> dict[str, tuple]:
    return {"file": ("logo", data, content_type)}


async def test_upload_shows_in_client_config_and_streams(client: AsyncClient) -> None:
    put = await client.put(URL, files=_file(PNG))

    assert put.status_code == 200
    url = put.json()["lyceum_logo_url"]
    assert url.startswith("/v1/public/lyceum-logo?v=")
    config = (await client.get("/v1/public/client-config")).json()
    assert config["branding"] == {"lyceum_logo_url": url}
    assert (await client.get("/v1/admin/settings")).json()["lyceum_logo_url"] == url
    image = await client.get(url)
    assert image.status_code == 200
    assert image.content == PNG
    assert image.headers["content-type"] == "image/png"
    assert image.headers["cache-control"] == "public, max-age=86400, immutable"
    again = await client.get(url, headers={"If-None-Match": image.headers["etag"]})
    assert again.status_code == 304


async def test_declared_type_is_not_trusted(client: AsyncClient) -> None:
    response = await client.put(URL, files=_file(b"<svg/>", "image/png"))

    assert response.status_code == 422
    assert response.json()["type"] == "admin/logo-type-not-allowed"


async def test_oversized_logo_is_refused(client: AsyncClient) -> None:
    response = await client.put(URL, files=_file(PNG + b"\x00" * (1024 * 1024)))

    assert response.status_code == 413
    assert response.json()["type"] == "admin/logo-too-large"


async def test_delete_clears_the_logo_and_the_object(
    client: AsyncClient, stack: Stack
) -> None:
    await client.put(URL, files=_file(PNG))
    assert len(stack.storage.objects) == 1

    deleted = await client.delete(URL)

    assert deleted.status_code == 200
    assert deleted.json()["lyceum_logo_url"] is None
    assert not stack.storage.objects
    config = (await client.get("/v1/public/client-config")).json()
    assert config["branding"] == {"lyceum_logo_url": None}
    missing = await client.get("/v1/public/lyceum-logo")
    assert missing.status_code == 404
    assert missing.json()["type"] == "admin/logo-not-found"


async def test_replacing_removes_the_old_object(
    client: AsyncClient, stack: Stack
) -> None:
    await client.put(URL, files=_file(PNG))
    await client.put(URL, files=_file(PNG + b"1"))

    assert len(stack.storage.objects) == 1
