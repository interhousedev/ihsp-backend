"""Registers the renderers that the notify module owns."""

from app.modules.notify.application.renderers.account_closing import (
    AccountClosingRenderer,
)
from app.modules.notify.application.renderers.broadcast import BroadcastRenderer
from app.modules.notify.application.renderers.emis_reauth import EmisReauthRenderer
from app.modules.notify.application.renderers.files_expiring import (
    FilesExpiringRenderer,
)
from app.modules.notify.application.renderers.lesson_changed import (
    LessonChangedRenderer,
)
from app.modules.notify.application.renderers.lesson_resources import (
    LessonResourcesRenderer,
)
from app.modules.notify.application.renderers.login_failures import (
    LoginFailuresRenderer,
)
from app.modules.notify.application.renderers.mail_bounced import MailBouncedRenderer
from app.modules.notify.application.renderers.mail_suspended import (
    MailSuspendedRenderer,
)
from app.modules.notify.application.renderers.marks import MarksRenderer
from app.modules.notify.application.renderers.registry import RendererRegistry
from app.modules.notify.application.renderers.result_below import ResultBelowRenderer
from app.modules.notify.application.renderers.result_drop import ResultDropRenderer
from app.modules.notify.application.renderers.sync_alert import SyncAlertRenderer
from app.settings import UrlsSettings
from app.shared.contracts.files import FilesApi
from app.shared.contracts.links import LinksApi
from app.shared.i18n.core import I18nCore
from app.shared.notifications import NotificationType


def register_builtin_renderers(
    registry: RendererRegistry,
    *,
    i18n: I18nCore,
    urls: UrlsSettings,
    links: LinksApi,
    files: FilesApi,
) -> None:
    """Add renderers for every type except those the bot module registers."""
    registry.register(NotificationType.MARKS, MarksRenderer(i18n, urls))
    registry.register(NotificationType.RESULT_DROP, ResultDropRenderer(i18n, urls))
    registry.register(NotificationType.RESULT_BELOW, ResultBelowRenderer(i18n, urls))
    registry.register(
        NotificationType.LESSON_RESOURCES, LessonResourcesRenderer(i18n, urls, links)
    )
    registry.register(
        NotificationType.LESSON_CHANGED, LessonChangedRenderer(i18n, urls)
    )
    registry.register(NotificationType.MAIL_BOUNCED, MailBouncedRenderer(i18n, urls))
    registry.register(NotificationType.BROADCAST, BroadcastRenderer(i18n, files))
    registry.register(NotificationType.EMIS_REAUTH, EmisReauthRenderer(i18n, urls))
    registry.register(
        NotificationType.FILES_EXPIRING, FilesExpiringRenderer(i18n, urls)
    )
    registry.register(
        NotificationType.LOGIN_FAILURES, LoginFailuresRenderer(i18n, urls)
    )
    registry.register(
        NotificationType.ACCOUNT_CLOSING, AccountClosingRenderer(i18n, urls)
    )
    registry.register(
        NotificationType.MAIL_SUSPENDED, MailSuspendedRenderer(i18n, urls)
    )
    registry.register(NotificationType.SYNC_ALERT, SyncAlertRenderer(i18n, urls))
