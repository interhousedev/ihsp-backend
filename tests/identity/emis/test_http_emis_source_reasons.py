"""The HTTP EMIS source keeps the reason code of a failed gateway call."""

from collections.abc import Iterator
from uuid import UUID

from app.bootstrap.adapters.http_emis_source import HttpEmisSource
from app.shared.contracts.emis import EmisUnavailable

import httpx
import pytest
import respx

BASE = "http://identity.test/internal/emis"
USER = UUID(int=7)
PROFILE_URL = f"{BASE}/{USER}/profile"


async def _no_sleep(seconds: float) -> None:
    return None


@pytest.fixture
def gateway() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as router:
        yield router


def _source() -> HttpEmisSource:
    return HttpEmisSource(gateway_url=BASE, service_token="svc-token", sleep=_no_sleep)


async def test_a_typed_gateway_problem_passes_its_params_through(
    gateway: respx.MockRouter,
) -> None:
    """The gateway's reason and upstream status reach the caller."""
    gateway.get(PROFILE_URL).respond(
        503,
        json={
            "type": "emis/unavailable",
            "params": {"reason": "timeout", "upstream_status": 504},
        },
    )

    with pytest.raises(EmisUnavailable) as caught:
        await _source().profile(USER)

    assert caught.value.params["reason"] == "timeout"


async def test_two_timeouts_end_as_a_timeout_reason(
    gateway: respx.MockRouter,
) -> None:
    """An unreachable gateway is retried once, then reported as a timeout."""
    route = gateway.get(PROFILE_URL).mock(side_effect=httpx.ReadTimeout("slow"))

    with pytest.raises(EmisUnavailable) as caught:
        await _source().profile(USER)

    assert route.call_count == 2
    assert caught.value.params["reason"] == "timeout"


async def test_a_non_json_200_is_a_bad_response(
    gateway: respx.MockRouter,
) -> None:
    """A 200 with an HTML body is our contract problem."""
    gateway.get(PROFILE_URL).respond(200, html="<html/>")

    with pytest.raises(EmisUnavailable) as caught:
        await _source().profile(USER)

    assert caught.value.params["reason"] == "bad_response"
