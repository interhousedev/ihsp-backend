"""build_course (MCP) puts an uploaded lesson video into a new step, on the real DB."""

import dataclasses
from typing import Any, cast
from uuid import UUID

from app.modules.lms.application.public_course_ops import LmsCourseOpsImpl
from app.modules.lms.domain.authoring.errors import ContentInvalidError
from app.modules.lms.wiring_authoring import AuthoringServices
from app.shared.contracts.files import FilePurpose
from app.shared.contracts.lms_blocks import UploadedVideoBlockInput, build_block
from tests.fakes.lms.files import FakeFilesApi
from tests.lms.authoring.conftest import CourseFixture

import pytest

NOT_USED: Any = None  # learning use cases are not reached by build_course


def _ops(services: AuthoringServices) -> LmsCourseOpsImpl:
    return LmsCourseOpsImpl(
        apply_outline_ops=services.apply_outline_ops,
        apply_course_plan=services.apply_course_plan,
        get_step_draft=services.get_step_draft,
        save_step_draft=services.save_step_draft,
        get_pending_changes=services.get_pending_changes,
        publish_course=services.publish_course,
        restore_version=services.restore_version,
        get_course_settings=services.get_course_settings,
        update_course_settings=services.update_course_settings,
        list_course_staff=services.list_course_staff,
        add_course_staff=services.add_course_staff,
        remove_course_staff=services.remove_course_staff,
        list_course_students=NOT_USED,
        get_attempt=NOT_USED,
        override_score=NOT_USED,
        set_access_rule=services.set_access_rule,
    )


def _plan(file_id: UUID) -> list[dict[str, Any]]:
    video = build_block(UploadedVideoBlockInput(file_id=file_id, caption="Watch"))
    text = {"id": "", "type": "text", "markdown": "Summary"}
    return [
        {"title": "Week 1", "steps": [{"title": "Lesson", "blocks": [text, video]}]}
    ]


def _video_file(files: FakeFilesApi, purpose: FilePurpose) -> UUID:
    ref = dataclasses.replace(files.add_file(), purpose=purpose, name="lesson.mp4")
    files.files[ref.id] = ref
    return ref.id


async def test_an_uploaded_lesson_video_lands_in_the_new_step(
    services: AuthoringServices, course: CourseFixture, files: FakeFilesApi
) -> None:
    """One call creates the section, the step, the text and the upload video."""
    file_id = _video_file(files, FilePurpose.LMS_VIDEO)

    result = await _ops(services).build_course(
        course.team.owner, course.id, _plan(file_id)
    )

    step_id = UUID(str(result["plan"][0]["steps"][0]["step_id"]))
    draft = await services.get_step_draft.execute(course.team.owner, step_id)
    video = cast(Any, draft.content.blocks[1])
    assert video.type == "video"
    assert video.source == "upload"
    assert video.file_id == str(file_id)
    assert draft.updated_via == "mcp"


async def test_a_file_that_is_not_a_lesson_video_is_refused(
    services: AuthoringServices, course: CourseFixture, files: FakeFilesApi
) -> None:
    """A picture cannot play as a lesson video."""
    file_id = _video_file(files, FilePurpose.LINK)

    with pytest.raises(ContentInvalidError):
        await _ops(services).build_course(course.team.owner, course.id, _plan(file_id))
