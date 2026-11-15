"""Administration of the Telegram bots: registry, tokens, switches, announcements."""

import asyncio
from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass
from uuid import UUID

from app.modules.admin.application.deliver_broadcast import broadcast_drafts
from app.modules.admin.application.resolve_audience import ResolveAudience
from app.modules.admin.application.send_broadcast import broadcast_sent_audit
from app.modules.admin.domain.errors import (
    BotAlreadyExistsError,
    BotAnnouncementsOffError,
    BotDefaultTokenEnvError,
    BotTokenInvalidError,
    BotVaultUnavailableError,
    BroadcastEmptyAudienceError,
)
from app.modules.admin.domain.telegram_bot import (
    ALL_FEATURES,
    BotFeature,
    TelegramBot,
    check_name,
    token_bot_id,
    token_hint,
)
from app.modules.admin.ports.telegram_bots import BotProbe, BotTokenVault
from app.modules.admin.ports.unit_of_work import AdminUnitOfWork
from app.shared.actor import Actor, Role
from app.shared.clock import Clock
from app.shared.ids import new_id
from app.shared.notifications import AuditDraft

import structlog

log = structlog.get_logger(__name__)

AUDIT_BOT_ADDED = "bot.added"
AUDIT_BOT_UPDATED = "bot.updated"
AUDIT_BOT_TOKEN_ROTATED = "bot.token_rotated"
AUDIT_BOT_ANNOUNCEMENT_SENT = "bot.announcement_sent"

NEW_BOT_FEATURES: dict[BotFeature, bool] = dict.fromkeys(BotFeature, False)
"""A newly added bot does nothing until Administration switches features on."""


def _has_default(bots: Collection[TelegramBot], telegram_id: int) -> bool:
    """Whether the env bot cannot be registered as default any more."""
    return any(bot.is_default or bot.telegram_id == telegram_id for bot in bots)


async def _settled(write: Awaitable[None]) -> None:
    """Await a Vault write that a cancellation cannot leave in flight.

    The blocking client runs in a thread that cancelling cannot stop, so on
    cancellation the write is awaited to its end before CancelledError goes on;
    the caller's compensation then cannot be overtaken by the late write.
    """
    task = asyncio.ensure_future(write)
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        await asyncio.wait({task})
        if not task.cancelled():
            task.exception()  # retrieved: the cancellation is what goes on
        raise


@dataclass(frozen=True, slots=True)
class BotView:
    """A bot as Administration sees it (never the token)."""

    bot: TelegramBot
    members: int


@dataclass(frozen=True, slots=True)
class AnnouncementResult:
    """How many recipients each selected bot got."""

    broadcast_id: UUID
    recipients: int
    per_bot: dict[UUID, int]


class BotAdmin:
    """Use cases of the admin "Bots" page plus the startup import."""

    def __init__(
        self,
        *,
        uow_factory: Callable[[], AdminUnitOfWork],
        vault: BotTokenVault,
        probe: BotProbe,
        resolver: ResolveAudience,
        clock: Clock,
        step_up: Callable[[Actor, str], Awaitable[None]],
    ) -> None:
        """Store the collaborators; `step_up` raises when the code is wrong.

        Every write (add, update, rotate, announce) verifies a fresh step-up code
        here, after the input is validated, so no edge can skip it.
        """
        self.uow_factory = uow_factory
        self.vault = vault
        self.probe = probe
        self.resolver = resolver
        self.clock = clock
        self.step_up = step_up

    async def list_bots(self, actor: Actor) -> list[BotView]:
        """Every bot with its linked member count."""
        actor.require(Role.ADMIN)
        async with self.uow_factory() as uow:
            bots = await uow.bots.list_all()
            counts = await uow.bots.member_counts()
        return [BotView(bot, counts.get(bot.id, 0)) for bot in bots]

    async def add(
        self, actor: Actor, *, name: str, token: str, otp_code: str
    ) -> BotView:
        """Validate the token with getMe, store it in Vault, register the bot."""
        actor.require(Role.ADMIN)
        cleaned = check_name(name)
        token = token.strip()
        token_bot_id(token)
        await self.step_up(actor, otp_code)
        identity = await self.probe.identify(token)
        async with self.uow_factory() as uow:
            if await uow.bots.by_telegram_id(identity.telegram_id) is not None:
                raise BotAlreadyExistsError(
                    support_details=f"telegram id {identity.telegram_id}"
                )
        now = self.clock.now()
        bot = TelegramBot(
            id=new_id(),
            name=cleaned,
            username=identity.username,
            telegram_id=identity.telegram_id,
            token_hint=token_hint(token),
            enabled=True,
            is_default=False,
            created_at=now,
            updated_at=now,
            features=dict(NEW_BOT_FEATURES),
        )
        # Vault first: a row without a token would be a bot that cannot start.
        # A failed insert (also a concurrent add of the same bot, which the
        # repository reports as BotAlreadyExistsError) leaves an unreferenced
        # secret under a fresh random id; the policy cannot delete it, and no row
        # or process ever reads it.
        await self.vault.put(bot.id, token)
        async with self.uow_factory() as uow:
            await uow.bots.add(bot, actor_id=actor.user_id)
            uow.audit(
                AuditDraft(
                    type=AUDIT_BOT_ADDED,
                    actor_id=actor.user_id,
                    metadata={
                        "bot_id": str(bot.id),
                        "username": bot.username,
                        "telegram_id": bot.telegram_id,
                    },
                )
            )
            await uow.commit()
        return BotView(bot, 0)

    async def update(
        self,
        actor: Actor,
        bot_id: UUID,
        *,
        name: str | None = None,
        enabled: bool | None = None,
        features: dict[BotFeature, bool] | None = None,
        otp_code: str,
    ) -> BotView:
        """Rename, switch on or off, or change feature switches."""
        actor.require(Role.ADMIN)
        if name is not None:
            check_name(name)
        await self.step_up(actor, otp_code)
        async with self.uow_factory() as uow:
            bot = await uow.bots.get(bot_id, for_update=True)
            changes: dict[str, object] = {}
            if name is not None and name.strip() != bot.name:
                bot.rename(name)
                changes["name"] = bot.name
            if enabled is not None and enabled != bot.enabled:
                bot.set_enabled(enabled)
                changes["enabled"] = enabled
            if features:
                diff = {k: v for k, v in features.items() if bot.features.get(k) != v}
                if diff:
                    bot.set_features(diff)
                    changes["features"] = {str(k): v for k, v in diff.items()}
            if changes:
                await uow.bots.save(bot, actor_id=actor.user_id)
                uow.audit(
                    AuditDraft(
                        type=AUDIT_BOT_UPDATED,
                        actor_id=actor.user_id,
                        metadata={"bot_id": str(bot.id), "changes": changes},
                    )
                )
            members = (await uow.bots.member_counts()).get(bot.id, 0)
            await uow.commit()
        return BotView(bot, members)

    async def rotate_token(
        self, actor: Actor, bot_id: UUID, token: str, *, otp_code: str
    ) -> BotView:
        """Replace the token with a new one of the same Telegram bot.

        The bot row stays locked (FOR UPDATE) from reading the previous token
        through the commit, so rotations of one bot run one after another and a
        compensation never overwrites a later rotation. When the database write
        fails or the request is cancelled, the previous token is put back so
        Vault and the hint agree.
        """
        actor.require(Role.ADMIN)
        current = await self.get(bot_id)
        if current.is_default:
            raise BotDefaultTokenEnvError(support_details=f"bot {bot_id}")
        token = token.strip()
        token_bot_id(token)
        await self.step_up(actor, otp_code)
        identity = await self.probe.identify(token)
        current.rotate(identity, token_hint(token))  # BotTokenMismatchError
        async with self.uow_factory() as uow:
            bot = await uow.bots.get(bot_id, for_update=True)
            if bot.is_default:
                raise BotDefaultTokenEnvError(support_details=f"bot {bot_id}")
            bot.rotate(identity, token_hint(token))
            previous = await self.vault.get(bot_id)
            try:
                await _settled(self.vault.put(bot_id, token))
                await uow.bots.save(bot, actor_id=actor.user_id)
                uow.audit(
                    AuditDraft(
                        type=AUDIT_BOT_TOKEN_ROTATED,
                        actor_id=actor.user_id,
                        metadata={"bot_id": str(bot.id), "hint": bot.token_hint},
                    )
                )
                members = (await uow.bots.member_counts()).get(bot.id, 0)
                await uow.commit()
            except BaseException:
                await self._restore_token(bot_id, previous)
                raise
        return BotView(bot, members)

    async def _restore_token(self, bot_id: UUID, previous: str | None) -> None:
        """Compensate a failed rotation: Vault gets the previous token back.

        Runs while the row lock is still held, so no later rotation is undone.
        """
        if previous is None:
            return
        try:
            await _settled(self.vault.put(bot_id, previous))
        except BotVaultUnavailableError:
            log.error("bot_token_restore_failed", bot_id=str(bot_id))

    async def announce(
        self,
        actor: Actor,
        broadcast_id: UUID,
        bot_ids: Collection[UUID],
        *,
        otp_code: str,
    ) -> AnnouncementResult:
        """Send a draft broadcast through the selected bots.

        Each bot reaches the users linked to it (the default bot reaches every
        recipient); a recipient gets the message once, from the first selected bot
        that reaches them, in the order given.
        """
        actor.require(Role.ADMIN)
        selected = list(dict.fromkeys(bot_ids))
        if not selected:
            raise BotAnnouncementsOffError(support_details="no bots selected")
        await self.step_up(actor, otp_code)
        async with self.uow_factory() as uow:
            bots = [await uow.bots.get(bot_id) for bot_id in selected]
            for bot in bots:
                if not bot.has(BotFeature.ANNOUNCEMENTS):
                    raise BotAnnouncementsOffError(support_details=f"bot {bot.id}")
            broadcast = await uow.broadcasts.get(broadcast_id, for_update=True)
            broadcast.ensure_sendable()
            audience = await self.resolver.execute(broadcast.audience)
            bot_of: dict[UUID, UUID] = {}
            for bot in bots:
                remaining = audience - bot_of.keys()
                reached = (
                    set(remaining)
                    if bot.is_default
                    else await uow.bots.members(bot.id, remaining)
                )
                bot_of.update({user_id: bot.id for user_id in reached})
            if not bot_of:
                raise BroadcastEmptyAudienceError(
                    support_details=f"broadcast {broadcast_id}"
                )
            broadcast.start_sending(len(bot_of))
            await uow.broadcasts.save(broadcast)
            # One transaction: the resume job never re-sends a partial fan-out to
            # the full audience through the default bot.
            uow.notify(*broadcast_drafts(broadcast, bot_of.keys(), bot_of=bot_of))
            per_bot = {bot.id: 0 for bot in bots}
            for target in bot_of.values():
                per_bot[target] += 1
            uow.audit(
                broadcast_sent_audit(
                    broadcast, actor_id=actor.user_id, recipients=len(bot_of)
                )
            )
            uow.audit(
                AuditDraft(
                    type=AUDIT_BOT_ANNOUNCEMENT_SENT,
                    actor_id=actor.user_id,
                    metadata={
                        "broadcast_id": str(broadcast.id),
                        "bots": {str(k): v for k, v in per_bot.items()},
                    },
                )
            )
            await uow.commit()
        return AnnouncementResult(broadcast.id, len(bot_of), per_bot)

    def _default_bot(self, token: str, username: str, telegram_id: int) -> TelegramBot:
        now = self.clock.now()
        return TelegramBot(
            id=new_id(),
            name=username,
            username=username,
            telegram_id=telegram_id,
            token_hint=token_hint(token),
            enabled=True,
            is_default=True,
            created_at=now,
            updated_at=now,
            features=dict.fromkeys(ALL_FEATURES, True),
        )

    async def _persist_default(self, bot: TelegramBot) -> TelegramBot | None:
        try:
            async with self.uow_factory() as uow:
                if _has_default(await uow.bots.list_all(), bot.telegram_id):
                    return None  # another process won the race
                await uow.bots.add(bot, actor_id=None)
                uow.audit(
                    AuditDraft(
                        type=AUDIT_BOT_ADDED,
                        metadata={
                            "bot_id": str(bot.id),
                            "username": bot.username,
                            "default": True,
                        },
                    )
                )
                await uow.commit()
        except BotAlreadyExistsError:  # unique indexes: another process raced
            log.info("default_bot_import_raced")
            return None
        return bot

    async def import_default_bot(
        self, token: str | None, username: str
    ) -> TelegramBot | None:
        """A start without a default bot: register the env bot as default.

        Every feature is on, so the default bot behaves exactly like the single
        bot did before. Skipped (env token keeps working) when a default bot or
        this very bot is already registered, the token is malformed, or Vault is
        unreachable; a skipped import is retried on the next start, also when
        other bots were added meanwhile. With a default bot registered, its Vault
        token and hint are brought in line with the env token instead.
        """
        if not token:
            return None
        async with self.uow_factory() as uow:
            registered = await uow.bots.list_all()
        default = next((bot for bot in registered if bot.is_default), None)
        if default is not None:
            await self._sync_default_token(default.id, token.strip())
            return None
        try:
            telegram_id = token_bot_id(token)
        except BotTokenInvalidError:
            log.warning("default_bot_import_skipped", reason="token")
            return None
        if _has_default(registered, telegram_id):
            log.warning("default_bot_import_skipped", reason="registered")
            return None
        bot = self._default_bot(token, username, telegram_id)
        try:
            await self.vault.put(bot.id, token.strip())
        except BotVaultUnavailableError:
            log.warning("default_bot_import_skipped", reason="vault")
            return None
        return await self._persist_default(bot)

    async def _sync_default_token(self, bot_id: UUID, token: str) -> None:
        """The env token is the truth for the default bot: Vault and hint follow."""
        try:
            telegram_id = token_bot_id(token)
            if await self.vault.get(bot_id) == token:
                return
            await self.vault.put(bot_id, token)
        except BotTokenInvalidError:
            log.warning("default_bot_token_sync_skipped", reason="token")
            return
        except BotVaultUnavailableError:
            log.warning("default_bot_token_sync_skipped", reason="vault")
            return
        async with self.uow_factory() as uow:
            bot = await uow.bots.get(bot_id, for_update=True)
            bot.token_hint = token_hint(token)
            if await uow.bots.by_telegram_id(telegram_id) is None:
                bot.telegram_id = telegram_id  # the env now names another bot
            await uow.bots.save(bot, actor_id=None)
            uow.audit(
                AuditDraft(
                    type=AUDIT_BOT_TOKEN_ROTATED,
                    metadata={
                        "bot_id": str(bot.id),
                        "hint": bot.token_hint,
                        "source": "env",
                    },
                )
            )
            await uow.commit()
        log.info("default_bot_token_synced", bot_id=str(bot_id))

    async def token_of(self, bot: TelegramBot, env_token: str | None) -> str | None:
        """The token to run the bot with; the env token wins for the default bot.

        The notification sender and the Mini App check use the env token too, so
        every process agrees whatever Vault holds.
        """
        if bot.is_default and env_token:
            return env_token
        try:
            return await self.vault.get(bot.id)
        except BotVaultUnavailableError:
            return None

    async def enabled_bots(self) -> list[TelegramBot]:
        """The bots the bot process runs."""
        async with self.uow_factory() as uow:
            return [bot for bot in await uow.bots.list_all() if bot.enabled]

    async def get(self, bot_id: UUID) -> TelegramBot:
        """One bot (BotNotFoundError)."""
        async with self.uow_factory() as uow:
            return await uow.bots.get(bot_id)
