"""Streaming an uploaded video: enrolled students and staff, nobody else."""

from typing import Any
from uuid import UUID, uuid4

from app.modules.lms.domain.learning.errors import (
    NotEnrolledError,
    VideoNotFoundError,
)
from app.modules.lms.domain.step_content import VideoBlock
from app.modules.lms.wiring_learning import LearningServices, build_learning
from app.shared.actor import Actor, Role
from app.shared.wiring import ModuleDeps
from tests.lms.learning.builders import add_staff, content, seed_course, text_block
from tests.lms.learning.fakes.identity import FakeIdentityDirectory
from tests.lms.learning.fakes.preview_revisions import FakePreviewRevisions

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

FILE_ID = uuid4()


class _Files:
    """Records the presign requests of the files API."""

    def __init__(self) -> None:
        self.calls: list[tuple[UUID, bool | None, int | None]] = []

    async def download_url(
        self,
        file_id: UUID,
        *,
        inline: bool | None = None,
        ttl_seconds: int | None = None,
    ) -> str:
        self.calls.append((file_id, inline, ttl_seconds))
        return f"https://s3.test/{file_id}?X-Amz-Expires={ttl_seconds}"


@pytest.fixture
def files() -> _Files:
    return _Files()


@pytest.fixture
def streaming(
    deps: ModuleDeps,
    identity: FakeIdentityDirectory,
    previews: FakePreviewRevisions,
    files: _Files,
) -> LearningServices:
    """Learning use cases with a fake files API."""
    return build_learning(
        deps,
        identity=identity,
        preview_revisions=previews,
        files=files,  # type: ignore[arg-type]
    )


async def _course(maker: async_sessionmaker[AsyncSession]) -> Any:  # noqa: ANN401
    upload: Any = VideoBlock(id="vid", source="upload", file_id=str(FILE_ID))
    link: Any = VideoBlock(id="link", source="link", url="https://youtu.be/x")
    return await seed_course(
        maker,
        steps=[
            (
                "v",
                content("Video", upload, link, text_block()),
            )
        ],
    )


async def test_an_enrolled_student_gets_a_short_inline_url(
    maker: async_sessionmaker[AsyncSession],
    streaming: LearningServices,
    student: Actor,
    files: _Files,
) -> None:
    """Enrolled: a presigned GET with a short TTL."""
    course = await _course(maker)
    await streaming.enroll_in_course.execute(student, course.id)

    view = await streaming.get_video_stream.execute(
        student, course.id, course.step("v").step_id, "vid"
    )

    assert str(FILE_ID) in view.url
    assert 0 < view.expires_in <= 3600
    assert files.calls == [(FILE_ID, True, view.expires_in)]


async def test_a_student_who_is_not_enrolled_gets_nothing(
    maker: async_sessionmaker[AsyncSession],
    streaming: LearningServices,
    student: Actor,
    files: _Files,
) -> None:
    """Not enrolled and not staff: not-enrolled, and nothing is presigned."""
    course = await _course(maker)

    with pytest.raises(NotEnrolledError):
        await streaming.get_video_stream.execute(
            student, course.id, course.step("v").step_id, "vid"
        )

    assert files.calls == []


async def test_course_staff_can_stream_without_enrolling(
    maker: async_sessionmaker[AsyncSession],
    streaming: LearningServices,
    identity: FakeIdentityDirectory,
    make_teacher: Any,  # noqa: ANN401
) -> None:
    """Staff of the course do not need an enrollment."""
    course = await _course(maker)
    teacher: Actor = make_teacher(identity)
    await add_staff(maker, course, teacher.user_id)

    view = await streaming.get_video_stream.execute(
        teacher, course.id, course.step("v").step_id, "vid"
    )

    assert str(FILE_ID) in view.url


@pytest.mark.parametrize("block_id", ["link", "missing"])
async def test_only_uploaded_video_blocks_stream(
    maker: async_sessionmaker[AsyncSession],
    streaming: LearningServices,
    student: Actor,
    block_id: str,
) -> None:
    """A link block, or a block that does not exist, has no stream."""
    course = await _course(maker)
    await streaming.enroll_in_course.execute(student, course.id)

    with pytest.raises(VideoNotFoundError):
        await streaming.get_video_stream.execute(
            student, course.id, course.step("v").step_id, block_id
        )


@pytest.fixture
def make_teacher(make_actor: Any) -> Any:  # noqa: ANN401
    """Build a teacher actor known to the identity directory."""

    def build(identity: FakeIdentityDirectory) -> Actor:
        user = identity.add(first_name="Tina", last_name="Teacher")
        actor: Actor = make_actor(Role.TEACHER, user_id=user.id)
        return actor

    return build
