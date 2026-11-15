"""Builds the onboarding module (container.onboarding)."""

from dataclasses import dataclass

from app.modules.onboarding.application.onboarding import (
    CompleteCertificatesStep,
    GetOnboarding,
    RefreshEmisCertificates,
)
from app.modules.onboarding.infrastructure.uow import SqlOnboardingUnitOfWork
from app.modules.onboarding.ports.gateways import EmisCertificateImport, FaceGate
from app.modules.onboarding.ports.unit_of_work import UowFactory
from app.shared.wiring import ModuleDeps


@dataclass(slots=True)
class OnboardingServices:
    """Use cases of the onboarding module."""

    get_onboarding: GetOnboarding
    complete_certificates: CompleteCertificatesStep
    refresh_emis: RefreshEmisCertificates


def build(
    deps: ModuleDeps,
    *,
    faces: FaceGate,
    importer: EmisCertificateImport,
    uow_factory: UowFactory | None = None,
) -> OnboardingServices:
    """Wire the module; ``uow_factory`` replaces the SQL one in tests."""
    factory = uow_factory or _sql_uow_factory(deps)
    reader = GetOnboarding(uow_factory=factory, faces=faces, clock=deps.clock)
    return OnboardingServices(
        get_onboarding=reader,
        complete_certificates=CompleteCertificatesStep(
            uow_factory=factory, clock=deps.clock, reader=reader
        ),
        refresh_emis=RefreshEmisCertificates(
            importer=importer, limiter=deps.rate_limiter
        ),
    )


def _sql_uow_factory(deps: ModuleDeps) -> UowFactory:
    def make() -> SqlOnboardingUnitOfWork:
        return SqlOnboardingUnitOfWork(
            deps.sessionmaker,
            deps.outbox_writer,
            deps.audit_writer,
            deps.outbox_committed_hook,
        )

    return make
