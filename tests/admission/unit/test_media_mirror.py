"""Mirroring external logos into storage with a fake HTTP transport and store."""

import hashlib
from collections.abc import Awaitable, Callable

from app.modules.admission.application.media_mirroring import mirror_media
from app.modules.admission.domain.errors import MediaUnreachableError
from app.modules.admission.infrastructure.media_mirror import (
    MAX_BYTES,
    HttpS3MediaMirror,
)

import httpx
import pytest

PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 20
BASE = "https://files.example/bucket"


async def _public(_host: str) -> list[str]:
    return ["93.184.216.34"]


def _mirror(
    handler: Callable[[httpx.Request], httpx.Response],
    resolve: Callable[[str], Awaitable[list[str]]] = _public,
) -> tuple[HttpS3MediaMirror, dict[str, tuple[bytes, str]]]:
    stored: dict[str, tuple[bytes, str]] = {}

    async def put(key: str, data: bytes, ct: str) -> None:
        stored[key] = (data, ct)

    m = HttpS3MediaMirror(
        put, BASE, transport=httpx.MockTransport(handler), resolve=resolve
    )
    return m, stored


async def test_mirrors_png_by_hash_and_sends_no_origin() -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, content=PNG)

    m, stored = _mirror(handler)
    url = await m.mirror("https://upload.wikimedia.org/a.png")
    key = f"admission/org-media/{hashlib.sha256(PNG).hexdigest()}.png"
    assert url == f"{BASE}/{key}"
    assert stored[key] == (PNG, "image/png")
    assert "origin" not in seen[0].headers and "referer" not in seen[0].headers
    assert seen[0].headers["user-agent"].startswith("IHT-")
    assert await m.mirror(url) == url


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(404),
        httpx.Response(200, content=b"<svg xmlns='http://www.w3.org/2000/svg'/>"),
        httpx.Response(200, content=b"x" * (MAX_BYTES + 1)),
    ],
)
async def test_rejects_bad_responses(response: httpx.Response) -> None:
    m, stored = _mirror(lambda _r: response)
    with pytest.raises(MediaUnreachableError):
        await m.mirror("https://example.com/a.png")
    assert not stored


async def test_rejects_private_host_and_http() -> None:
    async def private(_h: str) -> list[str]:
        return ["10.0.0.5"]

    m, _ = _mirror(lambda _r: httpx.Response(200, content=PNG), private)
    with pytest.raises(MediaUnreachableError):
        await m.mirror("https://internal.example/a.png")
    m2, _ = _mirror(lambda _r: httpx.Response(200, content=PNG))
    with pytest.raises(MediaUnreachableError):
        await m2.mirror("http://example.com/a.png")


async def test_follows_redirect_and_mirror_media_helper() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/old.png":
            return httpx.Response(302, headers={"location": "/new.png"})
        return httpx.Response(200, content=PNG)

    m, stored = _mirror(handler)
    out = await mirror_media(
        m, {"logo_url": "https://e.com/old.png", "name": "X"}, ("logo_url", "cover_url")
    )
    assert out["logo_url"].startswith(BASE) and out["name"] == "X"
    assert len(stored) == 1
    same = {"logo_url": "https://e.com/old.png"}
    assert await mirror_media(None, same, ("logo_url",)) == same
