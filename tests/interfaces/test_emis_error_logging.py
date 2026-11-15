"""Upstream EMIS trouble is logged at warning and answers 503 with Retry-After."""

from app.interfaces.http.errors import install_error_handlers
from app.shared.base_error import BaseError
from app.shared.contracts.emis import EmisPaused, EmisUnavailable

import httpx
import pytest
from fastapi import FastAPI
from structlog.testing import capture_logs


class Broken(BaseError):
    """A genuine server-side defect."""

    code = "common/broken"
    status = 500
    message_key = "broken"


def _client(error: BaseError) -> httpx.AsyncClient:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/boom")
    async def boom() -> None:
        raise error

    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def test_emis_unavailable_is_a_warning_with_retry_after() -> None:
    """No error-level event; problem type and Retry-After stay."""
    async with _client(EmisUnavailable()) as client:
        with capture_logs() as logs:
            response = await client.get("/boom")

    assert response.status_code == 503
    assert response.json()["type"] == "emis/unavailable"
    assert response.headers["Retry-After"] == "30"
    entry = next(item for item in logs if item["event"] == "domain_error")
    assert entry["log_level"] == "warning"


async def test_emis_paused_uses_its_own_retry_after() -> None:
    """The seconds EMIS asked for are passed on."""
    async with _client(EmisPaused(retry_after=61.2)) as client:
        response = await client.get("/boom")

    assert response.headers["Retry-After"] == "62"


@pytest.mark.parametrize("level", ["error"])
async def test_other_server_errors_stay_errors(level: str) -> None:
    """A real 5xx domain error is still error level."""
    async with _client(Broken()) as client:
        with capture_logs() as logs:
            response = await client.get("/boom")

    assert response.status_code == 500
    assert "Retry-After" not in response.headers
    entry = next(item for item in logs if item["event"] == "domain_error")
    assert entry["log_level"] == level


async def test_emis_file_not_found_is_a_quiet_404() -> None:
    """A gone material is a client-side 404 at info level, no Retry-After."""
    from app.shared.contracts.emis import EmisFileNotFound

    async with _client(EmisFileNotFound()) as client:
        with capture_logs() as logs:
            response = await client.get("/boom")

    assert response.status_code == 404
    assert response.json()["type"] == "emis/file-not-found"
    assert "Retry-After" not in response.headers
    entry = next(item for item in logs if item["event"] == "domain_error")
    assert entry["log_level"] == "info"


async def test_a_failure_relayed_from_the_gateway_is_info() -> None:
    """The identity process already logged it: one warning per failure."""
    relayed = EmisUnavailable(support_details="gateway answered 503 emis/unavailable")
    async with _client(relayed) as client:
        with capture_logs() as logs:
            response = await client.get("/boom")

    assert response.status_code == 503
    entry = next(item for item in logs if item["event"] == "domain_error")
    assert entry["log_level"] == "info"
