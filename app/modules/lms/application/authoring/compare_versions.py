"""Use case: compare two published versions step by step (LMS-11)."""

from uuid import UUID

from app.modules.lms.application.authoring.access import access_to, load_course
from app.modules.lms.application.authoring.uow_factory import UowFactory
from app.modules.lms.application.authoring.views import (
    CompareStepView,
    VersionCompareView,
)
from app.modules.lms.domain.authoring.compare import compare_manifests
from app.modules.lms.domain.authoring.errors import VersionNotFoundError
from app.modules.lms.domain.authoring.manifest import manifest_steps, parse_manifest
from app.shared.actor import Actor


class CompareVersions:
    """Compare revision IDs per step; content diffs are fetched on demand."""

    def __init__(self, uow_factory: UowFactory) -> None:
        """Store the unit of work factory."""
        self.uow_factory = uow_factory

    async def execute(
        self, actor: Actor, course_id: UUID, a: int, b: int
    ) -> VersionCompareView:
        """Return which steps are the same, changed, added or removed from A to B."""
        async with self.uow_factory() as uow:
            await load_course(uow, course_id)
            access = await access_to(uow, actor, course_id)
            access.require_staff()
            first = await uow.versions.get_by_number(course_id, a)
            second = await uow.versions.get_by_number(course_id, b)
            if first is None or second is None:
                raise VersionNotFoundError(params={"a": a, "b": b})
        rows = compare_manifests(
            manifest_steps(parse_manifest(first.outline)),
            manifest_steps(parse_manifest(second.outline)),
        )
        return VersionCompareView(
            a=a,
            b=b,
            steps=[
                CompareStepView(
                    step_id=r.step_id,
                    title=r.title,
                    change=r.change.value,
                    revision_a=r.revision_a,
                    revision_b=r.revision_b,
                )
                for r in rows
            ],
        )
