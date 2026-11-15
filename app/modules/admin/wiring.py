"""Builds the admin services: broadcasts (task B8)."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from app.modules.admin.application.audience_count import AudienceCount
from app.modules.admin.application.bot_admin import BotAdmin
from app.modules.admin.application.broadcast_view import BroadcastPresenter
from app.modules.admin.application.cancel_broadcast import CancelBroadcast
from app.modules.admin.application.create_broadcast import CreateBroadcast
from app.modules.admin.application.deliver_broadcast import DeliverBroadcast
from app.modules.admin.application.finish_broadcasts import FinishBroadcasts
from app.modules.admin.application.get_broadcast import GetBroadcast
from app.modules.admin.application.limit_admin import LimitAdmin
from app.modules.admin.application.list_broadcasts import ListBroadcasts
from app.modules.admin.application.migration_service import MigrationService
from app.modules.admin.application.platform_settings import PlatformSettingsService
from app.modules.admin.application.preview_broadcast import PreviewBroadcast
from app.modules.admin.application.resolve_audience import ResolveAudience
from app.modules.admin.application.send_broadcast import SendBroadcast
from app.modules.admin.application.start_scheduled_broadcasts import (
    StartScheduledBroadcasts,
)
from app.modules.admin.application.update_broadcast import UpdateBroadcast
from app.modules.admin.infrastructure.bot_registry import (
    AiogramBotProbe,
    FakeBotProbe,
)
from app.modules.admin.infrastructure.bot_token_vault import VaultBotTokenStore
from app.modules.admin.infrastructure.migration_store import FileMigrationStore
from app.modules.admin.infrastructure.repositories.platform_settings_store import (
    SqlPlatformSettingsStore,
)
from app.modules.admin.infrastructure.uow import SqlAdminUnitOfWork
from app.shared.actor import Actor
from app.shared.clock import local_today
from app.shared.contracts.academic import ScheduleQueries
from app.shared.contracts.identity import IdentityDirectory
from app.shared.wiring import ModuleDeps


@dataclass(slots=True)
class AdminServices:
    """Broadcast use cases (attribute name = use case file name)."""

    create_broadcast: CreateBroadcast
    update_broadcast: UpdateBroadcast
    get_broadcast: GetBroadcast
    list_broadcasts: ListBroadcasts
    audience_count: AudienceCount
    preview_broadcast: PreviewBroadcast
    send_broadcast: SendBroadcast
    cancel_broadcast: CancelBroadcast
    start_scheduled_broadcasts: StartScheduledBroadcasts
    finish_broadcasts: FinishBroadcasts
    resolve_audience: ResolveAudience
    platform_settings: PlatformSettingsService
    limit_admin: LimitAdmin
    migration: MigrationService
    bot_admin: BotAdmin


def build(
    deps: ModuleDeps,
    *,
    identity: IdentityDirectory,
    schedule: ScheduleQueries,
    step_up: Callable[[Actor, str], Awaitable[None]],
) -> AdminServices:
    """Wire the admin module."""

    def uow_factory() -> SqlAdminUnitOfWork:
        return SqlAdminUnitOfWork(
            deps.sessionmaker,
            deps.outbox_writer,
            deps.audit_writer,
            deps.outbox_committed_hook,
        )

    presenter = BroadcastPresenter(identity)
    resolver = ResolveAudience(identity, schedule)
    deliver = DeliverBroadcast(uow_factory=uow_factory)
    return AdminServices(
        create_broadcast=CreateBroadcast(
            uow_factory=uow_factory, presenter=presenter, clock=deps.clock
        ),
        update_broadcast=UpdateBroadcast(uow_factory=uow_factory, presenter=presenter),
        get_broadcast=GetBroadcast(uow_factory=uow_factory, presenter=presenter),
        list_broadcasts=ListBroadcasts(uow_factory=uow_factory, presenter=presenter),
        audience_count=AudienceCount(resolver),
        preview_broadcast=PreviewBroadcast(uow_factory=uow_factory, identity=identity),
        send_broadcast=SendBroadcast(
            uow_factory=uow_factory,
            resolver=resolver,
            deliver=deliver,
            presenter=presenter,
            clock=deps.clock,
        ),
        cancel_broadcast=CancelBroadcast(uow_factory=uow_factory, presenter=presenter),
        start_scheduled_broadcasts=StartScheduledBroadcasts(
            uow_factory=uow_factory,
            resolver=resolver,
            deliver=deliver,
            clock=deps.clock,
        ),
        finish_broadcasts=FinishBroadcasts(
            uow_factory=uow_factory, resolver=resolver, deliver=deliver
        ),
        resolve_audience=resolver,
        platform_settings=PlatformSettingsService(
            SqlPlatformSettingsStore(deps.sessionmaker)
        ),
        limit_admin=LimitAdmin(
            uow_factory=uow_factory,
            identity=identity,
            limits=deps.effective_limits,
            base=deps.settings.limits,
            today=lambda: local_today(deps.clock),
        ),
        migration=MigrationService(
            store=FileMigrationStore(
                Path(deps.settings.migration.dir)
                if deps.settings.migration.dir
                else None
            ),
            uow_factory=uow_factory,
            step_up=step_up,
            clock=deps.clock,
        ),
        bot_admin=BotAdmin(
            uow_factory=uow_factory,
            vault=VaultBotTokenStore(deps.settings.bot_vault),
            probe=(
                FakeBotProbe()
                if deps.settings.telegram.mode == "fake"
                else AiogramBotProbe()
            ),
            resolver=resolver,
            clock=deps.clock,
            step_up=step_up,
        ),
    )
