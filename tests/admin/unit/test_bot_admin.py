"""Telegram bot registry use cases: add, switches, rotation, announcements."""

import asyncio
import threading
from uuid import UUID

from app.modules.admin.application.bot_admin import BotAdmin
from app.modules.admin.domain.errors import (
    BotAlreadyExistsError,
    BotAnnouncementsOffError,
    BotDefaultLockedError,
    BotDefaultTokenEnvError,
    BotFeatureUnknownError,
    BotNameInvalidError,
    BotTokenInvalidError,
    BotTokenMismatchError,
)
from app.modules.admin.domain.telegram_bot import (
    ALL_FEATURES,
    BotFeature,
    BotIdentity,
    parse_features,
    token_bot_id,
)
from app.modules.identity.domain.errors import StepUpInvalidError
from app.shared.ids import new_id
from tests.admin.unit.test_broadcasts import Admin
from tests.fakes.clock import FixedClock

import pytest

TOKEN_A = "111111:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
TOKEN_A2 = "111111:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBzz99"
TOKEN_B = "222222:CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC"
ENV_TOKEN = "999999:DDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDD"


CODE = "123456"


async def accept_code(actor: object, code: str) -> None:
    """A step-up check that accepts the one right code."""
    if code != CODE:
        raise StepUpInvalidError()


class MemoryVault:
    def __init__(self) -> None:
        self.tokens: dict[UUID, str] = {}

    async def put(self, bot_id: UUID, token: str) -> None:
        self.tokens[bot_id] = token

    async def get(self, bot_id: UUID) -> str | None:
        return self.tokens.get(bot_id)


class Probe:
    async def identify(self, token: str) -> BotIdentity:
        if token.endswith("bad"):
            raise BotTokenInvalidError(support_details="getMe")
        telegram_id = token_bot_id(token)
        return BotIdentity(
            telegram_id=telegram_id, username=f"bot{telegram_id}", first_name="Bot"
        )


@pytest.fixture
def adm(clock: FixedClock) -> Admin:
    return Admin(clock)


@pytest.fixture
def vault() -> MemoryVault:
    return MemoryVault()


@pytest.fixture
def bots(adm: Admin, vault: MemoryVault, clock: FixedClock) -> BotAdmin:
    return BotAdmin(
        uow_factory=adm.world.uow,
        vault=vault,
        probe=Probe(),
        resolver=adm.resolver,
        clock=clock,
        step_up=accept_code,
    )


async def test_add_validates_stores_token_in_vault_and_starts_with_features_off(
    adm: Admin, bots: BotAdmin, vault: MemoryVault
) -> None:
    view = await bots.add(adm.actor, name=" Library ", token=TOKEN_A, otp_code=CODE)

    assert view.bot.name == "Library"
    assert view.bot.username == "bot111111"
    assert view.bot.token_hint == TOKEN_A[-4:]
    assert not any(view.bot.has(f) for f in ALL_FEATURES)
    assert vault.tokens[view.bot.id] == TOKEN_A
    assert adm.world.audits[-1].type == "bot.added"
    assert "token" not in str(adm.world.audits[-1].metadata)


class _FailingCommit:
    """A unit of work whose commit fails, as a database outage would."""

    def __init__(self, inner: object) -> None:
        self._inner = inner

    async def __aenter__(self) -> "_FailingCommit":
        self._uow = await self._inner.__aenter__()  # type: ignore[attr-defined]
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._inner.__aexit__(*exc)  # type: ignore[attr-defined]

    def __getattr__(self, name: str) -> object:
        return getattr(self._uow, name)

    async def commit(self) -> None:
        raise RuntimeError("database down")


async def test_rotate_restores_the_vault_token_when_the_database_write_fails(
    adm: Admin, vault: MemoryVault, clock: FixedClock
) -> None:
    good = BotAdmin(
        uow_factory=adm.world.uow,
        vault=vault,
        probe=Probe(),
        resolver=adm.resolver,
        clock=clock,
        step_up=accept_code,
    )
    view = await good.add(adm.actor, name="Library", token=TOKEN_A, otp_code=CODE)
    failing = BotAdmin(
        uow_factory=lambda: _FailingCommit(adm.world.uow()),
        vault=vault,
        probe=Probe(),
        resolver=adm.resolver,
        clock=clock,
        step_up=accept_code,
    )

    with pytest.raises(RuntimeError):
        await failing.rotate_token(adm.actor, view.bot.id, TOKEN_A2, otp_code=CODE)

    assert vault.tokens[view.bot.id] == TOKEN_A


async def test_add_rejects_bad_and_duplicate_tokens(adm: Admin, bots: BotAdmin) -> None:
    with pytest.raises(BotTokenInvalidError):
        await bots.add(adm.actor, name="x", token="not-a-token", otp_code=CODE)
    with pytest.raises(BotTokenInvalidError):
        await bots.add(adm.actor, name="x", token=TOKEN_B + "bad", otp_code=CODE)
    await bots.add(adm.actor, name="x", token=TOKEN_A, otp_code=CODE)
    with pytest.raises(BotAlreadyExistsError):
        await bots.add(adm.actor, name="y", token=TOKEN_A2, otp_code=CODE)


async def test_update_switches_and_default_stays_on(adm: Admin, bots: BotAdmin) -> None:
    default = await bots.import_default_bot(ENV_TOKEN, "ihspbot")
    assert default is not None and all(default.has(f) for f in ALL_FEATURES)
    added = await bots.add(adm.actor, name="Extra", token=TOKEN_A, otp_code=CODE)

    view = await bots.update(
        adm.actor,
        added.bot.id,
        features={BotFeature.ANNOUNCEMENTS: True},
        otp_code=CODE,
    )
    assert view.bot.has(BotFeature.ANNOUNCEMENTS)
    assert not view.bot.has(BotFeature.AI_AGENT)
    with pytest.raises(BotDefaultLockedError):
        await bots.update(adm.actor, default.id, enabled=False, otp_code=CODE)
    with pytest.raises(BotFeatureUnknownError):
        parse_features({"teleport": True})


async def test_import_runs_once_and_token_falls_back_to_env(
    bots: BotAdmin, vault: MemoryVault
) -> None:
    first = await bots.import_default_bot(ENV_TOKEN, "ihspbot")
    assert first is not None
    assert await bots.import_default_bot(ENV_TOKEN, "ihspbot") is None
    assert await bots.token_of(first, ENV_TOKEN) == ENV_TOKEN
    vault.tokens.clear()
    assert await bots.token_of(first, "fallback") == "fallback"


async def test_a_skipped_import_is_retried_after_other_bots_were_added(
    adm: Admin, bots: BotAdmin, vault: MemoryVault
) -> None:
    """A first start without Vault must not leave the env bot unregistered."""
    assert await bots.import_default_bot("malformed", "ihspbot") is None
    extra = await bots.add(adm.actor, name="Extra", token=TOKEN_A, otp_code=CODE)

    default = await bots.import_default_bot(ENV_TOKEN, "ihspbot")

    assert default is not None and default.is_default
    assert all(default.has(feature) for feature in ALL_FEATURES)
    assert vault.tokens[default.id] == ENV_TOKEN
    assert not extra.bot.is_default
    assert await bots.import_default_bot(ENV_TOKEN, "ihspbot") is None


async def test_an_env_bot_added_by_hand_is_not_imported_twice(
    adm: Admin, bots: BotAdmin, vault: MemoryVault
) -> None:
    added = await bots.add(adm.actor, name="Same bot", token=ENV_TOKEN, otp_code=CODE)

    assert await bots.import_default_bot(ENV_TOKEN, "ihspbot") is None
    assert list(vault.tokens) == [added.bot.id]


async def test_rotate_accepts_only_the_same_bot(
    adm: Admin, bots: BotAdmin, vault: MemoryVault
) -> None:
    added = await bots.add(adm.actor, name="Extra", token=TOKEN_A, otp_code=CODE)

    view = await bots.rotate_token(adm.actor, added.bot.id, TOKEN_A2, otp_code=CODE)
    assert view.bot.token_hint == "zz99"
    assert vault.tokens[added.bot.id] == TOKEN_A2
    with pytest.raises(BotTokenMismatchError):
        await bots.rotate_token(adm.actor, added.bot.id, TOKEN_B, otp_code=CODE)


async def test_announce_splits_recipients_once_per_bot(
    adm: Admin, bots: BotAdmin
) -> None:
    students = adm.students(3)
    default = await bots.import_default_bot(ENV_TOKEN, "ihspbot")
    assert default is not None
    extra = await bots.add(adm.actor, name="Extra", token=TOKEN_A, otp_code=CODE)
    await bots.update(
        adm.actor,
        extra.bot.id,
        features={BotFeature.ANNOUNCEMENTS: True},
        otp_code=CODE,
    )
    adm.world.bots.links[extra.bot.id] = {students[0].id}
    draft = await adm.draft()

    result = await bots.announce(
        adm.actor, draft.broadcast.id, [extra.bot.id, default.id], otp_code=CODE
    )

    assert result.recipients == 3
    assert result.per_bot == {extra.bot.id: 1, default.id: 2}
    by_user = {d.user_id: d.payload["bot_id"] for d in adm.world.outbox}
    assert by_user[students[0].id] == str(extra.bot.id)
    assert by_user[students[1].id] == str(default.id)
    assert adm.world.batches == [3]


async def test_announce_refuses_bots_without_the_switch(
    adm: Admin, bots: BotAdmin
) -> None:
    adm.students(1)
    extra = await bots.add(adm.actor, name="Extra", token=TOKEN_A, otp_code=CODE)
    draft = await adm.draft()

    with pytest.raises(BotAnnouncementsOffError):
        await bots.announce(
            adm.actor, draft.broadcast.id, [extra.bot.id], otp_code=CODE
        )
    assert adm.world.outbox == []


async def test_the_env_token_wins_for_the_default_bot_and_vault_follows(
    adm: Admin, bots: BotAdmin, vault: MemoryVault
) -> None:
    default = await bots.import_default_bot(ENV_TOKEN, "ihspbot")
    assert default is not None
    audits = len(adm.world.audits)
    assert await bots.import_default_bot(ENV_TOKEN, "ihspbot") is None
    assert len(adm.world.audits) == audits  # same token: nothing written
    new_env = "999999:" + "E" * 32 + "4321"

    assert await bots.token_of(default, new_env) == new_env  # even before the sync
    assert await bots.import_default_bot(new_env, "ihspbot") is None

    stored = await bots.get(default.id)
    assert vault.tokens[default.id] == new_env
    assert stored.token_hint == "4321"
    assert stored.telegram_id == 999999
    assert adm.world.audits[-1].type == "bot.token_rotated"
    assert new_env not in str(adm.world.audits[-1].metadata)
    assert len(await bots.list_bots(adm.actor)) == 1


async def test_the_default_bot_token_cannot_be_rotated_by_administration(
    adm: Admin, bots: BotAdmin, vault: MemoryVault
) -> None:
    default = await bots.import_default_bot(ENV_TOKEN, "ihspbot")
    assert default is not None

    with pytest.raises(BotDefaultTokenEnvError):
        await bots.rotate_token(
            adm.actor, default.id, "999999:" + "F" * 36, otp_code=CODE
        )
    assert vault.tokens[default.id] == ENV_TOKEN


async def test_a_switch_without_a_stored_value_is_on_only_for_the_default_bot(
    adm: Admin, bots: BotAdmin
) -> None:
    default = await bots.import_default_bot(ENV_TOKEN, "ihspbot")
    extra = (await bots.add(adm.actor, name="Extra", token=TOKEN_A, otp_code=CODE)).bot
    assert default is not None
    default.features.pop(BotFeature.NOTIFICATIONS)
    extra.features.pop(BotFeature.NOTIFICATIONS)

    assert default.has(BotFeature.NOTIFICATIONS)
    assert not extra.has(BotFeature.NOTIFICATIONS)
    default.set_features({BotFeature.NOTIFICATIONS: False})
    assert not default.has(BotFeature.NOTIFICATIONS)


async def test_every_write_checks_the_step_up_code_after_the_input(
    adm: Admin, bots: BotAdmin
) -> None:
    extra = await bots.add(adm.actor, name="Extra", token=TOKEN_A, otp_code=CODE)
    wrong = "000000"

    with pytest.raises(StepUpInvalidError):
        await bots.add(adm.actor, name="Other", token=TOKEN_B, otp_code=wrong)
    with pytest.raises(StepUpInvalidError):
        await bots.update(adm.actor, extra.bot.id, enabled=False, otp_code=wrong)
    with pytest.raises(StepUpInvalidError):
        await bots.rotate_token(adm.actor, extra.bot.id, TOKEN_A2, otp_code=wrong)
    with pytest.raises(StepUpInvalidError):
        await bots.announce(adm.actor, new_id(), [extra.bot.id], otp_code=wrong)
    with pytest.raises(BotNameInvalidError):
        await bots.update(adm.actor, extra.bot.id, name=" ", otp_code=wrong)
    with pytest.raises(BotTokenInvalidError):
        await bots.add(adm.actor, name="x", token="not-a-token", otp_code=wrong)

    views = await bots.list_bots(adm.actor)
    assert [v.bot.name for v in views] == ["Extra"]
    assert views[0].bot.enabled
    assert views[0].bot.token_hint == TOKEN_A[-4:]


TOKEN_A3 = "111111:EEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEyy88"


class _SlowFailingCommit(_FailingCommit):
    """A commit that waits for the test, then fails."""

    def __init__(
        self, inner: object, reached: asyncio.Event, go: asyncio.Event
    ) -> None:
        super().__init__(inner)
        self._reached, self._go = reached, go

    async def commit(self) -> None:
        self._reached.set()
        await self._go.wait()
        raise RuntimeError("database down")


async def test_a_failed_rotation_never_undoes_a_later_committed_one(
    adm: Admin, bots: BotAdmin, vault: MemoryVault, clock: FixedClock
) -> None:
    view = await bots.add(adm.actor, name="Library", token=TOKEN_A, otp_code=CODE)
    reached, go = asyncio.Event(), asyncio.Event()
    failing = BotAdmin(
        uow_factory=lambda: _SlowFailingCommit(adm.world.uow(), reached, go),
        vault=vault,
        probe=Probe(),
        resolver=adm.resolver,
        clock=clock,
        step_up=accept_code,
    )
    first = asyncio.create_task(
        failing.rotate_token(adm.actor, view.bot.id, TOKEN_A2, otp_code=CODE)
    )
    await reached.wait()
    second = asyncio.create_task(
        bots.rotate_token(adm.actor, view.bot.id, TOKEN_A3, otp_code=CODE)
    )
    for _ in range(20):
        await asyncio.sleep(0)
    go.set()

    with pytest.raises(RuntimeError):
        await first
    committed = await second

    assert committed.bot.token_hint == TOKEN_A3[-4:]
    assert vault.tokens[view.bot.id] == TOKEN_A3


class _ThreadVault(MemoryVault):
    """Writes in a thread, like hvac: cancelling the caller does not stop it."""

    def __init__(self) -> None:
        super().__init__()
        self.gate = threading.Event()
        self.blocked = asyncio.Event()
        self.block_token: str | None = None

    async def put(self, bot_id: UUID, token: str) -> None:
        if token != self.block_token:
            self.tokens[bot_id] = token
            return
        loop = asyncio.get_running_loop()

        def write() -> None:
            loop.call_soon_threadsafe(self.blocked.set)
            self.gate.wait(5)
            self.tokens[bot_id] = token

        await asyncio.to_thread(write)


async def test_a_cancelled_rotation_restores_the_previous_token(
    adm: Admin, clock: FixedClock
) -> None:
    vault = _ThreadVault()
    bots = BotAdmin(
        uow_factory=adm.world.uow,
        vault=vault,
        probe=Probe(),
        resolver=adm.resolver,
        clock=clock,
        step_up=accept_code,
    )
    view = await bots.add(adm.actor, name="Library", token=TOKEN_A, otp_code=CODE)
    vault.block_token = TOKEN_A2
    task = asyncio.create_task(
        bots.rotate_token(adm.actor, view.bot.id, TOKEN_A2, otp_code=CODE)
    )
    await vault.blocked.wait()
    task.cancel()
    for _ in range(5):
        await asyncio.sleep(0)
    vault.gate.set()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert vault.tokens[view.bot.id] == TOKEN_A
