"""LMS-8, UF-LMS-09: preview of pending changes as a student."""

import json
from uuid import uuid4

from app.modules.lms.domain.authoring.enums import Visibility
from app.modules.lms.domain.authoring.errors import (
    CoursePermissionError,
    StepNotFoundError,
)
from app.modules.lms.wiring_authoring import AuthoringServices
from tests.fakes.clock import FixedClock
from tests.lms.authoring.conftest import CourseFixture
from tests.lms.authoring.helpers import (
    quiz_block,
    seed_published,
    set_blocks,
    single_question,
    text_block,
)

import pytest


async def test_preview_renders_the_draft_without_correct_answers(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """LMS-8, LMS-17: the preview shows pending changes, never the answers."""
    owner, tester = course.team.owner, course.team.tester
    seeded = await seed_published(services, owner, course.id)
    await set_blocks(
        services,
        owner,
        seeded.step_b,
        text_block("Draft text"),
        quiz_block(single_question("Secret question?")),
    )

    preview = await services.preview_step.execute(
        tester, course.id, seeded.step_b.step_id
    )

    raw = json.dumps(preview.model_dump(mode="json"))
    assert preview.preview and not preview.completed
    assert preview.title == "Step B"
    assert [b["type"] for b in preview.blocks] == ["text", "test"]
    assert preview.blocks[0]["markdown"] == "Draft text"
    assert preview.blocks[1]["rules"]["questions"] == 1
    assert "Power rule." not in raw
    assert "correct" not in raw and "explanation" not in raw
    assert "Secret question?" not in raw


async def test_preview_needs_view_drafts(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """LMS-5: reviewers and outsiders cannot preview drafts."""
    seeded = await seed_published(services, course.team.owner, course.id)

    for actor in (course.team.reviewer, course.team.outsider):
        with pytest.raises(CoursePermissionError):
            await services.preview_step.execute(actor, course.id, seeded.step_a.step_id)
    with pytest.raises(StepNotFoundError):
        await services.preview_step.execute(course.team.tester, course.id, uuid4())


async def test_a_step_cannot_be_previewed_through_another_course(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """The step must belong to the course in the URL."""
    seeded = await seed_published(services, course.team.owner, course.id)

    with pytest.raises(StepNotFoundError):
        await services.preview_step.execute(
            course.team.admin, uuid4(), seeded.step_a.step_id
        )
    other = await services.create_course.execute(
        course.team.admin,
        title="Other",
        slug="other-course",
        visibility=Visibility.PUBLIC,
    )
    with pytest.raises(StepNotFoundError):
        await services.preview_step.execute(
            course.team.admin, other.id, seeded.step_a.step_id
        )


async def test_preview_revision_freezes_the_current_draft(
    services: AuthoringServices, course: CourseFixture, clock: FixedClock
) -> None:
    """LMS-8: preview attempts point to a `preview` revision of the draft."""
    owner, tester = course.team.owner, course.team.tester
    seeded = await seed_published(services, owner, course.id)
    await set_blocks(services, owner, seeded.step_a, text_block("A2"))

    first = await services.ensure_preview_revision.execute(
        seeded.step_a.step_id, tester
    )
    again = await services.ensure_preview_revision.ensure_preview_revision(
        seeded.step_a.step_id, tester
    )
    step = await services.get_step_draft.execute(owner, seeded.step_a.step_id)
    await set_blocks(services, owner, step, text_block("A3"))
    clock.advance(minutes=1)
    later = await services.ensure_preview_revision.execute(
        seeded.step_a.step_id, tester
    )

    assert first == again
    assert later != first


async def test_preview_revision_needs_view_drafts(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """Only staff with `view_drafts` get a preview revision."""
    seeded = await seed_published(services, course.team.owner, course.id)

    with pytest.raises(CoursePermissionError):
        await services.ensure_preview_revision.execute(
            seeded.step_a.step_id, course.team.reviewer
        )
