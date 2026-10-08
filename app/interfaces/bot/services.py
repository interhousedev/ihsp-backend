"""The contract objects the bot uses, resolved once from the container."""

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from app.interfaces.bot.urls import BotUrls
from app.settings import Settings
from app.shared.clock import Clock
from app.shared.contracts.academic import (
    ClassworkCommands,
    ClassworkQueries,
    MarksQueries,
    ScheduleQueries,
)
from app.shared.contracts.files import FilesApi
from app.shared.contracts.identity import IdentityCommands, IdentityDirectory
from app.shared.contracts.links import LinksApi
from app.shared.contracts.mail import MailApi
from app.shared.contracts.notify import NotifyApi
from app.shared.i18n.core import I18nCore

from redis.asyncio import Redis


class CancelOtpReset(Protocol):
    """The identity use case ``cancel_otp_reset`` (called with the request id)."""

    async def execute(self, request_id: UUID, /) -> object:
        """Cancel the pending OTP reset."""
        ...


@dataclass(frozen=True, slots=True)
class BotServices:
    """Everything handlers need, typed by contract."""

    settings: Settings
    clock: Clock
    redis: Redis
    i18n: I18nCore
    urls: BotUrls
    directory: IdentityDirectory
    identity_commands: IdentityCommands
    cancel_otp_reset: CancelOtpReset
    schedule: ScheduleQueries
    classwork_queries: ClassworkQueries
    classwork: ClassworkCommands
    marks: MarksQueries
    links: LinksApi
    files: FilesApi
    mail: MailApi
    notify: NotifyApi


def services_from_container(container: Any) -> BotServices:
    """Pick the contract objects out of the container (paths of FINAL_PLAN § 3.12)."""
    settings: Settings = container.settings
    return BotServices(
        settings=settings,
        clock=container.clock,
        redis=container.redis,
        i18n=container.i18n,
        urls=BotUrls.from_settings(settings.urls),
        directory=container.identity.directory,
        identity_commands=container.identity.commands,
        cancel_otp_reset=container.identity.auth.cancel_otp_reset,
        schedule=container.academic.schedule.queries,
        classwork_queries=container.academic.classwork.queries,
        classwork=container.academic.classwork.commands,
        marks=container.academic.marks.queries,
        links=container.links.public,
        files=container.files.public,
        mail=container.mail.public,
        notify=container.notify.public,
    )
