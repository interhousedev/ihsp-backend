"""Routes of course badges: staff editing and the learner views."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.modules.lms.application.badges import (
    BadgeInput,
    BadgeListView,
    BadgeSettingsInput,
    BadgeView,
    MyBadgesView,
    UserBadgesView,
)
from app.modules.lms.domain.badges import IMAGE_MAX_BYTES
from app.shared.actor import Actor

from fastapi import APIRouter, Depends, File, Response, UploadFile

ActorDep = Annotated[Actor, Depends(get_actor)]
ContainerDep = Annotated[Container, Depends(get_container)]

router = APIRouter(prefix="/v1/lms", tags=["lms"])


@router.get("/courses/{course_id}/badges", operation_id="lms_list_course_badges")
async def list_course_badges(
    course_id: UUID, actor: ActorDep, container: ContainerDep
) -> BadgeListView:
    """Return the badges of a course (course staff with `review`)."""
    return await container.lms.badges.list_course(actor, course_id)


@router.post(
    "/courses/{course_id}/badges",
    operation_id="lms_create_course_badge",
    status_code=201,
)
async def create_course_badge(
    course_id: UUID, body: BadgeInput, actor: ActorDep, container: ContainerDep
) -> BadgeView:
    """Create a badge with its design and rule (course staff with `edit`)."""
    return await container.lms.badges.create(actor, course_id, body)


@router.put(
    "/courses/{course_id}/badges/{badge_id}", operation_id="lms_update_course_badge"
)
async def update_course_badge(
    course_id: UUID,
    badge_id: UUID,
    body: BadgeInput,
    actor: ActorDep,
    container: ContainerDep,
) -> BadgeView:
    """Replace a badge; a null `design.image_url` removes the uploaded image."""
    return await container.lms.badges.update(actor, course_id, badge_id, body)


@router.delete(
    "/courses/{course_id}/badges/{badge_id}",
    operation_id="lms_delete_course_badge",
    status_code=204,
)
async def delete_course_badge(
    course_id: UUID, badge_id: UUID, actor: ActorDep, container: ContainerDep
) -> Response:
    """Delete a badge and its awards."""
    await container.lms.badges.delete(actor, course_id, badge_id)
    return Response(status_code=204)


@router.post(
    "/courses/{course_id}/badges/{badge_id}/image",
    operation_id="lms_upload_course_badge_image",
)
async def upload_course_badge_image(
    course_id: UUID,
    badge_id: UUID,
    file: Annotated[UploadFile, File()],
    actor: ActorDep,
    container: ContainerDep,
) -> BadgeView:
    """Upload the badge image: PNG, JPEG or WebP, at most 512 KB."""
    data = await file.read(IMAGE_MAX_BYTES + 1)
    return await container.lms.badges.upload_image(
        actor,
        course_id,
        badge_id,
        name=file.filename or "badge",
        content_type=file.content_type or "",
        data=data,
    )


@router.put(
    "/courses/{course_id}/badge-settings", operation_id="lms_set_course_badge_settings"
)
async def set_course_badge_settings(
    course_id: UUID, body: BadgeSettingsInput, actor: ActorDep, container: ContainerDep
) -> BadgeListView:
    """Choose whether learners see the badges they have not earned yet."""
    return await container.lms.badges.set_settings(actor, course_id, body)


@router.get("/badges/mine", operation_id="lms_my_badges")
async def my_badges(actor: ActorDep, container: ContainerDep) -> MyBadgesView:
    """Return the learner's earned and locked badges and the unseen awards."""
    return await container.lms.badges.mine(actor)


@router.post(
    "/badges/awards/{award_id}/seen",
    operation_id="lms_mark_badge_award_seen",
    status_code=204,
)
async def mark_badge_award_seen(
    award_id: UUID, actor: ActorDep, container: ContainerDep
) -> Response:
    """Record that the learner saw the celebration of an award."""
    await container.lms.badges.mark_seen(actor, award_id)
    return Response(status_code=204)


@router.get("/users/{user_id}/badges", operation_id="lms_user_badges")
async def user_badges(
    user_id: UUID, actor: ActorDep, container: ContainerDep
) -> UserBadgesView:
    """Return a learner's badges in the courses the caller shares with them."""
    return await container.lms.badges.of_user(actor, user_id)
