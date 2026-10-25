"""PWA-3: GET /v1/app/version tells the installed app which release is current."""

from app.interfaces.http.v1.app_version import ROUTERS
from app.settings import AppSettings, Settings
from tests.conftest import HttpClientFactory

from httpx import AsyncClient

APP_ORIGIN = "http://localhost:3007"


async def version_client(
    http_client: HttpClientFactory, settings: Settings, **versions: str
) -> AsyncClient:
    """A client of the version route with the given release numbers configured."""
    configured = settings.model_copy(update={"app": AppSettings(**versions)})
    return await http_client(ROUTERS, settings=configured)


async def test_the_default_versions_are_1_0_0(
    http_client: HttpClientFactory, settings: Settings
) -> None:
    """PWA-3: a fresh deployment reports 1.0.0 for both numbers."""
    client = await version_client(http_client, settings)

    response = await client.get("/v1/app/version")

    assert response.status_code == 200
    assert response.json() == {"latest": "1.0.0", "min_supported": "1.0.0"}


async def test_the_versions_come_from_the_settings(
    http_client: HttpClientFactory, settings: Settings
) -> None:
    """PWA-3: IHSP_APP__LATEST and IHSP_APP__MIN_SUPPORTED are what the app reads."""
    client = await version_client(
        http_client, settings, latest="1.10.2", min_supported="1.9"
    )

    response = await client.get("/v1/app/version")

    assert response.json() == {"latest": "1.10.2", "min_supported": "1.9"}


async def test_the_answer_is_never_stored(
    http_client: HttpClientFactory, settings: Settings
) -> None:
    """PWA-3: the client and the service worker always see the current values."""
    client = await version_client(http_client, settings)

    response = await client.get("/v1/app/version")

    assert response.headers["cache-control"] == "no-store"


async def test_no_authorization_header_is_needed(
    http_client: HttpClientFactory, settings: Settings
) -> None:
    """PWA-3: the check runs before sign-in, so the route is public.

    The test container has no identity module, so any authentication dependency
    would answer 401.
    """
    client = await version_client(http_client, settings)

    anonymous = await client.get("/v1/app/version")
    bogus = await client.get(
        "/v1/app/version", headers={"Authorization": "Bearer not-a-token"}
    )

    assert anonymous.status_code == 200
    assert bogus.status_code == 200


async def test_the_app_origin_may_read_it(
    http_client: HttpClientFactory, settings: Settings
) -> None:
    """PWA-1, PWA-3: app.<domain> reads the route across origins."""
    client = await version_client(http_client, settings)

    response = await client.get("/v1/app/version", headers={"Origin": APP_ORIGIN})

    assert response.headers["access-control-allow-origin"] == APP_ORIGIN


async def test_only_get_is_allowed(
    http_client: HttpClientFactory, settings: Settings
) -> None:
    """PWA-3: the route reads configuration and changes nothing."""
    client = await version_client(http_client, settings)

    response = await client.post("/v1/app/version")

    assert response.status_code == 405


async def test_the_route_is_documented_as_app_version(
    http_client: HttpClientFactory, settings: Settings
) -> None:
    """PWA-3: the OpenAPI contract names both fields as required strings."""
    client = await version_client(http_client, settings)

    body = (await client.get("/openapi.json")).json()

    operation = body["paths"]["/v1/app/version"]["get"]
    assert operation["tags"] == ["app"]
    ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    schema = body["components"]["schemas"][ref.rsplit("/", 1)[-1]]
    assert schema["required"] == ["latest", "min_supported"]
    assert {k: v["type"] for k, v in schema["properties"].items()} == {
        "latest": "string",
        "min_supported": "string",
    }
