"""Builds the mail module: use cases, jobs and the public MailApi."""

import asyncio
from dataclasses import dataclass

from app.modules.mail.application.check_bounces import CheckBounces
from app.modules.mail.application.config import MailConfig
from app.modules.mail.application.deliver_outbound import DeliverOutbound, Sleep
from app.modules.mail.application.forward_mail import ForwardMail
from app.modules.mail.application.list_sent_mail import ListSentMail
from app.modules.mail.application.mark_spam import MarkSpam
from app.modules.mail.application.original_mail import LoadOriginal
from app.modules.mail.application.parse_inbound import ParseInbound
from app.modules.mail.application.public_api import MailApiImpl
from app.modules.mail.application.purge_mail import PurgeMail
from app.modules.mail.application.queue_outbound import QueueOutbound
from app.modules.mail.application.receive_inbound import ReceiveInbound
from app.modules.mail.application.recent_mail import RecentMail
from app.modules.mail.application.reply_mail import ReplyMail
from app.modules.mail.application.resolve_mailbox import ResolveMailbox
from app.modules.mail.application.send_mail import SendMail
from app.modules.mail.application.send_outbound import SendOutbound
from app.modules.mail.application.sweep_mail import SweepMail
from app.modules.mail.application.view_mail import ViewMail
from app.modules.mail.infrastructure.auth.authenticator import DnsInboundAuthenticator
from app.modules.mail.infrastructure.auth.dns_txt_resolver import DnsTxtResolver
from app.modules.mail.infrastructure.relay.aiosmtplib_relay import AiosmtplibRelay
from app.modules.mail.infrastructure.relay.smtp_outbound import AiosmtplibOutbound
from app.modules.mail.infrastructure.uow import SqlMailUnitOfWork
from app.modules.mail.ports.inbound_authenticator import InboundAuthenticator
from app.modules.mail.ports.outbound_relay import OutboundRelay
from app.modules.mail.ports.outbound_smtp import OutboundSmtp
from app.modules.mail.ports.suspension import MailSuspension
from app.modules.mail.ports.txt_resolver import TxtResolver
from app.shared.contracts.files import FilesApi
from app.shared.contracts.identity import IdentityDirectory
from app.shared.redis_util import RedisKeyLock
from app.shared.wiring import ModuleDeps


@dataclass(slots=True)
class MailServices:
    """Use cases of the mail module (attribute = use case file name) and the API."""

    resolve_mailbox: ResolveMailbox
    receive_inbound: ReceiveInbound
    parse_inbound: ParseInbound
    send_mail: SendMail
    send_outbound: SendOutbound
    reply_mail: ReplyMail
    forward_mail: ForwardMail
    deliver_outbound: DeliverOutbound
    check_bounces: CheckBounces
    purge_mail: PurgeMail
    sweep_mail: SweepMail
    recent_mail: RecentMail
    list_sent_mail: ListSentMail
    view_mail: ViewMail
    mark_spam: MarkSpam
    public: MailApiImpl
    config: MailConfig


def build(
    deps: ModuleDeps,
    *,
    identity: IdentityDirectory,
    files: FilesApi,
    suspension: MailSuspension,
    resolver: TxtResolver | None = None,
    authenticator: InboundAuthenticator | None = None,
    relay: OutboundRelay | None = None,
    smtp: OutboundSmtp | None = None,
    sleep: Sleep = asyncio.sleep,
) -> MailServices:
    """Build the module; I1 passes identity, files and the suspension adapter.

    ``resolver``, ``authenticator``, ``relay`` and ``sleep`` default to the real
    DNS, SPF/DKIM/DMARC, aiosmtplib and asyncio.sleep; tests replace them.
    """
    settings = deps.settings
    config = MailConfig(
        mail_domain=settings.smtp_out.mail_domain,
        recipients_limit=settings.limits.mail_recipients,
        per_day_limit=settings.limits.mail_per_day,
        global_per_day_limit=settings.limits.mail_global_per_day,
    )

    def uow_factory() -> SqlMailUnitOfWork:
        return SqlMailUnitOfWork(
            deps.sessionmaker,
            deps.outbox_writer,
            deps.audit_writer,
            deps.outbox_committed_hook,
        )

    if authenticator is None:
        authenticator = DnsInboundAuthenticator(
            resolver or DnsTxtResolver(),
            enable_spf=settings.smtp_in.check_spf,
            enable_dkim=settings.smtp_in.check_dkim,
        )
    relay = relay or AiosmtplibRelay(settings.smtp_out)
    original = LoadOriginal(uow_factory=uow_factory, files=files)
    queue = QueueOutbound(
        uow_factory=uow_factory,
        files=files,
        identity=identity,
        suspension=suspension,
        rate_limiter=deps.rate_limiter,
        clock=deps.clock,
        kicker=deps.kicker,
        config=config,
    )
    resolve_mailbox = ResolveMailbox(identity=identity, config=config)
    recent_mail = RecentMail(uow_factory=uow_factory, clock=deps.clock)
    view_mail = ViewMail(original=original, files=files, clock=deps.clock)
    send_mail = SendMail(queue=queue)
    reply_mail = ReplyMail(original=original, queue=queue)
    forward_mail = ForwardMail(original=original, queue=queue, files=files)
    mark_spam = MarkSpam(uow_factory=uow_factory, identity=identity)
    public = MailApiImpl(
        recent=recent_mail,
        view=view_mail,
        send=send_mail,
        reply=reply_mail,
        forward=forward_mail,
        mark_spam=mark_spam,
        clock=deps.clock,
        config=config,
    )
    return MailServices(
        resolve_mailbox=resolve_mailbox,
        receive_inbound=ReceiveInbound(
            uow_factory=uow_factory,
            files=files,
            authenticator=authenticator,
            resolve_mailbox=resolve_mailbox,
            clock=deps.clock,
            kicker=deps.kicker,
            config=config,
        ),
        parse_inbound=ParseInbound(
            uow_factory=uow_factory,
            files=files,
            identity=identity,
            clock=deps.clock,
            config=config,
        ),
        send_mail=send_mail,
        send_outbound=SendOutbound(
            smtp=smtp or AiosmtplibOutbound(settings.mail.outbound),
            identity=identity,
            files=files,
            rate_limiter=deps.rate_limiter,
            uow_factory=uow_factory,
            clock=deps.clock,
            settings=settings.mail.outbound,
        ),
        reply_mail=reply_mail,
        forward_mail=forward_mail,
        deliver_outbound=DeliverOutbound(
            uow_factory=uow_factory,
            files=files,
            relay=relay,
            lock=RedisKeyLock(deps.redis),
            clock=deps.clock,
            sleep=sleep,
        ),
        check_bounces=CheckBounces(
            uow_factory=uow_factory, suspension=suspension, clock=deps.clock
        ),
        purge_mail=PurgeMail(uow_factory=uow_factory, clock=deps.clock, config=config),
        sweep_mail=SweepMail(
            uow_factory=uow_factory, kicker=deps.kicker, clock=deps.clock
        ),
        recent_mail=recent_mail,
        list_sent_mail=ListSentMail(uow_factory=uow_factory),
        view_mail=view_mail,
        mark_spam=mark_spam,
        public=public,
        config=config,
    )
