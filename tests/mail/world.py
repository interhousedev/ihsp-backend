"""The mail module wired over in-memory adapters, for use case tests."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from uuid import UUID

from app.modules.mail.application.check_bounces import CheckBounces
from app.modules.mail.application.config import MailConfig
from app.modules.mail.application.deliver_outbound import DeliverOutbound
from app.modules.mail.application.forward_mail import ForwardMail
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
from app.modules.mail.application.sweep_mail import SweepMail
from app.modules.mail.application.view_mail import ViewMail
from app.shared.contracts.identity import UserRef
from app.shared.rate_limit import RateLimiter
from app.shared.redis_util import RedisKeyLock
from tests.fakes.clock import FixedClock
from tests.fakes.tasks import FakeTaskKicker
from tests.mail.fakes import (
    FakeAuthenticator,
    FakeFilesApi,
    FakeIdentity,
    FakeMailUnitOfWork,
    FakeRelay,
    FakeSuspension,
    MailStore,
    RecordingSleep,
)
from tests.mail.helpers import ADDRESS, MAIL_DOMAIN

from redis.asyncio import Redis


@dataclass(slots=True)
class MailWorld:
    """Use cases plus the fakes behind them."""

    clock: FixedClock
    kicker: FakeTaskKicker
    identity: FakeIdentity
    files: FakeFilesApi
    suspension: FakeSuspension
    relay: FakeRelay
    authenticator: FakeAuthenticator
    sleep: RecordingSleep
    store: MailStore
    config: MailConfig
    resolve_mailbox: ResolveMailbox
    receive_inbound: ReceiveInbound
    parse_inbound: ParseInbound
    send_mail: SendMail
    reply_mail: ReplyMail
    forward_mail: ForwardMail
    deliver_outbound: DeliverOutbound
    check_bounces: CheckBounces
    purge_mail: PurgeMail
    sweep_mail: SweepMail
    recent_mail: RecentMail
    view_mail: ViewMail
    mark_spam: MarkSpam
    public: MailApiImpl
    users: list[UserRef] = field(default_factory=list)

    def student(self, login: str = "aleksey.brastilov", **kwargs: object) -> UserRef:
        """Add an active student to identity."""
        user = self.identity.add_student(login, **kwargs)  # type: ignore[arg-type]
        self.users.append(user)
        return user

    async def deliver(
        self,
        raw: bytes,
        *,
        recipients: Sequence[str] = (ADDRESS,),
        mail_from: str = "anna@example.com",
        peer_ip: str = "203.0.113.9",
        helo: str = "mx.example.com",
    ) -> list[UUID]:
        """Hand a message to ReceiveInbound like the SMTP handler does."""
        return await self.receive_inbound.execute(
            raw,
            peer_ip=peer_ip,
            helo=helo,
            mail_from=mail_from,
            recipients=recipients,
        )

    async def deliver_and_parse(self, raw: bytes, **kwargs: object) -> UUID:
        """Receive a message for the default mailbox and run the parse task."""
        created = await self.deliver(raw, **kwargs)  # type: ignore[arg-type]
        assert len(created) == 1
        await self.parse_inbound.execute(created[0])
        return created[0]


def build_world(
    clock: FixedClock, kicker: FakeTaskKicker, redis: Redis, **config: int
) -> MailWorld:
    """Wire the use cases like app.modules.mail.wiring.build, over fakes."""
    identity = FakeIdentity()
    files = FakeFilesApi()
    suspension = FakeSuspension()
    relay = FakeRelay()
    authenticator = FakeAuthenticator()
    sleep = RecordingSleep()
    store = MailStore()
    mail_config = MailConfig(
        mail_domain=MAIL_DOMAIN,
        recipients_limit=config.get("recipients_limit", 5),
        per_day_limit=config.get("per_day_limit", 20),
        global_per_day_limit=config.get("global_per_day_limit", 2000),
    )

    def uow_factory() -> FakeMailUnitOfWork:
        return FakeMailUnitOfWork(store)

    original = LoadOriginal(uow_factory=uow_factory, files=files)
    queue = QueueOutbound(
        uow_factory=uow_factory,
        files=files,
        identity=identity,
        suspension=suspension,
        rate_limiter=RateLimiter(redis),
        clock=clock,
        kicker=kicker,
        config=mail_config,
    )
    resolve_mailbox = ResolveMailbox(identity=identity, config=mail_config)
    recent_mail = RecentMail(uow_factory=uow_factory, clock=clock)
    view_mail = ViewMail(original=original, files=files, clock=clock)
    send_mail = SendMail(queue=queue)
    reply_mail = ReplyMail(original=original, queue=queue)
    forward_mail = ForwardMail(original=original, queue=queue, files=files)
    mark_spam = MarkSpam(uow_factory=uow_factory, identity=identity)
    return MailWorld(
        clock=clock,
        kicker=kicker,
        identity=identity,
        files=files,
        suspension=suspension,
        relay=relay,
        authenticator=authenticator,
        sleep=sleep,
        store=store,
        config=mail_config,
        resolve_mailbox=resolve_mailbox,
        receive_inbound=ReceiveInbound(
            uow_factory=uow_factory,
            files=files,
            authenticator=authenticator,
            resolve_mailbox=resolve_mailbox,
            clock=clock,
            kicker=kicker,
            config=mail_config,
        ),
        parse_inbound=ParseInbound(
            uow_factory=uow_factory,
            files=files,
            identity=identity,
            clock=clock,
            config=mail_config,
        ),
        send_mail=send_mail,
        reply_mail=reply_mail,
        forward_mail=forward_mail,
        deliver_outbound=DeliverOutbound(
            uow_factory=uow_factory,
            files=files,
            relay=relay,
            lock=RedisKeyLock(redis),
            clock=clock,
            sleep=sleep,
        ),
        check_bounces=CheckBounces(
            uow_factory=uow_factory, suspension=suspension, clock=clock
        ),
        purge_mail=PurgeMail(uow_factory=uow_factory, clock=clock, config=mail_config),
        sweep_mail=SweepMail(uow_factory=uow_factory, kicker=kicker, clock=clock),
        recent_mail=recent_mail,
        view_mail=view_mail,
        mark_spam=mark_spam,
        public=MailApiImpl(
            recent=recent_mail,
            view=view_mail,
            send=send_mail,
            reply=reply_mail,
            forward=forward_mail,
            mark_spam=mark_spam,
            clock=clock,
            config=mail_config,
        ),
    )
