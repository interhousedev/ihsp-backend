"""Gemini's per-user redirect URIs are added to Gemini clients, and nothing else."""

from types import SimpleNamespace
from typing import Any

from app.modules.identity.application.sync_gemini_redirect import (
    MAX_REDIRECTS_PER_CLIENT,
    SyncGeminiRedirect,
)

import pytest

GEMINI = (
    "https://oauth-redirect.googleusercontent.com/r/"
    "user_bound_custom-mcp-101341883812643068641-mcp_ihsu_uz"
)


class Hydra:
    def __init__(self, service: str = "gemini", uris: list[str] | None = None) -> None:
        self.client = SimpleNamespace(
            metadata={"service": service}, redirect_uris=uris or []
        )
        self.saved: list[str] | None = None

    async def get_client(self, client_id: str) -> Any:
        return None if client_id == "missing" else self.client

    async def set_client_redirects(self, client_id: str, uris: list[str]) -> None:
        self.saved = uris


def _sync(hydra: Hydra) -> SyncGeminiRedirect:
    return SyncGeminiRedirect(hydra)  # type: ignore[arg-type]


async def test_the_generated_uri_is_added_to_a_gemini_client() -> None:
    hydra = Hydra(uris=["https://vertexaisearch.cloud.google.com/oauth-redirect"])

    assert await _sync(hydra).execute("id", GEMINI)

    assert hydra.saved == [*hydra.client.redirect_uris, GEMINI]


@pytest.mark.parametrize(
    ("client_id", "service", "uri"),
    [
        ("id", "gemini", "https://evil.example/r/x"),
        ("id", "gemini", "https://oauth-redirect.googleusercontent.com/x/y"),
        ("id", "gemini", "http://127.0.0.1:7777/oauth/callback"),
        ("id", "chatgpt", GEMINI),
        ("missing", "gemini", GEMINI),
    ],
)
async def test_anything_else_is_left_alone(
    client_id: str, service: str, uri: str
) -> None:
    hydra = Hydra(service=service)

    assert not await _sync(hydra).execute(client_id, uri)

    assert hydra.saved is None


async def test_a_known_uri_and_a_full_client_are_not_written() -> None:
    known = Hydra(uris=[GEMINI])
    full = Hydra(uris=[f"u{n}" for n in range(MAX_REDIRECTS_PER_CLIENT)])

    assert not await _sync(known).execute("id", GEMINI)
    assert not await _sync(full).execute("id", GEMINI)
    assert known.saved is None and full.saved is None
