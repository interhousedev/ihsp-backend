"""LMS-12: the daily task `lms.prune_revisions` runs the prune use case."""

from types import SimpleNamespace

from app.interfaces.jobs.context import set_container
from app.interfaces.jobs.tasks.lms.prune_revisions import prune_revisions
from app.modules.lms.wiring_authoring import AuthoringServices
from tests.fakes.clock import FixedClock
from tests.lms.authoring.conftest import CourseFixture
from tests.lms.authoring.helpers import set_blocks, text_block


async def test_the_task_deletes_old_previews_and_reports_counts(
    services: AuthoringServices, course: CourseFixture, clock: FixedClock
) -> None:
    """The task is registered under its wire name and prunes through the container."""
    owner = course.team.owner
    section = await services.create_section.execute(owner, course.id, "Limits")
    step = await services.create_step.execute(
        owner, course.id, section_id=section.id, title="Intro"
    )
    await set_blocks(services, owner, step, text_block("preview"))
    await services.ensure_preview_revision.execute(step.step_id, owner)
    clock.advance(days=31)
    set_container(SimpleNamespace(lms=SimpleNamespace(authoring=services)))

    result = await prune_revisions()

    assert result == {"checkpoints": 0, "previews": 1}
    assert prune_revisions.task_name == "lms.prune_revisions"
