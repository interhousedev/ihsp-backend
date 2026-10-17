"""Composition of the sign-in factors: authenticator app (TOTP) and passkeys."""

from dataclasses import dataclass

from app.modules.identity.application.factor_support import TotpVerifier
from app.modules.identity.application.log_in_with_passkey import LogInWithPasskey
from app.modules.identity.application.log_in_with_totp import LogInWithTotp
from app.modules.identity.application.manage_passkeys import ManagePasskeys
from app.modules.identity.application.manage_totp import ManageTotp
from app.modules.identity.application.restore_account import RestoreOffer
from app.modules.identity.application.start_login_session import LoginSessionStarter
from app.modules.identity.ports.hydra_gateway import HydraGateway
from app.modules.identity.ports.secret_cipher import SecretCipher
from app.modules.identity.ports.ticket_store import TicketStore
from app.modules.identity.ports.unit_of_work import UowFactory
from app.modules.identity.ports.webauthn import WebAuthn
from app.shared.clock import Clock
from app.shared.rate_limit import RateLimiter


@dataclass(slots=True)
class FactorServices:
    """Use cases of the IHT ID security settings and the second login steps."""

    manage_totp: ManageTotp
    log_in_with_totp: LogInWithTotp
    manage_passkeys: ManagePasskeys
    log_in_with_passkey: LogInWithPasskey


def build_factors(
    *,
    uow_factory: UowFactory,
    hydra: HydraGateway,
    cipher: SecretCipher,
    webauthn: WebAuthn,
    tickets: TicketStore,
    starter: LoginSessionStarter,
    rate_limiter: RateLimiter,
    clock: Clock,
    restore_offer: RestoreOffer | None,
) -> FactorServices:
    """Wire the factor use cases from the shared auth infrastructure."""
    verifier = TotpVerifier(cipher=cipher, clock=clock)
    return FactorServices(
        manage_totp=ManageTotp(
            uow_factory=uow_factory,
            cipher=cipher,
            tickets=tickets,
            verifier=verifier,
            rate_limiter=rate_limiter,
            clock=clock,
        ),
        log_in_with_totp=LogInWithTotp(
            uow_factory=uow_factory,
            hydra=hydra,
            tickets=tickets,
            verifier=verifier,
            starter=starter,
            rate_limiter=rate_limiter,
        ),
        manage_passkeys=ManagePasskeys(
            uow_factory=uow_factory, webauthn=webauthn, tickets=tickets, clock=clock
        ),
        log_in_with_passkey=LogInWithPasskey(
            uow_factory=uow_factory,
            hydra=hydra,
            webauthn=webauthn,
            tickets=tickets,
            starter=starter,
            rate_limiter=rate_limiter,
            clock=clock,
            restore_offer=restore_offer,
        ),
    )
