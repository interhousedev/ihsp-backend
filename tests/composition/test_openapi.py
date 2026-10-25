"""The OpenAPI schema lists the composition routes of the API contract."""

from typing import Any

from app.interfaces.http.public.ical import ROUTERS as ICAL_ROUTERS
from app.interfaces.http.v1.composition import ROUTERS
from tests.conftest import HttpClientFactory

CONTRACT = {
    ("get", "/v1/me/alerts"),
    ("get", "/v1/me/search"),
    ("post", "/v1/me/calendar-token"),
    ("get", "/ical/{token}.ics"),
    ("get", "/v1/admin/dashboard"),
    ("get", "/v1/admin/groups/stats"),
    ("get", "/v1/admin/students/{user_id}"),
    ("get", "/v1/admin/teachers/{user_id}/profile"),
}


async def schema(http_client: HttpClientFactory) -> dict[str, Any]:
    client = await http_client([*ROUTERS, *ICAL_ROUTERS])
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


async def test_every_route_of_the_contract_is_published(
    http_client: HttpClientFactory,
) -> None:
    """§ API contract -> Composition (I2): paths and methods."""
    body = await schema(http_client)

    published = {
        (method, path) for path, ops in body["paths"].items() for method in ops
    }
    assert published == CONTRACT


async def test_the_feed_is_documented_as_a_calendar(
    http_client: HttpClientFactory,
) -> None:
    """GET /ical/{token}.ics answers text/calendar."""
    body = await schema(http_client)

    content = body["paths"]["/ical/{token}.ics"]["get"]["responses"]["200"]["content"]

    assert list(content) == ["text/calendar"]


async def test_student_attendance_is_published_with_from_and_to(
    http_client: HttpClientFactory,
) -> None:
    """Student360.attendance uses the JSON names `from` and `to`."""
    body = await schema(http_client)

    schemas = body["components"]["schemas"]
    attendance = next(v for k, v in schemas.items() if "StudentAttendance" in k)

    assert {"from", "to"} <= set(attendance["properties"])
