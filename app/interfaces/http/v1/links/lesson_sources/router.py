"""Routes of lesson sources (admin and staff) and the group "hide EMIS" rule."""

from typing import Annotated, Literal
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.interfaces.http.v1.links.lesson_sources.schemas import (
    EmisSourcesHiddenBody,
    EmisSourcesHiddenResponse,
    LessonSourcePageResponse,
)
from app.shared.actor import Actor, Role

from fastapi import APIRouter, Depends, Query

AdminActor = Annotated[Actor, Depends(require_roles(Role.ADMIN))]
TeacherActor = Annotated[Actor, Depends(require_roles(Role.TEACHER))]
Services = Annotated[Container, Depends(get_container)]
OriginParam = Annotated[Literal["emis", "all"], Query()]
Limit = Annotated[int, Query(ge=1, le=200)]
Offset = Annotated[int, Query(ge=0)]


async def list_admin_lesson_sources(
    subject_id: UUID,
    actor: AdminActor,
    container: Services,
    group_id: UUID | None = None,
    origin: OriginParam = "emis",
    limit: Limit = 50,
    offset: Offset = 0,
) -> LessonSourcePageResponse:
    """Materials of every lesson of the subject (EMIS ones by default)."""
    page = await container.links.list_lesson_sources.execute(
        subject_id,
        teacher_id=None,
        group_id=group_id,
        origin=origin,
        limit=limit,
        offset=offset,
    )
    return LessonSourcePageResponse.from_page(page, limit, offset)


async def list_staff_lesson_sources(
    subject_id: UUID,
    actor: TeacherActor,
    container: Services,
    group_id: UUID | None = None,
    origin: OriginParam = "emis",
    limit: Limit = 50,
    offset: Offset = 0,
) -> LessonSourcePageResponse:
    """Materials of the teacher's own lessons of the subject; 403 if they teach none."""
    page = await container.links.list_lesson_sources.execute(
        subject_id,
        teacher_id=actor.user_id,
        group_id=group_id,
        origin=origin,
        limit=limit,
        offset=offset,
    )
    return LessonSourcePageResponse.from_page(page, limit, offset)


async def get_emis_sources_hidden(
    subject_id: UUID, group_id: UUID, actor: TeacherActor, container: Services
) -> EmisSourcesHiddenResponse:
    """Whether the teacher hides the EMIS sources of the subject for the group."""
    state = await container.links.emis_sources_hiding.get(
        actor.user_id, subject_id, group_id
    )
    return EmisSourcesHiddenResponse.from_state(state)


async def put_emis_sources_hidden(
    subject_id: UUID,
    group_id: UUID,
    body: EmisSourcesHiddenBody,
    actor: TeacherActor,
    container: Services,
) -> EmisSourcesHiddenResponse:
    """Hide (or show again) the EMIS sources of the teacher's lessons for the group."""
    state = await container.links.emis_sources_hiding.set(
        actor.user_id, subject_id, group_id, hidden=body.hidden
    )
    return EmisSourcesHiddenResponse.from_state(state)


router = APIRouter(tags=["lesson-sources"])
router.add_api_route(
    "/v1/admin/subjects/{subject_id}/lesson-sources",
    list_admin_lesson_sources,
    methods=["GET"],
    response_model=LessonSourcePageResponse,
)
router.add_api_route(
    "/v1/staff/subjects/{subject_id}/lesson-sources",
    list_staff_lesson_sources,
    methods=["GET"],
    response_model=LessonSourcePageResponse,
)
HIDDEN = "/v1/staff/subjects/{subject_id}/groups/{group_id}/emis-sources-hidden"
router.add_api_route(
    HIDDEN,
    get_emis_sources_hidden,
    methods=["GET"],
    response_model=EmisSourcesHiddenResponse,
)
router.add_api_route(
    HIDDEN,
    put_emis_sources_hidden,
    methods=["PUT"],
    response_model=EmisSourcesHiddenResponse,
)
