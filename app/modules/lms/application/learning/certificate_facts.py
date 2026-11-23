"""LMS side of the course certificates contract."""

from collections.abc import Awaitable, Callable
from decimal import Decimal
from uuid import UUID

from app.modules.lms.application.learning.audience import AudienceGate
from app.modules.lms.application.learning.step_points import load_course_points
from app.modules.lms.domain.learning.live import RenderCache
from app.modules.lms.ports.learning.unit_of_work import LearningUnitOfWork
from app.shared.contracts.course_certificates import (
    CertificateCourse,
    CertificateSection,
    LearnerResult,
    LearnerSection,
)


class LmsCertificateFacts:
    """Course facts and learner results over the steps each learner may open."""

    def __init__(
        self,
        uow_factory: Callable[[], LearningUnitOfWork],
        gate: AudienceGate,
        can_manage: Callable[[UUID, UUID], Awaitable[bool]],
    ) -> None:
        """Keep the collaborators."""
        self._uow_factory = uow_factory
        self._gate = gate
        self._cache = RenderCache()
        self._can_manage = can_manage

    async def course(self, course_id: UUID) -> CertificateCourse | None:
        """Return the course with its live sections."""
        async with self._uow_factory() as uow:
            course = await uow.courses.get(course_id)
            if course is None:
                return None
            sections: tuple[CertificateSection, ...] = ()
            if course.live_version_id is not None:
                version = await uow.versions.get(course.live_version_id)
                if version is not None:
                    sections = tuple(
                        CertificateSection(s.id, s.title)
                        for s in version.manifest.sections
                    )
            public = str(getattr(course.visibility, "value", course.visibility))
            return CertificateCourse(
                course.id, course.title, public == "public", sections
            )

    async def learner(self, course_id: UUID, user_id: UUID) -> LearnerResult | None:
        """Return steps done and points per section of the live version."""
        async with self._uow_factory() as uow:
            course = await uow.courses.get(course_id)
            enrollment = await uow.enrollments.get(course_id, user_id)
            if course is None or enrollment is None or not course.live_version_id:
                return None
            version = await uow.versions.get(course.live_version_id)
            if version is None:
                return None
            actor = await self._gate.actor_for(user_id)
            access = await self._gate.course(uow, actor, course_id)
            readable = set(access.readable(version.manifest.step_ids()))
            done = set(await uow.states.completed_step_ids(user_id, list(readable)))
            points = await load_course_points(
                uow, self._cache, version, user_id, access
            )
            sections: list[LearnerSection] = []
            for section in version.manifest.sections:
                ids = [s.step_id for s in section.steps if s.step_id in readable]
                scored = [points.steps[i] for i in ids if i in points.steps]
                sections.append(
                    LearnerSection(
                        section_id=section.id,
                        steps_total=len(ids),
                        steps_done=sum(1 for i in ids if i in done),
                        points_total=sum((p.total for p in scored), Decimal(0)),
                        points_earned=sum((p.earned for p in scored), Decimal(0)),
                    )
                )
            return LearnerResult(user_id, enrollment.progress_pct, tuple(sections))

    async def active_learners(self, course_id: UUID) -> list[UUID]:
        """Return the enrolled learners with some progress."""
        async with self._uow_factory() as uow:
            rows = await uow.enrollments.list_for_course(course_id)
        return [e.user_id for e in rows if e.progress_pct > 0]

    async def can_manage(self, user_id: UUID, course_id: UUID) -> bool:
        """Return whether the user may edit the course."""
        return await self._can_manage(user_id, course_id)
