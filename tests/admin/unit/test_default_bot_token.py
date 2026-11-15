"""The default bot without TELEGRAM__BOT_TOKEN: its token comes from Vault."""

import io
from dataclasses import replace
from datetime import timedelta
from uuid import UUID

from app.bootstrap.import_default_bot import import_env_bot
from app.modules.admin.application.bot_admin import BotAdmin
from app.modules.admin.domain.errors import (
    BotDefaultTokenEnvError,
    BotVaultUnavailableError,
)
from app.modules.admin.domain.telegram_bot import TelegramBot
from app.modules.admin.infrastructure.default_bot_token import DefaultBotToken
from app.modules.identity.infrastructure.telegram.init_data import (
    HmacInitDataVerifier,
)
from app.shared.base_error import UnauthorizedError
from tests.admin.unit.test_bot_admin import (
    CODE,
    ENV_TOKEN,
    MemoryVault,
    Probe,
    accept_code,
)
from tests.admin.unit.test_broadcasts import Admin
from tests.fakes.clock import FixedClock

import pytest

ROTATED = "999999:EEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEzz99"


def make_admin(
    adm: Admin, vault: MemoryVault, clock: FixedClock, env: bool
) -> BotAdmin:
    return BotAdmin(
        uow_factory=adm.world.uow,
        vault=vault,
        probe=Probe(),
        resolver=adm.resolver,
        clock=clock,
        step_up=accept_code,
        env_token_set=env,
    )


@pytest.fixture
def adm(clock: FixedClock) -> Admin:
    return Admin(clock)


async def test_without_env_token_the_default_token_comes_from_vault(
    adm: Admin, clock: FixedClock
) -> None:
    vault = MemoryVault()
    bots = make_admin(adm, vault, clock, env=False)
    assert await bots.default_token("") is None

    await bots.import_env_bot(ENV_TOKEN, "ihspbot")

    assert await bots.default_token("") == ENV_TOKEN
    assert await bots.default_token("1:other") == "1:other"


async def test_import_is_idempotent_and_never_prints_the_token(
    adm: Admin, clock: FixedClock
) -> None:
    vault = MemoryVault()
    bots = make_admin(adm, vault, clock, env=True)
    first, second = io.StringIO(), io.StringIO()

    assert await import_env_bot(bots, ENV_TOKEN, "ihspbot", first) == 0
    assert await import_env_bot(bots, ENV_TOKEN, "ihspbot", second) == 0

    default = await bots.default_bot()
    assert default is not None
    assert list(vault.tokens) == [default.id]
    assert vault.tokens[default.id] == ENV_TOKEN
    assert str(default.id) in first.getvalue()
    assert first.getvalue() == second.getvalue()
    assert ENV_TOKEN not in first.getvalue() + second.getvalue()


async def test_import_refuses_an_empty_token(adm: Admin, clock: FixedClock) -> None:
    out = io.StringIO()
    bots = make_admin(adm, MemoryVault(), clock, env=False)

    assert await import_env_bot(bots, "", "ihspbot", out) == 1
    assert await bots.default_bot() is None


async def test_the_default_bot_rotates_in_vault_only_without_env_token(
    adm: Admin, clock: FixedClock
) -> None:
    vault = MemoryVault()
    with_env = make_admin(adm, vault, clock, env=True)
    default = await with_env.import_env_bot(ENV_TOKEN, "ihspbot")
    assert default is not None
    with pytest.raises(BotDefaultTokenEnvError):
        await with_env.rotate_token(adm.actor, default.id, ROTATED, otp_code=CODE)

    without_env = make_admin(adm, vault, clock, env=False)
    await without_env.rotate_token(adm.actor, default.id, ROTATED, otp_code=CODE)

    assert vault.tokens[default.id] == ROTATED


class Registry:
    def __init__(self, bots: list[TelegramBot]) -> None:
        self.bots = bots

    async def all(self) -> list[TelegramBot]:
        return self.bots


class FlakyVault(MemoryVault):
    down = False

    async def get(self, bot_id: UUID) -> str | None:
        if self.down:
            raise BotVaultUnavailableError()
        return await super().get(bot_id)


async def registered_default(
    adm: Admin, vault: MemoryVault, clock: FixedClock
) -> TelegramBot:
    bot = await make_admin(adm, vault, clock, env=False).import_env_bot(
        ENV_TOKEN, "ihspbot"
    )
    assert bot is not None
    return bot


async def test_default_bot_token_prefers_env_then_vault_and_survives_outage(
    adm: Admin, clock: FixedClock
) -> None:
    vault = FlakyVault()
    bot = await registered_default(adm, vault, clock)
    registry = Registry([bot])

    assert await DefaultBotToken("1:env", registry=registry, vault=vault).get() == (
        "1:env"
    )
    source = DefaultBotToken(
        "", registry=registry, vault=vault  # type: ignore[arg-type]
    )
    assert not source.from_env
    assert await source.get() == ENV_TOKEN

    vault.down = True
    vault.tokens[bot.id] = ROTATED
    registry.bots = [replace(bot, updated_at=clock.now().replace(year=2099))]
    assert await source.get() == ENV_TOKEN

    vault.down = False
    assert await source.get() == ROTATED
    registry.bots = []
    assert await source.get() is None


async def test_init_data_without_a_default_bot_is_refused(clock: FixedClock) -> None:
    async def no_token() -> str | None:
        return None

    verifier = HmacInitDataVerifier(token=no_token, clock=clock)

    with pytest.raises(UnauthorizedError):
        await verifier.verify("hash=x&auth_date=1", max_age=timedelta(days=1))
