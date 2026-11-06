"""Guessing an initial EMIS password: the attempts per EMIS login are limited."""

from app.modules.identity.application.register_emis_login import (
    REG_LOGIN_FAILURE_LIMIT,
)
from app.modules.identity.infrastructure.emis.fake import FAKE_PASSWORD
from app.shared.base_error import RateLimitedError
from app.shared.contracts.emis import EmisAuthFailed
from tests.identity.emis.world import World

import pytest


async def test_repeated_wrong_passwords_block_that_login_even_from_new_addresses(
    world: World,
) -> None:
    for attempt in range(REG_LOGIN_FAILURE_LIMIT):
        with pytest.raises(EmisAuthFailed):
            await world.register_start.execute(
                emis_login="student01",
                emis_password="01012009",
                ip=f"10.0.0.{attempt}",
                locale="ru",
            )

    with pytest.raises(RateLimitedError):
        await world.register_start.execute(
            emis_login="student01",
            emis_password=FAKE_PASSWORD,
            ip="10.0.1.1",
            locale="ru",
        )


async def test_another_login_is_not_blocked(world: World) -> None:
    for attempt in range(REG_LOGIN_FAILURE_LIMIT):
        with pytest.raises(EmisAuthFailed):
            await world.register_start.execute(
                emis_login="student01",
                emis_password="01012009",
                ip=f"10.0.0.{attempt}",
                locale="ru",
            )

    started = await world.register_start.execute(
        emis_login="student02", emis_password=FAKE_PASSWORD, ip="10.0.1.1", locale="ru"
    )

    assert started.registration_token
