"""LIB-12: the honest HTTP client; metadata only, no workarounds."""

import asyncio

from app.modules.library.infrastructure.unilibrary.client import UniLibraryClient
from app.modules.library.infrastructure.unilibrary.errors import UpstreamError
from app.modules.library.infrastructure.unilibrary.factory import UniLibraryStack
from tests.library.external.conftest import DETAIL_PATH, LIST_PATH
from tests.library.external.support import load

import httpx
import pytest
import respx

AGENT = "IHSP-library/1.0 (+https://ihsu.uz; contact: library@ihsu.uz)"


@pytest.fixture
def client(stack: UniLibraryStack) -> UniLibraryClient:
    """The client of the built stack."""
    return stack.client


async def test_list_asks_the_with_media_endpoint_with_the_query(
    client: UniLibraryClient, upstream: respx.MockRouter
) -> None:
    """LIB-12: the guest list with media, the mapped filters as the query."""
    route = upstream.get(LIST_PATH).respond(200, json=load("list_page"))

    payload = await client.list_resources({"page": 2, "name": "fizika"})

    assert payload == load("list_page")
    request = route.calls.last.request
    assert request.url.params["page"] == "2"
    assert request.url.params["name"] == "fizika"


async def test_requests_say_who_we_are_and_pose_as_no_browser(
    client: UniLibraryClient, upstream: respx.MockRouter
) -> None:
    """LIB-12 / doc 3.3: own User-Agent; never `Origin` or `Referer`."""
    route = upstream.get(LIST_PATH).respond(200, json=load("list_page"))

    await client.list_resources({"page": 1})

    headers = route.calls.last.request.headers
    assert headers["user-agent"] == AGENT
    assert headers["accept"] == "application/json"
    assert "origin" not in headers
    assert "referer" not in headers


async def test_a_403_is_a_failure_and_is_not_retried(
    client: UniLibraryClient, upstream: respx.MockRouter
) -> None:
    """LIB-12 / doc 1.2: a 403 is never worked around."""
    route = upstream.get(LIST_PATH).respond(
        403, json={"message": "Access denied: unauthorized"}
    )

    with pytest.raises(UpstreamError) as caught:
        await client.list_resources({"page": 1})

    assert caught.value.kind == "forbidden"
    assert caught.value.status == 403
    assert route.call_count == 1


async def test_retry_after_of_a_429_is_carried_in_the_error(
    client: UniLibraryClient, upstream: respx.MockRouter
) -> None:
    """LIB-12: the source says when to come back."""
    upstream.get(LIST_PATH).respond(429, headers={"Retry-After": "30"})

    with pytest.raises(UpstreamError) as caught:
        await client.list_resources({"page": 1})

    assert caught.value.kind == "rate_limited"
    assert caught.value.retry_after == 30


async def test_retry_after_may_come_with_a_503(
    client: UniLibraryClient, upstream: respx.MockRouter
) -> None:
    """LIB-12: an overloaded source asks for a pause the same way."""
    upstream.get(LIST_PATH).respond(503, headers={"Retry-After": "120"})

    with pytest.raises(UpstreamError) as caught:
        await client.list_resources({"page": 1})

    assert caught.value.kind == "server"
    assert caught.value.retry_after == 120


@pytest.mark.parametrize(
    ("status", "kind"), [(500, "server"), (502, "server"), (422, "bad_status")]
)
async def test_other_error_statuses_are_failures(
    client: UniLibraryClient, upstream: respx.MockRouter, status: int, kind: str
) -> None:
    """LIB-12: anything but a good answer counts against the source."""
    upstream.get(LIST_PATH).respond(status)

    with pytest.raises(UpstreamError) as caught:
        await client.list_resources({"page": 1})

    assert caught.value.kind == kind


async def test_a_body_that_is_not_json_is_a_failure(
    client: UniLibraryClient, upstream: respx.MockRouter
) -> None:
    """LIB-12: an HTML error page behind a 200 is not data."""
    upstream.get(LIST_PATH).respond(200, text="<html>maintenance</html>")

    with pytest.raises(UpstreamError) as caught:
        await client.list_resources({"page": 1})

    assert caught.value.kind == "bad_payload"


@pytest.mark.parametrize(
    "error", [httpx.ReadTimeout("slow"), httpx.ConnectTimeout("slow")]
)
async def test_httpx_timeouts_are_timeout_failures(
    client: UniLibraryClient, upstream: respx.MockRouter, error: Exception
) -> None:
    """LIB-12: timeouts count as failures."""
    upstream.get(LIST_PATH).mock(side_effect=error)

    with pytest.raises(UpstreamError) as caught:
        await client.list_resources({"page": 1})

    assert caught.value.kind == "timeout"


async def test_connection_errors_are_network_failures(
    client: UniLibraryClient, upstream: respx.MockRouter
) -> None:
    """LIB-12: refused or reset connections are failures too."""
    upstream.get(LIST_PATH).mock(side_effect=httpx.ConnectError("refused"))

    with pytest.raises(UpstreamError) as caught:
        await client.list_resources({"page": 1})

    assert caught.value.kind == "network"


async def test_the_list_gives_up_after_its_own_deadline(
    stack: UniLibraryStack, upstream: respx.MockRouter
) -> None:
    """LIB-12: 8 s for a list (here 0.05 s so the test is quick)."""

    async def slow(_request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(1)
        return httpx.Response(200, json=load("list_page"))

    upstream.get(LIST_PATH).mock(side_effect=slow)
    stack.client.list_timeout = 0.05

    with pytest.raises(UpstreamError) as caught:
        await stack.client.list_resources({"page": 1})

    assert caught.value.kind == "timeout"


async def test_detail_asks_the_record_in_the_language(
    client: UniLibraryClient, upstream: respx.MockRouter
) -> None:
    """LIB-12: `guest-publisher-resources/{id}?language=`."""
    route = upstream.get(f"{DETAIL_PATH}/355186").respond(200, json=load("detail"))

    payload = await client.resource("355186", "ru")

    assert payload == load("detail")
    assert route.calls.last.request.url.params["language"] == "ru"


async def test_detail_of_an_empty_result_is_passed_on(
    client: UniLibraryClient, upstream: respx.MockRouter
) -> None:
    """LIB-12: a missing id is `200 {"result": []}`; the mapper reads it."""
    upstream.get(f"{DETAIL_PATH}/1").respond(200, json=load("detail_empty"))

    assert await client.resource("1", "uz") == {"result": []}


async def test_detail_404_is_a_missing_record_not_a_failure(
    client: UniLibraryClient, upstream: respx.MockRouter
) -> None:
    """LIB-12: the record is gone."""
    upstream.get(f"{DETAIL_PATH}/1").respond(404)

    assert await client.resource("1", "uz") is None


@pytest.mark.parametrize("bad_id", ["../storage", "12/file", "abc", "", "1 2", "٣"])
async def test_an_id_that_is_not_digits_never_reaches_the_network(
    client: UniLibraryClient, upstream: respx.MockRouter, bad_id: str
) -> None:
    """LIB-12: the path comes from a user; only plain digits are a record id."""
    assert await client.resource(bad_id, "uz") is None

    assert upstream.calls.call_count == 0


@pytest.mark.parametrize(
    "name", ["resource-types", "resource-fields", "resource-languages"]
)
async def test_taxonomies_use_the_crm_lists_endpoints(
    client: UniLibraryClient, upstream: respx.MockRouter, name: str
) -> None:
    """LIB-12: `crm/{name}/lists`."""
    route = upstream.get(f"/api/crm/{name}/lists").respond(200, json={"result": []})

    await client.taxonomy(name)  # type: ignore[arg-type]

    assert route.call_count == 1


async def test_every_call_is_logged_for_the_status_page(
    stack: UniLibraryStack, upstream: respx.MockRouter
) -> None:
    """LIB-12: path, outcome and time of the last calls."""
    upstream.get(LIST_PATH).respond(200, json=load("list_page"))
    upstream.get(f"{DETAIL_PATH}/9").respond(500)

    await stack.client.list_resources({"page": 1})
    with pytest.raises(UpstreamError):
        await stack.client.resource("9", "uz")

    calls = await stack.monitor.last_calls(10)
    assert [(c.ok, c.path) for c in calls] == [
        (False, f"{DETAIL_PATH}/9"),
        (True, LIST_PATH),
    ]
    assert all(call.ms >= 0 for call in calls)
