"""GET /v1/me/onboarding and the certificates step."""

from app.interfaces.http.v1.certificates.schemas import CertificateEntryResponse
from app.interfaces.http.v1.onboarding.deps import (
    AnyActor,
    ContainerDep,
    StudentActor,
)
from app.interfaces.http.v1.onboarding.schemas import OnboardingOut, RefreshEmisOut


async def get_onboarding(container: ContainerDep, actor: AnyActor) -> OnboardingOut:
    """The steps the caller still has to see (none unless they are a student)."""
    return OnboardingOut.of(await container.onboarding.get_onboarding.execute(actor))


async def certificates_done(
    container: ContainerDep, actor: StudentActor
) -> OnboardingOut:
    """Mark the certificates step done or skipped; it is not shown again."""
    state = await container.onboarding.complete_certificates.execute(actor)
    return OnboardingOut.of(state)


async def refresh_emis(container: ContainerDep, actor: StudentActor) -> RefreshEmisOut:
    """Import the caller's EMIS certificates again and return all their entries."""
    await container.onboarding.refresh_emis.execute(actor)
    entries = await container.certificates.list_my_entries.execute(actor.user_id)
    return RefreshEmisOut(
        entries=[CertificateEntryResponse.from_domain(e) for e in entries]
    )
