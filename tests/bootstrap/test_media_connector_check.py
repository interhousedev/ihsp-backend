"""The api process, which serves media links, can check the connector behind one."""

from app.bootstrap.common import PLANS, BuildOverrides, build_container
from app.settings import Settings
from tests.fakes.tasks import FakeTaskKicker

from fakeredis.aioredis import FakeRedis


def test_the_api_process_builds_the_lms() -> None:
    """The check is bound while the LMS is built, after identity."""
    assert PLANS["api"].lms is True


async def test_the_connector_check_is_bound_in_the_api_process(
    settings: Settings, redis: FakeRedis
) -> None:
    """MCP-B5: `POST /v1/lms/media/redeem` runs here."""
    container = await build_container(
        settings,
        process="api",
        kicker=FakeTaskKicker(),
        overrides=BuildOverrides(redis=redis),
    )
    try:
        check = container.lms.learning.redeem_media_grant._connector_active
        assert check is not None
    finally:
        await container.close()
