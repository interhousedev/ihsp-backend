"""The EMIS use cases wired to fakes, plus helpers that walk through whole flows."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.identity.application.delete_account import DeleteAccount
from app.modules.identity.application.destroy_emis_secret import DestroyEmisSecret
from app.modules.identity.application.emis_gateway import EmisGatewayImpl
from app.modules.identity.application.reclaim_complete import CompleteReclaim
from app.modules.identity.application.reclaim_email_code import SendReclaimEmailCode
from app.modules.identity.application.reclaim_start import StartReclaim
from app.modules.identity.application.register_complete import (
    CompleteRegistration,
    RegisteredStudent,
)
from app.modules.identity.application.register_email_code import (
    SendRegistrationEmailCode,
)
from app.modules.identity.application.register_emis_login import VerifyEmisCredentials
from app.modules.identity.application.register_models import (
    PendingReclaim,
    PendingRegistration,
)
from app.modules.identity.application.register_ports import UnitOfWorkFactory
from app.modules.identity.application.register_start import (
    StartedRegistration,
    StartRegistration,
)
from app.modules.identity.application.register_verification import EmailVerifier
from app.modules.identity.application.update_emis_password import UpdateEmisPassword
from app.modules.identity.infrastructure.emis.pending_store import RedisPendingStore
from app.shared.rate_limit import RateLimiter
from tests.fakes.clock import FixedClock
from tests.fakes.identity.vault import InMemoryCredentialStore
from tests.fakes.tasks import FakeTaskKicker
from tests.identity.emis.fakes import (
    ControlledEmis,
    FakeAccountRevoker,
    FakeEmailSender,
    FakeEmisUnitOfWork,
    FakeEnrollment,
    FakeLoginAcceptor,
    FakeOtpStore,
    InMemoryAccountRepository,
    Ledger,
    PlainHasher,
)

from fakeredis.aioredis import FakeRedis

INSTITUTION_ID = 10815
NEW_PASSWORD = "Secret123"


@dataclass(slots=True)
class World:
    """Every use case of task B2 and the fakes behind them."""

    emis: ControlledEmis
    store: InMemoryCredentialStore
    repo: InMemoryAccountRepository
    ledger: Ledger
    enrollment: FakeEnrollment
    acceptor: FakeLoginAcceptor
    revoker: FakeAccountRevoker
    emails: FakeEmailSender
    otp: FakeOtpStore
    redis: FakeRedis
    clock: FixedClock
    kicker: FakeTaskKicker
    register_start: StartRegistration
    register_email_code: SendRegistrationEmailCode
    register_complete: CompleteRegistration
    reclaim_start: StartReclaim
    reclaim_email_code: SendReclaimEmailCode
    reclaim_complete: CompleteReclaim
    update_emis_password: UpdateEmisPassword
    delete_account: DeleteAccount
    destroy_emis_secret: DestroyEmisSecret
    gateway: EmisGatewayImpl
    pending_registrations: RedisPendingStore[PendingRegistration]
    pending_reclaims: RedisPendingStore[PendingReclaim]

    async def register(
        self,
        emis_login: str = "student01",
        *,
        email: str = "aleksey@example.com",
        password: str = NEW_PASSWORD,
        ip: str = "10.0.0.1",
        challenge: str | None = None,
    ) -> tuple[StartedRegistration, RegisteredStudent]:
        """Walk the whole registration flow and return both results."""
        started = await self.register_start.execute(
            emis_login=emis_login, emis_password="password", ip=ip, locale="en"
        )
        token = started.registration_token
        await self.register_email_code.execute(registration_token=token, email=email)
        registered = await self.register_complete.execute(
            registration_token=token,
            password=password,
            email_code=self.emails.last_code(),
            confirm_import_match=True,
            login_challenge=challenge,
            ip=ip,
            user_agent="pytest",
        )
        return started, registered

    def secret_ref_of(self, user_id: UUID) -> UUID:
        """The Vault reference of a registered user."""
        ref = self.repo.accounts[user_id].emis_vault_ref
        assert ref is not None
        return ref


def build_world(
    redis: FakeRedis,
    clock: FixedClock,
    kicker: FakeTaskKicker,
    uow_factory: UnitOfWorkFactory | None = None,
) -> World:
    """Wire the use cases exactly like wiring_emis.build_emis, with fakes.

    ``uow_factory`` swaps the in-memory accounts for the real SQL unit of work.
    """
    emis = ControlledEmis(clock)
    store = InMemoryCredentialStore()
    repo = InMemoryAccountRepository()
    ledger = Ledger()
    enrollment = FakeEnrollment()
    acceptor = FakeLoginAcceptor()
    revoker = FakeAccountRevoker()
    emails = FakeEmailSender()
    otp = FakeOtpStore()
    hasher = PlainHasher()
    limiter = RateLimiter(redis)
    pending_registrations = RedisPendingStore(
        redis, prefix="reg", model=PendingRegistration
    )
    pending_reclaims = RedisPendingStore(redis, prefix="reclaim", model=PendingReclaim)

    def in_memory() -> FakeEmisUnitOfWork:
        return FakeEmisUnitOfWork(repo, ledger)

    uow_factory = uow_factory or in_memory

    verify = VerifyEmisCredentials(
        emis=emis, store=store, rate_limiter=limiter, institution_id=INSTITUTION_ID
    )
    verifier = EmailVerifier(
        uow_factory=uow_factory, otp=otp, email_sender=emails, rate_limiter=limiter
    )
    destroy = DestroyEmisSecret(store=store, uow_factory=uow_factory)
    return World(
        emis=emis,
        store=store,
        repo=repo,
        ledger=ledger,
        enrollment=enrollment,
        acceptor=acceptor,
        revoker=revoker,
        emails=emails,
        otp=otp,
        redis=redis,
        clock=clock,
        kicker=kicker,
        register_start=StartRegistration(
            verify=verify,
            emis=emis,
            pending=pending_registrations,
            uow_factory=uow_factory,
            enrollment=enrollment,
        ),
        register_email_code=SendRegistrationEmailCode(
            pending=pending_registrations, verifier=verifier
        ),
        register_complete=CompleteRegistration(
            pending=pending_registrations,
            verifier=verifier,
            store=store,
            hasher=hasher,
            uow_factory=uow_factory,
            enrollment=enrollment,
            login_acceptor=acceptor,
            kicker=kicker,
            clock=clock,
        ),
        reclaim_start=StartReclaim(
            verify=verify, pending=pending_reclaims, uow_factory=uow_factory
        ),
        reclaim_email_code=SendReclaimEmailCode(
            pending=pending_reclaims, verifier=verifier
        ),
        reclaim_complete=CompleteReclaim(
            pending=pending_reclaims,
            verifier=verifier,
            store=store,
            hasher=hasher,
            uow_factory=uow_factory,
            revoker=revoker,
            email_sender=emails,
            clock=clock,
        ),
        update_emis_password=UpdateEmisPassword(
            emis=emis,
            store=store,
            uow_factory=uow_factory,
            rate_limiter=limiter,
            kicker=kicker,
        ),
        delete_account=DeleteAccount(
            uow_factory=uow_factory,
            hasher=hasher,
            otp=otp,
            revoker=revoker,
            enrollment=enrollment,
            destroy_secret=destroy,
            email_sender=emails,
            kicker=kicker,
            clock=clock,
        ),
        destroy_emis_secret=destroy,
        gateway=EmisGatewayImpl(emis=emis, store=store, uow_factory=uow_factory),
        pending_registrations=pending_registrations,
        pending_reclaims=pending_reclaims,
    )
