"""Builds the notify services (task B8)."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from app.modules.notify.application.count_unread import CountUnread
from app.modules.notify.application.dispatch_due import DispatchDue
from app.modules.notify.application.get_push_config import GetPushConfig
from app.modules.notify.application.list_notifications import ListNotifications
from app.modules.notify.application.mark_all_read import MarkAllRead
from app.modules.notify.application.mark_read import MarkRead
from app.modules.notify.application.public_api import NotifyApiImpl
from app.modules.notify.application.purge_old import PurgeOld
from app.modules.notify.application.push_delivery import PushDelivery
from app.modules.notify.application.register_push_subscription import (
    RegisterPushSubscription,
)
from app.modules.notify.application.remove_push_subscription import (
    RemovePushSubscription,
)
from app.modules.notify.application.renderers.builtin import register_builtin_renderers
from app.modules.notify.application.renderers.registry import RendererRegistry
from app.modules.notify.infrastructure.push_sender_factory import make_push_sender
from app.modules.notify.infrastructure.redis_send_limiter import RedisSendLimiter
from app.modules.notify.infrastructure.uow import SqlNotifyUnitOfWork
from app.modules.notify.ports.push_sender import PushSender
from app.shared.contracts.academic import ScheduleQueries
from app.shared.contracts.files import FilesApi
from app.shared.contracts.identity import IdentityDirectory
from app.shared.contracts.links import LinksApi
from app.shared.contracts.mail import MailApi
from app.shared.contracts.notify import TelegramSender
from app.shared.wiring import ModuleDeps


@dataclass(slots=True)
class NotifyServices:
    """Use cases of the notify module, the renderer registry and the public API."""

    dispatch_due: DispatchDue
    purge_old: PurgeOld
    list_notifications: ListNotifications
    count_unread: CountUnread
    mark_read: MarkRead
    mark_all_read: MarkAllRead
    renderers: RendererRegistry
    public: NotifyApiImpl
    push_config: GetPushConfig
    register_push_subscription: RegisterPushSubscription
    remove_push_subscription: RemovePushSubscription
    closers: list[Callable[[], Awaitable[None]]] = field(default_factory=list)
    """Things to close with the container (the Web Push HTTP session)."""


def build(
    deps: ModuleDeps,
    *,
    identity: IdentityDirectory,
    schedule: ScheduleQueries,
    links: LinksApi,
    mail: MailApi,
    files: FilesApi,
    telegram: TelegramSender,
    push: PushSender | None = None,
) -> NotifyServices:
    """Wire the notify module.

    `schedule` and `mail` are accepted for the composition root's sake; the mail
    renderer is registered by the bot module (it formats mail for Telegram).
    `push` replaces the Web Push sender that `PUSH__ENABLED` would build (tests).
    """
    urls = deps.settings.urls
    push_settings = deps.settings.push
    closers: list[Callable[[], Awaitable[None]]] = []
    if push is None:
        push, push_closer = make_push_sender(push_settings)
        if push_closer is not None:
            closers.append(push_closer)

    def uow_factory() -> SqlNotifyUnitOfWork:
        return SqlNotifyUnitOfWork(
            deps.sessionmaker,
            deps.outbox_writer,
            deps.audit_writer,
            deps.outbox_committed_hook,
        )

    renderers = RendererRegistry()
    register_builtin_renderers(
        renderers, i18n=deps.i18n, urls=urls, links=links, files=files
    )
    push_delivery = (
        PushDelivery(
            uow_factory=uow_factory,
            sender=push,
            limiter=RedisSendLimiter(
                deps.redis,
                per_second=push_settings.per_second,
                key_prefix="push:send",
            ),
            i18n=deps.i18n,
            urls=urls,
            clock=deps.clock,
        )
        if push is not None
        else None
    )
    return NotifyServices(
        dispatch_due=DispatchDue(
            uow_factory=uow_factory,
            identity=identity,
            renderers=renderers,
            sender=telegram,
            limiter=RedisSendLimiter(deps.redis),
            clock=deps.clock,
            push=push_delivery,
        ),
        purge_old=PurgeOld(uow_factory=uow_factory, clock=deps.clock),
        list_notifications=ListNotifications(
            uow_factory=uow_factory,
            identity=identity,
            i18n=deps.i18n,
            urls=urls,
            clock=deps.clock,
        ),
        count_unread=CountUnread(uow_factory=uow_factory, clock=deps.clock),
        mark_read=MarkRead(uow_factory=uow_factory, clock=deps.clock),
        mark_all_read=MarkAllRead(uow_factory=uow_factory, clock=deps.clock),
        renderers=renderers,
        public=NotifyApiImpl(
            uow_factory=uow_factory,
            identity=identity,
            i18n=deps.i18n,
            urls=urls,
            clock=deps.clock,
        ),
        push_config=GetPushConfig(
            enabled=push is not None, vapid_public_key=push_settings.vapid_public_key
        ),
        register_push_subscription=RegisterPushSubscription(
            uow_factory=uow_factory,
            clock=deps.clock,
            allowed_suffixes=push_settings.endpoint_suffixes,
        ),
        remove_push_subscription=RemovePushSubscription(uow_factory=uow_factory),
        closers=closers,
    )
