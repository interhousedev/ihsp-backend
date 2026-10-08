"""Builds the notify services (task B8)."""

from dataclasses import dataclass

from app.modules.notify.application.count_unread import CountUnread
from app.modules.notify.application.dispatch_due import DispatchDue
from app.modules.notify.application.list_notifications import ListNotifications
from app.modules.notify.application.mark_all_read import MarkAllRead
from app.modules.notify.application.mark_read import MarkRead
from app.modules.notify.application.public_api import NotifyApiImpl
from app.modules.notify.application.purge_old import PurgeOld
from app.modules.notify.application.renderers.builtin import register_builtin_renderers
from app.modules.notify.application.renderers.registry import RendererRegistry
from app.modules.notify.infrastructure.redis_send_limiter import RedisSendLimiter
from app.modules.notify.infrastructure.uow import SqlNotifyUnitOfWork
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


def build(
    deps: ModuleDeps,
    *,
    identity: IdentityDirectory,
    schedule: ScheduleQueries,
    links: LinksApi,
    mail: MailApi,
    files: FilesApi,
    telegram: TelegramSender,
) -> NotifyServices:
    """Wire the notify module.

    `schedule` and `mail` are accepted for the composition root's sake; the mail
    renderer is registered by the bot module (it formats mail for Telegram).
    """
    urls = deps.settings.urls

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
    return NotifyServices(
        dispatch_due=DispatchDue(
            uow_factory=uow_factory,
            identity=identity,
            renderers=renderers,
            sender=telegram,
            limiter=RedisSendLimiter(deps.redis),
            clock=deps.clock,
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
    )
