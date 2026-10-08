"""Assembly of the identity module: auth services plus the EMIS part (task I1)."""

from dataclasses import dataclass

from app.modules.identity.application.register_ports import CredentialStore
from app.modules.identity.infrastructure.access_token_verifier import (
    HydraAccessTokenVerifier,
)
from app.modules.identity.infrastructure.connector_token_verifier import (
    DbConnectorTokenVerifier,
)
from app.modules.identity.infrastructure.hydra.factory import build_hydra_admin
from app.modules.identity.ports.email_sender import EmailSender
from app.modules.identity.ports.hydra_gateway import HydraGateway
from app.modules.identity.wiring_auth import AuthServices, build_auth
from app.modules.identity.wiring_emis import EmisServices, build_emis
from app.shared.contracts.academic import AcademicEnrollment
from app.shared.contracts.identity import IdentityCommands, IdentityDirectory
from app.shared.contracts.notify import TelegramSender
from app.shared.wiring import ModuleDeps


@dataclass(slots=True)
class IdentityModule:
    """`container.identity`: auth services, EMIS services and the public contracts."""

    auth: AuthServices
    directory: IdentityDirectory
    commands: IdentityCommands
    token_verifier: HydraAccessTokenVerifier
    connector_verifier: DbConnectorTokenVerifier
    emis_services: EmisServices | None = None

    @property
    def emis(self) -> EmisServices:
        """The EMIS services (only processes with Vault credentials build them)."""
        if self.emis_services is None:
            raise RuntimeError("EMIS services are not built in this process")
        return self.emis_services

    def attach_emis(
        self,
        deps: ModuleDeps,
        *,
        academic_enrollment: AcademicEnrollment,
        credentials: CredentialStore | None = None,
    ) -> EmisServices:
        """Build the EMIS part once the academic enrollment exists.

        ``credentials`` replaces the Vault store (tests and local runs without Vault).
        """
        self.emis_services = build_emis(
            deps,
            login_acceptor=self.auth.login_acceptor,
            account_revoker=self.auth.account_revoker,
            email_sender=self.auth.email_sender,
            otp_store=self.auth.otp_store,
            academic_enrollment=academic_enrollment,
            commands=self.commands,
            credentials=credentials,
        )
        return self.emis_services


def build(
    deps: ModuleDeps,
    *,
    hydra: HydraGateway | None = None,
    telegram_sender: TelegramSender | None = None,
    email_sender: EmailSender | None = None,
    academic_enrollment: AcademicEnrollment | None = None,
) -> IdentityModule:
    """Build the identity module; EMIS services need the academic enrollment.

    Without ``academic_enrollment`` the EMIS part is left out; call
    ``attach_emis`` after the academic schedule exists (processes that need it).
    """
    auth = build_auth(
        deps,
        hydra=hydra or build_hydra_admin(deps.settings),
        telegram_sender=telegram_sender,
        email_sender=email_sender,
    )
    module = IdentityModule(
        auth=auth,
        directory=auth.directory,
        commands=auth.commands,
        token_verifier=auth.token_verifier,
        connector_verifier=auth.connector_verifier,
    )
    if academic_enrollment is not None:
        module.attach_emis(deps, academic_enrollment=academic_enrollment)
    return module
