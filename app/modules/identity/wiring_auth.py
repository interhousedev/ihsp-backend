"""Composition of the identity auth services (task B1)."""

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from app.modules.identity.application.accept_consent import AcceptConsent
from app.modules.identity.application.accept_login_for_user import LoginAcceptorImpl
from app.modules.identity.application.accept_logout import AcceptLogout
from app.modules.identity.application.account_revoker_impl import AccountRevokerImpl
from app.modules.identity.application.activate_account import ActivateAccount
from app.modules.identity.application.activation_info import ActivationInfo
from app.modules.identity.application.activation_links import ActivationLinks
from app.modules.identity.application.activation_send_email_code import (
    ActivationSendEmailCode,
)
from app.modules.identity.application.admin_reset_otp import AdminResetOtp
from app.modules.identity.application.admin_reset_password import AdminResetPassword
from app.modules.identity.application.apply_otp_resets import ApplyOtpResets
from app.modules.identity.application.auto_accept_consent import AutoAcceptConsent
from app.modules.identity.application.block_user import BlockUser
from app.modules.identity.application.cancel_otp_reset import CancelOtpReset
from app.modules.identity.application.change_password import ChangePassword
from app.modules.identity.application.change_roles import ChangeRoles
from app.modules.identity.application.confirm_email_change import ConfirmEmailChange
from app.modules.identity.application.confirm_otp_enable import ConfirmOtpEnable
from app.modules.identity.application.confirm_otp_reset import ConfirmOtpReset
from app.modules.identity.application.confirm_password_reset import (
    ConfirmPasswordReset,
)
from app.modules.identity.application.course_creators import ManageCourseCreators
from app.modules.identity.application.create_connector import CreateConnector
from app.modules.identity.application.create_staff_account import CreateStaffAccount
from app.modules.identity.application.create_teacher import CreateTeacher
from app.modules.identity.application.deactivate_teacher import DeactivateTeacher
from app.modules.identity.application.disable_otp import DisableOtp
from app.modules.identity.application.enable_otp import EnableOtp
from app.modules.identity.application.exchange_code import ExchangeCode
from app.modules.identity.application.exchange_telegram_init_data import (
    ExchangeTelegramInitData,
)
from app.modules.identity.application.get_consent_info import GetConsentInfo
from app.modules.identity.application.get_login_info import GetLoginInfo
from app.modules.identity.application.get_mcp_scopes import GetMcpScopes
from app.modules.identity.application.get_me import GetMe
from app.modules.identity.application.get_user_detail import GetUserDetail
from app.modules.identity.application.handle_token_hook import HandleTokenHook
from app.modules.identity.application.link_telegram_account import LinkTelegramAccount
from app.modules.identity.application.list_activity import ListActivity
from app.modules.identity.application.list_audit import ListAudit
from app.modules.identity.application.list_connectors import ListConnectors
from app.modules.identity.application.list_oauth_clients import ListOAuthClients
from app.modules.identity.application.list_sessions import ListSessions
from app.modules.identity.application.list_teachers import ListTeachers
from app.modules.identity.application.list_telegram_accounts import (
    ListTelegramAccounts,
)
from app.modules.identity.application.list_users import ListUsers
from app.modules.identity.application.log_in_with_otp import LogInWithOtp
from app.modules.identity.application.log_in_with_password import LogInWithPassword
from app.modules.identity.application.log_out_client import LogOutClient
from app.modules.identity.application.otp_service import OtpService
from app.modules.identity.application.password_authenticator import (
    PasswordAuthenticator,
)
from app.modules.identity.application.passwordless_otp_check import PasswordlessOtpCheck
from app.modules.identity.application.public_api import (
    IdentityCommandsImpl,
    IdentityDirectoryImpl,
)
from app.modules.identity.application.purge_deleted_users import PurgeDeletedUsers
from app.modules.identity.application.refresh_tokens import RefreshTokens
from app.modules.identity.application.request_email_change import RequestEmailChange
from app.modules.identity.application.request_login_otp import RequestLoginOtp
from app.modules.identity.application.request_otp_reset import RequestOtpReset
from app.modules.identity.application.request_password_reset import (
    RequestPasswordReset,
)
from app.modules.identity.application.request_telegram_otp import RequestTelegramOtp
from app.modules.identity.application.resume_mail import ResumeMail
from app.modules.identity.application.revoke_access import AccessRevoker
from app.modules.identity.application.revoke_connector import RevokeConnector
from app.modules.identity.application.revoke_other_sessions import RevokeOtherSessions
from app.modules.identity.application.revoke_session import RevokeSession
from app.modules.identity.application.revoke_user_sessions import RevokeUserSessions
from app.modules.identity.application.route_consent_request import RouteConsentRequest
from app.modules.identity.application.route_login_request import RouteLoginRequest
from app.modules.identity.application.route_logout_request import RouteLogoutRequest
from app.modules.identity.application.send_consent_otp import SendConsentOtp
from app.modules.identity.application.send_login_reminder import SendLoginReminder
from app.modules.identity.application.start_login_session import LoginSessionStarter
from app.modules.identity.application.step_up import StepUp
from app.modules.identity.application.suspend_mail import SuspendMail
from app.modules.identity.application.telegram_login import TelegramLogin
from app.modules.identity.application.telegram_status import TelegramStatus
from app.modules.identity.application.unblock_user import UnblockUser
from app.modules.identity.application.unlink_telegram_account import (
    UnlinkTelegramAccount,
)
from app.modules.identity.application.update_preferences import UpdatePreferences
from app.modules.identity.application.update_teacher import UpdateTeacher
from app.modules.identity.application.update_telegram_account import (
    UpdateTelegramAccount,
)
from app.modules.identity.application.verify_oauth_client import VerifyOAuthClient
from app.modules.identity.infrastructure.access_token_verifier import (
    HydraAccessTokenVerifier,
)
from app.modules.identity.infrastructure.argon2_hasher import Argon2PasswordHasher
from app.modules.identity.infrastructure.connector_token_verifier import (
    DbConnectorTokenVerifier,
)
from app.modules.identity.infrastructure.hydra.jwks import JwksCache
from app.modules.identity.infrastructure.jwt_assertion import JoseAssertionSigner
from app.modules.identity.infrastructure.mailer.smtp import SmtpEmailSender
from app.modules.identity.infrastructure.otp_sender import ChannelOtpSender
from app.modules.identity.infrastructure.redis.auth_epoch_cache import (
    RedisAuthEpochCache,
)
from app.modules.identity.infrastructure.redis.login_throttle import RedisLoginThrottle
from app.modules.identity.infrastructure.redis.otp_store import RedisOtpStore
from app.modules.identity.infrastructure.redis.revocation_list import (
    RedisRevocationList,
)
from app.modules.identity.infrastructure.redis.ticket_store import RedisTicketStore
from app.modules.identity.infrastructure.telegram.init_data import HmacInitDataVerifier
from app.modules.identity.infrastructure.uow import make_uow_factory
from app.modules.identity.ports.email_sender import EmailSender
from app.modules.identity.ports.hydra_gateway import HydraGateway
from app.modules.identity.ports.init_data_verifier import InitDataVerifier
from app.modules.identity.ports.otp_sender import OtpSender
from app.modules.identity.ports.password_hasher import PasswordHasher
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.contracts.notify import TelegramSender
from app.shared.wiring import ModuleDeps


@dataclass(slots=True)
class AuthServices:
    """Use cases of the login app, token handler, account pages and Administration."""

    # - - - Contracts and ports for other modules - - -
    directory: IdentityDirectoryImpl
    commands: IdentityCommandsImpl
    token_verifier: HydraAccessTokenVerifier
    connector_verifier: DbConnectorTokenVerifier
    login_acceptor: LoginAcceptorImpl
    account_revoker: AccountRevokerImpl
    email_sender: EmailSender
    otp_store: RedisOtpStore
    otp_sender: OtpSender
    hasher: PasswordHasher
    signer: JoseAssertionSigner
    uow_factory: UowFactory
    # - - - Login app - - -
    get_login_info: GetLoginInfo
    log_in_with_password: LogInWithPassword
    request_login_otp: RequestLoginOtp
    log_in_with_otp: LogInWithOtp
    get_consent_info: GetConsentInfo
    send_consent_otp: SendConsentOtp
    accept_consent: AcceptConsent
    accept_logout: AcceptLogout
    # - - - Hydra's login, consent and logout URLs (redirects only) - - -
    route_login_request: RouteLoginRequest
    route_consent_request: RouteConsentRequest
    route_logout_request: RouteLogoutRequest
    # - - - Token handler - - -
    exchange_code: ExchangeCode
    refresh_tokens: RefreshTokens
    log_out_client: LogOutClient
    exchange_telegram_init_data: ExchangeTelegramInitData
    handle_token_hook: HandleTokenHook
    # - - - Telegram - - -
    telegram_status: TelegramStatus
    request_telegram_otp: RequestTelegramOtp
    telegram_login: TelegramLogin
    # - - - Account - - -
    get_me: GetMe
    update_preferences: UpdatePreferences
    change_password: ChangePassword
    list_sessions: ListSessions
    revoke_session: RevokeSession
    revoke_other_sessions: RevokeOtherSessions
    list_telegram_accounts: ListTelegramAccounts
    update_telegram_account: UpdateTelegramAccount
    unlink_telegram_account: UnlinkTelegramAccount
    enable_otp: EnableOtp
    confirm_otp_enable: ConfirmOtpEnable
    disable_otp: DisableOtp
    request_email_change: RequestEmailChange
    confirm_email_change: ConfirmEmailChange
    list_activity: ListActivity
    step_up: StepUp
    list_connectors: ListConnectors
    create_connector: CreateConnector
    revoke_connector: RevokeConnector
    get_mcp_scopes: GetMcpScopes
    # - - - Recovery - - -
    request_password_reset: RequestPasswordReset
    confirm_password_reset: ConfirmPasswordReset
    request_otp_reset: RequestOtpReset
    confirm_otp_reset: ConfirmOtpReset
    cancel_otp_reset: CancelOtpReset
    apply_otp_resets: ApplyOtpResets
    send_login_reminder: SendLoginReminder
    # - - - Staff accounts - - -
    create_staff_account: CreateStaffAccount
    create_teacher: CreateTeacher
    activation_info: ActivationInfo
    activation_send_email_code: ActivationSendEmailCode
    activate_account: ActivateAccount
    # - - - Administration - - -
    list_users: ListUsers
    list_teachers: ListTeachers
    get_user_detail: GetUserDetail
    block_user: BlockUser
    unblock_user: UnblockUser
    change_roles: ChangeRoles
    manage_course_creators: ManageCourseCreators
    revoke_user_sessions: RevokeUserSessions
    admin_reset_password: AdminResetPassword
    admin_reset_otp: AdminResetOtp
    suspend_mail: SuspendMail
    resume_mail: ResumeMail
    update_teacher: UpdateTeacher
    deactivate_teacher: DeactivateTeacher
    list_audit: ListAudit
    list_oauth_clients: ListOAuthClients
    verify_oauth_client: VerifyOAuthClient
    purge_deleted_users: PurgeDeletedUsers


def build_auth(
    deps: ModuleDeps,
    *,
    hydra: HydraGateway,
    telegram_sender: TelegramSender | None = None,
    email_sender: EmailSender | None = None,
    hasher: PasswordHasher | None = None,
    init_data_verifier: InitDataVerifier | None = None,
    otp_sender: OtpSender | None = None,
    uow_factory: UowFactory | None = None,
) -> AuthServices:
    """Build every identity auth service.

    ``telegram_sender`` (B8's aiogram sender) is wired by I1; without it codes go
    to email only. The other optional arguments replace infrastructure in tests.
    """
    settings, clock, redis = deps.settings, deps.clock, deps.redis
    uow_factory = uow_factory or make_uow_factory(deps)
    email = email_sender or SmtpEmailSender(
        settings=settings.smtp_out, i18n=deps.i18n, app_name=settings.public_app_name
    )
    hasher = hasher or Argon2PasswordHasher()
    verifier = init_data_verifier or HmacInitDataVerifier(
        bot_token=settings.telegram.bot_token.get_secret_value(), clock=clock
    )
    otp_store = RedisOtpStore(redis)
    tickets = RedisTicketStore(redis)
    revocations = RedisRevocationList(redis)
    epochs = RedisAuthEpochCache(redis)
    throttle = RedisLoginThrottle(redis)
    limiter = deps.rate_limiter
    otp_sender = otp_sender or ChannelOtpSender(
        uow_factory=uow_factory,
        email=email,
        telegram=telegram_sender,
        i18n=deps.i18n,
        redis=redis,
        clock=clock,
        id_app_url=settings.urls.id,
        app_name=settings.public_app_name,
    )
    otp = OtpService(otp_store=otp_store, otp_sender=otp_sender, email=email)
    signer = JoseAssertionSigner(
        private_key_pem=settings.jwt_bearer.private_key_pem.get_secret_value(),
        key_id=settings.jwt_bearer.key_id,
        issuer=settings.jwt_bearer.issuer,
        token_url=f"{settings.hydra.issuer.rstrip('/')}/oauth2/token",
        clock=clock,
    )
    revoker = AccessRevoker(
        revocations=revocations, epochs=epochs, hydra=hydra, clock=clock
    )
    starter = LoginSessionStarter(hydra=hydra, clock=clock)
    authenticator = PasswordAuthenticator(hasher=hasher, throttle=throttle, clock=clock)
    limits = settings.limits
    passwordless = PasswordlessOtpCheck(
        otp=otp, throttle=throttle, failures_per_day=limits.otp_failures_per_day
    )
    auto_accept = AutoAcceptConsent(uow_factory=uow_factory, hydra=hydra, clock=clock)
    init_max_age = timedelta(seconds=settings.telegram.init_data_max_age_seconds)
    links = ActivationLinks(clock=clock, email=email, id_app_url=settings.urls.id)
    users = ListUsers(uow_factory=uow_factory)
    change_roles = ChangeRoles(uow_factory=uow_factory, revoker=revoker)
    update_prefs = UpdatePreferences(uow_factory=uow_factory)
    creator = CreateStaffAccount(uow_factory=uow_factory, links=links)

    async def load_epoch(user_id: UUID) -> int | None:
        async with uow_factory() as uow:
            return await uow.users.get_epoch(user_id)

    token_verifier = HydraAccessTokenVerifier(
        jwks=JwksCache(
            public_url=settings.hydra.public_url,
            ttl_seconds=settings.hydra.jwks_cache_seconds,
            clock=clock,
        ),
        issuer=settings.hydra.issuer,
        epochs=epochs,
        revocations=revocations,
        load_epoch=load_epoch,
        clock=clock,
    )
    login_info = GetLoginInfo(uow_factory=uow_factory, hydra=hydra, clock=clock)
    accept_logout = AcceptLogout(
        uow_factory=uow_factory, hydra=hydra, revocations=revocations, clock=clock
    )
    request_login_otp = RequestLoginOtp(
        uow_factory=uow_factory,
        otp=otp,
        throttle=throttle,
        rate_limiter=limiter,
        clock=clock,
        codes_per_hour=limits.otp_codes_per_hour,
        failures_per_day=limits.otp_failures_per_day,
    )
    return AuthServices(
        directory=IdentityDirectoryImpl(uow_factory=uow_factory, clock=clock),
        commands=IdentityCommandsImpl(
            uow_factory=uow_factory,
            clock=clock,
            preferences=update_prefs,
            revoker=revoker,
            kicker=deps.kicker,
        ),
        token_verifier=token_verifier,
        connector_verifier=DbConnectorTokenVerifier(
            uow_factory=uow_factory, clock=clock
        ),
        login_acceptor=LoginAcceptorImpl(
            uow_factory=uow_factory, hydra=hydra, starter=starter
        ),
        account_revoker=AccountRevokerImpl(uow_factory=uow_factory, revoker=revoker),
        email_sender=email,
        otp_store=otp_store,
        otp_sender=otp_sender,
        hasher=hasher,
        signer=signer,
        uow_factory=uow_factory,
        get_login_info=login_info,
        log_in_with_password=LogInWithPassword(
            uow_factory=uow_factory,
            hydra=hydra,
            authenticator=authenticator,
            rate_limiter=limiter,
            tickets=tickets,
            otp=otp,
            starter=starter,
        ),
        request_login_otp=request_login_otp,
        log_in_with_otp=LogInWithOtp(
            uow_factory=uow_factory,
            hydra=hydra,
            otp=otp,
            passwordless=passwordless,
            tickets=tickets,
            starter=starter,
        ),
        get_consent_info=GetConsentInfo(
            uow_factory=uow_factory, hydra=hydra, auto_accept=auto_accept
        ),
        send_consent_otp=SendConsentOtp(
            uow_factory=uow_factory, hydra=hydra, otp=otp, rate_limiter=limiter
        ),
        accept_consent=AcceptConsent(
            uow_factory=uow_factory,
            hydra=hydra,
            otp=otp,
            auto_accept=auto_accept,
            clock=clock,
        ),
        accept_logout=accept_logout,
        route_login_request=RouteLoginRequest(
            hydra=hydra, login_info=login_info, id_url=settings.urls.id
        ),
        route_consent_request=RouteConsentRequest(
            hydra=hydra, auto_accept=auto_accept, id_url=settings.urls.id
        ),
        route_logout_request=RouteLogoutRequest(
            accept_logout=accept_logout, id_url=settings.urls.id
        ),
        exchange_code=ExchangeCode(hydra=hydra),
        refresh_tokens=RefreshTokens(uow_factory=uow_factory, hydra=hydra, clock=clock),
        log_out_client=LogOutClient(
            uow_factory=uow_factory,
            hydra=hydra,
            revocations=revocations,
            clock=clock,
            # The browser follows this URL: the public issuer, not the internal address.
            logout_url=f"{settings.hydra.issuer.rstrip('/')}/oauth2/sessions/logout",
        ),
        exchange_telegram_init_data=ExchangeTelegramInitData(
            uow_factory=uow_factory,
            hydra=hydra,
            verifier=verifier,
            signer=signer,
            clock=clock,
        ),
        handle_token_hook=HandleTokenHook(
            uow_factory=uow_factory, signer=signer, clock=clock
        ),
        telegram_status=TelegramStatus(
            uow_factory=uow_factory, verifier=verifier, max_age=init_max_age
        ),
        request_telegram_otp=RequestTelegramOtp(
            verifier=verifier,
            request_login_otp=request_login_otp,
            max_age=init_max_age,
        ),
        telegram_login=TelegramLogin(
            uow_factory=uow_factory,
            verifier=verifier,
            authenticator=authenticator,
            passwordless=passwordless,
            otp=otp,
            linker=LinkTelegramAccount(email=email, clock=clock),
            max_age=init_max_age,
        ),
        get_me=GetMe(
            uow_factory=uow_factory, mail_domain=settings.smtp_out.mail_domain
        ),
        update_preferences=update_prefs,
        change_password=ChangePassword(
            uow_factory=uow_factory,
            hasher=hasher,
            revoker=revoker,
            rate_limiter=limiter,
        ),
        list_sessions=ListSessions(uow_factory=uow_factory, clock=clock),
        revoke_session=RevokeSession(uow_factory=uow_factory, revoker=revoker),
        revoke_other_sessions=RevokeOtherSessions(
            uow_factory=uow_factory, revoker=revoker
        ),
        list_telegram_accounts=ListTelegramAccounts(uow_factory=uow_factory),
        update_telegram_account=UpdateTelegramAccount(uow_factory=uow_factory),
        unlink_telegram_account=UnlinkTelegramAccount(uow_factory=uow_factory),
        enable_otp=EnableOtp(uow_factory=uow_factory, otp=otp, tickets=tickets),
        confirm_otp_enable=ConfirmOtpEnable(
            uow_factory=uow_factory, otp=otp, tickets=tickets
        ),
        disable_otp=DisableOtp(
            uow_factory=uow_factory, hasher=hasher, rate_limiter=limiter
        ),
        request_email_change=RequestEmailChange(
            uow_factory=uow_factory,
            hasher=hasher,
            otp=otp,
            tickets=tickets,
            rate_limiter=limiter,
        ),
        confirm_email_change=ConfirmEmailChange(
            uow_factory=uow_factory, otp=otp, tickets=tickets, email=email, clock=clock
        ),
        list_activity=ListActivity(uow_factory=uow_factory),
        step_up=StepUp(uow_factory=uow_factory, otp=otp),
        list_connectors=ListConnectors(uow_factory=uow_factory),
        create_connector=CreateConnector(uow_factory=uow_factory, otp=otp, clock=clock),
        revoke_connector=RevokeConnector(
            uow_factory=uow_factory, hydra=hydra, revocations=revocations, clock=clock
        ),
        get_mcp_scopes=GetMcpScopes(),
        request_password_reset=RequestPasswordReset(
            uow_factory=uow_factory, otp=otp, rate_limiter=limiter
        ),
        confirm_password_reset=ConfirmPasswordReset(
            uow_factory=uow_factory,
            otp=otp,
            hasher=hasher,
            revoker=revoker,
            rate_limiter=limiter,
        ),
        request_otp_reset=RequestOtpReset(
            uow_factory=uow_factory, otp=otp, rate_limiter=limiter
        ),
        confirm_otp_reset=ConfirmOtpReset(
            uow_factory=uow_factory, otp=otp, clock=clock, rate_limiter=limiter
        ),
        cancel_otp_reset=CancelOtpReset(uow_factory=uow_factory, email=email),
        apply_otp_resets=ApplyOtpResets(uow_factory=uow_factory, clock=clock),
        send_login_reminder=SendLoginReminder(
            uow_factory=uow_factory, email=email, rate_limiter=limiter
        ),
        create_staff_account=creator,
        create_teacher=CreateTeacher(creator=creator),
        activation_info=ActivationInfo(uow_factory=uow_factory, clock=clock),
        activation_send_email_code=ActivationSendEmailCode(
            uow_factory=uow_factory,
            otp=otp,
            tickets=tickets,
            rate_limiter=limiter,
            clock=clock,
        ),
        activate_account=ActivateAccount(
            uow_factory=uow_factory,
            hasher=hasher,
            otp=otp,
            tickets=tickets,
            revoker=revoker,
            clock=clock,
            urls={
                "admin": settings.urls.admin,
                "staff": settings.urls.staff,
                "sp": settings.urls.sp,
            },
        ),
        list_users=users,
        list_teachers=ListTeachers(users=users),
        get_user_detail=GetUserDetail(uow_factory=uow_factory, clock=clock),
        block_user=BlockUser(uow_factory=uow_factory, revoker=revoker),
        unblock_user=UnblockUser(uow_factory=uow_factory),
        change_roles=change_roles,
        manage_course_creators=ManageCourseCreators(
            users=users, change_roles=change_roles
        ),
        revoke_user_sessions=RevokeUserSessions(
            uow_factory=uow_factory, revoker=revoker
        ),
        admin_reset_password=AdminResetPassword(uow_factory=uow_factory, links=links),
        admin_reset_otp=AdminResetOtp(uow_factory=uow_factory),
        suspend_mail=SuspendMail(uow_factory=uow_factory, clock=clock),
        resume_mail=ResumeMail(uow_factory=uow_factory),
        update_teacher=UpdateTeacher(uow_factory=uow_factory, links=links),
        deactivate_teacher=DeactivateTeacher(
            uow_factory=uow_factory, revoker=revoker, kicker=deps.kicker
        ),
        list_audit=ListAudit(uow_factory=uow_factory),
        list_oauth_clients=ListOAuthClients(uow_factory=uow_factory, hydra=hydra),
        verify_oauth_client=VerifyOAuthClient(uow_factory=uow_factory, hydra=hydra),
        purge_deleted_users=PurgeDeletedUsers(uow_factory=uow_factory, clock=clock),
    )
