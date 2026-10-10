"""GET /v1/me/files filters: name, type, order and numbered paging (file picker)."""

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.files import ROUTERS
from app.shared.actor import Actor
from tests.conftest import HttpClientFactory
from tests.fakes.files.services import FilesFakes
from tests.files.helpers import PNG_BYTES, make_pdf, upload_ready

from httpx import AsyncClient


async def _seed(fakes: FilesFakes, actor: Actor) -> None:
    for index in range(8):
        fakes.clock.advance(minutes=1)
        await upload_ready(
            fakes,
            actor,
            name=f"notes-{index}.txt",
            data=b"text",
            content_type="text/plain",
        )
    fakes.clock.advance(minutes=1)
    await upload_ready(
        fakes,
        actor,
        name="Report.pdf",
        data=make_pdf("r"),
        content_type="application/pdf",
    )
    fakes.clock.advance(minutes=1)
    await upload_ready(
        fakes, actor, name="pic.png", data=PNG_BYTES, content_type="image/png"
    )


async def _client(
    http_client: HttpClientFactory, fakes: FilesFakes, actor: Actor
) -> AsyncClient:
    return await http_client(
        ROUTERS, overrides={get_actor: lambda: actor}, files=fakes.services
    )


async def test_filters_by_name_and_type(
    http_client: HttpClientFactory, fakes: FilesFakes, student: Actor
) -> None:
    """`q` is a case-insensitive substring; `type` keeps one family."""
    await _seed(fakes, student)
    client = await _client(http_client, fakes, student)

    by_name = (await client.get("/v1/me/files", params={"q": "REPORT"})).json()
    by_type = (await client.get("/v1/me/files", params={"type": "image"})).json()

    assert [i["name"] for i in by_name["items"]] == ["Report.pdf"]
    assert [i["name"] for i in by_type["items"]] == ["pic.png"]


async def test_sorts_and_pages_six_at_a_time(
    http_client: HttpClientFactory, fakes: FilesFakes, student: Actor
) -> None:
    """`sort=older` flips the order; `page`/`page_size` give numbered pages."""
    await _seed(fakes, student)
    client = await _client(http_client, fakes, student)
    params = {"page_size": 6}

    first = (await client.get("/v1/me/files", params={**params, "page": 1})).json()
    second = (await client.get("/v1/me/files", params={**params, "page": 2})).json()
    oldest = (
        await client.get("/v1/me/files", params={**params, "page": 1, "sort": "older"})
    ).json()

    assert len(first["items"]) == 6 and first["next_cursor"] == "2"
    assert first["items"][0]["name"] == "pic.png"
    assert len(second["items"]) == 4 and second["next_cursor"] is None
    assert oldest["items"][0]["name"] == "notes-0.txt"


def test_the_video_group_covers_the_allowed_video_types() -> None:
    """`type=video` matches mp4, webm and mov; an unknown group matches nothing."""
    from app.modules.files.domain.list_filters import content_types_of

    types = content_types_of("video")
    assert types is not None
    assert {"video/mp4", "video/webm", "video/quicktime"} <= set(types)
    assert content_types_of(None) is None
    assert content_types_of("nope") == ()
