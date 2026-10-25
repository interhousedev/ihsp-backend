"""The real client address: X-Forwarded-For counts only from a trusted proxy."""

from types import SimpleNamespace
from typing import Annotated

from app.interfaces.http.dependencies import get_client_ip
from app.settings import HttpSettings
from app.shared.client_ip import client_address, parse_trusted_proxies

import httpx
import pytest
from fastapi import Depends, FastAPI
from pydantic import ValidationError

EDGE = "172.31.240.10"


def make_app(trusted: str) -> FastAPI:
    app = FastAPI()
    settings = SimpleNamespace(http=HttpSettings(trusted_proxies=trusted))
    app.state.container = SimpleNamespace(settings=settings)

    @app.get("/ip")
    async def report(
        ip: Annotated[str | None, Depends(get_client_ip)],
    ) -> dict[str, str | None]:
        return {"ip": ip}

    return app


async def ask(app: FastAPI, peer: str, forwarded_for: str | None) -> str | None:
    headers = {"X-Forwarded-For": forwarded_for} if forwarded_for else {}
    transport = httpx.ASGITransport(app=app, client=(peer, 40000))
    async with httpx.AsyncClient(transport=transport, base_url="http://api") as http:
        response = await http.get("/ip", headers=headers)
    return response.json()["ip"]


async def test_forwarded_for_is_ignored_when_no_proxy_is_trusted() -> None:
    app = make_app("")
    assert await ask(app, EDGE, "203.0.113.7") == EDGE


async def test_forwarded_for_from_the_trusted_proxy_gives_the_client() -> None:
    app = make_app(EDGE)
    assert await ask(app, EDGE, "203.0.113.7") == "203.0.113.7"


async def test_forwarded_for_from_an_untrusted_peer_is_a_spoof() -> None:
    app = make_app(EDGE)
    assert await ask(app, "198.51.100.4", "10.0.0.1") == "198.51.100.4"


async def test_trusted_network_skips_its_own_hops_from_the_right() -> None:
    app = make_app("172.16.0.0/12")
    assert await ask(app, "172.18.0.5", "203.0.113.7, 172.18.0.2") == "203.0.113.7"


async def test_garbage_forwarded_for_from_a_trusted_proxy_falls_back_to_peer() -> None:
    app = make_app(EDGE)
    assert await ask(app, EDGE, "not-an-address") == EDGE


async def test_missing_client_address_is_none() -> None:
    app = make_app(EDGE)
    transport = httpx.ASGITransport(app=app, client=None)  # type: ignore[arg-type]
    async with httpx.AsyncClient(transport=transport, base_url="http://api") as http:
        response = await http.get("/ip")
    assert response.json()["ip"] is None


@pytest.mark.parametrize(
    ("peer", "forwarded", "expected"),
    [
        ("10.1.2.3", "8.8.8.8", "10.1.2.3"),  # no trusted peer
        (EDGE, None, EDGE),  # trusted peer, no header
        (EDGE, "8.8.8.8", "8.8.8.8"),
        (EDGE, "8.8.8.8, 172.31.240.10", "8.8.8.8"),
        (EDGE, "   ", EDGE),
        (None, "8.8.8.8", None),
    ],
)
def test_client_address_rules(
    peer: str | None, forwarded: str | None, expected: str | None
) -> None:
    trusted = parse_trusted_proxies(EDGE)
    assert client_address(peer, forwarded, trusted) == expected


def test_trusted_proxy_list_accepts_ips_and_cidrs() -> None:
    networks = parse_trusted_proxies("172.31.240.10, 10.0.0.0/8 ,")
    assert [str(n) for n in networks] == ["172.31.240.10/32", "10.0.0.0/8"]


@pytest.mark.parametrize("value", ["*", "edge", "10.0.0.0/33"])
def test_settings_refuse_wildcards_and_garbage(value: str) -> None:
    with pytest.raises(ValidationError):
        HttpSettings(trusted_proxies=value)
