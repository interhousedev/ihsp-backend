"""Use cases of the onboarding wizard."""

from app.modules.onboarding.domain.steps import Onboarding, Progress, plan
from app.modules.onboarding.ports.gateways import EmisCertificateImport, FaceGate
from app.modules.onboarding.ports.unit_of_work import UowFactory
from app.shared.actor import Actor, Role
from app.shared.clock import Clock
from app.shared.rate_limit import RateLimiter

REFRESH_LIMIT = 3
REFRESH_WINDOW_SECONDS = 600


class GetOnboarding:
    """The steps the caller still has to see."""

    def __init__(
        self, *, uow_factory: UowFactory, faces: FaceGate, clock: Clock
    ) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._faces = faces
        self._clock = clock

    async def execute(self, actor: Actor) -> Onboarding:
        """Return the steps; non-students get none."""
        if not actor.has(Role.STUDENT):
            return plan(is_student=False, has_face=True, certificates_done=True)
        has_face = await self._faces.has_face(actor.user_id)
        async with self._uow_factory() as uow:
            progress = await uow.progress.get(actor.user_id)
            done = progress is not None and progress.certificates_prompt_done_at
            result = plan(
                is_student=True, has_face=has_face, certificates_done=bool(done)
            )
            if progress is not None and not result.steps and not progress.completed_at:
                progress.completed_at = self._clock.now()
                await uow.progress.save(progress)
                await uow.commit()
        return result


class CompleteCertificatesStep:
    """The student finished or skipped the certificates prompt."""

    def __init__(
        self, *, uow_factory: UowFactory, clock: Clock, reader: GetOnboarding
    ) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._clock = clock
        self._reader = reader

    async def execute(self, actor: Actor) -> Onboarding:
        """Mark the prompt done (the first time counts) and return the new state."""
        actor.require(Role.STUDENT)
        now = self._clock.now()
        async with self._uow_factory() as uow:
            progress = await uow.progress.get(actor.user_id)
            if progress is None:
                progress = Progress(actor.user_id, created_at=now)
            if progress.certificates_prompt_done_at is None:
                progress.certificates_prompt_done_at = now
                await uow.progress.save(progress)
                await uow.commit()
        return await self._reader.execute(actor)


class RefreshEmisCertificates:
    """The student pulls their certificates from EMIS again."""

    def __init__(
        self, *, importer: EmisCertificateImport, limiter: RateLimiter
    ) -> None:
        """Store the dependencies."""
        self._importer = importer
        self._limiter = limiter

    async def execute(self, actor: Actor) -> None:
        """Run the import; raises `RateLimitedError` when called too often."""
        actor.require(Role.STUDENT)
        await self._limiter.hit(
            f"onboarding:emis:{actor.user_id}",
            limit=REFRESH_LIMIT,
            window_seconds=REFRESH_WINDOW_SECONDS,
        )
        await self._importer.refresh(actor.user_id)
