"""MCP-B5: revocable media grants over the real tables, with a fake presigner."""

import dataclasses
from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

from app.modules.lms.application.learning.redeem_media_grant import MEDIA_URL_SECONDS
from app.modules.lms.domain.learning.errors import (
    CourseNotFoundError,
    MediaNotAvailableError,
    VideoNotFoundError,
)
from app.modules.lms.domain.step_content import VideoBlock
from app.modules.lms.infrastructure.orm.course import Course
from app.modules.lms.wiring_learning import LearningServices, build_learning
from app.shared.actor import Actor, Role
from app.shared.contracts.identity import UserStatus
from app.shared.notifications import AuditDraft
from app.shared.wiring import ModuleDeps
from tests.fakes.clock import FixedClock
from tests.lms.learning.builders import (
    add_staff,
    content,
    quiz,
    seed_course,
    text_block,
)
from tests.lms.learning.fakes.identity import FakeIdentityDirectory
from tests.lms.learning.fakes.preview_revisions import FakePreviewRevisions

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

FILE_ID = uuid4()
Seed = tuple[Any, UUID]


class _Files:
    async def download_url(
        self,
        file_id: UUID,
        *,
        inline: bool | None = None,
        ttl_seconds: int | None = None,
    ) -> str:
        return f"https://s3.test/{file_id}?ttl={ttl_seconds}"


@pytest.fixture
def audits() -> list[AuditDraft]:
    return []


@pytest.fixture
def media(
    deps: ModuleDeps,
    identity: FakeIdentityDirectory,
    previews: FakePreviewRevisions,
    audits: list[AuditDraft],
) -> LearningServices:
    async def record(_session: Any, drafts: list[AuditDraft]) -> None:  # noqa: ANN401
        audits.extend(drafts)

    return build_learning(
        dataclasses.replace(deps, audit_writer=record),
        identity=identity,
        preview_revisions=previews,
        files=_Files(),  # type: ignore[arg-type]
    )


async def _seed(
    maker: async_sessionmaker[AsyncSession], media: LearningServices, student: Actor
) -> Seed:
    upload: Any = VideoBlock(id="vid", source="upload", file_id=str(FILE_ID))
    link: Any = VideoBlock(id="link", source="link", url="https://youtu.be/x")
    course = await seed_course(
        maker, steps=[("v", content("Video", upload, link, text_block()))]
    )
    await media.enroll_in_course.execute(student, course.id)
    return course, course.step("v").step_id


async def _issue(media: LearningServices, student: Actor, seed: Seed) -> str:
    issued = await media.issue_media_grant.execute(student, seed[0].id, seed[1], "vid")
    assert issued.token is not None
    return issued.token


async def test_anonymous_within_five_hours_then_refused(
    maker: async_sessionmaker[AsyncSession],
    media: LearningServices,
    student: Actor,
    clock: FixedClock,
) -> None:
    """MCP-B5: an anonymous holder has 5 hours and is refused right after."""
    token = await _issue(media, student, await _seed(maker, media, student))
    view = await media.redeem_media_grant.execute(token, None, None)
    assert str(FILE_ID) in view.url
    assert view.expires_in == MEDIA_URL_SECONDS
    assert view.tier == "anon"
    clock.advance(hours=5, seconds=1)
    with pytest.raises(MediaNotAvailableError):
        await media.redeem_media_grant.execute(token, None, None)


async def test_enrolled_viewer_is_unlimited_after_expiry(
    maker: async_sessionmaker[AsyncSession],
    media: LearningServices,
    student: Actor,
    clock: FixedClock,
) -> None:
    """MCP-B5: a signed-in enrolled student keeps access after the 5 hours."""
    token = await _issue(media, student, await _seed(maker, media, student))
    clock.advance(days=30)
    view = await media.redeem_media_grant.execute(token, student, None)
    assert view.tier == "enrolled"


async def test_course_staff_viewer_is_allowed(
    maker: async_sessionmaker[AsyncSession],
    media: LearningServices,
    student: Actor,
    teacher: Actor,
    clock: FixedClock,
) -> None:
    """MCP-B5: course staff read a link like an enrolled student."""
    seed = await _seed(maker, media, student)
    await add_staff(maker, seed[0], teacher.user_id)
    token = await _issue(media, student, seed)
    clock.advance(days=1)
    view = await media.redeem_media_grant.execute(token, teacher, None)
    assert view.tier == "enrolled"


async def test_signed_in_unenrolled_is_denied_within_five_hours(
    maker: async_sessionmaker[AsyncSession],
    media: LearningServices,
    student: Actor,
    other_student: Actor,
    audits: list[AuditDraft],
) -> None:
    """MCP-B5 (D2): signed in and not enrolled is refused even within the window."""
    token = await _issue(media, student, await _seed(maker, media, student))
    with pytest.raises(MediaNotAvailableError):
        await media.redeem_media_grant.execute(token, other_student, "10.0.0.9")
    event = [a for a in audits if a.type == "lms.media_redeemed"][-1]
    assert event.metadata is not None
    assert event.metadata["tier"] == "denied"
    assert event.metadata["reason"] == "signed_in_not_enrolled"
    assert event.ip == "10.0.0.9"
    assert token not in str(event)


async def test_unknown_token_is_the_same_error(
    maker: async_sessionmaker[AsyncSession], media: LearningServices
) -> None:
    """MCP-B5: an unknown token cannot be told from a refused one."""
    with pytest.raises(MediaNotAvailableError) as error:
        await media.redeem_media_grant.execute("nope", None, None)
    assert error.value.code == "lms/media-not-available"
    assert not error.value.params


async def test_reissue_rotates_the_old_token(
    maker: async_sessionmaker[AsyncSession], media: LearningServices, student: Actor
) -> None:
    """MCP-B5: one grant per user and block; a new issue kills the previous link."""
    seed = await _seed(maker, media, student)
    old = await _issue(media, student, seed)
    new = await _issue(media, student, seed)
    assert old != new
    with pytest.raises(MediaNotAvailableError):
        await media.redeem_media_grant.execute(old, None, None)
    assert (await media.redeem_media_grant.execute(new, None, None)).tier == "anon"
    assert len(await media.revoke_media_grants.list_mine(student)) == 1


async def test_revoked_grant_refuses_everyone(
    maker: async_sessionmaker[AsyncSession], media: LearningServices, student: Actor
) -> None:
    """MCP-B5: revoking stops anonymous and enrolled viewers alike."""
    token = await _issue(media, student, await _seed(maker, media, student))
    grant = (await media.revoke_media_grants.list_mine(student))[0]
    await media.revoke_media_grants.revoke(student, grant.id)
    for viewer in (None, student):
        with pytest.raises(MediaNotAvailableError):
            await media.redeem_media_grant.execute(token, viewer, None)


async def test_only_the_issuer_revokes(
    maker: async_sessionmaker[AsyncSession],
    media: LearningServices,
    student: Actor,
    other_student: Actor,
) -> None:
    """MCP-B5: someone else's grant looks missing and stays alive."""
    token = await _issue(media, student, await _seed(maker, media, student))
    grant = (await media.revoke_media_grants.list_mine(student))[0]
    with pytest.raises(MediaNotAvailableError):
        await media.revoke_media_grants.revoke(other_student, grant.id)
    assert await media.revoke_media_grants.list_mine(other_student) == []
    assert (await media.redeem_media_grant.execute(token, None, None)).tier == "anon"


async def test_issuer_blocked_kills_the_link(
    maker: async_sessionmaker[AsyncSession],
    media: LearningServices,
    student: Actor,
    identity: FakeIdentityDirectory,
) -> None:
    """MCP-B5: a link dies with its issuer, no decision is cached."""
    token = await _issue(media, student, await _seed(maker, media, student))
    user = identity.users[student.user_id]
    identity.users[student.user_id] = dataclasses.replace(
        user, status=UserStatus.BLOCKED
    )
    with pytest.raises(MediaNotAvailableError):
        await media.redeem_media_grant.execute(token, None, None)


async def test_issuer_unenrolled_kills_the_link(
    maker: async_sessionmaker[AsyncSession], media: LearningServices, student: Actor
) -> None:
    """MCP-B5: unenrolment of the issuer ends the link."""
    from app.modules.lms.infrastructure.orm.enrollment import Enrollment

    from sqlalchemy import delete

    seed = await _seed(maker, media, student)
    token = await _issue(media, student, seed)
    async with maker() as session:
        await session.execute(
            delete(Enrollment).where(Enrollment.user_id == student.user_id)
        )
        await session.commit()
    with pytest.raises(MediaNotAvailableError):
        await media.redeem_media_grant.execute(token, None, None)


async def test_archived_course_kills_the_link(
    maker: async_sessionmaker[AsyncSession], media: LearningServices, student: Actor
) -> None:
    """MCP-B5: archiving the course ends the link."""
    seed = await _seed(maker, media, student)
    token = await _issue(media, student, seed)
    async with maker() as session:
        await session.execute(
            update(Course).where(Course.id == seed[0].id).values(status="archived")
        )
        await session.commit()
    with pytest.raises(MediaNotAvailableError):
        await media.redeem_media_grant.execute(token, None, None)


async def test_revoked_connector_kills_the_link(
    maker: async_sessionmaker[AsyncSession],
    media: LearningServices,
    make_actor: Callable[..., Actor],
    identity: FakeIdentityDirectory,
) -> None:
    """MCP-B5: revoking the connector that asked for a link ends it."""
    connector = uuid4()
    user = identity.add()
    student = dataclasses.replace(
        make_actor(Role.STUDENT, user_id=user.id), connector_id=connector
    )
    token = await _issue(media, student, await _seed(maker, media, student))
    alive = {connector}

    async def active(connector_id: UUID) -> bool:
        return connector_id in alive

    media.redeem_media_grant.bind_connector_check(active)
    assert (await media.redeem_media_grant.execute(token, None, None)).tier == "anon"
    alive.clear()
    with pytest.raises(MediaNotAvailableError):
        await media.redeem_media_grant.execute(token, None, None)


async def test_not_enrolled_cannot_issue(
    maker: async_sessionmaker[AsyncSession],
    media: LearningServices,
    student: Actor,
    other_student: Actor,
) -> None:
    """MCP-B5: a link is only for those enrolled; others see not found."""
    seed = await _seed(maker, media, student)
    with pytest.raises(CourseNotFoundError):
        await media.issue_media_grant.execute(other_student, seed[0].id, seed[1], "vid")


async def test_link_video_needs_no_grant_and_text_is_refused(
    maker: async_sessionmaker[AsyncSession], media: LearningServices, student: Actor
) -> None:
    """MCP-B5: a linked video returns its address; a text block has no media."""
    seed = await _seed(maker, media, student)
    issued = await media.issue_media_grant.execute(student, seed[0].id, seed[1], "link")
    assert issued.token is None
    assert issued.external_url == "https://youtu.be/x"
    with pytest.raises(VideoNotFoundError):
        await media.issue_media_grant.execute(student, seed[0].id, seed[1], "text")


async def test_step_read_has_no_side_effects_and_no_answers(
    maker: async_sessionmaker[AsyncSession], media: LearningServices, student: Actor
) -> None:
    """MCP-B5: reading a step changes nothing and hides file ids and tokens."""
    seed = await _seed(maker, media, student)
    step = await media.learner_course_reader.step(student, seed[0].id, seed[1])
    assert [block["type"] for block in step["blocks"]] == ["video", "video", "text"]
    assert "file_id" not in str(step)
    state = await media.get_step_view.execute(student, seed[0].id, seed[1])
    assert state.completed is False


async def test_reader_lists_only_enrolled_courses(
    maker: async_sessionmaker[AsyncSession],
    media: LearningServices,
    student: Actor,
    other_student: Actor,
) -> None:
    """MCP-B5: courses, outline and files only for the enrolled."""
    seed = await _seed(maker, media, student)
    reader = media.learner_course_reader
    assert [c["id"] for c in await reader.my_courses(student)] == [seed[0].id]
    assert await reader.my_courses(other_student) == []
    outline = await reader.curriculum(student, seed[0].id)
    assert outline["sections"][0]["steps"][0]["step_id"] == seed[1]
    assert await reader.course_file_ids(student) == [(seed[0].id, FILE_ID)]
    assert await reader.course_file_ids(other_student) == []
    with pytest.raises(CourseNotFoundError):
        await reader.curriculum(other_student, seed[0].id)
    with pytest.raises(CourseNotFoundError):
        await reader.step(other_student, seed[0].id, seed[1])


async def test_abuse_of_anonymous_redeems_revokes_the_grant(
    maker: async_sessionmaker[AsyncSession], media: LearningServices, student: Actor
) -> None:
    """MCP-B5: over the anonymous ceiling a shared link closes itself."""
    from app.modules.lms.application.learning import redeem_media_grant as module
    from app.modules.lms.infrastructure.orm.media_grant import MediaGrant

    token = await _issue(media, student, await _seed(maker, media, student))
    async with maker() as session:
        await session.execute(
            update(MediaGrant).values(redeem_count=module.ANON_REDEEM_CEILING)
        )
        await session.commit()
    with pytest.raises(MediaNotAvailableError):
        await media.redeem_media_grant.execute(token, None, None)
    with pytest.raises(MediaNotAvailableError):
        await media.redeem_media_grant.execute(token, student, None)


async def test_unbound_connector_check_denies_a_connector_link(
    maker: async_sessionmaker[AsyncSession],
    media: LearningServices,
    make_actor: Callable[..., Actor],
    identity: FakeIdentityDirectory,
) -> None:
    """MCP-B5: a process without the check refuses, even an enrolled viewer."""
    user = identity.add()
    student = dataclasses.replace(
        make_actor(Role.STUDENT, user_id=user.id), connector_id=uuid4()
    )
    token = await _issue(media, student, await _seed(maker, media, student))

    with pytest.raises(MediaNotAvailableError):
        await media.redeem_media_grant.execute(token, None, None)
    with pytest.raises(MediaNotAvailableError):
        await media.redeem_media_grant.execute(token, student, None)


async def test_step_read_refuses_a_step_of_another_course(
    maker: async_sessionmaker[AsyncSession], media: LearningServices, student: Actor
) -> None:
    """MCP-B5: enrolment in one course opens no step of another."""
    seed = await _seed(maker, media, student)
    foreign = await seed_course(
        maker, slug="foreign", steps=[("f", content("Foreign", text_block()))]
    )

    with pytest.raises(CourseNotFoundError):
        await media.learner_course_reader.step(
            student, seed[0].id, foreign.step("f").step_id
        )


async def test_step_read_shows_rules_of_a_test_and_never_its_questions(
    maker: async_sessionmaker[AsyncSession], media: LearningServices, student: Actor
) -> None:
    """MCP-B5: prompts, options, right answers and explanations stay out."""
    course = await seed_course(maker, steps=[("t", content("Test", quiz()))])
    await media.enroll_in_course.execute(student, course.id)

    step = await media.learner_course_reader.step(
        student, course.id, course.step("t").step_id
    )

    assert step["blocks"][0]["type"] == "test"
    assert step["blocks"][0]["best_score_pct"] is None
    text = str(step)
    for secret in ("Question q1", "Option a", "q1-a", "correct", "Because."):
        assert secret not in text
