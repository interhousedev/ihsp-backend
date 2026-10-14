"""Builds the EMIS services of the identity module (B2)."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from app.modules.identity.application.delete_account import (
    DeleteAccount,
    TelegramNotice,
)
from app.modules.identity.application.destroy_emis_secret import DestroyEmisSecret
from app.modules.identity.application.emis_gateway import EmisGatewayImpl
from app.modules.identity.application.finalize_account_deletions import (
    FinalizeAccountDeletions,
)
from app.modules.identity.application.reclaim_complete import CompleteReclaim
from app.modules.identity.application.reclaim_email_code import SendReclaimEmailCode
from app.modules.identity.application.reclaim_start import StartReclaim
from app.modules.identity.application.register_complete import CompleteRegistration
from app.modules.identity.application.register_email_code import (
    SendRegistrationEmailCode,
)
from app.modules.identity.application.register_emis_login import VerifyEmisCredentials
from app.modules.identity.application.register_models import (
    PendingReclaim,
    PendingRegistration,
)
from app.modules.identity.application.register_ports import (
    AccountRevokerPort,
    CredentialStore,
    EmailSenderPort,
    EmisApi,
    LoginAcceptorPort,
    OtpPort,
    PasswordHasher,
)
from app.modules.identity.application.register_start import StartRegistration
from app.modules.identity.application.register_verification import EmailVerifier
from app.modules.identity.application.update_emis_password import UpdateEmisPassword
from app.modules.identity.infrastructure.emis.client import EmisClient
from app.modules.identity.infrastructure.emis.fake import FakeEmisClient
from app.modules.identity.infrastructure.emis.password_hasher import (
    Argon2PasswordHasher,
)
from app.modules.identity.infrastructure.emis.pending_store import RedisPendingStore
from app.modules.identity.infrastructure.emis.uow import EmisSqlUnitOfWork
from app.modules.identity.infrastructure.vault.client import VaultCredentialStore
from app.shared.contracts.academic import AcademicEnrollment
from app.shared.contracts.identity import IdentityCommands
from app.shared.wiring import ModuleDeps


@dataclass(slots=True)
class EmisServices:
    """``container.identity.emis``: use cases (names = file names) and the gateway."""

    gateway: EmisGatewayImpl
    register_start: StartRegistration
    register_email_code: SendRegistrationEmailCode
    register_complete: CompleteRegistration
    reclaim_start: StartReclaim
    reclaim_email_code: SendReclaimEmailCode
    reclaim_complete: CompleteReclaim
    update_emis_password: UpdateEmisPassword
    delete_account: DeleteAccount
    finalize_account_deletions: FinalizeAccountDeletions
    destroy_emis_secret: DestroyEmisSecret
    closers: list[Callable[[], Awaitable[None]]] = field(default_factory=list)

    async def close(self) -> None:
        """Close the EMIS HTTP client."""
        for closer in self.closers:
            await closer()


def build_emis(
    deps: ModuleDeps,
    *,
    login_acceptor: LoginAcceptorPort,
    account_revoker: AccountRevokerPort,
    email_sender: EmailSenderPort,
    otp_store: OtpPort,
    academic_enrollment: AcademicEnrollment,
    commands: IdentityCommands | None = None,
    emis_client: EmisApi | None = None,
    deletion_telegram_notice: TelegramNotice | None = None,
    credentials: CredentialStore | None = None,
    password_hasher: PasswordHasher | None = None,
) -> EmisServices:
    """Wire the use cases; ``commands`` is accepted for § 3.12 but not needed.

    ``emis_client``, ``credentials`` and ``password_hasher`` replace the real
    adapters in tests; by default they come from ``EMIS__MODE`` and ``VAULT__*``.
    """
    settings = deps.settings
    closers: list[Callable[[], Awaitable[None]]] = []
    emis: EmisApi
    if emis_client is not None:
        emis = emis_client
    elif settings.emis.mode == "fake":
        emis = FakeEmisClient(deps.clock)
    else:
        http_client = EmisClient.from_settings(settings.emis)
        closers.append(http_client.aclose)
        emis = http_client
    store = credentials or VaultCredentialStore(settings.vault)
    hasher = password_hasher or Argon2PasswordHasher()

    def uow_factory() -> EmisSqlUnitOfWork:
        return EmisSqlUnitOfWork(
            deps.sessionmaker,
            deps.outbox_writer,
            deps.audit_writer,
            deps.outbox_committed_hook,
        )

    pending_registrations = RedisPendingStore(
        deps.redis, prefix="reg", model=PendingRegistration
    )
    pending_reclaims = RedisPendingStore(
        deps.redis, prefix="reclaim", model=PendingReclaim
    )
    verify = VerifyEmisCredentials(
        emis=emis,
        store=store,
        rate_limiter=deps.rate_limiter,
        institution_id=settings.emis.institution_id,
    )
    verifier = EmailVerifier(
        uow_factory=uow_factory,
        otp=otp_store,
        email_sender=email_sender,
        rate_limiter=deps.rate_limiter,
    )
    destroy_secret = DestroyEmisSecret(store=store, uow_factory=uow_factory)
    return EmisServices(
        gateway=EmisGatewayImpl(
            emis=emis,
            store=store,
            uow_factory=uow_factory,
            # only the fake EMIS answers without a stored secret
            fake_tokens=emis if isinstance(emis, FakeEmisClient) else None,
        ),
        register_start=StartRegistration(
            verify=verify,
            emis=emis,
            pending=pending_registrations,
            uow_factory=uow_factory,
            enrollment=academic_enrollment,
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
            enrollment=academic_enrollment,
            login_acceptor=login_acceptor,
            kicker=deps.kicker,
            clock=deps.clock,
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
            revoker=account_revoker,
            email_sender=email_sender,
            clock=deps.clock,
        ),
        update_emis_password=UpdateEmisPassword(
            emis=emis,
            store=store,
            uow_factory=uow_factory,
            rate_limiter=deps.rate_limiter,
            kicker=deps.kicker,
        ),
        delete_account=DeleteAccount(
            uow_factory=uow_factory,
            hasher=hasher,
            otp=otp_store,
            revoker=account_revoker,
            email_sender=email_sender,
            clock=deps.clock,
            telegram_notice=deletion_telegram_notice,
            retention_days=deps.settings.identity.account_deletion_days,
        ),
        finalize_account_deletions=FinalizeAccountDeletions(
            uow_factory=uow_factory,
            revoker=account_revoker,
            enrollment=academic_enrollment,
            kicker=deps.kicker,
            clock=deps.clock,
            retention_days=deps.settings.identity.account_deletion_days,
        ),
        destroy_emis_secret=destroy_secret,
        closers=closers,
    )
